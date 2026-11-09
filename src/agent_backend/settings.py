"""Process-level settings for the agent backend, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_LOOPBACK = "127.0.0.1"
_WILDCARD_HOSTS = {"0.0.0.0", "::"}


@dataclass(frozen=True)
class Settings:
    """Backend settings shared by every agent.

    Anything that differs between agents lives in the agent's own
    ``agent.yaml`` instead, so deploying a new agent never needs a new
    setting here.

    Attributes:
        host: Interface the HTTP server binds to.
        port: Port the HTTP server binds to.
        agents_dir: Directory scanned for agent bundles (one subfolder each).
        admin_token: When set, admin endpoints require it as a bearer token.
        company: Company this container serves (``COMPANY``). When set, the agents' webhooks
            are mounted at ``/agents/<company>/<path>`` instead of ``/agents/<slug>/<path>``.
    """

    host: str
    port: int
    agents_dir: Path
    admin_token: str | None
    company: str | None = None

    @property
    def self_base_url(self) -> str:
        """URL the backend uses to call its own tool routes.

        Returns:
            ``http://<loopback-or-host>:<port>`` without a trailing slash.
        """
        host = _LOOPBACK if self.host in _WILDCARD_HOSTS else self.host
        return f"http://{host}:{self.port}"

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Settings:
        """Builds settings from environment variables.

        Args:
            environ: Mapping to read from. Defaults to ``os.environ``; tests
                pass their own to avoid touching the process environment.

        Returns:
            The resolved settings.
        """
        env = os.environ if environ is None else environ
        return cls(
            host=env.get("HOST", _LOOPBACK),
            port=int(env.get("PORT", "8010")),
            agents_dir=Path(env.get("AGENTS_DIR", "bundles")).resolve(),
            admin_token=env.get("ADMIN_TOKEN") or None,
            company=env.get("COMPANY") or None,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns the process-wide settings, reading the environment once.

    Returns:
        The cached ``Settings`` instance.
    """
    return Settings.from_env()
