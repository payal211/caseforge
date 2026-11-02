"""Case storage and audit log: files vs SQLite vs PostgreSQL (set TEST_POSTGRES_URL to include Postgres)."""
import os
import threading

import pytest
from sqlalchemy import text

from caseforge.core import config
from caseforge.core.audit import AuditLog, SqlAuditLog
from caseforge.core.jev import JevClient
from caseforge.core.orchestrator import Orchestrator
from caseforge.core.store import CaseStore, SqlCaseStore
from caseforge.packs import load_packs

config.LLM_MODE = "mock"
PG = os.getenv("TEST_POSTGRES_URL")
BACKENDS = ["files", "sqlite"] + (["postgres"] if PG else [])


@pytest.fixture(params=BACKENDS)
def backend(request, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    if request.param == "files":
        mk = lambda: (CaseStore(), AuditLog())
    else:
        url = PG if request.param == "postgres" else f"sqlite:///{tmp_path.as_posix()}/t.db"
        mk = lambda: (SqlCaseStore(url), SqlAuditLog(url))
    store, audit = mk()
    store.clear(); audit.clear()
    yield request.param, mk
    store, audit = mk()
    store.clear(); audit.clear()


def orch_for(store, audit):
    return Orchestrator(load_packs(), store=store, audit=audit, jev=JevClient(enabled=False))


def test_full_case_roundtrip_is_lossless(backend):
    store, audit = backend[1]()
    o = orch_for(store, audit)
    c = o.investigate("manufacturing", "PUMP-07")
    back = store.get(c.case_id)
    assert back == c
    assert back.artifacts["work_order"]["suspected_cause"] == "Bearing wear"
    assert [x.case_id for x in store.list()][0] == c.case_id
    with pytest.raises(KeyError):
        store.get("CASE-NOPE")


def test_investigate_and_decide_with_audit_trail(backend):
    store, audit = backend[1]()
    o = orch_for(store, audit)
    c = o.investigate("bfsi", "TXN-9001")
    d = o.decide(c.case_id, "payal", "approve", "ok")
    assert d.status.value == "approved"
    events = [e["event"] for e in audit.read(c.case_id)]
    assert events[0] == "investigation_started" and "awaiting_human_approval" in events and events[-1] == "human_decision"
    assert o.metrics()["by_domain"]["bfsi"]["approved"] == 1


def test_data_survives_a_restart(backend):
    store, audit = backend[1]()
    c = orch_for(store, audit).investigate("bfsi", "TXN-9002")
    store2, audit2 = backend[1]()  # new objects, same storage
    assert store2.get(c.case_id).subject_id == "TXN-9002" and audit2.read(c.case_id)


def test_second_decision_is_refused(backend):
    store, audit = backend[1]()
    o = orch_for(store, audit)
    c = o.investigate("bfsi", "TXN-9001")
    o.decide(c.case_id, "a", "approve")
    with pytest.raises(ValueError):
        o.decide(c.case_id, "b", "reject")
    assert store.get(c.case_id).decision.reviewer == "a"


@pytest.mark.skipif(not PG, reason="needs PostgreSQL")
def test_concurrent_reviewers_exactly_one_wins_on_postgres(backend):
    if backend[0] != "postgres":
        pytest.skip("postgres only")
    store, audit = backend[1]()
    o = orch_for(store, audit)
    c = o.investigate("bfsi", "TXN-9001")
    results, barrier = [], threading.Barrier(8)

    def reviewer(i):
        barrier.wait()
        try:
            o.decide(c.case_id, f"r{i}", "approve")
            results.append("ok")
        except ValueError:
            results.append("refused")

    ts = [threading.Thread(target=reviewer, args=(i,)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert results.count("ok") == 1 and results.count("refused") == 7


def test_concurrent_reviewers_files_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    o = orch_for(CaseStore(), AuditLog())
    c = o.investigate("bfsi", "TXN-9001")
    results, barrier = [], threading.Barrier(6)

    def reviewer(i):
        barrier.wait()
        try:
            o.decide(c.case_id, f"r{i}", "approve"); results.append("ok")
        except ValueError:
            results.append("refused")

    ts = [threading.Thread(target=reviewer, args=(i,)) for i in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert results.count("ok") == 1


def test_clear_resets_everything(backend):
    store, audit = backend[1]()
    orch_for(store, audit).investigate("bfsi", "TXN-9001")
    assert store.clear() == 1 and store.list() == []
    audit.clear()
    assert audit.read() == []


@pytest.mark.skipif(not PG, reason="needs PostgreSQL")
def test_postgres_uses_jsonb_and_indexes(backend):
    if backend[0] != "postgres":
        pytest.skip("postgres only")
    store, _ = backend[1]()
    with store.engine.connect() as conn:
        typ = conn.execute(text("select data_type from information_schema.columns "
                                "where table_name='cases' and column_name='doc'")).scalar()
        idx = {r[0] for r in conn.execute(text("select indexname from pg_indexes where tablename='cases'"))}
    assert typ == "jsonb" and {"ix_cases_status", "ix_cases_created_at", "ix_cases_domain_subject"} <= idx
