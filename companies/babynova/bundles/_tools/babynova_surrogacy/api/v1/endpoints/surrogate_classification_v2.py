from fastapi import APIRouter

from ....schemas.surrogate_classification_v2 import (
    SurrogateClassificationV2Request,
    SurrogateClassificationV2Response,
)
from ....services.surrogate_classifier_v2 import classify_surrogate_v2_detailed, eligibility_fields

router = APIRouter()


@router.post("/surrogate-classification-v2", response_model=SurrogateClassificationV2Response)
async def surrogate_classification_v2(req: SurrogateClassificationV2Request):
    try:
        result, missing_field = classify_surrogate_v2_detailed(req.model_dump())
        eligibility_result, eligibility_reason = eligibility_fields(result, missing_field)
        return SurrogateClassificationV2Response(
            success=True,
            result=result,
            eligibility_result=eligibility_result,
            eligibility_reason=eligibility_reason,
            errors=None,
        )
    except Exception as e:
        return SurrogateClassificationV2Response(success=False, result=None, errors=str(e))
