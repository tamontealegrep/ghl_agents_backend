from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from agent_backend import date_formatting
from agent_backend.ghl_calendar import list_events as ghl_list_events
from agent_backend.ghl_calendar import update_appointment as ghl_update_appointment
from agent_backend.slot_filters import conflicts_with_busy
from agent_backend.timezones import get_hour_in_tz, get_weekday_in_tz

from ....core.config import get_settings
from ....schemas.booking import EditAppointmentRequest, EditAppointmentResponse
from ....services import booking_engine as engine
from ....services.calendars import resolve_calendar, unknown_calendar_message
from ....services.slot_rules import earliest_start, load_busy

router = APIRouter()


@router.post("/edit-appointment-ghl", response_model=EditAppointmentResponse)
async def edit_appointment_ghl(req: EditAppointmentRequest):
    settings = get_settings()

    cal = resolve_calendar(settings, req.calendar_type)
    if cal is None:
        return EditAppointmentResponse(
            success=False, errors=unknown_calendar_message(settings, req.calendar_type)
        )
    tool, policy = cal.tool, cal.booking

    try:
        now = datetime.now(ZoneInfo("UTC"))

        if not settings.ghl_token:
            return EditAppointmentResponse(success=False, errors="Missing GHL_TOKEN in environment")
        if not settings.ghl_location_id:
            return EditAppointmentResponse(success=False, errors="Missing GHL_LOCATION_ID in environment")

        # 1) Procesar nuevos valores
        start_dt = None
        end_dt = None
        applied_duration = req.new_duration

        if req.new_start_date:
            try:
                start_dt = engine.parse_start_date(req.new_start_date)
            except ValueError:
                return EditAppointmentResponse(
                    success=False, errors="new_start_date is not a valid ISO 8601 date"
                )

            if not engine.is_future(start_dt, now):
                return EditAppointmentResponse(success=False, errors="The new date cannot be in the past")

            weekday = get_weekday_in_tz(start_dt, "America/Bogota")
            hour = get_hour_in_tz(start_dt, "America/Bogota")
            minute = start_dt.astimezone(ZoneInfo("America/Bogota")).minute
            if not policy.is_valid_business_hour(weekday, hour, minute):
                return EditAppointmentResponse(
                    success=False, errors="The requested new time is outside business hours"
                )

            # Duración: usar la enviada o la del .env si no viene
            duration_int = (
                engine.parse_duration_minutes(applied_duration)
                if applied_duration
                else int(tool.duration_minutes)
            )
            applied_duration = str(duration_int)
            end_dt = engine.compute_end_date(start_dt, duration_int)

            if start_dt < earliest_start(now, tool):
                return EditAppointmentResponse(
                    success=False, errors="The requested new time does not meet the minimum advance notice"
                )

            # Validate against the calendar's other appointments and their buffers (excluding this event)
            if tool.ghl_calendar_id:
                busy = await load_busy(
                    ghl_list_events,
                    settings,
                    tool,
                    start_dt - timedelta(minutes=tool.post_buffer_minutes),
                    end_dt + timedelta(minutes=tool.pre_buffer_minutes),
                    exclude_event_id=req.event_id,
                )
                if busy and conflicts_with_busy(
                    start_dt, end_dt, busy, tool.pre_buffer_minutes, tool.post_buffer_minutes
                ):
                    return EditAppointmentResponse(
                        success=False,
                        errors="The requested new time is already taken by another appointment.",
                    )

        # 2) Actualizar en GHL
        updated = await ghl_update_appointment(
            access_token=settings.ghl_token,
            appointment_id=req.event_id,
            start_dt=start_dt,
            end_dt=end_dt,
        )
        if not isinstance(updated, dict):
            return EditAppointmentResponse(
                success=False, errors="Could not update the event. Please verify the event_id."
            )

        # 3) Formato de respuesta
        local_tz = req.iana_timezone or "America/Bogota"
        language = "EN"

        message = "The appointment has been successfully updated."
        new_time_str = None
        if start_dt:
            local_start = start_dt.astimezone(ZoneInfo(local_tz))
            formatted_date = date_formatting.format_full_date(local_start, language)
            formatted_time = date_formatting.format_booking_time(local_start, language)
            new_time_str = f"{formatted_date} at {formatted_time}"
            message = f"The appointment has been rescheduled to {new_time_str}."

        return EditAppointmentResponse(
            success=True,
            message=message,
            new_start_time=new_time_str,
            new_duration=applied_duration,
        )

    except Exception as e:
        return EditAppointmentResponse(success=False, errors=str(e))
