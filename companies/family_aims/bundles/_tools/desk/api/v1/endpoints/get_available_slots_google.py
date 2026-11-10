from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter

from ....core.config import get_settings
from ....schemas.slots import SlotsRequest, SlotsResponse
from ....services.calendars import resolve_calendar, unknown_calendar_message
from agent_backend.google_calendar import get_access_token, get_free_busy
from ....services.slot_engine import compute_available_slots, compute_end_date, compute_start_date

router = APIRouter()

@router.post("/get-available-slots-google", response_model=SlotsResponse)
async def get_available_slots_google(req: SlotsRequest):
    settings = get_settings()
    user_tz = req.iana_timezone.strip() if req.iana_timezone and req.iana_timezone.strip() else "America/Bogota"
    
    cal = resolve_calendar(settings, req.calendar_type)
    if cal is None:
        return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors=unknown_calendar_message(settings, req.calendar_type))
    tool, policy, env_suffix = cal.tool, cal.slots, cal.key

    try:
        now = datetime.now(ZoneInfo("UTC"))

        if not (tool.google_client_id and tool.google_client_secret and tool.google_refresh_token):
            return SlotsResponse(
                success=False, iana_timezone=user_tz, available_slots=[],
                errors=f"Missing GOOGLE_CLIENT_ID_{env_suffix} / GOOGLE_CLIENT_SECRET_{env_suffix} / GOOGLE_REFRESH_TOKEN_{env_suffix} in environment",
            )

        access_token = await get_access_token(
            tool.google_client_id, tool.google_client_secret, tool.google_refresh_token
        )
        if not access_token:
            return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors="Failed to obtain access token")

        start_date = compute_start_date(now)
        end_date = compute_end_date(start_date, tool.date_range_days, policy.closing_hour)
        busy_events = await get_free_busy(access_token, tool.calendar_id, start_date, end_date)

        slots = compute_available_slots(
            start_date=start_date,
            end_date=end_date,
            now_utc=now,
            duration_minutes=tool.duration_minutes,
            interval_minutes=max(tool.duration_minutes, tool.interval_minutes),
            min_advance_minutes=60,
            user_tz=user_tz,
            busy_events=busy_events,
            day_window_fn=policy.day_window,
            lunch_break_fn=policy.lunch_break,
        )

        return SlotsResponse(success=True, iana_timezone=user_tz, available_slots=slots, errors=None)

    except Exception as e:
        return SlotsResponse(success=False, iana_timezone=user_tz, available_slots=[], errors=str(e))
