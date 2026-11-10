"""GoHighLevel tools carry the -ghl suffix and Google Calendar tools the -google suffix."""

from tests.tools.apps import desk_app as app

SCHEDULING = ("get-available-slots", "book-appointment", "find-appointment", "edit-appointment", "cancel-appointment")


def _paths() -> set[str]:
    return {path.removeprefix("/api/v1/") for path in app.openapi()["paths"]}


def test_scheduling_tools_exist_with_ghl_and_google_suffixes():
    paths = _paths()
    for name in SCHEDULING:
        assert f"{name}-ghl" in paths, name
        assert f"{name}-google" in paths, name
    assert "resolve-event-link-ghl" in paths


def test_no_scheduling_route_is_left_without_a_suffix():
    paths = _paths()
    assert [name for name in SCHEDULING if name in paths] == []
    assert "resolve-event-link" not in paths


def test_ghl_routes_are_the_gohighlevel_implementations():
    from desk.api.v1.endpoints import book_appointment_ghl, get_available_slots_ghl

    assert hasattr(book_appointment_ghl, "ghl_create_appointment")
    assert hasattr(get_available_slots_ghl, "ghl_get_available_slots")
