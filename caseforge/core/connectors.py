import csv
from pathlib import Path
from typing import Protocol


class Connector(Protocol):
    def rows(self) -> list[dict]: ...


class CsvConnector:
    """Simplest connector. Add SqlConnector / KafkaConnector with the same
    rows() method and packs work unchanged."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._cache: list[dict] | None = None

    def rows(self) -> list[dict]:
        if self._cache is None:
            with open(self.path, newline="", encoding="utf-8") as f:
                self._cache = list(csv.DictReader(f))
        return self._cache


# ---------------------------------------------------------------- SQL
import os
import re
import sqlite3
from datetime import date, datetime

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _norm(v) -> str:
    """Normalise DB values to the string contract CsvConnector uses, so packs never care."""
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


class SqlConnector:
    """Read-only SQL source (Postgres, MySQL, SQL Server, SQLite: anything SQLAlchemy supports).
    Only `SELECT * FROM <table>` is ever issued; table/order_by are validated identifiers, never
    user input. Use a read-only database user in production."""

    def __init__(self, url: str, table: str, order_by: str | None = None):
        for ident in (table, order_by):
            if ident is not None and not _IDENT.match(ident):
                raise ValueError(f"invalid SQL identifier: {ident!r}")
        self.url, self.table, self.order_by = url, table, order_by
        self._cache: list[dict] | None = None

    def rows(self) -> list[dict]:
        if self._cache is None:
            from sqlalchemy import create_engine, text
            q = f"SELECT * FROM {self.table}" + (f" ORDER BY {self.order_by}" if self.order_by else "")
            engine = create_engine(self.url)
            try:
                with engine.connect() as conn:
                    self._cache = [{k: _norm(v) for k, v in row._mapping.items()}
                                   for row in conn.execute(text(q))]
            finally:
                engine.dispose()
        return self._cache


class HttpConnector:
    """Read-only REST source: GET a JSON array of objects (or {records_key: [...]}).
    URL and token come from environment configuration, never from request data.
    Rows are cached for the life of the process (add a TTL if you need live refresh)."""

    def __init__(self, url: str, token: str | None = None, records_key: str | None = None,
                 timeout: float = 10.0, transport=None):
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        self.url, self.token, self.records_key = url, token, records_key
        self.timeout, self._transport = timeout, transport
        self._cache: list[dict] | None = None

    def rows(self) -> list[dict]:
        if self._cache is None:
            import httpx
            headers = {"Accept": "application/json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            with httpx.Client(timeout=self.timeout, transport=self._transport, follow_redirects=False) as client:
                resp = client.get(self.url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            if isinstance(data, dict) and self.records_key:
                data = data.get(self.records_key)
            if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
                raise ValueError("expected a JSON array of objects")
            self._cache = [{k: _norm(v) for k, v in row.items()} for row in data]
        return self._cache


class ParquetConnector:
    """Read-only Parquet source: one .parquet file or a directory (partitioned dataset).
    Timestamps become ISO strings, numbers become strings, so packs see exactly what CSV gives them.
    The whole table is loaded into memory; max_rows stops accidental huge loads."""

    def __init__(self, path: Path, max_rows: int = 2_000_000):
        self.path, self.max_rows = Path(path), max_rows
        self._cache: list[dict] | None = None

    def rows(self) -> list[dict]:
        if self._cache is None:
            import pyarrow.dataset as ds
            if not self.path.exists():
                raise FileNotFoundError(f"parquet path not found: {self.path}")
            dataset = ds.dataset(str(self.path), format="parquet")
            n = dataset.count_rows()
            if n > self.max_rows:
                raise ValueError(f"{n} rows exceeds max_rows={self.max_rows}; filter or sample the data first")
            self._cache = [{k: _norm(v) for k, v in row.items()} for row in dataset.to_table().to_pylist()]
        return self._cache


def write_parquet_from_csv(csv_path: Path, out_path: Path) -> int:
    """Demo helper: CSV -> typed Parquet (ints, floats; an ISO column named ts becomes a timestamp)."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cols = {}
    for c in rows[0]:
        vals = [r[c] for r in rows]
        for conv in (int, float):
            try:
                cols[c] = [conv(v) for v in vals]
                break
            except ValueError:
                pass
        else:
            cols[c] = [datetime.fromisoformat(v) for v in vals] if c == "ts" else vals
    pq.write_table(pa.table(cols), out_path)
    return len(rows)


def make_connector(pack: str, table: str, csv_path: Path, order_by: str | None = None):
    """Source priority: SQL (CASEFORGE_<PACK>_DB_URL) > REST (CASEFORGE_<PACK>_<TABLE>_URL, optional
    CASEFORGE_<PACK>_API_TOKEN) > Parquet (CASEFORGE_<PACK>_<TABLE>_PARQUET) > bundled CSV. Packs stay identical whichever is used."""
    db = os.getenv(f"CASEFORGE_{pack.upper()}_DB_URL")
    if db:
        return SqlConnector(db, table, order_by)
    api = os.getenv(f"CASEFORGE_{pack.upper()}_{table.upper()}_URL")
    if api:
        return HttpConnector(api, token=os.getenv(f"CASEFORGE_{pack.upper()}_API_TOKEN"))
    pq_path = os.getenv(f"CASEFORGE_{pack.upper()}_{table.upper()}_PARQUET")
    if pq_path:
        return ParquetConnector(Path(pq_path))
    return CsvConnector(csv_path)


def load_csv_into_sqlite(csv_path: Path, db_path: Path, table: str) -> int:
    """Demo helper: load a CSV into a typed SQLite table. Returns row count."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    def kind(col):
        vals = [r[col] for r in rows]
        for conv, sql in ((int, "INTEGER"), (float, "REAL")):
            try:
                [conv(v) for v in vals]
                return sql
            except ValueError:
                pass
        return "TEXT"

    cols = list(rows[0])
    types = {c: kind(c) for c in cols}
    con = sqlite3.connect(db_path)
    try:
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(f"CREATE TABLE {table} ({', '.join(f'{c} {types[c]}' for c in cols)})")
        con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(cols))})",
                        [[r[c] for c in cols] for r in rows])
        con.commit()
    finally:
        con.close()
    return len(rows)
