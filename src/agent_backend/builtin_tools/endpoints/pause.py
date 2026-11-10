"""Built-in tool: pauses the agent for a few seconds."""

import asyncio

from fastapi import APIRouter

from agent_backend.builtin_tools.schemas.pause import PauseRequest, PauseResponse

router = APIRouter()


@router.post("/pause", response_model=PauseResponse)
async def pause(req: PauseRequest) -> PauseResponse:
    """Waits the requested seconds before answering."""
    seconds = int(req.seconds) if isinstance(req.seconds, int) else 0
    if seconds > 0:
        await asyncio.sleep(seconds)
    return PauseResponse(success=True, seconds=seconds)
