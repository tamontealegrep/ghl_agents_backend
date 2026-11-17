"""A fake GoHighLevel API for the built-in tool tests."""

from types import SimpleNamespace

import httpx
import pytest

from agent_backend.builtin_tools.services import ghl_contacts, ghl_http

CONFIG = SimpleNamespace(base_url="https://ghl.test", version="v3", token="tok-123", send_message_timeout_seconds=5)


@pytest.fixture
def ghl(monkeypatch):
    """Points the tools at a fake GHL: records the requests and answers with ``state["reply"]``."""
    state = {
        "requests": [],
        "locations": [],
        "reply": lambda request: httpx.Response(201, json={"tags": ["vip"], "tagsAdded": ["vip"]}),
    }
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["reply"](request)

    def config_for(location_id):
        state["locations"].append(location_id)
        return CONFIG

    monkeypatch.setattr(ghl_http, "ghl_client_config_for_location", config_for)
    monkeypatch.setattr(ghl_contacts, "ghl_client_config_for_location", config_for)
    monkeypatch.setattr(
        ghl_http.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    return state
