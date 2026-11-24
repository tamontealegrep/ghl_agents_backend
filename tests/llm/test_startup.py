"""The server refuses to start when no LLM provider is usable."""

import pytest

from agent_backend import __main__ as entry


def test_no_start_without_provider(monkeypatch):
    """The server does not start without a usable provider."""
    for name in ("LLM_PROVIDERS", "OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: pytest.fail("the server must not start"))

    with pytest.raises(SystemExit, match="Cannot start"):
        entry.main()


def test_starts_with_one_provider(monkeypatch):
    """The server starts with one valid provider."""
    monkeypatch.setenv("LLM_PROVIDERS", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    started = []
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: started.append(True))

    entry.main()

    assert started == [True]
