"""add_tags: adding tags to a GoHighLevel contact (POST /contacts/{contactId}/tags)."""

import asyncio
import json
import httpx
import pytest
from fastapi.testclient import TestClient

from agent_backend.builtin_tools.services.ghl_tags import add_tags_service, normalize_tags
from tests.builtin_tools.app_factory import app


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
def test_tags_are_normalised(raw, expected):
    """Tags are cleaned whether they come as a list or a string."""
    assert normalize_tags(raw) == expected


def test_add_tags_posts_with_headers(ghl):
    """Tags are posted to the contact with the right headers."""
    result = asyncio.run(add_tags_service(["vip", " Nuevo "], "contact1", "loc1"))

    assert result == {"success": True, "tags": ["vip"], "tags_added": ["vip"]}
    (request,) = ghl["requests"]
    assert request.method == "POST"
    assert str(request.url) == "https://ghl.test/contacts/contact1/tags"
    assert request.headers["Authorization"] == "Bearer tok-123"
    assert request.headers["Version"] == "v3"
    assert json.loads(request.content) == {"tags": ["vip", "Nuevo"]}
    assert ghl["locations"] == ["loc1"]  # the location picks the token


def test_existing_tag_not_reported_added(ghl):
    """A tag the contact already has is not reported as added."""
    ghl["reply"] = lambda r: httpx.Response(201, json={"tags": ["vip", "nuevo"], "tagsAdded": ["nuevo"]})

    result = asyncio.run(add_tags_service("vip,nuevo", "contact1"))

    assert result["tags"] == ["vip", "nuevo"] and result["tags_added"] == ["nuevo"]


def test_nothing_new_means_an_empty_added_list(ghl):
    """Adding only existing tags gives an empty added list."""
    ghl["reply"] = lambda r: httpx.Response(201, json={"tags": ["vip"], "tagsAdded": []})
    assert asyncio.run(add_tags_service(["vip"], "contact1"))["tags_added"] == []


def test_missing_input_skips_ghl(ghl):
    """A missing contact or empty tags never reach GHL."""
    assert asyncio.run(add_tags_service(["vip"], "  ")) == {
        "success": False,
        "errors": "contact_id is required",
    }
    assert asyncio.run(add_tags_service([" ", ""], "contact1"))["errors"] == "No tags"
    assert asyncio.run(add_tags_service(None, "contact1"))["success"] is False
    assert ghl["requests"] == []


def test_ghl_error_is_reported(ghl):
    """A GHL error is returned with its reason and never raised."""
    ghl["reply"] = lambda r: httpx.Response(401, json={"message": "Invalid token"})

    result = asyncio.run(add_tags_service(["vip"], "contact1", "loc1"))

    assert result["success"] is False
    assert "HTTP 401" in result["errors"] and "Invalid token" in result["errors"]
    assert "tags" not in result


def test_a_long_error_body_is_cut(ghl):
    """A long error body is cut to a short length."""
    ghl["reply"] = lambda r: httpx.Response(500, text="x" * 5000)
    assert len(asyncio.run(add_tags_service(["vip"], "c"))["errors"]) < 400


def test_a_network_failure_is_reported(ghl):
    """A network failure is returned as data."""

    def boom(request):
        raise httpx.ConnectError("connection refused")

    ghl["reply"] = boom
    result = asyncio.run(add_tags_service(["vip"], "c"))
    assert result["success"] is False and "connection refused" in result["errors"]


def test_non_json_reply_is_reported(ghl):
    """A reply that is not JSON is returned as an error."""
    ghl["reply"] = lambda r: httpx.Response(201, text="<html>")
    result = asyncio.run(add_tags_service(["vip"], "c"))
    assert result["success"] is False and result["errors"]


def test_served_under_kebab_route(ghl):
    """The tool is served under the kebab-case route."""
    client = TestClient(app)

    response = client.post(
        "/api/v1/add-tags", json={"tags": ["vip", "nuevo"], "contact_id": "contact1", "location_id": "loc1"}
    )

    assert response.status_code == 200
    assert response.json() == {"success": True, "tags": ["vip"], "tags_added": ["vip"], "errors": None}
    assert json.loads(ghl["requests"][0].content) == {"tags": ["vip", "nuevo"]}


def test_route_accepts_ghl_names(ghl):
    """The route accepts GHL-style names and a string of tags."""
    client = TestClient(app)

    response = client.post(
        "/api/v1/add-tags", json={"tags": "vip, nuevo", "contactId": "contact1", "locationId": "loc1"}
    )

    assert response.status_code == 200 and response.json()["success"] is True
    assert str(ghl["requests"][0].url).endswith("/contacts/contact1/tags")


def test_route_failure_is_in_body(ghl):
    """A failure is reported in the body, not as an HTTP error."""
    ghl["reply"] = lambda r: httpx.Response(404, json={"message": "Contact not found"})

    response = TestClient(app).post("/api/v1/add-tags", json={"tags": ["vip"], "contact_id": "nope"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False and "Contact not found" in body["errors"]


def test_tool_is_builtin_route():
    """The tool is one of the built-in routes the runtime tries."""
    from agent_backend.tool_client import candidate_urls

    urls = candidate_urls("http://x/tools/add_tags")
    assert "http://x/builtin-tools/add-tags" in urls
