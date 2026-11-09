"""GoHighLevel (GHL) HTTP client helpers: configuration, search and send."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from agent_backend.channels.ghl.text import normalize_channel

GHL_DEFAULTS_PATH = Path(__file__).resolve().parents[2] / "defaults" / "ghl_defaults.json"
DEFAULT_TOKEN_ENVS: tuple[str, ...] = ("GHL_TOKEN",)

GHL_OUTBOUND_CHANNEL_MAP: dict[str, str] = {
    "SMS": "SMS",
    "WHATSAPP": "WhatsApp",
    "IG": "IG",
    "INSTAGRAM": "IG",
    "EMAIL": "Email",
    "FACEBOOK": "FB",
    "GMB": "FB",
    "LIVE_CHAT": "Live_Chat",
}

GHL_FILTER_TYPE_MAP: dict[str, str] = {
    "CALL": "TYPE_CALL",
    "SMS": "TYPE_SMS",
    "WHATSAPP": "TYPE_WHATSAPP",
    "IG": "TYPE_INSTAGRAM",
    "INSTAGRAM": "TYPE_INSTAGRAM",
    "EMAIL": "TYPE_EMAIL",
    "FACEBOOK": "TYPE_FACEBOOK",
    "GMB": "TYPE_GMB",
    "VOICEMAIL": "TYPE_VOICEMAIL",
    "LIVE_CHAT": "TYPE_LIVE_CHAT",
}


@lru_cache(maxsize=1)
def load_ghl_defaults() -> dict[str, Any]:
    """Reads the packaged GHL defaults file once.

    Returns:
        The parsed ``defaults/ghl_defaults.json`` document.
    """
    return json.loads(GHL_DEFAULTS_PATH.read_text(encoding="utf-8"))


def _load_inbound_type_map() -> dict[Any, str]:
    """Builds the incoming ``message.type`` -> channel-name map.

    Numeric-looking keys (``"19"``) are turned back into ``int``: a real GHL
    payload carries those as JSON numbers, but JSON object keys are strings.

    Returns:
        Mapping from raw GHL message type to normalized channel name.
    """
    raw = load_ghl_defaults().get("inbound_type_map", {})
    return {(int(key) if key.isdigit() else key): value for key, value in raw.items() if key != "_note"}


GHL_INBOUND_TYPE_MAP: dict[Any, str] = _load_inbound_type_map()


@dataclass(frozen=True)
class GhlClientConfig:
    """Everything needed to call the GHL API for one sub-account.

    Attributes:
        base_url: API root, without trailing slash.
        version: Value of the ``Version`` header.
        token: Bearer token of the sub-account.
        message_history_page_size: Page size when reading history.
        conversation_search_limit: Max conversations returned by a search.
        history_timeout_seconds: Timeout for history requests.
        conversation_search_timeout_seconds: Timeout for conversation search.
        send_message_timeout_seconds: Timeout for sending a message.
        default_send_type: Channel used when the inbound one is unknown.
        channel_type_map: Normalized channel name -> GHL send type.
    """

    base_url: str
    version: str
    token: str
    message_history_page_size: int
    conversation_search_limit: int
    history_timeout_seconds: float
    conversation_search_timeout_seconds: float
    send_message_timeout_seconds: float
    default_send_type: str
    channel_type_map: dict[str, str]


def build_ghl_client_config(
    ghl_settings: dict[str, Any],
    runtime_settings: dict[str, Any],
    messaging_settings: dict[str, Any],
    token_envs: tuple[str, ...] = DEFAULT_TOKEN_ENVS,
) -> GhlClientConfig:
    """Resolves a ``GhlClientConfig`` from the defaults file plus environment.

    Args:
        ghl_settings: The ``ghl`` section of the defaults document.
        runtime_settings: The ``runtime`` section (timeouts).
        messaging_settings: The ``messaging`` section (channel map).
        token_envs: Environment variable names tried in order for the token.

    Returns:
        The resolved, immutable configuration.
    """
    timeouts = runtime_settings.get("timeouts", {})
    base_url_env = ghl_settings.get("base_url_env", "GHL_BASE_URL")
    version_env = ghl_settings.get("version_env", "GHL_VERSION")
    default_base_url = ghl_settings.get("default_base_url", "https://services.leadconnectorhq.com")
    return GhlClientConfig(
        base_url=os.getenv(base_url_env, default_base_url).rstrip("/"),
        version=os.getenv(version_env, ghl_settings.get("default_version", "v3")),
        token=next((v for v in (os.getenv(env, "").strip() for env in token_envs) if v), ""),
        message_history_page_size=int(ghl_settings.get("message_history_page_size", 100)),
        conversation_search_limit=int(ghl_settings.get("conversation_search_limit", 1)),
        history_timeout_seconds=float(timeouts.get("history_seconds", 60.0)),
        conversation_search_timeout_seconds=float(timeouts.get("conversation_search_seconds", 30.0)),
        send_message_timeout_seconds=float(timeouts.get("send_message_seconds", 30.0)),
        default_send_type=messaging_settings.get("default_send_type", "Live_Chat"),
        channel_type_map=messaging_settings.get("channel_type_map", GHL_OUTBOUND_CHANNEL_MAP),
    )


def ghl_client_config_for(token_envs: tuple[str, ...]) -> GhlClientConfig:
    """Builds the GHL config for an agent from its declared token variables.

    This replaces the per-vertical ``*_ghl_client_config`` functions: which
    sub-account an agent talks to is data in its ``agent.yaml``, not code.

    Args:
        token_envs: Environment variable names holding the agent's token.

    Returns:
        The resolved configuration.
    """
    raw = load_ghl_defaults()
    return build_ghl_client_config(
        raw.get("ghl", {}), raw.get("runtime", {}), raw.get("messaging", {}), token_envs=token_envs
    )


LOCATION_TOKEN_ENVS_VAR = "GHL_LOCATION_TOKEN_ENVS"


def ghl_client_config_for_location(location_id: str | None) -> GhlClientConfig:
    """Picks the GHL config whose token owns ``location_id``.

    A location id is only valid for its own sub-account's token. Which token
    belongs to which location is deployment data, declared in
    ``GHL_LOCATION_TOKEN_ENVS`` as ``<location_id>:<TOKEN_ENV_VAR>`` pairs
    separated by commas; any other location uses ``DEFAULT_TOKEN_ENVS``.

    Args:
        location_id: The GHL location id the call targets, if any.

    Returns:
        The resolved configuration.
    """
    pairs = (item.split(":", 1) for item in os.getenv(LOCATION_TOKEN_ENVS_VAR, "").split(",") if ":" in item)
    by_location = {loc.strip(): env.strip() for loc, env in pairs}
    token_env = by_location.get(location_id or "")
    return ghl_client_config_for((token_env,) if token_env else DEFAULT_TOKEN_ENVS)


def get_ghl_headers(config: GhlClientConfig) -> dict[str, str]:
    """Builds the auth headers for a GHL request.

    Args:
        config: Client configuration carrying the token and API version.

    Returns:
        Header mapping ready for ``httpx``.
    """
    return {
        "Authorization": f"Bearer {config.token}",
        "Version": config.version,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def search_conversation_async(
    contact_id: str,
    location_id: str,
    config: GhlClientConfig,
    logger: logging.Logger | None = None,
) -> str | None:
    active_logger = logger or logging.getLogger(__name__)
    url = (
        f"{config.base_url}/conversations/search?locationId={location_id}"
        f"&contactId={contact_id}&sort=desc&limit={config.conversation_search_limit}"
    )
    headers = get_ghl_headers(config)
    active_logger.info("Searching conversation for contact_id=%s location_id=%s", contact_id, location_id)

    async with httpx.AsyncClient(timeout=config.conversation_search_timeout_seconds) as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            conversations = response.json().get("conversations", [])
            if conversations:
                active_logger.info("Found %s conversation(s) for contact_id=%s", len(conversations), contact_id)
                return conversations[0].get("id")
        except Exception as exc:
            active_logger.error("Error searching conversation: %s", exc)
    return None


async def search_conversation_channel_async(
    contact_id: str,
    location_id: str,
    config: GhlClientConfig,
    logger: logging.Logger | None = None,
) -> str | None:
    """
    Channel (normalized, e.g. 'WHATSAPP') of the contact's most recent conversation, read from its
    lastMessageType, or None when there is no conversation or its last message is not on a
    channel a reply can be sent through.
    """
    active_logger = logger or logging.getLogger(__name__)
    url = (
        f"{config.base_url}/conversations/search?locationId={location_id}"
        f"&contactId={contact_id}&sort=desc&limit=1"
    )
    async with httpx.AsyncClient(timeout=config.conversation_search_timeout_seconds) as client:
        try:
            response = await client.get(url, headers=get_ghl_headers(config))
            response.raise_for_status()
            conversations = response.json().get("conversations", [])
        except Exception as exc:
            active_logger.error("Error looking up the conversation channel: %s", exc)
            return None
    if not conversations:
        return None
    channel = GHL_INBOUND_TYPE_MAP.get(conversations[0].get("lastMessageType"))
    return channel if normalize_channel(channel) in config.channel_type_map else None


async def send_ghl_message_async(
    contact_id: str,
    message: str,
    channel: str | None,
    exec_id: str,
    config: GhlClientConfig,
    location_id: str | None = None,
    reply_message_id: str | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    active_logger = logger or logging.getLogger(__name__)
    send_type = config.channel_type_map.get(normalize_channel(channel), config.default_send_type)
    payload = {
        "contactId": contact_id,
        "type": send_type,
        "message": message,
        "status": "pending",
    }
    if location_id:
        payload["locationId"] = location_id
    if reply_message_id:
        payload["replyMessageId"] = reply_message_id

    url = f"{config.base_url}/conversations/messages"

    active_logger.info(
        "[%s] Sending outbound GHL message: contact_id=%s channel=%s mapped_type=%s size_chars=%s location_id=%s",
        exec_id,
        contact_id,
        channel,
        send_type,
        len(message or ""),
        location_id,
    )

    async with httpx.AsyncClient(timeout=config.send_message_timeout_seconds) as client:
        try:
            response = await client.post(url, json=payload, headers=get_ghl_headers(config))
            response.raise_for_status()
            body = response.json()
            active_logger.info("[%s] GHL outbound message accepted.", exec_id)
            return body
        except httpx.HTTPStatusError as exc:
            # Log detalle del error para diagnosticar 4xx/5xx (sin incluir el token)
            status = exc.response.status_code if exc.response is not None else None
            text = exc.response.text if exc.response is not None else ""
            canonical = None
            try:
                canonical = (exc.response.json() if exc.response is not None else {}).get("canonicalCode")
            except Exception:
                canonical = None

            msg = (
                f"[{exec_id}] GHL send {'failed' if status and status >= 500 else 'rejected'}: "
                f"{status} {exc.request.url if exc.request is not None else url} | "
                f"type={payload.get('type')} len={len(payload.get('message') or '')} canonical={canonical} | body={text[:1000]}"
            )

            if status == 400 and canonical == "CONVERSATIONS_CONTACT_NOT_FOUND":
                # Downgrade noisy, expected case in closing sweep
                active_logger.warning(msg)
            else:
                active_logger.error(msg)
            raise
