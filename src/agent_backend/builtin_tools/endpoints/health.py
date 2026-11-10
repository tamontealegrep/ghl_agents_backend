"""Liveness endpoint shared by the plugins."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    """Reports that the plugin is up."""
    return {"status": "ok"}
