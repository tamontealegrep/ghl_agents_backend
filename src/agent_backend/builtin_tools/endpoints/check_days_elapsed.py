from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from agent_backend.builtin_tools.schemas.days_elapsed import CheckDaysElapsedRequest, CheckDaysElapsedResponse
from agent_backend.builtin_tools.services.days_elapsed import (
    check_days_elapsed,
    parse_days_threshold,
    parse_ymd_date,
)

router = APIRouter()


@router.post("/check-days-elapsed", response_model=CheckDaysElapsedResponse)
async def check_days_elapsed_endpoint(req: CheckDaysElapsedRequest):
    try:
        raw_date = str(req.date).strip() if req.date is not None else ""
        try:
            input_date = parse_ymd_date(raw_date)
        except ValueError:
            return CheckDaysElapsedResponse(
                success=True, errors="Invalid format, expected YYYY-MM-DD or YYYY/MM/DD"
            )

        days_threshold = parse_days_threshold(req.days)
        if days_threshold is None:
            return CheckDaysElapsedResponse(
                success=True, errors="The number of days must be an integer greater than 0"
            )

        today = datetime.now(ZoneInfo("UTC")).date()
        elapsed, days_elapsed = check_days_elapsed(input_date, today, days_threshold)
        return CheckDaysElapsedResponse(success=True, elapsed=elapsed, days_elapsed=days_elapsed, errors=None)

    except Exception as e:
        return CheckDaysElapsedResponse(success=False, errors=str(e))
