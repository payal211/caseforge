"""No-code domain packs: describe an industry in pack.yaml (sources, risk rules, action bands, templates)
plus a docs/ folder of policies, and the harness gives you the full pipeline: investigation, guardrails,
human approval, audit log, API, console, MCP tools, agent loop, evals. Record-style cases only
(a record to judge, with a history per entity); time-series packs use the Python DomainPack API."""
import statistics
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from ..core.connectors import CsvConnector, ParquetConnector, make_connector
from ..core.schema import Analysis, Citation, Evidence
from ..packs.base import DomainPack

RULE_TYPES = {"zscore", "new_value", "count_window", "shared_across", "time_of_day", "threshold", "differs_from_entity"}
OPS = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b,
       "<=": lambda a, b: a <= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
REQUIRED_RULE_KEYS = {"zscore": ["field", "tiers"], "new_value": ["field", "weight"], "count_window": ["minutes", "min_count", "weight"],
                      "shared_across": ["field", "group", "min_groups", "weight"], "time_of_day": ["start", "end", "weight"],
                      "threshold": ["field", "op", "value", "weight"], "differs_from_entity": ["field", "entity_field", "weight"]}


class _Safe(dict):
    def __missing__(self, key):
        return ""


def validate_spec(spec: dict, root: Path) -> list[str]:
    """Return human-readable problems (empty list = valid)."""
    errs = []
    for k in ("name", "title", "id_field", "entity_field", "time_field", "sources", "signals", "actions"):
        if k not in spec:
            errs.append(f"missing required key '{k}'")
    if errs:
        return errs
    if not str(spec["name"]).replace("_", "").isalnum():
        errs.append("name must be letters, digits and underscores")
    src = spec["sources"].get("records") or {}
    if not src.get("file"):
        errs.append("sources.records.file is required")
    elif not (root / "data" / src["file"]).exists():
        errs.append(f"data file not found: data/{src['file']}")
    ent = spec["sources"].get("entities")
    if ent and not (root / "data" / ent.get("file", "")).exists():
        errs.append(f"entities file not found: data/{ent.get('file')}")
    if not list((root / "docs").glob("*.md")):
        errs.append("docs/ needs at least one .md policy file with '## Section' headings")
    names = set()
    for i, r in enumerate(spec["signals"]):
        t, n = r.get("type"), r.get("name")
        if t not in RULE_TYPES:
            errs.append(f"signals[{i}]: unknown type '{t}' (use one of {sorted(RULE_TYPES)})"); continue
        if not n or n in names:
            errs.append(f"signals[{i}]: needs a unique name")
        names.add(n)
        for key in REQUIRED_RULE_KEYS[t]:
            if key not in r:
                errs.append(f"signal '{n}': missing '{key}'")
        if t == "threshold" and r.get("op") not in OPS:
            errs.append(f"signal '{n}': op must be one of {sorted(OPS)}")
        weights = [x.get("weight") for x in r["tiers"]] if t == "zscore" and "tiers" in r else [r.get("weight")]
        if any(not isinstance(w, (int, float)) or not 0 <= w <= 100 for w in weights):
            errs.append(f"signal '{n}': weights must be numbers between 0 and 100")
    mins = [a.get("min") for a in spec["actions"]]
    if 0 not in mins or any(not isinstance(m, (int, float)) for m in mins):
        errs.append("actions need numeric 'min' values and one band with min: 0")
    return errs


class DeclarativePack(DomainPack):
    def __init__(self, spec: dict, root: Path):
        errs = validate_spec(spec, root)
        if errs:
            raise ValueError(f"invalid pack at {root}: " + "; ".join(errs))
        self.spec, self.root = spec, Path(root)
        self.name, self.title = spec["name"], spec["title"]
        self.baseline_manual_minutes = int(spec.get("baseline_manual_minutes", 30))
        self.jev_question = spec.get("second_opinion_question", "Do these facts indicate a problem that needs action?")
        self.scenarios = spec.get("scenarios", [])
        super().__init__(self.root / "docs")
        s = spec["sources"]
        self.records = self._connector("records", s["records"])
        self.entities = self._connector("entities", s["entities"]) if s.get("entities") else None

    @classmethod
    def from_dir(cls, root: Path) -> "DeclarativePack":
        return cls(yaml.safe_load((Path(root) / "pack.yaml").read_text(encoding="utf-8")), Path(root))

    def _connector(self, key: str, cfg: dict):
        path = self.root / "data" / cfg["file"]
        c = make_connector(self.name, cfg.get("table", key), path)
        return ParquetConnector(path) if isinstance(c, CsvConnector) and path.suffix == ".parquet" else c

    def lookup_sources(self):
        allowed = tuple(self.spec.get("lookup_fields", [self.spec["entity_field"], self.spec["id_field"]]))
        return {"records": (self.records, allowed)}

    def list_subjects(self):
        sub, idf = self.spec.get("subjects", {}), self.spec["id_field"]
        label = sub.get("label", "{" + idf + "}")
        out = []
        for r in self.records.rows():
            if "field" in sub and r.get(sub["field"]) != str(sub.get("equals", "1")):
                continue
            out.append({"subject_id": r[idf], "label": label.format_map(_Safe(r))})
        return out

    # ------------------------------------------------------------------ rules
    def _apply(self, rule, rec, ent, same, prior, all_rows, ts):
        t, f = rule["type"], rule.get("field")
        v = rec.get(f, "") if f else ""
        if t == "zscore":
            vals = [float(r[f]) for r in prior if r.get(f, "") != ""]
            if len(vals) < int(rule.get("history_min", 5)) or statistics.pstdev(vals) == 0:
                return None
            mean, sd = statistics.mean(vals), statistics.pstdev(vals)
            z = (float(v) - mean) / sd
            for tier in sorted(rule["tiers"], key=lambda x: -x["z"]):
                if z >= tier["z"]:
                    return tier["weight"], dict(value=v, mean=f"{mean:,.0f}", z=f"{z:.1f}"), {"z": round(z, 2)}
            return None
        if t == "new_value":
            return (rule["weight"], dict(value=v), {}) if prior and v not in {r.get(f) for r in prior} else None
        if t == "count_window":
            win = [r for r in same if timedelta(0) <= ts - datetime.fromisoformat(r[self.spec["time_field"]]) <= timedelta(minutes=rule["minutes"])]
            return (rule["weight"], dict(count=len(win)), {"count": len(win)}) if len(win) >= rule["min_count"] else None
        if t == "shared_across":
            groups = {r[rule["group"]] for r in all_rows if r.get(f) == v and v != ""}
            return (rule["weight"], dict(value=v, groups=len(groups)), {"groups": len(groups)}) if len(groups) >= rule["min_groups"] else None
        if t == "time_of_day":
            return (rule["weight"], dict(hour=f"{ts:%H:%M}"), {}) if rule["start"] <= ts.hour < rule["end"] else None
        if t == "threshold":
            try:
                a, b = (float(v), float(rule["value"])) if isinstance(rule["value"], (int, float)) else (v, str(rule["value"]))
            except ValueError:
                return None
            return (rule["weight"], dict(value=v), {}) if OPS[rule["op"]](a, b) else None
        if t == "differs_from_entity":
            ev = ent.get(rule["entity_field"], "")
            return (rule["weight"], dict(value=v, entity_value=ev), {}) if ev and v != ev else None

    def gather(self, subject_id):
        s, rows = self.spec, self.records.rows()
        idf, entf, tf = s["id_field"], s["entity_field"], s["time_field"]
        rec = next((r for r in rows if r[idf] == subject_id), None)
        if rec is None:
            raise KeyError(subject_id)
        ent = next((e for e in (self.entities.rows() if self.entities else [])
                    if e.get(s["sources"]["entities"].get("key", entf)) == rec[entf]), {})
        ts = datetime.fromisoformat(rec[tf])
        same = [r for r in rows if r[entf] == rec[entf] and r[idf] != subject_id]
        prior = [r for r in same if ts - datetime.fromisoformat(r[tf]) >= timedelta(hours=int(s.get("baseline_hours", 24)))]
        ev: list[Evidence] = [Evidence(source="profile", signal="profile",
                                       detail=f"{entf} {rec[entf]}: {len(prior)} established prior records, {len(same)} other records in total.")]
        fired = []
        for rule in s["signals"]:
            got = self._apply(rule, rec, ent, same, prior, rows, ts)
            name = rule["name"]
            if got is None:
                ev.append(Evidence(source=rule.get("source", "records"), signal=name, weight=0, detail=f"{name}: no signal."))
                continue
            weight, vars_, raw = got
            detail = rule.get("detail", f"{name} triggered by {rule.get('field', 'activity')} " + "{value}").format_map(_Safe({**vars_, "field": rule.get("field", "")}))
            ev.append(Evidence(source=rule.get("source", "records"), signal=name, weight=float(weight), detail=detail, raw=raw))
            fired.append(rule)
        return ev, {"record": rec, "entity": ent, "fired": [r["name"] for r in fired],
                    "keywords": " ".join(r.get("keywords", "") for r in fired)}

    def policy_query(self, evidence, ctx):
        return f"{self.spec.get('policy_keywords', '')} {ctx.get('keywords', '')} escalation thresholds"

    def reason(self, evidence, ctx, citations):
        score = min(100.0, sum(e.weight for e in evidence))
        action = next(a["action"] for a in sorted(self.spec["actions"], key=lambda a: -a["min"]) if score >= a["min"])
        reasoning = [f"{e.signal}: {e.detail} (+{e.weight:g})" for e in evidence if e.weight > 0] or ["No risk signals triggered."]
        if citations:
            reasoning.append(f"Policy basis: {citations[0].doc} / {citations[0].section}.")
        return Analysis(risk_score=score, action=action, reasoning=reasoning)

    def draft_artifacts(self, subject_id, evidence, ctx, analysis, citations):
        out = {}
        data = _Safe({**{f"entity_{k}": v for k, v in ctx["entity"].items()}, **ctx["record"],
                      "subject_id": subject_id, "score": f"{analysis.risk_score:g}", "action": analysis.action})
        for art in self.spec.get("artifacts", []):
            band = next((b for b in sorted(art["bands"], key=lambda b: -b["min"]) if analysis.risk_score >= b["min"]), None)
            if band:
                out[art["name"]] = band["template"].format_map(data)
        return out

    def narrative_prompt(self, subject_id, evidence, analysis, citations):
        facts = "\n".join(f"- {r}" for r in analysis.reasoning)
        docs = "\n".join(f"- {c.doc} / {c.section}: {c.excerpt[:200]}" for c in citations)
        return (f"Domain: {self.title}.", f"Case: {subject_id}\nRisk score: {analysis.risk_score:g}/100\nFindings:\n{facts}\n"
                f"Policy excerpts:\n{docs}\nRecommended action: {analysis.action}")

    def fallback_summary(self, subject_id, evidence, analysis, citations):
        top = "; ".join(e.detail.rstrip(".") for e in sorted(evidence, key=lambda e: -e.weight)[:3] if e.weight > 0)
        sec = f" per section '{citations[0].section}'" if citations else ""
        return f"Case {subject_id} scored {analysis.risk_score:g}/100. Key signals: {top or 'none'}. Recommended action{sec}: {analysis.action}. Human approval required."
