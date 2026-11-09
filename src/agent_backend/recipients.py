"""Parsing of e-mail address lists taken from environment variables."""

from __future__ import annotations

import re

__all__ = ["split_recipients"]

_SEPARATORS = re.compile(r"[,;\s]+")
_ADDRESS = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def split_recipients(raw: str | None) -> tuple[list[str], list[str]]:
    """Splits a ``*_NOTIFICATION_EMAIL`` value into addresses.

    Args:
        raw: Value of the variable: one or several addresses separated by commas,
            semicolons or whitespace. May be empty or None.

    Returns:
        ``(valid, invalid)``: the well-formed addresses without duplicates, in the
        order given, and the entries that do not look like an address. Both are
        empty when the variable is empty.
    """
    valid: list[str] = []
    invalid: list[str] = []
    for item in _SEPARATORS.split((raw or "").strip()):
        if not item:
            continue
        if not _ADDRESS.match(item):
            invalid.append(item)
        elif item.lower() not in {v.lower() for v in valid}:
            valid.append(item)
    return valid, invalid
