"""Webhooks are served under ``/agents/<company>/`` when ``COMPANY`` is set."""

from pathlib import Path

from agent_backend.app import create_app
from agent_backend.settings import Settings

BUNDLES = Path(__file__).resolve().parents[2] / "companies" / "babynova" / "bundles"


def _paths(company):
    app = create_app(Settings(host="127.0.0.1", port=8010, agents_dir=BUNDLES, admin_token=None, company=company))
    return {route.path for route in app.routes if hasattr(route, "path")}


def test_webhooks_use_the_company_id_when_it_is_set():
    paths = _paths("babynova")
    assert "/agents/babynova/surrogate-questions-text" in paths
    assert "/agents/babynova/triage-text" in paths
    assert "/agents/babynova_surrogate_questions_text/surrogate-questions-text" not in paths


def test_tools_are_served_once_under_the_company():
    paths = _paths("babynova")
    assert "/agents/babynova/tools/book-appointment-google" in paths
    assert "/agents/babynova/tools/surrogate-classification" in paths
    assert not any(p.startswith("/agents/babynova_") and "/tools/" in p for p in paths)


def test_without_a_company_tools_stay_under_each_agent():
    assert "/agents/babynova_surrogate_questions_voice/tools/book-appointment-google" in _paths(None)


def test_without_a_company_webhooks_fall_back_to_the_agent_slug():
    assert "/agents/babynova_surrogate_questions_text/surrogate-questions-text" in _paths(None)


def test_agents_call_their_tools_under_the_company(tmp_path):
    from agent_backend.loader import AgentRegistry

    settings = Settings(host="127.0.0.1", port=8010, agents_dir=tmp_path, admin_token=None, company="acme")
    assert AgentRegistry(settings).tools_base_url("any_agent") == "http://127.0.0.1:8010/agents/acme/tools"


def test_company_comes_from_the_environment():
    base = {"HOST": "127.0.0.1"}
    assert Settings.from_env({**base, "COMPANY": "acme"}).company == "acme"
    assert Settings.from_env(base).company is None
