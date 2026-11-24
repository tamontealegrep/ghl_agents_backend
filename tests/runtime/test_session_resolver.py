"""
Unit tests for agent_runtime.runtime.session_resolver — new/continuing/stale resolution.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent_runtime.runtime.session_resolver import now_iso, resolve_session


def test_no_values_is_new():
    """No values means a new session."""
    assert resolve_session(None, timeout_minutes=None) == "new"


def test_empty_values_is_new():
    """Empty values mean a new session."""
    assert resolve_session({}, timeout_minutes=None) == "new"


def test_values_without_current_state_is_new():
    """Values without a current state mean a new session."""
    assert resolve_session({"current_state": ""}, timeout_minutes=None) == "new"


def test_continuing_without_timeout():
    """A session continues when no timeout is configured."""
    values = {"current_state": "ASKING_NAME", "last_message_at": now_iso()}
    assert resolve_session(values, timeout_minutes=None) == "continuing"


def test_continuing_when_within_timeout():
    """A session continues when within the timeout."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    last_message_at = (base - timedelta(minutes=5)).isoformat()
    values = {"current_state": "ASKING_NAME", "last_message_at": last_message_at}
    assert resolve_session(values, timeout_minutes=10, now=base) == "continuing"


def test_stale_when_gap_exceeds_timeout():
    """A session is stale when the gap exceeds the timeout."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    last_message_at = (base - timedelta(minutes=15)).isoformat()
    values = {"current_state": "ASKING_NAME", "last_message_at": last_message_at}
    assert resolve_session(values, timeout_minutes=10, now=base) == "stale"


def test_continuing_without_last_message():
    """A session continues when there is no last-message time, even with a timeout."""
    values = {"current_state": "ASKING_NAME"}
    assert resolve_session(values, timeout_minutes=10) == "continuing"


def test_now_iso_is_parseable():
    """`now_iso` returns a parseable, timezone-aware timestamp."""
    parsed = datetime.fromisoformat(now_iso())
    assert parsed.tzinfo is not None
