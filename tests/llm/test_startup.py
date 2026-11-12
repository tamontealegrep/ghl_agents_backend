"""The server refuses to start when no LLM provider is usable."""

import pytest

from agent_backend import __main__ as entry


def test_the_server_does_not_start_without_a_usable_provider(monkeypatch):
    for name in ("LLM_PROVIDERS", "OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: pytest.fail("the server must not start"))

    with pytest.raises(SystemExit, match="Cannot start"):
        entry.main()


def test_the_server_starts_with_one_valid_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "m")
    started = []
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: started.append(True))

    entry.main()

    assert started == [True]
