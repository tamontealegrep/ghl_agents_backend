"""Built-in tool: validates and records a request to call the contact back."""

from fastapi import APIRouter

from agent_backend.builtin_tools.schemas.callback_request import CallbackRequest, CallbackRequestResponse
from agent_backend.builtin_tools.services.callback_request import prepare_callback_request

router = APIRouter()


@router.post("/request-callback", response_model=CallbackRequestResponse)
async def request_callback_endpoint(req: CallbackRequest):
    """Validates a callback request and answers with the normalised data."""
    try:
        result = prepare_callback_request(
            req.contact_name,
            req.contact_phone,
            req.contact_email,
            req.reason,
            req.context,
            req.preferred_days,
            req.preferred_time_window,
            req.iana_timezone,
        )
        return CallbackRequestResponse(success=True, **result)
    except Exception as e:
        return CallbackRequestResponse(success=False, errors=str(e))
