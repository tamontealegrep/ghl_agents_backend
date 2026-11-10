"""API_TOKEN and WEBHOOK_TOKEN protect chat, tools and webhooks; /health stays open."""

from pathlib import Path

from fastapi.testclient import TestClient

from agent_backend.app import create_app
from agent_backend.settings import Settings

BUNDLES = Path(__file__).resolve().parents[2] / "companies" / "babynova" / "bundles"
TOOL = "/agents/babynova/tools/calendars"
BUILTIN = "/builtin-tools/time-now"
WEBHOOK = "/agents/babynova/surrogate-questions-text"


def _client(**tokens):
    settings = Settings(
        host="127.0.0.1", port=8010, agents_dir=BUNDLES, admin_token=None, company="babynova", **tokens
    )
    return TestClient(create_app(settings))


def test_without_tokens_everything_stays_open():
    client = _client()
    assert client.get(TOOL).status_code == 200
    assert client.post(BUILTIN, json={}).status_code != 401


def test_tools_and_builtin_tools_require_the_api_token():
    client = _client(api_token="s3cret")
    assert client.get(TOOL).status_code == 401
    assert client.post(BUILTIN, json={}).status_code == 401
    assert client.get(TOOL, headers={"X-API-Key": "wrong"}).status_code == 401


def test_the_api_token_is_accepted_as_x_api_key_or_bearer():
    client = _client(api_token="s3cret")
    assert client.get(TOOL, headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get(TOOL, headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_chat_requires_the_api_token():
    client = _client(api_token="s3cret")
    url = "/agents/babynova_surrogate_questions_voice/chat"
    assert client.post(url, json={"message": "hi"}).status_code == 401


def test_health_is_always_open():
    assert _client(api_token="s3cret", webhook_token="w").get("/health").status_code == 200


def test_webhook_requires_its_own_token_not_the_api_token():
    client = _client(api_token="s3cret", webhook_token="hook")
    assert client.post(WEBHOOK, json={}).status_code == 401
    assert client.post(WEBHOOK, json={}, headers={"X-API-Key": "s3cret"}).status_code == 401
    assert client.post(WEBHOOK, json={}, headers={"X-Webhook-Token": "hook"}).status_code != 401


def test_the_tool_client_carries_the_api_token():
    from agent_backend.tool_client import ToolRoutingClient

    client = ToolRoutingClient(headers={"X-API-Key": "s3cret"})
    assert client.headers["x-api-key"] == "s3cret"


def test_tokens_come_from_the_environment():
    settings = Settings.from_env({"API_TOKEN": "a", "WEBHOOK_TOKEN": "w"})
    assert (settings.api_token, settings.webhook_token) == ("a", "w")
    assert Settings.from_env({}).api_token is None
