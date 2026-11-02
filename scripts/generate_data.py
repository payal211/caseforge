"""Generates deterministic synthetic demo data. Run: python scripts/generate_data.py"""
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)
ROOT = Path(__file__).resolve().parent.parent / "caseforge" / "packs"


def write(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def bfsi():
    out = ROOT / "bfsi" / "data"
    accounts = [("ACC-1001", "Asha Verma", "IN"), ("ACC-1002", "Rohan Mehta", "IN"),
                ("ACC-1003", "Priya Nair", "IN"), ("ACC-1004", "Kiran Rao", "IN"),
                ("ACC-1005", "Dev Malhotra", "IN")]
    write(out / "accounts.csv", [dict(account_id=a, name=n, home_country=c) for a, n, c in accounts],
          ["account_id", "name", "home_country"])
    device = {"ACC-1001": "DEV-A1", "ACC-1002": "DEV-B1", "ACC-1003": "DEV-T1",
              "ACC-1004": "DEV-D1", "ACC-1005": "DEV-E1"}
    merchants = ["BigBasket", "Swiggy", "Amazon IN", "Uber", "Reliance Retail", "IRCTC"]
    base = datetime(2026, 9, 1, 12, 0)
    rows, n = [], 1

    def add(acc, ts, amt, merchant, country, dev, disputed=0, txn_id=None):
        nonlocal n
        rows.append(dict(txn_id=txn_id or f"TXN-{1000 + n}", account_id=acc, ts=ts.isoformat(),
                         amount=round(amt, 2), merchant=merchant, country=country,
                         device_id=dev, channel="app", disputed=disputed))
        n += 1

    for acc, _, _ in accounts:
        for _ in range(28):
            ts = base - timedelta(days=random.randint(1, 30), hours=random.randint(0, 10),
                                  minutes=random.randint(0, 59))
            add(acc, ts, random.uniform(300, 4500), random.choice(merchants), "IN", device[acc])
    for d in range(6):  # legit travel history for ACC-1003 in UAE
        ts = base - timedelta(days=2 + d, hours=random.randint(0, 6))
        add("ACC-1003", ts, random.uniform(3000, 9000), "Dubai Retail", "AE", "DEV-T1")
    # Scenario 1: classic account takeover / card testing (should score high)
    add("ACC-1001", datetime(2026, 9, 2, 2, 3), 1.0, "ONLINE-TEST", "SG", "DEV-X77", txn_id="TXN-9000")
    add("ACC-1001", datetime(2026, 9, 2, 2, 14), 185000.0, "ELECTRO-WORLD", "SG", "DEV-X77",
        disputed=1, txn_id="TXN-9001")
    add("ACC-1004", datetime(2026, 9, 2, 1, 40), 2.0, "ONLINE-TEST", "SG", "DEV-X77", txn_id="TXN-9004")
    add("ACC-1005", datetime(2026, 9, 2, 1, 55), 3.0, "ONLINE-TEST", "SG", "DEV-X77", txn_id="TXN-9005")
    # Scenario 2: ordinary purchase the customer forgot (should score low)
    add("ACC-1002", datetime(2026, 9, 1, 18, 30), 2450.0, "Swiggy", "IN", "DEV-B1",
        disputed=1, txn_id="TXN-9002")
    # Scenario 3: legit traveller, high amount, known device (should escalate)
    add("ACC-1003", datetime(2026, 9, 1, 20, 10), 42000.0, "Dubai Mall Retail", "AE", "DEV-T1",
        disputed=1, txn_id="TXN-9003")
    rows.sort(key=lambda r: r["ts"])
    write(out / "transactions.csv", rows,
          ["txn_id", "account_id", "ts", "amount", "merchant", "country", "device_id", "channel", "disputed"])


def manufacturing():
    out = ROOT / "manufacturing" / "data"
    start = datetime(2026, 9, 1)
    rows = []
    for machine in ["PUMP-03", "PUMP-07", "COMP-02"]:
        for h in range(14 * 24):
            d = h / 24
            vib = random.gauss(2.2, 0.08)
            temp = random.gauss(61, 0.6)
            pres = random.gauss(6.0, 0.05)
            cur = random.gauss(18.5, 0.25)
            if machine == "PUMP-07" and d > 9:
                k = d - 9
                vib += 0.35 * k ** 1.6
                temp += 1.1 * k ** 1.3
                cur += 0.15 * k
            if machine == "COMP-02" and d > 10:
                k = d - 10
                pres -= 0.25 * k
                cur += 0.5 * k
                vib += 0.02 * k
            rows.append(dict(ts=(start + timedelta(hours=h)).isoformat(), machine_id=machine,
                             vibration_mm_s=round(vib, 3), temp_c=round(temp, 2),
                             pressure_bar=round(pres, 3), current_a=round(cur, 2)))
    write(out / "sensors.csv", rows, ["ts", "machine_id", "vibration_mm_s", "temp_c", "pressure_bar", "current_a"])


def claims():
    """Insurance claims pack: defined entirely in YAML; this only generates its demo data."""
    out = ROOT / "claims" / "data"
    pol = [("POL-101", "Maya Iyer", "CA"), ("POL-102", "Tom Reed", "CA"), ("POL-103", "Lena Fox", "CA"),
           ("POL-104", "Omar Said", "TX"), ("POL-105", "Ana Ruiz", "TX")]
    write(out / "policies.csv", [dict(policy_id=a, holder=b, home_state=c) for a, b, c in pol],
          ["policy_id", "holder", "home_state"])
    base, rows, n = datetime(2026, 9, 1, 12, 0), [], 1
    descs = ["Windshield repair", "Minor collision repair", "Dental procedure", "Routine clinic visit", "Roof leak repair"]

    def add(pid, ts, amt, prov, state, bank, desc, flagged=0, cid=None):
        nonlocal n
        rows.append(dict(claim_id=cid or f"CLM-{1000 + n}", policy_id=pid, ts=ts.isoformat(), amount=round(amt, 2),
                         provider_id=prov, state=state, bank_account=bank, description=desc, flagged=flagged))
        n += 1

    for pid, _, st in pol:
        for _ in range(25):
            ts = base - timedelta(days=random.randint(2, 40), hours=random.randint(0, 9), minutes=random.randint(0, 59))
            add(pid, ts, random.uniform(300, 4500), f"PRV-{random.randint(1, 4)}", st, f"ACCT-{pid[-3:]}", random.choice(descs))
    add("POL-104", datetime(2026, 9, 2, 0, 30), 900.0, "PRV-2", "TX", "ACCT-FRAUD", "Clinic visit")
    add("POL-105", datetime(2026, 9, 2, 0, 50), 1200.0, "PRV-3", "TX", "ACCT-FRAUD", "Clinic visit")
    add("POL-101", datetime(2026, 9, 2, 1, 40), 750.0, "PRV-X9", "NV", "ACCT-FRAUD", "Equipment invoice")
    add("POL-101", datetime(2026, 9, 2, 1, 58), 820.0, "PRV-X9", "NV", "ACCT-FRAUD", "Equipment invoice")
    add("POL-101", datetime(2026, 9, 2, 2, 14), 48000.0, "PRV-X9", "NV", "ACCT-FRAUD", "Urgent equipment invoice", 1, "CLM-9001")
    add("POL-102", datetime(2026, 9, 1, 15, 5), 1850.0, "PRV-2", "CA", "ACCT-102", "Windshield repair", 1, "CLM-9002")
    add("POL-103", datetime(2026, 9, 1, 14, 0), 30000.0, "PRV-1", "CA", "ACCT-103", "Roof leak repair", 1, "CLM-9003")
    rows.sort(key=lambda r: r["ts"])
    write(out / "claims.csv", rows, ["claim_id", "policy_id", "ts", "amount", "provider_id", "state", "bank_account", "description", "flagged"])


if __name__ == "__main__":
    bfsi()
    manufacturing()
    claims()
    print("data generated")
