import os

import pytest

os.environ["LLM_MODE"] = "mock"

from caseforge.core import config  # noqa: E402

config.LLM_MODE = "mock"


@pytest.fixture()
def orch(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from caseforge.core.orchestrator import Orchestrator
    from caseforge.packs import load_packs
    return Orchestrator(load_packs())


def test_packs_discovered(orch):
    assert {"bfsi", "manufacturing"} <= set(orch.packs)


def test_bfsi_fraud_scores_high(orch):
    c = orch.investigate("bfsi", "TXN-9001")
    assert c.risk_score >= 70 and "block card" in c.recommended_action
    assert any(x.signal == "shared_device" and x.weight > 0 for x in c.evidence)
    assert c.citations and c.status.value == "pending_approval"


def test_bfsi_legit_scores_low(orch):
    c = orch.investigate("bfsi", "TXN-9002")
    assert c.risk_score < 40 and "Decline" in c.recommended_action


def test_bfsi_traveller_escalates(orch):
    c = orch.investigate("bfsi", "TXN-9003")
    assert 40 <= c.risk_score < 70


def test_mfg_bearing_root_cause_and_work_order(orch):
    c = orch.investigate("manufacturing", "PUMP-07")
    assert c.risk_score >= 70
    wo = c.artifacts["work_order"]
    assert wo["suspected_cause"] == "Bearing wear" and wo["priority"] == "P1"
    assert any(p["part_no"] == "BRG-6205-2RS" for p in c.artifacts["parts_request"])


def test_mfg_healthy_and_seal(orch):
    assert orch.investigate("manufacturing", "PUMP-03").risk_score < 40
    seal = orch.investigate("manufacturing", "COMP-02")
    assert seal.artifacts["work_order"]["suspected_cause"] == "Seal leak and pressure loss"


def test_human_approval_flow_and_audit(orch):
    c = orch.investigate("bfsi", "TXN-9001")
    d = orch.decide(c.case_id, "payal", "approve", "looks right")
    assert d.status.value == "approved" and d.decision.final_action == c.recommended_action
    with pytest.raises(ValueError):
        orch.decide(c.case_id, "payal", "approve")
    events = [e["event"] for e in orch.audit.read(c.case_id)]
    assert "human_decision" in events and "agent:gather" in events


def test_override_requires_action(orch):
    c = orch.investigate("bfsi", "TXN-9002")
    with pytest.raises(ValueError):
        orch.decide(c.case_id, "payal", "override")
    assert orch.decide(c.case_id, "payal", "override", override_action="Escalate").status.value == "overridden"


def test_unknown_subject(orch):
    with pytest.raises(KeyError):
        orch.investigate("bfsi", "NOPE")
