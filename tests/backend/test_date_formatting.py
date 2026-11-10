from datetime import datetime

import pytest

from agent_backend.date_formatting import format_booking_time, format_full_date

# 2026-04-07 es martes.
TUESDAY = datetime(2026, 4, 7, 15, 30)


def test_format_full_date_spanish():
    assert format_full_date(TUESDAY, "ES") == "Martes, 7 de abril de 2026"


def test_format_full_date_english():
    assert format_full_date(TUESDAY, "EN") == "Tuesday, April 7, 2026"


def test_format_full_date_portuguese():
    assert format_full_date(TUESDAY, "PT") == "Terça-feira, 7 de abril de 2026"


def test_format_booking_time_spanish_is_12h_with_period():
    assert format_booking_time(TUESDAY, "ES") == "03:30 pm"


def test_format_booking_time_english_is_24h():
    assert format_booking_time(TUESDAY, "EN") == "15:30"


def test_format_booking_time_portuguese_is_24h():
    assert format_booking_time(TUESDAY, "PT") == "15:30"


@pytest.mark.parametrize("hour,expected", [(0, "12:00 am"), (12, "12:00 pm"), (23, "11:00 pm")])
def test_format_booking_time_spanish_boundaries(hour, expected):
    dt = TUESDAY.replace(hour=hour, minute=0)
    assert format_booking_time(dt, "ES") == expected
