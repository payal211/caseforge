"""check-pack: validate a pack's files, data columns and scenarios before you run it."""
import tempfile
from pathlib import Path

from ..core import config
from ..core.audit import AuditLog
from ..core.jev import JevClient
from ..core.orchestrator import Orchestrator
from ..core.store import CaseStore
from .declarative import DeclarativePack, validate_spec
import yaml


def check_pack(root: Path) -> list[dict]:
    """Returns result rows {name, pass, detail}. Never raises on a bad pack."""
    from .evals import eval_declarative
    root, res = Path(root), []

    def add(name, ok, detail=""):
        res.append({"name": name, "pass": bool(ok), "detail": detail})

    if not (root / "pack.yaml").exists():
        return [{"name": "pack.yaml exists", "pass": False, "detail": str(root)}]
    spec = yaml.safe_load((root / "pack.yaml").read_text(encoding="utf-8"))
    errs = validate_spec(spec, root)
    add("spec is valid", not errs, "; ".join(errs))
    if errs:
        return res
    pack = DeclarativePack(spec, root)
    cols = set(pack.records.rows()[0])
    needed = {spec["id_field"], spec["entity_field"], spec["time_field"]} | {r["field"] for r in spec["signals"] if "field" in r}
    needed |= {r["group"] for r in spec["signals"] if "group" in r}
    add("data has every column the YAML uses", needed <= cols, f"missing: {sorted(needed - cols)}")
    ids = {r[spec["id_field"]] for r in pack.records.rows()}
    add("scenario subjects exist", all(s["subject"] in ids for s in pack.scenarios) and bool(pack.scenarios),
        "define at least one scenario whose subject id exists in the data")
    add("subject list is not empty", len(pack.list_subjects()) > 0)
    add("policy docs indexed", len(pack.index.chunks) > 0, "use '## Section' headings")
    if all(r["pass"] for r in res):
        with tempfile.TemporaryDirectory() as tmp:
            old, config.DATA_DIR = config.DATA_DIR, Path(tmp)
            try:
                orch = Orchestrator({pack.name: pack}, store=CaseStore(), audit=AuditLog(), jev=JevClient(enabled=False))
                for r in eval_declarative(orch, pack):
                    add(f"[{r['suite']}] {r['name']}", r["pass"], f"expected {r['expected']}, got {r['got']}")
            finally:
                config.DATA_DIR = old
    return res
