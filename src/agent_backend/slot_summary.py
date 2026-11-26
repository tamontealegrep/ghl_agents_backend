"""Compact summary of the available slots, one entry per day, with typed time blocks.

The slot list has one entry every few minutes (hundreds of lines): a model that has to read it to say
which days are free can miss most of it and invent dates. This summary is built by code from the same slots,
so the days, parts of the day and time blocks the agent says always come from the real availability.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
# [start hour, end hour): morning 06-12, afternoon 12-18, evening 18-21, night 21-06.
_PARTS = (("morning", 6, 12), ("afternoon", 12, 18), ("evening", 18, 21))


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def _label(day: date) -> str:
    return f"{_WEEKDAYS[day.weekday()]}, {_MONTHS[day.month - 1]} {day.day}"


def _offset(moment: datetime) -> str:
    """``+01:00`` / ``-05:00`` / ``+05:30``: the UTC offset of ``moment``."""
    total = int(moment.utcoffset().total_seconds() // 60) if moment.utcoffset() is not None else 0
    sign = "+" if total >= 0 else "-"
    hours, minutes = divmod(abs(total), 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def _part_of(hour: int) -> str:
    return next((name for name, start, end in _PARTS if start <= hour < end), "night")


def _blocks(times: list[str], step: int) -> list[dict[str, Any]]:
    """Sorted HH:MM start times as typed blocks: consecutive ones (``step`` apart) form a continuous_range."""
    runs: list[list[str]] = []
    for clock in times:
        if runs and _minutes(clock) - _minutes(runs[-1][-1]) == step:
            runs[-1].append(clock)
        else:
            runs.append([clock])
    return [
        {"type": "single_slot", "start": run[0]}
        if len(run) == 1
        else {"type": "continuous_range", "first_start": run[0], "last_start": run[-1], "every_minutes": step}
        for run in runs
    ]


def summarize_days(slot_starts: list[str], timezone: str) -> list[dict[str, Any]]:
    """Groups slot start times (ISO 8601 with offset) by day.

    Args:
        slot_starts: The ``start_local`` of every offered slot: ISO 8601 in the contact's time zone, so the day, the
            part of the day and the times are all the contact's own, not the company's.
        timezone: IANA name of that time zone, echoed on every day.

    Returns:
        One dict per day, soonest first: ``date`` (YYYY-MM-DD, the contact's local date), ``label`` (English weekday,
        month and day), ``timezone`` (IANA) and ``utc_offset`` (``+01:00``) of that day,
        ``parts_of_day`` (morning, afternoon, evening or night, those that have slots), ``times`` (typed blocks:
        ``continuous_range`` with first_start, last_start and every_minutes, or ``single_slot`` with start)
        and ``slot_count``.
    """
    by_day: dict[date, list[str]] = {}
    offsets: dict[date, str] = {}
    for start in slot_starts:
        moment = datetime.fromisoformat(start)
        by_day.setdefault(moment.date(), []).append(f"{moment.hour:02d}:{moment.minute:02d}")
        offsets.setdefault(moment.date(), _offset(moment))
    gaps = [
        _minutes(b) - _minutes(a) for times in by_day.values() for a, b in zip(sorted(times), sorted(times)[1:], strict=False)
    ]
    step = min(gaps) if gaps else 30
    days = []
    for day in sorted(by_day):
        times = sorted(set(by_day[day]))
        parts = {_part_of(_minutes(t) // 60) for t in times}
        days.append(
            {
                "date": day.isoformat(),
                "label": _label(day),
                "timezone": timezone,
                "utc_offset": offsets[day],
                "parts_of_day": [name for name in ("morning", "afternoon", "evening", "night") if name in parts],
                "times": _blocks(times, step),
                "slot_count": len(times),
            }
        )
    return days
