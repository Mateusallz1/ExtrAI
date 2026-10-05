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
        return;
      }
    } catch {
      return;
    }

    const response = await fetch(EXTRAI_API_URL);
    if (!response.ok) return;

    const payload = await response.json();
    if (!payload.hasData || !payload.data) return;

    const defaults = await getStoredDefaults();

    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["content/content.js"],
    });

    chrome.tabs.sendMessage(tab.id, {
      action: "fill_form",
      data: payload.data,
      defaults,
    });
  } catch (err) {
    console.error("[ExtrAI] Erro ao preencher via atalho:", err);
  }
});
