"""Browser tests for the flows that string checks cannot observe."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Page  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic"

RESULT = {
    "kind": "cnh",
    "pages": 1,
    "fields": {
        "name": {"value": "MARIA DE TESTE", "confidence": "high", "label": "Nome"},
        "cpf": {"value": "123.456.789-09", "confidence": "medium", "label": "CPF"},
        "birthDate": {
            "value": "10/02/1990",
            "confidence": "low",
            "label": "Data de nascimento",
        },
    },
    "missing": [
        {"key": "validity", "label": "Validade"},
        {"key": "category", "label": "Categoria"},
    ],
    "text": "DOCUMENTO: CNH\nNome: MARIA DE TESTE",
    "warnings": ["A categoria não pôde ser confirmada.", "Confira a data de emissão."],
    "durationMs": 12,
    "previews": [],
}


def upload(page: Page, name: str = "doc.png") -> None:
    page.set_input_files(
        "#document",
        files=[{"name": name, "mimeType": "image/png", "buffer": PNG}],
    )


def answer(page: Page, body: dict | None = None, status: int = 200) -> None:
    page.route(
        "**/api/extract",
        lambda route: route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(body if body is not None else RESULT),
        ),
    )


def analyze(page: Page) -> None:
    page.click("#submit")
    page.wait_for_selector("#result:not(.hidden)")


@pytest.fixture
def page_at_home(page: Page, live_server: str) -> Page:
    page.goto(live_server)
    return page


def test_the_page_runs_without_tripping_the_content_security_policy(
    page: Page, live_server: str
) -> None:
    messages: list[str] = []
    page.on("console", lambda message: messages.append(message.text))
    page.goto(live_server)
    answer(page)
    upload(page)
    analyze(page)

    blocked = [text for text in messages if "Content Security Policy" in text]
    assert blocked == []


def test_extraction_renders_fields_warnings_and_placeholders(page_at_home: Page) -> None:
    page = page_at_home
    answer(page)
    upload(page)
    analyze(page)

    assert page.locator('.field-card[data-found="true"]').count() == 3
    assert page.locator('.field-card[data-found="false"]').count() == 2
    assert page.locator('[data-field-label="validity"] .field-value').inner_text() == (
        "Não identificado"
    )
    assert page.locator('[data-field-label="cpf"] .field-confidence').inner_text() == "conferir"
    assert page.locator('[data-field-label="birthDate"] .field-confidence').inner_text() == (
        "conferir com atenção"
    )
    assert page.locator('[data-field-label="name"] .field-confidence').count() == 0


def test_warnings_render_inside_one_visible_alert(page_at_home: Page) -> None:
    page = page_at_home
    answer(page)
    upload(page)
    analyze(page)

    alert = page.locator("#warning-box")
    assert alert.is_visible()
    assert page.locator("#warnings li").count() == 2
    assert "categoria" in page.locator("#warnings li").first.inner_text()


def test_result_without_warnings_hides_the_alert(page_at_home: Page) -> None:
    page = page_at_home
    answer(page, {**RESULT, "warnings": []})
    upload(page)
    analyze(page)

    assert not page.locator("#warning-box").is_visible()


def test_a_response_in_flight_cannot_land_on_a_new_selection(page_at_home: Page) -> None:
    page = page_at_home
    held = []
    page.route("**/api/extract", lambda route: held.append(route))

    upload(page, "primeiro.png")
    page.click("#submit")
    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "a requisição não chegou a ser feita"

    upload(page, "segundo.png")
    try:
        held[0].fulfill(
            status=200, content_type="application/json", body=json.dumps(RESULT)
        )
    except Exception:
        pass  # The abort already killed the request, which is the point.
    page.wait_for_timeout(300)

    assert page.locator("#result").is_hidden()
    assert page.locator(".field-card").count() == 0
    assert "Tudo certo" not in page.locator("#status").inner_text()
    assert not page.locator("#submit").is_disabled()


def test_selecting_a_new_file_clears_the_previous_result(page_at_home: Page) -> None:
    page = page_at_home
    answer(page)
    upload(page)
    analyze(page)
    assert page.locator(".field-card").count() > 0

    upload(page, "outro.png")

    assert page.locator("#result").is_hidden()
    assert page.locator(".field-card").count() == 0
    assert page.locator("#raw-text").inner_text() == ""


def test_error_detail_from_the_api_reaches_the_status_line(page_at_home: Page) -> None:
    page = page_at_home
    answer(page, {"detail": "O arquivo excede o limite local de 15 MB."}, status=413)
    upload(page)
    page.click("#submit")
    page.wait_for_selector("#status.error")

    assert "excede o limite local" in page.locator("#status").inner_text()
    assert page.locator("#result").is_hidden()
    assert not page.locator("#submit").is_disabled()


def test_result_survives_a_narrow_viewport_without_sideways_scroll(page_at_home: Page) -> None:
    page = page_at_home
    answer(page)
    upload(page)
    analyze(page)

    page.set_viewport_size({"width": 620, "height": 780})
    page.wait_for_timeout(200)

    assert page.locator("#result").is_visible()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_copying_all_data_skips_the_fields_that_were_not_found(page_at_home: Page) -> None:
    page = page_at_home
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    answer(page)
    upload(page)
    analyze(page)

    page.click("#copy")
    page.wait_for_timeout(200)
    copied = page.evaluate("navigator.clipboard.readText()")

    assert "Nome: MARIA DE TESTE" in copied
    assert "Não identificado" not in copied
    assert "Validade" not in copied


def test_manual_editing_updates_copy_content(page_at_home: Page) -> None:
    page = page_at_home
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    answer(page)
    upload(page)
    analyze(page)

    name_field = page.locator('[data-field-label="name"] .field-value')
    name_field.fill("MARIA SILVA REVISADA")
    page.click("#copy")
    page.wait_for_timeout(200)
    copied = page.evaluate("navigator.clipboard.readText()")

    assert "Nome: MARIA SILVA REVISADA" in copied


def test_manual_filling_missing_field_enables_copy(page_at_home: Page) -> None:
    page = page_at_home
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    answer(page)
    upload(page)
    analyze(page)

    validity_card = page.locator('[data-field-label="validity"]')
    validity_field = validity_card.locator(".field-value")
    validity_copy = validity_card.locator(".field-copy")

    assert validity_card.get_attribute("data-found") == "false"
    assert validity_copy.is_disabled()

    validity_field.focus()
    validity_field.type("15/12/2030")

    assert validity_card.get_attribute("data-found") == "true"
    assert not validity_copy.is_disabled()

    page.click("#copy")
    page.wait_for_timeout(200)
    copied = page.evaluate("navigator.clipboard.readText()")

    assert "Validade: 15/12/2030" in copied


def test_zoom_buttons_adjust_focus_image_transform(page_at_home: Page) -> None:
    page = page_at_home
    body_with_preview = dict(RESULT)
    tiny_png = (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    body_with_preview["previews"] = [
        {
            "label": "Frente",
            "primary": True,
            "src": tiny_png,
        }
    ]
    answer(page, body=body_with_preview)
    upload(page, name="doc.pdf")
    analyze(page)

    focus_image = page.locator("#focus-image")
    page.click("#zoom-in")
    transform_after_zoom = focus_image.evaluate("el => el.style.transform")
    assert "scale(1.25)" in transform_after_zoom

    page.click("#zoom-reset")
    transform_after_reset = focus_image.evaluate("el => el.style.transform")
    assert "scale(1)" in transform_after_reset


def test_preview_panel_has_no_inner_scrollbar(page_at_home: Page) -> None:
    page = page_at_home
    body_with_preview = dict(RESULT)
    tiny_png = (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    body_with_preview["previews"] = [
        {"label": "Frente", "primary": True, "src": tiny_png}
    ]
    answer(page, body=body_with_preview)
    upload(page, name="doc.pdf")
    analyze(page)

    panel = page.locator("#preview-panel")
    scroll_height = panel.evaluate("el => el.scrollHeight")
    client_height = panel.evaluate("el => el.clientHeight")
    assert scroll_height <= client_height


def test_pasting_image_from_clipboard_populates_input(page_at_home: Page) -> None:
    page = page_at_home
    page.evaluate(
        """() => {
            const dt = new DataTransfer();
            const file = new File(["fake"], "print.png", { type: "image/png" });
            dt.items.add(file);
            window.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt }));
        }"""
    )
    assert not page.locator("#submit").is_disabled()
    assert "print.png" in page.locator("#status").inner_text()


def test_pasting_while_editing_field_does_not_replace_document(page_at_home: Page) -> None:
    page = page_at_home
    answer(page)
    upload(page, name="original.pdf")
    analyze(page)

    cpf_field = page.locator('[data-field-label="cpf"] .field-value')
    cpf_field.focus()

    page.evaluate(
        """() => {
            const dt = new DataTransfer();
            const file = new File(["fake"], "print.png", { type: "image/png" });
            dt.items.add(file);
            const target = document.querySelector('[data-field-label="cpf"] .field-value');
            target.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true }));
        }"""
    )

    assert not page.locator("#result").is_hidden()
    assert "print.png" not in page.locator("#status").inner_text()


def test_zoom_rotate_rotates_focus_image(page_at_home: Page) -> None:
    page = page_at_home
    body_with_preview = dict(RESULT)
    tiny_png = (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    body_with_preview["previews"] = [
        {"label": "Frente", "primary": True, "src": tiny_png}
    ]
    answer(page, body=body_with_preview)
    upload(page, name="doc.pdf")
    analyze(page)

    focus_image = page.locator("#focus-image")
    page.click("#zoom-rotate")
    transform = focus_image.evaluate("el => el.style.transform")
    assert "rotate(90deg)" in transform


def test_field_dynamic_validation_flags_invalid_values(page_at_home: Page) -> None:
    page = page_at_home
    answer(page)
    upload(page)
    analyze(page)

    cpf_field = page.locator('[data-field-label="cpf"] .field-value')
    cpf_field.fill("111.111.111-11")
    assert "field-invalid" in (cpf_field.get_attribute("class") or "")

    cpf_field.fill("123.456.789-09")
    assert "field-invalid" not in (cpf_field.get_attribute("class") or "")

    birth_field = page.locator('[data-field-label="birthDate"] .field-value')
    birth_field.fill("10/02/2099")
    assert "field-invalid" in (birth_field.get_attribute("class") or "")

    birth_field.fill("10/02/1990")
    assert "field-invalid" not in (birth_field.get_attribute("class") or "")

    validity_field = page.locator('[data-field-label="validity"] .field-value')
    validity_field.fill("10/02/2099")
    assert "field-invalid" in (validity_field.get_attribute("class") or "")

    validity_field.fill("10/02/2030")
    assert "field-invalid" not in (validity_field.get_attribute("class") or "")


def test_download_json_and_csv_trigger_downloads(page_at_home: Page) -> None:
    page = page_at_home
    answer(page)
    upload(page)
    analyze(page)

    with page.expect_download() as download_info:
        page.click("#download-json")
    download = download_info.value
    assert download.suggested_filename.endswith(".json")

    with page.expect_download() as download_info:
        page.click("#download-csv")
    download = download_info.value
    assert download.suggested_filename.endswith(".csv")


def test_download_csv_sanitizes_multiline_fields(page_at_home: Page) -> None:
    from pathlib import Path

    page = page_at_home
    body = {
        **RESULT,
        "fields": {
            **RESULT["fields"],
            "parentage": {
                "value": "MARIA MAE\nJOSE PAI",
                "confidence": "high",
                "label": "Filiação",
            },
        },
    }
    answer(page, body=body)
    upload(page)
    analyze(page)

    with page.expect_download() as download_info:
        page.click("#download-csv")
    download = download_info.value
    csv_path = download.path()
    assert csv_path is not None
    csv_text = Path(csv_path).read_text(encoding="utf-8")
    assert "MARIA MAE / JOSE PAI" in csv_text
    assert "MARIA MAE\n" not in csv_text


def test_copy_core_copies_only_values_without_labels(page_at_home: Page) -> None:
    page = page_at_home
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    answer(page)
    upload(page)
    analyze(page)

    page.click("#copy-core")
    page.wait_for_timeout(200)
    copied = page.evaluate("navigator.clipboard.readText()")

    assert "MARIA DE TESTE" in copied
    assert "123.456.789-09" in copied
    assert "10/02/1990" in copied
    assert "Nome:" not in copied
    assert "CPF:" not in copied


def test_image_upload_uses_interactive_focus_viewer_without_broken_preview(
    page_at_home: Page,
) -> None:
    page = page_at_home
    answer(page)
    upload(page, name="photo.png")
    analyze(page)

    assert page.locator("#focus-panel").is_visible()
    assert page.locator("#focus-image").is_visible()
    src = page.locator("#focus-image").get_attribute("src")
    assert src is not None and src.startswith("blob:")
    assert page.locator("#image-preview").is_hidden()


def test_status_shows_timer_and_analyzing_state_during_extraction(
    page_at_home: Page,
) -> None:
    page = page_at_home
    held = []
    page.route("**/api/extract", lambda route: held.append(route))

    upload(page, "doc.png")
    page.click("#submit")

    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(50)
    assert held, "a requisição não chegou a ser feita"

    status = page.locator("#status")
    assert "analyzing" in (status.get_attribute("class") or "")
    assert "Analisando seu documento" in status.inner_text()
    assert "s)" in status.inner_text()

    held[0].fulfill(
        status=200, content_type="application/json", body=json.dumps(RESULT)
    )
    page.wait_for_selector("#result:not(.hidden)")

    assert "analyzing" not in (status.get_attribute("class") or "")
    assert "Tudo certo" in status.inner_text()


def test_status_shows_formatted_elapsed_time_on_success(page_at_home: Page) -> None:
    page = page_at_home
    body = {**RESULT, "durationMs": 15812}
    answer(page, body=body)
    upload(page)
    analyze(page)

    status = page.locator("#status")
    assert (
        "Tudo certo em 15.8s! Confira as informações antes de copiar."
        in status.inner_text()
    )


def test_status_shows_fallback_message_when_duration_is_absent(page_at_home: Page) -> None:
    page = page_at_home
    body = {**RESULT, "durationMs": None}
    answer(page, body=body)
    upload(page)
    analyze(page)

    status = page.locator("#status")
    assert (
        "Tudo certo! Confira as informações antes de copiar."
        in status.inner_text()
    )


def test_dragging_file_over_upload_panel_activates_and_resets_drag_style(
    page_at_home: Page,
) -> None:
    page = page_at_home
    page.evaluate(
        """() => {
            const dt = new DataTransfer();
            const file = new File(["fake"], "documento.png", { type: "image/png" });
            dt.items.add(file);
            const panel = document.getElementById("upload-panel");
            panel.dispatchEvent(new DragEvent("dragenter", { dataTransfer: dt, bubbles: true }));
        }"""
    )
    assert "drag-active" in (page.locator("#upload-panel").get_attribute("class") or "")

    page.evaluate(
        """() => {
            const dt = new DataTransfer();
            const file = new File(["fake"], "documento.png", { type: "image/png" });
            dt.items.add(file);
            window.dispatchEvent(new DragEvent("dragleave", { dataTransfer: dt, bubbles: true }));
        }"""
    )
    assert "drag-active" not in (page.locator("#upload-panel").get_attribute("class") or "")


def test_dropping_file_on_upload_panel_populates_input(page_at_home: Page) -> None:
    page = page_at_home
    page.evaluate(
        """() => {
            const dt = new DataTransfer();
            const file = new File(["fake"], "documento_arrastado.png", { type: "image/png" });
            dt.items.add(file);
            const panel = document.getElementById("upload-panel");
            panel.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true }));
        }"""
    )
    assert not page.locator("#submit").is_disabled()
    assert "documento_arrastado.png" in page.locator("#status").inner_text()
    assert "drag-active" not in (page.locator("#upload-panel").get_attribute("class") or "")


def test_dropping_unsupported_file_shows_error(page_at_home: Page) -> None:
    page = page_at_home
    page.evaluate(
        """() => {
            const dt = new DataTransfer();
            const file = new File(["fake"], "documento.txt", { type: "text/plain" });
            dt.items.add(file);
            const panel = document.getElementById("upload-panel");
            panel.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true }));
        }"""
    )
    assert "Formato não suportado" in page.locator("#status").inner_text()
    assert "error" in (page.locator("#status").get_attribute("class") or "")


def test_ctrl_enter_triggers_document_analysis(page_at_home: Page) -> None:
    page = page_at_home
    answer(page)
    upload(page)

    page.keyboard.press("Control+Enter")
    page.wait_for_selector("#result:not(.hidden)")

    assert page.locator("#result").is_visible()
    assert page.locator('.field-card[data-found="true"]').count() > 0


def test_escape_resets_zoom_in_focus_panel(page_at_home: Page) -> None:
    page = page_at_home
    body_with_preview = dict(RESULT)
    tiny_png = (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    body_with_preview["previews"] = [
        {"label": "Frente", "primary": True, "src": tiny_png}
    ]
    answer(page, body=body_with_preview)
    upload(page, name="doc.pdf")
    analyze(page)

    focus_image = page.locator("#focus-image")
    page.click("#zoom-in")
    assert "scale(1.25)" in focus_image.evaluate("el => el.style.transform")

    page.keyboard.press("Escape")
    assert "scale(1)" in focus_image.evaluate("el => el.style.transform")


def test_copy_shortcuts_trigger_data_copy(page_at_home: Page) -> None:
    page = page_at_home
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    answer(page)
    upload(page)
    analyze(page)

    page.keyboard.press("Alt+c")
    page.wait_for_timeout(200)
    copied = page.evaluate("navigator.clipboard.readText()")

    assert "MARIA DE TESTE" in copied
    assert "123.456.789-09" in copied


def test_brand_header_and_logo_are_visible(page_at_home: Page) -> None:
    page = page_at_home
    assert page.title() == "ExtrAI — Extração inteligente de documentos"

    logo = page.locator(".app-logo")
    assert logo.is_visible()
    assert logo.get_attribute("src") == "/static/logo.png"

    heading = page.locator(".app-title-group h1")
    assert heading.inner_text() == "ExtrAI"

    subtitle = page.locator(".app-subtitle")
    assert subtitle.is_visible()
    assert subtitle.inner_text() == "Extração inteligente de documentos"

    answer(page)
    upload(page)
    analyze(page)

    assert not subtitle.is_visible()
    box = logo.bounding_box()
    assert box is not None
    assert round(box["width"]) == 28

