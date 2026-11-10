"""Pure filters that discard time slots which do not meet a calendar's own parameters.

GoHighLevel computes the free slots of a calendar with the settings stored in GHL.
The functions here only *discard* slots that break the parameters configured in the
company's ``.env`` (interval, buffers, minimum notice, date range); what is left is what
the agent may offer. They never add a slot, so applying them on top of slots that GHL
already filtered is harmless.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

__all__ = [
    "Busy",
    "conflicts_with_busy",
    "drop_after",
    "drop_before",
    "drop_conflicting",
    "parse_busy",
    "thin_by_interval",
]

Busy = tuple[datetime, datetime]

_START_KEYS = ("startTime", "start_time", "start")
_END_KEYS = ("endTime", "end_time", "end")


def _parse(value: Any) -> datetime | None:
    """Parses an ISO 8601 string; naive values are taken as UTC.

    Args:
        value: Candidate value.

    Returns:
        A timezone-aware datetime, or None when the value is not a date string.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_busy(events: Iterable[Mapping[str, Any]]) -> list[Busy]:
    """Turns calendar events into busy intervals.

    Args:
        events: Events as returned by the calendar API (``startTime``/``endTime`` or
            ``start_time``/``end_time`` or ``start``/``end``).

    Returns:
        ``(start, end)`` pairs. Cancelled events and events whose dates cannot be
        read are skipped.
    """
    busy: list[Busy] = []
    for event in events:
        if str(event.get("status", "")).lower() == "cancelled":
            continue
        start = next((d for k in _START_KEYS if (d := _parse(event.get(k)))), None)
        end = next((d for k in _END_KEYS if (d := _parse(event.get(k)))), None)
        if start and end and end > start:
            busy.append((start, end))
    return busy


def conflicts_with_busy(start: datetime, end: datetime, busy: Iterable[Busy], pre_buffer_minutes: int = 0, post_buffer_minutes: int = 0) -> bool:
    """Tells whether a slot overlaps an existing appointment together with its buffers.

    Every existing appointment blocks its own time plus ``pre_buffer_minutes`` before it
    and ``post_buffer_minutes`` after it, the way a GHL calendar blocks "extra time ...
    to get ready" and "to wrap up". The slot itself is compared as is.

    Args:
        start: Slot start.
        end: Slot end.
        busy: Existing appointments as busy intervals.
        pre_buffer_minutes: Free time kept before each existing appointment.
        post_buffer_minutes: Free time kept after each existing appointment.

    Returns:
        True when the slot overlaps a blocked interval. Touching edges do not overlap.
    """
    before = timedelta(minutes=pre_buffer_minutes)
    after = timedelta(minutes=post_buffer_minutes)
    return any(b_start - before < end and b_end + after > start for b_start, b_end in busy)


def drop_conflicting(
    starts: Iterable[datetime],
    duration_minutes: int,
    busy: Iterable[Busy],
    pre_buffer_minutes: int = 0,
    post_buffer_minutes: int = 0,
) -> list[datetime]:
    """Discards the slots that fall inside an existing appointment or its buffers.

    Args:
        starts: Slot start times.
        duration_minutes: Appointment length.
        busy: Existing appointments as busy intervals.
        pre_buffer_minutes: Free time kept before each existing appointment.
        post_buffer_minutes: Free time kept after each existing appointment.

    Returns:
        The slots that respect every buffer, in the original order.
    """
    busy = list(busy)
    length = timedelta(minutes=duration_minutes)
    return [s for s in starts if not conflicts_with_busy(s, s + length, busy, pre_buffer_minutes, post_buffer_minutes)]


def drop_before(starts: Iterable[datetime], earliest: datetime) -> list[datetime]:
    """Discards slots that start before ``earliest`` (minimum notice).

    Args:
        starts: Slot start times.
        earliest: First acceptable start.

    Returns:
        The slots starting at or after ``earliest``.
    """
    return [s for s in starts if s >= earliest]


def drop_after(starts: Iterable[datetime], latest: datetime) -> list[datetime]:
    """Discards slots that start after ``latest`` (date range).

    Args:
        starts: Slot start times.
        latest: Last acceptable start.

    Returns:
        The slots starting at or before ``latest``.
    """
    return [s for s in starts if s <= latest]


def thin_by_interval(starts: Iterable[datetime], interval_minutes: int) -> list[datetime]:
    """Keeps slots at least ``interval_minutes`` apart, counted per calendar day.

    Args:
        starts: Slot start times.
        interval_minutes: Minimum distance between two kept starts of the same day;
            0 or less keeps every slot.

    Returns:
        The kept slots in chronological order. The first slot of each day is always kept.
    """
    ordered = sorted(starts)
    if interval_minutes <= 0:
        return ordered
    gap = timedelta(minutes=interval_minutes)
    kept: list[datetime] = []
    for slot in ordered:
        last = kept[-1] if kept else None
        if last is None or slot.date() != last.date() or slot - last >= gap:
            kept.append(slot)
    return kept
