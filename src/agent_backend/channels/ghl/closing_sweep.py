"""Background job that sends the closing message to threads inactive for a day."""

from __future__ import annotations

import asyncio
import logging
import os

import httpx
from starlette.concurrency import run_in_threadpool

from agent_backend.channels.ghl.client import (
    send_ghl_message_async,
)
from agent_backend.channels.ghl.config import CompiledAgentGhlConfig, _closing_message_text
from agent_backend.channels.ghl.text import normalize_channel
from agent_backend.persistence.postgres import (
    claim_conversations_needing_closing_message,
    mark_closing_message_sent,
    reset_closing_message_claim,
)


async def run_closing_sweep_once(cfg: CompiledAgentGhlConfig) -> int:
    """One pass: find every thread of `cfg.slug` sitting at 23:45+ of inactivity with no closing message sent yet for this window, and send one.

    Module-level (not a closure inside build_compiled_agent_router) so it's directly testable/callable without spinning up the router.

    Deliberately bypasses the compiled graph entirely -- there's no new
    user message to run it against, and the message is intentionally
    generic (see CompiledAgentGhlConfig.closing_message's own docstring),
    so a direct send_ghl_message_async call is simpler and correct.

    Returns how many closing messages were actually sent (tests read this;
    production code doesn't need to).
    """
    logger = logging.getLogger(f"compiled_runner.ghl_endpoint.{cfg.slug}")
    # Atomically claim candidates to avoid duplicate sends across processes
    candidates = await run_in_threadpool(
        claim_conversations_needing_closing_message, cfg.slug, cfg.closing_message_lookback_days
    )
    sent = 0
    for row in candidates:
        thread_id = row["thread_id"]
        try:
            # If conversation was widget and the agent is configured
            # to redirect, send closing message via WhatsApp (2026-09-30)
            reply_channel = row.get("channel")
            if cfg.redirect_widget_to_whatsapp:
                ch = normalize_channel(reply_channel)
                if ch in {"LIVE_CHAT", "WEBCHAT", "TYPE_WEBCHAT"}:
                    reply_channel = "WHATSAPP"

            # Send directly; if GHL rejects (e.g., missing contact/conversation),
            # we'll catch the error and release the claim below.
            await send_ghl_message_async(
                contact_id=row["contact_id"],
                message=_closing_message_text(cfg, row.get("preferred_language")),
                channel=reply_channel,
                exec_id=f"{cfg.slug}:closing:{thread_id}",
                config=cfg.ghl_client_config(),
                location_id=row["location_id"],
                logger=logger,
            )
            logger.info("[%s] Closing message sent after ~24h of inactivity.", thread_id)
            sent += 1
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else None
            canonical = None
            try:
                canonical = (exc.response.json() if exc.response is not None else {}).get("canonicalCode")
            except Exception:
                canonical = None
            if code == 400 and canonical == "CONVERSATIONS_CONTACT_NOT_FOUND":
                logger.warning(
                    "[%s] Skipping closing message: contact not found (400, canonical=%s).",
                    thread_id,
                    canonical,
                )
                # Do not retry this window: mark as sent to suppress future picks
                try:
                    await run_in_threadpool(
                        mark_closing_message_sent, cfg.slug, row["location_id"], row["contact_id"]
                    )
                except Exception:
                    logger.warning(
                        "[%s] Failed to mark closing message sent after contact-missing (non-fatal).",
                        thread_id,
                        exc_info=True,
                    )
            else:
                logger.error("[%s] Failed to send closing message.", thread_id, exc_info=True)
                # Allow a future sweep to retry: clear claim
                try:
                    await run_in_threadpool(
                        reset_closing_message_claim, cfg.slug, row["location_id"], row["contact_id"]
                    )
                except Exception:
                    logger.warning(
                        "[%s] Failed to reset closing message claim after send error (non-fatal).",
                        thread_id,
                        exc_info=True,
                    )
        except Exception:
            logger.error("[%s] Failed to send closing message.", thread_id, exc_info=True)
            try:
                await run_in_threadpool(
                    reset_closing_message_claim, cfg.slug, row["location_id"], row["contact_id"]
                )
            except Exception:
                logger.warning(
                    "[%s] Failed to reset closing message claim after send error (non-fatal).",
                    thread_id,
                    exc_info=True,
                )
    return sent


async def _closing_sweep_loop(cfg: CompiledAgentGhlConfig) -> None:
    logger = logging.getLogger(f"compiled_runner.ghl_endpoint.{cfg.slug}")
    interval_seconds = float(os.getenv("CLOSING_MESSAGE_SWEEP_INTERVAL_SECONDS", "300"))
    startup_delay = float(os.getenv("CLOSING_MESSAGE_SWEEP_STARTUP_DELAY_SECONDS", "10"))
    # Give the app a brief window to handle first user messages on cold start
    # before the sweep kicks in (avoids contention in serverless environments).
    if startup_delay > 0:
        try:
            await asyncio.sleep(startup_delay)
        except asyncio.CancelledError:
            return
    while True:
        try:
            await run_closing_sweep_once(cfg)
        except Exception:
            logger.error("Closing-message sweep iteration failed.", exc_info=True)
        await asyncio.sleep(interval_seconds)
