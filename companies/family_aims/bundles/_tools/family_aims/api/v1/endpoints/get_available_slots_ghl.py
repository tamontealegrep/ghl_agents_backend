from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter

from ....core.config import get_settings
from ....schemas.slots import SlotsRequest, SlotsResponse, Slot
from ....services.calendars import resolve_calendar, unknown_calendar_message
from agent_backend.slot_filters import conflicts_with_busy, thin_by_interval

from ....services.slot_engine import compute_end_date, is_holiday, BUSINESS_TZ
from ....services.slot_rules import earliest_start, load_busy, range_error
from ....services.ghl_calendar import get_available_slots as ghl_get_available_slots
from ....services.ghl_calendar import list_events as ghl_list_events
from ....utils.timezones import format_iso_with_offset, get_weekday_in_tz

router = APIRouter()


def _meets_policy(start: datetime, end: datetime, policy) -> bool:
    """El slot libre de GHL debe caer en un día hábil, dentro de la ventana del día y fuera del almuerzo."""
    local_start = start.astimezone(ZoneInfo(BUSINESS_TZ))
    local_end = end.astimezone(ZoneInfo(BUSINESS_TZ))
    if is_holiday(local_start.year, local_start.month, local_start.day):
        return False
    window = policy.day_window(get_weekday_in_tz(start, BUSINESS_TZ))
    if not window:
        return False
    h1, m1, h2, m2 = window
    start_min = local_start.hour * 60 + local_start.minute
    end_min = local_end.hour * 60 + local_end.minute
    if start_min < h1 * 60 + m1 or end_min > h2 * 60 + m2:
        return False
    return not policy.lunch_break(start_min, end_min)


@router.post("/get-available-slots-ghl", response_model=SlotsResponse)
async def get_available_slots_ghl(req: SlotsRequest):
    settings = get_settings()
    user_tz = (req.iana_timezone or "").strip() or "America/Bogota"

    cal = resolve_calendar(settings, req.calendar_type)
    if cal is None:
        return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors=unknown_calendar_message(settings, req.calendar_type))
    tool, policy, env_suffix = cal.tool, cal.slots, cal.key

    try:
        now = datetime.now(ZoneInfo("UTC"))

        if not settings.ghl_token:
            return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors="Missing GHL_TOKEN in environment")
        if not tool.ghl_calendar_id:
            return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors=f"Missing FA_GHL_CALENDAR_ID_{env_suffix} in environment")

        too_long = range_error(tool, f"FA_DATE_RANGE_DAYS_{env_suffix}")
        if too_long:
            return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors=too_long)

        earliest = earliest_start(now, tool)
        end_date = compute_end_date(earliest, tool.date_range_days, policy.closing_hour)
        duration = int(tool.duration_minutes)

        # GHL computes the free slots with its own calendar settings; the filters below only discard.
        try:
            free_slots = await ghl_get_available_slots(
                access_token=settings.ghl_token,
                calendar_id=tool.ghl_calendar_id,
                start_dt=earliest,
                end_dt=end_date,
                timezone=BUSINESS_TZ,
                duration_minutes=duration,
            )
        except Exception as exc:
            return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors=str(exc))

        starts = [datetime.fromisoformat(iso.replace("Z", "+00:00")) for iso in free_slots]
        starts = [s for s in starts if s >= earliest and _meets_policy(s, s + timedelta(minutes=duration), policy)]

        # Buffers: an existing appointment blocks its own time plus the pre/post buffers.
        if tool.pre_buffer_minutes or tool.post_buffer_minutes:
            busy = await load_busy(ghl_list_events, settings, tool, earliest - timedelta(days=1), end_date + timedelta(days=1))
            if busy:
                starts = [
                    s for s in starts
                    if not conflicts_with_busy(s, s + timedelta(minutes=duration), busy, tool.pre_buffer_minutes, tool.post_buffer_minutes)
                ]

        result = []
        for dt in thin_by_interval(starts, tool.interval_minutes):
            dt_end = dt + timedelta(minutes=duration)
            result.append(
                Slot(
                    start_co=format_iso_with_offset(dt, BUSINESS_TZ),
                    end_co=format_iso_with_offset(dt_end, BUSINESS_TZ),
                    start_local=format_iso_with_offset(dt, user_tz),
                    end_local=format_iso_with_offset(dt_end, user_tz),
                )
            )

        return SlotsResponse(success=True, iana_timezone=user_tz, available_slots=result, errors=None)

    except Exception as e:
        return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors=str(e))
