"""Relational schema for case storage and the audit log (PostgreSQL in production, SQLite for tests)."""
from functools import lru_cache

from sqlalchemy import (BigInteger, Column, DateTime, Float, Index, Integer, JSON, MetaData, String, Table,
                        create_engine)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
_JSON = JSON().with_variant(JSONB(), "postgresql")  # JSONB on Postgres: indexable, compact

cases = Table(
    "cases", metadata,
    Column("case_id", String(32), primary_key=True),
    Column("domain", String(64), nullable=False),
    Column("subject_id", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("risk_score", Float, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("doc", _JSON, nullable=False),  # the full CaseFile
    Index("ix_cases_status", "status"),
    Index("ix_cases_domain_subject", "domain", "subject_id"),
    Index("ix_cases_created_at", "created_at"),
)

audit_events = Table(
    "audit_events", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("case_id", String(32), nullable=False, index=True),
    Column("event", String(64), nullable=False),
    Column("data", _JSON, nullable=False),
)


@lru_cache(maxsize=8)
def get_engine(url: str):
    """One pooled engine per URL. create_all is a dev convenience; use migrations (Alembic) in production."""
    engine = create_engine(url, pool_pre_ping=True)
    metadata.create_all(engine)
    return engine
