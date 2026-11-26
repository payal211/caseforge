"""CaseForge tools for the customer-facing agent.

These are thin HTTP calls to CaseForge's /cx channel. The account identity comes from ADK
session state (`account_id`), which in a real GECX deployment is the authenticated session
parameter, NOT something the model or the customer can type into the chat.
"""
import os

import httpx
from google.adk.tools import ToolContext

BASE = os.getenv("CASEFORGE_URL", "http://127.0.0.1:8000")


def _account(tool_context: ToolContext) -> str | None:
    return tool_context.state.get("account_id")


async def list_recent_transactions(tool_context: ToolContext) -> dict:
    """List the authenticated customer's recent card transactions, newest first.

    Use this when the customer wants to dispute a charge but has not given a transaction ID.
    """
    acc = _account(tool_context)
    if not acc:
        return {"error": "customer is not authenticated"}
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE}/cx/accounts/{acc}/transactions", timeout=30)
        r.raise_for_status()
        return {"transactions": r.json()}


async def open_dispute(transaction_id: str, customer_statement: str, tool_context: ToolContext) -> dict:
    """Open a fraud dispute for one of the customer's transactions.

    Args:
        transaction_id: The transaction ID, e.g. TXN-9001.
        customer_statement: The customer's own words about why they dispute it, verbatim.

    Returns the existing dispute if one is already recorded for this transaction, otherwise opens
    one for analyst review. Relay its customer_message; never promise a refund or a result.
    """
    tool_context.state["last_dispute_reference"] = None
    tool_context.state["last_dispute_message"] = None
    acc = _account(tool_context)
    if not acc:
        return {"error": "customer is not authenticated"}
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{BASE}/cx/disputes", timeout=60, json={
            "account_id": acc, "transaction_id": transaction_id, "customer_statement": customer_statement})
        if r.status_code == 404:
            return {"error": "That transaction was not found on this account."}
        r.raise_for_status()
        out = r.json()
    tool_context.state["last_dispute_reference"] = out["reference"]
    tool_context.state["last_dispute_message"] = out["customer_message"]
    return out


async def check_dispute_status(reference: str, tool_context: ToolContext) -> dict:
    """Check the status of a dispute by its reference (e.g. CASE-1A2B3C4D).

    Relay `customer_message` to the customer exactly as written.
    """
    tool_context.state["last_dispute_reference"] = None
    tool_context.state["last_dispute_message"] = None
    acc = _account(tool_context)
    if not acc:
        return {"error": "customer is not authenticated"}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE}/cx/disputes/{reference}",
            params={"account_id": acc},
            timeout=30,
        )
        if r.status_code == 404:
            return {"error": "No dispute with that reference was found on this account."}
        r.raise_for_status()
        out = r.json()
    tool_context.state["last_dispute_reference"] = out["reference"]
    tool_context.state["last_dispute_message"] = out["customer_message"]
    return out
