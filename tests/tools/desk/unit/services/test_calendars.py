import pytest
from desk.core.config import ToolConfig, discover_calendar_keys
from desk.services import booking_ivf, booking_sur, slots_ivf, slots_sur
from desk.services.calendars import (
    ConfiguredBooking,
    ConfiguredSlots,
    available_keys,
    resolve_calendar,
    unknown_calendar_message,
)


def _tool(ghl_id: str = "") -> ToolConfig:
    return ToolConfig("", "", "", "", ghl_id)


class _Settings:
    def __init__(self, **calendars: ToolConfig) -> None:
        self.calendars = {k.upper(): v for k, v in calendars.items()}


IVF_HOURS = {d: [7, 30, 17, 0] for d in (1, 2, 3, 4, 5)}
SUR_HOURS = {1: [7, 30, 14, 0], **{d: [7, 30, 16, 0] for d in (2, 3, 4, 5)}}
LUNCH = {"start_hour": 12, "end_hour": 13}


# --- discovery -------------------------------------------------------------


def test_discovery_finds_ghl_and_google_ids_and_keeps_builtins_first():
    env = {
        "FA_GHL_CALENDAR_ID_CONSULTA": "abc",
        "FA_GOOGLE_CALENDAR_ID_SEGUIMIENTO": "def",
        "FA_GHL_CALENDAR_ID_IVF": "x",
    }
    assert discover_calendar_keys(env) == ["IVF", "SUR", "CONSULTA", "SEGUIMIENTO"]


def test_discovery_ignores_empty_values_and_unrelated_variables():
    env = {
        "FA_GHL_CALENDAR_ID_VACIO": "",
        "GHL_LOCATION_ID": "loc",
        "OTRA_GHL_CALENDAR_ID_X": "1",
        "FA_GOOGLE_CLIENT_ID_GMAIL": "x",
        "FA_GMAIL_SENDER_EMAIL": "x@y.z",
        "FA_NOTIFICATION_EMAIL": "team@y.z",
    }
    assert discover_calendar_keys(env) == ["IVF", "SUR"]


def test_google_and_timing_variables_also_declare_a_calendar():
    env = {"FA_GOOGLE_CLIENT_ID_CONTROL": "x", "FA_DURATION_MINUTES_SEGUIMIENTO": "20"}
    assert discover_calendar_keys(env) == ["IVF", "SUR", "CONTROL", "SEGUIMIENTO"]


def test_discovery_supports_keys_with_underscores_and_digits():
    assert discover_calendar_keys({"FA_GHL_CALENDAR_ID_FOLLOW_UP_2": "1"})[-1] == "FOLLOW_UP_2"


# --- resolution ------------------------------------------------------------


def test_builtin_calendars_keep_their_own_policy_modules():
    settings = _Settings(ivf=_tool("a"), sur=_tool("b"))
    ivf = resolve_calendar(settings, "ivf")
    sur = resolve_calendar(settings, "SUR")
    assert ivf.booking is booking_ivf and ivf.slots is slots_ivf
    assert sur.booking is booking_sur and sur.slots is slots_sur


def test_empty_calendar_type_means_ivf():
    assert resolve_calendar(_Settings(ivf=_tool()), None).key == "IVF"
    assert resolve_calendar(_Settings(ivf=_tool()), "").key == "IVF"


def test_unknown_calendar_resolves_to_none_instead_of_falling_back_to_ivf():
    assert resolve_calendar(_Settings(ivf=_tool()), "NOPE") is None


def test_unknown_message_lists_valid_keys():
    message = unknown_calendar_message(_Settings(ivf=_tool(), consulta=_tool()), "x")
    assert "IVF, CONSULTA" in message and "'x'" in message


def test_new_calendar_uses_default_rules_with_its_key_as_tag():
    cal = resolve_calendar(_Settings(consulta=_tool("id1")), "consulta", {"default": {"hours": IVF_HOURS}, "calendars": {}})
    assert cal.tool.ghl_calendar_id == "id1"
    assert cal.booking.EVENT_SUMMARY_TAG == "CONSULTA"
    assert cal.booking.EMAIL_TEMPLATE_PREFIX is None
    assert cal.booking.is_valid_business_hour(1, 9, 0) is True


def test_new_calendar_entry_overrides_default_fields_only():
    config = {
        "default": {"agent_name": "Base", "hours": IVF_HOURS},
        "calendars": {"Consulta": {"agent_name": "Ana", "email_template_prefix": "book_x", "hours": {3: [8, 0, 10, 0]}}},
    }
    cal = resolve_calendar(_Settings(consulta=_tool()), "CONSULTA", config)
    assert (cal.booking.AGENT_NAME, cal.booking.EMAIL_TEMPLATE_PREFIX) == ("Ana", "book_x")
    assert cal.booking.is_valid_business_hour(3, 9, 0) is True
    assert cal.booking.is_valid_business_hour(1, 9, 0) is False  # Monday not in the override
    assert cal.slots.day_window(3) == (8, 0, 10, 0)


def test_available_keys_follow_settings():
    assert available_keys(_Settings(ivf=_tool(), x=_tool())) == ["IVF", "X"]


# --- the YAML-driven rules reproduce the hand-written IVF/SUR rules ---------


@pytest.mark.parametrize(
    ("hours", "reference"),
    [(IVF_HOURS, booking_ivf), (SUR_HOURS, booking_sur)],
    ids=["ivf", "sur"],
)
def test_configured_booking_matches_reference_for_every_minute_of_the_week(hours, reference):
    rules = {"hours": hours, "lunch_break": LUNCH}
    configured = ConfiguredBooking("X", rules)
    for weekday in range(7):
        for hour in range(24):
            for minute in (0, 1, 30, 59):
                assert configured.is_valid_business_hour(weekday, hour, minute) == reference.is_valid_business_hour(
                    weekday, hour, minute
                ), (weekday, hour, minute)


@pytest.mark.parametrize("policy_name, reference", [("ivf", slots_ivf), ("sur", slots_sur)])
def test_configured_slots_match_reference(policy_name, reference):
    from desk.core.config import load_slots_config

    rules = load_slots_config()["policies"][policy_name]
    configured = ConfiguredSlots({"hours": rules["windows"], "lunch_break": rules["lunch_break"]})
    for weekday in range(7):
        assert configured.day_window(weekday) == reference.day_window(weekday)
        if configured.day_window(weekday):  # on closed days the legacy fallback differs per calendar
            assert configured.closing_hour(weekday) == reference.closing_hour(weekday)
    for start_min in range(0, 24 * 60, 15):
        assert configured.lunch_break(start_min, start_min + 30) == reference.lunch_break(start_min, start_min + 30)
