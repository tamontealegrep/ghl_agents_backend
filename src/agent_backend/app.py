"""Application factory: one FastAPI app that serves every agent bundle."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agent_backend import routes
from agent_backend.builtin_tools.router import router as builtin_tools_router
from agent_backend.bundle import AgentBundle, discover_bundles
from agent_backend.channels.ghl.client import ghl_client_config_for
from agent_backend.channels.ghl.endpoint import (
    CompiledAgentGhlConfig,
    build_compiled_agent_router,
    load_phone_whitelist,
)
from agent_backend.loader import AgentRegistry
from agent_backend.plugins import load_tool_router
from agent_backend.settings import Settings, get_settings
from agent_backend.tool_client import BUILTIN_TOOLS_PREFIX

logger = logging.getLogger("agent_backend")


def _ghl_config(bundle: AgentBundle) -> CompiledAgentGhlConfig | None:
    """Translates a bundle's ``agent.yaml`` into the GHL endpoint config.

    Args:
        bundle: Bundle to translate.

    Returns:
        The endpoint config, or ``None`` if the agent has no GHL channel.
    """
    ghl = bundle.config.ghl
    if ghl is None:
        return None
    phones, enforce = load_phone_whitelist(
        ghl.allowed_phones_env or f"{bundle.env_prefix}_ALLOWED_PHONES",
        ghl.enforce_whitelist_env or f"{bundle.env_prefix}_ENFORCE_PHONE_WHITELIST",
        default_phones=ghl.default_allowed_phones,
    )
    token_envs = ghl.token_envs
    return CompiledAgentGhlConfig(
        slug=bundle.slug,
        path=ghl.path,
        allowed_phones=phones,
        debounce_seconds=ghl.debounce_seconds,
        ghl_client_config=lambda: ghl_client_config_for(token_envs),
        enforce_phone_whitelist=enforce,
        closing_message_lookback_days=ghl.closing_message_lookback_days,
        closing_message=ghl.closing_message,
        unsupported_media_message=ghl.unsupported_media_message,
        redirect_widget_to_whatsapp=ghl.redirect_widget_to_whatsapp,
    )


def _mount_bundle(app: FastAPI, registry: AgentRegistry, bundle: AgentBundle, company: str | None = None) -> None:
    """Mounts one agent's tool plugin and channels, isolating its failures.

    A broken bundle is logged and skipped so it cannot take down the others.

    Args:
        app: Application to mount on.
        registry: Registry the channels load graphs from.
        bundle: Bundle to mount.
        company: Company id. Webhooks go under ``/agents/<company>``; without it, under ``/agents/<slug>``.
    """
    prefix = f"/agents/{bundle.slug}"
    try:
        tools_router = load_tool_router(bundle)
        if tools_router is not None:
            app.include_router(tools_router, prefix=f"{prefix}/tools", tags=[f"{bundle.slug}.tools"])
        ghl_config = _ghl_config(bundle)
        if ghl_config is not None:
            app.include_router(
                build_compiled_agent_router(ghl_config, registry),
                prefix=f"/agents/{company}" if company else prefix,
                tags=[f"{bundle.slug}.ghl"],
            )
    except Exception:
        logger.error("Bundle %r failed to mount and was skipped.", bundle.slug, exc_info=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Builds the backend application.

    Args:
        settings: Settings to use. Defaults to the process environment.

    Returns:
        A FastAPI app serving every bundle found under ``settings.agents_dir``.
    """
    settings = settings or get_settings()
    app = FastAPI(title="Agent Backend")
    app.state.settings = settings
    app.state.registry = registry = AgentRegistry(settings)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.error("Validation error for %s: %s", request.url, exc.errors())
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @app.get("/health", include_in_schema=False)
    def _health() -> dict[str, object]:
        return {"status": "ok", "agents": sorted(bundles)}

    app.include_router(routes.router, tags=["agents"])
    app.include_router(builtin_tools_router, prefix=BUILTIN_TOOLS_PREFIX, tags=["builtin-tools"])
    bundles = discover_bundles(settings.agents_dir)
    for bundle in bundles.values():
        _mount_bundle(app, registry, bundle, settings.company)
    logger.info("Serving %d agent(s) from %s: %s", len(bundles), settings.agents_dir, ", ".join(bundles))
    return app
