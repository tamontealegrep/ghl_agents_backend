"""How an SDK exception is sorted into a failure kind."""

import pytest

from agent_backend.llm.errors import ErrorKind, LLMProviderError, classify_exception


class FakeApiError(Exception):
    def __init__(self, message="boom", status_code=None, code=None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class RateLimitError(FakeApiError):
    pass


class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (FakeApiError(status_code=401), ErrorKind.AUTH),
        (FakeApiError(status_code=403), ErrorKind.AUTH),
        (FakeApiError("API key not valid. Please pass a valid API key.", code=400), ErrorKind.AUTH),
        (FakeApiError(status_code=402), ErrorKind.QUOTA),
        (FakeApiError("You exceeded your current quota, check billing", status_code=429), ErrorKind.QUOTA),
        (FakeApiError("Your credit balance is too low", status_code=400), ErrorKind.QUOTA),
        (FakeApiError("RESOURCE_EXHAUSTED", code=429), ErrorKind.QUOTA),
        (FakeApiError("slow down", status_code=429), ErrorKind.RATE_LIMIT),
        (RateLimitError("slow down"), ErrorKind.RATE_LIMIT),
        (FakeApiError(status_code=503), ErrorKind.UNAVAILABLE),
        (FakeApiError(code=500), ErrorKind.UNAVAILABLE),
        (APIConnectionError("dns"), ErrorKind.UNAVAILABLE),
        (APITimeoutError("Request timed out."), ErrorKind.TIMEOUT),
        (FakeApiError(status_code=400), ErrorKind.BAD_REQUEST),
        (ValueError("odd"), ErrorKind.UNKNOWN),
    ],
)
def test_kinds(exc, kind):
    assert classify_exception("openai", exc).kind is kind


def test_the_provider_name_and_message_are_kept():
    error = classify_exception("google", FakeApiError("nope", status_code=401))

    assert error.provider == "google"
    assert "nope" in str(error)


def test_an_already_classified_error_is_returned_as_is():
    original = LLMProviderError("openai", ErrorKind.QUOTA, "x")

    assert classify_exception("anthropic", original) is original
