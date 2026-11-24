"""Unit tests for ``agent_backend.tool_client``."""

from agent_backend.tool_client import candidate_urls


def test_agent_routes_before_builtin():
    """Agent routes are tried before built-in routes."""
    urls = candidate_urls("http://h:1/agents/sam/tools/check_visa")
    assert urls == [
        "http://h:1/agents/sam/tools/check-visa",
        "http://h:1/builtin-tools/check-visa",
    ]


def test_configured_suffix_is_tried_first():
    """A configured route suffix is tried first."""
    urls = candidate_urls("http://h:1/agents/fa/tools/book_appointment", ("-ghl",))
    assert urls[:2] == [
        "http://h:1/agents/fa/tools/book-appointment-ghl",
        "http://h:1/agents/fa/tools/book-appointment",
    ]


def test_suffix_already_present_is_not_doubled():
    """A suffix already in the tool name is not added twice."""
    urls = candidate_urls("http://h:1/agents/bn/tools/book_appointment_sur", ("-sur",))
    assert urls[0] == "http://h:1/agents/bn/tools/book-appointment-sur"
    assert len(urls) == len(set(urls))


def test_single_word_tool_has_no_duplicates():
    """A one-word tool name does not produce duplicate URLs."""
    urls = candidate_urls("http://h:1/agents/sam/tools/echo")
    assert len(urls) == len(set(urls)) == 2


def test_builtin_tools_skip_the_route_suffixes():
    """Built-in tools ignore the route suffixes."""
    urls = candidate_urls("http://h:1/agents/bn/tools/calculate_bmi", ("-ghl", "-sur"))
    assert urls == [
        "http://h:1/agents/bn/tools/calculate-bmi",
        "http://h:1/builtin-tools/calculate-bmi",
    ]
