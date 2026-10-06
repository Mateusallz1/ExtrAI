// ExtrAI Content Script — Injeção e Autopreenchimento de Formulários

(function () {
  if (window.__extraiInjected) return;
  window.__extraiInjected = true;

  function normalizeText(str) {
    return String(str || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();
  }

  const BRAZIL_UF_MAP = {
    ac: "AC", acre: "AC",
    al: "AL", alagoas: "AL",
    ap: "AP", amapa: "AP",
    am: "AM", amazonas: "AM",
    ba: "BA", bahia: "BA",
    ce: "CE", ceara: "CE",
    df: "DF", "distrito federal": "DF", brasilia: "DF",
    es: "ES", "espirito santo": "ES",
    go: "GO", goias: "GO",
    ma: "MA", maranhao: "MA",
    mt: "MT", "mato grosso": "MT",
    ms: "MS", "mato grosso do sul": "MS",
    mg: "MG", "minas gerais": "MG",
    pa: "PA", para: "PA",
    pb: "PB", paraiba: "PB",
    pr: "PR", parana: "PR",
    pe: "PE", pernambuco: "PE",
    pi: "PI", piaui: "PI",
    rj: "RJ", "rio de janeiro": "RJ",
    rn: "RN", "rio grande do norte": "RN",
    rs: "RS", "rio grande do sul": "RS",
    ro: "RO", rondonia: "RO",
    rr: "RR", roraima: "RR",
    sc: "SC", "santa catarina": "SC",
    sp: "SP", "sao paulo": "SP",
    se: "SE", sergipe: "SE",
    to: "TO", tocantins: "TO",
  };

  function findElementBySelectors(selectors) {
    for (const sel of selectors) {
      try {
        const el = document.querySelector(sel);
        if (el && !el.disabled && el.type !== "hidden") {
          return el;
        }
      } catch {
        // Ignore invalid selector
      }
    }
    return null;
  }

  function highlightField(el) {
    if (!el) return;
    const originalOutline = el.style.outline;
    const originalBoxShadow = el.style.boxShadow;
    const originalTransition = el.style.transition;

    el.style.transition = "outline 0.15s ease, box-shadow 0.15s ease";
    el.style.outline = "2px solid #16a34a";
    el.style.boxShadow = "0 0 0 3px rgba(22, 163, 74, 0.25)";

    setTimeout(() => {
      el.style.outline = originalOutline;
      el.style.boxShadow = originalBoxShadow;
      setTimeout(() => {
        el.style.transition = originalTransition;
      }, 200);
    }, 1200);
  }

  function setNativeValue(element, rawValue) {
    if (!element || rawValue === undefined || rawValue === null) return false;

    let value = String(rawValue).trim();
    if (!value || value === "Não identificado") return false;

    // Conversão para campos HTML5 date (exige AAAA-MM-DD)
    if (element.type === "date" && /^\d{2}\/\d{2}\/\d{4}$/.test(value)) {
      const [d, m, y] = value.split("/");
      value = `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
    }

    // Limpeza de dígitos para campos numéricos/CNH/CPF/telefone com máscara estrita
    const digitsOnly = value.replace(/\D/g, "");
    const isStrictCnh = element.classList.contains("cnh") || element.id === "inputCnh";
    const isStrict11 = element.maxLength === 11 && digitsOnly.length === 11;
    const isOverflowingField =
      element.maxLength > 0 &&
      element.maxLength < value.length &&
      digitsOnly.length <= element.maxLength;

    if (isStrictCnh || isStrict11 || isOverflowingField) {
      value = digitsOnly;
    }

    // Burlar override de setters de frameworks (React, Angular, Vue)
    const valueSetter = Object.getOwnPropertyDescriptor(element, "value")?.set;
    const prototype = Object.getPrototypeOf(element);
    const prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;

    element.focus();

    if (prototypeValueSetter && valueSetter !== prototypeValueSetter) {
      prototypeValueSetter.call(element, value);
    } else if (valueSetter) {
      valueSetter.call(element, value);
    } else {
      element.value = value;
    }

    // Disparar eventos nativos para ativar Cleave.js, jQuery Mask e reatividade
    element.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));
    element.dispatchEvent(new Event("change", { bubbles: true, cancelable: true }));
    element.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, cancelable: true }));
    element.dispatchEvent(new Event("blur", { bubbles: true, cancelable: true }));

    highlightField(element);
    return true;
  }

  function selectOption(selectEl, opt) {
    selectEl.value = opt.value;
    selectEl.dispatchEvent(new Event("input", { bubbles: true }));
    selectEl.dispatchEvent(new Event("change", { bubbles: true }));
    if (window.jQuery) {
      try {
        window.jQuery(selectEl).trigger("change");
      } catch {}
    }
    highlightField(selectEl);
    return true;
  }

  function matchAndSelectOption(selectEl, textOrValue) {
    if (!selectEl || !textOrValue) return false;
    const targetNorm = normalizeText(textOrValue);
    const targetUf = BRAZIL_UF_MAP[targetNorm] || targetNorm.toUpperCase();

    // Passagem 1: Correspondência exata pelo valor da UF (ex: value="PI")
    for (const opt of selectEl.options) {
      if (!opt.value || opt.value === "#" || opt.value === "") continue;
      if (opt.value.trim().toUpperCase() === targetUf) {
        return selectOption(selectEl, opt);
      }
    }

    // Passagem 2: Correspondência exata pelo texto ou valor normalizado (ex: "piaui", "teresina")
    for (const opt of selectEl.options) {
      if (!opt.value || opt.value === "#" || opt.value === "") continue;
      const optValNorm = normalizeText(opt.value);
      const optTextNorm = normalizeText(opt.text);
      if (optValNorm === targetNorm || optTextNorm === targetNorm) {
        return selectOption(selectEl, opt);
      }
    }

    // Passagem 3: Correspondência parcial/prefixo (somente para palavras com 3 ou mais letras)
    if (targetNorm.length >= 3) {
      for (const opt of selectEl.options) {
        if (!opt.value || opt.value === "#" || opt.value === "") continue;
        const optTextNorm = normalizeText(opt.text);
        if (optTextNorm.startsWith(targetNorm) || optTextNorm.includes(targetNorm)) {
          return selectOption(selectEl, opt);
        }
      }
    }

    return false;
  }

  function waitAndSelectCity(selectEl, cityName, maxWaitMs = 3500) {
    if (!selectEl || !cityName) return;
    if (matchAndSelectOption(selectEl, cityName)) return;

    const startTime = Date.now();
    const intervalId = setInterval(() => {
      if (matchAndSelectOption(selectEl, cityName) || Date.now() - startTime > maxWaitMs) {
        clearInterval(intervalId);
      }
    }, 150);
  }

  function fillEmissionDefaults(defaults = {}) {
    const phone = defaults.phone ?? "8698163900";
    const state = defaults.state ?? "PI";
    const city = defaults.city ?? "Teresina";
    const email = defaults.email ? String(defaults.email).trim() : "";
    const cnpj = defaults.cnpj ? String(defaults.cnpj).trim() : "";

    let filledCount = 0;
    const filledFields = [];

    // 1. Telefone / Celular
    if (phone) {
      const phoneInput = findElementBySelectors([
        "#inputPhone",
        "input[name='telefone' i]",
        "input[name='phone' i]",
        "input[name='celular' i]",
        "input.phone",
        "input[id*='phone' i]",
        "input[id*='telefone' i]",
        "input[id*='celular' i]",
        "input[placeholder*='celular' i]",
        "input[placeholder*='telefone' i]",
      ]);
      if (phoneInput && setNativeValue(phoneInput, phone)) {
        filledCount++;
        filledFields.push("Telefone");
      }
    }

    // 2. Estado (UF)
    if (state) {
      const stateEl = findElementBySelectors([
        "#listaEstados",
        "select[name='estados' i]",
        "select[name='uf' i]",
        "select[name*='estado' i]",
        "select[id*='estado' i]",
        "select[id*='uf' i]",
        "input[name='uf' i]",
        "input[name*='estado' i]",
        "input[id*='uf' i]",
      ]);
      if (stateEl) {
        if (stateEl.tagName === "SELECT") {
          if (matchAndSelectOption(stateEl, state)) {
            filledCount++;
            filledFields.push("Estado");
          }
        } else if (stateEl.tagName === "INPUT") {
          const uf = BRAZIL_UF_MAP[normalizeText(state)] || state;
          if (setNativeValue(stateEl, uf)) {
            filledCount++;
            filledFields.push("Estado");
          }
        }
      }
    }

    // 3. Cidade / Município
    if (city) {
      const cityEl = findElementBySelectors([
        "#listaMunicipios",
        "select[name='municipios' i]",
        "select[name='cidade' i]",
        "select[id*='municipio' i]",
        "select[id*='cidade' i]",
        "input[name='cidade' i]",
        "input[id*='cidade' i]",
        "input[name*='cidade' i]",
      ]);
      if (cityEl) {
        if (cityEl.tagName === "SELECT") {
          if (matchAndSelectOption(cityEl, city)) {
            filledCount++;
            filledFields.push("Cidade");
          } else {
            // Em caso de carregamento assíncrono (AJAX disparado pelo estado)
            waitAndSelectCity(cityEl, city);
            filledCount++;
            filledFields.push("Cidade");
          }
        } else if (cityEl.tagName === "INPUT") {
          if (setNativeValue(cityEl, city)) {
            filledCount++;
            filledFields.push("Cidade");
          }
        }
      }
    }

    // 4. E-mail (preenche o campo principal e o de confirmação que costuma bloquear colar)
    if (email) {
      const emailInput = findElementBySelectors([
        "#inputEmail",
        "input[name='email' i]",
        "input[id*='email' i]:not([id*='confirm' i]):not([id*='confirma' i]):not([id*='cc' i])",
        "input[name*='email' i]:not([name*='confirm' i]):not([name*='confirma' i]):not([name*='cc' i])",
        "input[type='email']:not([id*='confirm' i]):not([name*='confirm' i]):not([id*='confirma' i]):not([name*='confirma' i])",
        "input[placeholder*='e-mail' i]:not([placeholder*='confirm' i]):not([placeholder*='confirme' i])",
        "input[placeholder*='email' i]:not([placeholder*='confirm' i]):not([placeholder*='confirme' i])",
      ]);
      if (emailInput && setNativeValue(emailInput, email)) {
        filledCount++;
        filledFields.push("E-mail");
      }

      const confirmEmailInput = findElementBySelectors([
        "#inputConfirmarEmail",
        "#confirmEmail",
        "#inputConfirmEmail",
        "#emailConfirm",
        "#confirmaEmail",
        "input[name*='confirmar' i][name*='email' i]",
        "input[name*='confirma' i][name*='email' i]",
        "input[name*='confirm' i][name*='email' i]",
        "input[name='confirm_email' i]",
        "input[name='email_confirmation' i]",
        "input[id*='confirmar' i][id*='email' i]",
        "input[id*='confirma' i][id*='email' i]",
        "input[id*='confirm' i][id*='email' i]",
        "input[placeholder*='confirme' i]",
        "input[placeholder*='confirmar' i]",
        "input[placeholder*='confirm' i]",
      ]);
      if (confirmEmailInput && setNativeValue(confirmEmailInput, email)) {
        filledCount++;
        filledFields.push("Confirmação de E-mail");
      }
    }

    // 5. CNPJ (se informado)
    if (cnpj) {
      const cnpjInput = findElementBySelectors([
        "#inputCnpj",
        "input[name='cnpj' i]",
        "input[id*='cnpj' i]",
        "input[placeholder*='cnpj' i]",
        "input.cnpj",
      ]);
      if (cnpjInput && setNativeValue(cnpjInput, cnpj)) {
        filledCount++;
        filledFields.push("CNPJ");
      }
    }

    return { filledCount, filledFields };
  }

  const BASE_FIELD_DEFINITIONS = [
    {
      key: "name",
      label: "Nome completo",
      selectors: [
        "#inputName",
        "#nome",
        "#nomeCompleto",
        "input[name='nome' i]",
        "input[name='nomeCompleto' i]",
        "input[name*='nome' i]",
        "input[id*='nome' i]",
        "input[id*='name' i]",
        "input[placeholder*='nome' i]",
      ],
    },
    {
      key: "cpf",
      label: "CPF",
      selectors: [
        "#inputCpf",
        "#cpf",
        "input[name='cpf' i]",
        "input[id*='cpf' i]",
        "input[name*='cpf' i]",
        "input[placeholder*='cpf' i]",
      ],
    },
    {
      key: "birthDate",
      label: "Data de nascimento",
      selectors: [
        "#inputDataNascimento",
        "#dataNascimento",
        "#nascimento",
        "input[name*='nascimento' i]",
        "input[name*='nasc' i]",
        "input[id*='nascimento' i]",
        "input[id*='nasc' i]",
        "input[placeholder*='nascimento' i]",
      ],
    },
  ];

  const CNH_REGISTRATION_SELECTORS = [
    "#inputCnh",
    "#cnh",
    "input[name*='cnh' i]",
    "input[id*='cnh' i]",
    "input[placeholder*='cnh' i]",
    "#registro",
    "input[name*='registro' i]",
    "#inputRg",
    "#rg",
    "input[name*='rg' i]",
    "input[id*='rg' i]",
  ];

  const RG_REGISTRATION_SELECTORS = [
    "#inputRg",
    "#rg",
    "#registroGeral",
    "input[name*='rg' i]",
    "input[id*='rg' i]",
    "input[placeholder*='rg' i]",
    "input[name*='registroGeral' i]",
    "input[id*='registroGeral' i]",
    "#registro",
    "input[name*='registro' i]",
    "#inputCnh",
    "#cnh",
    "input[name*='cnh' i]",
  ];

  const FIELD_DEFINITIONS = [
    ...BASE_FIELD_DEFINITIONS,
    {
      key: "registration",
      label: "CNH / Registro",
      selectors: CNH_REGISTRATION_SELECTORS,
    },
  ];

  function fillFormWithExtrAI(data, defaults = {}) {
    let filledCount = 0;
    const filledFields = [];

    // Preenchimento de campos extraídos do documento
    if (data && data.fields) {
      const isRg = String(data.kind || "").toLowerCase() === "rg";
      const registrationDef = {
        key: "registration",
        label: isRg ? "RG / Registro Geral" : "CNH / Registro",
        selectors: isRg ? RG_REGISTRATION_SELECTORS : CNH_REGISTRATION_SELECTORS,
      };

      const fieldDefs = [...BASE_FIELD_DEFINITIONS, registrationDef];

      for (const def of fieldDefs) {
        const fieldData = data.fields[def.key];
        const val = fieldData?.value;
        if (!val || val === "Não identificado") continue;

        const targetInput = findElementBySelectors(def.selectors);
        if (targetInput) {
          if (setNativeValue(targetInput, val)) {
            filledCount++;
            filledFields.push(def.label);
          }
        }
      }
    }

    // Preenchimento de padrões da emissão (Telefone, Estado, Cidade)
    const defaultsResult = fillEmissionDefaults(defaults);
    filledCount += defaultsResult.filledCount;
    filledFields.push(...defaultsResult.filledFields);

    if (filledCount === 0) {
      return {
        success: false,
        filledCount: 0,
        message: "Nenhum campo compatível encontrado nesta página.",
      };
    }

    return {
      success: true,
      filledCount,
      filledFields,
      message: `${filledCount} campo(s) preenchido(s): ${filledFields.join(", ")}.`,
    };
  }

  // Expor para testes e chamada direta
  window.__extraiFillForm = fillFormWithExtrAI;

  // Ouvinte de mensagens da extensão (popup ou background service worker)
  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
      if (request.action === "fill_form") {
        const result = fillFormWithExtrAI(request.data, request.defaults || {});
        sendResponse(result);
      }
      return true;
    });
  }
})();
