"""
Unit tests for agent_runtime.runtime.tool_executor — the generic endpoint-calling executor.

    Uses `httpx.MockTransport` (part of httpx itself) to stub the tool
    endpoint — no real network call, no external mocking dependency.
"""

from __future__ import annotations

import json

import httpx
import pytest

from agent_runtime.dsl.schemas import ToolContract
from agent_runtime.runtime.tool_executor import ToolExecutionError, make_tool_executor


def _contract(**overrides) -> ToolContract:
    data = {
        "name": "book_appointment",
        "description": "Books an appointment.",
        "inputs": [
            {"name": "slot_start", "required": True, "description": "Start time."},
            {"name": "notes", "required": False, "description": "Optional notes."},
        ],
        "outputs": [
            {"name": "event_id", "description": "The created event id."},
            {"name": "success", "description": "Whether the booking succeeded."},
        ],
    }
    data.update(overrides)
    return ToolContract.model_validate(data)


def _client_returning(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_posts_to_base_url_plus_tool_name():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"event_id": "evt_1", "success": True})

    executor = make_tool_executor(_contract(), "https://tools.example.com", client=_client_returning(handler))
    executor(slot_start="2026-01-01T10:00:00Z")
    assert seen["url"] == "https://tools.example.com/book_appointment"


def test_sends_declared_inputs_as_json_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    executor = make_tool_executor(_contract(), "https://tools.example.com", client=_client_returning(handler))
    executor(slot_start="2026-01-01T10:00:00Z", notes="VIP client")
    assert seen["body"] == {"slot_start": "2026-01-01T10:00:00Z", "notes": "VIP client"}


def test_maps_response_onto_declared_outputs():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"event_id": "evt_1", "success": True, "extra_field": "ignored"})

    executor = make_tool_executor(_contract(), "https://tools.example.com", client=_client_returning(handler))
    result = executor(slot_start="2026-01-01T10:00:00Z")
    assert result == {"event_id": "evt_1", "success": True}


def test_missing_output_in_response_is_simply_omitted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"event_id": "evt_1"})

    executor = make_tool_executor(_contract(), "https://tools.example.com", client=_client_returning(handler))
    result = executor(slot_start="2026-01-01T10:00:00Z")
    assert result == {"event_id": "evt_1"}
    assert "success" not in result


def test_unknown_input_raises_value_error():
    executor = make_tool_executor(_contract(), "https://tools.example.com")
    with pytest.raises(ValueError, match="Unknown input"):
        executor(slot_start="x", made_up_field="y")


def test_missing_required_input_raises_value_error():
    executor = make_tool_executor(_contract(), "https://tools.example.com")
    with pytest.raises(ValueError, match="Missing required input"):
        executor(notes="only optional given")


def test_optional_input_can_be_omitted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    executor = make_tool_executor(_contract(), "https://tools.example.com", client=_client_returning(handler))
    executor(slot_start="2026-01-01T10:00:00Z")  # no ValueError


def test_http_error_status_raises_tool_execution_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    executor = make_tool_executor(_contract(), "https://tools.example.com", client=_client_returning(handler))
    with pytest.raises(ToolExecutionError, match="HTTP 500"):
        executor(slot_start="x")


def test_non_json_response_raises_tool_execution_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    executor = make_tool_executor(_contract(), "https://tools.example.com", client=_client_returning(handler))
    with pytest.raises(ToolExecutionError, match="non-JSON"):
        executor(slot_start="x")


def test_base_url_trailing_slash_is_normalized():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={})

    executor = make_tool_executor(
        _contract(), "https://tools.example.com/", client=_client_returning(handler)
    )
    executor(slot_start="x")
    assert seen["url"] == "https://tools.example.com/book_appointment"


def test_no_tool_specific_code_path_every_tool_goes_through_the_same_shape():
    """
    Two different contracts produce executors with identical call mechanics —

        the point of DESIGN_PATTERNS.md P05: no per-tool hand-written function.

        Returns:
            None.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    contract_a = _contract(name="tool_a", inputs=[], outputs=[{"name": "ok", "description": "d"}])
    contract_b = _contract(name="tool_b", inputs=[], outputs=[{"name": "ok", "description": "d"}])
    client = _client_returning(handler)

    executor_a = make_tool_executor(contract_a, "https://tools.example.com", client=client)
    executor_b = make_tool_executor(contract_b, "https://tools.example.com", client=client)
    assert executor_a() == {"ok": True}
    assert executor_b() == {"ok": True}
