"""Shared helpers of the development scripts: read a company's ``.env`` and build the URL of a target.

The scripts run on the host (not in the container) to test a company's backend by hand.
"""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TARGET_LOCAL, TARGET_DOCKER, TARGET_NGROK, TARGET_RENDER = "local", "docker", "ngrok", "render"
TARGETS = (TARGET_LOCAL, TARGET_DOCKER, TARGET_NGROK, TARGET_RENDER)


def read_env_file(path: Path) -> dict[str, str]:
    """Reads a ``KEY=VALUE`` file.

    Args:
        path: File to read. Blank lines and ``#`` comments are ignored; surrounding quotes are removed.

    Returns:
        The variables found.

    Raises:
        FileNotFoundError: The file does not exist.
    """
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def company_env_path(company: str, backend_root: Path = BACKEND_ROOT) -> Path:
    """Returns the ``.env`` of a company.

    Args:
        company: Folder name under ``companies/``.
        backend_root: Backend folder.

    Returns:
        ``companies/<company>/.env``.
    """
    return backend_root / "companies" / company / ".env"


def load_environment(company: str | None, env_file: Path | None) -> dict[str, str]:
    """Builds the variables a script works with: the process environment overlaid by the chosen ``.env``.

    Args:
        company: Company folder, or None.
        env_file: Explicit file; takes precedence over ``company``.

    Returns:
        The merged variables (the file wins over the process environment).

    Raises:
        FileNotFoundError: The chosen file does not exist.
    """
    path = env_file or (company_env_path(company) if company else None)
    return {**os.environ, **(read_env_file(path) if path else {})}


def base_url(env: dict[str, str], target: str) -> str:
    """Returns the base URL of a target.

    Args:
        env: Variables (see ``load_environment``).
        target: ``local`` (``python -m agent_backend`` on ``HOST``/``PORT``), ``docker`` (the container, published on
            ``HOST_PORT``), ``ngrok`` or ``render``.

    Returns:
        The URL without a trailing slash.

    Raises:
        ValueError: The target is unknown or lacks its variables.
    """
    if target == TARGET_RENDER:
        url = env.get("RENDER_BASE_URL", "").strip()
        if not url:
            raise ValueError("RENDER_BASE_URL is empty")
        return url.rstrip("/")
    if target == TARGET_NGROK:
        if env.get("NGROK_BASE_URL", "").strip():
            return env["NGROK_BASE_URL"].strip().rstrip("/")
        if env.get("NGROK_DOMAIN", "").strip():
            return f"https://{env['NGROK_DOMAIN'].strip()}"
        raise ValueError("NGROK_BASE_URL and NGROK_DOMAIN are both empty")
    if target == TARGET_DOCKER:
        return f"http://127.0.0.1:{env.get('HOST_PORT', '').strip() or '8010'}"
    if target == TARGET_LOCAL:
        host = env.get("HOST", "127.0.0.1").strip() or "127.0.0.1"
        host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        return f"http://{host}:{env.get('PORT', '8010').strip() or '8010'}"
    raise ValueError(f"Unknown target '{target}'. Options: {', '.join(TARGETS)}")


def default_target(env: dict[str, str]) -> str:
    """Returns the target used when ``--target`` is not given.

    Args:
        env: Variables; ``SEND_REQUEST_DEFAULT_TARGET`` chooses it.

    Returns:
        The configured target, ``local`` when unset (a remote deployment is never the silent default).

    Raises:
        ValueError: The configured value is not a known target.
    """
    target = env.get("SEND_REQUEST_DEFAULT_TARGET", "").strip().lower() or TARGET_LOCAL
    if target not in TARGETS:
        raise ValueError(f"SEND_REQUEST_DEFAULT_TARGET is '{target}'. Options: {', '.join(TARGETS)}")
    return target
