"""Agent contract: every step is an Agent with run(state) -> partial state.
Base class adds timing + audit so every pack gets traceability for free."""
import time
from abc import ABC, abstractmethod

import json

from .audit import AuditLog
from .guardrails import (GUARDRAIL_SYSTEM_PROMPT, REDACTED, redact, scan, validate_output,
                         wrap_untrusted)
from .llm import LLM

class Agent(ABC):
    name: str

    def __init__(self, pack, llm: LLM, audit: AuditLog, jev=None, agentic: bool = False, sandbox=None):
        self.pack, self.llm, self.audit, self.jev, self.agentic, self.sandbox = pack, llm, audit, jev, agentic, sandbox

    @abstractmethod
    def run(self, state: dict) -> dict: ...

    def __call__(self, state: dict) -> dict:
        t0 = time.perf_counter()
        out = self.run(state)
        self.audit.log(state["case_id"], f"agent:{self.name}",
                       {"seconds": round(time.perf_counter() - t0, 3), "produced": list(out)})
        return out


class GatherAgent(Agent):
    name = "gather"

    def run(self, state):
        evidence, ctx = self.pack.gather(state["subject_id"])
        return {"evidence": evidence, "ctx": ctx}


class RetrieveAgent(Agent):
    name = "retrieve"

    def run(self, state):
        q = self.pack.policy_query(state["evidence"], state["ctx"])
        return {"citations": self.pack.index.search(q, k=3)}


class GuardAgent(Agent):
    """Scans everything the LLM or customer-facing drafts could see: evidence, retrieved
    documents and record fields. Flagged text is redacted before reasoning and drafting."""
    name = "guard"

    def run(self, state):
        flags, evidence, citations = [], [], []
        for e in state["evidence"]:
            hits = scan(e.detail) + scan(json.dumps(e.raw, default=str))
            if hits:
                flags.append(f"evidence:{e.signal}:{','.join(sorted(set(hits)))}")
                e = e.model_copy(update={"detail": REDACTED, "raw": {}})
            evidence.append(e)
        for c in state["citations"]:
            hits = scan(c.excerpt)
            if hits:
                flags.append(f"source:{c.doc}/{c.section}:{','.join(hits)}")
                c = c.model_copy(update={"excerpt": REDACTED})
            citations.append(c)
        ctx, ctx_flags = redact(state["ctx"])
        flags = flags + ctx_flags
        if self.jev and self.jev.enabled:  # second net: model-based detection of novel phrasings
            citations, ctx, jev_flags = self._jev_scan(citations, ctx)
            flags += jev_flags
        return {"evidence": evidence, "citations": citations, "ctx": ctx, "flags": flags}

    def _jev_scan(self, citations, ctx):
        """Cap calls per case; only long free-text strings can realistically carry a payload."""
        flags, budget, out_c = [], [6], []
        for c in citations:
            if c.excerpt != REDACTED and budget[0] > 0:
                budget[0] -= 1
                p = self.jev.injection_probability(c.excerpt)
                if p is None:
                    return citations, ctx, ["jev_unavailable"]
                if p >= self.jev.injection_threshold:
                    flags.append(f"jev:source:{c.doc}/{c.section}:p={p:.2f}")
                    c = c.model_copy(update={"excerpt": REDACTED})
            out_c.append(c)

        def walk(o, path):
            if isinstance(o, str):
                if o != REDACTED and len(o) >= 25 and budget[0] > 0:
                    budget[0] -= 1
                    p = self.jev.injection_probability(o)
                    if p is None:
                        flags.append("jev_unavailable")
                    elif p >= self.jev.injection_threshold:
                        flags.append(f"jev:{path}:p={p:.2f}")
                        return REDACTED
                return o
            if isinstance(o, dict):
                return {k: walk(v, f"{path}.{k}") for k, v in o.items()}
            if isinstance(o, list):
                return [walk(v, f"{path}[{i}]") for i, v in enumerate(o)]
            return o

        return out_c, walk(ctx, "ctx"), list(dict.fromkeys(flags))


class SecondOpinionAgent(Agent):
    """Advisory only: asks a Jev-compatible model one yes/no question about the sanitized facts.
    A confident disagreement with the deterministic result adds a flag; it never changes the decision."""
    name = "second_opinion"

    def run(self, state):
        if not (self.jev and self.jev.enabled):
            return {}
        an = state["analysis"]
        facts = "; ".join(e.detail for e in state["evidence"] if e.weight > 0) or "No risk signals were triggered."
        p = self.jev.ask_yes_no(facts, self.pack.jev_question)
        flags = list(state.get("flags", []))
        if p is None:
            return {"flags": list(dict.fromkeys(flags + ["jev_unavailable"])), "second_opinion": {"available": False}}
        note = self.jev.disagreement(p, an.risk_score)
        if note:
            flags.append(f"second_opinion_disagrees:p={p:.2f}")
        return {"flags": list(dict.fromkeys(flags)),
                "second_opinion": {"available": True, "model": self.jev.model, "question": self.pack.jev_question,
                                   "p_yes": round(p, 3), "disagrees": bool(note), "note": note}}


class AgentLoopAgent(Agent):
    """Optional agentic investigation: the LLM picks read-only tools inside the harness limits and
    reports grounded notes. Advisory only; the score and action are already fixed by then."""
    name = "agent_loop"

    def run(self, state):
        if not self.agentic:
            return {}
        from ..harness.loop import AgentLoop
        from ..harness.tools import build_toolbox
        goal = (f"Investigate {state['subject_id']} ({self.pack.title}). Use the tools to find facts that "
                "corroborate or contradict the gathered evidence, then submit your findings.")
        data = {"evidence": [{"signal": e.signal, "detail": e.detail, "weight": e.weight} for e in state["evidence"]],
                "record": state["ctx"].get("record", {}), "entity": state["ctx"].get("entity", {})}
        run = AgentLoop(self.llm).run(goal, build_toolbox(self.pack, state["evidence"], self.sandbox, data))
        flags = list(dict.fromkeys(list(state.get("flags", [])) + run["flags"]))
        return {"agent_run": run, "flags": flags}


class ReasonAgent(Agent):
    name = "reason"

    def run(self, state):
        return {"analysis": self.pack.reason(state["evidence"], state["ctx"], state["citations"])}


class DraftAgent(Agent):
    name = "draft"

    def run(self, state):
        p, sid = self.pack, state["subject_id"]
        ev, an, cit = state["evidence"], state["analysis"], state["citations"]
        artifacts = p.draft_artifacts(sid, ev, state["ctx"], an, cit)
        system_extra, prompt = p.narrative_prompt(sid, ev, an, cit)
        text = self.llm.generate(GUARDRAIL_SYSTEM_PROMPT + " " + system_extra, wrap_untrusted(prompt))
        flags = list(state.get("flags", []))
        if text:
            ok, reasons = validate_output(text, an)
            if not ok:
                flags.append("llm_output_rejected:" + ",".join(reasons))
                text = None
        return {"artifacts": artifacts, "flags": flags,
                "summary": text or p.fallback_summary(sid, ev, an, cit),
                "llm_used": text is not None}
