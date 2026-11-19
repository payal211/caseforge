"""Customer-experience (CX) channel for CaseForge.

This router is the ONLY surface a customer-facing agent (Gemini Enterprise for Customer
Experience / CX Agent Studio, or an ADK agent) should be wired to. It differs from the
reviewer API in three deliberate ways:

1. Ownership is enforced server-side. A dispute can only be opened for a transaction that
   belongs to the authenticated account; the agent/LLM cannot talk its way across accounts.
2. Responses are customer-safe projections. Risk score, evidence, guardrail flags and the
   recommended action never leave the building before a human has decided.
3. There is no approve/reject endpoint here. Only the reviewer API (`/cases/{id}/decision`)
   can decide, so a customer-facing agent can open and track cases but never resolve them.

The free-text customer statement is untrusted input: it is scanned by the existing
guardrails, redacted if hostile, and written to the audit trail. It never feeds the score.
"""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core import guardrails
from ..core.schema import Status


class DisputeIn(BaseModel):
    account_id: str = Field(description="Authenticated account (from the CX session, not from chat text).")
    transaction_id: str
    customer_statement: str = Field(default="", max_length=2000)


class TransactionOut(BaseModel):
    transaction_id: str
    timestamp: str
    amount: float
    merchant: str
    country: str


class DisputeOut(BaseModel):
    reference: str
    status: Literal["under_review", "resolved", "specialist_follow_up"]
    customer_message: str


def build_router(orch) -> APIRouter:
    router = APIRouter(prefix="/cx", tags=["cx (customer channel)"])
    pack = orch.packs["bfsi"]

    def _txn(txn_id: str):
        return next((r for r in pack.txns.rows() if r["txn_id"] == txn_id), None)

    @router.get("/accounts/{account_id}/transactions", response_model=list[TransactionOut])
    def recent_transactions(account_id: str, limit: int = 8):
        """Recent transactions for the authenticated account, newest first (customer-safe fields only)."""
        if not any(a["account_id"] == account_id for a in pack.accounts.rows()):
            raise HTTPException(404, "account not found")
        rows = sorted((r for r in pack.txns.rows() if r["account_id"] == account_id),
                      key=lambda r: r["ts"], reverse=True)[:max(1, min(limit, 25))]
        return [TransactionOut(transaction_id=r["txn_id"], timestamp=r["ts"], amount=float(r["amount"]),
                               merchant=r["merchant"], country=r["country"]) for r in rows]

    @router.post("/disputes", response_model=DisputeOut)
    def open_dispute(body: DisputeIn):
        """Open a dispute. Runs the full CaseForge investigation; result is held for human approval."""
        txn = _txn(body.transaction_id)
        if txn is None or txn["account_id"] != body.account_id:
            # Same answer for "doesn't exist" and "not yours": no enumeration of other accounts.
            raise HTTPException(404, "transaction not found on this account")
        case = orch.investigate("bfsi", body.transaction_id)
        hits = guardrails.scan(body.customer_statement)
        safe_statement, _ = guardrails.redact(body.customer_statement, "customer_statement")
        orch.audit.log(case.case_id, "customer_statement",
                       {"channel": "cx", "account_id": body.account_id, "text": safe_statement,
                        "guardrail_hits": hits})
        if hits:
            orch.audit.log(case.case_id, "guardrail_flags",
                           {"flags": [f"customer_statement:{','.join(hits)}"]})
        return DisputeOut(
            reference=case.case_id, status="under_review",
            customer_message=("We've opened a dispute for this transaction. Our fraud team reviews every "
                              "dispute before any decision is made, and we'll update you here."))

    @router.get("/disputes/{reference}", response_model=DisputeOut)
    def dispute_status(reference: str, account_id: str):
        """Customer-safe status. The notification text is released only after a human decision."""
        try:
            case = orch.store.get(reference)
        except KeyError:
            raise HTTPException(404, "dispute not found")
        txn = _txn(case.subject_id)
        if case.domain != "bfsi" or txn is None or txn["account_id"] != account_id:
            raise HTTPException(404, "dispute not found")
        if case.status == Status.PENDING_APPROVAL:
            return DisputeOut(reference=reference, status="under_review",
                              customer_message="Your dispute is still being reviewed by our fraud team.")
        if case.status == Status.APPROVED:
            return DisputeOut(reference=reference, status="resolved",
                              customer_message=case.artifacts.get("customer_notification_draft", ""))
        return DisputeOut(reference=reference, status="specialist_follow_up",
                          customer_message=("A fraud specialist is handling your dispute personally and "
                                            "will contact you shortly."))

    return router
