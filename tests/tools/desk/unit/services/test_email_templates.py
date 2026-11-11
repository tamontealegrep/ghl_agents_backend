import pytest
from desk.services.email_templates import render_email_template

VARS = dict(
    contact_name="Maria Perez",
    agent_name="Ayda",
    booking_date="Martes, 7 de abril de 2026",
    booking_time="03:30 pm",
    meet_link="https://meet.google.com/abc-defg-hij",
    calendar_link="https://calendar.google.com/calendar/render?action=TEMPLATE",
)


TEMPLATES = ["book_appointment_ft_es", "book_appointment_ft_en", "book_appointment_ft_pt"]


@pytest.mark.parametrize("template_name", TEMPLATES)
def test_render_email_template_substitutes_all_variables(template_name):
    html = render_email_template(template_name, **VARS)
    assert "Maria Perez" in html
    assert VARS["meet_link"] in html
    assert VARS["calendar_link"] in html
    assert "${" not in html  # no debe quedar ningun placeholder sin resolver


@pytest.mark.parametrize("template_name", TEMPLATES)
def test_the_confirmation_e_mail_never_names_the_advisor(template_name):
    """Appointments are shared out by the round robin, so the e-mail cannot say who will attend."""
    html = render_email_template(template_name, **{**VARS, "agent_name": "UNIQUE-ADVISOR-NAME"})
    assert "UNIQUE-ADVISOR-NAME" not in html
    assert "agent_name" not in (
        __import__("pathlib").Path(__file__).resolve().parents[5]
        / "companies/family_aims/bundles/_tools/desk/templates/emails"
        / f"{template_name}.html"
    ).read_text(encoding="utf-8")


def test_render_email_template_missing_variable_raises():
    incomplete = dict(VARS)
    del incomplete["meet_link"]
    with pytest.raises(KeyError):
        render_email_template("book_appointment_ft_es", **incomplete)


def test_render_email_template_unknown_template_raises():
    with pytest.raises(FileNotFoundError):
        render_email_template("no_existe", **VARS)


def test_the_add_to_calendar_link_carries_the_time_and_the_meet_link():
    from datetime import datetime, timedelta
    from urllib.parse import parse_qs, urlparse
    from zoneinfo import ZoneInfo

    from desk.services.calendar_links import build_add_to_calendar_link

    start = datetime(2026, 12, 1, 15, 30, tzinfo=ZoneInfo("America/Bogota"))
    link = build_add_to_calendar_link(start, start + timedelta(minutes=30), "en", "https://meet.google.com/abc")
    query = parse_qs(urlparse(link).query)

    assert link.startswith("https://calendar.google.com/calendar/render?")
    assert query["dates"] == ["20261201T203000Z/20261201T210000Z"]
    assert query["location"] == ["https://meet.google.com/abc"]
    assert query["text"] == ["Appointment with Family Aims"]
    assert "location" not in parse_qs(urlparse(build_add_to_calendar_link(start, start, "xx")).query)


def test_the_booking_response_carries_both_links():
    from desk.schemas.booking import BookAppointmentResponse

    response = BookAppointmentResponse(success=True, event_link="https://g/e", calendar_link="https://g/c")

    assert response.model_dump()["event_link"] == "https://g/e"
    assert response.model_dump()["calendar_link"] == "https://g/c"
