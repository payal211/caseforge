import os
import threading

from sqlalchemy import delete, insert, select, update

from . import config
from .db import cases, get_engine
from .schema import CaseFile, Status


class CaseStore:
    """One JSON file per case. Zero setup; fine for a laptop demo."""
    backend = "files"
    _lock = threading.Lock()

    @property
    def dir(self):
        d = config.DATA_DIR / "cases"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, case: CaseFile) -> None:
        (self.dir / f"{case.case_id}.json").write_text(case.model_dump_json(indent=2), encoding="utf-8")

    def get(self, case_id: str) -> CaseFile:
        p = self.dir / f"{case_id}.json"
        if not p.exists():
            raise KeyError(case_id)
        return CaseFile.model_validate_json(p.read_text(encoding="utf-8"))

    def list(self) -> list[CaseFile]:
        found = [CaseFile.model_validate_json(p.read_text(encoding="utf-8")) for p in self.dir.glob("CASE-*.json")]
        return sorted(found, key=lambda c: c.created_at, reverse=True)

    def save_decision(self, case: CaseFile, expected: Status) -> None:
        """Atomically record a decision only if the stored case is still in the expected status."""
        with self._lock:
            try:
                current = self.get(case.case_id)
            except KeyError:
                raise ValueError("case not found")
            if current.status != expected:
                raise ValueError(f"case already {current.status.value}")
            self.save(case)

    def clear(self) -> int:
        n = 0
        for f in self.dir.glob("CASE-*.json"):
            f.unlink()
            n += 1
        return n


class SqlCaseStore:
    """Cases in a relational database (PostgreSQL recommended). Decisions are a single conditional
    UPDATE, so two reviewers can never both decide the same case, even across processes."""

    def __init__(self, url: str):
        self.engine = get_engine(url)
        self.backend = self.engine.dialect.name

    @staticmethod
    def _row(case: CaseFile) -> dict:
        return dict(domain=case.domain, subject_id=case.subject_id, status=case.status.value,
                    risk_score=case.risk_score, created_at=case.created_at, doc=case.model_dump(mode="json"))

    def save(self, case: CaseFile) -> None:
        row = self._row(case)
        with self.engine.begin() as conn:
            if conn.execute(update(cases).where(cases.c.case_id == case.case_id).values(**row)).rowcount == 0:
                conn.execute(insert(cases).values(case_id=case.case_id, **row))

    def get(self, case_id: str) -> CaseFile:
        with self.engine.connect() as conn:
            doc = conn.execute(select(cases.c.doc).where(cases.c.case_id == case_id)).scalar_one_or_none()
        if doc is None:
            raise KeyError(case_id)
        return CaseFile.model_validate(doc)

    def list(self) -> list[CaseFile]:
        with self.engine.connect() as conn:
            docs = conn.execute(select(cases.c.doc).order_by(cases.c.created_at.desc())).scalars().all()
        return [CaseFile.model_validate(d) for d in docs]

    def save_decision(self, case: CaseFile, expected: Status) -> None:
        row = self._row(case)
        with self.engine.begin() as conn:
            r = conn.execute(update(cases).where(cases.c.case_id == case.case_id,
                                                 cases.c.status == expected.value)
                             .values(status=row["status"], doc=row["doc"]))
        if r.rowcount != 1:
            raise ValueError("case already decided or not found")

    def clear(self) -> int:
        with self.engine.begin() as conn:
            return conn.execute(delete(cases)).rowcount


def make_store():
    """CASEFORGE_DB_URL set -> SQL (e.g. postgresql+psycopg://user:pw@host/db); otherwise JSON files."""
    url = os.getenv("CASEFORGE_DB_URL")
    return SqlCaseStore(url) if url else CaseStore()
