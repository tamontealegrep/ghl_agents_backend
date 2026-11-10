from fastapi import APIRouter

from ....core.config import get_settings
from ....services.calendars import resolve_calendar, unknown_calendar_message
from agent_backend.scheduling_schemas import (
    CancelAppointmentRequest,
    CancelAppointmentResponse,
)
from agent_backend.google_calendar import delete_event, get_access_token

router = APIRouter()


@router.post("/cancel-appointment", response_model=CancelAppointmentResponse)
async def cancel_appointment(req: CancelAppointmentRequest):
    settings = get_settings()
    cal = resolve_calendar(settings, req.calendar_type)
    if cal is None:
        return CancelAppointmentResponse(success=False, errors=unknown_calendar_message(settings, req.calendar_type))
    tool = cal.tool
    
    if not (tool.google_client_id and tool.google_client_secret and tool.google_refresh_token):
        return CancelAppointmentResponse(success=False, errors=f"Missing BN_GOOGLE_CLIENT_ID_{cal.key} / BN_GOOGLE_CLIENT_SECRET_{cal.key} / BN_GOOGLE_REFRESH_TOKEN_{cal.key} in environment")

    try:
        access_token = await get_access_token(
            tool.google_client_id, tool.google_client_secret, tool.google_refresh_token
        )
        if not access_token:
            return CancelAppointmentResponse(success=False, errors="Failed to obtain Google Calendar access token")

        success = await delete_event(access_token, tool.calendar_id, req.event_id)
        
        if success:
            return CancelAppointmentResponse(success=True, message="The appointment has been successfully canceled.")
        else:
            return CancelAppointmentResponse(success=False, errors="Could not delete the event. Please verify the event_id.")

    except Exception as e:
        return CancelAppointmentResponse(success=False, errors=str(e))

