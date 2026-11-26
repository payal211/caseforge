import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel, Field

from gecx.caseforge_dispute_agent.agent import root_agent

logger = logging.getLogger(__name__)


class ChatSessionIn(BaseModel):
    account_id: str


class ChatMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def build_router(orch) -> APIRouter:
    router = APIRouter(prefix="/cx/assistant", tags=["cx assistant demo"])
    runner = InMemoryRunner(agent=root_agent, app_name="caseforge_gecx")
    sessions: dict[str, tuple[str, str]] = {}
    accounts = {row["account_id"] for row in orch.packs["bfsi"].accounts.rows()}

    @router.post("/sessions")
    async def create_session(body: ChatSessionIn):
        if body.account_id not in accounts:
            raise HTTPException(404, "demo customer not found")
        session = await runner.session_service.create_session(
            app_name=runner.app_name,
            user_id=body.account_id,
            state={"account_id": body.account_id},
        )
        session_key = uuid4().hex
        sessions[session_key] = (body.account_id, session.id)
        return {"session_id": session_key}

    @router.post("/sessions/{session_id}/messages")
    async def send_message(session_id: str, body: ChatMessageIn):
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(404, "assistant session not found")
        account_id, adk_session_id = session
        content = types.Content(role="user", parts=[types.Part(text=body.text)])
        reply = ""
        activities: list[str] = []
        try:
            async for event in runner.run_async(
                user_id=account_id,
                session_id=adk_session_id,
                new_message=content,
            ):
                for part in event.content.parts if event.content else []:
                    if part.function_call:
                        activities.append(part.function_call.name)
                    if part.text and event.author != "user":
                        reply = part.text
        except Exception as exc:
            logger.exception("GECX assistant request failed for account %s", account_id)
            raise HTTPException(
                502,
                "The customer assistant is unavailable. Check the configured model and Ollama service.",
            ) from exc
        if not reply:
            raise HTTPException(502, "The customer assistant returned no response.")
        dispute_reference = None
        customer_message = None
        if {"open_dispute", "check_dispute_status"}.intersection(activities):
            adk_session = await runner.session_service.get_session(
                app_name=runner.app_name,
                user_id=account_id,
                session_id=adk_session_id,
            )
            dispute_reference = adk_session.state.get("last_dispute_reference")
            customer_message = adk_session.state.get("last_dispute_message")
        return {
            "reply": reply,
            "activities": activities,
            "dispute_reference": dispute_reference,
            "customer_message": customer_message,
        }

    return router
