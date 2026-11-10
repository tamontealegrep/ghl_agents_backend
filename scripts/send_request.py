"""Calls a tool or a chat of a running backend, to test a company by hand.

Examples (from ``backend/``)::

    python scripts/send_request.py --company babynova --list
    python scripts/send_request.py --company babynova --agent babynova_triage_obstetrico_text --tool calendars --method GET
    python scripts/send_request.py --company family_aims --target ngrok --agent family_aims_sam_text \\
        --tool get-available-slots-ghl --payload '{"calendar_type": "IVF"}'
    python scripts/send_request.py --company babynova --agent X --tool book-appointment-ghl --show-default

The variables come from ``companies/<company>/.env``: ``HOST``/``PORT`` (target ``local``), ``NGROK_BASE_URL`` or
``NGROK_DOMAIN`` (``ngrok``), ``RENDER_BASE_URL`` (``render``) and ``SEND_REQUEST_DEFAULT_TARGET``. The server must
already be running (``docker compose up`` or ``python -m agent_backend``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import devenv


def list_operations(openapi: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """Lists the agent operations of an OpenAPI document.

    Args:
        openapi: The backend's ``/openapi.json``.

    Returns:
        ``(slug, tool, method, path)`` for every ``/agents/<slug>/...`` operation, sorted. ``tool`` is the path
        after the slug, e.g. ``tools/book-appointment-ghl`` or ``chat``.
    """
    found = []
    for path, methods in openapi.get("paths", {}).items():
        parts = path.strip("/").split("/", 2)
        if parts[0] != "agents" or len(parts) < 3:
            continue
        for method in methods:
            found.append((parts[1], parts[2], method.upper(), path))
    return sorted(found)


def _resolve(openapi: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    node: Any = openapi
    for key in ref.lstrip("#/").split("/"):
        node = node[key]
    return node


def default_payload(openapi: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    """Builds a starting payload from the operation's request schema.

    Args:
        openapi: The backend's ``/openapi.json``.
        path: Operation path.
        method: HTTP method.

    Returns:
        For each field, its first ``examples`` value, else its default, else an empty string if it is required.
    """
    body = openapi["paths"][path][method.lower()].get("requestBody", {})
    schema = body.get("content", {}).get("application/json", {}).get("schema")
    if not schema:
        return {}
    schema = _resolve(openapi, schema)
    required = set(schema.get("required", []))
    payload: dict[str, Any] = {}
    for name, prop in schema.get("properties", {}).items():
        if prop.get("examples"):
            payload[name] = prop["examples"][0]
        elif "default" in prop and prop["default"] is not None:
            payload[name] = prop["default"]
        elif name in required:
            payload[name] = ""
    return payload


def find_operation(openapi: dict[str, Any], slug: str, tool: str, method: str | None) -> tuple[str, str]:
    """Finds the path of ``/agents/<slug>/<tool>`` (``tool`` may omit the ``tools/`` prefix).

    Args:
        openapi: The backend's ``/openapi.json``.
        slug: Agent folder name.
        tool: Tool or route name.
        method: HTTP method, or None for the only one the path has (``POST`` preferred).

    Returns:
        ``(path, method)``.

    Raises:
        ValueError: The operation does not exist; the message lists what does.
    """
    wanted = {f"{slug}/{tool}", f"{slug}/tools/{tool}"}
    matches = [
        (p, m)
        for s, t, m, p in list_operations(openapi)
        if f"{s}/{t}" in wanted and (method is None or m == method.upper())
    ]
    if not matches:
        available = (
            ", ".join(sorted({f"{s}/{t}" for s, t, _, _ in list_operations(openapi) if s == slug}))
            or "(agent not found)"
        )
        raise ValueError(f"No operation /agents/{slug}/{tool}. Available: {available}")
    matches.sort(key=lambda pm: pm[1] != "POST")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--company", help="Folder under companies/ whose .env is read.")
    parser.add_argument("--env-file", type=Path, help="Explicit .env file (overrides --company).")
    parser.add_argument(
        "--target",
        choices=devenv.TARGETS,
        help="Where the backend runs (default SEND_REQUEST_DEFAULT_TARGET, else local).",
    )
    parser.add_argument("--base-url", help="Explicit base URL (overrides --target).")
    parser.add_argument("--agent", help="Agent folder name.")
    parser.add_argument(
        "--tool", help="Tool name (tools/ prefix optional) or `chat`, `reset`, `admin/reload`."
    )
    parser.add_argument("--method", help="HTTP method (default: POST when it exists).")
    parser.add_argument("--payload", help="JSON body.")
    parser.add_argument("--payload-file", type=Path, help="File with the JSON body.")
    parser.add_argument(
        "--list", action="store_true", help="List the agents and operations of the target and exit."
    )
    parser.add_argument(
        "--show-default", action="store_true", help="Print the default payload of the operation and exit."
    )
    args = parser.parse_args(argv)

    try:
        env = devenv.load_environment(args.company, args.env_file)
        root = (args.base_url or devenv.base_url(env, args.target or devenv.default_target(env))).rstrip("/")
        openapi = httpx.get(f"{root}/openapi.json", timeout=15).json()
        if args.list:
            for slug, tool, method, _ in list_operations(openapi):
                print(f"{slug:48} {method:5} {tool}")
            return 0
        if not (args.agent and args.tool):
            parser.error("--agent and --tool are required (or use --list)")
        path, method = find_operation(openapi, args.agent, args.tool, args.method)
        payload = default_payload(openapi, path, method)
        if args.show_default:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        if args.payload_file:
            payload.update(json.loads(args.payload_file.read_text(encoding="utf-8")))
        if args.payload:
            payload.update(json.loads(args.payload))
        headers = {"Authorization": f"Bearer {env['ADMIN_TOKEN']}"} if env.get("ADMIN_TOKEN") else {}
        if env.get("API_TOKEN"):
            headers["X-API-Key"] = env["API_TOKEN"]
        if env.get("WEBHOOK_TOKEN"):
            headers["X-Webhook-Token"] = env["WEBHOOK_TOKEN"]
        print(f"{method} {root}{path}", file=sys.stderr)
        response = httpx.request(
            method, f"{root}{path}", json=payload if method != "GET" else None, headers=headers, timeout=120
        )
        print(f"HTTP {response.status_code}", file=sys.stderr)
        try:
            print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        except ValueError:
            print(response.text)
        return 0 if response.status_code < 400 else 1
    except (ValueError, FileNotFoundError, httpx.HTTPError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
