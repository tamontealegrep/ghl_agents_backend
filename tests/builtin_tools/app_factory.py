"""Minimal app exposing the built-in tools under the legacy ``/api/v1`` prefix, for tests."""

from fastapi import FastAPI

from agent_backend.builtin_tools.router import router

app = FastAPI(title="Built-in tools (test)")
app.include_router(router, prefix="/api/v1")
