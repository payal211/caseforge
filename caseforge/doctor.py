"""Pre-flight self check:  python -m caseforge.doctor      (add --no-llm to skip the Ollama test)
Tells you exactly what is wrong and how to fix it. Exit code 1 only if something FAILs."""
import importlib
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .core import config


@dataclass
class R:
    level: str  # PASS | WARN | FAIL
    name: str
    hint: str = ""


def _mod(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def check_environment() -> list[R]:
    out = []
    v = sys.version_info
    out.append(R("PASS" if v >= (3, 10) else "FAIL", f"Python {v.major}.{v.minor}.{v.micro}",
                 "Need Python 3.10 or newer (python.org, tick 'Add python.exe to PATH')."))
    for mod, pip, required in (("fastapi", "fastapi", 1), ("uvicorn", "uvicorn", 1), ("pydantic", "pydantic", 1),
                               ("httpx", "httpx", 1), ("langgraph", "langgraph", 1), ("sqlalchemy", "sqlalchemy", 1),
                               ("yaml", "pyyaml", 1), ("mcp", "mcp", 0), ("pyarrow", "pyarrow", 0),
                               ("psycopg", "psycopg[binary]", 0), ("typesafe_sdk", "typesafe-sdk", 0)):
        ok = _mod(mod)
        out.append(R("PASS" if ok else ("FAIL" if required else "WARN"), f"package {pip}" + ("" if ok else " missing"),
                     f"pip install {pip}" + ("" if required else "   (optional: only for a feature you may not use)")))
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = config.DATA_DIR / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        out.append(R("PASS", f"data folder writable ({config.DATA_DIR})"))
    except Exception as e:
        out.append(R("FAIL", f"cannot write to {config.DATA_DIR}", f"Run from a normal folder such as C:\\caseforge. {e}"))
    static = Path(__file__).parent / "api" / "static" / "index.html"
    out.append(R("PASS" if static.exists() else "FAIL", "React console build present",
                 "Re-extract the zip; caseforge/api/static must exist."))
    return out


def check_packs() -> list[R]:
    try:
        from .harness.evals import run_evals
        from .packs import load_packs
        out = [R("PASS", f"packs loaded: {', '.join(sorted(load_packs()))}")]
        rep = run_evals()
        out.append(R("PASS" if rep["passed"] == rep["total"] else "FAIL", f"scenario and attack evals {rep['passed']}/{rep['total']}",
                     "Run: python -m caseforge.harness evals   to see which one failed."))
        return out
    except Exception as e:
        return [R("FAIL", "packs or evals crashed", f"{type(e).__name__}: {e}")]


def check_ollama() -> list[R]:
    import httpx
    from .core.audit import AuditLog
    from .core.jev import JevClient
    from .core.orchestrator import Orchestrator
    from .core.store import CaseStore
    from .packs import load_packs
    if config.LLM_MODE == "mock":
        return [R("WARN", "LLM_MODE=mock: summaries are rule-based (a good fallback demo mode)",
                  "For real model text: set LLM_MODE=auto and start Ollama.")]
    try:
        tags = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=5).json()
    except Exception:
        return [R("FAIL", f"Ollama not reachable at {config.OLLAMA_URL}",
                  "Start the Ollama app (system tray) or run 'ollama serve'. Or use LLM_MODE=mock.")]
    names = {m.get("name", "") for m in tags.get("models", [])}
    if config.OLLAMA_MODEL not in names and f"{config.OLLAMA_MODEL}:latest" not in names:
        return [R("FAIL", f"model '{config.OLLAMA_MODEL}' is not installed (have: {', '.join(sorted(names)) or 'none'})",
                  f"ollama pull {config.OLLAMA_MODEL}   or set OLLAMA_MODEL to one you have.")]
    out = [R("PASS", f"Ollama reachable, model '{config.OLLAMA_MODEL}' installed")]
    with tempfile.TemporaryDirectory() as tmp:  # real end-to-end narrative through the real guardrails
        old, config.DATA_DIR = config.DATA_DIR, Path(tmp)
        try:
            t0 = time.perf_counter()
            case = Orchestrator(load_packs(), store=CaseStore(), audit=AuditLog(),
                                jev=JevClient(enabled=False)).investigate("bfsi", "TXN-9001")
            dt = time.perf_counter() - t0
        finally:
            config.DATA_DIR = old
    if case.llm_used:
        out.append(R("PASS", f"model narrative accepted by the guardrails ({dt:.0f}s for the first case)",
                     "" if dt < 60 else "Slow: run this check once before the demo to warm the model up, and set LLM_TIMEOUT=300."))
    else:
        rej = [f for f in case.guardrail_flags if f.startswith("llm_output_rejected")]
        out.append(R("WARN", "model text was not used for the summary" +
                     (f" (rejected: {rej[0]})" if rej else f" (no usable answer within {config.LLM_TIMEOUT:.0f}s)"),
                     "The app still works with rule-based summaries. Try OLLAMA_MODEL=llama3.1:8b, or LLM_TIMEOUT=300 if the first call was just slow."))
    return out


def check_sandbox() -> list[R]:
    from .harness.sandbox import Sandbox
    sb = Sandbox.from_env()
    if not sb.enabled:
        return [R("WARN", "sandbox is off (optional: lets the agent run Python safely)",
                  "Windows: Docker Desktop or Podman Desktop, then python -m caseforge.harness sandbox-setup, "
                  "python -m caseforge.harness sandbox-check, and set CASEFORGE_SANDBOX=on.")]
    ok, why = sb.status(fresh=True)
    return [R("PASS" if ok else "FAIL", f"sandbox: {why}", "" if ok else "Fix this, or set CASEFORGE_SANDBOX=off.")]


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    results = check_environment()
    if not any(r.level == "FAIL" for r in results):
        results += check_packs()
        results += check_sandbox()
        if "--no-llm" not in argv:
            results += check_ollama()
    for r in results:
        print(f"[{r.level}] {r.name}" + (f"\n        fix: {r.hint}" if r.hint and r.level != "PASS" else ""))
    print(f"\nstorage: {'PostgreSQL' if os.getenv('CASEFORGE_DB_URL') else 'JSON files'} | agent loop: "
          f"{os.getenv('CASEFORGE_AGENTIC', 'off')} | Jev layer: {os.getenv('CASEFORGE_JEV', 'off')}")
    bad = [r for r in results if r.level == "FAIL"]
    print("\nREADY: start with  uvicorn caseforge.api.main:app  then open http://localhost:8000" if not bad
          else f"\n{len(bad)} problem(s) to fix above.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
