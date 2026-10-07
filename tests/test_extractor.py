from __future__ import annotations

import asyncio
import base64
from io import BytesIO

import pytest
from PIL import Image
from pydantic_ai.exceptions import ModelHTTPError
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

import doc_extractor_pydantic.document_processing as processing_module
import doc_extractor_pydantic.extractor as extractor_module
from doc_extractor_pydantic.config import Settings
from doc_extractor_pydantic.extractor import (
    DocumentExtractor,
    ProviderUnavailableError,
    UploadValidationError,
    extract_pdf_previews,
    format_text,
    media_type_for,
    to_api_response,
    validate_upload,
)
from doc_extractor_pydantic.limits import (
    MAX_PDF_PAGES,
    MAX_PREVIEW_IMAGES,
    MAX_PREVIEW_SCAN_PAGES,
    PROVIDER_RETRIES,
)
from doc_extractor_pydantic.models import DocumentExtraction, DocumentIntegrity, ExtractedField
from doc_extractor_pydantic.prompts import EXTRACTION_INSTRUCTIONS


def make_image(format_name: str) -> bytes:
    stream = BytesIO()
    with Image.new("RGB", (10, 10), (100, 120, 200)) as image:
        image.save(stream, format=format_name)
    return stream.getvalue()


PNG = make_image("PNG")
JPEG = make_image("JPEG")


@pytest.fixture(autouse=True)
def inline_document_processing(monkeypatch):
    """Agent tests isolate provider behavior; worker lifecycle has its own tests."""

    async def process_inline(file_name, content, max_upload_bytes, content_type=None):
        document = extractor_module.validate_upload(file_name, content, max_upload_bytes)
        return processing_module.ProcessedDocument(
            media_type=media_type_for(file_name, content_type),
            pages=len(document.pages) if document is not None else 1,
            previews=extractor_module.extract_pdf_previews(document),
        )

    monkeypatch.setattr(extractor_module, "process_document_async", process_inline)


def make_pdf(pages: int = 1) -> bytes:
    stream = BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    writer.write(stream)
    return stream.getvalue()


def make_image_pdf(pages: int = 1, size: tuple[int, int] = (420, 300)) -> bytes:
    """Synthetic PDF where every page carries one embedded image."""

    images = [
        Image.new("RGB", size, (30 * (index + 1) % 256, 120, 200)) for index in range(pages)
    ]
    stream = BytesIO()
    images[0].save(stream, format="PDF", save_all=True, append_images=images[1:])
    return stream.getvalue()


def make_webp(size: tuple[int, int] = (10, 10)) -> bytes:
    img = Image.new("RGB", size, (255, 0, 0))
    stream = BytesIO()
    img.save(stream, format="WEBP")
    return stream.getvalue()


PDF = make_pdf()
WEBP = make_webp()
INVALID_PDF = b"%PDF-1.7\nnot-a-complete-pdf"


def test_default_settings_match_the_local_pilot() -> None:
    settings = Settings()
    assert settings.model == "google:gemini-3.5-flash-lite"
    assert settings.port == 8788


def test_settings_refuse_a_host_outside_loopback(monkeypatch) -> None:
    monkeypatch.setenv("HOST", "localhost")
    assert Settings.from_env().host == "localhost"

    monkeypatch.setenv("HOST", "0.0.0.0")
    with pytest.raises(ValueError, match="não é loopback"):
        Settings.from_env()


def test_prompt_maps_cnh_category_to_the_cat_hab_field() -> None:
    prompt = EXTRACTION_INSTRUCTIONS.lower()
    assert "9 cat hab" in prompt
    assert "acc" in prompt
    assert "tabelas de veículos" in prompt


def test_prompt_instructs_cnh_first_licence_date_extraction() -> None:
    prompt = EXTRACTION_INSTRUCTIONS.lower()
    assert "1ª habilitação" in prompt
    assert "first_licence_date" in EXTRACTION_INSTRUCTIONS


def test_google_agent_uses_minimal_thinking_without_a_network_call(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    agent = DocumentExtractor(
        Settings(model="google:gemini-3.5-flash-lite")
    )._build_agent()
    assert agent.model_settings == {
        "google_thinking_config": {"thinking_level": "MINIMAL"}
    }


def test_validates_supported_uploads_and_signatures() -> None:
    validate_upload("document.png", PNG, 1024)
    validate_upload("document.jpg", JPEG, 1024)
    validate_upload("document.webp", WEBP, 1024)
    validate_upload("document.pdf", PDF, 1024)

    with pytest.raises(UploadValidationError, match="Formato não suportado"):
        validate_upload("document.exe", b"x", 1024)
    with pytest.raises(UploadValidationError, match="PNG válido"):
        validate_upload("document.png", b"x", 1024)
    with pytest.raises(UploadValidationError, match="WebP válida"):
        validate_upload("document.webp", b"x", 1024)
    with pytest.raises(UploadValidationError, match="PDF válido"):
        validate_upload("document.pdf", INVALID_PDF, 1024)
    with pytest.raises(UploadValidationError, match="excede"):
        validate_upload("document.jpg", JPEG, 2)


def test_infers_media_type_from_extension() -> None:
    assert media_type_for("doc.png", "application/octet-stream") == "image/png"
    assert media_type_for("doc.jpeg") == "image/jpeg"
    assert media_type_for("doc.webp") == "image/webp"
    assert media_type_for("doc.pdf") == "application/pdf"


def test_validation_returns_the_only_parsed_pdf() -> None:
    assert validate_upload("doc.png", PNG, 1024) is None
    document = validate_upload("doc.pdf", PDF, 1024)
    assert document is not None
    assert len(document.pages) == 1


def test_rejects_a_pdf_with_more_pages_than_the_local_limit() -> None:
    oversized = make_pdf(pages=MAX_PDF_PAGES + 1)
    validate_upload("doc.pdf", make_pdf(pages=MAX_PDF_PAGES), len(oversized))

    with pytest.raises(UploadValidationError, match="limite local é de"):
        validate_upload("doc.pdf", oversized, len(oversized))


def test_validation_rejects_password_protected_pdf() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret-password")
    stream = BytesIO()
    writer.write(stream)
    encrypted_pdf = stream.getvalue()

    with pytest.raises(UploadValidationError, match="protegido por senha"):
        validate_upload("protected.pdf", encrypted_pdf, len(encrypted_pdf) + 1024)


def test_extraction_parses_the_pdf_only_once(monkeypatch) -> None:
    readers = []
    original_reader = processing_module.PdfReader

    def counting_reader(*args, **kwargs):
        readers.append(1)
        return original_reader(*args, **kwargs)

    monkeypatch.setattr(processing_module, "PdfReader", counting_reader)
    asyncio.run(
        DocumentExtractor(settings=Settings(model="test:model"), agent=FakeAgent()).extract(
            "doc.pdf", make_image_pdf()
        )
    )

    assert len(readers) == 1


def test_previews_stop_at_the_scan_and_encode_limits(monkeypatch) -> None:
    encoded = []
    original_encode = processing_module._encode_preview

    def counting_encode(document, candidate):
        encoded.append(candidate["page"])
        return original_encode(document, candidate)

    monkeypatch.setattr(processing_module, "_encode_preview", counting_encode)
    document = validate_upload("doc.pdf", make_image_pdf(pages=MAX_PREVIEW_SCAN_PAGES + 2), 10**7)
    previews = extract_pdf_previews(document)

    assert len(previews) == MAX_PREVIEW_IMAGES
    assert len(encoded) == MAX_PREVIEW_IMAGES
    assert max(encoded) <= MAX_PREVIEW_SCAN_PAGES
    assert [preview["label"] for preview in previews] == ["Frente", "Verso", "Detalhe", "Detalhe"]
    assert previews[0]["primary"] is True
    assert previews[0]["src"].startswith("data:image/")


def test_repeated_references_to_one_image_produce_a_single_preview() -> None:
    document = validate_upload("doc.pdf", make_image_pdf(), 10**7)
    assert document is not None
    page = document.pages[0]
    repeated = DecodedStreamObject()
    repeated.set_data(b"\n".join([b"q 420 0 0 300 0 0 cm /image Do Q"] * 500))
    page[NameObject("/Contents")] = repeated

    previews = extract_pdf_previews(document)

    assert len(previews) == 1
    assert previews[0]["label"] == "Frente"


def test_previews_are_empty_without_a_pdf() -> None:
    assert extract_pdf_previews(None) == []


def test_pydantic_output_normalizes_blank_values() -> None:
    extraction = DocumentExtraction(
        kind="cnh",
        fields={"name": {"value": " ", "confidence": "high"}},
    )
    assert extraction.fields.name is not None
    assert extraction.fields.name.value is None


def test_pydantic_output_removes_semantically_invalid_values() -> None:
    extraction = DocumentExtraction(
        kind="cnh",
        fields={
            "cpf": {"value": "111.111.111-11", "confidence": "high"},
            "birth_date": {"value": "31/02/1990", "confidence": "high"},
            "registration": {"value": "ABC123", "confidence": "high"},
            "category": {"value": "Z", "confidence": "high"},
        },
    )
    assert extraction.fields.cpf is None
    assert extraction.fields.birth_date is None
    assert extraction.fields.registration is None
    assert extraction.fields.category is None
    assert len(extraction.warnings) == 4


def test_pydantic_output_removes_incoherent_date_pairs() -> None:
    extraction = DocumentExtraction(
        fields={
            "birth_date": {"value": "10/02/2020", "confidence": "high"},
            "issue_date": {"value": "10/02/2019", "confidence": "high"},
        },
    )
    assert extraction.fields.birth_date is None
    assert extraction.fields.issue_date is None
    assert "incompatíveis" in extraction.warnings[0]


def test_pydantic_output_keeps_valid_semantic_values() -> None:
    extraction = DocumentExtraction(
        fields={
            "cpf": {"value": "123.456.789-09", "confidence": "high"},
            "birth_date": {"value": "10/02/1990", "confidence": "high"},
            "issue_date": {"value": "12/03/2024", "confidence": "high"},
            "validity": {"value": "12/03/2034", "confidence": "high"},
            "first_licence_date": {"value": "15/05/2010", "confidence": "high"},
            "registration": {"value": "12345678901", "confidence": "high"},
            "category": {"value": "ab", "confidence": "high"},
        },
    )
    assert set(extraction.fields.populated()) == {
        "cpf",
        "birth_date",
        "issue_date",
        "validity",
        "first_licence_date",
        "registration",
        "category",
    }
    assert extraction.fields.category.value == "AB"
    assert extraction.fields.first_licence_date.value == "15/05/2010"
    assert extraction.warnings == []


def test_pydantic_output_removes_invalid_and_incoherent_first_licence_dates() -> None:
    extraction_future = DocumentExtraction(
        fields={
            "birth_date": {"value": "10/02/1990", "confidence": "high"},
            "first_licence_date": {"value": "01/01/2099", "confidence": "high"},
        },
    )
    assert extraction_future.fields.first_licence_date is None
    assert "A data de 1ª habilitação não pode ser no futuro." in extraction_future.warnings

    extraction_birth = DocumentExtraction(
        fields={
            "birth_date": {"value": "10/02/2010", "confidence": "high"},
            "first_licence_date": {"value": "10/02/2005", "confidence": "high"},
        },
    )
    assert extraction_birth.fields.birth_date is None
    assert extraction_birth.fields.first_licence_date is None
    assert "As datas de nascimento e 1ª habilitação são incompatíveis." in extraction_birth.warnings

    extraction_issue = DocumentExtraction(
        fields={
            "issue_date": {"value": "10/02/2015", "confidence": "high"},
            "first_licence_date": {"value": "10/02/2020", "confidence": "high"},
        },
    )
    assert extraction_issue.fields.first_licence_date is None
    assert extraction_issue.fields.issue_date is None
    assert "As datas de 1ª habilitação e emissão são incompatíveis." in extraction_issue.warnings

    extraction_val = DocumentExtraction(
        fields={
            "validity": {"value": "10/02/2015", "confidence": "high"},
            "first_licence_date": {"value": "10/02/2020", "confidence": "high"},
        },
    )
    assert extraction_val.fields.first_licence_date is None
    assert extraction_val.fields.validity is None
    assert "As datas de 1ª habilitação e validade são incompatíveis." in extraction_val.warnings


def test_parentage_normalizes_escaped_and_labeled_line_breaks() -> None:
    extraction = DocumentExtraction(
        fields={
            "parentage": {
                "value": r"PAI DA SILVA\n; MAE DE TESTE",
                "confidence": "high",
            }
        }
    )
    assert extraction.fields.parentage is not None
    assert extraction.fields.parentage.value == "PAI DA SILVA\nMAE DE TESTE"


def test_api_response_keeps_legacy_field_names_and_text() -> None:
    extraction = DocumentExtraction(
        kind="cnh",
        fields={
            "name": ExtractedField(value="MARIA DE TESTE", confidence="high"),
            "birth_date": ExtractedField(value="10/02/1990", confidence="medium"),
        },
        transcription="CARTEIRA NACIONAL DE HABILITAÇÃO",
        warnings=["Confira a data."],
    )
    result = to_api_response(extraction, pages=1, duration_ms=42)
    assert result["fields"]["birthDate"]["label"] == "Data de nascimento"
    assert result["previews"] == []
    assert "Nome: MARIA DE TESTE" in result["text"]
    assert "TRANSCRIÇÃO RECONHECIDA" in result["text"]


def test_rg_does_not_warn_about_fields_a_rg_does_not_have() -> None:
    extraction = DocumentExtraction(
        kind="rg",
        warnings=[
            "Não foi possível localizar o número de registro.",
            "A categoria de habilitação não foi encontrada.",
            "A validade não está legível.",
            "A data da 1ª habilitação não foi localizada.",
            "A data de emissão não está legível.",
        ],
    )

    assert extraction.warnings == ["A data de emissão não está legível."]


def test_cnh_keeps_the_warning_about_its_own_registration() -> None:
    extraction = DocumentExtraction(
        kind="cnh",
        warnings=["Não foi possível localizar o número de registro."],
    )

    assert extraction.warnings == ["Não foi possível localizar o número de registro."]


def test_unknown_document_keeps_every_warning() -> None:
    extraction = DocumentExtraction(
        kind="unknown",
        warnings=["Não foi possível localizar o número de registro."],
    )

    assert len(extraction.warnings) == 1


def test_unknown_document_preserves_unsupported_document_guidance_warning() -> None:
    extraction = DocumentExtraction(
        kind="unknown",
        warnings=[
            "O documento aparenta ser um comprovante de residência. "
            "O ExtrAI suporta atualmente RG e CNH."
        ],
    )
    assert len(extraction.warnings) == 1
    assert "comprovante de residência" in extraction.warnings[0]


def test_an_invalid_value_still_warns_even_when_the_kind_does_not_expect_it() -> None:
    extraction = DocumentExtraction(
        kind="rg",
        fields={"registration": {"value": "ABC123", "confidence": "high"}},
    )

    assert extraction.fields.registration is None
    assert extraction.warnings == ["O registro não pôde ser confirmado."]


def test_prompt_tells_the_model_not_to_warn_about_absent_field_types() -> None:
    assert "Só avise sobre campos que o documento identificado realmente possui" in (
        EXTRACTION_INSTRUCTIONS
    )


def test_api_response_lists_the_expected_fields_that_were_not_found() -> None:
    extraction = DocumentExtraction(
        kind="cnh",
        fields={"name": ExtractedField(value="MARIA DE TESTE", confidence="low")},
    )

    result = to_api_response(extraction, pages=1, duration_ms=42)
    missing = [field["key"] for field in result["missing"]]

    assert "name" not in missing
    assert missing == [
        "cpf",
        "birthDate",
        "issueDate",
        "validity",
        "firstLicenceDate",
        "registration",
        "category",
        "parentage",
    ]
    assert result["missing"][0]["label"] == "CPF"
    assert result["fields"]["name"]["confidence"] == "low"


def test_expected_fields_follow_the_document_kind() -> None:
    rg = to_api_response(DocumentExtraction(kind="rg"), pages=1, duration_ms=1)
    unknown = to_api_response(DocumentExtraction(kind="unknown"), pages=1, duration_ms=1)

    assert "category" not in [field["key"] for field in rg["missing"]]
    assert "firstLicenceDate" not in [field["key"] for field in rg["missing"]]
    assert [field["key"] for field in unknown["missing"]] == ["name", "cpf", "birthDate"]


def test_cin_expected_fields_and_missing_mapping() -> None:
    cin = to_api_response(DocumentExtraction(kind="cin"), pages=1, duration_ms=1)
    missing_keys = [field["key"] for field in cin["missing"]]
    assert "category" not in missing_keys
    assert "registration" not in missing_keys
    assert "firstLicenceDate" not in missing_keys
    assert missing_keys == [
        "name",
        "cpf",
        "birthDate",
        "issueDate",
        "validity",
        "birthPlace",
        "nationality",
        "parentage",
    ]


def test_cin_prunes_inapplicable_warnings_and_accepts_indeterminada() -> None:
    extraction = DocumentExtraction(
        kind="cin",
        fields={
            "name": {"value": "SEBASTIAO DA SILVA", "confidence": "high"},
            "cpf": {"value": "123.456.789-09", "confidence": "high"},
            "validity": {"value": "INDETERMINADA", "confidence": "high"},
        },
        warnings=[
            "Não foi possível localizar o número de registro.",
            "Categoria de habilitação não encontrada.",
            "1ª habilitação ausente.",
            "Filiação parcialmente ilegível.",
        ],
    )
    assert extraction.fields.validity is not None
    assert extraction.fields.validity.value == "INDETERMINADA"
    assert extraction.warnings == ["Filiação parcialmente ilegível."]


class FakeAgent:
    def __init__(self) -> None:
        self.messages = None

    async def run(self, messages, *args, **kwargs):
        self.messages = messages
        return type(
            "FakeResult",
            (),
            {
                "output": DocumentExtraction(
                    kind="unknown",
                    warnings=["Documento de teste."],
                ),
                "usage": lambda self: type(
                    "FakeUsage",
                    (),
                    {"requests": 1, "input_tokens": 120, "output_tokens": 45},
                )(),
            },
        )()


def test_slow_provider_is_cut_by_the_local_timeout(monkeypatch) -> None:
    class SlowAgent:
        async def run(self, messages, *args, **kwargs):
            await asyncio.sleep(5)

    monkeypatch.setattr(extractor_module, "EXTRACTION_TIMEOUT_SECONDS", 0.05)
    extractor = DocumentExtractor(settings=Settings(model="test:model"), agent=SlowAgent())

    with pytest.raises(extractor_module.ExtractionTimeoutError, match="tempo limite"):
        asyncio.run(extractor.extract("doc.png", PNG))


def test_agent_keeps_additional_attempts(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    agent = DocumentExtractor(Settings(model="google:gemini-3.5-flash-lite"))._build_agent()
    assert PROVIDER_RETRIES == 2
    assert agent._max_output_retries == PROVIDER_RETRIES


def test_transient_provider_503_uses_backoff_retry(monkeypatch) -> None:
    class FlakyAgent:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, messages, *args, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise ModelHTTPError(503, "test:model", {"status": "unavailable"})
            return type("FakeResult", (), {"output": DocumentExtraction(kind="unknown")})()

    agent = FlakyAgent()
    monkeypatch.setattr(extractor_module, "PROVIDER_BACKOFF_SECONDS", 0)
    result = asyncio.run(
        DocumentExtractor(settings=Settings(model="test:model"), agent=agent).extract(
            "doc.png", PNG
        )
    )

    assert agent.calls == 3
    assert result["kind"] == "unknown"


def test_exhausted_provider_503_becomes_provider_unavailable(monkeypatch) -> None:
    class UnavailableAgent:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, messages, *args, **kwargs):
            self.calls += 1
            raise ModelHTTPError(503, "test:model", {"status": "unavailable"})

    agent = UnavailableAgent()
    monkeypatch.setattr(extractor_module, "PROVIDER_BACKOFF_SECONDS", 0)
    with pytest.raises(ProviderUnavailableError, match="temporariamente indisponível"):
        asyncio.run(
            DocumentExtractor(settings=Settings(model="test:model"), agent=agent).extract(
                "doc.png", PNG
            )
        )
    assert agent.calls == 3


def test_extractor_sends_multimodal_content_without_writing_file() -> None:
    fake = FakeAgent()
    settings = Settings(model="test:model")
    result = asyncio.run(
        DocumentExtractor(settings=settings, agent=fake).extract("doc.png", PNG)
    )
    assert result["pages"] == 1
    assert result["warnings"] == ["Documento de teste."]
    assert fake.messages[0].startswith("Extraia os campos")
    assert "nome do arquivo" not in fake.messages[0].lower()
    assert "doc.png" not in fake.messages[0]
    assert fake.messages[1].media_type == "image/png"
    assert fake.messages[1].data == PNG


def test_extractor_adds_only_the_primary_embedded_image_to_pdf_input(monkeypatch) -> None:
    fake = FakeAgent()
    preview = {
        "label": "Frente",
        "primary": True,
        "src": "data:image/jpeg;base64," + base64.b64encode(JPEG).decode("ascii"),
    }
    monkeypatch.setattr(extractor_module, "extract_pdf_previews", lambda *_: [preview])

    result = asyncio.run(
        DocumentExtractor(settings=Settings(model="test:model"), agent=fake).extract(
            "doc.pdf", PDF
        )
    )

    assert result["previews"] == [preview]
    assert fake.messages[1].media_type == "application/pdf"
    assert fake.messages[2].media_type == "image/jpeg"
    assert fake.messages[2].data == JPEG


def test_pydantic_output_removes_future_dates() -> None:
    extraction = DocumentExtraction(
        fields={
            "birth_date": {"value": "01/01/2099", "confidence": "high"},
            "issue_date": {"value": "01/01/2099", "confidence": "high"},
        },
    )
    assert extraction.fields.birth_date is None
    assert extraction.fields.issue_date is None
    assert any("futuro" in w for w in extraction.warnings)


def test_pydantic_output_removes_incoherent_birth_and_validity() -> None:
    extraction = DocumentExtraction(
        fields={
            "birth_date": {"value": "10/02/2025", "confidence": "high"},
            "validity": {"value": "10/02/2024", "confidence": "high"},
        },
    )
    assert extraction.fields.birth_date is None
    assert extraction.fields.validity is None
    assert any("incompatíveis" in w for w in extraction.warnings)


def test_parse_brazilian_date_enforces_year_bounds() -> None:
    from doc_extractor_pydantic.models import _parse_brazilian_date

    assert _parse_brazilian_date("10/02/1899") is None
    assert _parse_brazilian_date("10/02/1900") is not None
    assert _parse_brazilian_date("10/02/2030") is not None
    assert _parse_brazilian_date("10/02/2100") is not None
    assert _parse_brazilian_date("10/02/2101") is None
    assert _parse_brazilian_date("10/02/2925") is None


def test_pydantic_output_removes_excessively_distant_validity() -> None:
    extraction = DocumentExtraction(
        fields={
            "validity": {"value": "10/02/2050", "confidence": "high"},
        },
    )
    assert extraction.fields.validity is None
    assert any("excessivamente distante" in w for w in extraction.warnings)


def test_pydantic_output_removes_validity_too_far_from_issue_date() -> None:
    extraction = DocumentExtraction(
        fields={
            "issue_date": {"value": "10/02/2015", "confidence": "high"},
            "validity": {"value": "10/02/2035", "confidence": "high"},
        },
    )
    assert extraction.fields.validity is None
    assert any("excessivamente distante" in w for w in extraction.warnings)


def test_pydantic_output_preserves_realistic_future_validity() -> None:
    extraction = DocumentExtraction(
        fields={
            "issue_date": {"value": "10/02/2024", "confidence": "high"},
            "validity": {"value": "10/02/2034", "confidence": "high"},
        },
    )
    assert extraction.fields.validity is not None
    assert extraction.fields.validity.value == "10/02/2034"


def test_pydantic_output_warns_on_expired_validity_without_dropping_value() -> None:
    extraction = DocumentExtraction(
        kind="cnh",
        fields={
            "birth_date": {"value": "10/02/1990", "confidence": "high"},
            "issue_date": {"value": "10/02/2015", "confidence": "high"},
            "validity": {"value": "10/02/2020", "confidence": "high"},
        },
    )
    assert extraction.fields.validity is not None
    assert extraction.fields.validity.value == "10/02/2020"
    assert any("expirada" in w and "10/02/2020" in w for w in extraction.warnings)


def test_rg_keeps_warning_about_registro_geral() -> None:
    extraction = DocumentExtraction(
        kind="rg",
        warnings=["O registro geral está parcialmente ilegível."],
    )
    assert extraction.warnings == ["O registro geral está parcialmente ilegível."]


def test_rg_accepts_check_digit_x() -> None:
    extraction_upper = DocumentExtraction(
        kind="rg",
        fields={"registration": {"value": "12.345.678-X", "confidence": "high"}},
    )
    assert extraction_upper.fields.registration is not None
    assert extraction_upper.fields.registration.value == "12.345.678-X"

    extraction_lower = DocumentExtraction(
        kind="rg",
        fields={"registration": {"value": "12.345.678-x", "confidence": "high"}},
    )
    assert extraction_lower.fields.registration is not None
    assert extraction_lower.fields.registration.value == "12.345.678-x"


def test_rg_rejects_x_in_middle_or_invalid_letters() -> None:
    extraction = DocumentExtraction(
        kind="rg",
        fields={"registration": {"value": "12X345678", "confidence": "high"}},
    )
    assert extraction.fields.registration is None
    assert any("registro" in w for w in extraction.warnings)


def test_google_cloud_provider_applies_minimal_thinking(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    agent = DocumentExtractor(
        Settings(model="google-cloud:gemini-3.5-flash-lite")
    )._build_agent()
    assert agent.model_settings == {
        "google_thinking_config": {"thinking_level": "MINIMAL"}
    }


def test_extraction_includes_usage_metadata() -> None:
    extractor = DocumentExtractor(settings=Settings(model="test:model"), agent=FakeAgent())
    result = asyncio.run(extractor.extract("doc.png", PNG))
    assert result["usage"] == {
        "requests": 1,
        "inputTokens": 120,
        "outputTokens": 45,
    }


def test_extraction_handles_pydantic_ai_run_usage_without_deprecation_warning() -> None:
    import warnings

    from pydantic_ai.result import RunUsage

    class RunUsageAgent:
        async def run(self, messages, *args, **kwargs):
            return type(
                "RunUsageResult",
                (),
                {
                    "output": DocumentExtraction(kind="unknown"),
                    "usage": RunUsage(requests=2, input_tokens=350, output_tokens=80),
                },
            )()

    extractor = DocumentExtractor(settings=Settings(model="test:model"), agent=RunUsageAgent())
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = asyncio.run(extractor.extract("doc.png", PNG))

    assert result["usage"] == {
        "requests": 2,
        "inputTokens": 350,
        "outputTokens": 80,
    }


def test_primary_model_failure_triggers_fallback_model(monkeypatch) -> None:
    class FailingPrimaryAgent:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, messages, *args, **kwargs):
            self.calls += 1
            raise ModelHTTPError(503, "primary:model", {"status": "unavailable"})

    class SuccessfulFallbackAgent:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, messages, *args, **kwargs):
            self.calls += 1
            return type(
                "Result",
                (),
                {"output": DocumentExtraction(kind="cnh")},
            )()

    primary = FailingPrimaryAgent()
    fallback = SuccessfulFallbackAgent()
    monkeypatch.setattr(extractor_module, "PROVIDER_BACKOFF_SECONDS", 0)

    settings = Settings(
        model="primary:model",
        fallback_models=("fallback:model",),
    )
    extractor = DocumentExtractor(
        settings=settings,
        agent=primary,
        fallback_agents=[fallback],
    )
    result = asyncio.run(extractor.extract("doc.png", PNG))

    assert primary.calls == 3
    assert fallback.calls == 1
    assert result["kind"] == "cnh"
    assert result["modelUsed"] == "fallback:model"


def test_primary_model_timeout_triggers_fallback_model(monkeypatch) -> None:
    class HangingPrimaryAgent:
        async def run(self, messages, *args, **kwargs):
            await asyncio.sleep(5.0)

    class QuickFallbackAgent:
        async def run(self, messages, *args, **kwargs):
            return type(
                "Result",
                (),
                {"output": DocumentExtraction(kind="rg")},
            )()

    primary = HangingPrimaryAgent()
    fallback = QuickFallbackAgent()
    monkeypatch.setattr(extractor_module, "MODEL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(extractor_module, "EXTRACTION_TIMEOUT_SECONDS", 5.0)

    settings = Settings(
        model="primary:model",
        fallback_models=("fallback:model",),
    )
    extractor = DocumentExtractor(
        settings=settings,
        agent=primary,
        fallback_agents=[fallback],
    )
    result = asyncio.run(extractor.extract("doc.png", PNG))

    assert result["kind"] == "rg"
    assert result["modelUsed"] == "fallback:model"


def test_all_models_failing_raises_provider_unavailable(monkeypatch) -> None:
    class FailingAgent:
        def __init__(self, name: str) -> None:
            self.name = name
            self.calls = 0

        async def run(self, messages, *args, **kwargs):
            self.calls += 1
            raise ModelHTTPError(503, self.name, {"status": "unavailable"})

    primary = FailingAgent("primary")
    fallback = FailingAgent("fallback")
    monkeypatch.setattr(extractor_module, "PROVIDER_BACKOFF_SECONDS", 0)

    settings = Settings(
        model="primary:model",
        fallback_models=("fallback:model",),
    )
    extractor = DocumentExtractor(
        settings=settings,
        agent=primary,
        fallback_agents=[fallback],
    )

    with pytest.raises(ProviderUnavailableError):
        asyncio.run(extractor.extract("doc.png", PNG))

    assert primary.calls == 3
    assert fallback.calls == 3


def test_non_retryable_error_does_not_trigger_fallback(monkeypatch) -> None:
    class AuthFailingAgent:
        async def run(self, messages, *args, **kwargs):
            raise ModelHTTPError(401, "primary", {"status": "unauthorized"})

    class ShouldNotBeCalledAgent:
        def __init__(self) -> None:
            self.called = False

        async def run(self, messages, *args, **kwargs):
            self.called = True
            return type("Result", (), {"output": DocumentExtraction(kind="cnh")})()

    fallback = ShouldNotBeCalledAgent()
    settings = Settings(
        model="primary:model",
        fallback_models=("fallback:model",),
    )
    extractor = DocumentExtractor(
        settings=settings,
        agent=AuthFailingAgent(),
        fallback_agents=[fallback],
    )

    with pytest.raises(ModelHTTPError) as exc_info:
        asyncio.run(extractor.extract("doc.png", PNG))

    assert exc_info.value.status_code == 401
    assert not fallback.called


def test_settings_fallback_models_env_parsing(monkeypatch) -> None:
    monkeypatch.delenv("PYDANTIC_AI_FALLBACK_MODELS", raising=False)
    default_settings = Settings.from_env()
    assert default_settings.fallback_models == ("google:gemini-3-flash-preview",)

    monkeypatch.setenv(
        "PYDANTIC_AI_FALLBACK_MODELS",
        "google:gemini-3-flash-preview, google:gemini-3.5-flash",
    )
    custom_settings = Settings.from_env()
    assert custom_settings.fallback_models == (
        "google:gemini-3-flash-preview",
        "google:gemini-3.5-flash",
    )

    monkeypatch.setenv("PYDANTIC_AI_FALLBACK_MODELS", "")
    disabled_settings = Settings.from_env()
    assert disabled_settings.fallback_models == ()


def test_settings_configured_fallback_models_filters_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    settings = Settings(
        model="google:gemini-3.5-flash-lite",
        fallback_models=(
            "google:gemini-3-flash-preview",
            "openai:gpt-4o-mini",
            "google:gemini-3.5-flash-lite",
        ),
    )
    configured = settings.configured_fallback_models()
    assert configured == ("google:gemini-3-flash-preview",)


def test_document_integrity_defaults_and_validation() -> None:
    integrity_default = DocumentIntegrity()
    assert integrity_default.media_type == "unknown"
    assert integrity_default.risk_level == "low"
    assert integrity_default.tampering_detected is False
    assert integrity_default.flags == []

    # Tampering detected elevates low risk to high
    tampered = DocumentIntegrity(tampering_detected=True, risk_level="low")
    assert tampered.risk_level == "high"

    # Screen capture elevates low risk to medium
    screen = DocumentIntegrity(media_type="screen_capture", risk_level="low")
    assert screen.risk_level == "medium"

    # Flag list cleaning strips whitespace
    with_flags = DocumentIntegrity(flags=["  padrão moiré detectado  ", "", " "])
    assert with_flags.flags == ["padrão moiré detectado"]


def test_document_integrity_warnings_injected_in_extraction() -> None:
    tampered_extraction = DocumentExtraction(
        kind="cnh",
        integrity=DocumentIntegrity(tampering_detected=True),
    )
    assert any("adulteração visual" in w for w in tampered_extraction.warnings)

    screen_extraction = DocumentExtraction(
        kind="rg",
        integrity=DocumentIntegrity(media_type="screen_capture"),
    )
    assert any("foto de tela/monitor" in w for w in screen_extraction.warnings)


def test_api_response_includes_document_integrity() -> None:
    extraction = DocumentExtraction(
        kind="cnh",
        integrity=DocumentIntegrity(
            media_type="physical_original",
            risk_level="low",
            tampering_detected=False,
            flags=["padrão gráfico íntegro"],
        ),
    )
    result = to_api_response(extraction, pages=1, duration_ms=50)
    assert "integrity" in result
    assert result["integrity"] == {
        "mediaType": "physical_original",
        "riskLevel": "low",
        "tamperingDetected": False,
        "flags": ["padrão gráfico íntegro"],
    }


def test_format_text_includes_document_integrity() -> None:
    extraction = DocumentExtraction(
        kind="cnh",
        integrity=DocumentIntegrity(
            media_type="physical_original",
            risk_level="low",
            tampering_detected=False,
            flags=["padrão gráfico íntegro"],
        ),
    )
    text = format_text(extraction)
    assert "INTEGRIDADE DO DOCUMENTO" in text
    assert "Tipo de mídia: Documento físico original" in text
    assert "Nível de risco: Baixo" in text
    assert "Adulteração detectada: Não" in text
    assert "Observações: padrão gráfico íntegro" in text

