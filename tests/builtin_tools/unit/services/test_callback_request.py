import pytest

from agent_backend.builtin_tools.services.callback_request import prepare_callback_request


def _call(**overrides):
    defaults = {
        "raw_contact_name": "Maria Perez",
        "raw_contact_phone": "+573001234567",
        "raw_contact_email": None,
        "raw_reason": "no_availability",
        "raw_context": None,
        "raw_preferred_days": None,
        "raw_preferred_time_window": None,
        "raw_timezone": "America/Bogota",
    }
    defaults.update(overrides)
    return prepare_callback_request(**defaults)


def test_phone_only_request_is_valid():
    """A request with only a phone is valid and gets empty preferences."""
    result = _call()
    assert result["contact_name"] == "Maria Perez"
    assert result["contact_phone"] == "+573001234567"
    assert result["contact_email"] is None
    assert result["preferred_days"] == []
    assert result["preferred_time_window"] is None
    assert result["errors"] is None


def test_email_only_request_is_valid():
    """A request with only an email is valid."""
    result = _call(raw_contact_phone=None, raw_contact_email="maria@example.com")
    assert result["errors"] is None
    assert result["contact_phone"] is None
    assert result["contact_email"] == "maria@example.com"


def test_phone_and_email_are_both_kept():
    """When both phone and email are given, both are returned."""
    result = _call(raw_contact_email="maria@example.com")
    assert result["errors"] is None
    assert result["contact_phone"] == "+573001234567"
    assert result["contact_email"] == "maria@example.com"


@pytest.mark.parametrize("raw_contact_name", [None, "", "   "])
def test_missing_name_is_rejected(raw_contact_name):
    """A missing or blank contact name is rejected and no partial data leaks."""
    result = _call(raw_contact_name=raw_contact_name)
    assert "contact_name" in result["errors"]
    assert result["contact_phone"] is None  # a rejection never leaks partly valid data


def test_missing_phone_and_email_is_rejected():
    """At least one of phone or email is required."""
    result = _call(raw_contact_phone=None, raw_contact_email=None)
    assert "contact_phone" in result["errors"]
    assert "contact_email" in result["errors"]


@pytest.mark.parametrize(
    "reason",
    [
        "no_availability",
        "booking_failed",
        "user_requested",
        "ambiguous_data",
        "technical_error",
        "NO_AVAILABILITY",
    ],
)
def test_valid_reason_is_accepted_any_case(reason):
    """Every allowed reason is accepted and lowercased."""
    result = _call(raw_reason=reason)
    assert result["errors"] is None
    assert result["reason"] == reason.lower()


@pytest.mark.parametrize("reason", [None, "", "otra_cosa"])
def test_invalid_reason_is_rejected(reason):
    """A missing or unknown reason is rejected."""
    result = _call(raw_reason=reason)
    assert "reason" in result["errors"]


def test_missing_timezone_is_rejected():
    """A missing timezone is rejected."""
    result = _call(raw_timezone=None)
    assert "timezone" in result["errors"]


def test_unknown_timezone_is_rejected():
    """A timezone that is not an IANA zone is rejected."""
    result = _call(raw_timezone="Not/A_Real_Zone")
    assert "timezone" in result["errors"]


@pytest.mark.parametrize(
    "raw_timezone",
    ["America/Bogota", "Europe/Madrid", "America/New_York", "Asia/Tokyo"],
)
def test_valid_timezone_is_accepted(raw_timezone):
    """IANA timezones from any region are accepted and returned as `iana_timezone`."""
    result = _call(raw_timezone=raw_timezone)
    assert result["errors"] is None
    assert result["iana_timezone"] == raw_timezone


def test_days_single_day():
    """A single day is returned as a one-item list."""
    result = _call(raw_preferred_days="monday")
    assert result["errors"] is None
    assert result["preferred_days"] == ["monday"]


def test_days_comma_string_is_sorted():
    """A comma-separated string is split and returned in week order."""
    result = _call(raw_preferred_days="wednesday,monday")
    assert result["errors"] is None
    assert result["preferred_days"] == ["monday", "wednesday"]  # week order, not input order


def test_days_list_is_sorted():
    """A list of days is returned in week order."""
    result = _call(raw_preferred_days=["friday", "monday"])
    assert result["errors"] is None
    assert result["preferred_days"] == ["monday", "friday"]


def test_days_weekdays_shortcut():
    """`weekdays` expands to Monday through Friday."""
    result = _call(raw_preferred_days="weekdays")
    assert result["errors"] is None
    assert result["preferred_days"] == ["monday", "tuesday", "wednesday", "thursday", "friday"]


def test_days_weekend_shortcut():
    """`weekend` expands to Saturday and Sunday."""
    result = _call(raw_preferred_days="weekend")
    assert result["errors"] is None
    assert result["preferred_days"] == ["saturday", "sunday"]


def test_days_weekend_plus_day_is_merged():
    """`weekend` plus an extra day merges into one sorted list."""
    result = _call(raw_preferred_days="weekend,monday")
    assert result["errors"] is None
    assert result["preferred_days"] == ["monday", "saturday", "sunday"]


def test_days_any_means_no_restriction():
    """`any` gives an empty list, meaning no restriction."""
    result = _call(raw_preferred_days="any")
    assert result["errors"] is None
    assert result["preferred_days"] == []


def test_days_none_means_no_restriction():
    """No days given gives an empty list, meaning no restriction."""
    result = _call(raw_preferred_days=None)
    assert result["errors"] is None
    assert result["preferred_days"] == []


def test_days_unknown_day_is_rejected():
    """An unknown day name is rejected."""
    result = _call(raw_preferred_days="funday")
    assert "preferred_days" in result["errors"]


@pytest.mark.parametrize("window", ["morning", "midday", "afternoon", "evening", "EVENING"])
def test_valid_time_window_is_accepted_any_case(window):
    """Every allowed time window is accepted and lowercased."""
    result = _call(raw_preferred_time_window=window)
    assert result["errors"] is None
    assert result["preferred_time_window"] == window.lower()


def test_time_window_any_means_no_restriction():
    """`any` gives no time window."""
    result = _call(raw_preferred_time_window="any")
    assert result["errors"] is None
    assert result["preferred_time_window"] is None


def test_unknown_time_window_is_rejected():
    """An unknown time window is rejected."""
    result = _call(raw_preferred_time_window="madrugada")
    assert "preferred_time_window" in result["errors"]


def test_context_is_kept():
    """A given context is returned unchanged."""
    result = _call(raw_context="No hubo cupos en los proximos 14 dias")
    assert result["errors"] is None
    assert result["context"] == "No hubo cupos en los proximos 14 dias"


def test_context_is_none_when_missing():
    """No context given gives None."""
    result = _call()
    assert result["context"] is None
