// ExtrAI Background Service Worker — Atalhos Globais e Padrões de Emissão

const EXTRAI_API_URL = "http://127.0.0.1:8788/api/last-extraction";

const DEFAULT_CONFIG = {
  phone: "8698163900",
  state: "PI",
  city: "Teresina",
  email: "",
  cnpj: "",
};

async function getStoredDefaults() {
  return new Promise((resolve) => {
    const storageArea = chrome.storage?.local || chrome.storage?.sync;
    if (!storageArea) {
      resolve(DEFAULT_CONFIG);
      return;
    }
    storageArea.get(["phone", "state", "city", "email", "cnpj"], (items) => {
      if (chrome.runtime.lastError || !items) {
        resolve(DEFAULT_CONFIG);
      } else {
        resolve({
          phone: items.phone !== undefined ? items.phone : DEFAULT_CONFIG.phone,
          state: items.state !== undefined ? items.state : DEFAULT_CONFIG.state,
          city: items.city !== undefined ? items.city : DEFAULT_CONFIG.city,
          email: items.email || "",
          cnpj: items.cnpj || "",
        });
      }
    });
  });
}

function setBadge(text, color, durationMs = 2500) {
  if (typeof chrome !== "undefined" && chrome.action) {
    chrome.action.setBadgeText({ text });
    if (color) {
      chrome.action.setBadgeBackgroundColor({ color });
    }
    setTimeout(() => {
      chrome.action.setBadgeText({ text: "" });
    }, durationMs);
  }
}

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "fill_form") return;

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) return;

    const url = tab.url || "";
    if (
      !url ||
      url.startsWith("chrome://") ||
      url.startsWith("edge://") ||
      url.startsWith("chrome-extension://") ||
      url.startsWith("about:")
    ) {
      setBadge("NAV", "#64748b");
      return;
    }

    try {
      const parsed = new URL(url);
      const isHttps = parsed.protocol === "https:";
      const isLocal =
        parsed.hostname === "127.0.0.1" ||
        parsed.hostname === "localhost" ||
        parsed.protocol === "file:";

      if (!isHttps && !isLocal) {
        console.warn("[ExtrAI Segurança] Preenchimento bloqueado em conexão HTTP externa:", parsed.origin);
        setBadge("BLOQ", "#dc2626");
        return;
      }
    } catch {
      setBadge("ERR", "#dc2626");
      return;
    }

    let response;
    try {
      response = await fetch(EXTRAI_API_URL);
    } catch {
      setBadge("OFF", "#dc2626");
      return;
    }

    if (!response.ok) {
      setBadge("OFF", "#dc2626");
      return;
    }

    const payload = await response.json();
    if (!payload.hasData || !payload.data) {
      setBadge("NULL", "#d97706");
      return;
    }

    const defaults = await getStoredDefaults();

    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["content/content.js"],
    });

    chrome.tabs.sendMessage(tab.id, {
      action: "fill_form",
      data: payload.data,
      defaults,
    }, (res) => {
      if (res && res.success) {
        setBadge("OK", "#16a34a");
      } else {
        setBadge("0/0", "#d97706");
      }
    });
  } catch (err) {
    console.error("[ExtrAI] Erro ao preencher via atalho:", err);
    setBadge("ERR", "#dc2626");
  }
});
