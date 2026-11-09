from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from ....core.config import BUSINESS_TZ, get_settings
from agent_backend.scheduling_schemas import SlotsRequest, SlotsResponse
from agent_backend.google_calendar import get_access_token, get_free_busy
from ....services.calendars import resolve_calendar, unknown_calendar_message
from agent_backend.timezones import add_days

router = APIRouter()


@router.post("/get-available-slots-google", response_model=SlotsResponse)
async def get_available_slots(req: SlotsRequest):
    settings = get_settings()
    user_tz = req.iana_timezone.strip() if req.iana_timezone and req.iana_timezone.strip() else BUSINESS_TZ

    cal = resolve_calendar(settings, req.calendar_type)
    if cal is None:
        return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors=unknown_calendar_message(settings, req.calendar_type))
    tool = cal.tool

    try:
        now = datetime.now(ZoneInfo("UTC"))

        if not (tool.google_client_id and tool.google_client_secret and tool.google_refresh_token):
            return SlotsResponse(
                success=False, iana_timezone=user_tz, available_slots=[],
                errors=f"Missing BN_GOOGLE_CLIENT_ID_{cal.key} / BN_GOOGLE_CLIENT_SECRET_{cal.key} / BN_GOOGLE_REFRESH_TOKEN_{cal.key} in environment",
            )
        access_token = await get_access_token(
            tool.google_client_id, tool.google_client_secret, tool.google_refresh_token
        )
        if not access_token:
            return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors="Failed to obtain access token")

        range_end = add_days(now, tool.date_range_days)
        busy_events = await get_free_busy(access_token, tool.calendar_id, now, range_end)

        slots = cal.slots.compute_available_slots(
            now=now,
            date_range_days=tool.date_range_days,
            duration_minutes=tool.duration_minutes,
            interval_minutes=tool.interval_minutes,
            pre_buffer_minutes=tool.pre_buffer_minutes,
            post_buffer_minutes=tool.post_buffer_minutes,
            min_notice_minutes=tool.min_notice_minutes,
            user_tz=user_tz,
            busy_events=busy_events,
        )

        return SlotsResponse(success=True, iana_timezone=user_tz, available_slots=slots, errors=None)

    except Exception as e:
        return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors=str(e))

