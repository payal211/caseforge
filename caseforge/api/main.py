from typing import Optional

from fastapi import FastAPI, HTTPException
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..core.orchestrator import Orchestrator
from ..demo_attacks import ATTACKS, catalogue, run_attack
from ..packs import load_packs

app = FastAPI(title="CaseForge", version="0.1.0",
              description="Shared multi-agent investigation platform with pluggable domain packs.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
orch = Orchestrator(load_packs())


class NewCase(BaseModel):
    domain: str
    subject_id: str


class DecisionIn(BaseModel):
    reviewer: str
    outcome: str  # approve | reject | override
    note: str = ""
    override_action: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok", "domains": list(orch.packs), "jev": orch.jev.status(), "storage": orch.store.backend, "agentic": orch.agentic,
            "sandbox": {"enabled": orch.sandbox.enabled, "ready": orch.sandbox.status()[0] if orch.sandbox.enabled else False,
                        "detail": orch.sandbox.status()[1]}}


@app.get("/domains")
def domains():
    return [{"name": p.name, "title": p.title, "subjects": p.list_subjects()} for p in orch.packs.values()]


@app.post("/cases")
def create_case(body: NewCase):
    try:
        return orch.investigate(body.domain, body.subject_id)
    except KeyError as e:
        raise HTTPException(404, f"not found: {e}")


@app.get("/cases")
def list_cases():
    return orch.store.list()


@app.get("/cases/{case_id}")
def get_case(case_id: str):
    try:
        return orch.store.get(case_id)
    except KeyError:
        raise HTTPException(404, "case not found")


@app.post("/cases/{case_id}/decision")
def decide(case_id: str, body: DecisionIn):
    try:
        return orch.decide(case_id, body.reviewer, body.outcome, body.note, body.override_action)
    except KeyError:
        raise HTTPException(404, "case not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/cases/{case_id}/audit")
def case_audit(case_id: str):
    return orch.audit.read(case_id)


@app.get("/metrics")
def metrics():
    return orch.metrics()


@app.delete("/demo/reset")
def reset_demo():
    """Clear all cases and the audit log so the demo can be re-run from scratch."""
    n = orch.store.clear()
    orch.audit.clear()
    return {"cleared_cases": n}


@app.get("/demo/attacks")
def demo_attacks():
    return catalogue()


@app.post("/demo/attacks/{attack_id}")
def demo_run_attack(attack_id: str):
    if attack_id not in ATTACKS:
        raise HTTPException(404, "unknown attack")
    return run_attack(orch, attack_id)


app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/ui/")
