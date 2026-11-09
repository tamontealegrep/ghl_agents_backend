"""
Module.

    Reglas propias de available-slots-sur (port del nodo "code_02" de
    get_available_slots_surrogacy): ventana horaria, franja de almuerzo y hora
    de cierre del último día. La generación/formato de slots vive en slot_engine.py.
"""

from typing import Optional, Tuple
from ..core.config import load_slots_config


def day_window(weekday: int) -> Optional[Tuple[int, int, int, int]]:
    """Configuración de ventanas horarias desde YAML.
    """
    config = load_slots_config().get("policies", {}).get("sur", {})
    window = config.get("windows", {}).get(weekday)
    if window:
        return tuple(window)
    return None


def lunch_break(start_min: int, end_min: int) -> bool:
    """Excluye el slot si inicia dentro de la hora configurada (ej: 12:00-12:59).
    """
    config = load_slots_config().get("policies", {}).get("sur", {}).get("lunch_break", {})
    start_hour = config.get("start_hour", 12)
    end_hour = config.get("end_hour", 13)
    return start_hour * 60 <= start_min < end_hour * 60


def closing_hour(weekday: int) -> Tuple[int, int]:
    """El rango de búsqueda cierra a la hora de fin de la ventana configurada.
    """
    window = day_window(weekday)
    if window:
        return (window[2], window[3])
    # Fallback original
    return (14, 0) if weekday == 1 else (16, 0)
