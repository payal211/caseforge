from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


class Status(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"


class Evidence(BaseModel):
    source: str                 # which connector/agent produced it
    signal: str                 # short machine-readable name
    detail: str                 # human-readable explanation
    weight: float = 0.0         # contribution to the risk score
    raw: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    doc: str
    section: str
    excerpt: str
    score: float


class Analysis(BaseModel):
    risk_score: float
    action: str
    reasoning: list[str]


class Decision(BaseModel):
    reviewer: str
    outcome: str                # approve | reject | override
    final_action: str
    note: str = ""
    decided_at: datetime = Field(default_factory=now)


class CaseFile(BaseModel):
    case_id: str = Field(default_factory=lambda: "CASE-" + uuid.uuid4().hex[:8].upper())
    domain: str
    subject_id: str
    status: Status = Status.PENDING_APPROVAL
    created_at: datetime = Field(default_factory=now)
    risk_score: float
    recommended_action: str
    summary: str
    reasoning: list[str]
    evidence: list[Evidence]
    citations: list[Citation]
    artifacts: dict[str, Any] = Field(default_factory=dict)
    llm_used: bool = False
    guardrail_flags: list[str] = Field(default_factory=list)
    second_opinion: Optional[dict[str, Any]] = None
    agent_run: Optional[dict[str, Any]] = None
    investigation_seconds: float = 0.0
    decision: Optional[Decision] = None
