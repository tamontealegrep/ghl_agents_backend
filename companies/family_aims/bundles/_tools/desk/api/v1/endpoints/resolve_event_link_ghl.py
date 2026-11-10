from datetime import datetime, timedelta

from fastapi import APIRouter

from ....core.config import get_settings
from ....schemas.booking import ResolveEventLinkRequest, ResolveEventLinkResponse
from ....services import booking_engine as engine
from ....services.calendars import resolve_calendar, unknown_calendar_message

router = APIRouter()


@router.post("/resolve-event-link-ghl", response_model=ResolveEventLinkResponse)
async def resolve_event_link_ghl(req: ResolveEventLinkRequest):
    settings = get_settings()

    cal = resolve_calendar(settings, req.calendar_type)
    if cal is None:
        return ResolveEventLinkResponse(
            success=False, errors=unknown_calendar_message(settings, req.calendar_type)
        )
    calendar_type, tool = cal.key, cal.tool

    try:
        try:
            start_dt = engine.parse_start_date(req.start_date)
        except ValueError:
            return ResolveEventLinkResponse(success=False, errors="start_date is not a valid ISO 8601 date")

        # End time from configured duration
        duration_minutes = int(tool.duration_minutes or 30)
        end_dt = engine.compute_end_date(start_dt, duration_minutes)

        # Validate Google Calendar credentials
        if not (
            tool.google_client_id
            and tool.google_client_secret
            and tool.google_refresh_token
            and tool.calendar_id
        ):
            return ResolveEventLinkResponse(
                success=False, errors=f"Missing Google Calendar credentials for {calendar_type}"
            )

        from agent_backend.google_calendar import (
            find_synced_google_event,
        )
        from agent_backend.google_calendar import (
            get_access_token as google_get_access_token,
        )
        from agent_backend.google_calendar import (
            list_events as gcal_list_events,
        )

        gcal_token = await google_get_access_token(
            tool.google_client_id, tool.google_client_secret, tool.google_refresh_token
        )
        if not gcal_token:
            return ResolveEventLinkResponse(
                success=False, errors="Failed to obtain Google Calendar access token"
            )

        # Strategy 1: by Meet link when provided
        if req.meet_link:
            matched = await find_synced_google_event(
                access_token=gcal_token,
                calendar_id=tool.calendar_id,
                start_dt=start_dt,
                end_dt=end_dt,
                meet_link=req.meet_link,
                attempts=4,
            )
            if isinstance(matched, dict):
                return ResolveEventLinkResponse(success=True, event_link=matched.get("htmlLink"))

        # Strategy 2: fallback by time window and summary pattern
        events = await gcal_list_events(
            access_token=gcal_token,
            calendar_id=tool.calendar_id,
            time_min=start_dt - timedelta(minutes=5),
            time_max=end_dt + timedelta(minutes=5),
        )

        expected_prefix = f"family aims ({cal.booking.EVENT_SUMMARY_TAG})".lower()
        name_lc = (req.contact_name or "").strip().lower()

        candidates = []
        for ev in events:
            if ev.get("status") == "cancelled":
                continue
            summary = (ev.get("summary") or "").lower()
            if expected_prefix in summary and (not name_lc or name_lc in summary):
                candidates.append(ev)

        exact = []
        for ev in candidates:
            ev_start = (ev.get("start") or {}).get("dateTime")
            if not isinstance(ev_start, str):
                continue
            try:
                ev_dt = datetime.fromisoformat(ev_start.replace("Z", "+00:00"))
                if ev_dt == start_dt:
                    exact.append(ev)
            except Exception:
                continue

        picked = exact[0] if len(exact) == 1 else (candidates[0] if len(candidates) == 1 else None)
        if isinstance(picked, dict):
            return ResolveEventLinkResponse(success=True, event_link=picked.get("htmlLink"))

        return ResolveEventLinkResponse(
            success=False, errors="Event link not found yet — try again in a few seconds"
        )

    except Exception as e:
        return ResolveEventLinkResponse(success=False, errors=str(e))
