"""The failover client: priority order, hand-over on failure, rest periods and the last resort."""

import pytest

from agent_backend.llm.errors import AllProvidersFailedError, ErrorKind, LLMProviderError
from agent_backend.llm.failover import FailoverLLMClient
from agent_backend.llm.providers.base import Provider


class Scripted(Provider):
    """Answers or fails as told; counts its calls."""

    def __init__(self, name, *, fail=None):
        super().__init__(f"{name}-model")
        self.name = name
        self.fail = fail
        self.calls = 0

    def _complete(self, prompt, temperature):
        self.calls += 1
        if self.fail:
            raise self.fail(self.name)
        return f"{self.name}:{prompt}"

    def _extract(self, prompt, json_schema):
        self.calls += 1
        if self.fail:
            raise self.fail(self.name)
        return {"from": self.name}


def quota(name):
    return LLMProviderError(name, ErrorKind.QUOTA, "no credits")


def outage(name):
    return LLMProviderError(name, ErrorKind.UNAVAILABLE, "down")


def refused(name):
    return LLMProviderError(name, ErrorKind.BAD_REQUEST, "bad")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def client(*providers, clock=None):
    return FailoverLLMClient(
        providers, cooldown_seconds=300, transient_cooldown_seconds=30, clock=clock or Clock()
    )


def test_first_provider_answers():
    """The first provider answers when it works."""
    a, b = Scripted("a"), Scripted("b")

    assert client(a, b).complete("hi") == "a:hi"
    assert b.calls == 0


def test_failure_goes_to_next_provider():
    """A failure hands the same call to the next provider."""
    a, b = Scripted("a", fail=quota), Scripted("b")
    llm = client(a, b)

    assert llm.complete("hi") == "b:hi"
    assert llm.extract_structured("hi", {}) == {"from": "b"}
    assert llm.last_provider == "b"


def test_no_credits_provider_rests():
    """A provider without credits rests, so the next calls skip it."""
    a, b = Scripted("a", fail=quota), Scripted("b")
    llm = client(a, b)

    llm.complete("1")
    llm.complete("2")
    llm.complete("3")

    assert a.calls == 1  # not asked again while it rests
    assert b.calls == 3


def test_preferred_provider_returns_after_rest():
    """The preferred provider is tried again after its rest."""
    clock = Clock()
    a, b = Scripted("a", fail=quota), Scripted("b")
    llm = client(a, b, clock=clock)
    llm.complete("1")

    a.fail = None  # credits topped up
    clock.now += 299
    assert llm.complete("2") == "b:2"
    clock.now += 2
    assert llm.complete("3") == "a:3"
    assert llm.last_provider == "a"


def test_outage_rest_is_short():
    """An outage rests the provider only for a short time."""
    clock = Clock()
    a, b = Scripted("a", fail=outage), Scripted("b")
    llm = client(a, b, clock=clock)
    llm.complete("1")

    a.fail = None
    clock.now += 31

    assert llm.complete("2") == "a:2"


def test_refused_request_does_not_rest():
    """A refused request moves on without resting the provider."""
    a, b = Scripted("a", fail=refused), Scripted("b")
    llm = client(a, b)

    assert llm.complete("1") == "b:1"
    assert llm.complete("2") == "b:2"
    assert a.calls == 2  # asked every time


def test_all_fail_lists_each_provider():
    """When every provider fails the error lists each one."""
    llm = client(Scripted("a", fail=quota), Scripted("b", fail=outage))

    with pytest.raises(AllProvidersFailedError) as info:
        llm.complete("hi")

    assert [e.provider for e in info.value.attempts] == ["a", "b"]
    assert "a (quota)" in str(info.value) and "b (unavailable)" in str(info.value)


def test_resting_tried_as_last_resort():
    """Resting providers are still tried as a last resort."""
    a, b = Scripted("a", fail=quota), Scripted("b", fail=outage)
    llm = client(a, b)
    with pytest.raises(AllProvidersFailedError):
        llm.complete("1")

    a.fail = None  # a recovers while still resting

    assert llm.complete("2") == "a:2"


def test_status_shows_rest_time():
    """Status shows how long each provider still rests."""
    llm = client(Scripted("a", fail=quota), Scripted("b"))
    llm.complete("hi")

    status = {row["provider"]: row for row in llm.status()}

    assert status["a"]["resting_seconds"] == 300
    assert status["b"]["resting_seconds"] == 0
    assert llm.provider_names == ["a", "b"]


def test_model_of_last_answering_provider():
    """The model reported is the one of the provider that answered last."""
    llm = client(Scripted("a", fail=quota), Scripted("b"))
    assert llm.model == "a-model"

    llm.complete("hi")

    assert llm.model == "b-model"


def test_needs_one_provider():
    """At least one provider is required."""
    with pytest.raises(ValueError):
        FailoverLLMClient([], cooldown_seconds=1)
