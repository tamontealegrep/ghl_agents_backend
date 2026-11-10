from datetime import date

import pytest

from surrogacy.utils.parsing import is_present, normalize, parse_boolean, parse_flexible_date, parse_float


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------

def test_normalize_strips_accents_and_uppercases():
    assert normalize("bogotÃ¡") == "BOGOTA"


def test_normalize_trims_surrounding_whitespace():
    assert normalize("  ChÃ­a  ") == "CHIA"


def test_normalize_none_returns_empty_string():
    assert normalize(None) == ""


# ---------------------------------------------------------------------------
# is_present
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "", "   "])
def test_is_present_false_for_missing_values(value):
    assert is_present(value) is False


@pytest.mark.parametrize("value", ["si", 0, False, "0"])
def test_is_present_true_for_falsy_but_present_values(value):
    assert is_present(value) is True


# ---------------------------------------------------------------------------
# parse_boolean
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [True, "true", "TRUE", "1", "si", "SI", "yes"])
def test_parse_boolean_true_variants(value):
    assert parse_boolean(value) is True


@pytest.mark.parametrize("value", [False, "false", "FALSE", "0", "no", "NO"])
def test_parse_boolean_false_variants(value):
    assert parse_boolean(value) is False


@pytest.mark.parametrize("value", [None, "", "tal vez", "2"])
def test_parse_boolean_unrecognized_returns_none(value):
    assert parse_boolean(value) is None


# ---------------------------------------------------------------------------
# parse_float
# ---------------------------------------------------------------------------

def test_parse_float_valid_numeric_string():
    assert parse_float("22.5") == 22.5


def test_parse_float_invalid_string_returns_none():
    assert parse_float("veinticinco") is None


def test_parse_float_none_returns_none():
    assert parse_float(None) is None


# ---------------------------------------------------------------------------
# parse_flexible_date
# ---------------------------------------------------------------------------

def test_parse_flexible_date_year_first_format():
    assert parse_flexible_date("2023/01/15") == date(2023, 1, 15)


def test_parse_flexible_date_day_first_format():
    assert parse_flexible_date("15/01/2023") == date(2023, 1, 15)


def test_parse_flexible_date_iso_datetime_fallback():
    assert parse_flexible_date("2023-01-15T10:00:00") == date(2023, 1, 15)


def test_parse_flexible_date_invalid_month_returns_none():
    assert parse_flexible_date("13/13/2023") is None


def test_parse_flexible_date_garbage_string_returns_none():
    assert parse_flexible_date("no es una fecha") is None


def test_parse_flexible_date_none_returns_none():
    assert parse_flexible_date(None) is None


def test_parse_flexible_date_accepts_python_date_instance():
    d = date(2023, 1, 15)
    assert parse_flexible_date(d) == d

