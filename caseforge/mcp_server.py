"""MCP server: exposes CaseForge investigations to any MCP client (Claude Desktop, IDE agents).
Run: python -m caseforge.mcp_server   (stdio)

Deliberate design: there is NO approve/reject tool. An agent can investigate and read cases,
but only a human using the approval console / API can decide. Tool output is data, not authority."""
from mcp.server.mcpserver import MCPServer

from .core.orchestrator import Orchestrator
from .packs import load_packs

mcp = MCPServer(
    "caseforge",
    instructions=("Investigate fraud disputes and machine-health cases. Every result is a recommendation "
                  "that requires human approval; this server cannot approve or execute actions."),
)
orch = Orchestrator(load_packs())


def _brief(case) -> dict:
    return {
        "case_id": case.case_id, "domain": case.domain, "subject_id": case.subject_id,
        "status": case.status.value, "risk_score": case.risk_score,
        "recommended_action": case.recommended_action, "summary": case.summary,
        "reasoning": case.reasoning,
        "sources": [f"{c.doc} / {c.section}" for c in case.citations],
        "artifacts": case.artifacts, "guardrail_flags": case.guardrail_flags,
        "requires_human_approval": case.status.value == "pending_approval",
    }


@mcp.tool()
def list_domains() -> list[dict]:
    """List available investigation domains and their case subjects."""
    return [{"domain": p.name, "title": p.title, "subjects": p.list_subjects()} for p in orch.packs.values()]


@mcp.tool()
def investigate_case(domain: str, subject_id: str) -> dict:
    """Run the multi-agent investigation and return the case file (always pending human approval)."""
    try:
        return _brief(orch.investigate(domain, subject_id))
    except KeyError as e:
        raise ValueError(f"Unknown domain or subject: {e}")


@mcp.tool()
def get_case(case_id: str) -> dict:
    """Fetch an existing case file, including the human decision if one was made."""
    try:
        case = orch.store.get(case_id)
    except KeyError:
        raise ValueError(f"Case not found: {case_id}")
    out = _brief(case)
    out["decision"] = case.decision.model_dump(mode="json") if case.decision else None
    return out


@mcp.tool()
def list_cases() -> list[dict]:
    """List all cases with status and risk, newest first."""
    return [{"case_id": c.case_id, "domain": c.domain, "subject_id": c.subject_id,
             "status": c.status.value, "risk_score": c.risk_score} for c in orch.store.list()]


@mcp.tool()
def get_audit_trail(case_id: str) -> list[dict]:
    """Return the audit log (agent steps, guardrail flags, human decision) for a case."""
    return orch.audit.read(case_id)


@mcp.tool()
def get_metrics() -> dict:
    """Return productivity metrics (manual baselines are assumptions)."""
    return orch.metrics()


def main():
    mcp.run()


if __name__ == "__main__":
    main()
