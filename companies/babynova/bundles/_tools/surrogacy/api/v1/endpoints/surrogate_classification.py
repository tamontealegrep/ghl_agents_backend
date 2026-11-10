from fastapi import APIRouter

from ....schemas.surrogate_classification import (
    SurrogateClassificationRequest,
    SurrogateClassificationResponse,
)
from ....services.surrogate_classifier import classify_surrogate_detailed, eligibility_fields

router = APIRouter()


@router.post("/surrogate-classification", response_model=SurrogateClassificationResponse)
async def surrogate_classification(req: SurrogateClassificationRequest):
    try:
        result, missing_field = classify_surrogate_detailed(req.model_dump())
        eligibility_result, eligibility_reason = eligibility_fields(result, missing_field)
        return SurrogateClassificationResponse(
            success=True,
            result=result,
            eligibility_result=eligibility_result,
            eligibility_reason=eligibility_reason,
            errors=None,
        )
    except Exception as e:
        return SurrogateClassificationResponse(success=False, result=None, errors=str(e))
