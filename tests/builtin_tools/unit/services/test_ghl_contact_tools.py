"""remove_tags, update_contact and update_opportunity: the GoHighLevel tools besides add_tags."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_backend.builtin_tools.services import ghl as custom_field_helpers
from agent_backend.builtin_tools.services.ghl_contacts import update_contact_service
from agent_backend.builtin_tools.services.ghl_custom_fields import normalize_custom_fields
from agent_backend.builtin_tools.services.ghl_opportunities import update_opportunity_service
from agent_backend.builtin_tools.services.ghl_tags import remove_tags_service
from tests.builtin_tools.app_factory import app

client = TestClient(app)


def _body(ghl, index=0):
    return json.loads(ghl["requests"][index].content)


# --------------------------------------------------------------------------------------------------- remove_tags


def test_remove_tags_sends_a_delete_with_the_tags_in_the_body(ghl):
    ghl["reply"] = lambda r: httpx.Response(200, json={"tags": ["assigned"], "tagsRemoved": ["contacted"]})

    result = asyncio.run(remove_tags_service([" contacted "], "contact1", "loc1"))

    assert result == {"success": True, "tags": ["assigned"], "tags_removed": ["contacted"]}
    (request,) = ghl["requests"]
    assert request.method == "DELETE"
    assert str(request.url) == "https://ghl.test/contacts/contact1/tags"
    assert request.headers["Version"] == "v3" and request.headers["Authorization"] == "Bearer tok-123"
    assert json.loads(request.content) == {"tags": ["contacted"]}
    assert ghl["locations"] == ["loc1"]


def test_removing_a_tag_the_contact_does_not_have_is_not_an_error(ghl):
    ghl["reply"] = lambda r: httpx.Response(200, json={"tags": ["a"], "tagsRemoved": []})
    assert asyncio.run(remove_tags_service("nope", "c")) == {"success": True, "tags": ["a"], "tags_removed": []}


def test_remove_tags_checks_its_input_before_calling_ghl(ghl):
    assert asyncio.run(remove_tags_service(["x"], " "))["errors"] == "contact_id is required"
    assert asyncio.run(remove_tags_service([], "c"))["errors"] == "No tags"
    assert ghl["requests"] == []


def test_remove_tags_reports_a_ghl_error(ghl):
    ghl["reply"] = lambda r: httpx.Response(401, json={"message": "Invalid token"})
    result = asyncio.run(remove_tags_service(["x"], "c"))
    assert result["success"] is False and "HTTP 401" in result["errors"] and "Invalid token" in result["errors"]


def test_remove_tags_route(ghl):
    ghl["reply"] = lambda r: httpx.Response(200, json={"tags": [], "tagsRemoved": ["contacted"]})
    response = client.post("/api/v1/remove-tags", json={"tags": "contacted", "contact_id": "c1", "location_id": "l"})
    assert response.status_code == 200
    assert response.json() == {"success": True, "tags": [], "tags_removed": ["contacted"], "errors": None}


# --------------------------------------------------------------------------------------------- custom fields


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"city": "Bogotá", "age": 30}, [("city", "Bogotá"), ("age", "30")]),
        (["city=Bogotá", " age = 30 "], [("city", "Bogotá"), ("age", "30")]),
        (["note=a=b"], [("note", "a=b")]),  # split on the first =
        ([{"key": "city", "value": "Bogotá"}, {"id": "x", "fieldValue": "1"}, {"name": "n", "field_value": "2"}],
         [("city", "Bogotá"), ("x", "1"), ("n", "2")]),
        ('{"city": "Bogotá"}', [("city", "Bogotá")]),
        ('[{"key": "city", "value": "Bogotá"}]', [("city", "Bogotá")]),
        ("city=Bogotá\nage=30", [("city", "Bogotá"), ("age", "30")]),
        ({"docs": ["cc", "ppt"]}, [("docs", "cc,ppt")]),
        (["city=A", "city=B"], [("city", "B")]),  # the last value of a repeated name wins
        (["sin igual", "=sin nombre", "vacio="], []),
        ({"a": None, "b": ""}, []),
        (None, []),
        ("", []),
    ],
)
def test_custom_fields_are_read_whatever_their_shape(raw, expected):
    assert normalize_custom_fields(raw) == expected


# ----------------------------------------------------------------------------------------------- update_contact


def test_update_contact_sends_only_what_is_given_with_ghl_names(ghl):
    ghl["reply"] = lambda r: httpx.Response(200, json={"succeeded": True, "contact": {"id": "c1"}})

    result = asyncio.run(
        update_contact_service(
            " c1 ", "loc1", {"first_name": " Laura ", "postal_code": "110111", "city": None, "dnd": False, "bogus": "x"}
        )
    )

    assert result == {"success": True, "contact_id": "c1", "updated_fields": ["first_name", "postal_code", "dnd"]}
    (request,) = ghl["requests"]
    assert request.method == "PUT" and str(request.url) == "https://ghl.test/contacts/c1"
    assert json.loads(request.content) == {"firstName": "Laura", "postalCode": "110111", "dnd": False}


def test_update_contact_never_sends_tags(ghl):
    asyncio.run(update_contact_service("c1", "l", {"first_name": "A"}))
    assert "tags" not in _body(ghl)


def test_update_contact_resolves_custom_fields_by_name_and_validates_options(ghl, monkeypatch):
    fields = {
        "city": {"id": "fieldcity0000001", "dataType": "SINGLE_OPTIONS", "picklistOptions": ["Bogotá", "Chía"]},
        "age": {"id": "fieldage00000001", "dataType": "TEXT"},
    }

    async def fake_find(location_id, name, config, headers):
        return fields.get(name)

    monkeypatch.setattr(custom_field_helpers, "_find_custom_field_by_name", fake_find)
    ghl["reply"] = lambda r: httpx.Response(200, json={"succeeded": True})

    ok = asyncio.run(update_contact_service("c1", "loc1", {"email": "a@b.co"}, {"city": "Chía", "age": 30}))

    assert ok["success"] is True and ok["updated_fields"] == ["email", "city", "age"]
    assert _body(ghl) == {
        "email": "a@b.co",
        "customFields": [{"id": "fieldcity0000001", "fieldValue": "Chía"}, {"id": "fieldage00000001", "fieldValue": "30"}],
    }

    ghl["requests"].clear()
    bad = asyncio.run(update_contact_service("c1", "loc1", None, {"city": "Medellín"}))
    assert bad["success"] is False and "Allowed: Bogotá, Chía" in bad["errors"]
    missing = asyncio.run(update_contact_service("c1", "loc1", None, {"nope": "x"}))
    assert "Custom field 'nope' not found" in missing["errors"]
    assert ghl["requests"] == []  # nothing is sent when a field cannot be resolved


def test_update_contact_uses_a_field_id_as_it_is_and_needs_a_location_for_names(ghl):
    ghl["reply"] = lambda r: httpx.Response(200, json={"succeeded": True})
    asyncio.run(update_contact_service("c1", None, None, {"uWLesAbC123456789": "x"}))
    assert _body(ghl)["customFields"] == [{"id": "uWLesAbC123456789", "fieldValue": "x"}]
    result = asyncio.run(update_contact_service("c1", None, None, {"city": "x"}))
    assert result["success"] is False and "location_id is required" in result["errors"]


def test_update_contact_with_nothing_to_change_does_not_call_ghl(ghl):
    assert asyncio.run(update_contact_service("c1", "l", {"city": None}))["errors"] == "Nothing to update"
    assert asyncio.run(update_contact_service("  ", "l", {"city": "x"}))["errors"] == "contact_id is required"
    assert ghl["requests"] == []


def test_update_contact_reports_ghl_errors_such_as_a_duplicate_email(ghl):
    ghl["reply"] = lambda r: httpx.Response(400, json={"message": "Duplicate email"})
    result = asyncio.run(update_contact_service("c1", "l", {"email": "a@b.co"}))
    assert result["success"] is False and "HTTP 400" in result["errors"] and "Duplicate email" in result["errors"]
    ghl["reply"] = lambda r: httpx.Response(200, json={"succeeded": False})
    assert asyncio.run(update_contact_service("c1", "l", {"city": "x"}))["success"] is False


def test_update_contact_route_accepts_snake_case_and_ghl_names(ghl):
    ghl["reply"] = lambda r: httpx.Response(200, json={"succeeded": True})

    snake = client.post("/api/v1/update-contact", json={"contact_id": "c1", "location_id": "l", "first_name": "Ana", "city": "Cali"})
    ghl_style = client.post("/api/v1/update-contact", json={"contactId": "c1", "firstName": "Ana", "postalCode": "760001"})

    assert snake.json() == {"success": True, "contact_id": "c1", "updated_fields": ["first_name", "city"], "errors": None}
    assert ghl_style.json()["updated_fields"] == ["first_name", "postal_code"]
    assert _body(ghl, 0) == {"firstName": "Ana", "city": "Cali"}


# ------------------------------------------------------------------------------------------- update_opportunity

OPPORTUNITY = {"opportunity": {"id": "o1", "status": "won", "pipelineId": "p1", "pipelineStageId": "s2", "name": "Deal", "monetaryValue": 1500.5}}


def test_update_opportunity_sends_only_what_is_given_with_ghl_names(ghl):
    ghl["reply"] = lambda r: httpx.Response(200, json=OPPORTUNITY)

    result = asyncio.run(
        update_opportunity_service(
            " o1 ", "loc1", {"status": "WON", "monetary_value": "$1,500.50", "pipeline_stage_id": "s2", "name": None, "assigned_to": "  "}
        )
    )

    assert result == {
        "success": True,
        "opportunity_id": "o1",
        "updated_fields": ["status", "monetary_value", "pipeline_stage_id"],
        "status": "won",
        "pipeline_id": "p1",
        "pipeline_stage_id": "s2",
        "name": "Deal",
        "monetary_value": 1500.5,
    }
    (request,) = ghl["requests"]
    assert request.method == "PUT" and str(request.url) == "https://ghl.test/opportunities/o1"
    assert json.loads(request.content) == {"status": "won", "monetaryValue": 1500.5, "pipelineStageId": "s2"}
    assert ghl["locations"] == ["loc1"]


def test_update_opportunity_checks_status_and_numbers_before_calling_ghl(ghl):
    assert "status must be one of" in asyncio.run(update_opportunity_service("o1", "l", {"status": "pending"}))["errors"]
    assert "monetary_value must be 0 or more" in asyncio.run(update_opportunity_service("o1", "l", {"monetary_value": -1}))["errors"]
    assert "must be a number" in asyncio.run(update_opportunity_service("o1", "l", {"monetary_value": "mucho"}))["errors"]
    assert "must be a number" in asyncio.run(update_opportunity_service("o1", "l", {"forecast_probability": True}))["errors"]
    assert asyncio.run(update_opportunity_service("o1", "l", {"name": None}))["errors"] == "Nothing to update"
    assert asyncio.run(update_opportunity_service("", "l", {"name": "x"}))["errors"] == "opportunity_id is required"
    assert ghl["requests"] == []


def test_update_opportunity_numbers_keep_integers_whole(ghl):
    ghl["reply"] = lambda r: httpx.Response(200, json=OPPORTUNITY)
    asyncio.run(update_opportunity_service("o1", "l", {"monetary_value": 500.0, "forecast_probability": "75"}))
    body = _body(ghl)
    assert body == {"monetaryValue": 500, "forecastProbability": 75}


def test_update_opportunity_custom_fields_go_by_id_or_key_without_the_prefix(ghl):
    ghl["reply"] = lambda r: httpx.Response(200, json=OPPORTUNITY)

    result = asyncio.run(
        update_opportunity_service("o1", "l", None, {"opportunity.source_detail": "web", "uWLesAbC123456789": "x"})
    )

    assert result["updated_fields"] == ["opportunity.source_detail", "uWLesAbC123456789"]
    assert _body(ghl)["customFields"] == [
        {"key": "source_detail", "fieldValue": "web"},
        {"id": "uWLesAbC123456789", "fieldValue": "x"},
    ]


def test_update_opportunity_reports_ghl_errors(ghl):
    ghl["reply"] = lambda r: httpx.Response(400, json={"code": "OPPORTUNITY_NO_DUPLICATE"})
    result = asyncio.run(update_opportunity_service("o1", "l", {"pipeline_id": "p9"}))
    assert result["success"] is False and "OPPORTUNITY_NO_DUPLICATE" in result["errors"]
    assert result["opportunity_id"] == "o1"


def test_update_opportunity_route(ghl):
    ghl["reply"] = lambda r: httpx.Response(200, json=OPPORTUNITY)

    response = client.post(
        "/api/v1/update-opportunity", json={"opportunityId": "o1", "locationId": "l", "status": "won", "monetaryValue": "1500.5"}
    )

    assert response.status_code == 200 and response.json()["success"] is True
    assert response.json()["status"] == "won"
    assert _body(ghl) == {"status": "won", "monetaryValue": 1500.5}


def test_the_new_tools_are_builtin_routes_the_runtime_finds():
    from agent_backend.tool_client import candidate_urls

    for tool in ("remove_tags", "update_contact", "update_opportunity"):
        assert f"http://x/builtin-tools/{tool.replace('_', '-')}" in candidate_urls(f"http://x/tools/{tool}")
