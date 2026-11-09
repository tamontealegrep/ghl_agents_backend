import hashlib

from agent_backend.channels.ghl.request import GhlAgentRequest


def derive_execution_id(request: GhlAgentRequest, prefix: str) -> str:
    if request.messageId:
        return request.messageId
    if request.conversation_id:
        return request.conversation_id

    fingerprint_source = f"{request.contact_id}|{request.location_id or ''}|{request.message or ''}"
    fingerprint = hashlib.sha1(fingerprint_source.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{fingerprint}"
