"""Rendering of the HTML e-mail templates of a company plugin."""

from __future__ import annotations

from pathlib import Path
from string import Template

__all__ = ["render_template_file"]


def render_template_file(templates_dir: Path, template_name: str, **variables: str) -> str:
    """Reads ``<templates_dir>/<template_name>.html`` and substitutes its ``${...}`` variables.

    ``Template.substitute`` is used (not ``safe_substitute``): a missing variable must fail the request with a
    clear error instead of sending an e-mail with a visible ``${something}``.

    Args:
        templates_dir: Folder with the plugin's templates.
        template_name: File name without ``.html``.
        **variables: Values for the template variables.

    Returns:
        The rendered HTML.

    Raises:
        FileNotFoundError: The template does not exist.
        KeyError: The template uses a variable that was not given.
    """
    content = (Path(templates_dir) / f"{template_name}.html").read_text(encoding="utf-8")
    return Template(content).substitute(**variables)
