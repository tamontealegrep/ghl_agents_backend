from fastapi import APIRouter

from ....core.config import get_settings
from ....schemas.adres import CheckAdresRequest, CheckAdresResponse
from ....services.adres import build_result, prepare_lookup
from ....services.croma_client import CromaError, lookup_affiliation

router = APIRouter()


@router.post("/check-adres", response_model=CheckAdresResponse)
async def check_adres(req: CheckAdresRequest):
    """Consults the health-system affiliation (BDUA, ADRES) of a document through Croma."""
    body, invalid = prepare_lookup(req.document_type, req.document_number)
    if body is None:
        # A bad input is a normal result the agent can fix by asking again, not a technical failure.
        return CheckAdresResponse(success=True, errors=invalid)

    settings = get_settings()
    if not settings.croma_api_key:
        return CheckAdresResponse(
            success=False,
            document_type=body["document_type"],
            document_number=body["document_number"],
            errors="Missing CROMA_API_KEY in environment",
        )
    try:
        data = await lookup_affiliation(
            body,
            api_key=settings.croma_api_key,
            base_url=settings.croma_base_url,
            timeout_seconds=settings.croma_timeout_seconds,
        )
        return CheckAdresResponse(
            success=True,
            document_type=body["document_type"],
            document_number=body["document_number"],
            **build_result(data),
            errors=None,
        )
    except CromaError as exc:
        return CheckAdresResponse(
            success=False,
            document_type=body["document_type"],
            document_number=body["document_number"],
            errors=str(exc),
        )
    except Exception as exc:
        return CheckAdresResponse(
            success=False,
            document_type=body["document_type"],
            document_number=body["document_number"],
            errors=str(exc),
        )
