from datetime import date

import pytest
from surrogacy.utils.parsing import is_present, normalize, parse_boolean, parse_flexible_date, parse_float

# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


def test_normalize_strips_accents_and_uppercases():
    """Accents are removed and the text is uppercased."""
    assert normalize("bogotá") == "BOGOTA"


def test_normalize_trims_whitespace():
    """Leading and trailing spaces are removed."""
    assert normalize("  Chía  ") == "CHIA"


def test_normalize_none_is_empty():
    """None gives an empty string."""
    assert normalize(None) == ""


# ---------------------------------------------------------------------------
# is_present
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   "])
def test_is_present_false_for_blank(value):
    """None, empty and blank strings are not present."""
    assert is_present(value) is False


@pytest.mark.parametrize("value", ["si", 0, False, "0"])
def test_is_present_true_for_falsy_values(value):
    """0, False and '0' still count as present."""
    assert is_present(value) is True


# ---------------------------------------------------------------------------
# parse_boolean
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [True, "true", "TRUE", "1", "si", "SI", "yes"])
def test_boolean_true_variants(value):
    """Common yes spellings parse to True."""
    assert parse_boolean(value) is True


@pytest.mark.parametrize("value", [False, "false", "FALSE", "0", "no", "NO"])
def test_boolean_false_variants(value):
    """Common no spellings parse to False."""
    assert parse_boolean(value) is False


@pytest.mark.parametrize("value", [None, "", "tal vez", "2"])
def test_boolean_unknown_is_none(value):
    """Unrecognised text parses to None."""
    assert parse_boolean(value) is None


# ---------------------------------------------------------------------------
# parse_float
# ---------------------------------------------------------------------------


def test_float_parses_numeric_string():
    """A numeric string parses to a float."""
    assert parse_float("22.5") == 22.5


def test_float_invalid_is_none():
    """A non-numeric string parses to None."""
    assert parse_float("veinticinco") is None


def test_float_none_is_none():
    """None parses to None."""
    assert parse_float(None) is None


# ---------------------------------------------------------------------------
# parse_flexible_date
# ---------------------------------------------------------------------------


def test_date_year_first():
    """YYYY/MM/DD is parsed."""
    assert parse_flexible_date("2023/01/15") == date(2023, 1, 15)


def test_date_day_first():
    """DD/MM/YYYY is parsed."""
    assert parse_flexible_date("15/01/2023") == date(2023, 1, 15)


def test_date_iso_datetime():
    """An ISO datetime falls back to its date."""
    assert parse_flexible_date("2023-01-15T10:00:00") == date(2023, 1, 15)


def test_date_invalid_month_is_none():
    """An impossible month gives None."""
    assert parse_flexible_date("13/13/2023") is None


def test_date_garbage_is_none():
    """Free text gives None."""
    assert parse_flexible_date("no es una fecha") is None


def test_date_none_is_none():
    """None gives None."""
    assert parse_flexible_date(None) is None


def test_date_instance_passes_through():
    """A date object is returned unchanged."""
    d = date(2023, 1, 15)
    assert parse_flexible_date(d) == d
