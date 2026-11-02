"""Domain pack auto-discovery. Two ways to add an industry:
  1. Python: caseforge/packs/<name>/pack.py exposing PACK = <DomainPack instance>
  2. No-code: caseforge/packs/<name>/pack.yaml + data/ + docs/  (see HARNESS.md)
Scaffold either with:  python -m caseforge.harness new-pack <name>"""
import importlib
from functools import lru_cache
from pathlib import Path

from .base import DomainPack


@lru_cache(maxsize=1)
def load_packs() -> dict[str, DomainPack]:
    packs: dict[str, DomainPack] = {}
    for d in sorted(Path(__file__).parent.iterdir()):
        if not d.is_dir() or d.name.startswith(("_", ".")):
            continue
        if (d / "pack.py").exists():
            pack = getattr(importlib.import_module(f"{__name__}.{d.name}.pack"), "PACK", None)
        elif (d / "pack.yaml").exists():
            from ..harness.declarative import DeclarativePack
            pack = DeclarativePack.from_dir(d)
        else:
            continue
        if pack is not None:
            packs[pack.name] = pack
    return packs
