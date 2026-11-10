"""HTTP client used by the graph runtime to call an agent's tools.

The compiled graph POSTs to ``{base_url}/{tool_name}`` with the snake_case name
from the tool contract. Hand-written plugins usually expose kebab-case routes,
and shared tools live under the built-in prefix, so a 404 is retried on the
remaining candidates. Nothing here knows any agent or vertical by name.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

BUILTIN_TOOLS_PREFIX = "/builtin-tools"


def _builtin_tool_names() -> frozenset[str]:
    """Kebab-case names of the shared built-in tools (``calculate-bmi``, ``time-now``...)."""
    from agent_backend.builtin_tools.router import router

    return frozenset(route.path.lstrip("/") for route in router.routes if hasattr(route, "path"))


def candidate_urls(url: str, route_suffixes: tuple[str, ...] = ()) -> list[str]:
    """Lists the URLs to try for a tool call, most likely first.

    Order: the agent's kebab-case route with each configured suffix, the plain
    kebab-case route, then the shared built-in tool. Routes are always kebab-case:
    the snake_case name of the contract is never tried.
    A built-in tool (``calculate_bmi``, ``time_now``...) never tries the suffixes:
    only its plain kebab-case route, then the built-in one.

    Args:
        url: The ``{base_url}/{tool_name}`` URL the runtime requested.
        route_suffixes: Suffixes to try first, in order (see ``AgentConfig``).

    Returns:
        Unique candidate URLs.
    """
    parts = urlsplit(url)
    head, _, tail = parts.path.rpartition("/")
    kebab = tail.replace("_", "-")
    suffixes = () if kebab in _builtin_tool_names() else route_suffixes
    suffixed = [f"{head}/{kebab}{s}" for s in suffixes if not kebab.endswith(s)]
    paths = [*suffixed, f"{head}/{kebab}", f"{BUILTIN_TOOLS_PREFIX}/{kebab}"]
    return [
        urlunsplit((parts.scheme, parts.netloc, p, parts.query, parts.fragment)) for p in dict.fromkeys(paths)
    ]


class ToolRoutingClient(httpx.Client):
    """``httpx.Client`` that retries a 404 tool POST on the other candidates.

    The first URL that does not answer 404 is remembered per requested URL,
    so only a tool's first call can pay for extra requests. If every candidate
    answers 404, the first response is returned so a genuine application 404
    keeps its own body.

    Args:
        args: Forwarded to ``httpx.Client``.
        route_suffixes: Suffixes tried before a tool's plain route name.
        kwargs: Forwarded to ``httpx.Client``.
    """

    def __init__(self, *args: Any, route_suffixes: tuple[str, ...] = (), **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._route_suffixes = route_suffixes
        self._resolved: dict[str, str] = {}

    def post(self, url: Any, *args: Any, **kwargs: Any) -> httpx.Response:  # type: ignore[override]
        """Posts to ``url``, falling back across candidate routes on 404.

        Args:
            url: The requested tool URL.
            args: Forwarded to ``httpx.Client.post``.
            kwargs: Forwarded to ``httpx.Client.post``.

        Returns:
            The first non-404 response, or the first response if all were 404.
        """
        requested = str(url)
        candidates = (
            [self._resolved[requested]]
            if requested in self._resolved
            else candidate_urls(requested, self._route_suffixes)
        )

        first_response: httpx.Response | None = None
        for candidate in candidates:
            response = super().post(candidate, *args, **kwargs)
            if response.status_code != 404:
                self._resolved[requested] = candidate
                return response
            first_response = first_response or response
        assert first_response is not None  # candidates is never empty
        return first_response
