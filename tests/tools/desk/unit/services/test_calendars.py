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


def test_discovery_finds_ids_ft_first():
    """Discovery finds GHL and Google ids and keeps FT first."""
    env = {
        "FA_GHL_CALENDAR_ID_CONSULTA": "abc",
        "FA_GOOGLE_CALENDAR_ID_SEGUIMIENTO": "def",
        "FA_GHL_CALENDAR_ID_IVF": "x",
    }
    assert discover_calendar_keys(env) == ["FT", "CONSULTA", "IVF", "SEGUIMIENTO"]


def test_discovery_ignores_empty_and_unrelated():
    """Discovery ignores empty values and unrelated variables."""
    env = {
        "FA_GHL_CALENDAR_ID_VACIO": "",
        "GHL_LOCATION_ID": "loc",
        "OTRA_GHL_CALENDAR_ID_X": "1",
        "FA_GOOGLE_CLIENT_ID_GMAIL": "x",
        "FA_GMAIL_SENDER_EMAIL": "x@y.z",
        "FA_NOTIFICATION_EMAIL": "team@y.z",
    }
    assert discover_calendar_keys(env) == ["FT"]


def test_any_variable_declares_calendar():
    """Google and timing variables also declare a calendar."""
    env = {"FA_GOOGLE_CLIENT_ID_CONTROL": "x", "FA_DURATION_MINUTES_SEGUIMIENTO": "20"}
    assert discover_calendar_keys(env) == ["FT", "CONTROL", "SEGUIMIENTO"]


def test_discovery_key_chars():
    """Calendar keys may contain underscores and digits."""
    assert discover_calendar_keys({"FA_GHL_CALENDAR_ID_FOLLOW_UP_2": "1"})[-1] == "FOLLOW_UP_2"


# --- resolution ------------------------------------------------------------


def test_builtin_calendars_keep_modules():
    """Built-in calendars keep their own policy modules."""
    settings = _Settings(ivf=_tool("a"), sur=_tool("b"))
    ivf = resolve_calendar(settings, "ivf")
    sur = resolve_calendar(settings, "SUR")
    assert ivf.booking is booking_ivf and ivf.slots is slots_ivf
    assert sur.booking is booking_sur and sur.slots is slots_sur


def test_empty_calendar_type_means_ft():
    """An empty calendar type means FT."""
    assert resolve_calendar(_Settings(ft=_tool()), None).key == "FT"
    assert resolve_calendar(_Settings(ft=_tool()), "").key == "FT"


def test_unknown_calendar_is_none():
    """An unknown calendar resolves to None instead of falling back to IVF."""
    assert resolve_calendar(_Settings(ivf=_tool()), "NOPE") is None


def test_unknown_message_lists_valid_keys():
    """The unknown-calendar message lists the valid keys."""
    message = unknown_calendar_message(_Settings(ivf=_tool(), consulta=_tool()), "x")
    assert "IVF, CONSULTA" in message and "'x'" in message


def test_new_calendar_default_rules():
    """A new calendar uses default rules with its key as tag."""
    cal = resolve_calendar(
        _Settings(consulta=_tool("id1")), "consulta", {"default": {"hours": IVF_HOURS}, "calendars": {}}
    )
    assert cal.tool.ghl_calendar_id == "id1"
    assert cal.booking.EVENT_SUMMARY_TAG == "CONSULTA"
    assert cal.booking.EMAIL_TEMPLATE_PREFIX is None
    assert cal.booking.is_valid_business_hour(1, 9, 0) is True


def test_new_calendar_overrides_only_given():
    """A calendar entry overrides only the fields it defines."""
    config = {
        "default": {"agent_name": "Base", "hours": IVF_HOURS},
        "calendars": {
            "Consulta": {"agent_name": "Ana", "email_template_prefix": "book_x", "hours": {3: [8, 0, 10, 0]}}
        },
    }
    cal = resolve_calendar(_Settings(consulta=_tool()), "CONSULTA", config)
    assert (cal.booking.AGENT_NAME, cal.booking.EMAIL_TEMPLATE_PREFIX) == ("Ana", "book_x")
    assert cal.booking.is_valid_business_hour(3, 9, 0) is True
    assert cal.booking.is_valid_business_hour(1, 9, 0) is False  # Monday not in the override
    assert cal.slots.day_window(3) == (8, 0, 10, 0)


def test_available_keys_follow_settings():
    """Available keys follow the settings."""
    assert available_keys(_Settings(ivf=_tool(), x=_tool())) == ["IVF", "X"]


# --- the YAML-driven rules reproduce the hand-written IVF/SUR rules ---------


@pytest.mark.parametrize(
    ("hours", "reference"),
    [(IVF_HOURS, booking_ivf), (SUR_HOURS, booking_sur)],
    ids=["ivf", "sur"],
)
def test_configured_booking_matches_reference(hours, reference):
    """Configured booking hours match the reference for every minute of the week."""
    rules = {"hours": hours, "lunch_break": LUNCH}
    configured = ConfiguredBooking("X", rules)
    for weekday in range(7):
        for hour in range(24):
            for minute in (0, 1, 30, 59):
                assert configured.is_valid_business_hour(
                    weekday, hour, minute
                ) == reference.is_valid_business_hour(weekday, hour, minute), (weekday, hour, minute)


@pytest.mark.parametrize("policy_name, reference", [("ivf", slots_ivf), ("sur", slots_sur)])
def test_configured_slots_match_reference(policy_name, reference):
    """Configured slot windows match the reference."""
    from desk.core.config import load_slots_config

    rules = load_slots_config()["policies"][policy_name]
    configured = ConfiguredSlots({"hours": rules["windows"], "lunch_break": rules["lunch_break"]})
    for weekday in range(7):
        assert configured.day_window(weekday) == reference.day_window(weekday)
        if configured.day_window(weekday):  # on closed days the legacy fallback differs per calendar
            assert configured.closing_hour(weekday) == reference.closing_hour(weekday)
    for start_min in range(0, 24 * 60, 15):
        assert configured.lunch_break(start_min, start_min + 30) == reference.lunch_break(
            start_min, start_min + 30
        )


# --- FT: the single round-robin calendar --------------------------------------


def test_ft_is_default_calendar():
    """FT always exists and is the default calendar."""
    assert discover_calendar_keys({}) == ["FT"]


def test_ft_rules_from_yaml():
    """FT takes its rules from calendars.yaml and sends the advisor-free email."""
    from desk.services.calendars import load_calendars_config

    cal = resolve_calendar(_Settings(ft=_tool("rr-id")), "ft", load_calendars_config())

    assert cal.tool.ghl_calendar_id == "rr-id"
    assert cal.booking.EVENT_SUMMARY_TAG == "FT"
    assert cal.booking.EMAIL_TEMPLATE_PREFIX == "book_appointment_ft"
    assert cal.booking.is_valid_business_hour(1, 7, 30) is True  # opens at 07:30
    assert cal.booking.is_valid_business_hour(1, 7, 0) is False
    assert cal.booking.is_valid_business_hour(1, 12, 30) is False  # lunch
    assert cal.booking.is_valid_business_hour(0, 9, 0) is False  # Sunday: closed
