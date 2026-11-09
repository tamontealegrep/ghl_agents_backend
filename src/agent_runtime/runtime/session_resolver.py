"""
Session resolver — decides new / continuing / stale BEFORE the graph is invoked.

    Lives outside the LangGraph graph on purpose (DESIGN_PATTERNS.md P03): the
    caller has to decide which of `invoke(fresh_state, config)` or
    `invoke(Command(resume=...), config)` to use before the graph can even be
    called, and a graph node only ever runs after that decision has already
    been made. `graph.get_state(config)` doubles as the session store: an
    empty `.values` means no checkpoint exists yet for this thread_id (brand
    new).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

SessionResolution = Literal["new", "continuing", "stale"]


def now_iso() -> str:
    """Current UTC timestamp, ISO-8601 — the format stored in `last_message_at`.
    """
    return datetime.now(UTC).isoformat()


def resolve_session(
    values: dict[str, Any] | None,
    timeout_minutes: float | None,
    *,
    now: datetime | None = None,
) -> SessionResolution:
    """Return `"new"`, `"continuing"`, or `"stale"`.

    Args:
        values: `graph.get_state(config).values`, or
            `None`/empty for a thread_id with no checkpoint yet.
        timeout_minutes: `None` means a session never goes stale.
        now: Injected for deterministic tests; defaults to
            the real current UTC time. Staleness must be measured against
            the moment the reply actually arrived, not against when the
            question was asked — callers resolve staleness AFTER waiting
            for the reply, not before.

    Returns:
        SessionResolution: `"new"` when no checkpoint exists yet for this
        session key; `"stale"` when `timeout_minutes` is set and more
        time than that has elapsed since `last_message_at`;
        `"continuing"` otherwise.
    """
    if not values or not values.get("current_state"):
        return "new"
    if timeout_minutes is not None:
        last_message_at = values.get("last_message_at")
        if last_message_at:
            current = now or datetime.now(UTC)
            elapsed_minutes = (
                current - datetime.fromisoformat(last_message_at)
            ).total_seconds() / 60
            if elapsed_minutes > timeout_minutes:
                return "stale"
    return "continuing"
