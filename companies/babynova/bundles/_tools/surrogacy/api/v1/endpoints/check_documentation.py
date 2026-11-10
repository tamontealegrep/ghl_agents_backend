from fastapi import APIRouter

from ....schemas.documentation_check import CheckDocumentationRequest, CheckDocumentationResponse
from ....services.documentation_check import check_documentation

router = APIRouter()


@router.post("/check-documentation-sur", response_model=CheckDocumentationResponse)
async def check_documentation_sur(req: CheckDocumentationRequest):
    try:
        result = check_documentation(req.nationality, req.document_type)
        return CheckDocumentationResponse(success=True, **result, errors=None)
    except Exception as e:
        return CheckDocumentationResponse(success=False, errors=str(e))

