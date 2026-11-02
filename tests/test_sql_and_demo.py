import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from caseforge.core import config
from caseforge.core.connectors import SqlConnector, load_csv_into_sqlite
from caseforge.core.orchestrator import Orchestrator
from caseforge.demo_attacks import ATTACKS, run_attack

config.LLM_MODE = "mock"
PK = Path(__file__).resolve().parent.parent / "caseforge" / "packs"


@pytest.fixture()
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return tmp_path


def _fresh_packs():
    from caseforge.packs.bfsi.pack import BfsiPack
    from caseforge.packs.manufacturing.pack import ManufacturingPack
    return {"bfsi": BfsiPack(), "manufacturing": ManufacturingPack()}


def test_sql_packs_match_csv_packs_exactly(tmp_data, monkeypatch):
    db = tmp_data / "demo.db"
    load_csv_into_sqlite(PK / "bfsi/data/transactions.csv", db, "transactions")
    load_csv_into_sqlite(PK / "bfsi/data/accounts.csv", db, "accounts")
    load_csv_into_sqlite(PK / "manufacturing/data/sensors.csv", db, "sensors")
    csv_orch = Orchestrator(_fresh_packs())
    monkeypatch.setenv("CASEFORGE_BFSI_DB_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("CASEFORGE_MANUFACTURING_DB_URL", f"sqlite:///{db.as_posix()}")
    sql_packs = _fresh_packs()
    assert isinstance(sql_packs["bfsi"].txns, SqlConnector)
    sql_orch = Orchestrator(sql_packs)
    for dom, p in csv_orch.packs.items():
        for s in p.list_subjects():
            a = csv_orch.investigate(dom, s["subject_id"])
            b = sql_orch.investigate(dom, s["subject_id"])
            assert (a.risk_score, a.recommended_action) == (b.risk_score, b.recommended_action), s
            assert a.artifacts == b.artifacts


def test_sql_rows_are_normalised_to_strings(tmp_data):
    db = tmp_data / "x.db"
    load_csv_into_sqlite(PK / "bfsi/data/accounts.csv", db, "accounts")
    rows = SqlConnector(f"sqlite:///{db.as_posix()}", "accounts").rows()
    assert rows and all(isinstance(v, str) for v in rows[0].values())


@pytest.mark.parametrize("bad", ["accounts; DROP TABLE accounts", "a b", "x'--", "1abc", ""])
def test_sql_connector_rejects_unsafe_identifiers(bad):
    with pytest.raises(ValueError):
        SqlConnector("sqlite://", bad)
    with pytest.raises(ValueError):
        SqlConnector("sqlite://", "accounts", order_by=bad)


@pytest.mark.parametrize("attack_id", list(ATTACKS))
def test_every_demo_attack_is_contained(tmp_data, attack_id):
    from caseforge.packs import load_packs
    o = Orchestrator(load_packs())
    before = o.investigate(ATTACKS[attack_id]["domain"], ATTACKS[attack_id]["subject"])
    r = run_attack(o, attack_id)
    assert r["same_decision"] and r["flags"] and r["status"] == "pending_approval"
    assert r["attacked"]["risk_score"] == before.risk_score
    assert len(o.store.list()) == 2  # the earlier real case + the attacked case; dry run left nothing
    again = o.investigate(ATTACKS[attack_id]["domain"], ATTACKS[attack_id]["subject"])
    assert again.guardrail_flags == []  # data was restored after the attack


def test_demo_attack_api(tmp_data):
    from caseforge.api.main import app
    c = TestClient(app)
    assert len(c.get("/demo/attacks").json()) == len(ATTACKS)
    r = c.post("/demo/attacks/merchant_injection").json()
    assert r["same_decision"] and r["flags"]
    assert c.get(f"/cases/{r['case_id']}").json()["guardrail_flags"]
    assert c.post("/demo/attacks/nope").status_code == 404


def test_react_console_is_served(tmp_data):
    from caseforge.api.main import app
    c = TestClient(app)
    html = c.get("/ui/").text
    assert '<div id="root">' in html and "/ui/assets/" in html
    asset = html.split('src="')[1].split('"')[0]
    assert c.get(asset).status_code == 200
    assert c.get("/", follow_redirects=True).status_code == 200
