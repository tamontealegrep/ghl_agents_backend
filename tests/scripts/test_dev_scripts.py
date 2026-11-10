"""The development scripts (send_request, dev_tunnel) that read a company's .env."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import devenv
import send_request

BABYNOVA = Path(__file__).resolve().parents[2] / "companies" / "babynova" / "bundles"


@pytest.fixture(scope="module")
def openapi():
    from agent_backend.app import create_app
    from agent_backend.settings import Settings

    settings = Settings(host="127.0.0.1", port=8010, agents_dir=BABYNOVA, admin_token=None)
    return TestClient(create_app(settings)).get("/openapi.json").json()


def test_env_file_is_parsed_ignoring_comments_and_quotes(tmp_path):
    (tmp_path / ".env").write_text('# c\nA=1\n\nB="two words"\nC=\nbad line\nD=x=y\n', encoding="utf-8")
    assert devenv.read_env_file(tmp_path / ".env") == {"A": "1", "B": "two words", "C": "", "D": "x=y"}


def test_the_file_wins_over_the_process_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PORT", "1111")
    monkeypatch.setenv("ONLY_IN_PROCESS", "yes")
    (tmp_path / ".env").write_text("PORT=2222\n", encoding="utf-8")
    env = devenv.load_environment(None, tmp_path / ".env")
    assert env["PORT"] == "2222" and env["ONLY_IN_PROCESS"] == "yes"


@pytest.mark.parametrize(
    ("env", "target", "expected"),
    [
        ({"HOST": "0.0.0.0", "PORT": "9000"}, "local", "http://127.0.0.1:9000"),
        ({}, "local", "http://127.0.0.1:8010"),
        ({"HOST_PORT": "8011", "PORT": "8010"}, "docker", "http://127.0.0.1:8011"),
        ({"NGROK_BASE_URL": "https://a.ngrok.dev/"}, "ngrok", "https://a.ngrok.dev"),
        ({"NGROK_DOMAIN": "a.ngrok.dev"}, "ngrok", "https://a.ngrok.dev"),
        ({"RENDER_BASE_URL": "https://x.onrender.com/"}, "render", "https://x.onrender.com"),
    ],
)
def test_base_url_per_target(env, target, expected):
    assert devenv.base_url(env, target) == expected


@pytest.mark.parametrize(("env", "target"), [({}, "render"), ({}, "ngrok"), ({}, "mars")])
def test_a_target_without_its_variables_is_an_error(env, target):
    with pytest.raises(ValueError):
        devenv.base_url(env, target)


def test_the_default_target_is_local_unless_configured():
    assert devenv.default_target({}) == "local"
    assert devenv.default_target({"SEND_REQUEST_DEFAULT_TARGET": "RENDER"}) == "render"
    with pytest.raises(ValueError):
        devenv.default_target({"SEND_REQUEST_DEFAULT_TARGET": "prod"})


def test_the_operations_of_every_agent_are_listed(openapi):
    operations = send_request.list_operations(openapi)
    assert ("babynova_triage_obstetrico_text", "tools/calendars", "GET", "/agents/babynova_triage_obstetrico_text/tools/calendars") in operations
    assert any(t == "chat" for _, t, _, _ in operations)
    assert any(t == "tools/book-appointment-ghl" for _, t, _, _ in operations)


def test_a_tool_is_found_with_or_without_the_tools_prefix(openapi):
    slug = "babynova_surrogate_questions_text"
    assert send_request.find_operation(openapi, slug, "book-appointment-ghl", None) == (f"/agents/{slug}/tools/book-appointment-ghl", "POST")
    assert send_request.find_operation(openapi, slug, "tools/calendars", None)[1] == "GET"
    with pytest.raises(ValueError, match="Available"):
        send_request.find_operation(openapi, slug, "nope", None)


def test_the_default_payload_comes_from_the_request_schema(openapi):
    slug = "babynova_surrogate_questions_text"
    path, method = send_request.find_operation(openapi, slug, "book-appointment-ghl", None)
    payload = send_request.default_payload(openapi, path, method)
    assert payload["start_date"] == "2026-08-28T09:00:00-05:00"
    assert payload["calendar_type"] == "FT" and payload["iana_timezone"] == "America/Bogota"
