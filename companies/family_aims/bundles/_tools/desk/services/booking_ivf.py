"""
Module.

    Reglas propias de book-appointment-ivf (port del validador de horario del
    nodo "code_01" de book_appointment_ivf_api). Nota: esta ventana horaria NO
    es la misma que usa available-slots-ivf (esa abre a las 09:00 y bloquea el
    almuerzo de 12:00 a 13:30; esta abre a las 07:00 y bloquea solo la hora de
    las 12:00 a 12:59) — así estaba en los dos flujos originales de GHL, no es
    un error de este port. Ver SPEC.md §13 para la observación completa.
"""

AGENT_NAME = "Ayda"
EVENT_SUMMARY_TAG = "IVF"
EMAIL_TEMPLATE_PREFIX = "book_appointment_ivf"


def is_valid_business_hour(weekday: int, hour: int, minute: int) -> bool:
    """weekday: 0=Domingo..6=Sabado.

    Lunes a Viernes, 07:30-17:00, sin la hora del almuerzo (12:00-12:59).
    """
    if weekday in (0, 6):  # Domingo, Sabado
        return False
    if hour == 12:
        return False
    if weekday in (1, 2, 3, 4, 5):  # Lunes a Viernes
        if (hour, minute) < (7, 30):
            return False
        if hour > 17 or (hour == 17 and minute > 0):
            return False
        return True
    return False
