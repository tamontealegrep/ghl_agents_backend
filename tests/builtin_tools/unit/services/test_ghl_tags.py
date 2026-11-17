"""add_tags: adding tags to a GoHighLevel contact (POST /contacts/{contactId}/tags)."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_backend.builtin_tools.services import ghl_tags
from agent_backend.builtin_tools.services.ghl_tags import add_tags_service, normalize_tags
from tests.builtin_tools.app_factory import app

CONFIG = SimpleNamespace(base_url="https://ghl.test", version="v3", token="tok-123", send_message_timeout_seconds=5)


@pytest.fixture
def ghl(monkeypatch):
    """Points the service at a fake GHL: records the requests and answers with `reply`."""
    state = {"requests": [], "locations": [], "reply": lambda request: httpx.Response(201, json={"tags": ["vip"], "tagsAdded": ["vip"]})}
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["reply"](request)

    def config_for(location_id):
        state["locations"].append(location_id)
        return CONFIG

    monkeypatch.setattr(ghl_tags, "ghl_client_config_for_location", config_for)
    monkeypatch.setattr(ghl_tags.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return state


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["vip", "nuevo"], ["vip", "nuevo"]),
        ([" vip ", "", "  ", "nuevo"], ["vip", "nuevo"]),
        (["VIP", "vip", "Vip "], ["VIP"]),  # repeats ignoring case: GHL stores them in lower case
        ("vip, nuevo ,prospecto", ["vip", "nuevo", "prospecto"]),
        ("vip\nnuevo", ["vip", "nuevo"]),
        ('["vip", "nuevo"]', ["vip", "nuevo"]),  # a JSON list from a slot
        ("['vip', 'nuevo']", ["vip", "nuevo"]),  # a Python list from a slot
        ("solo-una", ["solo-una"]),
        ("[sin cerrar, vip", ["[sin cerrar", "vip"]),  # unreadable list: split on commas
        ("", []),
        ("  ", []),
        ([], []),
        (None, []),
        ([1, "a"], ["1", "a"]),
    ],
)
def test_the_tags_are_cleaned_whatever_their_shape(raw, expected):
    assert normalize_tags(raw) == expected


def test_it_posts_the_tags_to_the_contact_with_the_right_headers(ghl):
    result = asyncio.run(add_tags_service(["vip", " Nuevo "], "contact1", "loc1"))

    assert result == {"success": True, "tags": ["vip"], "tags_added": ["vip"]}
    (request,) = ghl["requests"]
    assert request.method == "POST"
    assert str(request.url) == "https://ghl.test/contacts/contact1/tags"
    assert request.headers["Authorization"] == "Bearer tok-123"
    assert request.headers["Version"] == "v3"
    assert json.loads(request.content) == {"tags": ["vip", "Nuevo"]}
    assert ghl["locations"] == ["loc1"]  # the location picks the token


def test_a_tag_the_contact_already_has_is_reported_as_not_added(ghl):
    ghl["reply"] = lambda r: httpx.Response(201, json={"tags": ["vip", "nuevo"], "tagsAdded": ["nuevo"]})

    result = asyncio.run(add_tags_service("vip,nuevo", "contact1"))

    assert result["tags"] == ["vip", "nuevo"] and result["tags_added"] == ["nuevo"]


def test_nothing_new_means_an_empty_added_list(ghl):
    ghl["reply"] = lambda r: httpx.Response(201, json={"tags": ["vip"], "tagsAdded": []})
    assert asyncio.run(add_tags_service(["vip"], "contact1"))["tags_added"] == []


def test_a_missing_contact_or_empty_tags_never_reach_ghl(ghl):
    assert asyncio.run(add_tags_service(["vip"], "  ")) == {"success": False, "errors": "contact_id is required"}
    assert asyncio.run(add_tags_service([" ", ""], "contact1"))["errors"] == "No tags to add"
    assert asyncio.run(add_tags_service(None, "contact1"))["success"] is False
    assert ghl["requests"] == []


def test_an_error_from_ghl_is_reported_with_its_reason_and_never_raised(ghl):
    ghl["reply"] = lambda r: httpx.Response(401, json={"message": "Invalid token"})

    result = asyncio.run(add_tags_service(["vip"], "contact1", "loc1"))

    assert result["success"] is False
    assert "HTTP 401" in result["errors"] and "Invalid token" in result["errors"]
    assert "tags" not in result


def test_a_long_error_body_is_cut(ghl):
    ghl["reply"] = lambda r: httpx.Response(500, text="x" * 5000)
    assert len(asyncio.run(add_tags_service(["vip"], "c"))["errors"]) < 400


def test_a_network_failure_is_reported(ghl):
    def boom(request):
        raise httpx.ConnectError("connection refused")

    ghl["reply"] = boom
    result = asyncio.run(add_tags_service(["vip"], "c"))
    assert result["success"] is False and "connection refused" in result["errors"]


def test_a_reply_that_is_not_json_is_reported(ghl):
    ghl["reply"] = lambda r: httpx.Response(201, text="<html>")
    result = asyncio.run(add_tags_service(["vip"], "c"))
    assert result["success"] is False and result["errors"]


def test_the_tool_is_served_under_the_kebab_case_route(ghl):
    client = TestClient(app)

    response = client.post(
        "/api/v1/add-tags", json={"tags": ["vip", "nuevo"], "contact_id": "contact1", "location_id": "loc1"}
    )

    assert response.status_code == 200
    assert response.json() == {"success": True, "tags": ["vip"], "tags_added": ["vip"], "errors": None}
    assert json.loads(ghl["requests"][0].content) == {"tags": ["vip", "nuevo"]}


def test_the_route_accepts_ghl_style_names_and_a_string_of_tags(ghl):
    client = TestClient(app)

    response = client.post("/api/v1/add-tags", json={"tags": "vip, nuevo", "contactId": "contact1", "locationId": "loc1"})

    assert response.status_code == 200 and response.json()["success"] is True
    assert str(ghl["requests"][0].url).endswith("/contacts/contact1/tags")


def test_the_route_reports_a_failure_in_the_body_not_as_an_http_error(ghl):
    ghl["reply"] = lambda r: httpx.Response(404, json={"message": "Contact not found"})

    response = TestClient(app).post("/api/v1/add-tags", json={"tags": ["vip"], "contact_id": "nope"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False and "Contact not found" in body["errors"]


def test_the_tool_is_one_of_the_builtin_tools_the_runtime_routes_to():
    from agent_backend.tool_client import candidate_urls

    urls = candidate_urls("http://x/tools/add_tags")
    assert "http://x/builtin-tools/add-tags" in urls
