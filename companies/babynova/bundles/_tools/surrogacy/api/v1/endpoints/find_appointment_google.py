from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from agent_backend import date_formatting
from agent_backend.google_calendar import get_access_token, list_events
from agent_backend.scheduling_schemas import (
    AppointmentInfo,
    FindAppointmentRequest,
    FindAppointmentResponse,
)
from agent_backend.timezones import parse_iso

from ....core.config import get_settings
from ....services.calendars import resolve_calendar, unknown_calendar_message

router = APIRouter()


@router.post("/find-appointment-google", response_model=FindAppointmentResponse)
async def find_appointment(req: FindAppointmentRequest):
    settings = get_settings()
    cal = resolve_calendar(settings, req.calendar_type)
    if cal is None:
        return FindAppointmentResponse(success=False, errors=unknown_calendar_message(settings, req.calendar_type))
    tool = cal.tool
    EVENT_TITLE_PREFIX, TITLE_SEPARATOR = cal.booking.EVENT_TITLE_PREFIX, cal.booking.TITLE_SEPARATOR
    
    # Safe normalization of inputs (handle None and strip)
    client_tz = (req.iana_timezone or "America/Bogota").strip()
    target_person = (req.contact_name or "").strip()
    target_phone = (req.contact_phone or "").strip()
    target_email = (req.contact_email or "").strip().lower()
    language = "EN"

    # 1. Validation: at least one of Name, Phone, or Email is required
    if not target_person and not target_phone and not target_email:
        return FindAppointmentResponse(success=False, errors="You must provide at least a name, phone, or email to search.")

    # 2. Phone normalization (+57 if 10 digits starting with 3)
    clean_phone_digits = "".join(c for c in target_phone if c.isdigit())
    if len(clean_phone_digits) == 10 and clean_phone_digits.startswith("3"):
        target_phone = f"+57{clean_phone_digits}"
    
    # 3. Basic email validation (if provided)
    if target_email and ("@" not in target_email or "." not in target_email.split("@")[1]):
        return FindAppointmentResponse(success=False, errors=f"The email '{target_email}' is not in a valid format.")

    try:
        # Range: from yesterday to 35 days ahead
        now = datetime.now(ZoneInfo("UTC"))
        time_min = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        time_max = time_min + timedelta(days=36)

        if not (tool.google_client_id and tool.google_client_secret and tool.google_refresh_token):
            return FindAppointmentResponse(success=False, errors=f"Missing BN_GOOGLE_CLIENT_ID_{cal.key} / BN_GOOGLE_CLIENT_SECRET_{cal.key} / BN_GOOGLE_REFRESH_TOKEN_{cal.key} in environment")

        access_token = await get_access_token(
            tool.google_client_id, tool.google_client_secret, tool.google_refresh_token
        )
        if not access_token:
            return FindAppointmentResponse(success=False, errors="Failed to obtain Google Calendar access token")

        events = await list_events(
            access_token=access_token,
            calendar_id=tool.calendar_id,
            time_min=time_min,
            time_max=time_max,
        )

        phone_matches = []
        name_matches = []
        email_matches = []

        target_lower = target_person.lower()
        target_keywords = [w for w in target_lower.split() if len(w) > 2 and w not in ("baby", "nova", "novafem", "first", "visit")]
        clean_target_phone = "".join(c for c in target_phone if c.isdigit())

        for event in events:
            summary = event.get("summary", "")
            description = event.get("description", "")
            attendees = event.get("attendees", [])

            if EVENT_TITLE_PREFIX not in summary:
                continue

            # Extract data from title: "First Visit - Name - Phone"
            parts = [p.strip() for p in summary.split(TITLE_SEPARATOR)]
            ext_name = parts[1] if len(parts) > 1 else ""
            ext_phone = parts[2] if len(parts) > 2 else ""
            
            # Extract email from description or attendees
            ext_email = None
            if "Email:" in description:
                try:
                    ext_email = description.split("Email:")[1].split("\n")[0].strip()
                except IndexError:
                    pass
            if not ext_email and attendees:
                ext_email = attendees[0].get("email")

            start_raw = event["start"].get("dateTime", event["start"].get("date"))
            start_dt = parse_iso(start_raw).astimezone(ZoneInfo(client_tz))
            formatted_date = date_formatting.format_full_date(start_dt, language)
            formatted_time = date_formatting.format_booking_time(start_dt, language)

            appt_info = AppointmentInfo(
                event_id=event["id"],
                summary=summary,
                start_time=f"{formatted_date} at {formatted_time}",
                contact_name=ext_name or None,
                contact_phone=ext_phone or None,
                contact_email=ext_email or None
            )

            # --- Search Prioritization ---
            
            # 1. Priority: Phone
            if clean_target_phone and ext_phone:
                clean_ext_phone = "".join(c for c in ext_phone if c.isdigit())
                if clean_target_phone in clean_ext_phone:
                    phone_matches.append(appt_info)
                    continue  # If phone matches, high priority

            # 2. Email (if provided and no phone match yet)
            if target_email and ext_email and target_email == ext_email.lower():
                email_matches.append(appt_info)
                continue

            # 3. Name
            if target_person and ext_name:
                content_to_search = (summary + " " + description).lower()
                if (target_lower in content_to_search) or (all(kw in content_to_search for kw in target_keywords) if target_keywords else False):
                    name_matches.append(appt_info)

        # Return results by priority
        results = phone_matches or email_matches or name_matches

        if results:
            return FindAppointmentResponse(success=True, appointments=results)

        target_search = target_phone or target_person or target_email
        return FindAppointmentResponse(
            success=False, errors=f"No appointments found for '{target_search}' in the next month."
        )

    except Exception as e:
        return FindAppointmentResponse(success=False, errors=str(e))

