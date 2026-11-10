from fastapi import APIRouter

from ....core.config import get_settings
from ....schemas.booking import (
    CancelAppointmentRequest,
    CancelAppointmentResponse,
)
from ....services.calendars import resolve_calendar, unknown_calendar_message
from agent_backend.google_calendar import delete_event, get_access_token

router = APIRouter()


@router.post("/cancel-appointment-google", response_model=CancelAppointmentResponse)
async def cancel_appointment_google(req: CancelAppointmentRequest):
    settings = get_settings()
    
    cal = resolve_calendar(settings, req.calendar_type)
    if cal is None:
        return CancelAppointmentResponse(success=False, errors=unknown_calendar_message(settings, req.calendar_type))
    config = cal.tool

    if not (config.google_client_id and config.google_client_secret and config.google_refresh_token):
        return CancelAppointmentResponse(success=False, errors=f"Missing credentials for calendar {req.calendar_type}")

    try:
        access_token = await get_access_token(
            config.google_client_id, config.google_client_secret, config.google_refresh_token
        )
        if not access_token:
            return CancelAppointmentResponse(success=False, errors="Failed to obtain Google Calendar access token")

        success = await delete_event(access_token, config.calendar_id, req.event_id)
        
        if success:
            return CancelAppointmentResponse(success=True, message="The appointment has been successfully canceled.")
        else:
            return CancelAppointmentResponse(success=False, errors="Could not delete the event. Please verify the event_id.")

    except Exception as e:
        return CancelAppointmentResponse(success=False, errors=str(e))
