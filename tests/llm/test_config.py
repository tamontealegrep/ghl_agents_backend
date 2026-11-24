"""LLM provider settings: which providers are used, in which order, with which model."""

import pytest

from agent_backend.llm.config import load_llm_settings, parse_provider_list
from agent_backend.llm.errors import NoProviderConfiguredError

ALL_KEYS = {
    "OPENAI_API_KEY": "o",
    "OPENAI_MODEL": "gpt-x",
    "ANTHROPIC_API_KEY": "a",
    "ANTHROPIC_MODEL": "claude-x",
    "GOOGLE_API_KEY": "g",
    "GOOGLE_MODEL": "gemini-x",
}


def names(settings):
    return [p.name for p in settings.providers]


@pytest.mark.parametrize("value", [None, "", "  ", " , "])
def test_provider_list_is_required(value):
    """The provider list is required and has no default."""
    env = dict(ALL_KEYS) if value is None else {**ALL_KEYS, "LLM_PROVIDERS": value}

    with pytest.raises(NoProviderConfiguredError, match="LLM_PROVIDERS"):
        load_llm_settings(env)


def test_list_sets_priority():
    """The provider list sets the priority order."""
    settings = load_llm_settings({**ALL_KEYS, "LLM_PROVIDERS": "google, anthropic ,openai"})

    assert names(settings) == ["google", "anthropic", "openai"]


def test_unlisted_provider_left_out():
    """A provider not in the list is left out even with a key."""
    settings = load_llm_settings({**ALL_KEYS, "LLM_PROVIDERS": "anthropic"})

    assert names(settings) == ["anthropic"]


def test_provider_without_key_ignored():
    """A listed provider without its key is ignored."""
    settings = load_llm_settings({**ALL_KEYS, "LLM_PROVIDERS": "openai,anthropic", "OPENAI_API_KEY": ""})

    assert names(settings) == ["anthropic"]


def test_provider_without_model_ignored():
    """A listed provider without its model is ignored."""
    settings = load_llm_settings({**ALL_KEYS, "LLM_PROVIDERS": "openai,anthropic", "OPENAI_MODEL": "  "})

    assert names(settings) == ["anthropic"]


def test_there_are_no_default_models():
    """There are no default models."""
    with pytest.raises(NoProviderConfiguredError, match="OPENAI_MODEL"):
        load_llm_settings({"LLM_PROVIDERS": "openai", "OPENAI_API_KEY": "o"})


def test_no_provider_names_missing():
    """With no usable provider the error names what is missing."""
    with pytest.raises(NoProviderConfiguredError) as info:
        load_llm_settings({"LLM_PROVIDERS": "openai,google"})

    message = str(info.value)
    assert "OPENAI_API_KEY" in message and "GOOGLE_MODEL" in message


def test_models_come_from_env():
    """Models are read from the environment exactly as given."""
    settings = load_llm_settings(
        {**ALL_KEYS, "LLM_PROVIDERS": "openai,anthropic,google", "ANTHROPIC_MODEL": " claude-y "}
    )

    assert {p.name: p.model for p in settings.providers} == {
        "openai": "gpt-x",
        "anthropic": "claude-y",
        "google": "gemini-x",
    }


def test_misspelled_provider_is_error():
    """A misspelled provider is an error, not a silent omission."""
    with pytest.raises(ValueError, match="clude"):
        parse_provider_list("openai,clude")


def test_repeated_names_count_once():
    """Repeated provider names count once."""
    assert parse_provider_list("openai,OpenAI, openai") == ["openai"]


def test_timings_defaults_and_validation():
    """Timings have defaults and must be positive numbers."""
    settings = load_llm_settings({**ALL_KEYS, "LLM_PROVIDERS": "openai", "LLM_TIMEOUT_SECONDS": "20"})
    assert settings.timeout_seconds == 20
    assert settings.cooldown_seconds == 300
    with pytest.raises(ValueError, match="LLM_COOLDOWN_SECONDS"):
        load_llm_settings({**ALL_KEYS, "LLM_PROVIDERS": "openai", "LLM_COOLDOWN_SECONDS": "soon"})
    with pytest.raises(ValueError, match="LLM_TIMEOUT_SECONDS"):
        load_llm_settings({**ALL_KEYS, "LLM_PROVIDERS": "openai", "LLM_TIMEOUT_SECONDS": "0"})
