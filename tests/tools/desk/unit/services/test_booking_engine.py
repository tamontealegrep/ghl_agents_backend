from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from desk.services import booking_engine as engine

# ---------------------------------------------------------------------------
# parse_start_date
# ---------------------------------------------------------------------------


def test_start_date_keeps_offset():
    """A start date with an offset keeps it."""
    dt = engine.parse_start_date("2026-08-28T09:00:00-05:00")
    assert dt.utcoffset() == timedelta(hours=-5)
    assert dt.hour == 9


def test_start_date_defaults_to_bogota():
    """A start date without an offset is read as Bogota time."""
    dt = engine.parse_start_date("2026-08-28T09:00:00")
    assert dt.utcoffset() == timedelta(hours=-5)


def test_start_date_invalid_raises():
    """An invalid start date raises ValueError."""
    with pytest.raises(ValueError):
        engine.parse_start_date("no es una fecha")


# ---------------------------------------------------------------------------
# parse_duration_minutes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [("20", 20), ("45", 45), ("20abc", 20), ("  30  ", 30)])
def test_duration_valid(raw, expected):
    """Valid durations are parsed."""
    assert engine.parse_duration_minutes(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", "0", "-5"])
def test_duration_falls_back(raw):
    """Invalid durations fall back to 20 minutes."""
    assert engine.parse_duration_minutes(raw) == 20


def test_duration_custom_default():
    """A custom default is used for invalid durations."""
    assert engine.parse_duration_minutes("abc", default=30) == 30


# ---------------------------------------------------------------------------
# compute_end_date / is_future
# ---------------------------------------------------------------------------


def test_end_date_adds_duration():
    """The end date is the start plus the duration."""
    start = datetime(2026, 8, 28, 9, 0, tzinfo=ZoneInfo("America/Bogota"))
    end = engine.compute_end_date(start, 20)
    assert end == start + timedelta(minutes=20)


def test_is_future_true_for_later_date():
    """A later date is in the future."""
    now = datetime(2026, 8, 20, 0, 0, tzinfo=ZoneInfo("UTC"))
    start = datetime(2026, 8, 28, 9, 0, tzinfo=ZoneInfo("America/Bogota"))
    assert engine.is_future(start, now) is True


def test_is_future_false_for_past_date():
    """An earlier date is not in the future."""
    now = datetime(2026, 8, 28, 0, 0, tzinfo=ZoneInfo("UTC"))
    start = datetime(2026, 8, 20, 9, 0, tzinfo=ZoneInfo("America/Bogota"))
    assert engine.is_future(start, now) is False


# ---------------------------------------------------------------------------
# format_contact_name
# ---------------------------------------------------------------------------


def test_contact_name_tidied():
    """Contact names are trimmed, collapsed and title-cased."""
    assert engine.format_contact_name("  maria   PEREZ gomez  ") == "Maria Perez Gomez"


def test_contact_name_single_word():
    """A one-word name is title-cased."""
    assert engine.format_contact_name("ana") == "Ana"


# ---------------------------------------------------------------------------
# email
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("email", ["Maria@Correo.com", "  ana.perez@dominio.co  "])
def test_email_valid(email):
    """Well-formed email addresses are accepted."""
    assert engine.is_valid_email(email) is True


@pytest.mark.parametrize("email", ["no-es-un-correo", "ana@", "ana@dominio", "ana@example.com"])
def test_email_invalid(email):
    """Malformed or example-domain emails are rejected."""
    assert engine.is_valid_email(email) is False


def test_email_normalised():
    """Emails are trimmed and lowercased."""
    assert engine.normalize_email("  Maria@Correo.COM  ") == "maria@correo.com"


# ---------------------------------------------------------------------------
# language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("es", "ES"),
        ("ES", "ES"),
        ("pt", "PT"),
        ("PT", "PT"),
        ("fr", "FR"),
        ("FR", "FR"),
        ("de", "DE"),
        ("it", "IT"),
    ],
)
def test_language_recognised(raw, expected):
    """Languages that have an email template are recognised."""
    assert engine.normalize_language(raw) == expected


@pytest.mark.parametrize("raw", ["en", "EN", "tlh", "", None])
def test_language_defaults_to_english(raw):
    """Unknown languages default to English."""
    assert engine.normalize_language(raw) == "EN"


# ---------------------------------------------------------------------------
# format_event_description
# ---------------------------------------------------------------------------


def test_event_description_has_contact():
    """The event description includes the contact's details."""
    text = engine.format_event_description("Maria Perez", "maria@correo.com", "+573001234567")
    assert "Maria Perez" in text
    assert "maria@correo.com" in text
    assert "+573001234567" in text
