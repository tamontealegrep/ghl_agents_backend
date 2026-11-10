"""
Module.

    Motor compartido por book-appointment-ivf y book-appointment-sur. Port de la
    parte de "code_01" que es común a los dos nodos GHL: parseo/validación de
    fecha, formateo del nombre de contacto, validación de email e idioma. Lo que
    cada tool aporta por su cuenta (nombre del agente, calendario, validador de
    horario laboral, templates de correo) vive en services/booking_ivf.py y
    services/booking_sur.py.

    No sabe nada de HTTP ni de Google.
"""

import re

from agent_backend.booking_helpers import compute_end_date, format_contact_name, is_future, parse_start_date  # noqa: F401
from agent_backend.booking_helpers import parse_duration_minutes as _parse_duration_minutes


def parse_duration_minutes(raw: str | None, default: int = 20) -> int:
    """Reads a duration in minutes; 20 when it is missing or not positive."""
    return _parse_duration_minutes(raw, default)


_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
_LEADING_INT_RE = re.compile(r"^\s*(-?\d+)")

EMAIL_SUBJECTS = {
    "ES": "🎉 ¡Cita confirmada! Detalles de tu consulta con Family Aims",
    "EN": "🎉 Appointment Confirmed! Details for your consultation with Family Aims",
    "PT": "🎉 Consulta confirmada! Detalhes da sua consulta com a Family Aims",
}

# Descripción del evento de Calendar: igual para ambos tools en el JSON
# original de GHL (bilingüe EN/ES fijo, sin importar el idioma solicitado
# para el correo — así estaba, no se cambia).
EVENT_DESCRIPTION_TEMPLATE = (
    "This consultation will allow us to better understand your situation, expectations, and "
    "family-building goals so we can identify the fertility treatment or program that best "
    "fits your needs. It is also an opportunity to answer your questions and provide "
    "personalized guidance throughout the process. Your attendance is essential for us to "
    "recommend the best path toward achieving your family-building goals.\n\n"
    "Esta cita nos permitira conocer tu caso, expectativas y objetivos para ayudarte a "
    "identificar el tratamiento o programa de fertilidad que mejor se adapte a tus "
    "necesidades. Tambien sera una oportunidad para resolver tus dudas y brindarte "
    "orientacion personalizada en cada paso del proceso. Tu asistencia es fundamental para "
    "ofrecerte la mejor alternativa para construir tu familia.\n\n"
    "Name: {name}\nEmail: {email}\nPhone: {phone}"
)


def format_event_description(name: str, email: str, phone: str) -> str:
    return EVENT_DESCRIPTION_TEMPLATE.format(name=name, email=email, phone=phone)


def normalize_email(raw_email: str) -> str:
    return raw_email.strip().lower()


def is_valid_email(raw_email: str) -> bool:
    email = normalize_email(raw_email)
    if not _EMAIL_RE.match(email):
        return False
    if "@example." in email:
        return False
    return True


def normalize_language(raw_language: str) -> str:
    """ES o PT si vienen explícitos; cualquier otra cosa cae a inglés (igual que el JS original, que solo distinguía ES vs "todo lo demás")."""
    lang = (raw_language or "").strip().upper()
    return lang if lang in ("ES", "PT") else "EN"
