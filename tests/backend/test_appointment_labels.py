"""The date and the time of a booked appointment, in English: the agent translates them to its language."""

from datetime import UTC, datetime

import pytest

from agent_backend.appointment_labels import appointment_labels

BOGOTA = "America/Bogota"


@pytest.mark.parametrize(
    ("utc", "expected"),
    [
        (datetime(2026, 11, 17, 13, 50, tzinfo=UTC), ("Tuesday, November 17, 2026", "08:50 AM")),
        (datetime(2026, 11, 16, 17, 0, tzinfo=UTC), ("Monday, November 16, 2026", "12:00 PM")),
        (datetime(2026, 12, 5, 5, 30, tzinfo=UTC), ("Saturday, December 5, 2026", "12:30 AM")),
        (datetime(2027, 1, 6, 19, 5, tzinfo=UTC), ("Wednesday, January 6, 2027", "02:05 PM")),
        (datetime(2026, 11, 22, 3, 0, tzinfo=UTC), ("Saturday, November 21, 2026", "10:00 PM")),
    ],
)
def test_labels_default_to_the_12_hour_clock(utc, expected):
    """Weekday, month name, day and year in English, and an AM/PM time by default."""
    assert appointment_labels(utc, BOGOTA) == expected
    assert appointment_labels(utc, BOGOTA, "12h") == expected
    assert appointment_labels(utc, BOGOTA, None) == expected


@pytest.mark.parametrize(
    ("utc", "expected_time"),
    [
        (datetime(2026, 11, 17, 13, 50, tzinfo=UTC), "08:50"),
        (datetime(2026, 11, 16, 17, 0, tzinfo=UTC), "12:00"),
        (datetime(2026, 12, 5, 5, 30, tzinfo=UTC), "00:30"),
        (datetime(2027, 1, 6, 19, 5, tzinfo=UTC), "14:05"),
        (datetime(2026, 11, 22, 3, 0, tzinfo=UTC), "22:00"),
    ],
)
@pytest.mark.parametrize("option", ["24h", "24H", " 24h "])
def test_labels_in_the_24_hour_clock(utc, expected_time, option):
    """With 24h the time has no AM/PM; the date is the same."""
    date_label, time_label = appointment_labels(utc, BOGOTA, option)
    assert time_label == expected_time
    assert date_label == appointment_labels(utc, BOGOTA)[0]


@pytest.mark.parametrize("option", ["", "12h", "banana", "24"])
def test_anything_but_24h_is_read_as_12h(option):
    """The option is lenient: an unknown value never fails the booking."""
    assert appointment_labels(datetime(2026, 11, 17, 19, 5, tzinfo=UTC), BOGOTA, option)[1] == "02:05 PM"


def test_labels_follow_the_contacts_time_zone():
    """The same instant reads differently in another zone, even on another day."""
    instant = datetime(2026, 11, 17, 13, 50, tzinfo=UTC)
    assert appointment_labels(instant, "Asia/Tokyo") == ("Tuesday, November 17, 2026", "10:50 PM")
    assert appointment_labels(instant, "Australia/Sydney") == ("Wednesday, November 18, 2026", "12:50 AM")
    assert appointment_labels(instant, "Australia/Sydney", "24h")[1] == "00:50"


@pytest.mark.parametrize("month", range(1, 13))
def test_every_month_has_its_english_name(month):
    """Every month is written in English."""
    label = appointment_labels(datetime(2026, month, 10, 15, 0, tzinfo=UTC), BOGOTA)[0]
    months = "January February March April May June July August September October November December".split()
    assert f", {months[month - 1]} 10, 2026" in label
