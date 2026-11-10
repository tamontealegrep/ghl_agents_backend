import pytest

from agent_backend.booking_helpers import format_contact_name, parse_duration_minutes, parse_start_date
from agent_backend.email_templates import render_template_file
from agent_backend.team_notification import join_errors


def test_template_variables_are_substituted_and_a_missing_one_fails(tmp_path):
    (tmp_path / "hello.html").write_text("<p>Hi ${name}</p>", encoding="utf-8")
    assert render_template_file(tmp_path, "hello", name="Ana") == "<p>Hi Ana</p>"
    with pytest.raises(KeyError):
        render_template_file(tmp_path, "hello")
    with pytest.raises(FileNotFoundError):
        render_template_file(tmp_path, "nope", name="x")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 20), ("", 20), ("abc", 20), ("0", 20), ("-5", 20), ("30", 30), ("45 min", 45)],
)
def test_duration_falls_back_to_the_given_default(raw, expected):
    assert parse_duration_minutes(raw, 20) == expected


def test_start_date_without_offset_uses_the_default_timezone():
    assert parse_start_date("2027-03-03T09:00:00").utcoffset().total_seconds() == -5 * 3600
    assert parse_start_date("2027-03-03T09:00:00", "UTC").utcoffset().total_seconds() == 0
    assert parse_start_date("2027-03-03T09:00:00Z").utcoffset().total_seconds() == 0
    with pytest.raises(ValueError):
        parse_start_date("not a date")


def test_contact_names_are_tidied_and_errors_joined():
    assert format_contact_name("  ana   GOMEZ ") == "Ana Gomez"
    assert join_errors(None, "", "a", "b") == "a; b" and join_errors(None, "") is None
