"""Deterministic stand-in for Gemini so the demo runs with no API key and no network.

It is a real ADK `BaseLlm`, so the Runner, session state, tool calling and tool-result
handling are all genuine ADK code paths; only the language model is scripted. Set
GOOGLE_API_KEY (or GOOGLE_GENAI_USE_VERTEXAI=1) and the agent switches to Gemini with the
same tools and the same instruction.
"""
import re
from typing import AsyncGenerator

from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


def _text(content) -> str:
    return " ".join(p.text for p in (content.parts or []) if getattr(p, "text", None))


class ScriptedGecxLlm(BaseLlm):
    model: str = "scripted-gecx-offline"

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        last = llm_request.contents[-1]
        responses = [p.function_response for p in (last.parts or []) if getattr(p, "function_response", None)]
        if responses:
            yield self._reply(self._explain(responses[0].name, responses[0].response or {}))
            return
        user = _text(last)
        txn = re.search(r"TXN-\d+", user, re.I)
        ref = re.search(r"CASE-[0-9A-F]{8}", user, re.I)
        if ref:
            yield self._call("check_dispute_status", {"reference": ref.group(0).upper()})
        elif txn:
            yield self._call("open_dispute", {"transaction_id": txn.group(0).upper(), "customer_statement": user})
        else:
            yield self._call("list_recent_transactions", {})

    @staticmethod
    def _call(name: str, args: dict) -> LlmResponse:
        return LlmResponse(content=types.Content(role="model", parts=[
            types.Part(function_call=types.FunctionCall(name=name, args=args))]))

    @staticmethod
    def _reply(text: str) -> LlmResponse:
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))

    @staticmethod
    def _explain(tool: str, r: dict) -> str:
        if r.get("error"):
            return f"I couldn't do that: {r['error']} Could you double-check the details?"
        if tool == "list_recent_transactions":
            rows = r["transactions"]
            lines = [f"- {t['transaction_id']}: {t['amount']:,.2f} at {t['merchant']} ({t['country']}), {t['timestamp']}"
                     for t in rows]
            return "Here are your recent transactions:\n" + "\n".join(lines) + \
                   "\nWhich one don't you recognise? Please give me its ID."
        if tool == "open_dispute":
            return (f"I've opened dispute {r['reference']}. {r['customer_message']} "
                    f"Keep that reference handy and ask me for an update any time.")
        if tool == "check_dispute_status":
            return r["customer_message"]
        return "Done."
