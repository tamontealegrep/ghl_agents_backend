"""
Unit tests for agent_runtime.runtime.session_resolver — new/continuing/stale resolution.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent_runtime.runtime.session_resolver import now_iso, resolve_session


def test_no_values_is_new():
    assert resolve_session(None, timeout_minutes=None) == "new"


def test_empty_values_is_new():
    assert resolve_session({}, timeout_minutes=None) == "new"


def test_values_without_current_state_is_new():
    assert resolve_session({"current_state": ""}, timeout_minutes=None) == "new"


def test_continuing_when_no_timeout_configured():
    values = {"current_state": "ASKING_NAME", "last_message_at": now_iso()}
    assert resolve_session(values, timeout_minutes=None) == "continuing"


def test_continuing_when_within_timeout():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    last_message_at = (base - timedelta(minutes=5)).isoformat()
    values = {"current_state": "ASKING_NAME", "last_message_at": last_message_at}
    assert resolve_session(values, timeout_minutes=10, now=base) == "continuing"


def test_stale_when_gap_exceeds_timeout():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    last_message_at = (base - timedelta(minutes=15)).isoformat()
    values = {"current_state": "ASKING_NAME", "last_message_at": last_message_at}
    assert resolve_session(values, timeout_minutes=10, now=base) == "stale"


def test_continuing_when_last_message_at_missing_even_with_timeout():
    values = {"current_state": "ASKING_NAME"}
    assert resolve_session(values, timeout_minutes=10) == "continuing"


def test_now_iso_returns_a_parseable_utc_timestamp():
    parsed = datetime.fromisoformat(now_iso())
    assert parsed.tzinfo is not None
