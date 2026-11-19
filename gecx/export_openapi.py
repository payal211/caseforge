"""Export ONLY the customer-safe /cx surface as an OpenAPI spec, for registering CaseForge as an
OpenAPI tool in GECX / CX Agent Studio. The reviewer endpoints are deliberately excluded.

    python gecx/export_openapi.py   ->   gecx/openapi/caseforge-cx.json
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CASEFORGE_DATA", tempfile.mkdtemp())

from caseforge.api.main import app  # noqa: E402

spec = app.openapi()
spec["paths"] = {p: v for p, v in spec["paths"].items() if p.startswith("/cx")}
spec["info"]["title"] = "CaseForge CX channel"
spec["servers"] = [{"url": "http://localhost:8000"}]
out = ROOT / "gecx" / "openapi" / "caseforge-cx.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(spec, indent=2))
print(f"wrote {out} with paths: {list(spec['paths'])}")
