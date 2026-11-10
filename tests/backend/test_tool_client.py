"""Unit tests for ``agent_backend.tool_client``."""

from agent_backend.tool_client import candidate_urls


def test_candidates_try_agent_routes_before_builtin():
    urls = candidate_urls("http://h:1/agents/sam/tools/check_visa")
    assert urls == [
        "http://h:1/agents/sam/tools/check-visa",
        "http://h:1/builtin-tools/check-visa",
    ]


def test_configured_suffix_is_tried_first():
    urls = candidate_urls("http://h:1/agents/fa/tools/book_appointment", ("-ghl",))
    assert urls[:2] == ["http://h:1/agents/fa/tools/book-appointment-ghl", "http://h:1/agents/fa/tools/book-appointment"]


def test_suffix_already_present_is_not_doubled():
    urls = candidate_urls("http://h:1/agents/bn/tools/book_appointment_sur", ("-sur",))
    assert urls[0] == "http://h:1/agents/bn/tools/book-appointment-sur"
    assert len(urls) == len(set(urls))


def test_single_word_tool_has_no_duplicates():
    urls = candidate_urls("http://h:1/agents/sam/tools/echo")
    assert len(urls) == len(set(urls)) == 2


def test_builtin_tools_skip_the_route_suffixes():
    urls = candidate_urls("http://h:1/agents/bn/tools/calculate_bmi", ("-ghl", "-sur"))
    assert urls == [
        "http://h:1/agents/bn/tools/calculate-bmi",
        "http://h:1/builtin-tools/calculate-bmi",
    ]
