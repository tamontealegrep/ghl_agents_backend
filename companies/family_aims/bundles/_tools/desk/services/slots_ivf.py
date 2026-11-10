"""
Module.

    Reglas propias de available-slots-ivf (port del nodo "code_02" de
    get_available_slots_ivf): ventana horaria, franja de almuerzo y hora de
    cierre del último día. La generación/formato de slots vive en slot_engine.py.
"""

from typing import Optional, Tuple
from ..core.config import load_slots_config


def day_window(weekday: int) -> Optional[Tuple[int, int, int, int]]:
    """Lunes a Viernes, 07:00-17:00, unificado desde YAML.
    """
    config = load_slots_config().get("policies", {}).get("ivf", {})
    window = config.get("windows", {}).get(weekday)
    if window:
        return tuple(window)
    return None


def lunch_break(start_min: int, end_min: int) -> bool:
    """Excluye el slot si se solapa con la franja de almuerzo configurada (ej: 12:00-13:00).

    Un slot que empieza antes y termina despues de que arranque el almuerzo tambien se excluye; el que termina
    justo cuando empieza el almuerzo, o empieza justo cuando termina, no. Un almuerzo sin duracion no excluye nada.
    """
    config = load_slots_config().get("policies", {}).get("ivf", {}).get("lunch_break", {})
    lunch_start = config.get("start_hour", 12) * 60
    lunch_end = config.get("end_hour", 13) * 60
    return lunch_start < lunch_end and start_min < lunch_end and end_min > lunch_start


def closing_hour(weekday: int) -> Tuple[int, int]:
    """El rango de búsqueda cierra a la hora de fin de la ventana configurada.
    """
    window = day_window(weekday)
    if window:
        return (window[2], window[3])
    return (17, 0)  # Default fallback
