"""
Module.

    Toda la configuración del agente vive aquí, leída una sola vez desde el .env
    del root con prefijo FA_. Nada más en el proyecto debe llamar a os.getenv
    directamente.

    IVF y SU son calendarios independientes: cada uno con su propia autorización
    OAuth (confirmado con el owner: no comparten refresh token) y su propia
    política de agenda — de ahí que ToolConfig agrupe credenciales + agenda por
    calendario, no solo las credenciales. Ese MISMO ToolConfig lo usan tanto
    available-slots-* (consulta disponibilidad) como book-appointment-* (agenda
    la cita) para ese calendario — son el mismo calendario de Google, dos tools
    distintas que lo consultan.

    El envío de correos de confirmación usa una cuenta de Gmail COMPARTIDA entre
    IVF y SU (así estaba en los dos flujos de GHL: mismo credential id) — por
    eso GmailConfig vive aparte, no dentro de cada ToolConfig.
"""

import os
import yaml
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping

from agent_backend.calendars import CalendarSettings as ToolConfig
from agent_backend.calendars import discover_calendar_keys as _discover
from agent_backend.calendars import load_calendars

BUSINESS_TZ = "America/Bogota"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "slots.yaml"
CALENDARS_PATH = Path(__file__).resolve().parent.parent / "config" / "calendars.yaml"

# Calendars that always exist, so a deployment without their variables still answers
# with "Missing FA_..." errors as before.
BUILTIN_CALENDARS = ("IVF", "SUR")
# Free time kept after every appointment so the agent is not rushed; FA_POST_BUFFER_MINUTES_<KEY> overrides it.
DEFAULT_POST_BUFFER_MINUTES = 10


def discover_calendar_keys(environ: Mapping[str, str] | None = None) -> list[str]:
    """Finds the calendar keys declared in the environment (prefix ``FA``).

    Args:
        environ: Variables to scan. Defaults to ``os.environ``.

    Returns:
        Upper-case keys, IVF and SUR first. See ``agent_backend.calendars``.
    """
    return _discover("FA", environ, BUILTIN_CALENDARS)


@lru_cache
def load_slots_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"holidays": [], "policies": {}}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class GmailConfig:
    google_client_id: str
    google_client_secret: str
    google_refresh_token: str
    sender_email: str


class Settings:
    def __init__(self) -> None:
        self.calendars: Dict[str, ToolConfig] = load_calendars("FA", BUILTIN_CALENDARS, post_buffer_minutes=DEFAULT_POST_BUFFER_MINUTES)
        self.ghl_token = os.getenv("GHL_TOKEN", "")
        self.ghl_location_id = os.getenv("GHL_LOCATION_ID", "")
        # Optional internal addresses (comma-separated) told about every booking; empty = no notification.
        self.notification_email = os.getenv("FA_NOTIFICATION_EMAIL", "")
        self.gmail = GmailConfig(
            google_client_id=os.getenv("FA_GOOGLE_CLIENT_ID_GMAIL", ""),
            google_client_secret=os.getenv("FA_GOOGLE_CLIENT_SECRET_GMAIL", ""),
            google_refresh_token=os.getenv("FA_GOOGLE_REFRESH_TOKEN_GMAIL", ""),
            sender_email=os.getenv("FA_GMAIL_SENDER_EMAIL", ""),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
