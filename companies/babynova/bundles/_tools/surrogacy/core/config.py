"""
Module.

    Toda la configuración del agente vive aquí, leída una sola vez desde el .env
    del root con prefijo BN_. Nada más en el proyecto debe llamar a os.getenv
    directamente.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from agent_backend.calendars import CalendarSettings, load_calendars

BUILTIN_CALENDARS = ("FT",)
BUSINESS_TZ = "America/Bogota"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "slots.yaml"
CALENDARS_PATH = Path(__file__).resolve().parent.parent / "config" / "calendars.yaml"


@lru_cache
def load_slots_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"holidays": [], "windows": {}}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class GmailConfig:
    google_client_id: str
    google_client_secret: str
    google_refresh_token: str
    sender_email: str


class Settings:
    def __init__(self) -> None:
        # Every calendar declared as BN_<VARIABLE>_<KEY> (see agent_backend.calendars); FT always exists
        # and defaults to the primary calendar of its Google account.
        self.calendars: dict[str, CalendarSettings] = load_calendars(
            "BN", BUILTIN_CALENDARS, calendar_id_defaults={"FT": "primary"}, read_unset_from_ghl=True
        )

        # GoHighLevel: the company token and the location (sub-account) it belongs to.
        self.ghl_token = os.getenv("GHL_TOKEN", "")
        self.ghl_location_id = os.getenv("GHL_LOCATION_ID", "")

        # Optional internal addresses (comma-separated) told about every booked appointment,
        # so the team can start the human follow-up. Empty = no e-mail. Sent from this Gmail account.
        self.notification_email = os.getenv("BN_NOTIFICATION_EMAIL", "")
        self.gmail = GmailConfig(
            google_client_id=os.getenv("BN_GOOGLE_CLIENT_ID_GMAIL", ""),
            google_client_secret=os.getenv("BN_GOOGLE_CLIENT_SECRET_GMAIL", ""),
            google_refresh_token=os.getenv("BN_GOOGLE_REFRESH_TOKEN_GMAIL", ""),
            sender_email=os.getenv("BN_GMAIL_SENDER_EMAIL", ""),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
