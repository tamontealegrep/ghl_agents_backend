import pytest

from babynova_surrogacy.services.email_templates import render_email_template

VARS = dict(
    contact_name="Maria Perez",
    booking_date="2026/08/28 09:00",
    contact_phone="+573001234567",
)


def test_render_email_template_substitutes_all_variables():
    html = render_email_template("book_appointment", **VARS)
    assert "Maria Perez" in html
    assert "2026/08/28 09:00" in html
    assert "+573001234567" in html
    assert "${" not in html  # no debe quedar ningun placeholder sin resolver


def test_render_email_template_missing_variable_raises():
    incomplete = dict(VARS)
    del incomplete["booking_date"]
    with pytest.raises(KeyError):
        render_email_template("book_appointment", **incomplete)


def test_render_email_template_unknown_template_raises():
    with pytest.raises(FileNotFoundError):
        render_email_template("no_existe", **VARS)

