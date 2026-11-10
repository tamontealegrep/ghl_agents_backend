import pytest
from surrogacy.services.documentation_check import check_documentation


def test_colombian_nationality_is_approved_without_document():
    result = check_documentation("COL", None)
    assert result == {"approved": True, "reason": "Colombian nationality", "normalized_documents": []}


def test_colombian_nationality_case_and_whitespace_insensitive():
    result = check_documentation("  col  ", None)
    assert result["approved"] is True


@pytest.mark.parametrize("bad_nationality", ["", "CO", "COLO", "123", "C0L", None])
def test_invalid_nationality_format_is_rejected(bad_nationality):
    result = check_documentation(bad_nationality, "cedula_ciudadania")
    assert result["approved"] is False
    assert "Format error" in result["reason"]
    assert result["normalized_documents"] == []


def test_foreign_nationality_without_document_type_is_rejected():
    result = check_documentation("VEN", None)
    assert result == {
        "approved": False,
        "reason": "Missing document type for foreign nationality",
        "normalized_documents": [],
    }


@pytest.mark.parametrize("empty_document_type", ["", "   ", []])
def test_foreign_nationality_with_empty_document_type_is_rejected(empty_document_type):
    result = check_documentation("VEN", empty_document_type)
    assert result["approved"] is False
    assert result["reason"] == "Missing document type for foreign nationality"
    assert result["normalized_documents"] == []


@pytest.mark.parametrize(
    "document_type",
    ["cedula_ciudadania", "cedula de ciudadania", "cedula ciudadania", "c.c", "cc", "CC"],
)
def test_foreigner_with_cedula_ciudadania_is_approved(document_type):
    result = check_documentation("VEN", document_type)
    assert result["approved"] is True
    assert result["normalized_documents"] == ["cedula_ciudadania"]
    assert result["reason"] == "Foreigner with Colombian Cedula de Ciudadania"


@pytest.mark.parametrize(
    "document_type",
    ["ppt", "PPT", "permiso de proteccion temporal", "permiso proteccion temporal"],
)
def test_foreigner_with_ppt_is_approved(document_type):
    """ModificaciÃ³n del owner (2026-08-26): el PPT tambiÃ©n aprueba a un extranjero."""
    result = check_documentation("VEN", document_type)
    assert result["approved"] is True
    assert result["normalized_documents"] == ["ppt"]
    assert result["reason"] == "Foreigner with Permiso de Proteccion Temporal (PPT)"


@pytest.mark.parametrize(
    "document_type,canonical",
    [
        ("cedula_extranjeria", "cedula_extranjeria"),
        ("cedula de extranjeria", "cedula_extranjeria"),
        ("c.e", "cedula_extranjeria"),
        ("pasaporte", "pasaporte"),
        ("passport", "pasaporte"),
        ("otro", "otro"),
        ("OTRO", "otro"),
    ],
)
def test_foreigner_with_other_documents_is_rejected(document_type, canonical):
    result = check_documentation("VEN", document_type)
    assert result["approved"] is False
    assert "Document not allowed" in result["reason"]
    assert document_type in result["reason"]
    assert result["normalized_documents"] == [canonical]


def test_foreigner_with_unknown_document_type_is_rejected_as_desconocido():
    result = check_documentation("VEN", "algo-que-no-existe")
    assert result["approved"] is False
    assert result["normalized_documents"] == ["desconocido"]


# ---------------------------------------------------------------------------
# document_type acepta multiples documentos: string separado por comas, o
# lista (2026-08-27, a pedido del owner). Se aprueba si CUALQUIERA de los
# documentos dados es un tipo valido.
# ---------------------------------------------------------------------------


def test_multiple_documents_as_comma_separated_string_approves_if_any_is_valid():
    result = check_documentation("VEN", "cedula_extranjeria,ppt")
    assert result["approved"] is True
    assert result["normalized_documents"] == ["cedula_extranjeria", "ppt"]
    assert result["reason"] == "Foreigner with Permiso de Proteccion Temporal (PPT)"


def test_multiple_documents_as_list_approves_if_any_is_valid():
    result = check_documentation("VEN", ["pasaporte", "cedula_ciudadania"])
    assert result["approved"] is True
    assert result["normalized_documents"] == ["pasaporte", "cedula_ciudadania"]
    assert result["reason"] == "Foreigner with Colombian Cedula de Ciudadania"


def test_multiple_documents_uses_first_approved_match_when_more_than_one_qualifies():
    result = check_documentation("VEN", "ppt,cedula_ciudadania")
    assert result["approved"] is True
    assert result["reason"] == "Foreigner with Permiso de Proteccion Temporal (PPT)"


def test_multiple_documents_rejected_when_none_are_valid():
    result = check_documentation("VEN", "cedula_extranjeria,pasaporte")
    assert result["approved"] is False
    assert result["normalized_documents"] == ["cedula_extranjeria", "pasaporte"]
    assert "Document not allowed" in result["reason"]
    assert "'cedula_extranjeria'" in result["reason"]
    assert "'pasaporte'" in result["reason"]


def test_multiple_documents_mixed_known_and_unknown():
    result = check_documentation("VEN", "algo-raro,ppt")
    assert result["approved"] is True
    assert result["normalized_documents"] == ["desconocido", "ppt"]


def test_multiple_documents_trims_whitespace_around_each_item():
    result = check_documentation("VEN", " ppt , pasaporte ")
    assert result["normalized_documents"] == ["ppt", "pasaporte"]
    assert result["approved"] is True


def test_multiple_documents_drops_empty_items_from_comma_string():
    result = check_documentation("VEN", "ppt,,pasaporte")
    assert result["normalized_documents"] == ["ppt", "pasaporte"]


def test_otro_alone_is_rejected():
    """'otro' es un alias reconocido explicito (no cae en 'desconocido'), pero no aprueba."""
    result = check_documentation("VEN", "otro")
    assert result["approved"] is False
    assert result["normalized_documents"] == ["otro"]
    assert "Document not allowed" in result["reason"]


def test_otro_mixed_with_a_valid_document_still_approves():
    result = check_documentation("VEN", "otro,ppt")
    assert result["approved"] is True
    assert result["normalized_documents"] == ["otro", "ppt"]


@pytest.mark.parametrize(
    "document_type",
    [
        "cedula de ciudadania",
        ["cedula de ciudadania"],
        "cedula de ciudadania, ppt",
        ["cedula de ciudadania", "ppt"],
    ],
)
def test_accepts_the_four_documented_input_shapes(document_type):
    """Los 4 formatos que el owner pidio soportar explicitamente: string simple,
    lista de un elemento, string separado por comas, y lista de varios elementos."""
    result = check_documentation("VEN", document_type)
    assert result["approved"] is True
    assert "cedula_ciudadania" in result["normalized_documents"]
