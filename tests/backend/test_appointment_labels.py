"""The date and the time of a booked appointment, written the way the contact reads them."""

from datetime import UTC, datetime

import pytest

from agent_backend.appointment_labels import appointment_labels


@pytest.mark.parametrize(
    ("utc", "timezone", "expected"),
    [
        (datetime(2026, 11, 17, 13, 50, tzinfo=UTC), "America/Bogota", ("Martes, 17 de NOVIEMBRE de 2026", "08:50 a.m")),
        (datetime(2026, 11, 16, 17, 0, tzinfo=UTC), "America/Bogota", ("Lunes, 16 de NOVIEMBRE de 2026", "12:00 p.m")),
        (datetime(2026, 12, 5, 5, 30, tzinfo=UTC), "America/Bogota", ("Sábado, 5 de DICIEMBRE de 2026", "12:30 a.m")),
        (datetime(2027, 1, 6, 19, 5, tzinfo=UTC), "America/Bogota", ("Miércoles, 6 de ENERO de 2027", "02:05 p.m")),
        (datetime(2026, 11, 20, 22, 10, tzinfo=UTC), "America/Bogota", ("Viernes, 20 de NOVIEMBRE de 2026", "05:10 p.m")),
        (datetime(2026, 11, 22, 3, 0, tzinfo=UTC), "America/Bogota", ("Sábado, 21 de NOVIEMBRE de 2026", "10:00 p.m")),
    ],
)
def test_labels_in_bogota(utc, timezone, expected):
    """Weekday, day, upper-case month and year, and a 12-hour time with a.m/p.m and no final period."""
    assert appointment_labels(utc, timezone) == expected


def test_labels_follow_the_contacts_time_zone():
    """The same instant reads differently in another zone, even on another day."""
    instant = datetime(2026, 11, 17, 13, 50, tzinfo=UTC)
    assert appointment_labels(instant, "Asia/Tokyo") == ("Martes, 17 de NOVIEMBRE de 2026", "10:50 p.m")
    assert appointment_labels(instant, "Australia/Sydney") == ("Miércoles, 18 de NOVIEMBRE de 2026", "12:50 a.m")


@pytest.mark.parametrize("month", range(1, 13))
def test_every_month_has_its_name(month):
    """Every month is written in upper-case Spanish."""
    label = appointment_labels(datetime(2026, month, 10, 15, 0, tzinfo=UTC), "America/Bogota")[0]
    months = "ENERO FEBRERO MARZO ABRIL MAYO JUNIO JULIO AGOSTO SEPTIEMBRE OCTUBRE NOVIEMBRE DICIEMBRE".split()
    assert f" de {months[month - 1]} de 2026" in label
