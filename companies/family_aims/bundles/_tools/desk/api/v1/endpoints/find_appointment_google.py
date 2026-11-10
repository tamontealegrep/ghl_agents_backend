from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from agent_backend import date_formatting
from agent_backend.google_calendar import get_access_token, list_events
from agent_backend.timezones import parse_iso

from ....core.config import get_settings
from ....schemas.booking import (
    AppointmentInfo,
    FindAppointmentRequest,
    FindAppointmentResponse,
)
from ....services.calendars import resolve_calendar, unknown_calendar_message

router = APIRouter()


@router.post("/find-appointment-google", response_model=FindAppointmentResponse)
async def find_appointment_google(req: FindAppointmentRequest):
    settings = get_settings()
    client_tz = req.iana_timezone.strip() or "America/Bogota"
    target_person = req.contact_name.strip()
    target_email = req.contact_email.strip().lower()
    cal = resolve_calendar(settings, req.calendar_type) if (req.calendar_type or "").strip() else None
    if cal is None:
        return FindAppointmentResponse(success=False, errors=unknown_calendar_message(settings, req.calendar_type))

    if not target_person and not target_email:
        return FindAppointmentResponse(success=False, errors="You must provide the person's name or email")

    try:
        # Range: from yesterday to 35 days ahead (full coverage)
        now = datetime.now(ZoneInfo("UTC"))
        time_min = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        time_max = time_min + timedelta(days=36)

        calendars = [(cal.key, cal.tool)]

        found_appointments = []
        target_lower = target_person.lower()
        # Palabras clave del nombre (ignorando conectores comunes)
        target_keywords = [w for w in target_lower.split() if len(w) > 2 and w not in ("family", "aims", "and")]

        for cal_type, config in calendars:
            if not (config.google_client_id and config.google_client_secret and config.google_refresh_token):
                continue

            access_token = await get_access_token(
                config.google_client_id, config.google_client_secret, config.google_refresh_token
            )
            if not access_token:
                continue

            events = await list_events(
                access_token=access_token,
                calendar_id=config.calendar_id,
                time_min=time_min,
                time_max=time_max,
                # Avoid using query 'q' so we fetch ALL events and post-filter locally.
            )

            for event in events:
                summary = event.get("summary", "")
                description = event.get("description", "")
                attendees = event.get("attendees", [])
                
                if "Family Aims" not in summary:
                    continue

                content_to_search = (summary + " " + description).lower()
                
                # Name-based search
                name_match = False
                if target_person:
                    name_match = (target_lower in content_to_search) or (
                        all(kw in content_to_search for kw in target_keywords) if target_keywords else False
                    )
                
                # Email-based search (in content or attendees list)
                email_match = False
                if target_email:
                    in_content = target_email in content_to_search
                    in_attendees = any(target_email == a.get("email", "").lower() for a in attendees)
                    email_match = in_content or in_attendees

                if name_match or email_match:
                    start_raw = event["start"].get("dateTime", event["start"].get("date"))
                    start_dt = parse_iso(start_raw).astimezone(ZoneInfo(client_tz))
                    
                    # Force English formatting for tool output
                    formatted_date = date_formatting.format_full_date(start_dt, "EN")
                    formatted_time = date_formatting.format_booking_time(start_dt, "EN")

                    found_appointments.append(
                        AppointmentInfo(
                            event_id=event["id"],
                            summary=summary,
                            start_time=f"{formatted_date} at {formatted_time}",
                            calendar_type=cal_type,
                        )
                    )

        if found_appointments:
            return FindAppointmentResponse(success=True, appointments=found_appointments)

        target_search = target_person or target_email
        return FindAppointmentResponse(
            success=False, errors=f"No appointments found for {target_search} in the next month."
        )

    except Exception as e:
        return FindAppointmentResponse(success=False, errors=str(e))
