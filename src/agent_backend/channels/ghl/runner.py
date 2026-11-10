"""Execution ids of webhook turns."""

import hashlib

from agent_backend.channels.ghl.request import GhlAgentRequest


def derive_execution_id(request: GhlAgentRequest, prefix: str) -> str:
    """Builds the id that tells one delivered message from a repeat of it.

    The id is the message id when GHL sends one. Without it, the id is a fingerprint of the conversation (or
    contact), the location and the text: two different messages of the same conversation must not share an id, or the
    second would be dropped as a duplicate; the same text delivered twice still is.

    Args:
        request: The webhook payload.
        prefix: Agent slug, to keep ids of different agents apart.

    Returns:
        The execution id.
    """
    if request.messageId:
        return request.messageId

    where = request.conversation_id or request.contact_id
    fingerprint_source = f"{where}|{request.location_id or ''}|{request.message or ''}"
    fingerprint = hashlib.sha1(fingerprint_source.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{fingerprint}"
