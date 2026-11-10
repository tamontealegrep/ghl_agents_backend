"""Rules that decide which GoHighLevel slots Family Aims offers or accepts.

GHL calculates the free slots of a calendar from its own settings. These helpers add the
parameters of the company's ``.env`` on top of that: slots that break them are discarded
and the rest is offered. See ``agent_backend.slot_filters`` for the filters themselves.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from agent_backend.ghl_scheduling import load_busy  # noqa: F401  (shared with every company)

from .slot_engine import compute_start_date

# GET /calendars/{id}/free-slots rejects ranges longer than this (GoHighLevel documentation).
GHL_MAX_RANGE_DAYS = 31


def earliest_start(now: datetime, tool: Any) -> datetime:
    """Returns the first moment a slot may start.

    Args:
        now: Current time, timezone-aware.
        tool: Calendar settings (``min_notice_minutes``).

    Returns:
        ``now`` plus the calendar's minimum notice when it is set; otherwise the
        company's own rule (``slot_engine.compute_start_date``).
    """
    if tool.min_notice_minutes is not None:
        return now + timedelta(minutes=tool.min_notice_minutes)
    return compute_start_date(now)


def range_error(tool: Any, variable: str) -> Optional[str]:
    """Checks that the configured date range fits GoHighLevel's free-slots limit.

    Args:
        tool: Calendar settings (``date_range_days``).
        variable: Name of the variable to blame in the message.

    Returns:
        An error message, or None when the range is acceptable.
    """
    if tool.date_range_days > GHL_MAX_RANGE_DAYS:
        return f"{variable} is {tool.date_range_days}; GoHighLevel free-slots accepts at most {GHL_MAX_RANGE_DAYS} days"
    return None
