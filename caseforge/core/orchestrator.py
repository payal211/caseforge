import os
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import config
from .agents import (AgentLoopAgent, DraftAgent, GatherAgent, GuardAgent, ReasonAgent, RetrieveAgent,
                     SecondOpinionAgent)
from .jev import JevClient
from .audit import AuditLog, make_audit
from .llm import LLM
from .schema import CaseFile, Decision, Status
from .store import CaseStore, make_store


class State(TypedDict, total=False):
    case_id: str
    domain: str
    subject_id: str
    evidence: list
    ctx: dict
    citations: list
    analysis: Any
    artifacts: dict
    summary: str
    llm_used: bool
    flags: list
    second_opinion: dict
    agent_run: dict


class Orchestrator:
    def __init__(self, packs: dict, store: CaseStore | None = None,
                 audit: AuditLog | None = None, llm: LLM | None = None, jev: JevClient | None = None, agentic: bool | None = None, sandbox=None):
        self.packs = packs
        self.store = store or make_store()
        self.audit = audit or make_audit()
        from ..harness.sandbox import Sandbox
        self.sandbox = sandbox if sandbox is not None else Sandbox.from_env()
        self.llm = llm or LLM()
        self.jev = jev if jev is not None else JevClient.from_env()
        self.agentic = agentic if agentic is not None else os.getenv("CASEFORGE_AGENTIC", "off").lower() in {"on", "1", "true"}

    def _graph(self, pack):
        a = (pack, self.llm, self.audit, self.jev, self.agentic, self.sandbox)
        agents = [GatherAgent(*a), RetrieveAgent(*a), GuardAgent(*a), ReasonAgent(*a),
                  SecondOpinionAgent(*a), AgentLoopAgent(*a), DraftAgent(*a)]
        g = StateGraph(State)
        for a in agents:
            g.add_node(a.name, a)
        g.add_edge(START, agents[0].name)
        for a, b in zip(agents, agents[1:]):
            g.add_edge(a.name, b.name)
        g.add_edge(agents[-1].name, END)
        return g.compile()

    def investigate(self, domain: str, subject_id: str) -> CaseFile:
        if domain not in self.packs:
            raise KeyError(f"unknown domain: {domain}")
        pack = self.packs[domain]
        case_id = "CASE-" + uuid.uuid4().hex[:8].upper()
        self.audit.log(case_id, "investigation_started", {"domain": domain, "subject_id": subject_id})
        t0 = time.perf_counter()
        out = self._graph(pack).invoke({"case_id": case_id, "domain": domain, "subject_id": subject_id})
        an = out["analysis"]
        flags = out.get("flags", [])
        reasoning = list(an.reasoning)
        if flags:
            reasoning.append("Guardrail: untrusted or suspicious content was detected and handled "
                             f"({len(flags)} flag(s)). It did not affect the score or action; a human must decide.")
        case = CaseFile(
            case_id=case_id, domain=domain, subject_id=subject_id,
            risk_score=an.risk_score, recommended_action=an.action, reasoning=reasoning, guardrail_flags=flags, second_opinion=out.get("second_opinion"), agent_run=out.get("agent_run"),
            summary=out["summary"], evidence=out["evidence"], citations=out["citations"],
            artifacts=out["artifacts"], llm_used=out["llm_used"],
            investigation_seconds=round(time.perf_counter() - t0, 2),
        )
        self.store.save(case)
        if flags:
            self.audit.log(case_id, "guardrail_flags", {"flags": flags})
        self.audit.log(case_id, "awaiting_human_approval", {"recommended_action": case.recommended_action})
        return case

    def decide(self, case_id: str, reviewer: str, outcome: str, note: str = "",
               override_action: str | None = None) -> CaseFile:
        case = self.store.get(case_id)
        if case.status != Status.PENDING_APPROVAL:
            raise ValueError(f"case already {case.status.value}")
        if outcome not in {"approve", "reject", "override"}:
            raise ValueError("outcome must be approve, reject or override")
        if outcome == "override" and not override_action:
            raise ValueError("override requires override_action")
        final = {"approve": case.recommended_action, "reject": "No action taken",
                 "override": override_action}[outcome]
        case.decision = Decision(reviewer=reviewer, outcome=outcome, final_action=final or "", note=note)
        case.status = {"approve": Status.APPROVED, "reject": Status.REJECTED,
                       "override": Status.OVERRIDDEN}[outcome]
        self.store.save_decision(case, Status.PENDING_APPROVAL)  # atomic: only one decision can win
        self.audit.log(case_id, "human_decision", case.decision.model_dump(mode="json"))
        return case

    def metrics(self) -> dict:
        cases = self.store.list()
        by_domain: dict[str, dict] = {}
        for c in cases:
            d = by_domain.setdefault(c.domain, {"cases": 0, "agent_seconds": 0.0, "approved": 0,
                                                "overridden": 0, "rejected": 0})
            d["cases"] += 1
            d["agent_seconds"] += c.investigation_seconds
            if c.status == Status.APPROVED: d["approved"] += 1
            if c.status == Status.OVERRIDDEN: d["overridden"] += 1
            if c.status == Status.REJECTED: d["rejected"] += 1
        for name, d in by_domain.items():
            base = self.packs[name].baseline_manual_minutes
            avg_agent_min = d["agent_seconds"] / d["cases"] / 60
            with_ai = avg_agent_min + config.REVIEW_MINUTES
            d["avg_agent_seconds"] = round(d["agent_seconds"] / d["cases"], 1)
            d["assumed_manual_minutes"] = base
            d["assumed_review_minutes"] = config.REVIEW_MINUTES
            d["est_minutes_saved_per_case"] = round(base - with_ai, 1)
            d["est_reduction_pct"] = round(100 * (base - with_ai) / base, 1)
            del d["agent_seconds"]
        return {"note": "Manual/review minutes are assumptions; replace with measured values.",
                "by_domain": by_domain}
