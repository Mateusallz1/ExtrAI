"""Automated tests for ExtrAI Chrome extension content script and form filling."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Page  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONTENT_JS = (ROOT / "extension" / "content" / "content.js").read_text(encoding="utf-8")
MODELO_HTML = (ROOT / "docs" / "base" / "modelo.html").read_text(encoding="utf-8")

SYNTHETIC_DATA = {
    "kind": "cnh",
    "pages": 1,
    "fields": {
        "name": {"value": "MARIA DA SILVA", "label": "Nome"},
        "cpf": {"value": "123.456.789-09", "label": "CPF"},
        "birthDate": {"value": "15/05/1990", "label": "Data de nascimento"},
        "registration": {"value": "01234567890", "label": "Registro"},
    },
}

EMISSION_DEFAULTS = {
    "phone": "8698163900",
    "state": "PI",
    "city": "Teresina",
    "email": "cliente@empresa.com.br",
    "cnpj": "12.345.678/0001-90",
}


def test_extension_fills_soluti_modelo_form_accurately_with_defaults(page: Page) -> None:
    page.set_content(MODELO_HTML)

    # Populate sample cities into #listaMunicipios as the Soluti AJAX service would
    page.evaluate(
        """() => {
            const select = document.querySelector('#listaMunicipios');
            const opt1 = new Option('Parnaíba', 'PARNAIBA');
            const opt2 = new Option('Teresina', 'TERESINA');
            const opt3 = new Option('Picos', 'PICOS');
            select.add(opt1);
            select.add(opt2);
            select.add(opt3);
        }"""
    )

    # Inject extension content script
    page.evaluate(CONTENT_JS)

    # Call fillFormWithExtrAI with document data and emission defaults
    result = page.evaluate(
        "({ data, defaults }) => window.__extraiFillForm(data, defaults)",
        {"data": SYNTHETIC_DATA, "defaults": EMISSION_DEFAULTS},
    )

    assert result["success"] is True
    assert result["filledCount"] == 10

    assert page.locator("#inputName").input_value() == "MARIA DA SILVA"
    assert page.locator("#inputDataNascimento").input_value() == "1990-05-15"
    assert "123" in page.locator("#inputCpf").input_value()
    assert page.locator("#inputCnh").input_value() == "01234567890"
    assert page.locator("#inputPhone").input_value() == "8698163900"
    assert page.locator("#listaEstados").input_value() == "PI"
    assert page.locator("#listaMunicipios").input_value() == "TERESINA"
    assert page.locator("#inputEmail").input_value() == "cliente@empresa.com.br"
    assert page.locator("#inputConfirmarEmail").input_value() == "cliente@empresa.com.br"
    assert page.locator("#inputCnpj").input_value() == "12.345.678/0001-90"


def test_extension_defaults_dynamic_city_loading(page: Page) -> None:
    page.set_content(MODELO_HTML)
    page.evaluate(CONTENT_JS)

    # Fill form when #listaMunicipios is initially empty
    result = page.evaluate(
        "({ data, defaults }) => window.__extraiFillForm(data, defaults)",
        {"data": SYNTHETIC_DATA, "defaults": EMISSION_DEFAULTS},
    )
    assert result["success"] is True

    # Simulate AJAX callback arriving after 100ms
    page.evaluate(
        """() => {
            setTimeout(() => {
                const select = document.querySelector('#listaMunicipios');
                select.add(new Option('Floriano', 'FLO'));
                select.add(new Option('Teresina', 'THE'));
            }, 100);
        }"""
    )

    # The extension's watcher will pick up the new options and select Teresina
    page.wait_for_function('document.querySelector("#listaMunicipios").value === "THE"')
    assert page.locator("#listaMunicipios").input_value() == "THE"


def test_extension_content_script_registers_message_listener(page: Page) -> None:
    page.set_content("<html><body><input id='inputName'><input id='inputPhone'></body></html>")
    page.evaluate(
        """() => {
            window.chrome = {
                runtime: {
                    onMessage: {
                        addListener: (fn) => { window.__mockListener = fn; }
                    }
                }
            };
        }"""
    )
    page.evaluate(CONTENT_JS)

    assert page.evaluate("() => Boolean(window.__extraiInjected)") is True
    assert page.evaluate("() => typeof window.__mockListener === 'function'") is True

    # Test listener handling fill_form message with defaults
    res = page.evaluate(
        """({ data, defaults }) => {
            let answer = null;
            window.__mockListener(
                { action: 'fill_form', data, defaults },
                {},
                (r) => { answer = r; }
            );
            return {
                answer,
                nameVal: document.querySelector('#inputName').value,
                phoneVal: document.querySelector('#inputPhone').value
            };
        }""",
        {"data": SYNTHETIC_DATA, "defaults": EMISSION_DEFAULTS},
    )
    assert res["answer"]["success"] is True
    assert res["answer"]["filledCount"] == 2
    assert res["nameVal"] == "MARIA DA SILVA"
    assert res["phoneVal"] == "8698163900"


def test_extension_fills_generic_form_via_heuristics_and_custom_defaults(page: Page) -> None:
    generic_html = """
    <html>
      <body>
        <form>
          <input type="text" name="nomeCompleto" />
          <input type="text" name="cpf" />
          <input type="text" name="data_nascimento" />
          <input type="text" name="registroGeral" />
          <input type="text" name="celular" />
          <input type="text" name="uf" />
          <input type="text" name="cidade" />
        </form>
      </body>
    </html>
    """
    page.set_content(generic_html)
    page.evaluate(CONTENT_JS)

    custom_defaults = {
        "phone": "86999990000",
        "state": "PI",
        "city": "Teresina",
    }

    result = page.evaluate(
        "({ data, defaults }) => window.__extraiFillForm(data, defaults)",
        {"data": SYNTHETIC_DATA, "defaults": custom_defaults},
    )
    assert result["success"] is True
    assert result["filledCount"] >= 6

    assert page.locator("input[name='nomeCompleto']").input_value() == "MARIA DA SILVA"
    assert page.locator("input[name='cpf']").input_value() == "123.456.789-09"
    assert page.locator("input[name='data_nascimento']").input_value() == "15/05/1990"
    assert page.locator("input[name='celular']").input_value() == "86999990000"
    assert page.locator("input[name='uf']").input_value() == "PI"
    assert page.locator("input[name='cidade']").input_value() == "Teresina"


def test_extension_popup_persists_edited_phone_and_defaults(page: Page) -> None:
    popup_uri = (ROOT / "extension" / "popup" / "popup.html").as_uri()
    page.goto(popup_uri)

    # Initial default values
    assert page.locator("#config-phone").input_value() == "8698163900"
    assert page.locator("#config-state").input_value() == "PI"
    assert page.locator("#config-city").input_value() == "Teresina"
    assert page.locator("#config-email").input_value() == ""
    assert page.locator("#config-cnpj").input_value() == ""

    # User edits phone, city, email, and cnpj
    page.locator("#config-phone").fill("86988887777")
    page.locator("#config-phone").blur()
    page.locator("#config-city").fill("Parnaíba")
    page.locator("#config-city").blur()
    page.locator("#config-email").fill("agr@certificadora.com.br")
    page.locator("#config-email").blur()
    page.locator("#config-cnpj").fill("11.222.333/0001-44")
    page.locator("#config-cnpj").blur()

    # Re-open/reload popup (simulating closing and reopening the extension popup)
    page.goto(popup_uri)

    # Verify edited values remained saved
    assert page.locator("#config-phone").input_value() == "86988887777"
    assert page.locator("#config-city").input_value() == "Parnaíba"
    assert page.locator("#config-email").input_value() == "agr@certificadora.com.br"
    assert page.locator("#config-cnpj").input_value() == "11.222.333/0001-44"

    # User clicks Reset/Restaurar button
    page.locator("#btn-reset-defaults").click()
    assert page.locator("#config-phone").input_value() == "8698163900"
    assert page.locator("#config-city").input_value() == "Teresina"
    assert page.locator("#config-email").input_value() == ""
    assert page.locator("#config-cnpj").input_value() == ""


def test_extension_sanitizes_cpf_and_phone_for_strict_maxlength_inputs(page: Page) -> None:
    strict_html = """
    <html>
      <body>
        <form>
          <input type="text" id="inputCpf" maxlength="11" />
          <input type="text" id="inputPhone" maxlength="10" />
        </form>
      </body>
    </html>
    """
    page.set_content(strict_html)
    page.evaluate(CONTENT_JS)

    test_data = {
        "kind": "cnh",
        "fields": {
            "cpf": {"value": "123.456.789-09"},
        },
    }
    test_defaults = {
        "phone": "(86) 9816-3900",
    }

    result = page.evaluate(
        "({ data, defaults }) => window.__extraiFillForm(data, defaults)",
        {"data": test_data, "defaults": test_defaults},
    )

    assert result["success"] is True
    # Asserts that 11-digit CPF was not truncated with punctuation (e.g. "123.456.789")
    assert page.locator("#inputCpf").input_value() == "12345678909"
    # Asserts that formatted phone digits fit in maxlength 10
    assert page.locator("#inputPhone").input_value() == "8698163900"


def test_extension_prioritizes_rg_over_cnh_when_document_kind_is_rg(page: Page) -> None:
    dual_reg_html = """
    <html>
      <body>
        <form>
          <input type="text" id="inputCnh" />
          <input type="text" id="inputRg" />
        </form>
      </body>
    </html>
    """
    page.set_content(dual_reg_html)
    page.evaluate(CONTENT_JS)

    # 1. Test when document is RG: should target inputRg, leaving inputCnh blank
    rg_data = {
        "kind": "rg",
        "fields": {
            "registration": {"value": "3.456.789-SSP/PI"},
        },
    }
    res_rg = page.evaluate(
        "({ data }) => window.__extraiFillForm(data, {})",
        {"data": rg_data},
    )
    assert res_rg["success"] is True
    assert page.locator("#inputRg").input_value() == "3.456.789-SSP/PI"
    assert page.locator("#inputCnh").input_value() == ""

    # Clear fields
    page.locator("#inputRg").fill("")
    page.locator("#inputCnh").fill("")

    # 2. Test when document is CNH: should target inputCnh, leaving inputRg blank
    cnh_data = {
        "kind": "cnh",
        "fields": {
            "registration": {"value": "01234567890"},
        },
    }
    res_cnh = page.evaluate(
        "({ data }) => window.__extraiFillForm(data, {})",
        {"data": cnh_data},
    )
    assert res_cnh["success"] is True
    assert page.locator("#inputCnh").input_value() == "01234567890"
    assert page.locator("#inputRg").input_value() == ""


def test_extension_fills_various_confirm_email_field_patterns(page: Page) -> None:
    patterns_html = """
    <html>
      <body>
        <form>
          <input type="email" id="email" />
          <input type="email" id="confirmEmail" />
          <input type="text" name="confirm_email" />
        </form>
      </body>
    </html>
    """
    page.set_content(patterns_html)
    page.evaluate(CONTENT_JS)

    result = page.evaluate(
        "({ defaults }) => window.__extraiFillForm(null, defaults)",
        {"defaults": {"email": "operador@teste.com"}},
    )

    assert result["success"] is True
    assert page.locator("#email").input_value() == "operador@teste.com"
    # First matched confirm email input should be filled
    assert page.locator("#confirmEmail").input_value() == "operador@teste.com"


def test_extension_popup_clear_client_inputs_preserves_branch_defaults(page: Page) -> None:
    popup_uri = (ROOT / "extension" / "popup" / "popup.html").as_uri()
    page.goto(popup_uri)

    # Set custom branch defaults and client values
    page.locator("#config-phone").fill("86988887777")
    page.locator("#config-city").fill("Parnaíba")
    page.locator("#config-email").fill("cliente@exemplo.com.br")
    page.locator("#config-cnpj").fill("11.222.333/0001-44")

    # Click clear client inputs
    page.locator("#btn-clear-client-inputs").click()

    # Client inputs must be cleared
    assert page.locator("#config-email").input_value() == ""
    assert page.locator("#config-cnpj").input_value() == ""

    # Branch defaults must remain untouched
    assert page.locator("#config-phone").input_value() == "86988887777"
    assert page.locator("#config-city").input_value() == "Parnaíba"


def test_extension_popup_finish_attendance_clears_client_data_and_resets_ui(page: Page) -> None:
    popup_uri = (ROOT / "extension" / "popup" / "popup.html").as_uri()
    page.goto(popup_uri)

    # Simulate ready state with client data populated
    page.evaluate(
        """() => {
            document.getElementById('state-ready').classList.remove('hidden');
            document.getElementById('state-empty').classList.add('hidden');
            document.getElementById('config-email').value = 'cliente@teste.com';
            document.getElementById('config-cnpj').value = '12.345.678/0001-90';
        }"""
    )

    # Click Concluir Atendimento
    page.locator("#btn-clear-session").click()

    # UI must switch back to empty state
    assert "hidden" not in page.locator("#state-empty").get_attribute("class")
    assert "hidden" in page.locator("#state-ready").get_attribute("class")

    # Client inputs must be cleared
    assert page.locator("#config-email").input_value() == ""
    assert page.locator("#config-cnpj").input_value() == ""



