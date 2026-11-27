"""send_whatsapp_template and send_whatsapp_file: WhatsApp messages through POST /conversations/messages."""

import asyncio
import json
import os
from pathlib import Path

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


def test_template_sent_like_ghl_app(ghl):
    """The template is sent the same way GHL's own app sends it."""
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
        "message": "[WhatsApp template: sam_fc_es]",  # not listed: the chat names the template
        "whatsapp": {
            "type": "template",
            "template": {"name": "sam_fc_es", "lang": "es", "category": "UTILITY"},
            "placeholders": {"header": [], "body": ["{{contact.first_name}}"]},
            "fromNumberId": "1293987563797889",
            "toNumber": "+573215616921",
        },
    }
    assert ghl["locations"] == ["loc1"]  # the location picks the token


def test_optional_numbers_left_out(ghl):
    """Optional phone numbers are left out when not given."""
    asyncio.run(send_whatsapp_template_service("c", "sam_fc_en", "en_US", category="marketing"))

    body = _sent(ghl)[1]
    assert body["whatsapp"] == {
        "type": "template",
        "template": {"name": "sam_fc_en", "lang": "en_US", "category": "MARKETING"},
        "placeholders": {"header": [], "body": []},
    }
    assert body["message"] == "[WhatsApp template: sam_fc_en]"  # GHL refuses an empty message


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
def test_variables_are_text_list(raw, expected):
    """Template variables are normalised to a list of texts."""
    assert normalize_variables(raw) == expected


@pytest.mark.parametrize(
    ("contact", "name", "language"), [("", "t", "es"), ("  ", "t", "es"), ("c", "", "es"), ("c", "t", " ")]
)
def test_template_missing_input_skips_ghl(ghl, contact, name, language):
    """A template without contact, name or language never reaches GHL."""
    result = asyncio.run(send_whatsapp_template_service(contact, name, language))

    assert result["success"] is False and "required" in result["errors"]
    assert ghl["requests"] == []


def test_file_sent_as_media(ghl):
    """A file is sent as WhatsApp media named from its URL."""
    result = asyncio.run(
        send_whatsapp_file_service(
            "contact1", "https://files.test/docs/Gu%C3%ADa%20FIV.pdf", location_id="loc1"
        )
    )

    assert result == {"success": True, "message_id": "msg1", "conversation_id": "conv1"}
    _, body = _sent(ghl)
    assert body == {
        "type": "WhatsApp",
        "contactId": "contact1",
        "status": "pending",
        "whatsapp": {
            "type": "media",
            "media": {
                "type": "document",
                "url": "https://files.test/docs/Gu%C3%ADa%20FIV.pdf",
                "name": "Guía FIV.pdf",
            },
        },
    }


def test_file_caption_type_name(ghl):
    """A caption, type and name given explicitly are used as is."""
    asyncio.run(
        send_whatsapp_file_service(
            "c",
            "https://files.test/x",
            file_type=" IMAGE ",
            file_name="Foto.png",
            message=" Mira ",
            from_number="+57",
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
def test_file_type_from_extension(url, expected):
    """The media type is deduced from the file extension."""
    assert media_type_for(url) == expected


def test_unknown_file_type_refused(ghl):
    """A type outside image, video, audio and document is refused."""
    result = asyncio.run(send_whatsapp_file_service("c", "https://x.test/a.pdf", file_type="sticker"))

    assert result["success"] is False and "image, video, audio, document" in result["errors"]
    assert ghl["requests"] == []


@pytest.mark.parametrize("url", ["", "  ", "ftp://x.test/a.pdf", "/local/a.pdf", "file:///a.pdf", "https://"])
def test_only_a_public_http_url_is_sent(ghl, url):
    """Only a public http(s) URL is accepted."""
    result = asyncio.run(send_whatsapp_file_service("c", url))

    assert result["success"] is False and "public http" in result["errors"]
    assert ghl["requests"] == []


def test_file_without_contact_skips_ghl(ghl):
    """A file without a contact never reaches GHL."""
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
    """The file name comes from the given name or from the URL."""
    assert file_name_for(url, given) == expected


def test_ghl_refusal_is_data(ghl):
    """A GHL refusal is returned as data."""
    ghl["reply"] = lambda request: httpx.Response(422, json={"message": "template not approved"})

    for result in (
        asyncio.run(send_whatsapp_template_service("c", "t", "es")),
        asyncio.run(send_whatsapp_file_service("c", "https://x.test/a.pdf")),
    ):
        assert result["success"] is False
        assert "422" in result["errors"] and "template not approved" in result["errors"]


def test_tools_accept_snake_or_camel(ghl):
    """Both tools are reachable with snake_case or camelCase names."""
    client = TestClient(app)

    template = client.post(
        "/api/v1/send-whatsapp-template",
        json={
            "contact_id": "c1",
            "template_name": "t1",
            "language": "es",
            "body_variables": "Ana, 5",
            "location_id": "loc1",
        },
    )
    file = client.post(
        "/api/v1/send-whatsapp-file",
        json={"contactId": "c1", "fileUrl": "https://x.test/a.png", "locationId": "loc1"},
    )

    assert template.status_code == 200 and template.json()["message_id"] == "msg1"
    assert json.loads(ghl["requests"][0].content)["whatsapp"]["placeholders"]["body"] == ["Ana", "5"]
    assert file.status_code == 200 and file.json() == {
        "success": True,
        "message_id": "msg1",
        "conversation_id": "conv1",
        "errors": None,
    }
    assert json.loads(ghl["requests"][1].content)["whatsapp"]["media"]["type"] == "image"


COMPANIES = Path(__file__).resolve().parents[4] / "companies"
BABYNOVA_FILE = COMPANIES / "babynova" / "shared" / "whatsapp_templates.yaml"
FAMILY_AIMS_FILE = COMPANIES / "family_aims" / "shared" / "whatsapp_templates.yaml"


def _file(tmp_path, name="whatsapp_templates.yaml", body="Hola {{1}}, tu cita es el {{2}}."):
    path = tmp_path / name
    path.write_text(f"templates:\n  - name: sofia_booking\n    language: es\n    body: |-\n      {body}\n", encoding="utf-8")
    return path


def test_a_known_template_shows_its_text_with_the_variables(ghl, tmp_path):
    """The conversation shows the text of the template with its variables filled in, not a placeholder."""
    asyncio.run(
        send_whatsapp_template_service(
            "c",
            "sofia_booking",
            "es",
            "loc1",
            body_variables=["Lunes, 30 de NOVIEMBRE de 2026", "09:10 a.m"],
            templates_file=BABYNOVA_FILE,
        )
    )

    message = _sent(ghl)[1]["message"]
    assert "📅 FECHA: Lunes, 30 de NOVIEMBRE de 2026." in message
    assert "⏰ HORA: 09:10 a.m. Te recomendamos llegar 15 minutos antes." in message
    assert "{{" not in message and message.startswith("🌸 ¡Nos alegra mucho")


def test_the_variables_sent_to_whatsapp_do_not_change(ghl):
    """The visible text is only for the conversation: the variables sent to WhatsApp are the same as ever."""
    asyncio.run(
        send_whatsapp_template_service(
            "c", "sofia_booking", "es", body_variables=["a, b", "c"], templates_file=BABYNOVA_FILE
        )
    )

    assert _sent(ghl)[1]["whatsapp"]["placeholders"] == {"header": [], "body": ["a, b", "c"]}


def test_a_missing_variable_stays_as_written(ghl):
    """A variable with no value is left as {{n}}: the message is never made up."""
    asyncio.run(
        send_whatsapp_template_service(
            "c", "sofia_booking", "es", body_variables=["only the date"], templates_file=BABYNOVA_FILE
        )
    )

    message = _sent(ghl)[1]["message"]
    assert "FECHA: only the date." in message and "HORA: {{2}}." in message


def test_the_template_is_found_whatever_the_case(ghl):
    """Name and language are compared without caring about case or spaces."""
    asyncio.run(
        send_whatsapp_template_service(
            "c", " SOFIA_BOOKING ", " ES ", body_variables=["d", "h"], templates_file=BABYNOVA_FILE
        )
    )

    assert "FECHA: d." in _sent(ghl)[1]["message"]


def test_a_template_that_is_not_in_the_file_shows_its_name(ghl):
    """Without a text for it, the chat names the template (never a bare dot)."""
    asyncio.run(send_whatsapp_template_service("c", "sam_fc_es", "es", templates_file=BABYNOVA_FILE))

    assert _sent(ghl)[1]["message"] == "[WhatsApp template: sam_fc_es]"


def test_each_company_has_its_own_templates(ghl, tmp_path):
    """The same template name shows the text of the company that sends it, never another's."""
    other = _file(tmp_path, body="Hi {{1}}, see you on {{2}}.")
    asyncio.run(
        send_whatsapp_template_service("c", "sofia_booking", "es", body_variables=["Ana", "Mon"], templates_file=other)
    )
    asyncio.run(
        send_whatsapp_template_service(
            "c", "sofia_booking", "es", body_variables=["d", "h"], templates_file=FAMILY_AIMS_FILE
        )
    )

    (_, first), (_, second) = (
        (request, json.loads(request.content)) for request in ghl["requests"]
    )
    assert first["message"] == "Hi Ana, see you on Mon."
    assert second["message"] == "[WhatsApp template: sofia_booking]"  # Family Aims has no such template


def test_a_changed_file_is_read_again(ghl, tmp_path):
    """Editing a text takes effect on the next message, without restarting the backend."""
    path = _file(tmp_path, body="before")
    asyncio.run(send_whatsapp_template_service("c", "sofia_booking", "es", templates_file=path))
    path.write_text(path.read_text(encoding="utf-8").replace("before", "after"), encoding="utf-8")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    asyncio.run(send_whatsapp_template_service("c", "sofia_booking", "es", templates_file=path))

    assert [json.loads(r.content)["message"] for r in ghl["requests"]] == ["before", "after"]


def test_a_missing_or_broken_file_never_fails_the_send(ghl, tmp_path):
    """No file, or a file that is not YAML, leaves the template named in the chat and the send intact."""
    broken = tmp_path / "broken.yaml"
    broken.write_text("templates: [unclosed", encoding="utf-8")
    for path in (tmp_path / "missing.yaml", broken, None):
        result = asyncio.run(send_whatsapp_template_service("c", "sofia_booking", "es", templates_file=path))
        assert result["success"] is True
    assert {json.loads(r.content)["message"] for r in ghl["requests"]} == {"[WhatsApp template: sofia_booking]"}


def test_the_company_files_are_valid():
    """Both company files exist and every template in them has a name, a language and a text."""
    from agent_backend.builtin_tools.services.whatsapp_templates import _bodies

    assert _bodies(BABYNOVA_FILE)[("sofia_booking", "es")].count("{{") == 2
    assert _bodies(FAMILY_AIMS_FILE) == {}


def test_the_company_file_sits_in_its_shared_folder(tmp_path, monkeypatch):
    """The backend of a company reads whatsapp_templates.yaml from the shared/ folder next to its bundles."""
    from types import SimpleNamespace

    from agent_backend.builtin_tools.services.whatsapp_templates import company_templates_file

    monkeypatch.delenv("WHATSAPP_TEMPLATES_FILE", raising=False)
    company = tmp_path / "company"
    (company / "bundles").mkdir(parents=True)

    assert company_templates_file(SimpleNamespace(agents_dir=company / "bundles")) == (
        company / "shared" / "whatsapp_templates.yaml"
    ).resolve()
    assert company_templates_file(object()) is None
    monkeypatch.setenv("WHATSAPP_TEMPLATES_FILE", str(tmp_path / "other.yaml"))
    assert company_templates_file(SimpleNamespace(agents_dir=company / "bundles")) == tmp_path / "other.yaml"


@pytest.mark.parametrize(
    ("company", "expected"),
    [
        ("babynova", "📅 FECHA: Lunes, 30 de NOVIEMBRE de 2026."),
        ("family_aims", "[WhatsApp template: sofia_booking]"),
    ],
)
def test_the_backend_of_each_company_reads_its_own_file(ghl, monkeypatch, company, expected):
    """Through the real app, the endpoint shows the text from the file of the company the backend serves."""
    from agent_backend.app import create_app
    from agent_backend.settings import Settings
    from agent_backend.tool_client import BUILTIN_TOOLS_PREFIX

    monkeypatch.delenv("WHATSAPP_TEMPLATES_FILE", raising=False)
    bundles = COMPANIES / company / "bundles"
    settings = Settings(host="127.0.0.1", port=8010, agents_dir=bundles, admin_token=None, company=company)

    response = TestClient(create_app(settings)).post(
        f"{BUILTIN_TOOLS_PREFIX}/send-whatsapp-template",
        json={
            "contact_id": "c1",
            "template_name": "sofia_booking",
            "language": "es",
            "body_variables": ["Lunes, 30 de NOVIEMBRE de 2026", "09:10 a.m"],
            "location_id": "loc1",
        },
    )

    assert response.status_code == 200 and response.json()["success"] is True
    assert expected in _sent(ghl)[1]["message"]
