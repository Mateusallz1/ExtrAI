// ExtrAI Popup Script

const EXTRAI_API_URL = "http://127.0.0.1:8788/api/last-extraction";

const DEFAULT_CONFIG = {
  phone: "8698163900",
  state: "PI",
  city: "Teresina",
  email: "",
  cnpj: "",
};

const STORAGE_KEY_PHONE = "extrai_default_phone";
const STORAGE_KEY_STATE = "extrai_default_state";
const STORAGE_KEY_CITY = "extrai_default_city";
const STORAGE_KEY_EMAIL = "extrai_default_email";
const STORAGE_KEY_CNPJ = "extrai_default_cnpj";

let currentExtractionData = null;

const connectionStatus = document.getElementById("connection-status");
const connectionText = document.getElementById("connection-text");

const stateOffline = document.getElementById("state-offline");
const stateEmpty = document.getElementById("state-empty");
const stateReady = document.getElementById("state-ready");

const docKind = document.getElementById("doc-kind");
const docPages = document.getElementById("doc-pages");
const fieldValName = document.getElementById("field-val-name");
const fieldValCpf = document.getElementById("field-val-cpf");
const fieldValBirthDate = document.getElementById("field-val-birthDate");
const fieldValRegistration = document.getElementById("field-val-registration");

const btnFill = document.getElementById("btn-fill");
const btnRetry = document.getElementById("btn-retry");
const fillFeedback = document.getElementById("fill-feedback");

// Configurações de padrões de emissão e dados do cliente
const inputEmail = document.getElementById("config-email");
const inputCnpj = document.getElementById("config-cnpj");
const inputPhone = document.getElementById("config-phone");
const selectState = document.getElementById("config-state");
const inputCity = document.getElementById("config-city");
const btnSaveDefaults = document.getElementById("btn-save-defaults");
const btnResetDefaults = document.getElementById("btn-reset-defaults");
const saveIndicator = document.getElementById("defaults-save-indicator");

let saveTimeout = null;

function showSaveIndicator(text) {
  if (!saveIndicator) return;
  saveIndicator.textContent = text;
  saveIndicator.style.opacity = "1";
  clearTimeout(saveTimeout);
  saveTimeout = setTimeout(() => {
    saveIndicator.style.opacity = "0.7";
  }, 2000);
}

function applyConfigToUI(config) {
  if (inputEmail && config.email !== undefined) {
    inputEmail.value = config.email;
  }
  if (inputCnpj && config.cnpj !== undefined) {
    inputCnpj.value = config.cnpj;
  }
  if (inputPhone && config.phone !== undefined) {
    inputPhone.value = config.phone;
  }
  if (selectState && config.state !== undefined) {
    selectState.value = config.state;
  }
  if (inputCity && config.city !== undefined) {
    inputCity.value = config.city;
  }
}

function loadEmissionDefaults() {
  // 1. Carrega imediatamente do localStorage (síncrono e instantâneo)
  let savedPhone = null;
  let savedState = null;
  let savedCity = null;
  let savedEmail = null;
  let savedCnpj = null;

  try {
    savedPhone = localStorage.getItem(STORAGE_KEY_PHONE);
    savedState = localStorage.getItem(STORAGE_KEY_STATE);
    savedCity = localStorage.getItem(STORAGE_KEY_CITY);
    savedEmail = localStorage.getItem(STORAGE_KEY_EMAIL);
    savedCnpj = localStorage.getItem(STORAGE_KEY_CNPJ);
  } catch (err) {
    console.warn("[ExtrAI] localStorage inacessível:", err);
  }

  const initialConfig = {
    phone: savedPhone !== null ? savedPhone : DEFAULT_CONFIG.phone,
    state: savedState !== null ? savedState : DEFAULT_CONFIG.state,
    city: savedCity !== null ? savedCity : DEFAULT_CONFIG.city,
    email: savedEmail !== null ? savedEmail : DEFAULT_CONFIG.email,
    cnpj: savedCnpj !== null ? savedCnpj : DEFAULT_CONFIG.cnpj,
  };

  applyConfigToUI(initialConfig);

  // 2. Se chrome.storage.local estiver disponível, sincroniza com ele
  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(["phone", "state", "city", "email", "cnpj"], (items) => {
      if (!chrome.runtime.lastError && items) {
        const mergedConfig = {
          phone: items.phone !== undefined ? items.phone : initialConfig.phone,
          state: items.state !== undefined ? items.state : initialConfig.state,
          city: items.city !== undefined ? items.city : initialConfig.city,
          email: items.email !== undefined ? items.email : initialConfig.email,
          cnpj: items.cnpj !== undefined ? items.cnpj : initialConfig.cnpj,
        };
        applyConfigToUI(mergedConfig);

        try {
          if (items.phone !== undefined) localStorage.setItem(STORAGE_KEY_PHONE, items.phone);
          if (items.state !== undefined) localStorage.setItem(STORAGE_KEY_STATE, items.state);
          if (items.city !== undefined) localStorage.setItem(STORAGE_KEY_CITY, items.city);
          if (items.email !== undefined) localStorage.setItem(STORAGE_KEY_EMAIL, items.email);
          if (items.cnpj !== undefined) localStorage.setItem(STORAGE_KEY_CNPJ, items.cnpj);
        } catch {}
      }
    });
  }
}

function saveEmissionDefaults(explicit = false) {
  const email = inputEmail ? inputEmail.value.trim() : "";
  const cnpj = inputCnpj ? inputCnpj.value.trim() : "";
  const phone = inputPhone ? inputPhone.value.trim() : "";
  const state = selectState ? selectState.value : DEFAULT_CONFIG.state;
  const city = inputCity ? inputCity.value.trim() : "";

  const config = {
    email,
    cnpj,
    phone: phone !== "" ? phone : DEFAULT_CONFIG.phone,
    state: state || DEFAULT_CONFIG.state,
    city: city !== "" ? city : DEFAULT_CONFIG.city,
  };

  // 1. Salva no localStorage de forma síncrona
  try {
    localStorage.setItem(STORAGE_KEY_EMAIL, config.email);
    localStorage.setItem(STORAGE_KEY_CNPJ, config.cnpj);
    localStorage.setItem(STORAGE_KEY_PHONE, config.phone);
    localStorage.setItem(STORAGE_KEY_STATE, config.state);
    localStorage.setItem(STORAGE_KEY_CITY, config.city);
  } catch (err) {
    console.warn("[ExtrAI] Erro ao gravar localStorage:", err);
  }

  // 2. Salva no chrome.storage.local para background.js e extensão
  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.set(config, () => {
      if (chrome.runtime.lastError) {
        console.warn("[ExtrAI] Erro no chrome.storage.local:", chrome.runtime.lastError);
      }
    });
  }

  showSaveIndicator(explicit ? "✓ Salvo com sucesso!" : "✓ Salvo no navegador");
}

function resetEmissionDefaults() {
  applyConfigToUI(DEFAULT_CONFIG);

  try {
    localStorage.setItem(STORAGE_KEY_EMAIL, DEFAULT_CONFIG.email);
    localStorage.setItem(STORAGE_KEY_CNPJ, DEFAULT_CONFIG.cnpj);
    localStorage.setItem(STORAGE_KEY_PHONE, DEFAULT_CONFIG.phone);
    localStorage.setItem(STORAGE_KEY_STATE, DEFAULT_CONFIG.state);
    localStorage.setItem(STORAGE_KEY_CITY, DEFAULT_CONFIG.city);
  } catch {}

  if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
    chrome.storage.local.set(DEFAULT_CONFIG);
  }

  showSaveIndicator("✓ Padrões restaurados (PI / Teresina)");
}

function getActiveDefaults() {
  let savedPhone = null;
  let savedState = null;
  let savedCity = null;
  let savedEmail = null;
  let savedCnpj = null;

  try {
    savedPhone = localStorage.getItem(STORAGE_KEY_PHONE);
    savedState = localStorage.getItem(STORAGE_KEY_STATE);
    savedCity = localStorage.getItem(STORAGE_KEY_CITY);
    savedEmail = localStorage.getItem(STORAGE_KEY_EMAIL);
    savedCnpj = localStorage.getItem(STORAGE_KEY_CNPJ);
  } catch {}

  return {
    email: inputEmail ? inputEmail.value.trim() : (savedEmail || ""),
    cnpj: inputCnpj ? inputCnpj.value.trim() : (savedCnpj || ""),
    phone: inputPhone?.value.trim() || savedPhone || DEFAULT_CONFIG.phone,
    state: selectState?.value || savedState || DEFAULT_CONFIG.state,
    city: inputCity?.value.trim() || savedCity || DEFAULT_CONFIG.city,
  };
}

function setStatus(status, text) {
  connectionStatus.className = `status-badge status-${status}`;
  connectionText.textContent = text;
}

function showState(state) {
  stateOffline.classList.toggle("hidden", state !== "offline");
  stateEmpty.classList.toggle("hidden", state !== "empty");
  stateReady.classList.toggle("hidden", state !== "ready");
}

function showFeedback(message, type = "success") {
  fillFeedback.textContent = message;
  fillFeedback.className = `feedback-msg feedback-${type}`;
  fillFeedback.classList.remove("hidden");
}

async function checkExtrAIConnection() {
  setStatus("checking", "Conectando...");
  fillFeedback.classList.add("hidden");

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2500);

    const response = await fetch(EXTRAI_API_URL, {
      method: "GET",
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    setStatus("online", "Conectado");

    if (payload.hasData && payload.data && payload.data.fields) {
      currentExtractionData = payload.data;
      renderReadyState(payload.data);
      showState("ready");
    } else {
      currentExtractionData = null;
      showState("empty");
    }
  } catch {
    setStatus("offline", "Desconectado");
    showState("offline");
  }
}

function renderReadyState(data) {
  const kind = (data.kind || "documento").toUpperCase();
  docKind.textContent = kind;
  docPages.textContent = data.pages === 1 ? "1 página" : `${data.pages} páginas`;

  const fields = data.fields || {};
  fieldValName.textContent = fields.name?.value || "Não identificado";
  fieldValCpf.textContent = fields.cpf?.value || "Não identificado";
  fieldValBirthDate.textContent = fields.birthDate?.value || "Não identificado";
  fieldValRegistration.textContent = fields.registration?.value || "Não identificado";

  btnFill.disabled = false;
}

async function triggerFillForm() {
  if (!currentExtractionData) return;

  btnFill.disabled = true;
  btnFill.textContent = "Preenchendo...";

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      showFeedback("Aba do navegador não encontrada.", "error");
      return;
    }

    const url = tab.url || "";
    if (
      !url ||
      url.startsWith("chrome://") ||
      url.startsWith("edge://") ||
      url.startsWith("chrome-extension://") ||
      url.startsWith("about:")
    ) {
      showFeedback("Abra a aba do portal de certificados para preencher.", "error");
      return;
    }

    // Validação de segurança: apenas HTTPS ou origens locais seguras (file: ou loopback)
    try {
      const parsed = new URL(url);
      const isHttps = parsed.protocol === "https:";
      const isLocal =
        parsed.hostname === "127.0.0.1" ||
        parsed.hostname === "localhost" ||
        parsed.protocol === "file:";

      if (!isHttps && !isLocal) {
        showFeedback("Bloqueado por segurança: a página ativa não utiliza HTTPS.", "error");
        return;
      }
    } catch {
      showFeedback("URL da página inválida.", "error");
      return;
    }

    // Garante que o content script está injetado na aba ativa
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["content/content.js"],
    });

    const defaults = getActiveDefaults();

    // Envia os dados para o content script preencher os campos
    chrome.tabs.sendMessage(
      tab.id,
      {
        action: "fill_form",
        data: currentExtractionData,
        defaults,
      },
      (response) => {
        if (chrome.runtime.lastError) {
          showFeedback("Não foi possível comunicar com a página.", "error");
          return;
        }

        if (response && response.success) {
          showFeedback(response.message, "success");
        } else {
          showFeedback(
            response?.message || "Nenhum campo compatível encontrado nesta página.",
            "error"
          );
        }
      }
    );
  } catch (err) {
    showFeedback("Erro ao injetar script de preenchimento.", "error");
  } finally {
    btnFill.disabled = false;
    btnFill.textContent = "Preencher Formulário";
  }
}

btnRetry?.addEventListener("click", checkExtrAIConnection);
btnFill?.addEventListener("click", triggerFillForm);

// Listeners de configuração de padrões (salva em tempo real em input, change, blur e botão explícito)
inputEmail?.addEventListener("input", () => saveEmissionDefaults(false));
inputEmail?.addEventListener("change", () => saveEmissionDefaults(false));
inputEmail?.addEventListener("blur", () => saveEmissionDefaults(false));

inputCnpj?.addEventListener("input", () => saveEmissionDefaults(false));
inputCnpj?.addEventListener("change", () => saveEmissionDefaults(false));
inputCnpj?.addEventListener("blur", () => saveEmissionDefaults(false));

inputPhone?.addEventListener("input", () => saveEmissionDefaults(false));
inputPhone?.addEventListener("change", () => saveEmissionDefaults(false));
inputPhone?.addEventListener("blur", () => saveEmissionDefaults(false));

selectState?.addEventListener("change", () => saveEmissionDefaults(false));

inputCity?.addEventListener("input", () => saveEmissionDefaults(false));
inputCity?.addEventListener("change", () => saveEmissionDefaults(false));
inputCity?.addEventListener("blur", () => saveEmissionDefaults(false));

btnSaveDefaults?.addEventListener("click", () => saveEmissionDefaults(true));
btnResetDefaults?.addEventListener("click", resetEmissionDefaults);

async function detectTargetPage() {
  const targetVal = document.getElementById("target-domain-val");
  if (!targetVal) return;

  try {
    if (typeof chrome === "undefined" || !chrome.tabs) {
      targetVal.textContent = "Ambiente local";
      return;
    }
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url) {
      targetVal.textContent = "Aba ativa não identificada";
      return;
    }
    const url = tab.url;
    if (
      url.startsWith("chrome://") ||
      url.startsWith("edge://") ||
      url.startsWith("chrome-extension://") ||
      url.startsWith("about:")
    ) {
      targetVal.textContent = "Página do navegador";
      return;
    }
    const parsed = new URL(url);
    if (parsed.protocol === "file:") {
      targetVal.textContent = "Arquivo local (modelo)";
    } else if (parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost") {
      targetVal.textContent = `Local (${parsed.port || "80"})`;
    } else {
      const isHttps = parsed.protocol === "https:";
      targetVal.textContent = `${isHttps ? "🔒 " : "⚠️ "}${parsed.hostname}`;
      if (!isHttps) {
        targetVal.title = "Aviso: esta página não usa criptografia HTTPS!";
        targetVal.style.color = "var(--danger)";
      }
    }
  } catch {
    targetVal.textContent = "Aba ativa";
  }
}

// Inicializar ao abrir o popup
document.addEventListener("DOMContentLoaded", () => {
  detectTargetPage();
  loadEmissionDefaults();
  checkExtrAIConnection();
});
