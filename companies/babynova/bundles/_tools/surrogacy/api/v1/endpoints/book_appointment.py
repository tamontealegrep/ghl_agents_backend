from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from ....core.config import get_settings
from ....services.calendars import resolve_calendar, unknown_calendar_message
from ....schemas.booking import BookAppointmentRequest, BookAppointmentResponse
from ....services.notifications import notify_booking
from agent_backend.google_calendar import create_event, get_access_token
from agent_backend.timezones import get_weekday_in_tz

router = APIRouter()


@router.post("/book-appointment", response_model=BookAppointmentResponse)
async def book_appointment(req: BookAppointmentRequest):
    settings = get_settings()
    cal = resolve_calendar(settings, req.calendar_type)
    if cal is None:
        return BookAppointmentResponse(success=False, errors=unknown_calendar_message(settings, req.calendar_type))
    tool = cal.tool
    policy = cal.booking

    try:
        now = datetime.now(ZoneInfo("UTC"))

        try:
            start_dt = policy.parse_start_date(req.start_date)
        except ValueError:
            return BookAppointmentResponse(success=False, reason="invalid_start_date", errors="start_date is not a valid ISO 8601 date")

        duration_minutes = policy.parse_duration_minutes(req.duration)
        end_dt = policy.compute_end_date(start_dt, duration_minutes)

        if not policy.is_future(start_dt, now):
            return BookAppointmentResponse(success=False, reason="past_date", errors="The date cannot be in the past")

        local_start = start_dt.astimezone(ZoneInfo("America/Bogota"))
        weekday = get_weekday_in_tz(start_dt, "America/Bogota")
        if not policy.is_valid_business_hour(weekday, local_start.hour, local_start.minute):
            return BookAppointmentResponse(success=False, reason="invalid_hour", errors="The requested time is outside business hours")

        contact_name = policy.format_contact_name(req.contact_name)
        contact_phone = (req.contact_phone or "").strip()
        contact_email = (req.contact_email or "").strip().lower()
        user_tz = (req.iana_timezone or "America/Bogota").strip()

        if not (tool.google_client_id and tool.google_client_secret and tool.google_refresh_token):
            return BookAppointmentResponse(success=False, errors=f"Missing BN_GOOGLE_CLIENT_ID_{cal.key} / BN_GOOGLE_CLIENT_SECRET_{cal.key} / BN_GOOGLE_REFRESH_TOKEN_{cal.key} in environment")

        access_token = await get_access_token(tool.google_client_id, tool.google_client_secret, tool.google_refresh_token)
        if not access_token:
            return BookAppointmentResponse(success=False, errors="Failed to obtain Google Calendar access token")

        event = await create_event(
            access_token=access_token,
            calendar_id=tool.calendar_id,
            summary=f"{policy.EVENT_TITLE_PREFIX}{policy.TITLE_SEPARATOR}{contact_name}{policy.TITLE_SEPARATOR}{contact_phone}",
            description=f"Email: {contact_email}\nPhone: {contact_phone}",
            start_dt=start_dt,
            end_dt=end_dt,
            attendee_email=contact_email,
            request_id=f"meet-{start_dt.isoformat()}",
        )
        event_id = event.get("id")
        if not event_id:
            return BookAppointmentResponse(success=False, reason="creation_failed", errors="Failed to create the appointment. The booking was not completed")

        event_link = event.get("htmlLink")
        meet_link = event.get("hangoutLink")

        # The patient is invited by Google Calendar itself (attendee). The e-mail below is the optional
        # heads-up for the team (BN_NOTIFICATION_EMAIL); it never fails the booking.
        notify_error = await notify_booking(
            settings, policy, contact_name=contact_name, contact_phone=contact_phone, start_dt=start_dt, timezone=user_tz
        )

        return BookAppointmentResponse(success=True, event_id=event_id, event_link=event_link, meet_link=meet_link, errors=notify_error)

    except Exception as e:
        return BookAppointmentResponse(success=False, errors=str(e))

