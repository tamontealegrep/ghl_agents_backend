from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from desk.services import booking_engine as engine


# ---------------------------------------------------------------------------
# parse_start_date
# ---------------------------------------------------------------------------

def test_parse_start_date_preserves_explicit_offset():
    dt = engine.parse_start_date("2026-08-28T09:00:00-05:00")
    assert dt.utcoffset() == timedelta(hours=-5)
    assert dt.hour == 9


def test_parse_start_date_assumes_bogota_when_no_offset():
    dt = engine.parse_start_date("2026-08-28T09:00:00")
    assert dt.utcoffset() == timedelta(hours=-5)


def test_parse_start_date_invalid_raises_value_error():
    with pytest.raises(ValueError):
        engine.parse_start_date("no es una fecha")


# ---------------------------------------------------------------------------
# parse_duration_minutes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [("20", 20), ("45", 45), ("20abc", 20), ("  30  ", 30)])
def test_parse_duration_minutes_valid(raw, expected):
    assert engine.parse_duration_minutes(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", "0", "-5"])
def test_parse_duration_minutes_falls_back_to_default(raw):
    assert engine.parse_duration_minutes(raw) == 20


def test_parse_duration_minutes_custom_default():
    assert engine.parse_duration_minutes("abc", default=30) == 30


# ---------------------------------------------------------------------------
# compute_end_date / is_future
# ---------------------------------------------------------------------------

def test_compute_end_date_adds_duration():
    start = datetime(2026, 8, 28, 9, 0, tzinfo=ZoneInfo("America/Bogota"))
    end = engine.compute_end_date(start, 20)
    assert end == start + timedelta(minutes=20)


def test_is_future_true_for_later_date():
    now = datetime(2026, 8, 20, 0, 0, tzinfo=ZoneInfo("UTC"))
    start = datetime(2026, 8, 28, 9, 0, tzinfo=ZoneInfo("America/Bogota"))
    assert engine.is_future(start, now) is True


def test_is_future_false_for_past_date():
    now = datetime(2026, 8, 28, 0, 0, tzinfo=ZoneInfo("UTC"))
    start = datetime(2026, 8, 20, 9, 0, tzinfo=ZoneInfo("America/Bogota"))
    assert engine.is_future(start, now) is False


# ---------------------------------------------------------------------------
# format_contact_name
# ---------------------------------------------------------------------------

def test_format_contact_name_trims_collapses_and_titlecases():
    assert engine.format_contact_name("  maria   PEREZ gomez  ") == "Maria Perez Gomez"


def test_format_contact_name_single_word():
    assert engine.format_contact_name("ana") == "Ana"


# ---------------------------------------------------------------------------
# email
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("email", ["Maria@Correo.com", "  ana.perez@dominio.co  "])
def test_is_valid_email_accepts_well_formed_addresses(email):
    assert engine.is_valid_email(email) is True


@pytest.mark.parametrize("email", ["no-es-un-correo", "ana@", "ana@dominio", "ana@example.com"])
def test_is_valid_email_rejects_malformed_or_example_domain(email):
    assert engine.is_valid_email(email) is False


def test_normalize_email_trims_and_lowercases():
    assert engine.normalize_email("  Maria@Correo.COM  ") == "maria@correo.com"


# ---------------------------------------------------------------------------
# language
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [("es", "ES"), ("ES", "ES"), ("pt", "PT"), ("PT", "PT")])
def test_normalize_language_recognizes_es_and_pt(raw, expected):
    assert engine.normalize_language(raw) == expected


@pytest.mark.parametrize("raw", ["en", "EN", "fr", "", None])
def test_normalize_language_defaults_to_english(raw):
    assert engine.normalize_language(raw) == "EN"


# ---------------------------------------------------------------------------
# format_event_description
# ---------------------------------------------------------------------------

def test_format_event_description_includes_contact_info():
    text = engine.format_event_description("Maria Perez", "maria@correo.com", "+573001234567")
    assert "Maria Perez" in text
    assert "maria@correo.com" in text
    assert "+573001234567" in text
