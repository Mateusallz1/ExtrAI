"""Browser tests for the flows that string checks cannot observe."""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path

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
    assert page.locator("#submit").inner_text() == "Parar análise"

    assert len(held) >= 2
    held[1].fulfill(
        status=200, content_type="application/json", body=json.dumps(RESULT)
    )
    page.wait_for_selector("#result:not(.hidden)")
    assert not page.locator("#submit").is_disabled()


def test_selecting_a_new_file_clears_the_previous_result(page_at_home: Page) -> None:
    page = page_at_home
    answer(page)
    upload(page)
    analyze(page)
    assert page.locator(".field-card").count() > 0

    held = []
    page.route("**/api/extract", lambda route: held.append(route))
    upload(page, "outro.png")

    assert page.locator("#result").is_hidden()
    assert page.locator(".field-card").count() == 0
    assert page.locator("#raw-text").inner_text() == ""
    assert "analyzing" in (page.locator("#status").get_attribute("class") or "")


def test_error_detail_from_the_api_reaches_the_status_line(page_at_home: Page) -> None:
    page = page_at_home
    answer(page, {"detail": "O arquivo excede o limite local de 15 MB."}, status=413)
    upload(page)
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


def test_copy_tsv_button_copies_tab_separated_row(page_at_home: Page) -> None:
    page = page_at_home
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    answer(page)
    upload(page)
    analyze(page)

    page.click("#copy-tsv")
    page.wait_for_timeout(200)
    copied = page.evaluate("navigator.clipboard.readText()")

    assert copied == "MARIA DE TESTE\t123.456.789-09\t10/02/1990"
    assert "Linha copiada (TSV)" in page.locator("#status").inner_text()


def test_copy_tsv_with_shift_includes_headers(page_at_home: Page) -> None:
    page = page_at_home
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    answer(page)
    upload(page)
    analyze(page)

    page.click("#copy-tsv", modifiers=["Shift"])
    page.wait_for_timeout(200)
    copied = page.evaluate("navigator.clipboard.readText()")

    lines = copied.splitlines()
    assert len(lines) == 2
    assert lines[0] == "Nome\tCPF\tData de nascimento"
    assert lines[1] == "MARIA DE TESTE\t123.456.789-09\t10/02/1990"
    assert "Linha com cabeçalhos copiada (TSV)" in page.locator("#status").inner_text()


def test_keyboard_shortcut_alt_t_triggers_copy_tsv(page_at_home: Page) -> None:
    page = page_at_home
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    answer(page)
    upload(page)
    analyze(page)

    page.keyboard.press("Alt+t")
    page.wait_for_timeout(200)
    copied = page.evaluate("navigator.clipboard.readText()")

    assert copied == "MARIA DE TESTE\t123.456.789-09\t10/02/1990"


def test_copy_tsv_sanitizes_spreadsheet_formulas(page_at_home: Page) -> None:
    page = page_at_home
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    body = {
        **RESULT,
        "fields": {
            "name": {"value": "=cmd|' /C calc'!A0", "confidence": "high", "label": "Nome"},
        },
    }
    answer(page, body=body)
    upload(page)
    analyze(page)

    page.click("#copy-tsv")
    page.wait_for_timeout(200)
    copied = page.evaluate("navigator.clipboard.readText()")

    assert copied.startswith("'=cmd")


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


def test_mobile_preview_fits_the_entire_card_at_initial_zoom(page_at_home: Page) -> None:
    page = page_at_home
    page.set_viewport_size({"width": 390, "height": 844})
    card_png = page.evaluate(
        """() => {
          const canvas = document.createElement('canvas');
          canvas.width = 1000;
          canvas.height = 650;
          return canvas.toDataURL('image/png');
        }"""
    )
    body = {
        **RESULT,
        "warnings": [],
        "previews": [{"label": "Frente", "primary": True, "src": card_png}],
    }
    answer(page, body)
    upload(page)
    analyze(page)
    page.wait_for_function('document.querySelector("#focus-image").naturalWidth === 1000')

    bounds = page.locator("#focus-image-container").evaluate(
        """container => {
          const image = container.querySelector('img');
          const outer = container.getBoundingClientRect();
          const inner = image.getBoundingClientRect();
          return {outer: outer.toJSON(), inner: inner.toJSON(), transform: image.style.transform};
        }"""
    )
    assert "scale(1)" in bounds["transform"]
    assert bounds["inner"]["top"] >= bounds["outer"]["top"]
    assert bounds["inner"]["bottom"] <= bounds["outer"]["bottom"]
    assert bounds["inner"]["left"] >= bounds["outer"]["left"]
    assert bounds["inner"]["right"] <= bounds["outer"]["right"]


def test_all_warnings_remain_reachable_in_a_short_desktop_viewport(
    page_at_home: Page,
) -> None:
    page = page_at_home
    page.set_viewport_size({"width": 1280, "height": 650})
    body = {
        **RESULT,
        "warnings": [
            f"Aviso sintético {index}: " + "Confira os dados do documento. " * 5
            for index in range(8)
        ],
    }
    answer(page, body)
    upload(page)
    analyze(page)
    last_warning = page.locator("#warnings li").last
    last_warning.scroll_into_view_if_needed()

    bounds = last_warning.evaluate(
        """warning => ({
          warning: warning.getBoundingClientRect().toJSON(),
          panel: document.querySelector('#preview-panel').getBoundingClientRect().toJSON(),
          overflow: getComputedStyle(document.querySelector('#preview-panel')).overflowY,
        })"""
    )
    assert bounds["overflow"] == "auto"
    assert bounds["warning"]["top"] >= bounds["panel"]["top"]
    assert bounds["warning"]["bottom"] <= bounds["panel"]["bottom"]


def test_pasting_image_from_clipboard_populates_input(page_at_home: Page) -> None:
    page = page_at_home
    answer(page)
    page.evaluate(
        """() => {
            const dt = new DataTransfer();
            const file = new File(["fake"], "print.png", { type: "image/png" });
            dt.items.add(file);
            window.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt }));
        }"""
    )
    page.wait_for_selector("#result:not(.hidden)")
    assert page.locator('.field-card[data-found="true"]').count() > 0
    assert (
        page.evaluate('() => document.getElementById("document").files[0]?.name')
        == "print.png"
    )


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
    validity_badge = page.locator('[data-field-label="validity"] .field-badge-expired')
    validity_field.fill("10/02/2099")
    assert "field-invalid" in (validity_field.get_attribute("class") or "")

    validity_field.fill("10/02/2020")
    assert "field-invalid" not in (validity_field.get_attribute("class") or "")
    assert "hidden" not in (validity_badge.get_attribute("class") or "")

    validity_field.fill("10/02/2030")
    assert "field-invalid" not in (validity_field.get_attribute("class") or "")
    assert "hidden" in (validity_badge.get_attribute("class") or "")


def test_cross_field_temporal_inconsistency_is_flagged(page_at_home: Page) -> None:
    page = page_at_home
    body = {
        **RESULT,
        "fields": {
            **RESULT["fields"],
            "birthDate": {
                "value": "10/02/2000",
                "confidence": "high",
                "label": "Data de nascimento",
            },
            "issueDate": {
                "value": "10/02/1990",
                "confidence": "high",
                "label": "Data de emissão",
            },
        },
    }
    answer(page, body=body)
    upload(page)
    analyze(page)

    birth_field = page.locator('[data-field-label="birthDate"] .field-value')
    issue_field = page.locator('[data-field-label="issueDate"] .field-value')

    assert "field-temporal-inconsistent" in (birth_field.get_attribute("class") or "")
    assert "field-temporal-inconsistent" in (issue_field.get_attribute("class") or "")

    # Fix the issue date
    issue_field.fill("10/02/2020")
    page.locator("#summary").click()

    assert "field-temporal-inconsistent" not in (birth_field.get_attribute("class") or "")
    assert "field-temporal-inconsistent" not in (issue_field.get_attribute("class") or "")


@pytest.mark.parametrize(
    ("key", "value", "valid_value", "label"),
    [
        ("cpf", "123", "123.456.789-09", "CPF"),
        ("birthDate", "31/02/20", "10/02/1990", "Data de nascimento"),
        ("validity", "15/12", "15/12/2030", "Validade"),
    ],
)
def test_incomplete_manual_value_is_flagged_after_blur_and_export_warns(
    page_at_home: Page, key: str, value: str, valid_value: str, label: str
) -> None:
    page = page_at_home
    answer(page)
    upload(page)
    analyze(page)
    field = page.locator(f'[data-field-label="{key}"] .field-value')
    field.fill(value)
    assert field.get_attribute("aria-invalid") == "false"
    page.locator("#summary").click()
    assert field.get_attribute("aria-invalid") == "true"
    assert "inválido ou incompleto" in (field.get_attribute("title") or "")

    with page.expect_download() as download_info:
        page.click("#download-json")
    download_path = download_info.value.path()
    assert download_path is not None
    data = json.loads(Path(download_path).read_text(encoding="utf-8"))
    assert data["dados"][label] == value  # Manual overrides remain available for review.
    assert "campos inválidos ou incompletos" in page.locator("#status").inner_text()

    field.fill(valid_value)
    page.locator("#summary").click()
    assert field.get_attribute("aria-invalid") == "false"
    assert "field-invalid" not in (field.get_attribute("class") or "")


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=1+1", "'=1+1"),
        ("+SUM(1;2)", "'+SUM(1;2)"),
        ("-1+1", "'-1+1"),
        ("@SUM(1,2)", "'@SUM(1,2)"),
        ("  \t=1+1", "'=1+1"),
        ("\x00\t=1+1", "'\x00\t=1+1"),
        ("\x1f\x7f@SUM(1,2)", "'\x1f\x7f@SUM(1,2)"),
        ('MARIA "TESTE"', 'MARIA "TESTE"'),
    ],
)
def test_download_csv_exports_formula_prefixes_as_literal_text(
    page_at_home: Page, value: str, expected: str
) -> None:
    page = page_at_home
    body = {
        **RESULT,
        "fields": {**RESULT["fields"], "name": {"value": value, "label": "Nome"}},
    }
    answer(page, body)
    upload(page)
    analyze(page)

    with page.expect_download() as download_info:
        page.click("#download-csv")
    download_path = download_info.value.path()
    assert download_path is not None
    exported = Path(download_path).read_text(encoding="utf-8-sig")
    rows = list(csv.reader(StringIO(exported), delimiter=";"))
    assert rows[0] == ["Campo", "Valor"]
    assert rows[1] == ["Nome", expected]
    assert all(len(row) == 2 for row in rows)


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
    answer(page)
    page.evaluate(
        """() => {
            const dt = new DataTransfer();
            const file = new File(["fake"], "documento_arrastado.png", { type: "image/png" });
            dt.items.add(file);
            const panel = document.getElementById("upload-panel");
            panel.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true }));
        }"""
    )
    page.wait_for_selector("#result:not(.hidden)")
    assert page.locator('.field-card[data-found="true"]').count() > 0
    assert (
        page.evaluate('() => document.getElementById("document").files[0]?.name')
        == "documento_arrastado.png"
    )
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
    assert page.locator("#result").is_hidden()


def test_selecting_unsupported_file_shows_error(page_at_home: Page) -> None:
    page = page_at_home
    page.set_input_files(
        "#document",
        files=[{"name": "test.txt", "mimeType": "text/plain", "buffer": b"test"}],
    )
    assert "Formato não suportado" in page.locator("#status").inner_text()
    assert "error" in (page.locator("#status").get_attribute("class") or "")
    assert page.locator("#result").is_hidden()
    assert page.locator("#submit").is_disabled()


def test_selecting_file_automatically_starts_extraction_without_submit_click(
    page_at_home: Page,
) -> None:
    page = page_at_home
    answer(page)
    upload(page, "auto.png")
    page.wait_for_selector("#result:not(.hidden)")
    assert page.locator('.field-card[data-found="true"]').count() > 0
    assert page.locator("#result").is_visible()


def test_ctrl_enter_triggers_document_analysis(page_at_home: Page) -> None:
    page = page_at_home
    requests: list[str] = []
    page.route(
        "**/api/extract",
        lambda route: (
            requests.append(route.request.url),
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(RESULT),
            ),
        ),
    )
    upload(page)
    page.wait_for_selector("#result:not(.hidden)")
    assert len(requests) == 1

    page.keyboard.press("Control+Enter")
    for _ in range(50):
        if len(requests) == 2:
            break
        page.wait_for_timeout(50)
    assert len(requests) == 2
    page.wait_for_selector("#result:not(.hidden)")
    assert page.locator("#result").is_visible()


def test_manual_submit_button_adapts_to_clear_when_results_are_visible(page_at_home: Page) -> None:
    page = page_at_home
    requests: list[str] = []
    page.route(
        "**/api/extract",
        lambda route: (
            requests.append(route.request.url),
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(RESULT),
            ),
        ),
    )
    upload(page)
    page.wait_for_selector("#result:not(.hidden)")
    assert len(requests) == 1

    submit = page.locator("#submit")
    assert submit.inner_text() == "Limpar análise"
    assert "secondary" in (submit.get_attribute("class") or "")

    submit.click()
    page.wait_for_timeout(100)
    assert page.locator("#result").is_hidden()
    assert submit.inner_text() == "Analisar documento"
    assert "secondary" not in (submit.get_attribute("class") or "")


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


def test_clicking_field_value_directly_copies_content(page_at_home: Page) -> None:
    page = page_at_home
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    answer(page)
    upload(page)
    analyze(page)

    name_field = page.locator('[data-field-label="name"] .field-value')
    assert name_field.get_attribute("title") == "Clique para copiar ou editar"
    name_field.click()
    page.wait_for_timeout(200)

    copied = page.evaluate("navigator.clipboard.readText()")
    assert copied == "MARIA DE TESTE"
    assert page.locator("#status").inner_text() == "Nome copiado."
    assert "field-copied" in (name_field.get_attribute("class") or "")


def test_dark_mode_applies_white_filter_to_logo(page: Page, live_server: str) -> None:
    page.emulate_media(color_scheme="dark")
    page.goto(live_server)
    logo = page.locator(".app-logo")
    assert logo.is_visible()
    logo_filter = logo.evaluate("el => window.getComputedStyle(el).filter")
    assert "brightness(0)" in logo_filter and "invert(1)" in logo_filter


def test_submit_button_adapts_to_clear_and_resets_home_view(page_at_home: Page) -> None:
    page = page_at_home
    answer(page)
    upload(page)
    analyze(page)

    submit = page.locator("#submit")
    assert page.locator("#result").is_visible()
    assert page.locator("#intro-copy").is_hidden()
    assert submit.inner_text() == "Limpar análise"
    assert "secondary" in (submit.get_attribute("class") or "")

    submit.click()
    page.wait_for_timeout(100)

    assert page.locator("#result").is_hidden()
    assert page.locator("#intro-copy").is_visible()
    assert submit.inner_text() == "Analisar documento"
    assert "secondary" not in (submit.get_attribute("class") or "")
    assert page.locator(".field-card").count() == 0
    assert page.locator("#raw-text").inner_text() == ""
    assert page.evaluate("() => document.body.classList.contains('has-extracted')") is False
    assert page.evaluate("() => document.getElementById('document').value") == ""


def test_clear_via_keyboard_shortcut(page_at_home: Page) -> None:
    page = page_at_home
    answer(page)
    upload(page)
    analyze(page)

    assert page.locator("#result").is_visible()
    page.keyboard.press("Alt+l")
    page.wait_for_timeout(100)

    assert page.locator("#result").is_hidden()
    assert page.locator("#intro-copy").is_visible()
    assert page.locator("#submit").inner_text() == "Analisar documento"


def test_unsupported_document_displays_friendly_guidance_and_adapted_summary(
    page_at_home: Page,
) -> None:
    page = page_at_home
    body = {
        "kind": "unknown",
        "pages": 1,
        "fields": {},
        "missing": [
            {"key": "name", "label": "Nome"},
            {"key": "cpf", "label": "CPF"},
            {"key": "birthDate", "label": "Data de nascimento"},
        ],
        "text": "COMPROVANTE DE RESIDENCIA",
        "warnings": [
            "O documento aparenta ser um comprovante de residência. "
            "O ExtrAI suporta atualmente RG e CNH."
        ],
        "durationMs": 15,
        "previews": [],
    }
    answer(page, body=body)
    upload(page)
    analyze(page)

    assert page.locator("#summary").inner_text() == "Documento não suportado • 1 página"
    assert page.locator("#warning-box").is_visible()
    assert page.locator("#warnings-title").inner_text() == "Documento não suportado"
    assert "comprovante de residência" in page.locator("#warnings").inner_text()
    assert "RG e CNH" in page.locator("#warnings").inner_text()


def test_stop_analysis_via_button(page_at_home: Page) -> None:
    page = page_at_home
    page.route("**/api/extract", lambda route: None)
    upload(page)

    submit = page.locator("#submit")
    page.wait_for_function('document.querySelector("#submit").textContent === "Parar análise"')
    assert submit.inner_text() == "Parar análise"
    assert submit.get_attribute("type") == "button"
    assert page.locator("#status").inner_text().startswith("Analisando")

    submit.click()
    page.wait_for_function('document.querySelector("#submit").textContent === "Analisar documento"')
    assert submit.inner_text() == "Analisar documento"
    assert page.locator("#status").inner_text() == "Análise cancelada."


def test_stop_analysis_via_escape_key(page_at_home: Page) -> None:
    page = page_at_home
    page.route("**/api/extract", lambda route: None)
    upload(page)

    submit = page.locator("#submit")
    page.wait_for_function('document.querySelector("#submit").textContent === "Parar análise"')
    assert submit.inner_text() == "Parar análise"

    page.keyboard.press("Escape")
    page.wait_for_function('document.querySelector("#submit").textContent === "Analisar documento"')
    assert submit.inner_text() == "Analisar documento"
    assert page.locator("#status").inner_text() == "Análise cancelada."


def test_cin_document_renders_summary_and_fields(page_at_home: Page) -> None:
    page = page_at_home
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    cin_data = {
        "kind": "cin",
        "pages": 1,
        "fields": {
            "name": {"value": "CARLOS EDUARDO SILVA", "confidence": "high", "label": "Nome"},
            "cpf": {"value": "123.456.789-09", "confidence": "high", "label": "CPF"},
            "birthDate": {
                "value": "15/05/1960",
                "confidence": "high",
                "label": "Data de nascimento",
            },
            "issueDate": {"value": "10/01/2024", "confidence": "high", "label": "Data de emissão"},
            "validity": {"value": "INDETERMINADA", "confidence": "high", "label": "Validade"},
        },
        "missing": [
            {"key": "birthPlace", "label": "Local de nascimento"},
            {"key": "nationality", "label": "Nacionalidade"},
            {"key": "parentage", "label": "Filiação"},
        ],
        "text": "CARTEIRA DE IDENTIDADE NACIONAL",
        "warnings": [],
        "durationMs": 420,
        "previews": [],
    }
    answer(page, body=cin_data)
    upload(page)
    analyze(page)

    assert page.locator("#summary").inner_text() == "CIN identificada • 1 página"
    validity_card = page.locator('.field-card[data-field-label="validity"]')
    assert "INDETERMINADA" in validity_card.inner_text()
    card_classes = validity_card.locator(".field-value").get_attribute("class") or ""
    assert "field-invalid" not in card_classes

    page.click("#copy")
    page.wait_for_timeout(200)
    copied = page.evaluate("navigator.clipboard.readText()")
    assert "FICHA CADASTRAL — CIN" in copied
    assert "Nome: CARLOS EDUARDO SILVA" in copied
    assert "Validade: INDETERMINADA" in copied


def test_render_integrity_low_risk_physical_original(page_at_home: Page) -> None:
    page = page_at_home
    doc_data = {
        "kind": "cnh",
        "pages": 1,
        "fields": {
            "name": {"value": "MARIA DE TESTE", "confidence": "high", "label": "Nome"},
        },
        "missing": [],
        "text": "DOCUMENTO: CNH",
        "warnings": [],
        "durationMs": 100,
        "previews": [],
        "integrity": {
            "mediaType": "physical_original",
            "riskLevel": "low",
            "tamperingDetected": False,
            "flags": ["Padrão gráfico e microletras íntegros"],
        },
    }
    answer(page, body=doc_data)
    upload(page)
    analyze(page)

    box = page.locator("#integrity-box")
    assert "hidden" not in (box.get_attribute("class") or "")
    badge = page.locator("#integrity-risk-badge")
    assert badge.inner_text() == "Risco baixo"
    assert "integrity-badge-low" in (badge.get_attribute("class") or "")
    media_text = page.locator("#integrity-media-type").inner_text()
    assert "Documento físico original" in media_text
    flags_text = page.locator("#integrity-flags").inner_text()
    assert "Padrão gráfico e microletras íntegros" in flags_text

    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.click("#copy")
    page.wait_for_timeout(200)
    copied = page.evaluate("navigator.clipboard.readText()")
    assert "INTEGRIDADE E DOCUMENTOSCOPIA" in copied
    assert "Mídia: Documento físico original" in copied
    assert "Risco: Risco baixo" in copied

    with page.expect_download() as download_info:
        page.click("#download-json")
    download_path = download_info.value.path()
    assert download_path is not None
    data = json.loads(Path(download_path).read_text(encoding="utf-8"))
    assert "integridade" in data
    assert data["integridade"]["mediaType"] == "physical_original"


def test_render_integrity_tampering_detected_high_risk(page_at_home: Page) -> None:
    page = page_at_home
    doc_data = {
        "kind": "rg",
        "pages": 1,
        "fields": {
            "name": {"value": "JOAO DA SILVA", "confidence": "high", "label": "Nome"},
        },
        "missing": [],
        "text": "DOCUMENTO: RG",
        "warnings": ["Possível adulteração visual ou manipulação digital detectada."],
        "durationMs": 150,
        "previews": [],
        "integrity": {
            "mediaType": "physical_original",
            "riskLevel": "high",
            "tamperingDetected": True,
            "flags": ["Recorte artificial na foto 3x4 detectado"],
        },
    }
    answer(page, body=doc_data)
    upload(page)
    analyze(page)

    badge = page.locator("#integrity-risk-badge")
    assert badge.inner_text() == "Risco alto"
    assert "integrity-badge-high" in (badge.get_attribute("class") or "")
    flags_text = page.locator("#integrity-flags").inner_text()
    assert "Alerta: Evidências visuais de adulteração ou manipulação digital." in flags_text
    assert "Recorte artificial na foto 3x4 detectado" in flags_text


def test_clear_extraction_hides_integrity_box(page_at_home: Page) -> None:
    page = page_at_home
    doc_data = {
        "kind": "cnh",
        "pages": 1,
        "fields": {
            "name": {"value": "MARIA DE TESTE", "confidence": "high", "label": "Nome"},
        },
        "missing": [],
        "text": "DOCUMENTO: CNH",
        "warnings": [],
        "durationMs": 80,
        "previews": [],
        "integrity": {
            "mediaType": "physical_original",
            "riskLevel": "low",
            "tamperingDetected": False,
            "flags": [],
        },
    }
    answer(page, body=doc_data)
    upload(page)
    analyze(page)

    box = page.locator("#integrity-box")
    assert "hidden" not in (box.get_attribute("class") or "")

    submit = page.locator("#submit")
    assert submit.inner_text() == "Limpar análise"
    submit.click()
    page.wait_for_timeout(100)
    assert page.locator("#result").is_hidden()
    assert "hidden" in (box.get_attribute("class") or "")




