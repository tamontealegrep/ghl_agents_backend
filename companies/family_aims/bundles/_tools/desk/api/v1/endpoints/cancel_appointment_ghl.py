from fastapi import APIRouter

from agent_backend.ghl_calendar import delete_appointment as ghl_delete_appointment

from ....core.config import get_settings
from ....schemas.booking import (
    CancelAppointmentRequest,
    CancelAppointmentResponse,
)

router = APIRouter()


@router.post("/cancel-appointment-ghl", response_model=CancelAppointmentResponse)
async def cancel_appointment_ghl(req: CancelAppointmentRequest):
    settings = get_settings()

    if not settings.ghl_token:
        return CancelAppointmentResponse(success=False, errors="Missing GHL_TOKEN in environment")

    try:
        success = await ghl_delete_appointment(settings.ghl_token, req.event_id)
        if success:
            return CancelAppointmentResponse(success=True, message="The appointment has been successfully canceled.")
        else:
            return CancelAppointmentResponse(success=False, errors="Could not delete the event. Please verify the event_id.")

    except Exception as e:
        return CancelAppointmentResponse(success=False, errors=str(e))
