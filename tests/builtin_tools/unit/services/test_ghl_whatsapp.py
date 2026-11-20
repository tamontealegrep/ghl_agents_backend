"""send_whatsapp_template and send_whatsapp_file: WhatsApp messages through POST /conversations/messages."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agent_backend.builtin_tools.services.ghl_whatsapp import (
    file_name_for,
    media_type_for,
    normalize_variables,
    send_whatsapp_file_service,
    send_whatsapp_template_service,
)
from tests.builtin_tools.app_factory import app


@pytest.fixture(autouse=True)
def _message_created(ghl):
    ghl["reply"] = lambda request: httpx.Response(201, json={"conversationId": "conv1", "messageId": "msg1"})


def _sent(ghl):
    (request,) = ghl["requests"]
    return request, json.loads(request.content)


def test_the_template_goes_the_way_ghls_own_app_sends_it(ghl):
    result = asyncio.run(
        send_whatsapp_template_service(
            " contact1 ",
            " sam_fc_es ",
            " es ",
            "loc1",
            body_variables=["{{contact.first_name}}"],
            from_number_id="1293987563797889",
            to_number="+573215616921",
        )
    )

    assert result == {"success": True, "message_id": "msg1", "conversation_id": "conv1"}
    request, body = _sent(ghl)
    assert request.method == "POST" and str(request.url) == "https://ghl.test/conversations/messages"
    assert request.headers["Authorization"] == "Bearer tok-123" and request.headers["Version"] == "v3"
    assert body == {
        "type": "WhatsApp",
        "contactId": "contact1",
        "message": ".",
        "whatsapp": {
            "type": "template",
            "template": {"name": "sam_fc_es", "lang": "es", "category": "UTILITY"},
            "placeholders": {"header": [], "body": ["{{contact.first_name}}"]},
            "fromNumberId": "1293987563797889",
            "toNumber": "+573215616921",
        },
    }
    assert ghl["locations"] == ["loc1"]  # the location picks the token


def test_the_optional_numbers_are_left_out_when_not_given(ghl):
    asyncio.run(send_whatsapp_template_service("c", "sam_fc_en", "en_US", category="marketing"))

    body = _sent(ghl)[1]
    assert body["whatsapp"] == {
        "type": "template",
        "template": {"name": "sam_fc_en", "lang": "en_US", "category": "MARKETING"},
        "placeholders": {"header": [], "body": []},
    }
    assert body["message"] == "."  # GHL refuses a message with no content; the contact gets the template


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, []),
        ("", []),
        (["a", "b"], ["a", "b"]),
        ('["a", "b"]', ["a", "b"]),
        ("a, b ,", ["a", "b"]),
        ("{{contact.first_name}}", ["{{contact.first_name}}"]),
        ([1, "b"], ["1", "b"]),
    ],
)
def test_the_variables_are_a_list_of_texts_whatever_their_shape(raw, expected):
    assert normalize_variables(raw) == expected


@pytest.mark.parametrize(
    ("contact", "name", "language"), [("", "t", "es"), ("  ", "t", "es"), ("c", "", "es"), ("c", "t", " ")]
)
def test_a_template_without_contact_name_or_language_never_reaches_ghl(ghl, contact, name, language):
    result = asyncio.run(send_whatsapp_template_service(contact, name, language))

    assert result["success"] is False and "required" in result["errors"]
    assert ghl["requests"] == []


def test_the_file_goes_as_whatsapp_media_with_the_name_from_the_url(ghl):
    result = asyncio.run(
        send_whatsapp_file_service("contact1", "https://files.test/docs/Gu%C3%ADa%20FIV.pdf", location_id="loc1")
    )

    assert result == {"success": True, "message_id": "msg1", "conversation_id": "conv1"}
    _, body = _sent(ghl)
    assert body == {
        "type": "WhatsApp",
        "contactId": "contact1",
        "status": "pending",
        "whatsapp": {
            "type": "media",
            "media": {"type": "document", "url": "https://files.test/docs/Gu%C3%ADa%20FIV.pdf", "name": "Guía FIV.pdf"},
        },
    }


def test_a_caption_and_an_explicit_type_and_name_are_used_as_given(ghl):
    asyncio.run(
        send_whatsapp_file_service(
            "c", "https://files.test/x", file_type=" IMAGE ", file_name="Foto.png", message=" Mira ", from_number="+57"
        )
    )

    body = _sent(ghl)[1]
    assert body["whatsapp"]["media"] == {"type": "image", "url": "https://files.test/x", "name": "Foto.png"}
    assert body["message"] == "Mira" and body["fromNumber"] == "+57"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x.test/a.JPG", "image"),
        ("https://x.test/a.png?token=1", "image"),
        ("https://x.test/a.mp4", "video"),
        ("https://x.test/a.ogg", "audio"),
        ("https://x.test/a.pdf", "document"),
        ("https://x.test/a.xlsx", "document"),
        ("https://x.test/a.unknown", "document"),
        ("https://x.test/no-extension", "document"),
        ("https://x.test/v1.2/file", "document"),  # a dot in a folder is not an extension
    ],
)
def test_the_kind_of_file_is_deduced_from_the_extension(url, expected):
    assert media_type_for(url) == expected


def test_a_file_type_that_is_not_one_of_the_four_is_refused(ghl):
    result = asyncio.run(send_whatsapp_file_service("c", "https://x.test/a.pdf", file_type="sticker"))

    assert result["success"] is False and "image, video, audio, document" in result["errors"]
    assert ghl["requests"] == []


@pytest.mark.parametrize("url", ["", "  ", "ftp://x.test/a.pdf", "/local/a.pdf", "file:///a.pdf", "https://"])
def test_only_a_public_http_url_is_sent(ghl, url):
    result = asyncio.run(send_whatsapp_file_service("c", url))

    assert result["success"] is False and "public http" in result["errors"]
    assert ghl["requests"] == []


def test_a_file_without_contact_never_reaches_ghl(ghl):
    assert asyncio.run(send_whatsapp_file_service(" ", "https://x.test/a.pdf"))["success"] is False
    assert ghl["requests"] == []


@pytest.mark.parametrize(
    ("url", "given", "expected"),
    [
        ("https://x.test/a/b.pdf", None, "b.pdf"),
        ("https://x.test/", None, "file"),
        ("https://x.test/a/b.pdf", " Mi archivo.pdf ", "Mi archivo.pdf"),
    ],
)
def test_the_file_name(url, given, expected):
    assert file_name_for(url, given) == expected


def test_a_ghl_refusal_comes_back_as_data(ghl):
    ghl["reply"] = lambda request: httpx.Response(422, json={"message": "template not approved"})

    for result in (
        asyncio.run(send_whatsapp_template_service("c", "t", "es")),
        asyncio.run(send_whatsapp_file_service("c", "https://x.test/a.pdf")),
    ):
        assert result["success"] is False
        assert "422" in result["errors"] and "template not approved" in result["errors"]


def test_both_tools_are_reachable_with_snake_or_camel_names(ghl):
    client = TestClient(app)

    template = client.post("/api/v1/send-whatsapp-template", json={"contact_id": "c1", "template_name": "t1", "language": "es", "body_variables": "Ana, 5", "location_id": "loc1"})
    file = client.post("/api/v1/send-whatsapp-file", json={"contactId": "c1", "fileUrl": "https://x.test/a.png", "locationId": "loc1"})

    assert template.status_code == 200 and template.json()["message_id"] == "msg1"
    assert json.loads(ghl["requests"][0].content)["whatsapp"]["placeholders"]["body"] == ["Ana", "5"]
    assert file.status_code == 200 and file.json() == {
        "success": True, "message_id": "msg1", "conversation_id": "conv1", "errors": None,
    }
    assert json.loads(ghl["requests"][1].content)["whatsapp"]["media"]["type"] == "image"
