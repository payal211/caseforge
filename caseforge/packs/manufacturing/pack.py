import re
import statistics
from pathlib import Path

from ...core.connectors import make_connector
from ...core.schema import Analysis, Citation, Evidence
from ..base import DomainPack

HERE = Path(__file__).parent
METRICS = ["vibration_mm_s", "temp_c", "pressure_bar", "current_a"]
BASELINE_HOURS = 7 * 24
RECENT_HOURS = 24
Z_FLAG = 3.0

HYPOTHESES = [  # most specific first
    {"name": "Bearing wear", "section": "Bearing wear",
     "requires": {("vibration_mm_s", "up"), ("temp_c", "up")},
     "query": "bearing wear vibration temperature lubrication"},
    {"name": "Seal leak and pressure loss", "section": "Seal leak and pressure loss",
     "requires": {("pressure_bar", "down"), ("current_a", "up")},
     "query": "seal leak pressure loss motor current impeller"},
    {"name": "Cavitation", "section": "Cavitation",
     "requires": {("vibration_mm_s", "up"), ("pressure_bar", "down")},
     "query": "cavitation vibration pressure suction strainer"},
]
PART = re.compile(r"Part:\s*(\S+)\s*\|\s*([^|]+?)\s*\|\s*qty\s*(\d+)")
STEP = re.compile(r"Step:\s*(.+)")
DOWNTIME = re.compile(r"Estimated downtime:\s*(\d+)")


def _slope_per_day(values: list[float]) -> float:
    n = len(values)
    xs = list(range(n))
    mx, my = statistics.mean(xs), statistics.mean(values)
    den = sum((x - mx) ** 2 for x in xs) or 1
    return sum((x - mx) * (y - my) for x, y in zip(xs, values)) / den * 24


class ManufacturingPack(DomainPack):
    name = "manufacturing"
    title = "Predictive maintenance root-cause agent"
    baseline_manual_minutes = 90  # ASSUMPTION: replace with measured engineer time
    jev_question = "Do these sensor findings indicate a machine fault that needs maintenance soon?"

    def __init__(self):
        super().__init__(HERE / "manuals")
        self.sensors = make_connector("manufacturing", "sensors", HERE / "data" / "sensors.csv", order_by="ts")

    def lookup_sources(self):
        return {"sensors": (self.sensors, ("machine_id",))}

    def list_subjects(self):
        return [{"subject_id": m, "label": m} for m in sorted({r["machine_id"] for r in self.sensors.rows()})]

    def gather(self, subject_id):
        rows = sorted((r for r in self.sensors.rows() if r["machine_id"] == subject_id), key=lambda r: r["ts"])
        if not rows:
            raise KeyError(subject_id)
        base, recent = rows[:BASELINE_HOURS], rows[-RECENT_HOURS:]
        last72 = rows[-72:]
        ev: list[Evidence] = []
        flagged: set[tuple[str, str]] = set()
        for m in METRICS:
            b = [float(r[m]) for r in base]
            bm, bs = statistics.mean(b), statistics.pstdev(b) or 1e-9
            rm = statistics.mean(float(r[m]) for r in recent)
            z = (rm - bm) / bs
            slope = _slope_per_day([float(r[m]) for r in last72])
            if abs(z) >= Z_FLAG:
                direction = "up" if z > 0 else "down"
                flagged.add((m, direction))
                ev.append(Evidence(source="sensor_logs", signal=f"{m}_drift", weight=min(35.0, abs(z) * 3),
                                   detail=f"{m} last 24h mean {rm:.2f} vs baseline {bm:.2f}±{bs:.2f} "
                                          f"(z={z:+.1f}, trend {slope:+.2f}/day, {direction}).",
                                   raw={"z": round(z, 2), "direction": direction}))
            else:
                ev.append(Evidence(source="sensor_logs", signal=f"{m}_stable", weight=0,
                                   detail=f"{m} within baseline (z={z:+.1f})."))
        hyp = None
        for h in HYPOTHESES:
            if h["requires"] <= flagged:
                hyp = h
                break
        return ev, {"machine": subject_id, "flagged": sorted(flagged), "hypothesis": hyp}

    def policy_query(self, evidence, ctx):
        h = ctx["hypothesis"]
        return h["query"] if h else "general inspection drift unclassified"

    def reason(self, evidence, ctx, citations):
        score = min(100.0, sum(e.weight for e in evidence))
        h = ctx["hypothesis"]
        if score >= 70:
            action = "Schedule corrective maintenance within 48 hours and raise a work order"
        elif score >= 40:
            action = "Raise an inspection work order for the next shift"
        else:
            action = "No action: continue monitoring"
        reasoning = [f"{e.signal}: {e.detail} (+{e.weight:.0f})" for e in evidence if e.weight > 0]
        reasoning = reasoning or ["All sensor channels within baseline."]
        if h:
            reasoning.append(f"Probable root cause: {h['name']} (drift pattern matches manual section).")
        elif score >= 40:
            reasoning.append("Drift pattern did not match a known fault; general inspection advised.")
        if citations:
            reasoning.append(f"Manual basis: {citations[0].doc} / {citations[0].section}.")
        return Analysis(risk_score=score, action=action, reasoning=reasoning)

    def draft_artifacts(self, subject_id, evidence, ctx, analysis, citations):
        if analysis.risk_score < 40:
            return {}
        h = ctx["hypothesis"]
        cite = next((c for c in citations if h and c.section == h["section"]),
                    citations[0] if citations else None)
        text = cite.excerpt if cite else ""
        parts = [{"part_no": p, "description": d, "qty": int(q)} for p, d, q in PART.findall(text)]
        tasks = STEP.findall(text)
        dt = DOWNTIME.search(text)
        return {
            "work_order": {
                "machine": subject_id,
                "priority": "P1" if analysis.risk_score >= 70 else "P2",
                "suspected_cause": h["name"] if h else "Unclassified drift",
                "tasks": tasks,
                "estimated_downtime_hours": int(dt.group(1)) if dt else None,
                "source_section": f"{cite.doc} / {cite.section}" if cite else None,
                "requires_approval": True,
            },
            "parts_request": parts,
        }

    def narrative_prompt(self, subject_id, evidence, analysis, citations):
        facts = "\n".join(f"- {r}" for r in analysis.reasoning)
        man = "\n".join(f"- {c.doc} / {c.section}: {c.excerpt[:200]}" for c in citations)
        return ("Domain: predictive maintenance root-cause analysis.",
                f"Machine: {subject_id}\nRisk score: {analysis.risk_score:g}/100\nFindings:\n{facts}\n"
                f"Manual excerpts:\n{man}\nRecommended action: {analysis.action}")

    def fallback_summary(self, subject_id, evidence, analysis, citations):
        drift = "; ".join(e.detail.rstrip(".") for e in sorted(evidence, key=lambda e: -e.weight)[:3] if e.weight > 0)
        sec = f" (manual section '{citations[0].section}')" if citations and analysis.risk_score >= 40 else ""
        return (f"Machine {subject_id} scored {analysis.risk_score:g}/100. "
                f"{('Drift: ' + drift + '. ') if drift else 'No drift detected. '}"
                f"Recommended action{sec}: {analysis.action}. Human approval required.")


PACK = ManufacturingPack()
