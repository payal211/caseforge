"""Tool layer of the agent harness. Every tool is READ-ONLY, typed, allowlisted, size-capped,
and its output is scanned/redacted before the model ever sees it."""
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.guardrails import redact

MAX_ARG_CHARS = 200
MAX_TEXT_CHARS = 4000
MAX_RESULT_CHARS = 2000
MAX_ROWS = 10


class ToolError(Exception):
    """Raised by a tool for a bad but non-fatal request; the message is shown to the model."""


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, str]  # parameter name -> "str" | "int"
    fn: Callable[..., Any]


@dataclass
class ToolResult:
    ok: bool
    text: str
    flags: list[str] = field(default_factory=list)


class ToolBox:
    def __init__(self, tools: list[Tool]):
        self.tools = {t.name: t for t in tools}

    def describe(self) -> str:
        return "\n".join(f"- {t.name}({', '.join(f'{k}: {v}' for k, v in t.params.items())}): {t.description}"
                         for t in self.tools.values())

    def call(self, name: Any, args: Any) -> ToolResult:
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return ToolResult(False, f"unknown tool. Available: {sorted(self.tools)}")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return ToolResult(False, "args must be a JSON object")
        if set(args) != set(tool.params):
            return ToolResult(False, f"args must be exactly {list(tool.params)}")
        for k, kind in tool.params.items():
            v = args[k]
            if kind == "str" and not (isinstance(v, str) and len(v) <= MAX_ARG_CHARS):
                return ToolResult(False, f"'{k}' must be a string of at most {MAX_ARG_CHARS} characters")
            if kind == "text" and not (isinstance(v, str) and 0 < len(v) <= MAX_TEXT_CHARS):
                return ToolResult(False, f"'{k}' must be text of at most {MAX_TEXT_CHARS} characters")
            if kind == "int" and (isinstance(v, bool) or not isinstance(v, int)):
                return ToolResult(False, f"'{k}' must be an integer")
        try:
            result = tool.fn(**args)
        except ToolError as e:
            return ToolResult(False, str(e))
        except Exception as e:  # a tool bug must never crash an investigation
            return ToolResult(False, f"tool failed: {type(e).__name__}")
        clean, flags = redact(result, f"tool:{name}")
        return ToolResult(True, json.dumps(clean, default=str)[:MAX_RESULT_CHARS], flags)


def build_toolbox(pack, evidence, sandbox=None, data=None) -> ToolBox:
    """Generic tools every domain pack gets for free, derived from the pack itself."""
    sources = pack.lookup_sources()

    def get_evidence():
        return [{"signal": e.signal, "detail": e.detail, "weight": e.weight} for e in evidence]

    def search_documents(query: str):
        return [{"doc": c.doc, "section": c.section, "excerpt": c.excerpt[:400]} for c in pack.index.search(query, k=3)]

    def lookup(source: str, field: str, value: str):
        if source not in sources:
            raise ToolError(f"unknown source. Allowed: {sorted(sources)}")
        conn, allowed = sources[source]
        if field not in allowed:
            raise ToolError(f"field not allowed for {source}. Allowed: {list(allowed)}")
        rows = [r for r in conn.rows() if r.get(field) == value]
        rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
        return rows[:MAX_ROWS]

    def run_python(code: str):
        r = sandbox.run(code, data or {})
        return {"ok": r.ok, "exit_code": r.exit_code, "timed_out": r.timed_out, "truncated": r.truncated,
                "stdout": r.stdout, "stderr": r.stderr[-500:]}

    extra = []
    if sandbox is not None and sandbox.enabled and sandbox.available:  # fail closed: no runtime, no tool
        extra.append(Tool("run_python", "Run short Python in an isolated container (no network, no files). The variable "
                          "`data` holds the case evidence and record. Print your results.", {"code": "text"}, run_python))
    return ToolBox(extra + [
        Tool("get_evidence", "List the weighted evidence signals already gathered for this case.", {}, get_evidence),
        Tool("search_documents", "Search policy or manual sections; returns the top 3 excerpts.",
             {"query": "str"}, search_documents),
        Tool("lookup", f"Look up up to {MAX_ROWS} recent source rows where field equals value. "
                       f"Sources: {sorted(sources)}.", {"source": "str", "field": "str", "value": "str"}, lookup),
    ])
