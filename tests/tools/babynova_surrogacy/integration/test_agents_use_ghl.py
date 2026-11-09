"""BabyNova's scheduling agents call the GoHighLevel tools first."""

from pathlib import Path

import pytest
from agent_backend.bundle import discover_bundles
from agent_backend.tool_client import candidate_urls

BUNDLES = Path(__file__).resolve().parents[4] / "companies" / "babynova" / "bundles"
SCHEDULING_AGENTS = [
    "babynova_surrogate_questions_text",
    "babynova_surrogate_questions_text_v2",
    "babynova_surrogate_questions_voice",
]


@pytest.mark.parametrize("slug", SCHEDULING_AGENTS)
@pytest.mark.parametrize("tool", ["get_available_slots", "book_appointment", "find_appointment", "edit_appointment", "cancel_appointment"])
def test_scheduling_tools_resolve_to_the_ghl_routes_first(slug, tool):
    bundle = discover_bundles(BUNDLES)[slug]
    urls = candidate_urls(f"http://x/agents/{slug}/tools/{tool}", bundle.config.tool_route_suffixes)
    assert urls[0].endswith(f"/{tool.replace('_', '-')}-ghl")


@pytest.mark.parametrize("slug", SCHEDULING_AGENTS)
def test_the_sur_routes_still_work_for_the_other_tools(slug):
    bundle = discover_bundles(BUNDLES)[slug]
    urls = candidate_urls(f"http://x/agents/{slug}/tools/check_documentation", bundle.config.tool_route_suffixes)
    assert any(u.endswith("/check-documentation-sur") for u in urls)
