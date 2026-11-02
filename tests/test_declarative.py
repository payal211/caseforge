import copy
import shutil
from pathlib import Path

import pytest
import yaml

from caseforge.core import config
from caseforge.core.jev import JevClient
from caseforge.core.orchestrator import Orchestrator
from caseforge.harness.__main__ import main as cli
from caseforge.harness.checks import check_pack
from caseforge.harness.declarative import DeclarativePack, validate_spec
from caseforge.harness.scaffold import new_pack
from caseforge.packs import load_packs

config.LLM_MODE = "mock"
CLAIMS = Path(__file__).resolve().parent.parent / "caseforge" / "packs" / "claims"


@pytest.fixture()
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return tmp_path


def test_yaml_only_industry_pack_is_discovered_and_investigates(tmp_data):
    packs = load_packs()
    assert {"bfsi", "manufacturing", "claims"} <= set(packs)
    o = Orchestrator(packs, jev=JevClient(enabled=False))
    fraud = o.investigate("claims", "CLM-9001")
    assert fraud.risk_score >= 70 and "special investigations" in fraud.recommended_action
    assert {e.signal for e in fraud.evidence if e.weight > 0} >= {"shared_bank_account", "new_provider", "claim_burst"}
    assert fraud.citations and "verification" in fraud.artifacts["claimant_message_draft"]
    assert 40 <= o.investigate("claims", "CLM-9003").risk_score < 70
    assert o.investigate("claims", "CLM-9002").risk_score < 40
    assert fraud.status.value == "pending_approval"


def test_every_harness_feature_works_for_a_pack_with_no_python(tmp_data):
    from caseforge.harness.loop import AgentLoop
    from caseforge.harness.tools import build_toolbox
    pack = load_packs()["claims"]
    o = Orchestrator(load_packs(), jev=JevClient(enabled=False))
    c = o.investigate("claims", "CLM-9001")
    assert o.decide(c.case_id, "payal", "approve").status.value == "approved"
    assert any(e["event"] == "human_decision" for e in o.audit.read(c.case_id))
    tb = build_toolbox(pack, c.evidence)
    rows = tb.call("lookup", {"source": "records", "field": "bank_account", "value": "ACCT-FRAUD"})
    assert rows.ok and "POL-104" in rows.text
    assert not tb.call("lookup", {"source": "records", "field": "amount", "value": "1"}).ok


def test_unknown_subject_is_a_clean_error(tmp_data):
    with pytest.raises(KeyError):
        Orchestrator(load_packs(), jev=JevClient(enabled=False)).investigate("claims", "NOPE")


def _spec():
    return yaml.safe_load((CLAIMS / "pack.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("mutate,expect", [
    (lambda s: s.pop("actions"), "missing required key 'actions'"),
    (lambda s: s["signals"][0].update(type="magic"), "unknown type"),
    (lambda s: s["signals"][2].pop("weight"), "missing 'weight'"),
    (lambda s: s["signals"][1].update(op="~="), "op must be"),
    (lambda s: s["signals"][2].update(weight=500), "between 0 and 100"),
    (lambda s: s["signals"][3].update(name="new_provider"), "unique name"),
    (lambda s: s["actions"].pop(), "min: 0"),
    (lambda s: s["sources"]["records"].update(file="nope.csv"), "data file not found"),
])
def test_spec_validation_catches_mistakes(mutate, expect):
    spec = copy.deepcopy(_spec())
    mutate(spec)
    assert any(expect in e for e in validate_spec(spec, CLAIMS)), validate_spec(spec, CLAIMS)


def test_invalid_pack_refuses_to_load(tmp_path):
    shutil.copytree(CLAIMS, tmp_path / "bad")
    (tmp_path / "bad" / "pack.yaml").write_text("name: bad\n")
    with pytest.raises(ValueError):
        DeclarativePack.from_dir(tmp_path / "bad")


def test_scaffold_creates_a_pack_that_passes_check_pack_out_of_the_box(tmp_path, tmp_data):
    root = new_pack("retail_returns", base=tmp_path)
    res = check_pack(root)
    assert all(r["pass"] for r in res), [r for r in res if not r["pass"]]
    assert any("injection" in r["name"] for r in res) and any("REC-9001" in r["name"] for r in res)
    with pytest.raises(FileExistsError):
        new_pack("retail_returns", base=tmp_path)
    for bad in ("Bad Name", "../x", "1abc", "a"):
        with pytest.raises(ValueError):
            new_pack(bad, base=tmp_path)


def test_check_pack_reports_broken_data(tmp_path, tmp_data):
    root = new_pack("broken", base=tmp_path)
    (root / "data" / "records.csv").write_text("record_id,entity_id,ts\nREC-9001,E,2026-09-01T10:00:00\n")
    res = check_pack(root)
    assert not all(r["pass"] for r in res)
    assert any("column" in r["name"] and not r["pass"] for r in res)


def test_cli_check_pack_exit_codes(tmp_data, capsys):
    assert cli(["check-pack", str(CLAIMS)]) == 0
    assert cli(["check-pack", "does_not_exist"]) == 1
    assert cli([]) == 2
