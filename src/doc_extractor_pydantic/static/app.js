const form = document.querySelector("#extract-form");
const input = document.querySelector("#document");
const submit = document.querySelector("#submit");
const status = document.querySelector("#status");
const introCopy = document.querySelector("#intro-copy");
const uploadPanel = document.querySelector("#upload-panel");
const uploadLabel = document.querySelector("#upload-label");
const result = document.querySelector("#result");

function setSubmitMode(mode) {
  if (mode === "clear") {
    submit.dataset.mode = "clear";
    submit.type = "button";
    submit.textContent = "Limpar análise";
    submit.className = "secondary";
    submit.title = "Limpar análise e voltar à tela inicial (Alt+L)";
    submit.disabled = false;
  } else if (mode === "cancel") {
    submit.dataset.mode = "cancel";
    submit.type = "button";
    submit.textContent = "Parar análise";
    submit.className = "secondary";
    submit.title = "Parar análise em andamento (Esc)";
    submit.disabled = false;
  } else {
    submit.dataset.mode = "extract";
    submit.type = "submit";
    submit.textContent = "Analisar documento";
    submit.className = "";
    submit.title = "Analisar documento (Ctrl+Enter)";
  }
}

const imagePreview = document.querySelector("#image-preview");
const focusPanel = document.querySelector("#focus-panel");
const focusEmpty = document.querySelector("#focus-empty");
const focusLabel = document.querySelector("#focus-label");
const focusImageContainer = document.querySelector("#focus-image-container");
const focusImage = document.querySelector("#focus-image");
const focusThumbnails = document.querySelector("#focus-thumbnails");
const summary = document.querySelector("#summary");
const integrityBox = document.querySelector("#integrity-box");
const integrityRiskBadge = document.querySelector("#integrity-risk-badge");
const integrityMediaType = document.querySelector("#integrity-media-type");
const integrityFlags = document.querySelector("#integrity-flags");
const warningBox = document.querySelector("#warning-box");
const warningsTitle = document.querySelector("#warnings-title");
const warnings = document.querySelector("#warnings");
const fields = document.querySelector("#fields");
const rawText = document.querySelector("#raw-text");
let lastData = null;
let previewUrl = null;
let selectedIsPdf = false;
let requestId = 0;
let pendingRequest = null;
const focusState = { previews: [], index: 0, kind: "unknown" };
let analysisTimer = null;

function formatProgressMessage(elapsed) {
  if (elapsed < 7) {
    return `Analisando seu documento... (${elapsed}s)`;
  }
  if (elapsed < 18) {
    return `Processando campos e visão computacional... (${elapsed}s)`;
  }
  if (elapsed < 30) {
    return `Aguardando resposta do provedor de IA... (${elapsed}s)`;
  }
  return `Provedor com alta demanda; aguardando retentativas automáticas... (${elapsed}s)`;
}

function formatSuccessMessage(durationMs) {
  if (typeof durationMs === "number" && durationMs > 0) {
    const seconds = durationMs < 100 ? "< 0.1s" : `${(durationMs / 1000).toFixed(1)}s`;
    return `Tudo certo em ${seconds}! Confira as informações antes de copiar.`;
  }
  return "Tudo certo! Confira as informações antes de copiar.";
}


function syncResultHeight() {
  if (result.classList.contains("hidden")) return;
  if (window.matchMedia("(max-width: 800px)").matches) {
    result.style.removeProperty("--result-height");
    return;
  }
  const top = result.getBoundingClientRect().top;
  const available = Math.max(240, Math.floor(window.innerHeight - top - 24));
  result.style.setProperty("--result-height", `${available}px`);
}

function fitFocusImage(preview) {
  const sourceWidth = focusImage.naturalWidth || Number(preview?.sourceWidth);
  const sourceHeight = focusImage.naturalHeight || Number(preview?.sourceHeight);
  const aspectRatio = sourceWidth && sourceHeight ? sourceWidth / sourceHeight : 0;
  const isCardDocument = aspectRatio >= 1.25
    && aspectRatio <= 1.75;
  const isSmallSquare = aspectRatio > 0
    && Math.abs(aspectRatio - 1) < 0.08
    && sourceWidth < 700;
  const shouldFit = isCardDocument || isSmallSquare;
  focusImageContainer.classList.toggle("focus-fit", shouldFit);
  focusImage.classList.toggle("focus-image-qr", shouldFit && isSmallSquare);
  const containerWidth = focusImageContainer.clientWidth;
  if (!sourceWidth || !sourceHeight || !containerWidth) {
    focusImageContainer.style.removeProperty("height");
    return;
  }
  const resultHeight = result.clientHeight || window.innerHeight;
  const availableHeight = Math.max(220, Math.min(520, resultHeight - 176)) * 0.9;
  const maxHeight = isSmallSquare
    ? Math.min(300, availableHeight)
    : availableHeight;
  if (!shouldFit) {
    focusImageContainer.style.height = `${Math.round(availableHeight)}px`;
    return;
  }
  const targetHeight = Math.min(
    maxHeight,
    Math.max(220, containerWidth / aspectRatio),
  );
  focusImageContainer.style.height = `${Math.round(targetHeight)}px`;
}

window.addEventListener("resize", () => {
  syncResultHeight();
  renderFocusPreview();
});

focusImage.addEventListener("load", () => {
  fitFocusImage(focusState.previews[focusState.index]);
});

input.addEventListener("change", () => {
  const file = input.files?.[0];
  if (!file) return;
  requestId += 1;
  if (pendingRequest) pendingRequest.abort();
  pendingRequest = null;
  if (analysisTimer) {
    clearInterval(analysisTimer);
    analysisTimer = null;
  }
  submit.disabled = false;
  setSubmitMode("extract");
  lastData = null;
  document.body.classList.remove("has-result");
  result.classList.add("hidden");
  summary.textContent = "";
  if (integrityBox) integrityBox.classList.add("hidden");
  if (integrityRiskBadge) {
    integrityRiskBadge.className = "integrity-badge";
    integrityRiskBadge.textContent = "";
  }
  if (integrityMediaType) integrityMediaType.textContent = "";
  if (integrityFlags) integrityFlags.replaceChildren();
  warningBox.classList.add("hidden");
  if (warningsTitle) warningsTitle.textContent = "Atenção";
  warnings.replaceChildren();
  fields.replaceChildren();
  rawText.textContent = "";
  status.className = "status";
  status.textContent = "";
  focusState.previews = [];
  focusState.index = 0;
  focusState.kind = "unknown";
  result.style.removeProperty("--result-height");
  focusImageContainer.style.removeProperty("height");
  focusPanel.classList.add("hidden");
  focusEmpty.classList.add("hidden");
  focusThumbnails.replaceChildren();
  focusImage.removeAttribute("src");
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(file);
  const isImage = file.type.startsWith("image/") || /\.(jpe?g|png|webp)$/i.test(file.name);
  selectedIsPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
  imagePreview.classList.toggle("hidden", !isImage);
  if (isImage && typeof previewUrl === "string") {
    const safeSrc = encodeURI(previewUrl);
    if (safeSrc.startsWith("blob:")) {
      imagePreview.src = safeSrc;
    }
  }

  if (!isImage && !selectedIsPdf) {
    status.className = "status error";
    status.textContent = "Formato não suportado. Use PDF, JPG, JPEG, PNG ou WEBP.";
    submit.disabled = true;
    return;
  }

  form.requestSubmit();
});

window.addEventListener("paste", (e) => {
  const target = e.target;
  if (
    target instanceof HTMLElement &&
    (target.closest(".field-value") || target.isContentEditable || target.matches("input, textarea"))
  ) {
    return;
  }
  const clipboardFiles = e.clipboardData?.files;
  if (!clipboardFiles || !clipboardFiles.length) return;
  const file = [...clipboardFiles].find(
    (f) => f.type.startsWith("image/") || f.type === "application/pdf"
  );
  if (!file) return;
  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
});

let dragDepth = 0;

function isFileDrag(e) {
  return Boolean(e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files"));
}

uploadPanel.addEventListener("dragenter", (e) => {
  if (!isFileDrag(e)) return;
  uploadPanel.classList.add("drag-active");
});

window.addEventListener("dragenter", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth += 1;
  uploadPanel.classList.add("drag-active");
});

window.addEventListener("dragover", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = "copy";
  }
  uploadPanel.classList.add("drag-active");
});

window.addEventListener("dragleave", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth -= 1;
  if (dragDepth <= 0) {
    dragDepth = 0;
    uploadPanel.classList.remove("drag-active");
  }
});

function handleDrop(e) {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth = 0;
  uploadPanel.classList.remove("drag-active");

  const target = e.target;
  if (
    target instanceof HTMLElement &&
    (target.closest(".field-value") || target.isContentEditable || target.matches("input, textarea"))
  ) {
    return;
  }

  const files = e.dataTransfer?.files;
  if (!files || !files.length) return;

  const file = [...files].find(
    (f) =>
      f.type.startsWith("image/") ||
      f.type === "application/pdf" ||
      /\.(pdf|jpe?g|png|webp)$/i.test(f.name)
  );

  if (!file) {
    status.className = "status error";
    status.textContent = "Formato não suportado. Use PDF, JPG, JPEG, PNG ou WEBP.";
    return;
  }

  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

uploadPanel.addEventListener("drop", (e) => {
  e.stopPropagation();
  handleDrop(e);
});
window.addEventListener("drop", handleDrop);

let zoomScale = 1;

let panX = 0;
let panY = 0;
let rotationDeg = 0;
let isPanning = false;
let startX = 0;
let startY = 0;
let pinchDist = 0;

function updateZoomTransform() {
  focusImage.style.transform = `translate(${panX}px, ${panY}px) scale(${zoomScale}) rotate(${rotationDeg}deg)`;
}

function resetZoom() {
  zoomScale = 1;
  panX = 0;
  panY = 0;
  rotationDeg = 0;
  updateZoomTransform();
}

const zoomInBtn = document.querySelector("#zoom-in");
const zoomOutBtn = document.querySelector("#zoom-out");
const zoomRotateBtn = document.querySelector("#zoom-rotate");
const zoomResetBtn = document.querySelector("#zoom-reset");

if (zoomInBtn) zoomInBtn.addEventListener("click", () => {
  zoomScale = Math.min(5, Math.round(zoomScale * 1.25 * 100) / 100);
  updateZoomTransform();
});
if (zoomOutBtn) zoomOutBtn.addEventListener("click", () => {
  zoomScale = Math.max(0.5, Math.round((zoomScale / 1.25) * 100) / 100);
  updateZoomTransform();
});
if (zoomRotateBtn) zoomRotateBtn.addEventListener("click", () => {
  rotationDeg = (rotationDeg + 90) % 360;
  updateZoomTransform();
});
if (zoomResetBtn) zoomResetBtn.addEventListener("click", resetZoom);

focusImageContainer.addEventListener("wheel", (e) => {
  e.preventDefault();
  const delta = e.deltaY < 0 ? 1.15 : 0.85;
  zoomScale = Math.min(5, Math.max(0.5, Math.round(zoomScale * delta * 100) / 100));
  updateZoomTransform();
}, { passive: false });

focusImageContainer.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return;
  isPanning = true;
  startX = e.clientX - panX;
  startY = e.clientY - panY;
  focusImageContainer.classList.add("panning");
});

window.addEventListener("mousemove", (e) => {
  if (!isPanning) return;
  panX = e.clientX - startX;
  panY = e.clientY - startY;
  updateZoomTransform();
});

window.addEventListener("mouseup", () => {
  if (isPanning) {
    isPanning = false;
    focusImageContainer.classList.remove("panning");
  }
});

focusImageContainer.addEventListener("touchstart", (e) => {
  if (e.touches.length === 1) {
    isPanning = true;
    startX = e.touches[0].clientX - panX;
    startY = e.touches[0].clientY - panY;
  } else if (e.touches.length === 2) {
    isPanning = false;
    pinchDist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
  }
}, { passive: true });

focusImageContainer.addEventListener("touchmove", (e) => {
  if (e.touches.length === 1 && isPanning) {
    panX = e.touches[0].clientX - startX;
    panY = e.touches[0].clientY - startY;
    updateZoomTransform();
  } else if (e.touches.length === 2) {
    const dist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
    if (pinchDist > 0) {
      const factor = dist / pinchDist;
      zoomScale = Math.min(5, Math.max(0.5, zoomScale * factor));
      updateZoomTransform();
    }
    pinchDist = dist;
  }
}, { passive: true });

focusImageContainer.addEventListener("touchend", () => {
  isPanning = false;
  pinchDist = 0;
});

function renderFocusPreview() {
  const preview = focusState.previews[focusState.index];
  if (!preview) return;
  focusLabel.textContent = preview.label || "Detalhe do documento";
  if (focusImage.getAttribute("src") !== preview.src) {
    if (typeof preview.src === "string" && (preview.src.startsWith("blob:") || preview.src.startsWith("data:image/"))) {
      focusImage.src = preview.src;
    }
  }
  focusImage.alt = preview.label || "Detalhe do documento";
  fitFocusImage(preview);
  resetZoom();
  [...focusThumbnails.children].forEach((thumbnail, index) => {
    thumbnail.classList.toggle("selected", index === focusState.index);
  });
}

function renderFocusPreviews(previews, kind) {
  focusState.previews = (previews && previews.length) ? previews : [];
  focusState.index = 0;
  focusState.kind = kind || "unknown";
  focusThumbnails.replaceChildren();
  if (!focusState.previews.length && !selectedIsPdf && previewUrl) {
    focusState.previews = [{
      label: "Documento",
      primary: true,
      src: previewUrl,
    }];
  }
  if (!focusState.previews.length) {
    focusPanel.classList.add("hidden");
    focusEmpty.classList.toggle("hidden", !selectedIsPdf);
    focusImage.removeAttribute("src");
    focusImage.classList.remove("focus-image-qr");
    focusImageContainer.classList.remove("focus-fit");
    focusImageContainer.style.removeProperty("height");
    return;
  }
  imagePreview.classList.add("hidden");
  focusPanel.classList.remove("hidden");
  focusEmpty.classList.add("hidden");
  if (focusState.previews.length > 1) {
    focusThumbnails.classList.remove("hidden");
    focusState.previews.forEach((preview, index) => {
      const thumbnail = document.createElement("button");
      thumbnail.type = "button";
      thumbnail.className = "focus-thumb";
      thumbnail.title = preview.label || `Detalhe ${index + 1}`;
      const image = document.createElement("img");
      if (typeof preview.src === "string" && (preview.src.startsWith("blob:") || preview.src.startsWith("data:image/"))) {
        image.src = preview.src;
      }
      image.alt = preview.label || `Detalhe ${index + 1}`;
      thumbnail.append(image);
      thumbnail.addEventListener("click", () => {
        focusState.index = index;
        renderFocusPreview();
      });
      focusThumbnails.append(thumbnail);
    });
  } else {
    focusThumbnails.classList.add("hidden");
  }
  renderFocusPreview();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!input.files?.[0] || submit.disabled || submit.dataset.mode === "cancel") return;
  setSubmitMode("cancel");
  document.body.classList.remove("has-result");
  result.classList.add("hidden");
  requestId += 1;
  const currentRequest = requestId;
  if (pendingRequest) pendingRequest.abort();
  if (analysisTimer) {
    clearInterval(analysisTimer);
    analysisTimer = null;
  }
  status.className = "status analyzing";
  const startedAt = Date.now();
  status.textContent = formatProgressMessage(0);
  analysisTimer = setInterval(() => {
    if (currentRequest !== requestId) {
      clearInterval(analysisTimer);
      analysisTimer = null;
      return;
    }
    const elapsed = Math.floor((Date.now() - startedAt) / 1000);
    status.textContent = formatProgressMessage(elapsed);
  }, 1000);

  const controller = new AbortController();
  pendingRequest = controller;
  try {
    const response = await fetch("/api/extract", { method: "POST", body: new FormData(form), signal: controller.signal });
    const data = await response.json();
    if (currentRequest !== requestId) return;
    if (!response.ok) throw new Error(data.detail || "Não foi possível analisar o documento.");
    lastData = data;
    renderResult(data);
    status.className = "status";
    status.textContent = formatSuccessMessage(data.durationMs);
  } catch (error) {
    if (currentRequest !== requestId || error.name === "AbortError") return;
    status.className = "status error";
    status.textContent = error.message;
    setSubmitMode("extract");
  } finally {
    if (currentRequest === requestId) {
      if (analysisTimer) {
        clearInterval(analysisTimer);
        analysisTimer = null;
      }
      pendingRequest = null;
      if (submit.dataset.mode === "cancel") {
        setSubmitMode("extract");
      }
    }
  }
});

const confidenceLabels = { medium: "conferir", low: "conferir com atenção" };
const confidenceHints = {
  medium: "O modelo leu este dado com pequena incerteza.",
  low: "O modelo leu este dado parcialmente. Compare com o documento.",
};

function isValidCpf(str) {
  const digits = (str || "").replace(/\D/g, "");
  if (digits.length !== 11 || /^(\d)\1{10}$/.test(digits)) return false;
  let sum = 0;
  for (let i = 0; i < 9; i++) sum += parseInt(digits[i], 10) * (10 - i);
  let rem = (sum * 10) % 11;
  if (rem === 10) rem = 0;
  if (rem !== parseInt(digits[9], 10)) return false;
  sum = 0;
  for (let i = 0; i < 10; i++) sum += parseInt(digits[i], 10) * (11 - i);
  rem = (sum * 10) % 11;
  if (rem === 10) rem = 0;
  return rem === parseInt(digits[10], 10);
}

function isValidDate(str) {
  const match = (str || "").trim().match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!match) return false;
  const day = parseInt(match[1], 10);
  const month = parseInt(match[2], 10);
  const year = parseInt(match[3], 10);
  if (year < 1900 || year > 2100 || month < 1 || month > 12 || day < 1 || day > 31) return false;
  const d = new Date(year, month - 1, day);
  return d.getFullYear() === year && d.getMonth() === month - 1 && d.getDate() === day;
}

function isExpiredDate(str) {
  if (/^indeterminad[ao]$/i.test((str || "").trim())) return false;
  if (!isValidDate(str)) return false;
  const [day, month, year] = str.trim().split("/").map(Number);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return new Date(year, month - 1, day) < today;
}

function parseDateValue(text) {
  if (!text || text === "Não identificado" || !isValidDate(text)) return null;
  const [day, month, year] = text.trim().split("/").map(Number);
  return new Date(year, month - 1, day);
}

function checkCrossDateConsistency() {
  const getDateVal = (fieldKey) => {
    const card = fields.querySelector(`.field-card[data-field-label="${fieldKey}"][data-found="true"]`);
    if (!card) return null;
    const text = card.querySelector(".field-value")?.textContent?.trim();
    return parseDateValue(text);
  };

  const birthDate = getDateVal("birthDate");
  const issueDate = getDateVal("issueDate");
  const firstLicence = getDateVal("firstLicenceDate");
  const validity = getDateVal("validity");

  const conflicts = new Set();
  const conflictReasons = {};

  const recordConflict = (k1, k2, reason) => {
    conflicts.add(k1);
    conflicts.add(k2);
    if (!conflictReasons[k1]) conflictReasons[k1] = reason;
    if (!conflictReasons[k2]) conflictReasons[k2] = reason;
  };

  if (birthDate && issueDate && birthDate >= issueDate) {
    recordConflict("birthDate", "issueDate", "Data de nascimento incompatível com data de emissão.");
  }
  if (birthDate && firstLicence && birthDate >= firstLicence) {
    recordConflict("birthDate", "firstLicenceDate", "Data de nascimento incompatível com 1ª habilitação.");
  }
  if (firstLicence && issueDate && firstLicence > issueDate) {
    recordConflict("firstLicenceDate", "issueDate", "Data da 1ª habilitação posterior à emissão.");
  }
  if (firstLicence && validity && validity <= firstLicence) {
    recordConflict("firstLicenceDate", "validity", "Data de validade incompatível com 1ª habilitação.");
  }
  if (issueDate && validity && validity <= issueDate) {
    recordConflict("issueDate", "validity", "Data de validade anterior ou igual à emissão.");
  }
  if (birthDate && validity && validity <= birthDate) {
    recordConflict("birthDate", "validity", "Data de validade incompatível com nascimento.");
  }

  for (const dateKey of ["birthDate", "issueDate", "firstLicenceDate", "validity"]) {
    const card = fields.querySelector(`.field-card[data-field-label="${dateKey}"]`);
    if (!card) continue;
    const valEl = card.querySelector(".field-value");
    if (!valEl) continue;
    const isConflicting = conflicts.has(dateKey);
    valEl.classList.toggle("field-temporal-inconsistent", isConflicting);
    if (isConflicting && !valEl.classList.contains("field-invalid")) {
      valEl.title = conflictReasons[dateKey] || "Inconsistência cronológica entre datas.";
      valEl.setAttribute("aria-invalid", "true");
    }
  }
  return conflicts.size > 0;
}

function checkFieldValidity(key, text, allowIncomplete = false) {
  if (!text || text === "Não identificado") return true;
  if (key === "cpf") {
    const digits = text.replace(/\D/g, "");
    if (digits.length < 11 && allowIncomplete) return true;
    return isValidCpf(digits);
  }
  if (key === "birthDate" || key === "issueDate" || key === "validity" || key === "firstLicenceDate") {
    if (key === "validity" && /^indeterminad[ao]$/i.test((text || "").trim())) return true;
    if (text.trim().length < 10 && allowIncomplete) return true;
    if (!isValidDate(text)) return false;
    const [day, month, year] = text.trim().split("/").map(Number);
    const now = new Date();
    if ((key === "birthDate" || key === "issueDate" || key === "firstLicenceDate") && new Date(year, month - 1, day) > now) {
      return false;
    }
    if (key === "validity" && year > now.getFullYear() + 15) {
      return false;
    }
    return true;
  }
  return true;
}

function renderFieldCard(key, value) {
  const card = document.createElement("div");
  card.className = "field-card";
  card.dataset.fieldLabel = key;
  card.dataset.found = value.value ? "true" : "false";
  const name = document.createElement("span");
  name.className = "field-name";
  const nameText = document.createElement("span");
  nameText.textContent = value.label;
  name.append(nameText);
  const confidence = confidenceLabels[value.confidence];
  if (value.value && confidence) {
    const badge = document.createElement("span");
    badge.className = "field-confidence";
    badge.dataset.confidence = value.confidence;
    badge.textContent = confidence;
    badge.title = confidenceHints[value.confidence];
    name.append(badge);
  }
  const expiredBadge = document.createElement("span");
  if (key === "validity") {
    expiredBadge.className = "field-badge field-badge-expired hidden";
    expiredBadge.textContent = "vencida";
    expiredBadge.title = "Documento com validade expirada";
    name.append(expiredBadge);
  }
  const fieldValue = document.createElement("span");
  fieldValue.className = "field-value";
  fieldValue.contentEditable = "plaintext-only";
  fieldValue.tabIndex = 0;
  fieldValue.setAttribute("role", "textbox");
  fieldValue.setAttribute("aria-label", value.label);
  fieldValue.textContent = value.value || "Não identificado";
  function updateValidity(text, allowIncomplete = false) {
    const valid = checkFieldValidity(key, text, allowIncomplete);
    fieldValue.classList.toggle("field-invalid", !valid);
    fieldValue.setAttribute("aria-invalid", String(!valid));
    fieldValue.title = !valid
      ? `${value.label} inválido ou incompleto. Confira o documento antes de usar.`
      : text && text !== "Não identificado" ? "Clique para copiar ou editar" : "";
    if (key === "validity") {
      expiredBadge.classList.toggle("hidden", !isExpiredDate(text));
    }
    checkCrossDateConsistency();
  }
  updateValidity(value.value || "");

  const control = document.createElement("div");
  control.className = "field-control";
  const copyButton = document.createElement("button");
  copyButton.type = "button";
  copyButton.className = "secondary field-copy";
  copyButton.title = `Copiar ${value.label}`;
  copyButton.setAttribute("aria-label", `Copiar ${value.label}`);
  copyButton.innerHTML = '<svg class="copy-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2"></rect><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"></path></svg>';
  copyButton.disabled = !value.value;

  fieldValue.addEventListener("focus", () => {
    if (card.dataset.found === "false") {
      fieldValue.textContent = "";
      updateValidity("");
    }
  });

  fieldValue.addEventListener("blur", () => {
    const text = fieldValue.textContent.trim();
    if (!text) {
      fieldValue.textContent = "Não identificado";
      card.dataset.found = "false";
      copyButton.disabled = true;
      updateValidity("");
    } else {
      updateValidity(text);
    }
  });

  fieldValue.addEventListener("input", () => {
    const text = fieldValue.textContent.trim();
    const isIdentified = Boolean(text && text !== "Não identificado");
    card.dataset.found = isIdentified ? "true" : "false";
    copyButton.disabled = !isIdentified;
    updateValidity(text, true);
  });

  let copyFeedbackTimer = null;
  async function copyFieldValue() {
    const text = fieldValue.textContent.trim();
    if (!text || text === "Não identificado") return;
    if (await copyText(text)) {
      status.textContent = `${value.label} copiado.`;
      fieldValue.classList.add("field-copied");
      if (copyFeedbackTimer) clearTimeout(copyFeedbackTimer);
      copyFeedbackTimer = setTimeout(() => {
        fieldValue.classList.remove("field-copied");
        copyFeedbackTimer = null;
      }, 600);
    }
  }

  fieldValue.addEventListener("click", async () => {
    if (window.getSelection && window.getSelection()?.toString()) return;
    await copyFieldValue();
  });

  copyButton.addEventListener("click", copyFieldValue);
  control.append(fieldValue, copyButton);
  card.append(name, control);
  return card;
}

function renderResult(data) {
  result.classList.remove("hidden");
  document.body.classList.add("has-result");
  document.body.classList.add("has-extracted");
  introCopy.classList.add("hidden");
  uploadLabel.classList.remove("hidden");
  setSubmitMode("clear");
  syncResultHeight();
  const warningItems = Array.isArray(data.warnings)
    ? data.warnings.filter((warning) => typeof warning === "string" && warning.trim())
    : [];
  const isUnknown = data.kind === "unknown";
  const unsupportedWarning = isUnknown && warningItems.some((w) =>
    /comprovante|passaporte|t[íi]tulo|certid[ãa]o|carteira de trabalho|crlv|contrato|fatura|boleto|n[ãa]o suportado|especializado/i.test(w)
  );

  const kindLabels = { cnh: "CNH", rg: "RG", cin: "CIN", unknown: "documento" };
  const kindLabel = kindLabels[data.kind] || "documento";
  const pageLabel = data.pages === 1 ? "1 página" : `${data.pages} páginas`;
  if (unsupportedWarning) {
    summary.textContent = `Documento não suportado • ${pageLabel}`;
    if (warningsTitle) warningsTitle.textContent = "Documento não suportado";
  } else {
    const summaryPrefix = (data.kind === "cnh" || data.kind === "cin")
      ? `${kindLabel} identificada`
      : `${kindLabel} identificado`;
    summary.textContent = data.kind === "unknown"
      ? `Não foi possível identificar o documento • ${pageLabel}`
      : `${summaryPrefix} • ${pageLabel}`;
    if (warningsTitle) warningsTitle.textContent = "Atenção";
  }
  rawText.textContent = data.text || "Nenhum texto foi encontrado.";
  renderFocusPreviews(data.previews, data.kind);
  warningBox.classList.toggle("hidden", !warningItems.length);
  warnings.replaceChildren(...warningItems.map((warning) => {
    const li = document.createElement("li"); li.textContent = warning; return li;
  }));
  if (data.integrity && data.integrity.mediaType) {
    const mediaLabels = {
      physical_original: "Documento físico original",
      digital_official: "Documento eletrônico oficial",
      photocopy: "Fotocópia (xerox)",
      screen_capture: "Recaptura de tela (monitor/celular)",
      unknown: "Mídia não identificada",
    };
    const riskLabels = {
      low: "Risco baixo",
      medium: "Risco médio",
      high: "Risco alto",
    };
    const riskLevel = data.integrity.riskLevel || "low";
    const mediaType = data.integrity.mediaType || "unknown";
    const mediaLabel = mediaLabels[mediaType] || mediaType;
    const riskLabel = riskLabels[riskLevel] || riskLevel;

    if (integrityRiskBadge) {
      integrityRiskBadge.className = `integrity-badge integrity-badge-${riskLevel}`;
      integrityRiskBadge.textContent = riskLabel;
    }
    if (integrityMediaType) {
      integrityMediaType.textContent = `Mídia: ${mediaLabel}`;
    }
    if (integrityFlags) {
      integrityFlags.replaceChildren();
      const flagItems = Array.isArray(data.integrity.flags)
        ? data.integrity.flags.filter((f) => typeof f === "string" && f.trim())
        : [];
      if (data.integrity.tamperingDetected) {
        const alertLi = document.createElement("li");
        alertLi.textContent = "Alerta: Evidências visuais de adulteração ou manipulação digital.";
        integrityFlags.append(alertLi);
      }
      for (const flag of flagItems) {
        const li = document.createElement("li");
        li.textContent = flag;
        integrityFlags.append(li);
      }
    }
    if (integrityBox) integrityBox.classList.remove("hidden");
  } else {
    if (integrityBox) integrityBox.classList.add("hidden");
  }
  const found = Object.entries(data.fields || {}).map(([key, value]) => renderFieldCard(key, value));
  const missing = (Array.isArray(data.missing) ? data.missing : [])
    .map((field) => renderFieldCard(field.key, { label: field.label, value: null }));
  fields.replaceChildren(...found, ...missing);
  checkCrossDateConsistency();
  syncResultHeight();
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
    status.className = "status";
    return true;
  } catch {
    status.className = "status error";
    status.textContent = "Não foi possível copiar. Selecione o texto e copie manualmente.";
    return false;
  }
}

const CORE_FIELD_KEYS = ["name", "cpf", "birthDate", "registration"];

document.querySelector("#copy-core")?.addEventListener("click", async () => {
  if (!lastData) return;
  const values = [];
  for (const key of CORE_FIELD_KEYS) {
    const card = fields.querySelector(`.field-card[data-field-label="${key}"][data-found="true"]`);
    if (card) {
      const val = card.querySelector(".field-value")?.textContent?.trim();
      if (val && val !== "Não identificado") {
        values.push(val);
      }
    }
  }
  if (!values.length) {
    status.textContent = "Nenhum dado essencial encontrado para copiar.";
    return;
  }
  if (await copyText(values.join("\n"))) {
    status.textContent = "Dados essenciais copiados (apenas valores).";
  }
});

document.querySelector("#copy")?.addEventListener("click", async () => {
  if (!lastData) return;
  const items = getExtractedItems();
  if (!items.length) {
    status.textContent = "Nenhum dado encontrado para copiar.";
    return;
  }
  const kind = (lastData.kind || "documento").toUpperCase();
  const lines = [
    `FICHA CADASTRAL — ${kind}`,
    ...items.map((it) => `${it.label}: ${it.value}`),
  ];
  if (lastData?.integrity && lastData.integrity.mediaType) {
    const mediaLabels = {
      physical_original: "Documento físico original",
      digital_official: "Documento eletrônico oficial",
      photocopy: "Fotocópia (xerox)",
      screen_capture: "Recaptura de tela (monitor/celular)",
      unknown: "Mídia não identificada",
    };
    const riskLabels = {
      low: "Risco baixo",
      medium: "Risco médio",
      high: "Risco alto",
    };
    const mLabel = mediaLabels[lastData.integrity.mediaType] || lastData.integrity.mediaType;
    const rLabel = riskLabels[lastData.integrity.riskLevel] || lastData.integrity.riskLevel;
    lines.push("", "INTEGRIDADE E DOCUMENTOSCOPIA", `Mídia: ${mLabel}`, `Risco: ${rLabel}`);
    if (lastData.integrity.tamperingDetected) {
      lines.push("Adulteração: Detectada");
    }
    if (Array.isArray(lastData.integrity.flags) && lastData.integrity.flags.length > 0) {
      lines.push(`Observações: ${lastData.integrity.flags.join(", ")}`);
    }
  }
  if (await copyText(lines.join("\n"))) {
    status.textContent = "Ficha cadastral copiada. Faça a conferência final.";
  }
});

document.querySelector("#copy-tsv")?.addEventListener("click", async (e) => {
  if (!lastData) return;
  const items = getExtractedItems();
  if (!items.length) {
    status.textContent = "Nenhum dado encontrado para copiar.";
    return;
  }
  const cells = items.map((it) => {
    let val = it.value.trim();
    if (/^[\s\u0000-\u001f\u007f-\u009f]*[=+\-@]/.test(val)) {
      val = `'${val}`;
    }
    return val.replace(/\r\n|\r|\n/g, " / ");
  });
  const tsvText = cells.join("\t");
  if (e && e.shiftKey) {
    const headers = items.map((it) => it.label.trim().replace(/\r\n|\r|\n/g, " "));
    const fullTsv = `${headers.join("\t")}\n${tsvText}`;
    if (await copyText(fullTsv)) {
      status.textContent = "Linha com cabeçalhos copiada (TSV). Cole na planilha (Ctrl+V).";
    }
    return;
  }
  if (await copyText(tsvText)) {
    status.textContent = "Linha copiada (TSV). Cole na planilha (Ctrl+V).";
  }
});

function getExtractedItems() {
  const items = [];
  for (const card of fields.querySelectorAll('.field-card[data-found="true"]')) {
    const label = card.querySelector(".field-name span")?.textContent || "";
    const val = card.querySelector(".field-value")?.textContent?.trim() || "";
    if (val && val !== "Não identificado") {
      items.push({ label, value: val, key: card.dataset.fieldLabel || "" });
    }
  }
  return items;
}

function downloadFile(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function reportDownload(message, items) {
  const invalid = items.some((item) => !checkFieldValidity(item.key, item.value)) || checkCrossDateConsistency();
  status.className = invalid ? "status error" : "status";
  status.textContent = invalid
    ? `${message} Há campos inválidos ou incompletos; confira o documento antes de usar.`
    : message;
}

document.querySelector("#download-json")?.addEventListener("click", () => {
  if (!lastData) return;
  const items = getExtractedItems();
  const obj = {
    documento: lastData.kind || "documento",
    dados: Object.fromEntries(items.map((it) => [it.label, it.value])),
  };
  if (lastData?.integrity) {
    obj.integridade = lastData.integrity;
  }
  downloadFile(JSON.stringify(obj, null, 2), `extracao-${lastData.kind || "documento"}.json`, "application/json");
  reportDownload("Arquivo JSON baixado.", items);
});

function escapeCsvCell(value) {
  // CSV quoting preserves columns, but spreadsheet formulas must remain literal text.
  const literal = /^[\s\u0000-\u001f\u007f-\u009f]*[=+\-@]/.test(value) ? `'${value}` : value;
  const singleLine = literal.replace(/\r\n|\r|\n/g, " / ");
  return `"${singleLine.replace(/"/g, '""')}"`;
}

document.querySelector("#download-csv")?.addEventListener("click", () => {
  if (!lastData) return;
  const items = getExtractedItems();
  const lines = [["Campo", "Valor"]];
  for (const it of items) {
    lines.push([escapeCsvCell(it.label), escapeCsvCell(it.value)]);
  }
  const csvText = "\uFEFF" + lines.map((r) => r.join(";")).join("\r\n");
  downloadFile(csvText, `extracao-${lastData.kind || "documento"}.csv`, "text/csv;charset=utf-8;");
  reportDownload("Arquivo CSV baixado.", items);
});

window.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    if (!submit.disabled && input.files?.[0] && !pendingRequest) {
      e.preventDefault();
      setSubmitMode("extract");
      form.requestSubmit();
    }
    return;
  }

  if (e.key === "Escape") {
    if (pendingRequest) {
      e.preventDefault();
      cancelAnalysis();
      return;
    }
    if (zoomScale !== 1 || panX !== 0 || panY !== 0 || rotationDeg !== 0) {
      e.preventDefault();
      resetZoom();
      return;
    }
  }

  const isEditing =
    e.target instanceof HTMLElement &&
    (e.target.closest(".field-value") || e.target.isContentEditable || e.target.matches("input, textarea"));
  if (isEditing) return;

  if (lastData && !result.classList.contains("hidden")) {
    if (
      ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "c") ||
      (e.altKey && e.key.toLowerCase() === "c")
    ) {
      e.preventDefault();
      document.querySelector("#copy-core")?.click();
      return;
    }
    if (
      (e.altKey && e.key.toLowerCase() === "a") ||
      ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "a")
    ) {
      e.preventDefault();
      document.querySelector("#copy")?.click();
      return;
    }
    if (
      (e.altKey && e.key.toLowerCase() === "t") ||
      ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "t")
    ) {
      e.preventDefault();
      document.querySelector("#copy-tsv")?.click();
      return;
    }
    if (e.altKey && e.key.toLowerCase() === "l") {
      e.preventDefault();
      clearExtraction();
      return;
    }
  }
});

function cancelAnalysis() {
  if (!pendingRequest) return;
  requestId += 1;
  pendingRequest.abort();
  pendingRequest = null;
  if (analysisTimer) {
    clearInterval(analysisTimer);
    analysisTimer = null;
  }
  setSubmitMode("extract");
  submit.disabled = false;
  status.className = "status";
  status.textContent = "Análise cancelada.";
}

function clearExtraction() {
  requestId += 1;
  if (pendingRequest) {
    pendingRequest.abort();
    pendingRequest = null;
  }
  if (analysisTimer) {
    clearInterval(analysisTimer);
    analysisTimer = null;
  }
  form.reset();
  lastData = null;
  fetch("/api/last-extraction", { method: "DELETE" }).catch(() => {});
  if (previewUrl) {
    URL.revokeObjectURL(previewUrl);
    previewUrl = null;
  }
  imagePreview.classList.add("hidden");
  imagePreview.removeAttribute("src");
  result.classList.add("hidden");
  document.body.classList.remove("has-result");
  document.body.classList.remove("has-extracted");
  introCopy.classList.remove("hidden");
  uploadLabel.classList.add("hidden");
  summary.textContent = "";
  if (integrityBox) integrityBox.classList.add("hidden");
  if (integrityRiskBadge) {
    integrityRiskBadge.className = "integrity-badge";
    integrityRiskBadge.textContent = "";
  }
  if (integrityMediaType) integrityMediaType.textContent = "";
  if (integrityFlags) integrityFlags.replaceChildren();
  warningBox.classList.add("hidden");
  if (warningsTitle) warningsTitle.textContent = "Atenção";
  warnings.replaceChildren();
  fields.replaceChildren();
  rawText.textContent = "";
  status.className = "status";
  status.textContent = "";
  focusState.previews = [];
  focusState.index = 0;
  focusState.kind = "unknown";
  result.style.removeProperty("--result-height");
  focusImageContainer.style.removeProperty("height");
  focusPanel.classList.add("hidden");
  focusEmpty.classList.add("hidden");
  focusThumbnails.replaceChildren();
  focusImage.removeAttribute("src");
  resetZoom();
  setSubmitMode("extract");
  submit.disabled = false;
  input.focus();
}

submit.addEventListener("click", (e) => {
  if (submit.dataset.mode === "clear") {
    e.preventDefault();
    clearExtraction();
  } else if (submit.dataset.mode === "cancel") {
    e.preventDefault();
    cancelAnalysis();
  }
});

