"""LLM provider settings: which providers are used, in which order, with which model."""

import pytest

from agent_backend.llm.config import DEFAULT_MODELS, load_llm_settings, parse_provider_list
from agent_backend.llm.errors import NoProviderConfiguredError

ALL_KEYS = {"OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "a", "GEMINI_API_KEY": "g"}


def names(settings):
    return [p.name for p in settings.providers]


def test_without_a_list_only_openai_is_used_so_existing_deployments_do_not_change():
    settings = load_llm_settings(ALL_KEYS)

    assert names(settings) == ["openai"]


def test_the_list_sets_the_priority_order():
    settings = load_llm_settings({**ALL_KEYS, "LLM_PROVIDERS": "gemini, anthropic ,openai"})

    assert names(settings) == ["gemini", "anthropic", "openai"]


def test_a_provider_that_is_not_listed_is_left_out_even_with_a_key():
    settings = load_llm_settings({**ALL_KEYS, "LLM_PROVIDERS": "anthropic"})

    assert names(settings) == ["anthropic"]


def test_a_listed_provider_without_a_key_is_skipped():
    settings = load_llm_settings({"LLM_PROVIDERS": "openai,anthropic", "ANTHROPIC_API_KEY": "a"})

    assert names(settings) == ["anthropic"]


def test_no_usable_provider_fails_with_a_clear_message():
    with pytest.raises(NoProviderConfiguredError, match="OPENAI_API_KEY"):
        load_llm_settings({"LLM_PROVIDERS": "openai"})


def test_models_come_from_the_environment_or_the_defaults():
    settings = load_llm_settings(
        {**ALL_KEYS, "LLM_PROVIDERS": "openai,anthropic,gemini", "ANTHROPIC_MODEL": " claude-x "}
    )
    models = {p.name: p.model for p in settings.providers}

    assert models["anthropic"] == "claude-x"
    assert models["openai"] == DEFAULT_MODELS["openai"]
    assert models["gemini"] == DEFAULT_MODELS["gemini"]


def test_gemini_accepts_the_google_api_key_name():
    settings = load_llm_settings({"LLM_PROVIDERS": "gemini", "GOOGLE_API_KEY": "g"})

    assert settings.providers[0].api_key == "g"


def test_a_misspelled_provider_is_an_error_not_a_silent_omission():
    with pytest.raises(ValueError, match="clude"):
        parse_provider_list("openai,clude")


def test_repeated_names_count_once():
    assert parse_provider_list("openai,OpenAI, openai") == ["openai"]


def test_timings_have_defaults_and_must_be_positive_numbers():
    settings = load_llm_settings({"OPENAI_API_KEY": "o", "LLM_TIMEOUT_SECONDS": "20"})
    assert settings.timeout_seconds == 20
    assert settings.cooldown_seconds == 300
    with pytest.raises(ValueError, match="LLM_COOLDOWN_SECONDS"):
        load_llm_settings({"OPENAI_API_KEY": "o", "LLM_COOLDOWN_SECONDS": "soon"})
    with pytest.raises(ValueError, match="LLM_TIMEOUT_SECONDS"):
        load_llm_settings({"OPENAI_API_KEY": "o", "LLM_TIMEOUT_SECONDS": "0"})
