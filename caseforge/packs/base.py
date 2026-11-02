from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..core.rag import DocIndex
from ..core.schema import Analysis, Citation, Evidence


class DomainPack(ABC):
    """Everything domain-specific lives here. The orchestrator, case file,
    approval flow, audit log and API are shared and never change per domain."""

    name: str
    title: str
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
