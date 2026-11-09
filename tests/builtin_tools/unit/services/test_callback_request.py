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


def test_minimal_valid_request_with_only_phone():
    result = _call()
    assert result["contact_name"] == "Maria Perez"
    assert result["contact_phone"] == "+573001234567"
    assert result["contact_email"] is None
    assert result["preferred_days"] == []
    assert result["preferred_time_window"] is None
    assert result["errors"] is None


def test_minimal_valid_request_with_only_email():
    result = _call(raw_contact_phone=None, raw_contact_email="maria@example.com")
    assert result["errors"] is None
    assert result["contact_phone"] is None
    assert result["contact_email"] == "maria@example.com"


def test_valid_request_with_both_phone_and_email():
    result = _call(raw_contact_email="maria@example.com")
    assert result["errors"] is None
    assert result["contact_phone"] == "+573001234567"
    assert result["contact_email"] == "maria@example.com"


@pytest.mark.parametrize("raw_contact_name", [None, "", "   "])
def test_missing_contact_name_is_rejected(raw_contact_name):
    result = _call(raw_contact_name=raw_contact_name)
    assert "contact_name" in result["errors"]
    assert result["contact_phone"] is None  # el rechazo no filtra datos parcialmente validados


def test_missing_both_phone_and_email_is_rejected():
    result = _call(raw_contact_phone=None, raw_contact_email=None)
    assert "contact_phone" in result["errors"]
    assert "contact_email" in result["errors"]


@pytest.mark.parametrize(
    "reason",
    ["no_availability", "booking_failed", "user_requested", "ambiguous_data", "technical_error", "NO_AVAILABILITY"],
)
def test_valid_reasons_are_accepted_case_insensitive(reason):
    result = _call(raw_reason=reason)
    assert result["errors"] is None
    assert result["reason"] == reason.lower()


@pytest.mark.parametrize("reason", [None, "", "otra_cosa"])
def test_invalid_reason_is_rejected(reason):
    result = _call(raw_reason=reason)
    assert "reason" in result["errors"]


def test_missing_timezone_is_rejected():
    result = _call(raw_timezone=None)
    assert "timezone" in result["errors"]


def test_invalid_timezone_is_rejected():
    result = _call(raw_timezone="Not/A_Real_Zone")
    assert "timezone" in result["errors"]


@pytest.mark.parametrize(
    "raw_timezone",
    ["America/Bogota", "Europe/Madrid", "America/New_York", "Asia/Tokyo"],
)
def test_valid_timezones_from_anywhere_are_accepted(raw_timezone):
    result = _call(raw_timezone=raw_timezone)
    assert result["errors"] is None
    assert result["timezone"] == raw_timezone


def test_preferred_days_single_day():
    result = _call(raw_preferred_days="monday")
    assert result["errors"] is None
    assert result["preferred_days"] == ["monday"]


def test_preferred_days_comma_separated_string():
    result = _call(raw_preferred_days="wednesday,monday")
    assert result["errors"] is None
    assert result["preferred_days"] == ["monday", "wednesday"]  # orden canonico, no el de entrada


def test_preferred_days_as_list():
    result = _call(raw_preferred_days=["friday", "monday"])
    assert result["errors"] is None
    assert result["preferred_days"] == ["monday", "friday"]


def test_preferred_days_weekdays_shortcut():
    result = _call(raw_preferred_days="weekdays")
    assert result["errors"] is None
    assert result["preferred_days"] == ["monday", "tuesday", "wednesday", "thursday", "friday"]


def test_preferred_days_weekend_shortcut():
    result = _call(raw_preferred_days="weekend")
    assert result["errors"] is None
    assert result["preferred_days"] == ["saturday", "sunday"]


def test_preferred_days_weekend_plus_extra_day_merges():
    result = _call(raw_preferred_days="weekend,monday")
    assert result["errors"] is None
    assert result["preferred_days"] == ["monday", "saturday", "sunday"]


def test_preferred_days_any_means_no_restriction():
    result = _call(raw_preferred_days="any")
    assert result["errors"] is None
    assert result["preferred_days"] == []


def test_preferred_days_none_means_no_restriction():
    result = _call(raw_preferred_days=None)
    assert result["errors"] is None
    assert result["preferred_days"] == []


def test_preferred_days_invalid_token_is_rejected():
    result = _call(raw_preferred_days="funday")
    assert "preferred_days" in result["errors"]


@pytest.mark.parametrize("window", ["morning", "midday", "afternoon", "evening", "EVENING"])
def test_valid_time_windows_are_accepted_case_insensitive(window):
    result = _call(raw_preferred_time_window=window)
    assert result["errors"] is None
    assert result["preferred_time_window"] == window.lower()


def test_time_window_any_means_no_restriction():
    result = _call(raw_preferred_time_window="any")
    assert result["errors"] is None
    assert result["preferred_time_window"] is None


def test_invalid_time_window_is_rejected():
    result = _call(raw_preferred_time_window="madrugada")
    assert "preferred_time_window" in result["errors"]


def test_context_is_passed_through_when_present():
    result = _call(raw_context="No hubo cupos en los proximos 14 dias")
    assert result["errors"] is None
    assert result["context"] == "No hubo cupos en los proximos 14 dias"


def test_context_is_none_when_absent():
    result = _call()
    assert result["context"] is None
