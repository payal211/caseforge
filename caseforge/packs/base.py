from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..core.rag import DocIndex
from ..core.schema import Analysis, Citation, Evidence


def weighted_score(evidence: list[Evidence], action_bands: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    raw_score = sum(item.weight for item in evidence)
    score = min(100.0, raw_score)
    breakdown = {
        "formula": "min(100, sum of evidence points)",
        "raw_total": round(raw_score, 2),
        "cap": 100,
        "signals": [
            {"signal": item.signal, "source": item.source, "points": item.weight, "detail": item.detail}
            for item in evidence if item.weight > 0
        ],
        "action_bands": sorted(action_bands, key=lambda band: band["minimum"], reverse=True),
    }
    return score, breakdown


class DomainPack(ABC):
    """Everything domain-specific lives here. The orchestrator, case file,
    approval flow, audit log and API are shared and never change per domain."""

    name: str
    title: str
    description: str = ""
    objective: str = ""
    scenario_guides: tuple[dict[str, str], ...] = ()
    baseline_manual_minutes: int  # ASSUMPTION for the productivity metric
    jev_question: str = "Do these findings indicate a problem that needs action?"

    def __init__(self, docs_dir: Path):
        self.index = DocIndex(docs_dir)

    def lookup_sources(self) -> dict:
        """Read-only sources the agent harness may query: {name: (connector, allowed_fields)}."""
        return {}

    @abstractmethod
    def list_subjects(self) -> list[dict]: ...

    @abstractmethod
    def gather(self, subject_id: str) -> tuple[list[Evidence], dict[str, Any]]:
        """Pull data via connectors, compute signals. Raise KeyError if unknown."""

    @abstractmethod
    def policy_query(self, evidence: list[Evidence], ctx: dict) -> str: ...

    @abstractmethod
    def reason(self, evidence: list[Evidence], ctx: dict, citations: list[Citation]) -> Analysis: ...

    @abstractmethod
    def draft_artifacts(self, subject_id: str, evidence: list[Evidence], ctx: dict,
                        analysis: Analysis, citations: list[Citation]) -> dict[str, Any]: ...

    @abstractmethod
    def narrative_prompt(self, subject_id: str, evidence: list[Evidence], analysis: Analysis,
                         citations: list[Citation]) -> tuple[str, str]: ...

    @abstractmethod
    def fallback_summary(self, subject_id: str, evidence: list[Evidence], analysis: Analysis,
                         citations: list[Citation]) -> str: ...
