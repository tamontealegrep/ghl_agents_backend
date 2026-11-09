"""
Module.

    Reglas propias de book-appointment-sur (port del validador de horario del
    nodo "code_01" de book_appointment_surrogacy_api). El bloqueo de almuerzo
    (12:00-12:59) coincide con available-slots-sur — unificado a pedido del
    owner, 2026-08-26. Ver SPEC.md §13.
"""

AGENT_NAME = "Marcela"
EVENT_SUMMARY_TAG = "SUR"
EMAIL_TEMPLATE_PREFIX = "book_appointment_sur"


def is_valid_business_hour(weekday: int, hour: int, minute: int) -> bool:
    """weekday: 0=Domingo..6=Sabado.

    Lunes 07:00-14:00; Martes a Viernes 07:00-16:00; sin la hora del almuerzo (12:00-12:59).
    """
    if weekday in (0, 6):  # Domingo, Sabado
        return False
    if hour == 12:
        return False
    if weekday == 1:  # Lunes
        if hour < 7:
            return False
        if hour > 14 or (hour == 14 and minute > 0):
            return False
        return True
    if weekday in (2, 3, 4, 5):  # Martes a Viernes
        if hour < 7:
            return False
        if hour > 16 or (hour == 16 and minute > 0):
            return False
        return True
    return False
