import pytest

from agent_backend.calendars import discover_calendar_keys, load_calendar_settings, load_calendars


def test_each_company_prefix_sees_only_its_own_calendars():
    env = {"FA_GHL_CALENDAR_ID_CONSULTA": "1", "BN_GHL_CALENDAR_ID_CONTROL": "2"}
    assert discover_calendar_keys("FA", env) == ["CONSULTA"]
    assert discover_calendar_keys("BN", env) == ["CONTROL"]


@pytest.mark.parametrize(
    "variable",
    [
        "GHL_CALENDAR_ID",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
        "GOOGLE_CALENDAR_ID",
        "DURATION_MINUTES",
        "INTERVAL_MINUTES",
        "PRE_BUFFER_MINUTES",
        "POST_BUFFER_MINUTES",
        "MIN_NOTICE_MINUTES",
        "DATE_RANGE_DAYS",
    ],
)
def test_any_calendar_variable_declares_the_calendar(variable):
    assert discover_calendar_keys("BN", {f"BN_{variable}_CONTROL": "x"}) == ["CONTROL"]


def test_several_variables_of_one_key_count_once_and_keys_are_sorted():
    env = {"BN_GHL_CALENDAR_ID_B": "1", "BN_GOOGLE_CALENDAR_ID_B": "2", "BN_DATE_RANGE_DAYS_A": "3"}
    assert discover_calendar_keys("BN", env) == ["A", "B"]


def test_builtin_keys_come_first_and_exist_without_variables():
    assert discover_calendar_keys("BN", {"BN_GHL_CALENDAR_ID_A": "1"}, builtin=("ft",)) == ["FT", "A"]
    assert discover_calendar_keys("BN", {}, builtin=("FT",)) == ["FT"]


def test_gmail_sender_variables_are_not_calendars():
    env = {
        "BN_GOOGLE_CLIENT_ID_GMAIL": "x",
        "BN_GOOGLE_CLIENT_SECRET_GMAIL": "x",
        "BN_GOOGLE_REFRESH_TOKEN_GMAIL": "x",
        "BN_GMAIL_SENDER_EMAIL": "x@y.z",
        "BN_NOTIFICATION_EMAIL": "team@y.z",
    }
    assert discover_calendar_keys("BN", env) == []


def test_empty_values_and_other_variables_are_ignored():
    env = {
        "BN_GHL_CALENDAR_ID_E": "",
        "BN_GHL_LOCATION_ID": "x",
        "GHL_CALENDAR_ID_Z": "1",
        "BNX_GHL_CALENDAR_ID_Y": "1",
    }
    assert discover_calendar_keys("BN", env) == []


def test_prefix_is_matched_literally():
    assert discover_calendar_keys("B.", {"BN_GHL_CALENDAR_ID_Q": "1"}) == []


def test_calendar_settings_read_every_variable_and_apply_defaults():
    env = {
        "BN_GOOGLE_CLIENT_ID_X": "cid",
        "BN_GOOGLE_CLIENT_SECRET_X": "sec",
        "BN_GOOGLE_REFRESH_TOKEN_X": "ref",
        "BN_GOOGLE_CALENDAR_ID_X": "cal@g",
        "BN_GHL_CALENDAR_ID_X": "ghl1",
        "BN_DURATION_MINUTES_X": "45",
    }
    s = load_calendar_settings("BN", "X", post_buffer_minutes=10, environ=env)
    assert (s.google_client_id, s.google_client_secret, s.google_refresh_token) == ("cid", "sec", "ref")
    assert (s.calendar_id, s.ghl_calendar_id) == ("cal@g", "ghl1")
    assert (s.duration_minutes, s.interval_minutes, s.pre_buffer_minutes, s.post_buffer_minutes) == (
        45,
        0,
        0,
        10,
    )
    assert (s.min_notice_minutes, s.date_range_days) == (None, 14)


def test_default_calendar_id_applies_only_when_the_variable_is_unset():
    assert load_calendar_settings("BN", "FT", calendar_id="primary", environ={}).calendar_id == "primary"
    env = {"BN_GOOGLE_CALENDAR_ID_FT": "mine"}
    assert load_calendar_settings("BN", "FT", calendar_id="primary", environ=env).calendar_id == "mine"


def test_non_numeric_duration_names_the_variable():
    with pytest.raises(ValueError, match="BN_DURATION_MINUTES_X"):
        load_calendar_settings("BN", "X", environ={"BN_DURATION_MINUTES_X": "abc"})


def test_load_calendars_returns_builtin_and_discovered_with_per_key_defaults():
    env = {"BN_GHL_CALENDAR_ID_CONTROL": "c1"}
    calendars = load_calendars(
        "BN", ("FT",), post_buffer_minutes=10, calendar_id_defaults={"ft": "primary"}, environ=env
    )
    assert list(calendars) == ["FT", "CONTROL"]
    assert calendars["FT"].calendar_id == "primary" and calendars["CONTROL"].calendar_id == ""
    assert calendars["CONTROL"].post_buffer_minutes == 10 and calendars["CONTROL"].ghl_calendar_id == "c1"


def test_scheduling_parameters_are_read_per_calendar():
    env = {
        "FA_DURATION_MINUTES_X": "20",
        "FA_INTERVAL_MINUTES_X": "30",
        "FA_PRE_BUFFER_MINUTES_X": "5",
        "FA_POST_BUFFER_MINUTES_X": "15",
        "FA_MIN_NOTICE_MINUTES_X": "120",
        "FA_DATE_RANGE_DAYS_X": "21",
    }
    s = load_calendar_settings("FA", "X", environ=env)
    assert (s.duration_minutes, s.interval_minutes, s.pre_buffer_minutes) == (20, 30, 5)
    assert (s.post_buffer_minutes, s.min_notice_minutes, s.date_range_days) == (15, 120, 21)


def test_min_notice_stays_none_when_unset_or_empty_and_zero_is_a_real_value():
    assert load_calendar_settings("FA", "X", environ={}).min_notice_minutes is None
    assert (
        load_calendar_settings("FA", "X", environ={"FA_MIN_NOTICE_MINUTES_X": " "}).min_notice_minutes is None
    )
    assert load_calendar_settings("FA", "X", environ={"FA_MIN_NOTICE_MINUTES_X": "0"}).min_notice_minutes == 0


def test_company_defaults_apply_to_every_calendar_and_variables_override_them():
    env = {"FA_GHL_CALENDAR_ID_A": "1", "FA_GHL_CALENDAR_ID_B": "2", "FA_POST_BUFFER_MINUTES_B": "0"}
    calendars = load_calendars("FA", (), post_buffer_minutes=10, environ=env)
    assert calendars["A"].post_buffer_minutes == 10
    assert calendars["B"].post_buffer_minutes == 0


def test_old_names_no_longer_declare_or_configure_anything():
    assert discover_calendar_keys("FA", {"FA_GAP_MINUTES_X": "5", "FA_DAYS_AHEAD_X": "9"}) == []
    s = load_calendar_settings("FA", "X", environ={"FA_GAP_MINUTES_X": "5", "FA_DAYS_AHEAD_X": "9"})
    assert (s.interval_minutes, s.date_range_days) == (0, 14)
