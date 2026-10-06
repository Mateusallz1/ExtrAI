# Execution Plan: ExtrAI Chrome Extension for Automated Form Filling

- **Status:** Completed (2026-10-06)
- **Date:** 2026-10-05
- **Goal:** Enable operators to automatically populate essential registration data extracted from ID documents (Full Name, CPF, Birth Date, ID/CNH number) directly into web forms of digital certificate systems via 1 click or keyboard shortcut.

---

## 1. Context and Problem

Currently, **ExtrAI** extracts Brazilian RG and CNH data in a private, local environment (`127.0.0.1:8788`). Operators previously had to copy extracted fields (via quick copy buttons or manual selection) and paste them into the active digital certification portal tab.

In operational routines with dozens of daily issuances, tab switching and manual copy-pasting consumes time and increases the risk of human transcription errors.

---

## 2. Goals and Non-Goals

### Goals
1. Build a **Google Chrome / Microsoft Edge Extension** based on **Manifest V3**.
2. Allow operators on certificate registration pages to populate all corresponding fields with 1 click (via popup) or global keyboard shortcut (`Alt + P`).
3. Fetch active extraction data from the local ExtrAI server (`http://127.0.0.1:8788/api/last-extraction`) quickly and securely from volatile memory.
4. Support **intelligent field heuristic detection** (via `name`, `id`, `placeholder`, `aria-label`, and `<label>`).
5. Support **native event dispatching** (`input`, `change`, `blur`, `keyup`), ensuring compatibility with React, Angular, Vue, and masking libraries.
6. Support simple local deployment via *"Load unpacked"* in under 1 minute.

### Non-Goals
- No data persistence to external servers or cloud storage (strict LGPD and privacy compliance).
- No automated form submission (final clicking of "Save/Issue" remains strictly under human operator control).
- No dependency on Chrome Web Store publishing for internal/pilot deployments.

---

## 3. Extension Architecture (Manifest V3)

```text
[ExtrAI Backend (FastAPI)]
     │ (127.0.0.1:8788)
     ▼
[GET /api/last-extraction] ──> (Returns active structured JSON in memory)
     ▲
     │ Local HTTP fetch
     │
[ExtrAI Chrome Extension]
  ├── manifest.json (Manifest V3, permissions: activeTab, scripting, storage)
  ├── popup/ (Window opened on icon click)
  │     ├── popup.html (Data preview + "Fill Form" button + defaults settings)
  │     ├── popup.css (Modern responsive UI matching ExtrAI design system)
  │     └── popup.js (Queries local API and communicates with active tab)
  └── content/
        └── content.js (Injected into certification page: identifies inputs and fills)
```

---

## 4. Detailed Technical Components

### 4.1. ExtrAI Backend Endpoint (`GET /api/last-extraction`)
- ExtrAI backend keeps the latest successful extraction result in volatile memory with a 30-minute TTL (no disk writes).
- Restrict to loopback (`127.0.0.1`) with safe CORS policies for browser extensions.
- Dedicated `DELETE /api/last-extraction` endpoint for immediate memory eviction upon session conclusion.

### 4.2. Extension Popup (`popup.html` / `popup.js`)
- Displays real-time connection status with local ExtrAI instance:
  - 🟢 *ExtrAI Connected* (with document preview: e.g. "CNH • MARIA DA SILVA • 123.456.789-09")
  - ⚪ *No pending document*
  - 🔴 *ExtrAI offline (start server on port 8788)*
- Primary Action Buttons:
  - **`[ Preencher Formulário ]`**
  - **`[ Concluir Atendimento ]`** (evicts backend cache and resets customer inputs)
- Verification checklist of fields to be injected.
- Structurally isolated configuration cards:
  - **Dados do Cliente:** Transient customer inputs (`E-mail`, `CNPJ`) with individual quick-clear action.
  - **Padrões do Posto:** Permanent station defaults (`Telefone`, `UF`, `Cidade`) with `Salvar` and `Restaurar`.

### 4.3. Injector Script (`content.js`)
- Listens for fill messages with payload:
  ```json
  {
    "name": "MARIA DA SILVA",
    "cpf": "123.456.789-09",
    "birthDate": "15/05/1990",
    "registration": "01234567890"
  }
  ```
- **Field Identification Heuristics:**
  - Matches common certification portal selectors for CPF, Name, Birth Date, ID/CNH, Phone, State, City, Email, Confirmation Email, and CNPJ.
  - Dynamic registration routing prioritizing RG inputs when `data.kind === "rg"` and CNH inputs when `data.kind === "cnh"`.
  - Strict input mask sanitization preventing truncation on numeric-only or fixed-length fields.
- **Reactive Value Injection:**
  - Employs prototype property descriptors (`Object.getOwnPropertyDescriptor`) to trigger internal state updates in React, Vue, and Angular frameworks.
  - Subtle visual feedback (1s green outline and glow on successfully populated fields).

---

## 5. Implementation Phases

1. **Phase 1: Backend Support (Local Query API)**
   - Add secure in-memory endpoint `GET /api/last-extraction` with 30-min TTL in ExtrAI.
   - Add `DELETE /api/last-extraction` for immediate cache eviction.
   - Unit tests covering extraction cache and TTL expiration.
2. **Phase 2: Extension Scaffolding (Manifest V3 & Popup UI)**
   - Create `extension/` directory with `manifest.json`, icons, and popup interface.
   - Connect popup to local API to display document data.
3. **Phase 3: Autofill Script (`content.js`)**
   - Implement field resolution heuristics and event dispatching.
   - Support visual highlight feedback on populated inputs.
4. **Phase 4: E2E Testing & Installation Documentation**
   - Test autofill against mock and real portal forms via Playwright.
   - Document installation guide in `README.md` (*Load unpacked*).

---

## 6. Acceptance Criteria

- [x] Extension connects successfully to ExtrAI on `127.0.0.1:8788`.
- [x] Popup displays extracted data from the latest processed document.
- [x] Clicking "Fill Form" or pressing `Alt + P` correctly populates Name, CPF, Birth Date, and Registration on active portal tab.
- [x] Populated fields trigger native web validations (CPF masks, reactive bindings).
- [x] Extension loads cleanly in any Chromium browser (Chrome, Edge, Brave, Opera).

---

## 7. Operational Refinements Completed

- **Strict Input Mask Sanitization:** Fixed digits-only stripping for fields with `maxLength === 11` (unmasked CPFs/phones), preventing truncation of formatted strings.
- **Dynamic RG vs. CNH Selection:** Conditional selector prioritization dynamically routes document numbers based on `data.kind`, preventing RG values from populating CNH inputs.
- **Session Cleanup & LGPD Privacy:** Added "Concluir Atendimento" action in the popup, calling `DELETE /api/last-extraction` and resetting client-specific fields while preserving branch defaults.
- **Visual Shortcut Feedback:** Added status badge indicators on `Alt + P` (`OK`, `0/0`, `NULL`, `OFF`, `BLOQ`).
- **Comprehensive Test Suite:** 10 automated Playwright tests covering form injection, async municipal loading, customer isolation, and attendance lifecycle (224 total project tests passing).

---

## 8. Future Enhancements & Backlog

- **Nested Iframe Injection (`allFrames: true`):** If partner certification portals embed form fields inside an `<iframe>`, update `chrome.scripting.executeScript` with `allFrames: true` and frame targeting once real test access or DOM samples for those legacy systems are available.
