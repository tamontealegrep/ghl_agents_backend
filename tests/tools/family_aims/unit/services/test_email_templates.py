import pytest

from family_aims.services.email_templates import render_email_template

VARS = dict(
    contact_name="Maria Perez",
    agent_name="Ayda",
    booking_date="Martes, 7 de abril de 2026",
    booking_time="03:30 pm",
    meet_link="https://meet.google.com/abc-defg-hij",
    event_link="https://calendar.google.com/event?eid=xyz",
)


@pytest.mark.parametrize(
    "template_name",
    [
        "book_appointment_ivf_es", "book_appointment_ivf_en", "book_appointment_ivf_pt",
        "book_appointment_sur_es", "book_appointment_sur_en", "book_appointment_sur_pt",
    ],
)
def test_render_email_template_substitutes_all_variables(template_name):
    html = render_email_template(template_name, **VARS)
    assert "Maria Perez" in html
    assert "Ayda" in html
    assert VARS["meet_link"] in html
    assert VARS["event_link"] in html
    assert "${" not in html  # no debe quedar ningun placeholder sin resolver


def test_render_email_template_missing_variable_raises():
    incomplete = dict(VARS)
    del incomplete["meet_link"]
    with pytest.raises(KeyError):
        render_email_template("book_appointment_ivf_es", **incomplete)


def test_render_email_template_unknown_template_raises():
    with pytest.raises(FileNotFoundError):
        render_email_template("no_existe", **VARS)
