from fastapi import APIRouter

from ....schemas.donor_classification import DonorClassificationRequest, DonorClassificationResponse
from ....services.donor_classifier import classify_donor_detailed, eligibility_fields

router = APIRouter()


@router.post("/donor-classification", response_model=DonorClassificationResponse)
async def donor_classification(req: DonorClassificationRequest):
    try:
        result, missing_field = classify_donor_detailed(req.model_dump())
        eligibility_result, not_eligibility_reason = eligibility_fields(result, missing_field)
        return DonorClassificationResponse(
            success=True,
            result=result,
            eligibility_result=eligibility_result,
            not_eligibility_reason=not_eligibility_reason,
            errors=None,
        )
    except Exception as e:
        return DonorClassificationResponse(success=False, result=None, errors=str(e))
