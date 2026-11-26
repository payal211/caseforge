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
from ..core.llm import LLMError
from ..core.schema import Status
from ..harness.loop import AgentLoopError


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
    status: Literal["under_review", "resolved", "not_approved", "specialist_follow_up"]
    customer_message: str


def build_router(orch) -> APIRouter:
    router = APIRouter(prefix="/cx", tags=["cx (customer channel)"])
    pack = orch.packs["bfsi"]

    def _txn(txn_id: str):
        return next((r for r in pack.txns.rows() if r["txn_id"] == txn_id), None)

    def _dispute_projection(case, account_id: str) -> DisputeOut:
        txn = _txn(case.subject_id)
        if case.domain != "bfsi" or txn is None or txn["account_id"] != account_id:
            raise HTTPException(404, "dispute not found")
        if case.status == Status.PENDING_APPROVAL:
            return DisputeOut(reference=case.case_id, status="under_review",
                              customer_message="Your dispute is still being reviewed by our fraud team.")
        if case.status == Status.APPROVED:
            return DisputeOut(reference=case.case_id, status="resolved",
                              customer_message=case.artifacts.get("customer_notification_draft", ""))
        if case.status == Status.REJECTED:
            return DisputeOut(reference=case.case_id, status="not_approved",
                              customer_message=("After review, we did not approve this dispute. If you still believe "
                                                "the transaction is incorrect, please contact customer support."))
        return DisputeOut(reference=case.case_id, status="specialist_follow_up",
                          customer_message=("A fraud specialist is handling your dispute personally and "
                                            "will contact you shortly."))

    def _canonical_case(cases):
        if not cases:
            return None
        decided = [case for case in cases if case.decision is not None]
        if decided:
            return max(decided, key=lambda case: (case.decision.decided_at, case.created_at))
        return max(cases, key=lambda case: case.created_at)

    def _account_cases_for_transaction(account_id: str, transaction_id: str):
        return [
            case for case in orch.store.list()
            if case.domain == "bfsi"
            and case.subject_id == transaction_id
            and (txn := _txn(case.subject_id)) is not None
            and txn["account_id"] == account_id
        ]

    def _log_customer_statement(case_id: str, body: DisputeIn) -> None:
        hits = guardrails.scan(body.customer_statement)
        safe_statement, _ = guardrails.redact(body.customer_statement, "customer_statement")
        orch.audit.log(case_id, "customer_statement",
                       {"channel": "cx", "account_id": body.account_id, "text": safe_statement,
                        "guardrail_hits": hits})
        if hits:
            orch.audit.log(case_id, "guardrail_flags",
                           {"flags": [f"customer_statement:{','.join(hits)}"]})

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
        existing = _canonical_case(_account_cases_for_transaction(body.account_id, body.transaction_id))
        if existing is not None:
            orch.audit.log(existing.case_id, "duplicate_dispute_reused",
                           {"channel": "cx", "account_id": body.account_id})
            _log_customer_statement(existing.case_id, body)
            return _dispute_projection(existing, body.account_id)
        try:
            case = orch.investigate("bfsi", body.transaction_id)
        except (AgentLoopError, LLMError) as e:
            raise HTTPException(503, f"dispute investigation unavailable: {e}")
        _log_customer_statement(case.case_id, body)
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
        _dispute_projection(case, account_id)
        canonical = _canonical_case(_account_cases_for_transaction(account_id, case.subject_id))
        if canonical is None:
            raise HTTPException(404, "dispute not found")
        return _dispute_projection(canonical, account_id)

    @router.get("/accounts/{account_id}/disputes", response_model=list[DisputeOut])
    def account_disputes(account_id: str):
        """List only customer-safe disputes belonging to this demo account."""
        if not any(a["account_id"] == account_id for a in pack.accounts.rows()):
            raise HTTPException(404, "account not found")
        grouped = {}
        for case in orch.store.list():
            if case.domain != "bfsi":
                continue
            txn = _txn(case.subject_id)
            if txn is not None and txn["account_id"] == account_id:
                grouped.setdefault(case.subject_id, []).append(case)
        canonical_cases = (_canonical_case(cases) for cases in grouped.values())
        ordered = sorted((case for case in canonical_cases if case is not None),
                         key=lambda case: case.created_at, reverse=True)
        return [_dispute_projection(case, account_id) for case in ordered]

    return router
