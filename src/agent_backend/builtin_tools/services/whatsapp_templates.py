"""The text a contact's conversation shows for a WhatsApp template sent through the API.

Every company keeps the text of its templates in its own ``whatsapp_templates.yaml``, in its ``shared/`` folder
(``companies/<company>/shared/whatsapp_templates.yaml``); the backend of a company reads only that file.
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml

TEMPLATES_FILE_NAME = "whatsapp_templates.yaml"
TEMPLATES_FILE_ENV = "WHATSAPP_TEMPLATES_FILE"
_VARIABLE = re.compile(r"\{\{\s*(\d+)\s*\}\}")
_cache: dict[Path, tuple[float, dict[tuple[str, str], str]]] = {}


def company_templates_file(settings: Any) -> Path | None:
    """The file with the templates of the company this backend serves.

    It is ``whatsapp_templates.yaml`` in the ``shared/`` folder next to ``bundles/`` (``settings.agents_dir``),
    which the Docker image and docker-compose already carry; ``WHATSAPP_TEMPLATES_FILE`` replaces it. ``None`` when the app has no settings (a bare test app).
    """
    override = os.getenv(TEMPLATES_FILE_ENV, "").strip()
    if override:
        return Path(override)
    agents_dir = getattr(settings, "agents_dir", None)
    return Path(agents_dir).resolve().parent / "shared" / TEMPLATES_FILE_NAME if agents_dir else None


def _bodies(templates_file: Path | None) -> dict[tuple[str, str], str]:
    """The known templates of a file: ``{(name, language): body}``; empty when it is missing or unreadable.

    The file is read again when it changes, so editing a text does not need a restart.
    """
    if templates_file is None:
        return {}
    try:
        modified = templates_file.stat().st_mtime
    except OSError:
        return {}
    cached = _cache.get(templates_file)
    if cached and cached[0] == modified:
        return cached[1]
    try:
        loaded: Any = yaml.safe_load(templates_file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    bodies: dict[tuple[str, str], str] = {}
    for entry in loaded.get("templates") or []:
        name, language, body = (str(entry.get(key) or "").strip() for key in ("name", "language", "body"))
        if name and language and body:
            bodies[(name.lower(), language.lower())] = body
    _cache[templates_file] = (modified, bodies)
    return bodies


def fallback_message(name: str) -> str:
    """What the conversation shows for a template whose text is not known."""
    return f"[WhatsApp template: {name.strip()}]"


def visible_message(
    name: str, language: str, body_variables: list[str], templates_file: Path | None = None
) -> str:
    """The text of a template with its variables filled in, as the advisors read it in the conversation.

    Args:
        name: Name of the template in GHL.
        language: Language code of that template (``es``, ``en_US``).
        body_variables: Values of the body variables, in order: the first one is ``{{1}}``.
        templates_file: The company's ``whatsapp_templates.yaml``.

    Returns:
        The body of the template with ``{{1}}``, ``{{2}}``... replaced by their values; a variable with no value stays as
        written. When the template is not listed, ``[WhatsApp template: <name>]``.
    """
    body = _bodies(templates_file).get((name.strip().lower(), language.strip().lower()))
    if body is None:
        return fallback_message(name)

    def value(match: re.Match[str]) -> str:
        index = int(match.group(1)) - 1
        return body_variables[index] if 0 <= index < len(body_variables) else match.group(0)

    return _VARIABLE.sub(value, body)
