"""Generic GHL webhook -> compiled LangGraph agent -> GHL reply endpoint.

Every compiled agent wired to a real GHL webhook needs the exact same
plumbing (202 immediately, per-thread debounce, session resolution with
the terminal-state fix, run_in_threadpool for the graph.invoke() deadlock,
idempotency by execution_id, reply via send_ghl_message_async, mirror the
turn into `conversations`). Only the agent identity, phone allowlist, and
debounce window differ -- see family_aims_sam_text/endpoint.py's own
docstring for the diagnosis behind each of the fixes baked in here. One
agent's endpoint module is now just a `CompiledAgentGhlConfig` plus a call
to `build_compiled_agent_router` instead of duplicating this file.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from fastapi import APIRouter, status
from langgraph.types import Command
from starlette.concurrency import run_in_threadpool

from agent_backend.channels.ghl.client import (
    GhlClientConfig,
    search_conversation_channel_async,
    send_ghl_message_async,
)
from agent_backend.channels.ghl.closing_sweep import _closing_sweep_loop
from agent_backend.channels.ghl.config import (
    GHL_TEXT_SESSION_TIMEOUT_MINUTES,
    CompiledAgentGhlConfig,
    _normalize_phone,
    _strip_reset_marker,
    _unsupported_media_text,
)
from agent_backend.channels.ghl.request import GhlAgentRequest
from agent_backend.channels.ghl.runner import derive_execution_id
from agent_backend.channels.ghl.text import normalize_channel
from agent_backend.loader import AgentRegistry, message_buffer
from agent_backend.persistence.postgres import (
    postgres_enabled,
    upsert_conversation,
)
from agent_runtime.runtime.graph_builder import fresh_state
from agent_runtime.runtime.session_resolver import resolve_session


@dataclass
class _PendingTurn:
    """Text accumulated for one thread_id, waiting out the debounce window."""

    execution_ids: list[str] = field(default_factory=list)
    message_parts: list[str] = field(default_factory=list)
    last_request: GhlAgentRequest | None = None
    flush_task: asyncio.Task | None = None


async def resolve_reply_channel(
    request: GhlAgentRequest,
    remembered: str | None,
    config: GhlClientConfig,
    logger: logging.Logger,
) -> str | None:
    """Returns the channel a reply goes out through.

    A payload without message.type (the one a workflow
    sends when the contact is created by their first message) carries no channel, and a reply
    with none falls to the default Live_Chat. Order: the payload, the last channel seen on this
    thread, the contact's conversation in GHL, then a WhatsApp attribution medium. When none is
    usable the payload's own value is returned and the default applies.
    """

    def usable(channel: str | None) -> bool:
        return normalize_channel(channel) in config.channel_type_map

    channel = request.channel
    if not usable(channel):
        channel = remembered
    if not usable(channel) and request.location_id:
        channel = await search_conversation_channel_async(
            request.contact_id, request.location_id, config, logger
        )
    if not usable(channel):
        contact = request.contact or {}
        sources = (contact.get("lastAttributionSource"), contact.get("attributionSource"))
        if any(
            isinstance(src, dict) and normalize_channel(src.get("medium")) == "WHATSAPP" for src in sources
        ):
            channel = "WHATSAPP"
    return channel if usable(channel) else request.channel


def build_compiled_agent_router(cfg: CompiledAgentGhlConfig, registry: AgentRegistry) -> APIRouter:
    """Build a self-contained router for one compiled agent's GHL webhook.

    State (processing_messages, pending turns) is local to this call, so
    two agents built from this factory never share or race on each
    other's in-flight messages, even though the shapes are identical.

    Args:
        cfg: Identity, phone allow-list, debounce and messages of the agent.
        registry: Source of the loaded agent graphs.

    Returns:
        The router with the agent's webhook route.
    """
    router = APIRouter()
    logger = logging.getLogger(f"compiled_runner.ghl_endpoint.{cfg.slug}")

    processing_messages: set[str] = set()
    pending_turns: dict[str, _PendingTurn] = {}
    turn_locks: dict[str, asyncio.Lock] = {}
    known_channels: dict[str, str] = {}

    async def _resolve_channel(request: GhlAgentRequest, thread_id: str, execution_id: str) -> str | None:
        channel = await resolve_reply_channel(
            request, known_channels.get(thread_id), cfg.ghl_client_config(), logger
        )
        if normalize_channel(channel) and normalize_channel(request.channel) != normalize_channel(channel):
            logger.info(
                "[%s] Payload had no usable channel (%r); replying through %s.",
                execution_id,
                request.channel,
                channel,
            )
        if channel and normalize_channel(channel) in cfg.ghl_client_config().channel_type_map:
            known_channels[thread_id] = channel
        return channel

    # Not a locally-scoped subclass: with `from __future__ import
    # annotations`, FastAPI resolves a parameter's type hint by name from
    # the function's __globals__ at route-registration time -- a class
    # defined inside this factory function isn't reachable that way, so
    # `request` silently fell back to being treated as a query param
    # instead of the JSON body (found live: every call 422'd on "request
    # missing"). GhlAgentRequest is already generic across agents, so
    # there's nothing a subclass would add here anyway.
    @router.post(cfg.path, status_code=status.HTTP_202_ACCEPTED)
    async def endpoint(request: GhlAgentRequest):
        phone = _normalize_phone((request.contact or {}).get("phone"))
        if cfg.enforce_phone_whitelist and phone not in cfg.allowed_phones:
            logger.info("Ignoring message from non-allowed phone: %s", phone)
            return {"status": "ignored", "reason": "phone_not_allowed"}

        if not request.location_id or not request.contact_id:
            logger.warning("Missing location_id/contact_id, dropping request.")
            return {"status": "ignored", "reason": "missing_ids"}

        execution_id = derive_execution_id(request, prefix=cfg.slug)
        logger.info(
            "[%s] Received request: conversation_id=%s contact_id=%s location_id=%s",
            execution_id,
            request.conversation_id,
            request.contact_id,
            request.location_id,
        )

        if execution_id in processing_messages:
            logger.info("[%s] Already processing/processed, skipping.", execution_id)
            return {"status": "duplicate", "execution_id": execution_id}
        processing_messages.add(execution_id)

        # Prefixed with the agent slug: makes "which agent is this" visible
        # at a glance in a shared Postgres, and keeps two different agents
        # talking to the same contact from colliding on the exact same
        # thread_id and corrupting each other's state.
        thread_id = f"{cfg.slug}:{request.location_id}:{request.contact_id}"
        turn = pending_turns.get(thread_id)
        if turn is None:
            turn = _PendingTurn()
            pending_turns[thread_id] = turn
        elif turn.flush_task is not None:
            turn.flush_task.cancel()

        turn.execution_ids.append(execution_id)
        if request.message:
            turn.message_parts.append(str(request.message))
        turn.last_request = request
        turn.flush_task = asyncio.create_task(_debounced_flush(thread_id))

        return {"status": "accepted", "execution_id": execution_id, "debounce_seconds": cfg.debounce_seconds}

    async def _debounced_flush(thread_id: str) -> None:
        try:
            await asyncio.sleep(cfg.debounce_seconds)
            # The turn stays pending while it waits for the conversation's previous turn:
            # a message that arrives meanwhile is merged into it (and restarts this flush).
            lock = turn_locks.setdefault(thread_id, asyncio.Lock())
            holds_lock = False
            try:
                await asyncio.wait_for(lock.acquire(), timeout=cfg.turn_lock_timeout_seconds)
                holds_lock = True
            except TimeoutError:
                logger.warning(
                    "[%s] Previous turn still running after %ss; running this one anyway.",
                    thread_id,
                    cfg.turn_lock_timeout_seconds,
                )
        except asyncio.CancelledError:
            return  # a newer message reset the timer -- this flush is stale

        try:
            turn = pending_turns.pop(thread_id, None)
            if turn is None:
                return
            await _run_turn(thread_id, turn)
        finally:
            if holds_lock:
                lock.release()
            if not lock.locked() and thread_id not in pending_turns and turn_locks.get(thread_id) is lock:
                turn_locks.pop(thread_id, None)

    async def _run_turn(thread_id: str, turn: _PendingTurn) -> None:
        request = turn.last_request
        if request is None:
            return
        combined_message = "\n".join(turn.message_parts).strip()
        combined_message, reset_requested = _strip_reset_marker(combined_message)
        execution_id = turn.execution_ids[-1]
        logger.info(
            "[%s] Combined inbound length=%s part_count=%s",
            execution_id,
            len(combined_message),
            len(turn.message_parts),
        )
        if len(turn.execution_ids) > 1:
            logger.info(
                "[%s] Flushing %s buffered message(s) for thread=%s after %ss of inactivity.",
                execution_id,
                len(turn.execution_ids),
                thread_id,
                cfg.debounce_seconds,
            )

        try:
            config = {"configurable": {"thread_id": thread_id}}
            loaded = registry.get(cfg.slug)
            artifact, graph = loaded.artifact, loaded.graph

            buffer: list[str] = []
            message_buffer.set(buffer)

            snapshot = graph.get_state(config)
            resolution = resolve_session(snapshot.values, GHL_TEXT_SESSION_TIMEOUT_MINUTES)
            if resolution == "continuing" and not (snapshot.next or snapshot.interrupts):
                # resolve_session only knows elapsed time, not whether the
                # graph actually has a pending interrupt -- a thread that
                # already reached a terminal node (snapshot.next == ()) has
                # nothing to resume, so Command(resume=...) would silently
                # do nothing. Treat this as the start of a fresh conversation.
                # A question that re-asks itself after a global-router match
                # (e.g. a language switch) is pending in snapshot.interrupts
                # while snapshot.next is already empty -- that one resumes.
                resolution = "new"
            if reset_requested:
                resolution = "new"
                logger.info("[%s] Reset marker detected -- forcing a fresh conversation.", execution_id)
            logger.info("[%s] thread=%s session=%s", execution_id, thread_id, resolution)

            # graph.invoke() is synchronous and blocking; a tool call this
            # graph makes (e.g. check_visa) hits this same server over HTTP,
            # so it must run off the event loop or that self-call deadlocks
            # against the frozen loop until the tool's own timeout kills it.
            if resolution in ("new", "stale"):
                state = fresh_state(
                    artifact,
                    contact=request.contact,
                    seed_history=[f"user: {combined_message}"] if combined_message else [],
                    seed_last_user_message=combined_message,
                )
                result = await run_in_threadpool(graph.invoke, state, config)
            else:
                if not combined_message:
                    # No text mid-conversation: a video, audio or sticker. Answer with the fixed
                    # message and leave the graph (and its pending question) untouched.
                    slots = (snapshot.values or {}).get("slots") or {}
                    language = slots.get("preferred_language") or (request.contact or {}).get("language")
                    buffer.append(_unsupported_media_text(cfg, language))
                    result = {}
                else:
                    result = await run_in_threadpool(graph.invoke, Command(resume=combined_message), config)

            interrupts = result.get("__interrupt__")
            if interrupts:
                buffer.extend(interrupts[0].value.get("prompt", []))

            final_state = graph.get_state(config).values
            channel = await _resolve_channel(request, thread_id, execution_id)
            upsert_conversation(
                thread_id=thread_id,
                agent_slug=cfg.slug,
                location_id=request.location_id or "",
                contact_id=request.contact_id,
                contact=final_state.get("contact"),
                slots=final_state.get("slots"),
                current_state=final_state.get("current_state"),
                last_user_message=final_state.get("last_user_message"),
                history=final_state.get("history"),
                channel=channel,
            )

            reply_text = "\n\n".join(buffer).strip()
            if reply_text:
                # If message came from widget and the agent is configured,
                # respond via WhatsApp (2026-09-30). Accept common synonyms.
                reply_channel = channel
                if cfg.redirect_widget_to_whatsapp:
                    ch = normalize_channel(reply_channel)
                    if ch in {"LIVE_CHAT", "WEBCHAT", "TYPE_WEBCHAT"}:
                        logger.info(
                            "[%s] Inbound channel was widget (%s), redirecting reply to WHATSAPP.",
                            execution_id,
                            ch,
                        )
                        reply_channel = "WHATSAPP"

                await send_ghl_message_async(
                    contact_id=request.contact_id,
                    message=reply_text,
                    channel=reply_channel,
                    exec_id=execution_id,
                    config=cfg.ghl_client_config(),
                    location_id=request.location_id,
                    reply_message_id=request.messageId,
                    logger=logger,
                )
                logger.info("[%s] Reply sent to GHL.", execution_id)
            else:
                logger.info(
                    "[%s] No reply text (empty buffer). resolution=%s combined_len=%s interrupts=%s",
                    execution_id,
                    resolution,
                    len(combined_message),
                    bool(interrupts),
                )

        except Exception:
            logger.error("[%s] Background execution failed.", execution_id, exc_info=True)
        finally:
            for eid in turn.execution_ids:
                processing_messages.discard(eid)

    background_tasks: set[asyncio.Task] = set()

    @router.on_event("startup")
    async def _start_closing_sweep() -> None:
        if postgres_enabled():
            task = asyncio.create_task(_closing_sweep_loop(cfg))
            background_tasks.add(task)  # keep a reference so the task is not garbage-collected
            task.add_done_callback(background_tasks.discard)

    return router
