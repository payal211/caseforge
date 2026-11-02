"""`python -m caseforge.harness new-pack <name>` writes a complete, runnable no-code industry pack
(sample data, risk rules, policy docs, scenarios). Edit the files, run check-pack, done."""
import csv
import random
import re
from datetime import datetime, timedelta
from pathlib import Path

PACKS_DIR = Path(__file__).resolve().parent.parent / "packs"

YAML = """# {title}. Edit me, then:  python -m caseforge.harness check-pack {name}
name: {name}
title: {title}
baseline_manual_minutes: 30        # ASSUMPTION: replace with measured reviewer time
id_field: record_id                # unique id of the thing being judged
entity_field: entity_id            # who/what it belongs to; history is built per entity
time_field: ts
sources:
  records: {{file: records.csv}}     # or any CSV/Parquet file in data/; SQL/REST via env vars (see README)
subjects:
  field: flagged                   # which records appear in the console list
  equals: "1"
  label: "{{entity_id}} · {{category}} · {{amount}}"
lookup_fields: [entity_id, category]
policy_keywords: suspicious unusual record review
second_opinion_question: Do these facts describe a record that needs escalation?
signals:                           # types: zscore, new_value, count_window, shared_across, time_of_day, threshold, differs_from_entity
  - {{name: abnormal_amount, type: zscore, field: amount, tiers: [{{z: 4, weight: 30}}, {{z: 2, weight: 15}}],
     detail: "Amount {{value}} vs entity average {{mean}} (z={{z}}).", keywords: "abnormal amount average verification"}}
  - {{name: high_value, type: threshold, field: amount, op: ">=", value: 10000, weight: 10,
     detail: "Amount {{value}} is above the 10,000 review limit.", keywords: "high value review limit"}}
  - {{name: new_category, type: new_value, field: category, weight: 20,
     detail: "Category {{value}} has never been seen for this entity.", keywords: "new category never seen"}}
  - {{name: burst, type: count_window, minutes: 180, min_count: 2, weight: 15,
     detail: "{{count}} other records for this entity in the previous 3 hours.", keywords: "burst repeated records short period"}}
  - {{name: night_activity, type: time_of_day, start: 0, end: 5, weight: 5,
     detail: "Activity at {{hour}}, outside normal hours."}}
actions:
  - {{min: 70, action: "Escalate to specialist and hold"}}
  - {{min: 40, action: "Request more information from the owner"}}
  - {{min: 0,  action: "Approve through the standard process"}}
artifacts:
  - name: owner_message_draft
    bands:
      - {{min: 70, template: "Record {{subject_id}} needs verification before we can proceed."}}
      - {{min: 0,  template: "Record {{subject_id}} ({{category}}) has been cleared."}}
scenarios:
  - {{subject: REC-9001, expect: high, why: "large unusual record with a burst before it"}}
  - {{subject: REC-9002, expect: low,  why: "ordinary record"}}
untrusted_fields: [notes]          # free-text fields a stranger could write into; the guardrails are tested against them
"""

POLICY = """# {title}: review policy

## Abnormal amount
An amount far above the entity's historical average needs verification before approval.

## High value review limit
Records of 10,000 or more must be reviewed by a specialist.

## New category never seen
A category the entity has never used is a risk signal; confirm the request with the owner.

## Burst of records
Several records for one entity within a few hours may indicate splitting or abuse.

## Escalation thresholds
Risk score 70 or above: escalate and hold. Score 40 to 69: request more information. Score below 40: approve. Every recommendation requires human approval.
"""

README = """# {title} pack

1. Replace `data/records.csv` with your data (keep the column names used in `pack.yaml`, or edit the YAML).
2. Rewrite `docs/policy.md` with your real policies. Use `## Section` headings: they become citations.
3. Tune `signals` (weights are points toward a 0-100 score) and `actions` (score bands) in `pack.yaml`.
4. Replace `scenarios` with real cases and the band you expect (high 70+, mid 40-69, low under 40).
5. `python -m caseforge.harness check-pack {name}` must be all PASS, then `uvicorn caseforge.api.main:app`.
"""


def new_pack(name: str, base: Path = PACKS_DIR) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", name):
        raise ValueError("name must be lowercase letters, digits, underscores (2-31 chars), starting with a letter")
    root = Path(base) / name
    if root.exists():
        raise FileExistsError(f"{root} already exists")
    title = name.replace("_", " ").title()
    (root / "data").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "pack.yaml").write_text(YAML.format(name=name, title=title), encoding="utf-8")
    (root / "docs" / "policy.md").write_text(POLICY.format(title=title), encoding="utf-8")
    (root / "README.md").write_text(README.format(name=name, title=title), encoding="utf-8")
    rnd, rows, n = random.Random(7), [], 1
    now = datetime(2026, 9, 1, 12, 0)

    def add(ent, ts, amount, cat, notes, flagged=0, rid=None):
        nonlocal n
        rows.append(dict(record_id=rid or f"REC-{1000 + n}", entity_id=ent, ts=ts.isoformat(), amount=round(amount, 2),
                         category=cat, notes=notes, flagged=flagged))
        n += 1

    for ent in ("ENT-1", "ENT-2", "ENT-3"):
        for _ in range(20):
            add(ent, now - timedelta(days=rnd.randint(2, 30), hours=rnd.randint(0, 9)), rnd.uniform(200, 3000),
                f"CAT-{rnd.randint(1, 3)}", "routine")
    add("ENT-1", datetime(2026, 9, 2, 1, 15), 400.0, "CAT-X", "burst 1")
    add("ENT-1", datetime(2026, 9, 2, 1, 50), 450.0, "CAT-X", "burst 2")
    add("ENT-1", datetime(2026, 9, 2, 2, 10), 20000.0, "CAT-X", "urgent", 1, "REC-9001")
    add("ENT-2", datetime(2026, 9, 1, 15, 0), 1500.0, "CAT-1", "ordinary", 1, "REC-9002")
    rows.sort(key=lambda r: r["ts"])
    with open(root / "data" / "records.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return root
