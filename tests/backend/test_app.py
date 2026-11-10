"""Integration tests for the application factory (no LLM calls)."""

from dataclasses import replace

from fastapi.testclient import TestClient

from agent_backend.app import create_app
from tests.backend.conftest import PLUGIN_SOURCE, make_bundle

GHL_YAML = "ghl:\n  path: /ghl\n  default_allowed_phones: '+573001112233'\n"


def test_health_lists_discovered_agents(settings, agents_dir):
    make_bundle(agents_dir, "alpha")
    make_bundle(agents_dir, "beta")
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json() == {"status": "ok", "agents": ["alpha", "beta"]}


def test_agent_tool_plugin_is_mounted_under_its_slug(settings, agents_dir):
    make_bundle(agents_dir, "alpha", plugin=PLUGIN_SOURCE)
    with TestClient(create_app(settings)) as client:
        assert client.post("/agents/alpha/tools/ping-tool").json() == {"pong": True}
        assert client.post("/agents/beta/tools/ping-tool").status_code == 404


def test_builtin_tools_are_available_to_every_agent(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/builtin-tools/echo", json={}).status_code != 404


def test_ghl_webhook_is_mounted_only_when_configured(settings, agents_dir):
    make_bundle(agents_dir, "with_ghl", agent_yaml=GHL_YAML)
    make_bundle(agents_dir, "without")
    with TestClient(create_app(settings)) as client:
        paths = client.get("/openapi.json").json()["paths"]
    assert "/agents/with_ghl/ghl" in paths
    assert "/agents/without/ghl" not in paths


def test_ghl_webhook_ignores_phone_outside_allow_list(settings, agents_dir):
    make_bundle(agents_dir, "a", agent_yaml=GHL_YAML)
    body = {"contact": {"phone": "+570000000000"}, "location_id": "L", "contact_id": "C", "message": "hi"}
    with TestClient(create_app(settings)) as client:
        response = client.post("/agents/a/ghl", json=body)
    assert response.status_code == 202
    assert response.json() == {"status": "ignored", "reason": "phone_not_allowed"}


def test_broken_bundle_is_skipped_without_breaking_the_others(settings, agents_dir):
    make_bundle(agents_dir, "good", plugin=PLUGIN_SOURCE)
    make_bundle(agents_dir, "bad", plugin="raise RuntimeError('boom')\n")
    with TestClient(create_app(settings)) as client:
        assert client.post("/agents/good/tools/ping-tool").status_code == 200
        assert client.post("/agents/bad/tools/ping-tool").status_code == 404


def test_unknown_agent_chat_is_404(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/agents/ghost/chat", json={"thread_id": "t"}).status_code == 404


def test_admin_routes_require_token_when_configured(settings, agents_dir):
    make_bundle(agents_dir, "a")
    with TestClient(create_app(replace(settings, admin_token="s3cret"))) as client:
        assert client.post("/agents/a/admin/reload").status_code == 401
        assert (
            client.post("/agents/a/admin/reload", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
