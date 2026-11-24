"""
Unit tests for how OpenAILLMClient picks its model.
"""

from __future__ import annotations

import sys
import types

import pytest

from agent_runtime.runtime.llm_client import (
    DEFAULT_OPENAI_MODEL,
    LARGE_SLOT_CHARS,
    LLMContext,
    OpenAILLMClient,
)


@pytest.fixture(autouse=True)
def fake_openai(monkeypatch):
    module = types.ModuleType("openai")
    module.OpenAI = lambda api_key=None: object()
    monkeypatch.setitem(sys.modules, "openai", module)


def test_model_default(monkeypatch):
    """The model defaults when the variable is missing."""
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert OpenAILLMClient(api_key="k")._model == DEFAULT_OPENAI_MODEL


def test_model_from_env(monkeypatch):
    """The model comes from the environment."""
    monkeypatch.setenv("OPENAI_MODEL", " gpt-4.1-mini ")
    assert OpenAILLMClient(api_key="k")._model == "gpt-4.1-mini"


def test_blank_model_uses_default(monkeypatch):
    """A blank variable falls back to the default model."""
    monkeypatch.setenv("OPENAI_MODEL", "  ")
    assert OpenAILLMClient(api_key="k")._model == DEFAULT_OPENAI_MODEL


def test_explicit_model_wins(monkeypatch):
    """An explicit model wins over the environment."""
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    assert OpenAILLMClient(api_key="k", model="gpt-4o")._model == "gpt-4o"


def _ctx(slots, goal=None, do=None):
    return LLMContext(slots=slots, history=[], last_user_message="hi", goal=goal or [], do=do or [])


def _big_list():
    return [
        {"start_local": f"2026-11-04T09:{i:02d}:00", "start_co": f"2026-11-04T09:{i:02d}:00-05:00"}
        for i in range(60)
    ]


def test_block_omits_unmentioned_large_slot():
    """A large slot the prompt does not name is left out."""
    assert len(str(_big_list())) > LARGE_SLOT_CHARS
    block = _ctx({"day": "x", "sc__available_slots": _big_list()}).block()
    assert "2026-11-04T09:30" not in block
    assert "sc__available_slots" in block and "60 items" in block
    assert '"day": "x"' in block


def test_block_keeps_mentioned_large_slot():
    """A large slot named in the mentions is kept."""
    block = _ctx({"sc__available_slots": _big_list()}).block(
        "IF [sc__available_slots] has a match -> GO_TO: X"
    )
    assert "2026-11-04T09:30:00" in block


def test_block_keeps_goal_named_large_slot():
    """A large slot named in the goal or do lines is kept."""
    assert (
        "2026-11-04T09:30:00"
        in _ctx({"sc__available_slots": _big_list()}, goal=["use [sc__available_slots]"]).block()
    )
    assert (
        "2026-11-04T09:30:00"
        in _ctx({"sc__available_slots": _big_list()}, do=["read sc__available_slots"]).block()
    )


def test_block_keeps_small_slots_whole():
    """Small slots are kept whole."""
    assert '"city": "Bogota"' in _ctx({"city": "Bogota", "tags": ["a", "b"]}).block()


def _slot_objects():
    return [
        {
            "start_co": f"2026-11-04T09:{i:02d}:00-05:00",
            "end_co": f"2026-11-04T09:{i:02d}:30-05:00",
            "start_local": f"2026-11-04T09:{i:02d}:00-05:00",
            "end_local": f"2026-11-04T09:{i:02d}:30-05:00",
        }
        for i in range(30)
    ]


def test_block_hides_end_times():
    """A slot list hides end times unless the prompt names them."""
    ctx = _ctx({"sc__available_slots": _slot_objects()}, goal=["use [sc__available_slots]"])
    block = ctx.block()
    assert "start_co" in block and "start_local" in block
    assert "end_co" not in block and "end_local" not in block
    assert "end_co" in ctx.block("the object has start_co and end_co")


def test_block_keeps_other_lists_whole():
    """Other lists are kept whole."""
    block = _ctx({"tags": [{"start_co": "a", "end_co": "b"}], "name": "x"}).block()
    assert "end_co" in block
