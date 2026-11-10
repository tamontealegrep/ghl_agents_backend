"""Booking and finding are tied to the conversation's GHL contact, end to end.

The GHL webhook puts contact_id in the contact; every compiled agent that books or finds an appointment tells the
model to send it; the tool contracts mark it required. If any link breaks, appointments could again be attached to a
contact found by e-mail or phone.
"""

import json
from pathlib import Path

import pytest

from agent_backend.channels.ghl.request import GhlAgentRequest

COMPANIES = Path(__file__).resolve().parents[2] / "companies"
SCHEDULING_AGENTS = [
    ("babynova", "babynova_surrogate_questions_text"),
    ("babynova", "babynova_surrogate_questions_voice"),
    ("family_aims", "family_aims_sam_text"),
    ("family_aims", "family_aims_sam_es_voice"),
    ("family_aims", "family_aims_sam_en_voice"),
    ("family_aims", "family_aims_sam_pt_voice"),
]
CONTACT_TOOLS = ("book_appointment", "find_appointment")


def _graph(company: str, slug: str) -> dict:
    return json.loads((COMPANIES / company / "bundles" / slug / "graph.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("company", "slug"), SCHEDULING_AGENTS)
def test_every_booking_and_finding_step_sends_the_contact_id(company, slug):
    nodes = _graph(company, slug)["graph"]["nodes"]
    steps = [n for n in nodes if n.get("execute") in CONTACT_TOOLS]

    assert {n["execute"] for n in steps} == set(CONTACT_TOOLS)
    for step in steps:
        assert any("contact_id = {{contact.contact_id}}" in line for line in step["do"]), step["do"]


@pytest.mark.parametrize(("company", "slug"), SCHEDULING_AGENTS)
def test_the_contracts_declare_the_contact_id(company, slug):
    """Declared but not marked required: the runtime skips a call with a missing required input in silence, while
    this way the call reaches the tool, which answers missing_contact_id and the failure shows up."""
    contracts = _graph(company, slug)["tool_contracts"]
    by_name = {c["name"]: c for c in (contracts.values() if isinstance(contracts, dict) else contracts)}

    for tool in CONTACT_TOOLS:
        inputs = {i["name"]: i for i in by_name[tool]["inputs"]}
        assert "contact_id" in inputs and inputs["contact_id"]["required"] is False, (slug, tool)


@pytest.mark.parametrize(
    "payload",
    [
        {"contactId": "abc123", "locationId": "loc9", "message": "hola"},
        {"contact_id": "abc123", "locationId": "loc9", "message": "hola"},
        {"customData": {"contact_id": "abc123"}, "locationId": "loc9", "message": "hola"},
    ],
)
def test_the_webhook_puts_contact_id_and_location_id_in_the_contact(payload):
    contact = GhlAgentRequest.model_validate(payload).contact

    assert contact["contact_id"] == "abc123" and contact["location_id"] == "loc9"
