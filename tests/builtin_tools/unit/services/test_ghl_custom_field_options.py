"""
Prueba que update_custom_field rechaza valores que no son opciones de un campo desplegable.
"""

import asyncio

from agent_backend.builtin_tools.services import ghl

CITY = {"id": "f1", "dataType": "SINGLE_OPTIONS", "picklistOptions": ["Bogotá", "Chía", "Otro"]}
DOCS = {"id": "f2", "dataType": "MULTIPLE_OPTIONS", "picklistOptions": ["cedula_ciudadania", "ppt"]}
TEXT = {"id": "f3", "dataType": "TEXT"}


def test_single_option_accepts_only_listed_values():
    assert ghl._invalid_options(CITY, "Chía") == []
    assert ghl._invalid_options(CITY, "Medellín") == ["Medellín"]
    assert ghl._invalid_options(CITY, "chía") == ["chía"]


def test_multiple_options_split_on_commas_and_report_each_invalid_value():
    assert ghl._invalid_options(DOCS, "cedula_ciudadania, ppt") == []
    assert ghl._invalid_options(DOCS, "ppt,pasaporte") == ["pasaporte"]


def test_free_text_and_missing_options_accept_anything():
    assert ghl._invalid_options(TEXT, "28") == []
    assert ghl._invalid_options({"id": "f4", "dataType": "SINGLE_OPTIONS"}, "x") == []


def test_update_is_rejected_before_calling_ghl_when_the_option_is_invalid(monkeypatch):
    async def fake_find(location_id, name, config, headers):
        return CITY

    monkeypatch.setattr(ghl, "_find_custom_field_by_name", fake_find)

    result = asyncio.run(ghl.update_custom_field_service("city_residence", "Medellín", "contact1", "loc1"))

    assert result["success"] is False
    assert "Medellín" in result["errors"] and "Allowed: Bogotá, Chía, Otro" in result["errors"]


def test_multiple_options_field_accepts_a_slot_list_and_writes_it_comma_separated():
    assert ghl._as_option_values(DOCS, "['cedula_ciudadania', 'ppt']") == "cedula_ciudadania,ppt"
    assert ghl._as_option_values(DOCS, "ppt") == "ppt"
    assert ghl._as_option_values(CITY, "['x']") == "['x']"
