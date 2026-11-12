"""The three provider adapters, against fake SDKs: what they send and how they read the answer."""

import sys
import types
from types import SimpleNamespace as NS

import pytest

from agent_backend.llm.errors import ErrorKind, LLMProviderError
from agent_backend.llm.factory import build_llm_client
from agent_backend.llm.providers import AnthropicProvider, GeminiProvider, OpenAIProvider

SCHEMA = {"type": "object", "properties": {"name": {"type": ["string", "null"]}}, "required": ["name"]}


class HttpError(Exception):
    status_code = 429


def fake_module(monkeypatch, name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


# ------------------------------------------------------------------------------------------------ openai
def install_openai(monkeypatch, content='{"name": "Ana"}', error=None):
    seen = []

    def create(**kwargs):
        seen.append(kwargs)
        if error:
            raise error
        return NS(choices=[NS(message=NS(content=content))])

    class OpenAI:
        def __init__(self, **kwargs):
            seen.append(("init", kwargs))
            self.chat = NS(completions=NS(create=create))

    fake_module(monkeypatch, "openai", OpenAI=OpenAI)
    return seen


def test_openai_complete_and_structured(monkeypatch):
    seen = install_openai(monkeypatch)
    provider = OpenAIProvider("k", "gpt-x", 20)

    assert provider.complete(" hola ") == '{"name": "Ana"}'
    assert provider.extract_structured("p", SCHEMA) == {"name": "Ana"}
    assert seen[0] == ("init", {"api_key": "k", "timeout": 20, "max_retries": 1})
    assert seen[2]["response_format"]["json_schema"]["strict"] is True
    assert seen[2]["model"] == "gpt-x"


def test_openai_malformed_json_is_an_empty_extraction(monkeypatch):
    install_openai(monkeypatch, content="not json")

    assert OpenAIProvider("k", "m", 5).extract_structured("p", SCHEMA) == {}


def test_sdk_errors_become_provider_errors(monkeypatch):
    install_openai(monkeypatch, error=HttpError("slow down"))

    with pytest.raises(LLMProviderError) as info:
        OpenAIProvider("k", "m", 5).complete("p")

    assert info.value.provider == "openai" and info.value.kind is ErrorKind.RATE_LIMIT


# ---------------------------------------------------------------------------------------------- anthropic
def install_anthropic(monkeypatch, content):
    seen = []

    def create(**kwargs):
        seen.append(kwargs)
        return NS(content=content)

    class Anthropic:
        def __init__(self, **kwargs):
            seen.append(("init", kwargs))
            self.messages = NS(create=create)

    fake_module(monkeypatch, "anthropic", Anthropic=Anthropic)
    return seen


def test_anthropic_complete_joins_the_text_blocks(monkeypatch):
    seen = install_anthropic(monkeypatch, [NS(type="text", text="Hola "), NS(type="text", text="mundo")])

    assert AnthropicProvider("k", "claude-x", 20).complete("p", temperature=0.3) == "Hola mundo"
    assert seen[1]["temperature"] == 0.3 and seen[1]["max_tokens"] > 0


def test_anthropic_structured_output_is_a_forced_tool_call(monkeypatch):
    seen = install_anthropic(
        monkeypatch, [NS(type="text", text="thinking"), NS(type="tool_use", input={"name": "Ana"})]
    )

    assert AnthropicProvider("k", "claude-x", 20).extract_structured("p", SCHEMA) == {"name": "Ana"}
    call = seen[1]
    assert call["tools"][0]["input_schema"] == SCHEMA
    assert call["tool_choice"] == {"type": "tool", "name": call["tools"][0]["name"]}


def test_anthropic_without_a_tool_call_is_an_empty_extraction(monkeypatch):
    install_anthropic(monkeypatch, [NS(type="text", text="no")])

    assert AnthropicProvider("k", "m", 5).extract_structured("p", SCHEMA) == {}


# -------------------------------------------------------------------------------------------------- gemini
def install_gemini(monkeypatch, text='{"name": "Ana"}'):
    seen = []

    class Config:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def generate_content(**kwargs):
        seen.append(kwargs)
        return NS(text=text)

    class Client:
        def __init__(self, **kwargs):
            seen.append(("init", kwargs))
            self.models = NS(generate_content=generate_content)

    types_module = types.ModuleType("google.genai.types")
    types_module.GenerateContentConfig = Config
    types_module.HttpOptions = lambda timeout: NS(timeout=timeout)
    genai = types.ModuleType("google.genai")
    genai.Client = Client
    genai.types = types_module
    google = types.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_module)
    return seen


def test_gemini_complete_and_structured(monkeypatch):
    seen = install_gemini(monkeypatch)
    provider = GeminiProvider("k", "gemini-x", 20)

    assert provider.complete("p") == '{"name": "Ana"}'
    assert provider.extract_structured("p", SCHEMA) == {"name": "Ana"}
    assert seen[0][1]["http_options"].timeout == 20000
    config = seen[2]["config"].kwargs
    assert config["response_mime_type"] == "application/json" and config["response_json_schema"] == SCHEMA


# ------------------------------------------------------------------------------------------------ factory
def test_the_factory_builds_the_listed_providers_in_order(monkeypatch):
    install_openai(monkeypatch)
    install_anthropic(monkeypatch, [])
    install_gemini(monkeypatch)
    env = {
        "LLM_PROVIDERS": "gemini,openai,anthropic",
        "OPENAI_API_KEY": "o",
        "ANTHROPIC_API_KEY": "a",
        "GEMINI_API_KEY": "g",
        "OPENAI_MODEL": "gpt-x",
    }

    llm = build_llm_client(env)

    assert llm.provider_names == ["gemini", "openai", "anthropic"]
    assert {row["provider"]: row["model"] for row in llm.status()}["openai"] == "gpt-x"
