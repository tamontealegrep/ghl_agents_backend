"""Webhooks are served under ``/agents/<company>/`` when ``COMPANY`` is set."""

from pathlib import Path

from agent_backend.app import create_app
from agent_backend.settings import Settings

BUNDLES = Path(__file__).resolve().parents[2] / "companies" / "babynova" / "bundles"


def _paths(company):
    app = create_app(
        Settings(host="127.0.0.1", port=8010, agents_dir=BUNDLES, admin_token=None, company=company)
    )
    return {route.path for route in app.routes if hasattr(route, "path")}


def test_webhooks_use_company_id():
    """With a company id set, webhooks are served under `/agents/<company>/`."""
    paths = _paths("babynova")
    assert "/agents/babynova/surrogate-questions-text" in paths
    assert "/agents/babynova/triage-text" in paths
    assert "/agents/babynova_surrogate_questions_text/surrogate-questions-text" not in paths


def test_tools_are_served_once_under_the_company():
    """Tools are mounted once under the company instead of once per agent."""
    paths = _paths("babynova")
    assert "/agents/babynova/tools/book-appointment-google" in paths
    assert "/agents/babynova/tools/surrogate-classification" in paths
    assert not any(p.startswith("/agents/babynova_") and "/tools/" in p for p in paths)


def test_no_company_tools_per_agent():
    """Without a company, tools stay under each agent."""
    assert "/agents/babynova_surrogate_questions_voice/tools/book-appointment-google" in _paths(None)


def test_no_company_webhooks_use_slug():
    """Without a company, webhooks fall back to the agent slug."""
    assert "/agents/babynova_surrogate_questions_text/surrogate-questions-text" in _paths(None)


def test_agents_call_tools_under_company(tmp_path):
    """Agents call their tools through the company base URL."""
    from agent_backend.loader import AgentRegistry

    settings = Settings(host="127.0.0.1", port=8010, agents_dir=tmp_path, admin_token=None, company="acme")
    assert AgentRegistry(settings).tools_base_url("any_agent") == "http://127.0.0.1:8010/agents/acme/tools"


def test_company_comes_from_the_environment():
    """The company id is read from the COMPANY environment variable."""
    base = {"HOST": "127.0.0.1"}
    assert Settings.from_env({**base, "COMPANY": "acme"}).company == "acme"
    assert Settings.from_env(base).company is None
