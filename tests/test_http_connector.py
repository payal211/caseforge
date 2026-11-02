import httpx
import pytest

from caseforge.core import config
from caseforge.core.connectors import HttpConnector, make_connector
from caseforge.core.jev import JevClient
from caseforge.core.orchestrator import Orchestrator

config.LLM_MODE = "mock"
import csv  # noqa: E402
from pathlib import Path  # noqa: E402

PK = Path(__file__).resolve().parent.parent / "caseforge" / "packs"


def typed_rows(path):
    def conv(v):
        for f in (int, float):
            try:
                return f(v)
            except ValueError:
                pass
        return v
    return [{k: conv(v) for k, v in r.items()} for r in csv.DictReader(open(path, newline="", encoding="utf-8"))]


def test_rest_packs_match_csv_and_send_bearer_token(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    seen = []
    data = {"/transactions": typed_rows(PK / "bfsi/data/transactions.csv"),
            "/accounts": {"records": typed_rows(PK / "bfsi/data/accounts.csv")}}

    def handler(req):
        seen.append((req.url.path, req.headers.get("authorization")))
        return httpx.Response(200, json=data[req.url.path])

    from caseforge.packs.bfsi.pack import BfsiPack
    csv_pack = BfsiPack()
    pack = BfsiPack()
    pack.txns = HttpConnector("https://core.example/transactions", token="s3cret", transport=httpx.MockTransport(handler))
    pack.accounts = HttpConnector("https://core.example/accounts", token="s3cret", records_key="records",
                                  transport=httpx.MockTransport(handler))
    a, b = (Orchestrator({"bfsi": p}, jev=JevClient(enabled=False)) for p in (csv_pack, pack))
    for s in pack.list_subjects():
        x, y = a.investigate("bfsi", s["subject_id"]), b.investigate("bfsi", s["subject_id"])
        assert (x.risk_score, x.recommended_action) == (y.risk_score, y.recommended_action)
    assert seen and all(tok == "Bearer s3cret" for _, tok in seen)


def test_bad_responses_are_rejected():
    for payload in ({"oops": 1}, [1, 2], "text"):
        c = HttpConnector("https://x.example/a", transport=httpx.MockTransport(lambda r, p=payload: httpx.Response(200, json=p)))
        with pytest.raises(ValueError):
            c.rows()
    c = HttpConnector("https://x.example/a", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        c.rows()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x/y", "javascript:alert(1)", "//x"])
def test_only_http_schemes_allowed(url):
    with pytest.raises(ValueError):
        HttpConnector(url)


def test_env_selects_rest_connector_with_sql_taking_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("CASEFORGE_BFSI_TRANSACTIONS_URL", "https://core.example/tx")
    assert isinstance(make_connector("bfsi", "transactions", tmp_path / "x.csv"), HttpConnector)
    monkeypatch.setenv("CASEFORGE_BFSI_DB_URL", "sqlite://")
    from caseforge.core.connectors import SqlConnector
    assert isinstance(make_connector("bfsi", "transactions", tmp_path / "x.csv"), SqlConnector)
