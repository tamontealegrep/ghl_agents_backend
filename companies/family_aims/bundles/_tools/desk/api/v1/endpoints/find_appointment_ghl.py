from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from ....core.config import get_settings
from ....services.calendars import resolve_calendar, unknown_calendar_message
from ....schemas.booking import (
    AppointmentInfo,
    FindAppointmentRequest,
    FindAppointmentResponse,
)
from agent_backend import date_formatting
from agent_backend.ghl_calendar import list_events as ghl_list_events, upsert_contact as ghl_upsert_contact
from agent_backend.timezones import parse_iso

router = APIRouter()


@router.post("/find-appointment-ghl", response_model=FindAppointmentResponse)
async def find_appointment_ghl(req: FindAppointmentRequest):
    settings = get_settings()
    client_tz = (req.iana_timezone or "").strip() or "America/Bogota"
    target_person = (req.contact_name or "").strip()
    target_email = (req.contact_email or "").strip().lower()
    cal = resolve_calendar(settings, req.calendar_type) if (req.calendar_type or "").strip() else None
    if cal is None:
        return FindAppointmentResponse(success=False, errors=unknown_calendar_message(settings, req.calendar_type))
    requested_cal = cal.key

    if not target_person and not target_email:
        return FindAppointmentResponse(success=False, errors="You must provide the person's name or email")

    try:
        now = datetime.now(ZoneInfo("UTC"))
        time_min = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        time_max = time_min + timedelta(days=36)

        tool = cal.tool
        if not settings.ghl_token:
            return FindAppointmentResponse(success=False, errors="Missing GHL_TOKEN in environment")
        if not settings.ghl_location_id:
            return FindAppointmentResponse(success=False, errors="Missing GHL_LOCATION_ID in environment")
        if not tool.ghl_calendar_id:
            return FindAppointmentResponse(success=False, errors=f"Missing FA_GHL_CALENDAR_ID_{requested_cal} in environment")

        # Resolver contacto en GHL para intentar filtrar por contact_id
        upsert = await ghl_upsert_contact(
            access_token=settings.ghl_token,
            location_id=settings.ghl_location_id,
            email=target_email or None,
            phone=None,
            name=target_person or None,
        )
        contact_id = (upsert.get("contact") or {}).get("id")

        data = await ghl_list_events(
            access_token=settings.ghl_token,
            location_id=settings.ghl_location_id,
            calendar_id=tool.ghl_calendar_id,
            start_dt=time_min,
            end_dt=time_max,
        )
        events = data.get("events", []) if isinstance(data, dict) else []

        found = []
        tname = target_person.lower()
        tkeywords = [w for w in tname.split() if len(w) > 2 and w not in ("family", "aims", "and")]

        for ev in events:
            title = ev.get("title", "")
            ev_contact_id = ev.get("contactId") or ev.get("contact_id")

            if contact_id and ev_contact_id and ev_contact_id == contact_id:
                match = True
            else:
                content = title.lower()
                name_match = (tname and tname in content) or (tkeywords and all(kw in content for kw in tkeywords))
                email_match = target_email and (target_email in content)
                match = name_match or email_match

            if not match:
                continue

            raw_start = ev.get("startTime") or ev.get("start_time")
            if not raw_start:
                continue
            start_dt = parse_iso(raw_start).astimezone(ZoneInfo(client_tz))

            formatted_date = date_formatting.format_full_date(start_dt, "EN")
            formatted_time = date_formatting.format_booking_time(start_dt, "EN")

            found.append(
                AppointmentInfo(
                    event_id=ev.get("id", ""),
                    summary=title,
                    start_time=f"{formatted_date} at {formatted_time}",
                    calendar_type=requested_cal,
                )
            )

        if found:
            return FindAppointmentResponse(success=True, appointments=found)

        target_search = target_person or target_email
        return FindAppointmentResponse(success=False, errors=f"No appointments found for {target_search} in the next month.")

    except Exception as e:
        return FindAppointmentResponse(success=False, errors=str(e))
