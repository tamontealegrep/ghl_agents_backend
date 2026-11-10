"""GoHighLevel scheduling tools of BabyNova.

The logic is shared by every company (``agent_backend.ghl_scheduling``); this file only says how
BabyNova finds its calendars, its default minimum notice and how it tells its team.
"""

from datetime import date, datetime, timedelta

from agent_backend.ghl_scheduling import GhlSchedulingHooks, build_ghl_scheduling_router

from ....core.config import BUSINESS_TZ, get_settings
from agent_backend import date_formatting
from ....services import slot_calculator
from ....services.calendars import resolve_calendar, unknown_calendar_message
from ....services.notifications import notify_booking
from agent_backend.timezones import build_business_instant


def _default_earliest(now: datetime) -> datetime:
    """First moment a slot may start when no minimum notice is configured: the day after the next business day."""
    year, month, day = (int(part) for part in slot_calculator.compute_processing_day_key(now).split("-"))
    after = date(year, month, day) + timedelta(days=1)
    return build_business_instant(after.year, after.month, after.day, 0, 0, BUSINESS_TZ)


def _format_start(moment: datetime) -> str:
    return f"{date_formatting.format_full_date(moment, 'EN')} at {date_formatting.format_booking_time(moment, 'EN')}"


router = build_ghl_scheduling_router(
    GhlSchedulingHooks(
        prefix="BN",
        # resolved at call time so tests (and reloads) can replace them
        get_settings=lambda: get_settings(),
        resolve_calendar=lambda settings, calendar_type: resolve_calendar(settings, calendar_type),
        unknown_calendar_message=lambda settings, calendar_type: unknown_calendar_message(settings, calendar_type),
        default_earliest=_default_earliest,
        notify_booking=lambda *args, **kwargs: notify_booking(*args, **kwargs),
        format_start=_format_start,
        business_tz=BUSINESS_TZ,
    )
)
