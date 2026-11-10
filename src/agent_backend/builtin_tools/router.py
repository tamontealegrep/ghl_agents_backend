"""Routes of the built-in tools every company shares, mounted at ``/builtin-tools``."""

from fastapi import APIRouter

# Utils tools (shared across agents)
from agent_backend.builtin_tools.endpoints import (
    calculate_bmi,
    callback_request,
    check_days_elapsed,
    time_now,
)
from agent_backend.builtin_tools.endpoints import (
    echo as echo_endpoint,
)
from agent_backend.builtin_tools.endpoints import (
    input_payload as input_payload_endpoint,
)
from agent_backend.builtin_tools.endpoints import (
    pause as pause_endpoint,
)
from agent_backend.builtin_tools.endpoints import (
    update_custom_field as ucf_endpoint,
)
from agent_backend.builtin_tools.schemas.ghl import GhlCustomUpdateResponse
from agent_backend.builtin_tools.schemas.input_payload import InputPayloadResponse

router = APIRouter()

# --- Shared (utils) ---
router.add_api_route(
    "/time-now",
    time_now.time_now,
    methods=["POST"],
    response_model=time_now.TimeNowResponse,
    tags=["utils.time_now"],
)
router.add_api_route(
    "/check-days-elapsed",
    check_days_elapsed.check_days_elapsed_endpoint,
    methods=["POST"],
    response_model=check_days_elapsed.CheckDaysElapsedResponse,
    tags=["utils.check_days_elapsed"],
)
router.add_api_route(
    "/callback",
    callback_request.request_callback_endpoint,
    methods=["POST"],
    response_model=callback_request.CallbackRequestResponse,
    tags=["utils.callback"],
)
router.add_api_route(
    "/calculate-bmi",
    calculate_bmi.calculate_bmi,
    methods=["POST"],
    response_model=calculate_bmi.CalculateBmiResponse,
    tags=["utils.calculate_bmi"],
)
router.add_api_route(
    "/update-custom-field",
    ucf_endpoint.update_custom_field,
    methods=["POST"],
    response_model=GhlCustomUpdateResponse,
    tags=["utils.update_custom_field"],
)
router.add_api_route(
    "/echo",
    echo_endpoint.echo,
    methods=["POST"],
    tags=["utils.echo"],
)
router.add_api_route(
    "/pause",
    pause_endpoint.pause,
    methods=["POST"],
    response_model=pause_endpoint.PauseResponse,
    tags=["utils.pause"],
)

router.add_api_route(
    "/input-payload",
    input_payload_endpoint.receive_payload,
    methods=["POST"],
    response_model=InputPayloadResponse,
    tags=["utils.input_payload"],
)
