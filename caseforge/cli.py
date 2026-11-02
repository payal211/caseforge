"""Quick terminal demo: python -m caseforge.cli [domain] [subject_id]"""
import sys

from .core.orchestrator import Orchestrator
from .packs import load_packs


def show(case):
    print(f"\n=== {case.case_id} | {case.domain} | {case.subject_id} ===")
    print(f"Risk {case.risk_score:g}/100 -> {case.recommended_action}")
    print(f"LLM summary used: {case.llm_used} | took {case.investigation_seconds}s")
    for r in case.reasoning:
        print("  -", r)
    print("Summary:", case.summary)
    if case.artifacts:
        print("Artifacts:", list(case.artifacts))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    orch = Orchestrator(load_packs())
    if len(sys.argv) == 3:
        show(orch.investigate(sys.argv[1], sys.argv[2]))
        return
    for name, pack in orch.packs.items():
        for s in pack.list_subjects():
            show(orch.investigate(name, s["subject_id"]))


if __name__ == "__main__":
    main()
