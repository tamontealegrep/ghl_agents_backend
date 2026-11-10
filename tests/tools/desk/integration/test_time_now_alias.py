from fastapi.testclient import TestClient
from tests.tools.apps import desk_app as app

client = TestClient(app)


def test_time_now_reachable_under_the_family_aims_snake_case_alias():
    """
Regression test (2026-09-17): family_aims_sam_text_2_0's scheduling.yaml/

    appointment_management.yaml declare time_now a required tool, but it only
        ever lived in tools.utils, mounted at a different top-level prefix
        (/utils/v1) than this agent's single tools_base_url (/family_aims/v1) -
        every real call 404'd. The fix aliases tools.utils's own handler here,
        the same way check_visa/get_available_slots/etc. are already aliased.

    Returns:
        None.
"""
    response = client.post("/api/v1/time_now", json={"iana_timezone": "Asia/Jakarta"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["iana_timezone"] == "Asia/Jakarta"
    assert data["now"] is not None
