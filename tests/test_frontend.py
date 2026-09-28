from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).parents[1] / "src" / "doc_extractor_pydantic" / "static"
MARKUP = (STATIC / "index.html").read_text(encoding="utf-8")
STYLES = (STATIC / "app.css").read_text(encoding="utf-8")
SCRIPT = (STATIC / "app.js").read_text(encoding="utf-8")
# The page is split into three files so the CSP can drop 'unsafe-inline'.
INDEX_HTML = MARKUP + STYLES + SCRIPT


def test_the_page_carries_no_inline_style_or_script() -> None:
    assert "<style" not in MARKUP
    assert "<script>" not in MARKUP
    assert 'href="/static/app.css"' in MARKUP
    assert 'src="/static/app.js"' in MARKUP
    assert "style=" not in MARKUP


def test_extracted_fields_are_display_only_and_have_copy_icon() -> None:
    assert 'document.createElement("input")' not in INDEX_HTML
    assert 'querySelectorAll("input[data-field]")' not in INDEX_HTML
    assert 'className = "field-value"' in INDEX_HTML
    assert 'class="copy-icon"' in INDEX_HTML
    assert '.field-card[data-field-label="parentage"] { grid-column: 1 / -1; }' in INDEX_HTML
    assert "white-space: pre-wrap" in INDEX_HTML


def test_pdf_uses_embedded_detail_instead_of_full_viewer() -> None:
    assert 'id="pdf-viewer"' not in INDEX_HTML
    assert 'id="pdf-preview"' not in INDEX_HTML
    assert "pdfViewer" not in INDEX_HTML
    assert "updatePdfPreview" not in INDEX_HTML
    assert 'id="focus-image"' in INDEX_HTML
    assert 'id="focus-zoom-in"' not in INDEX_HTML
    assert 'id="focus-zoom-out"' not in INDEX_HTML


def test_pdf_result_exposes_main_embedded_image_preview() -> None:
    assert 'id="focus-panel"' in INDEX_HTML
    assert 'id="focus-image"' in INDEX_HTML
    assert 'id="focus-thumbnails"' in INDEX_HTML
    assert "renderFocusPreviews(data.previews, data.kind)" in INDEX_HTML


def test_selecting_a_new_file_clears_previous_result() -> None:
    change_handler = INDEX_HTML.split('input.addEventListener("change"', maxsplit=1)[1]
    change_handler = change_handler.split('form.addEventListener("submit"', maxsplit=1)[0]
    assert "lastData = null;" in change_handler
    assert 'result.classList.add("hidden");' in change_handler
    assert "fields.replaceChildren();" in change_handler
    assert 'rawText.textContent = "";' in change_handler


def test_low_and_medium_confidence_reach_the_user() -> None:
    assert 'confidenceLabels = { medium: "conferir", low: "conferir com atenção" }' in INDEX_HTML
    assert 'badge.className = "field-confidence"' in INDEX_HTML
    assert 'badge.dataset.confidence = value.confidence;' in INDEX_HTML
    assert '.field-confidence[data-confidence="medium"]' in INDEX_HTML
    assert '.field-confidence[data-confidence="low"]' in INDEX_HTML
    # High confidence stays quiet, so the badge only marks what needs a check.
    assert "confidenceLabels[value.confidence]" in INDEX_HTML


def test_expected_fields_stay_visible_when_not_identified() -> None:
    assert "Array.isArray(data.missing) ? data.missing : []" in INDEX_HTML
    assert 'card.dataset.found = value.value ? "true" : "false";' in INDEX_HTML
    assert '.field-card[data-found="false"] .field-value' in INDEX_HTML
    assert 'Não identificado' in INDEX_HTML


def test_copying_all_data_skips_the_fields_that_were_not_found() -> None:
    assert "fields.querySelectorAll('.field-card[data-found=\"true\"]')" in INDEX_HTML


def test_selecting_a_new_file_cancels_the_running_analysis() -> None:
    change_handler = INDEX_HTML.split('input.addEventListener("change"', maxsplit=1)[1]
    change_handler = change_handler.split('form.addEventListener("submit"', maxsplit=1)[0]
    assert "requestId += 1;" in change_handler
    assert "if (pendingRequest) pendingRequest.abort();" in change_handler


def test_late_response_cannot_overwrite_the_current_file() -> None:
    submit_handler = INDEX_HTML.split('form.addEventListener("submit"', maxsplit=1)[1]
    submit_handler = submit_handler.split("function renderResult", maxsplit=1)[0]
    assert "const controller = new AbortController();" in submit_handler
    assert "signal: controller.signal" in submit_handler
    assert "const currentRequest = requestId;" in submit_handler
    # Guards for the analysis timer, before rendering, before showing an error,
    # and before re-enabling.
    assert submit_handler.count("currentRequest !== requestId") == 3

    assert "if (currentRequest === requestId) {" in submit_handler
    assert 'error.name === "AbortError"' in submit_handler


def test_copy_failure_has_a_friendly_message() -> None:
    assert "Não foi possível copiar." in INDEX_HTML
    assert "Selecione o texto e copie manualmente." in INDEX_HTML


def test_shadcn_style_tokens_and_interaction_states_are_defined() -> None:
    assert "--background:" in INDEX_HTML
    assert "--primary:" in INDEX_HTML
    assert "--muted:" in INDEX_HTML
    assert "--border:" in INDEX_HTML
    assert "border-radius: 6px" in INDEX_HTML
    assert "button:focus-visible" in INDEX_HTML
    assert 'input[type="file"]::file-selector-button' in INDEX_HTML


def test_text_outputs_grow_without_internal_scrollbars() -> None:
    assert ".recognized-text { min-height: 96px; height: auto;" in INDEX_HTML
    assert "overflow: visible; overflow-wrap: anywhere; white-space: pre-wrap" in INDEX_HTML
    assert (
        ".focus-thumbnails { width: 90%; margin-inline: auto; "
        "display: flex; flex-wrap: wrap;"
        in INDEX_HTML
    )


def test_upload_and_results_use_space_efficient_layouts() -> None:
    assert ".upload { display: grid; grid-template-columns: minmax(0, 1fr) auto;" in INDEX_HTML
    assert (
        ".fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));"
        in INDEX_HTML
    )
    assert '<details class="raw-details">' in INDEX_HTML
    assert "<summary>Texto do documento</summary>" in INDEX_HTML


def test_status_message_is_compact_and_reserves_no_empty_space() -> None:
    assert ".status { margin-top: 10px; min-height: 0;" in INDEX_HTML
    assert "font-size: 0.8125rem; line-height: 1.35" in INDEX_HTML
    assert ".status:empty { display: none; }" in INDEX_HTML


def test_intro_copy_is_replaced_by_a_compact_new_extraction_area() -> None:
    assert 'id="intro-copy"' in INDEX_HTML
    assert 'id="upload-label" class="upload-label hidden">Nova extração' in INDEX_HTML
    render_result = INDEX_HTML.split("function renderResult(data)", maxsplit=1)[1]
    assert 'document.body.classList.add("has-extracted");' in render_result
    assert 'introCopy.classList.add("hidden");' in render_result
    assert 'uploadLabel.classList.remove("hidden");' in render_result


def test_extracted_results_use_the_reclaimed_vertical_space() -> None:
    assert (
        "body.has-extracted .layout { height: var(--result-height, auto); }"
        in INDEX_HTML
    )
    assert "body.has-extracted .layout > .panel { overflow: auto; }" in INDEX_HTML
    assert "body.has-extracted .layout { height: auto; }" in INDEX_HTML
    assert "function syncResultHeight()" in INDEX_HTML
    assert 'result.style.setProperty("--result-height", `${available}px`);' in INDEX_HTML


def test_scrollbars_are_subtle_but_remain_interactive() -> None:
    assert "scrollbar-color: transparent transparent" in INDEX_HTML
    assert "scrollbar-color: #a1a1aa99 transparent" in INDEX_HTML
    assert "::-webkit-scrollbar-thumb { background: transparent;" in INDEX_HTML
    assert ":hover::-webkit-scrollbar-thumb { background: #a1a1aa99;" in INDEX_HTML


def test_main_uses_the_full_available_width() -> None:
    assert "main { width: 100%; max-width: none; box-sizing: border-box;" in INDEX_HTML
    assert "padding: 40px clamp(20px, 4vw, 64px) 64px;" in INDEX_HTML


def test_document_detail_options_are_visible_and_navigable() -> None:
    assert (
        ".focus-image-container { height: clamp(260px, 42vh, 520px); overflow: auto;"
        in INDEX_HTML
    )
    assert (
        ".focus-image-container.focus-fit { width: 90%; margin-inline: auto; "
        "overflow: hidden;"
        in INDEX_HTML
    )
    assert (
        ".focus-fit .focus-image { width: 95%; height: 95%; "
        "max-width: 95%; max-height: 95%;"
        in INDEX_HTML
    )
    assert ".focus-fit .focus-image.focus-image-qr { width: 220px; height: 220px;" in INDEX_HTML
    assert ".focus-thumbnails { width: 90%; margin-inline: auto;" in INDEX_HTML
    assert "thumbnail.append(image);" in INDEX_HTML
    assert "function fitFocusImage(preview)" in INDEX_HTML
    assert (
        "const aspectRatio = sourceWidth && sourceHeight ? sourceWidth / sourceHeight : 0;"
        in INDEX_HTML
    )
    assert "const isCardDocument = aspectRatio >= 1.25" in INDEX_HTML
    assert "Math.abs(aspectRatio - 1) < 0.08" in INDEX_HTML
    assert "Math.min(300, availableHeight)" in INDEX_HTML
    assert (
        'focusImage.classList.toggle("focus-image-qr", shouldFit && isSmallSquare);'
        in INDEX_HTML
    )
    assert "Math.min(520, resultHeight - 176)) * 0.9" in INDEX_HTML
    assert "focusImageContainer.classList.toggle(\"focus-fit\", shouldFit);" in INDEX_HTML
    assert "if (!shouldFit)" in INDEX_HTML
    assert 'focusImageContainer.style.height = `${Math.round(targetHeight)}px`;' in INDEX_HTML
    assert "renderFocusPreviews(data.previews, data.kind)" in INDEX_HTML


def test_warnings_render_inside_one_visible_alert() -> None:
    assert 'id="warning-box" class="warning-box hidden" role="alert"' in INDEX_HTML
    assert 'id="warnings" class="warnings"' in INDEX_HTML
    assert "const warningItems = Array.isArray(data.warnings)" in INDEX_HTML
    assert "warningBox.classList.toggle(\"hidden\", !warningItems.length);" in INDEX_HTML
    assert "warnings.replaceChildren(...warningItems.map" in INDEX_HTML


def test_results_use_a_viewport_workspace_on_desktop() -> None:
    assert "body.has-result { overflow: hidden; }" in INDEX_HTML
    assert "height: min(680px, calc(100dvh - 420px));" in INDEX_HTML
    assert ".layout > .panel { min-height: 0; overflow: auto; }" in INDEX_HTML
    assert "body.has-result { overflow: auto; }" in INDEX_HTML
    assert 'document.body.classList.add("has-result");' in INDEX_HTML
    assert 'document.body.classList.remove("has-result");' in INDEX_HTML


def test_status_feedback_supports_live_progress_and_timer() -> None:
    assert ".status.analyzing" in INDEX_HTML
    assert "formatProgressMessage(elapsed)" in INDEX_HTML
    assert "formatSuccessMessage(durationMs)" in INDEX_HTML
    assert "formatSuccessMessage(data.durationMs)" in INDEX_HTML
    assert "analysisTimer = setInterval" in INDEX_HTML
    assert "clearInterval(analysisTimer)" in INDEX_HTML


def test_upload_panel_supports_drag_and_drop_interaction() -> None:
    assert "#upload-panel.drag-active" in INDEX_HTML
    assert 'uploadPanel.classList.add("drag-active")' in INDEX_HTML
    assert 'uploadPanel.classList.remove("drag-active")' in INDEX_HTML
    assert "handleDrop(e)" in INDEX_HTML


def test_keyboard_shortcuts_support_submit_escape_and_copy() -> None:
    assert 'window.addEventListener("keydown"' in INDEX_HTML
    assert 'e.key === "Enter"' in INDEX_HTML
    assert 'e.key === "Escape"' in INDEX_HTML
    assert 'title="Analisar documento (Ctrl+Enter)"' in INDEX_HTML
    assert "Ctrl+Shift+C" in INDEX_HTML


def test_branding_and_favicon_are_configured() -> None:
    assert "<title>ExtrAI — Extração inteligente de documentos</title>" in MARKUP
    assert '<link rel="icon" type="image/x-icon" href="/favicon.ico" />' in MARKUP
    assert '<link rel="apple-touch-icon" href="/static/logo.png" />' in MARKUP
    assert '<header class="app-header">' in MARKUP
    assert '<img class="app-logo" src="/static/logo.png" alt="ExtrAI"' in MARKUP
    assert "<h1>ExtrAI</h1>" in MARKUP
    assert '<span class="app-subtitle">Extração inteligente de documentos</span>' in MARKUP
    assert ".app-header {" in STYLES
    assert ".app-logo {" in STYLES
    assert "body.has-extracted .app-logo { width: 28px; height: 28px; }" in STYLES
    assert "body.has-extracted .app-subtitle { display: none; }" in STYLES
