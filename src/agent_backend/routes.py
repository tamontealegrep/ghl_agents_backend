"""Generic HTTP routes served for every agent bundle: chat, reset and reload."""

from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from agent_backend.auth import require_api_token
from agent_backend.loader import AgentRegistry, LoadedAgent, message_buffer
from agent_backend.settings import Settings
from agent_runtime.runtime.graph_builder import fresh_state
from agent_runtime.runtime.session_resolver import resolve_session

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    """Body of a plain request/response chat turn.

    Attributes:
        thread_id: Conversation key; the same id resumes the same session.
        message: User text. Required unless the session is new.
        contact: CRM fields for a brand-new session; ignored once a session exists.
    """

    thread_id: str
    message: str | None = None
    contact: dict | None = None


class ChatResponse(BaseModel):
    """Result of one chat turn.

    Attributes:
        messages: Texts the agent produced this turn, in order.
        conversation_ended: True when the graph reached a terminal node.
        current_state: Name of the state the conversation is in.
    """

    messages: list[str]
    conversation_ended: bool
    current_state: str | None = None


def get_registry(request: Request) -> AgentRegistry:
    """FastAPI dependency returning the app's agent registry.

    Args:
        request: Incoming request.

    Returns:
        The registry stored on ``app.state`` by the app factory.
    """
    return request.app.state.registry


def require_admin(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """FastAPI dependency guarding admin routes.

    When ``ADMIN_TOKEN`` is not configured the routes stay open, matching the
    previous behaviour; set it in any deployment reachable from outside.

    Args:
        request: Incoming request.
        authorization: Value of the ``Authorization`` header.

    Raises:
        HTTPException: 401 if a token is configured and the request lacks it.
    """
    settings: Settings = request.app.state.settings
    if settings.admin_token is None:
        return
    expected = f"Bearer {settings.admin_token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing admin token.")


def _load_or_404(registry: AgentRegistry, slug: str) -> LoadedAgent:
    """Loads an agent, mapping a missing bundle to HTTP 404.

    Args:
        registry: Agent registry.
        slug: Agent slug from the URL.

    Returns:
        The loaded agent.

    Raises:
        HTTPException: 404 if no bundle exists for ``slug``.
    """
    try:
        return registry.get(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


router = APIRouter(prefix="/agents/{slug}")


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_token)])
async def chat(
    slug: str, req: ChatRequest, registry: Annotated[AgentRegistry, Depends(get_registry)]
) -> ChatResponse:
    """Runs one turn of an agent.

    Args:
        slug: Agent slug.
        req: Turn input.
        registry: Agent registry.

    Returns:
        The agent's messages and conversation status.

    Raises:
        HTTPException: 404 for an unknown agent; 422 if continuing without a message.
    """
    agent = _load_or_404(registry, slug)
    config = {"configurable": {"thread_id": req.thread_id}}
    buffer: list[str] = []
    message_buffer.set(buffer)

    snapshot = agent.graph.get_state(config)
    resolution = resolve_session(snapshot.values, agent.artifact.session_timeout_minutes)
    if resolution == "continuing" and not (snapshot.next or snapshot.interrupts):
        # A thread parked on a terminal node has nothing to resume; elapsed time alone
        # (all resolve_session knows) would wrongly call it "continuing".
        resolution = "new"
    logger.info("[%s] thread=%s session=%s", slug, req.thread_id, resolution)

    # graph.invoke() blocks and its tools call this same server over HTTP, so it must run off
    # the event loop or the self-call deadlocks until the tool timeout.
    if resolution in ("new", "stale"):
        result = await run_in_threadpool(
            agent.graph.invoke, fresh_state(agent.artifact, contact=req.contact), config
        )
    else:
        if not req.message:
            raise HTTPException(status_code=422, detail="message is required to continue an existing session.")
        result = await run_in_threadpool(agent.graph.invoke, Command(resume=req.message), config)

    interrupts = result.get("__interrupt__")
    if interrupts:
        buffer.extend(interrupts[0].value.get("prompt", []))
    return ChatResponse(
        messages=buffer,
        conversation_ended=not interrupts,
        current_state=agent.graph.get_state(config).values.get("current_state"),
    )


@router.post("/reset", dependencies=[Depends(require_admin)])
async def reset(
    slug: str, thread_id: str, registry: Annotated[AgentRegistry, Depends(get_registry)]
) -> dict:
    """Wipes one thread's checkpoint so the next chat starts a new session.

    Args:
        slug: Agent slug.
        thread_id: Conversation to wipe.
        registry: Agent registry.

    Returns:
        Confirmation payload.
    """
    agent = _load_or_404(registry, slug)
    agent.graph.checkpointer.delete_thread(thread_id)
    return {"reset": True, "thread_id": thread_id}


@router.post("/admin/reload", dependencies=[Depends(require_admin)])
async def reload_agent(slug: str, registry: Annotated[AgentRegistry, Depends(get_registry)]) -> dict:
    """Rebuilds an agent from the bundle files currently on disk.

    Call it after copying new generated files into the bundle; no restart needed.
    Tool plugin code changes still require a restart.

    Args:
        slug: Agent slug.
        registry: Agent registry.

    Returns:
        Confirmation with the reloaded ``agent_id``.

    Raises:
        HTTPException: 404 if the bundle does not exist.
    """
    try:
        agent = await run_in_threadpool(registry.reload, slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"reloaded": True, "agent_id": agent.artifact.agent_id}
