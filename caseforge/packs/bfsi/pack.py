import statistics
from datetime import datetime, timedelta
from pathlib import Path

from ...core.connectors import make_connector
from ...core.schema import Analysis, Citation, Evidence
from ..base import DomainPack

HERE = Path(__file__).parent
KEYWORDS = {
    "abnormal_amount": "abnormal amount standard deviations step-up verification",
    "new_device": "device never previously seen strong risk signal",
    "foreign_geo": "cross-border country home country prior history",
    "velocity": "card testing velocity micro-amounts block card",
    "shared_device": "device linked to three or more accounts fraud intelligence escalated",
}


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


class BfsiPack(DomainPack):
    name = "bfsi"
    title = "Fraud and dispute investigator"
    baseline_manual_minutes = 45  # ASSUMPTION: replace with measured analyst time
    jev_question = "Do these facts describe an unauthorized, fraudulent card transaction?"

    def __init__(self):
        super().__init__(HERE / "policies")
        self.txns = make_connector("bfsi", "transactions", HERE / "data" / "transactions.csv")
        self.accounts = make_connector("bfsi", "accounts", HERE / "data" / "accounts.csv")

    def lookup_sources(self):
        return {"transactions": (self.txns, ("account_id", "device_id", "merchant", "country")),
                "accounts": (self.accounts, ("account_id",))}

    def list_subjects(self):
        return [{"subject_id": r["txn_id"], "label": f'{r["account_id"]} · {r["merchant"]} · {r["amount"]}'}
                for r in self.txns.rows() if r["disputed"] == "1"]

    def gather(self, subject_id):
        rows = self.txns.rows()
        txn = next((r for r in rows if r["txn_id"] == subject_id), None)
        if not txn:
            raise KeyError(subject_id)
        acc = next(a for a in self.accounts.rows() if a["account_id"] == txn["account_id"])
        ts, amt = _ts(txn["ts"]), float(txn["amount"])
        mine = [r for r in rows if r["account_id"] == acc["account_id"] and r["txn_id"] != subject_id]
        # Baseline = established behaviour: activity older than 24h, so a fraudster's own
        # probe transactions never count as "normal history".
        prior = [r for r in mine if ts - _ts(r["ts"]) >= timedelta(hours=24)]
        ev: list[Evidence] = [Evidence(
            source="customer_profile", signal="profile",
            detail=f'Account {acc["account_id"]} ({acc["name"]}), home country {acc["home_country"]}, '
                   f'{len(prior)} prior transactions.')]

        amounts = [float(r["amount"]) for r in prior]
        if len(amounts) >= 5 and statistics.pstdev(amounts) > 0:
            mean, sd = statistics.mean(amounts), statistics.pstdev(amounts)
            z = (amt - mean) / sd
            w = 30 if z >= 4 else 15 if z >= 2 else 0
            ev.append(Evidence(source="transaction_history", signal="abnormal_amount", weight=w,
                               detail=f"Amount {amt:,.0f} vs customer average {mean:,.0f} (z={z:.1f}).",
                               raw={"z": round(z, 2)}))

        seen_devices = {r["device_id"] for r in prior}
        new_dev = txn["device_id"] not in seen_devices
        ev.append(Evidence(source="device_signals", signal="new_device", weight=20 if new_dev else 0,
                           detail=f'Device {txn["device_id"]} '
                                  f'{"never seen" if new_dev else "previously seen"} on this account.'))

        foreign = txn["country"] != acc["home_country"]
        seen_countries = {r["country"] for r in prior}
        if foreign:
            known = txn["country"] in seen_countries
            ev.append(Evidence(source="geo_signals", signal="foreign_geo", weight=10 if known else 20,
                               detail=f'Transaction in {txn["country"]} (home {acc["home_country"]}); '
                                      f'{"prior activity exists there" if known else "no prior activity there"}.'))
        else:
            ev.append(Evidence(source="geo_signals", signal="foreign_geo", weight=0,
                               detail="Transaction in home country."))

        recent = [r for r in mine if timedelta(0) <= ts - _ts(r["ts"]) <= timedelta(hours=1)]
        micro = [r for r in recent if float(r["amount"]) <= 10]
        vel_w = (15 if len(recent) >= 2 else 0) + (10 if micro else 0)
        ev.append(Evidence(source="transaction_history", signal="velocity", weight=vel_w,
                           detail=f"{len(recent)} other transactions in the prior hour"
                                  f"{f', {len(micro)} micro-amount probe(s)' if micro else ''}."))

        accounts_on_dev = {r["account_id"] for r in rows if r["device_id"] == txn["device_id"]}
        ev.append(Evidence(source="identity_signals", signal="shared_device",
                           weight=20 if len(accounts_on_dev) >= 3 else 0,
                           detail=f'Device {txn["device_id"]} linked to {len(accounts_on_dev)} account(s).'))

        if 0 <= ts.hour < 5:
            ev.append(Evidence(source="transaction_history", signal="off_hours", weight=5,
                               detail=f"Transaction at {ts:%H:%M}, outside normal hours."))
        return ev, {"txn": txn, "account": acc}

    def policy_query(self, evidence, ctx):
        words = ["unauthorized transaction dispute"]
        words += [KEYWORDS[e.signal] for e in evidence if e.weight > 0 and e.signal in KEYWORDS]
        words.append("escalation thresholds refund")
        return " ".join(words)

    def reason(self, evidence, ctx, citations):
        score = min(100.0, sum(e.weight for e in evidence))
        if score >= 70:
            action = "Approve dispute as fraud: block card and refund customer"
        elif score >= 40:
            action = "Escalate to senior analyst and request customer verification"
        else:
            action = "Decline dispute as legitimate and refer customer to merchant dispute process"
        reasoning = [f"{e.signal}: {e.detail} (+{e.weight:g})" for e in evidence if e.weight > 0]
        reasoning = reasoning or ["No risk signals triggered."]
        if citations:
            reasoning.append(f"Policy basis: {citations[0].doc} / {citations[0].section}.")
        return Analysis(risk_score=score, action=action, reasoning=reasoning)

    def draft_artifacts(self, subject_id, evidence, ctx, analysis, citations):
        name = ctx["account"]["name"]
        txn = ctx["txn"]
        if analysis.risk_score >= 70:
            msg = (f"Dear {name}, we have identified transaction {subject_id} ({txn['amount']} at "
                   f"{txn['merchant']}) as unauthorized. Your card will be blocked and reissued and the "
                   f"amount refunded within 10 business days.")
        elif analysis.risk_score >= 40:
            msg = (f"Dear {name}, we need to verify transaction {subject_id} with you before we can "
                   f"conclude your dispute. A specialist will contact you shortly.")
        else:
            msg = (f"Dear {name}, our review shows transaction {subject_id} matches your usual activity. "
                   f"Please contact {txn['merchant']} to resolve the charge or reply if you still disagree.")
        return {"customer_notification_draft": msg}

    def narrative_prompt(self, subject_id, evidence, analysis, citations):
        facts = "\n".join(f"- {r}" for r in analysis.reasoning)
        pol = "\n".join(f"- {c.doc} / {c.section}: {c.excerpt[:200]}" for c in citations)
        return ("Domain: card dispute fraud investigation.",
                f"Disputed transaction: {subject_id}\nRisk score: {analysis.risk_score:g}/100\n"
                f"Findings:\n{facts}\nPolicy excerpts:\n{pol}\nRecommended action: {analysis.action}")

    def fallback_summary(self, subject_id, evidence, analysis, citations):
        top = "; ".join(e.detail.rstrip(".") for e in sorted(evidence, key=lambda e: -e.weight)[:3] if e.weight > 0)
        sec = f" per policy section '{citations[0].section}'" if citations else ""
        return (f"Transaction {subject_id} scored {analysis.risk_score:g}/100. Key signals: "
                f"{top or 'none'}. Recommended action{sec}: {analysis.action}. Human approval required.")


PACK = BfsiPack()
