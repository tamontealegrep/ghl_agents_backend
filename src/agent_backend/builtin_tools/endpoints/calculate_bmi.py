from fastapi import APIRouter

from agent_backend.builtin_tools.schemas.bmi import CalculateBmiRequest, CalculateBmiResponse
from agent_backend.builtin_tools.services.bmi_calculator import calculate_bmi as calculate_bmi_service

router = APIRouter()


@router.post("/calculate-bmi", response_model=CalculateBmiResponse)
async def calculate_bmi(req: CalculateBmiRequest):
    try:
        result = calculate_bmi_service(req.weight_kg, req.height_cm)
        return CalculateBmiResponse(success=True, **result)
    except Exception as e:
        return CalculateBmiResponse(success=False, errors=str(e))
