"""WhatsApp messages sent through GoHighLevel (``POST /conversations/messages``): an approved template, or a file."""

import json
from typing import Any
from urllib.parse import unquote, urlparse

from agent_backend.builtin_tools.services.ghl_http import ghl_call

MEDIA_TYPES = ("image", "video", "audio", "document")
"""The kinds of file GHL's ``whatsapp.media.type`` accepts."""

_EXTENSION_TYPES = {
    **dict.fromkeys(("jpg", "jpeg", "png", "gif", "svg", "heic", "webp"), "image"),
    **dict.fromkeys(("mp4", "mpeg", "3gp", "mov"), "video"),
    **dict.fromkeys(("mp3", "wav", "wave", "aiff", "ogg", "opus", "aac", "m4a", "amr"), "audio"),
}
"""What the extension of a file says about its kind; anything else is sent as a document."""

DEFAULT_FILE_NAME = "file"


def media_type_for(file_url: str, file_type: str | None = None) -> str | None:
    """The kind of file to send: the one the agent named, else the one the extension of `file_url` suggests.

    Args:
        file_url: URL of the file.
        file_type: ``image``, ``video``, ``audio`` or ``document``, when the agent knows it.

    Returns:
        A value of ``MEDIA_TYPES``; ``None`` when `file_type` is given but is none of them.
    """
    if file_type and file_type.strip():
        chosen = file_type.strip().lower()
        return chosen if chosen in MEDIA_TYPES else None
    path = urlparse(file_url).path
    extension = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    return _EXTENSION_TYPES.get(extension, "document")


def file_name_for(file_url: str, file_name: str | None = None) -> str:
    """The name the recipient sees: the one given, else the last part of the URL path, else ``file``."""
    if file_name and file_name.strip():
        return file_name.strip()
    last = unquote(urlparse(file_url).path.rstrip("/").rsplit("/", 1)[-1]).strip()
    return last or DEFAULT_FILE_NAME


def _is_public_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


async def _send(body: dict[str, Any], location_id: str | None) -> dict[str, Any]:
    """Posts the message and turns GHL's answer into the tool's result; a failure is reported, never raised."""
    answer, error = await ghl_call("POST", "/conversations/messages", location_id=location_id, body=body)
    if error or answer is None:
        return {"success": False, "errors": error or "Empty response"}
    return {
        "success": True,
        "message_id": answer.get("messageId"),
        "conversation_id": answer.get("conversationId"),
    }


def _base_body(contact_id: str, from_number: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"type": "WhatsApp", "contactId": contact_id.strip(), "status": "pending"}
    if from_number and from_number.strip():
        body["fromNumber"] = from_number.strip()
    return body


TEMPLATE_MESSAGE = "."
"""What goes in `message` of a template. GHL refuses a message with no content, even when the template is named; the
contact receives the approved template (checked on WhatsApp), so the text only has to be something."""


def normalize_variables(raw: Any) -> list[str]:
    """The values of a template's variables as a list of texts: a list, or a JSON list or a comma separated text."""
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                loaded = json.loads(text)
            except ValueError:
                loaded = None
            if isinstance(loaded, list):
                return [str(item) for item in loaded]
        return [part.strip() for part in text.split(",") if part.strip()]
    return [str(item) for item in raw]


async def send_whatsapp_template_service(
    contact_id: str,
    template_name: str,
    language: str,
    location_id: str | None = None,
    body_variables: Any = None,
    header_variables: Any = None,
    category: str = "UTILITY",
    from_number_id: str | None = None,
    to_number: str | None = None,
) -> dict[str, Any]:
    """Sends an approved WhatsApp template to a contact, in the shape GHL's own web app sends it.

    GHL identifies a template by its name, language and category (not by the id its template list shows) and takes the
    values of its variables in ``whatsapp.placeholders``: ``["{{contact.first_name}}"]`` is resolved by GHL as a merge
    tag, any other text goes as written. That shape is the one GHL's web app posts to ``/conversations/messages``
    (minus the fields it was shown not to need: ``MessageType`` and, in a real test, the two numbers); the public page
    of the endpoint documents only media, so it can change without notice. The call needs the
    ``conversations/message.write`` scope on the token of the contact's location.

    Args:
        contact_id: GHL id of the contact.
        template_name: Name of the template in GHL (``sam_fc_es``).
        language: Language code of that template (``es``, ``en_US``, ``pt_BR``).
        location_id: GHL location (sub-account) of the contact: it picks the token that owns it.
        body_variables: Values of the body variables, in order (a list, a JSON list or a comma separated text).
        header_variables: Values of the header variables, in order; usually none.
        category: Category of the template (``UTILITY``, ``MARKETING``, ``AUTHENTICATION``).
        from_number_id: Id of the WhatsApp number to send from (``whatsapp.fromNumberId``); GHL's default when missing.
        to_number: The contact's WhatsApp number in international format; GHL's own record when missing.

    Returns:
        ``success``; on success ``message_id`` and ``conversation_id``; on failure ``errors`` with the reason.
    """
    if not (contact_id or "").strip():
        return {"success": False, "errors": "contact_id is required"}
    if not (template_name or "").strip():
        return {"success": False, "errors": "template_name is required"}
    if not (language or "").strip():
        return {"success": False, "errors": "language is required"}
    whatsapp: dict[str, Any] = {
        "type": "template",
        "template": {
            "name": template_name.strip(),
            "lang": language.strip(),
            "category": (category or "UTILITY").strip().upper(),
        },
        "placeholders": {"header": normalize_variables(header_variables), "body": normalize_variables(body_variables)},
    }
    if from_number_id and from_number_id.strip():
        whatsapp["fromNumberId"] = from_number_id.strip()
    if to_number and to_number.strip():
        whatsapp["toNumber"] = to_number.strip()
    body: dict[str, Any] = {
        "type": "WhatsApp",
        "contactId": contact_id.strip(),
        "message": TEMPLATE_MESSAGE,
        "whatsapp": whatsapp,
    }
    return await _send(body, location_id)


async def send_whatsapp_file_service(
    contact_id: str,
    file_url: str,
    file_type: str | None = None,
    file_name: str | None = None,
    message: str | None = None,
    location_id: str | None = None,
    from_number: str | None = None,
) -> dict[str, Any]:
    """Sends a file (image, video, audio or document) to a contact on WhatsApp.

    The file is sent by URL, so the URL must be reachable from outside. GHL documents a 5 MB limit and the file types
    its upload accepts; that page does not say what WhatsApp itself allows, so an oversize or unsupported file comes
    back as GHL's error. Free-form messages only reach a contact who wrote in the last 24 hours.

    Args:
        contact_id: GHL id of the contact.
        file_url: Public ``http(s)`` URL of the file.
        file_type: ``image``, ``video``, ``audio`` or ``document``; deduced from the extension when missing.
        file_name: Name the recipient sees; taken from the URL when missing.
        message: Text that goes with the file, if any.
        location_id: GHL location (sub-account) of the contact: it picks the token that owns it.
        from_number: WhatsApp number to send from, when the location has several.

    Returns:
        ``success``; on success ``message_id`` and ``conversation_id``; on failure ``errors`` with the reason.
    """
    if not (contact_id or "").strip():
        return {"success": False, "errors": "contact_id is required"}
    url = (file_url or "").strip()
    if not _is_public_url(url):
        return {"success": False, "errors": "file_url must be a public http or https URL"}
    media_type = media_type_for(url, file_type)
    if media_type is None:
        return {"success": False, "errors": f"file_type must be one of: {', '.join(MEDIA_TYPES)}"}
    body = _base_body(contact_id, from_number)
    body["whatsapp"] = {
        "type": "media",
        "media": {"type": media_type, "url": url, "name": file_name_for(url, file_name)},
    }
    if message and message.strip():
        body["message"] = message.strip()
    return await _send(body, location_id)
