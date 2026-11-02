from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from caseforge.core import config
from caseforge.core.connectors import ParquetConnector, make_connector, write_parquet_from_csv
from caseforge.core.jev import JevClient
from caseforge.core.orchestrator import Orchestrator

config.LLM_MODE = "mock"
PK = Path(__file__).resolve().parent.parent / "caseforge" / "packs"


def packs(monkeypatch, tmp_path, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    from caseforge.packs.bfsi.pack import BfsiPack
    from caseforge.packs.manufacturing.pack import ManufacturingPack
    return {"bfsi": BfsiPack(), "manufacturing": ManufacturingPack()}


def test_parquet_packs_match_csv_exactly(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    csv_orch = Orchestrator(packs(monkeypatch, tmp_path), jev=JevClient(enabled=False))
    for pack, table, src in (("BFSI", "TRANSACTIONS", "bfsi/data/transactions.csv"), ("BFSI", "ACCOUNTS", "bfsi/data/accounts.csv"),
                             ("MANUFACTURING", "SENSORS", "manufacturing/data/sensors.csv")):
        write_parquet_from_csv(PK / src, tmp_path / f"{table}.parquet")
    pq_packs = packs(monkeypatch, tmp_path,
                     CASEFORGE_BFSI_TRANSACTIONS_PARQUET=tmp_path / "TRANSACTIONS.parquet",
                     CASEFORGE_BFSI_ACCOUNTS_PARQUET=tmp_path / "ACCOUNTS.parquet",
                     CASEFORGE_MANUFACTURING_SENSORS_PARQUET=tmp_path / "SENSORS.parquet")
    assert isinstance(pq_packs["bfsi"].txns, ParquetConnector)
    pq_orch = Orchestrator(pq_packs, jev=JevClient(enabled=False))
    for dom, p in csv_orch.packs.items():
        for s in p.list_subjects():
            a, b = csv_orch.investigate(dom, s["subject_id"]), pq_orch.investigate(dom, s["subject_id"])
            assert (a.risk_score, a.recommended_action) == (b.risk_score, b.recommended_action), s
            assert a.artifacts == b.artifacts


def test_normalisation_of_native_parquet_types(tmp_path):
    from datetime import datetime
    pq.write_table(pa.table({"ts": [datetime(2026, 9, 2, 2, 14)], "amount": [185000.0], "n": [1], "s": [None]}), tmp_path / "t.parquet")
    row = ParquetConnector(tmp_path / "t.parquet").rows()[0]
    assert row == {"ts": "2026-09-02T02:14:00", "amount": "185000.0", "n": "1", "s": ""}


def test_directory_dataset_and_guards(tmp_path):
    for i in range(2):
        pq.write_table(pa.table({"a": [i, i + 10]}), tmp_path / f"part{i}.parquet")
    assert len(ParquetConnector(tmp_path).rows()) == 4
    with pytest.raises(ValueError):
        ParquetConnector(tmp_path, max_rows=3).rows()
    with pytest.raises(FileNotFoundError):
        ParquetConnector(tmp_path / "missing.parquet").rows()


def test_priority_sql_then_rest_then_parquet(monkeypatch, tmp_path):
    from caseforge.core.connectors import CsvConnector, HttpConnector, SqlConnector
    csv = tmp_path / "x.csv"
    monkeypatch.setenv("CASEFORGE_BFSI_TRANSACTIONS_PARQUET", str(tmp_path / "t.parquet"))
    assert isinstance(make_connector("bfsi", "transactions", csv), ParquetConnector)
    monkeypatch.setenv("CASEFORGE_BFSI_TRANSACTIONS_URL", "https://x.example/t")
    assert isinstance(make_connector("bfsi", "transactions", csv), HttpConnector)
    monkeypatch.setenv("CASEFORGE_BFSI_DB_URL", "sqlite://")
    assert isinstance(make_connector("bfsi", "transactions", csv), SqlConnector)
    for k in ("CASEFORGE_BFSI_TRANSACTIONS_PARQUET", "CASEFORGE_BFSI_TRANSACTIONS_URL", "CASEFORGE_BFSI_DB_URL"):
        monkeypatch.delenv(k)
    assert isinstance(make_connector("bfsi", "transactions", csv), CsvConnector)
