"""Tool plugin for the surrogacy agents; the backend mounts ``router`` under ``/agents/<slug>/tools``."""

from .api.v1.router import api_router as router

__all__ = ["router"]
