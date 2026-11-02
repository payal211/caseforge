import json
import os
import threading
from datetime import datetime, timezone

from sqlalchemy import delete, insert, select

from . import config
from .db import audit_events, get_engine


class AuditLog:
    """Append-only JSONL audit trail: every agent step and every human decision."""
    backend = "files"

    def __init__(self):
        self._lock = threading.Lock()

    @property
    def path(self):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        return config.DATA_DIR / "audit.jsonl"

    def log(self, case_id: str, event: str, data: dict | None = None) -> None:
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "case_id": case_id,
               "event": event, "data": data or {}}
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    def read(self, case_id: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        out = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]
        return [r for r in out if case_id is None or r["case_id"] == case_id]

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


class SqlAuditLog:
    """Audit events in the same database as the cases. The app only ever INSERTs; for stronger guarantees
    grant the app's DB user INSERT/SELECT only (see README)."""

    def __init__(self, url: str):
        self.engine = get_engine(url)
        self.backend = self.engine.dialect.name

    def log(self, case_id: str, event: str, data: dict | None = None) -> None:
        payload = json.loads(json.dumps(data or {}, default=str))
        with self.engine.begin() as conn:
            conn.execute(insert(audit_events).values(ts=datetime.now(timezone.utc), case_id=case_id,
                                                     event=event, data=payload))

    def read(self, case_id: str | None = None) -> list[dict]:
        q = select(audit_events).order_by(audit_events.c.id)
        if case_id is not None:
            q = q.where(audit_events.c.case_id == case_id)
        with self.engine.connect() as conn:
            return [{"ts": r.ts.isoformat(), "case_id": r.case_id, "event": r.event, "data": r.data}
                    for r in conn.execute(q)]

    def clear(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(audit_events))


def make_audit():
    url = os.getenv("CASEFORGE_DB_URL")
    return SqlAuditLog(url) if url else AuditLog()
