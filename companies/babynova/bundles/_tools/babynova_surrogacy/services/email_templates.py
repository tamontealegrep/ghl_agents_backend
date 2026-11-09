"""Renders this plugin's e-mail templates (``templates/emails``); the logic lives in ``agent_backend.email_templates``."""

from pathlib import Path

from agent_backend.email_templates import render_template_file

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "emails"


def render_email_template(template_name: str, **variables: str) -> str:
    """Renders ``templates/emails/<template_name>.html``.

    Args:
        template_name: File name without ``.html``.
        **variables: Values for the template variables.

    Returns:
        The rendered HTML.
    """
    return render_template_file(TEMPLATES_DIR, template_name, **variables)
