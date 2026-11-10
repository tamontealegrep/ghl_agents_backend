"""Default identifiers of a simulated or API-created contact.

A GoHighLevel webhook always carries the contact's ``contact_id`` and the ``location_id`` (sub-account). A chat
started by hand (the ``/chat`` route, the terminal chat, the playground, a voice call) has to provide them for the
tools that talk to GHL and for the custom-field syncs of the agents. The location is the same for every contact of
a company, so it can come from its ``.env``; the contact id never can.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

LOCATION_ENV = "GHL_LOCATION_ID"


def with_default_ids(
    contact: Mapping[str, Any] | None, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Returns the contact with ``location_id`` filled from ``GHL_LOCATION_ID`` when it is missing or empty.

    ``contact_id`` is never invented: a contact without one simply has none, and the GHL-dependent steps are skipped.

    Args:
        contact: CRM fields given by the caller (may be None).
        environ: Variables to read; defaults to the process environment.

    Returns:
        A new dict; the input is not modified.
    """
    result = dict(contact or {})
    default = (environ if environ is not None else os.environ).get(LOCATION_ENV, "").strip()
    if default and not str(result.get("location_id") or "").strip():
        result["location_id"] = default
    return result
