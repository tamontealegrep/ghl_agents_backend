"""remove_tags, get_contact, update_contact and update_opportunity: the GoHighLevel tools besides add_tags."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_backend.builtin_tools.services import ghl as custom_field_helpers
from agent_backend.builtin_tools.services.ghl_contacts import get_contact_service, update_contact_service
from agent_backend.builtin_tools.services.ghl_custom_fields import normalize_custom_fields
from agent_backend.builtin_tools.services.ghl_opportunities import update_opportunity_service
from agent_backend.builtin_tools.services.ghl_tags import remove_tags_service
from tests.builtin_tools.app_factory import app

client = TestClient(app)


def _body(ghl, index=0):
    return json.loads(ghl["requests"][index].content)


# --------------------------------------------------------------------------------------------------- remove_tags


def test_remove_tags_sends_delete(ghl):
    """Removing tags sends a DELETE with the tags in the body."""
    ghl["reply"] = lambda r: httpx.Response(200, json={"tags": ["assigned"], "tagsRemoved": ["contacted"]})

    result = asyncio.run(remove_tags_service([" contacted "], "contact1", "loc1"))

    assert result == {"success": True, "tags": ["assigned"], "tags_removed": ["contacted"]}
    (request,) = ghl["requests"]
    assert request.method == "DELETE"
    assert str(request.url) == "https://ghl.test/contacts/contact1/tags"
    assert request.headers["Version"] == "v3" and request.headers["Authorization"] == "Bearer tok-123"
    assert json.loads(request.content) == {"tags": ["contacted"]}
    assert ghl["locations"] == ["loc1"]


def test_remove_missing_tag_is_ok(ghl):
    """Removing a tag the contact does not have is not an error."""
    ghl["reply"] = lambda r: httpx.Response(200, json={"tags": ["a"], "tagsRemoved": []})
    assert asyncio.run(remove_tags_service("nope", "c")) == {
        "success": True,
        "tags": ["a"],
        "tags_removed": [],
    }


def test_remove_tags_validates_input(ghl):
    """Missing contact id or tags are rejected before calling GHL."""
    assert asyncio.run(remove_tags_service(["x"], " "))["errors"] == "contact_id is required"
    assert asyncio.run(remove_tags_service([], "c"))["errors"] == "No tags"
    assert ghl["requests"] == []


def test_remove_tags_reports_ghl_error(ghl):
    """A GHL error is returned as data with its status and reason."""
    ghl["reply"] = lambda r: httpx.Response(401, json={"message": "Invalid token"})
    result = asyncio.run(remove_tags_service(["x"], "c"))
    assert (
        result["success"] is False and "HTTP 401" in result["errors"] and "Invalid token" in result["errors"]
    )


def test_remove_tags_route(ghl):
    """The remove-tags route answers with the service result."""
    ghl["reply"] = lambda r: httpx.Response(200, json={"tags": [], "tagsRemoved": ["contacted"]})
    response = client.post(
        "/api/v1/remove-tags", json={"tags": "contacted", "contact_id": "c1", "location_id": "l"}
    )
    assert response.status_code == 200
    assert response.json() == {"success": True, "tags": [], "tags_removed": ["contacted"], "errors": None}


# --------------------------------------------------------------------------------------------- custom fields


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"city": "Bogotá", "age": 30}, [("city", "Bogotá"), ("age", "30")]),
        (["city=Bogotá", " age = 30 "], [("city", "Bogotá"), ("age", "30")]),
        (["note=a=b"], [("note", "a=b")]),  # split on the first =
        (
            [
                {"key": "city", "value": "Bogotá"},
                {"id": "x", "fieldValue": "1"},
                {"name": "n", "field_value": "2"},
            ],
            [("city", "Bogotá"), ("x", "1"), ("n", "2")],
        ),
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
def test_custom_fields_any_shape(raw, expected):
    """Custom fields are normalised whether they come as a list or a dict."""
    assert normalize_custom_fields(raw) == expected


# ------------------------------------------------------------------------------------------------ get_contact

CONTACT = {
    "contact": {
        "id": "c1",
        "locationId": "loc1",
        "firstName": "Ana",
        "lastName": "Gómez",
        "email": "ana@example.org",
        "phone": "+573001112233",
        "city": "",
        "country": "CO",
        "dnd": False,
        "tags": ["assigned", "pendiente agenda"],
        "dateAdded": "2026-11-01T10:00:00.000Z",
        "customFields": [
            {"id": "f1", "value": "Chía"},
            {"id": "f2", "value": ""},
            {"id": "f3", "value": ["a", "b"]},
        ],
    }
}
FIELD_DEFINITIONS = {
    "customFields": [
        {"id": "f1", "name": "City raw"},
        {"id": "f2", "name": "Empty"},
        {"id": "f3", "fieldKey": "contact.multi"},
    ]
}


def _reply_contact(request):
    if request.url.path.endswith("/customFields"):
        return httpx.Response(200, json=FIELD_DEFINITIONS)
    return httpx.Response(200, json=CONTACT)


def test_get_contact_returns_fields_tags_and_named_custom_fields(ghl):
    """The contact comes with the data that has a value, its tags and its custom fields by name."""
    ghl["reply"] = _reply_contact

    result = asyncio.run(get_contact_service(" c1 ", "loc1"))

    assert result == {
        "success": True,
        "contact_id": "c1",
        "fields": {
            "first_name": "Ana",
            "last_name": "Gómez",
            "email": "ana@example.org",
            "phone": "+573001112233",
            "country": "CO",
            "dnd": False,
            "date_added": "2026-11-01T10:00:00.000Z",
        },
        "tags": ["assigned", "pendiente agenda"],
        "custom_fields": {"City raw": "Chía", "contact.multi": ["a", "b"]},
    }
    methods = [(r.method, r.url.path) for r in ghl["requests"]]
    assert methods == [("GET", "/contacts/c1"), ("GET", "/locations/loc1/customFields")]
    assert ghl["locations"] == ["loc1", "loc1"]


def test_get_contact_uses_the_contacts_location_to_name_fields(ghl):
    """Without a location_id the contact's own location is used to read the field names."""
    ghl["reply"] = _reply_contact
    result = asyncio.run(get_contact_service("c1"))
    assert result["custom_fields"]["City raw"] == "Chía"
    assert ghl["requests"][1].url.path == "/locations/loc1/customFields"


def test_get_contact_falls_back_to_field_ids(ghl):
    """If the field definitions cannot be read, the custom fields come by id."""
    ghl["reply"] = lambda r: (
        httpx.Response(403, text="no scope")
        if r.url.path.endswith("/customFields")
        else httpx.Response(200, json=CONTACT)
    )
    result = asyncio.run(get_contact_service("c1", "loc1"))
    assert result["success"] is True and result["custom_fields"] == {"f1": "Chía", "f3": ["a", "b"]}


def test_get_contact_validates_input(ghl):
    """A missing contact id is rejected before calling GHL."""
    assert asyncio.run(get_contact_service(" "))["errors"] == "contact_id is required"
    assert ghl["requests"] == []


def test_get_contact_reports_ghl_errors(ghl):
    """A GHL error, such as an unknown contact, is returned as data."""
    ghl["reply"] = lambda r: httpx.Response(404, json={"message": "Contact not found"})
    result = asyncio.run(get_contact_service("nope", "loc1"))
    assert result["success"] is False and "HTTP 404" in result["errors"] and "not found" in result["errors"]
    assert result["contact_id"] == "nope"


def test_get_contact_route(ghl):
    """The route accepts snake_case and GHL-style names and answers with the service result."""
    ghl["reply"] = _reply_contact
    snake = client.post("/api/v1/get-contact", json={"contact_id": "c1", "location_id": "loc1"})
    ghl_style = client.post("/api/v1/get-contact", json={"contactId": "c1", "locationId": "loc1"})
    assert snake.status_code == 200 and snake.json()["success"] is True
    assert (
        snake.json()["custom_fields"]
        == ghl_style.json()["custom_fields"]
        == {"City raw": "Chía", "contact.multi": ["a", "b"]}
    )
    assert snake.json()["errors"] is None


# ----------------------------------------------------------------------------------------------- update_contact


def test_update_contact_sends_given_fields(ghl):
    """Update contact sends only the given fields, with GHL names."""
    ghl["reply"] = lambda r: httpx.Response(200, json={"succeeded": True, "contact": {"id": "c1"}})

    result = asyncio.run(
        update_contact_service(
            " c1 ",
            "loc1",
            {"first_name": " Laura ", "postal_code": "110111", "city": None, "dnd": False, "bogus": "x"},
        )
    )

    assert result == {
        "success": True,
        "contact_id": "c1",
        "updated_fields": ["first_name", "postal_code", "dnd"],
    }
    (request,) = ghl["requests"]
    assert request.method == "PUT" and str(request.url) == "https://ghl.test/contacts/c1"
    assert json.loads(request.content) == {"firstName": "Laura", "postalCode": "110111", "dnd": False}


def test_update_contact_never_sends_tags(ghl):
    """Update contact never sends tags."""
    asyncio.run(update_contact_service("c1", "l", {"first_name": "A"}))
    assert "tags" not in _body(ghl)


def test_update_contact_custom_fields_by_name(ghl, monkeypatch):
    """Custom fields given by name are resolved and their options validated."""
    fields = {
        "city": {
            "id": "fieldcity0000001",
            "dataType": "SINGLE_OPTIONS",
            "picklistOptions": ["Bogotá", "Chía"],
        },
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
        "customFields": [
            {"id": "fieldcity0000001", "fieldValue": "Chía"},
            {"id": "fieldage00000001", "fieldValue": "30"},
        ],
    }

    ghl["requests"].clear()
    bad = asyncio.run(update_contact_service("c1", "loc1", None, {"city": "Medellín"}))
    assert bad["success"] is False and "Allowed: Bogotá, Chía" in bad["errors"]
    missing = asyncio.run(update_contact_service("c1", "loc1", None, {"nope": "x"}))
    assert "Custom field 'nope' not found" in missing["errors"]
    assert ghl["requests"] == []  # nothing is sent when a field cannot be resolved


def test_update_contact_field_id_or_name(ghl):
    """A field id is used as is; a field name needs a location."""
    ghl["reply"] = lambda r: httpx.Response(200, json={"succeeded": True})
    asyncio.run(update_contact_service("c1", None, None, {"uWLesAbC123456789": "x"}))
    assert _body(ghl)["customFields"] == [{"id": "uWLesAbC123456789", "fieldValue": "x"}]
    result = asyncio.run(update_contact_service("c1", None, None, {"city": "x"}))
    assert result["success"] is False and "location_id is required" in result["errors"]


def test_update_contact_noop_skips_ghl(ghl):
    """With nothing to change GHL is not called."""
    assert asyncio.run(update_contact_service("c1", "l", {"city": None}))["errors"] == "Nothing to update"
    assert asyncio.run(update_contact_service("  ", "l", {"city": "x"}))["errors"] == "contact_id is required"
    assert ghl["requests"] == []


def test_update_contact_reports_ghl_errors(ghl):
    """GHL errors such as a duplicate email are returned as data."""
    ghl["reply"] = lambda r: httpx.Response(400, json={"message": "Duplicate email"})
    result = asyncio.run(update_contact_service("c1", "l", {"email": "a@b.co"}))
    assert (
        result["success"] is False
        and "HTTP 400" in result["errors"]
        and "Duplicate email" in result["errors"]
    )
    ghl["reply"] = lambda r: httpx.Response(200, json={"succeeded": False})
    assert asyncio.run(update_contact_service("c1", "l", {"city": "x"}))["success"] is False


def test_update_contact_route_names(ghl):
    """The route accepts snake_case and GHL-style field names."""
    ghl["reply"] = lambda r: httpx.Response(200, json={"succeeded": True})

    snake = client.post(
        "/api/v1/update-contact",
        json={"contact_id": "c1", "location_id": "l", "first_name": "Ana", "city": "Cali"},
    )
    ghl_style = client.post(
        "/api/v1/update-contact", json={"contactId": "c1", "firstName": "Ana", "postalCode": "760001"}
    )

    assert snake.json() == {
        "success": True,
        "contact_id": "c1",
        "updated_fields": ["first_name", "city"],
        "errors": None,
    }
    assert ghl_style.json()["updated_fields"] == ["first_name", "postal_code"]
    assert _body(ghl, 0) == {"firstName": "Ana", "city": "Cali"}


# ------------------------------------------------------------------------------------------- update_opportunity

OPPORTUNITY = {
    "opportunity": {
        "id": "o1",
        "status": "won",
        "pipelineId": "p1",
        "pipelineStageId": "s2",
        "name": "Deal",
        "monetaryValue": 1500.5,
    }
}


def test_update_opportunity_sends_given_fields(ghl):
    """Update opportunity sends only the given fields, with GHL names."""
    ghl["reply"] = lambda r: httpx.Response(200, json=OPPORTUNITY)

    result = asyncio.run(
        update_opportunity_service(
            " o1 ",
            "loc1",
            {
                "status": "WON",
                "monetary_value": "$1,500.50",
                "pipeline_stage_id": "s2",
                "name": None,
                "assigned_to": "  ",
            },
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


def test_update_opportunity_validates_input(ghl):
    """Status and numbers are validated before calling GHL."""
    assert (
        "status must be one of"
        in asyncio.run(update_opportunity_service("o1", "l", {"status": "pending"}))["errors"]
    )
    assert (
        "monetary_value must be 0 or more"
        in asyncio.run(update_opportunity_service("o1", "l", {"monetary_value": -1}))["errors"]
    )
    assert (
        "must be a number"
        in asyncio.run(update_opportunity_service("o1", "l", {"monetary_value": "mucho"}))["errors"]
    )
    assert (
        "must be a number"
        in asyncio.run(update_opportunity_service("o1", "l", {"forecast_probability": True}))["errors"]
    )
    assert asyncio.run(update_opportunity_service("o1", "l", {"name": None}))["errors"] == "Nothing to update"
    assert (
        asyncio.run(update_opportunity_service("", "l", {"name": "x"}))["errors"]
        == "opportunity_id is required"
    )
    assert ghl["requests"] == []


def test_update_opportunity_keeps_integers(ghl):
    """Whole numbers are sent as integers, not floats."""
    ghl["reply"] = lambda r: httpx.Response(200, json=OPPORTUNITY)
    asyncio.run(
        update_opportunity_service("o1", "l", {"monetary_value": 500.0, "forecast_probability": "75"})
    )
    body = _body(ghl)
    assert body == {"monetaryValue": 500, "forecastProbability": 75}


def test_update_opportunity_custom_fields(ghl):
    """Custom fields go by id or by key without the `opportunity.` prefix."""
    ghl["reply"] = lambda r: httpx.Response(200, json=OPPORTUNITY)

    result = asyncio.run(
        update_opportunity_service(
            "o1", "l", None, {"opportunity.source_detail": "web", "uWLesAbC123456789": "x"}
        )
    )

    assert result["updated_fields"] == ["opportunity.source_detail", "uWLesAbC123456789"]
    assert _body(ghl)["customFields"] == [
        {"key": "source_detail", "fieldValue": "web"},
        {"id": "uWLesAbC123456789", "fieldValue": "x"},
    ]


def test_update_opportunity_reports_ghl_errors(ghl):
    """GHL errors are returned as data."""
    ghl["reply"] = lambda r: httpx.Response(400, json={"code": "OPPORTUNITY_NO_DUPLICATE"})
    result = asyncio.run(update_opportunity_service("o1", "l", {"pipeline_id": "p9"}))
    assert result["success"] is False and "OPPORTUNITY_NO_DUPLICATE" in result["errors"]
    assert result["opportunity_id"] == "o1"


def test_update_opportunity_route(ghl):
    """The update-opportunity route answers with the service result."""
    ghl["reply"] = lambda r: httpx.Response(200, json=OPPORTUNITY)

    response = client.post(
        "/api/v1/update-opportunity",
        json={"opportunityId": "o1", "locationId": "l", "status": "won", "monetaryValue": "1500.5"},
    )

    assert response.status_code == 200 and response.json()["success"] is True
    assert response.json()["status"] == "won"
    assert _body(ghl) == {"status": "won", "monetaryValue": 1500.5}


def test_tools_are_builtin_routes():
    """The tools are built-in routes the runtime finds."""
    from agent_backend.tool_client import candidate_urls

    for tool in ("remove_tags", "get_contact", "update_contact", "update_opportunity"):
        assert f"http://x/builtin-tools/{tool.replace('_', '-')}" in candidate_urls(f"http://x/tools/{tool}")
