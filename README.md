# ExtrAI 🚀

> **Intelligent, privacy-first, and compliant document extraction (Brazilian RG & CNH) and automated form-filling for Digital Certification portals (ICP-Brasil).**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-e92063.svg?logo=pydantic)](https://docs.pydantic.dev/)
[![PydanticAI](https://img.shields.io/badge/PydanticAI-Multimodal-purple.svg)](https://ai.pydantic.dev/)
[![Chrome Extension](https://img.shields.io/badge/Chrome_Extension-Manifest_V3-4285F4.svg?logo=googlechrome)](https://developer.chrome.com/docs/extensions/)
[![Playwright](https://img.shields.io/badge/Playwright-E2E_Tests-45ba4b.svg?logo=playwright)](https://playwright.dev/)
[![LGPD](https://img.shields.io/badge/LGPD-Privacy_by_Design-green.svg)](#-information-security-and-privacy-lgpd)
[![Tests Passing](https://img.shields.io/badge/Tests-219%20passed-success.svg)](#-testing-and-quality-assurance)

---

## 🎯 Scenario and Project Purpose

**ExtrAI** is an engineering solution built to automate document data extraction and form-filling workflows within the Brazilian Public Key Infrastructure ecosystem (**ICP-Brasil** — Soluti, Certisign, Valid, Serasa, Safeweb). The system replaces manual data entry of official identification documents (RG and CNH) with multimodal AI extraction and assisted in-browser autofill via a Chrome Extension (Manifest V3).

### Who is this project for?

#### 1. Onboarding, Operations & RegTech Teams (KYC)
- **Elimination of manual transcription:** Structured, deterministic extraction of 10 critical registration fields in under 2 seconds, eliminating audit disqualification (*glosas*) caused by typing mistakes.
- **Legacy form automation (Chrome MV3):** Synthetic event injection to populate fields directly, bypassing paste-blocking restrictions (`Ctrl + V`) on confirmation inputs and synchronizing asynchronous AJAX municipality dropdowns.

#### 2. Information Security, Compliance & DPOs (LGPD)
- **Zero Document Persistence:** Ephemeral, in-memory processing; uploaded files and images are discarded immediately after request termination.
- **In-Memory Cache with TTL (30 min):** Automatic eviction via `time.monotonic()`, preventing unauthorized data retention on operator workstations.
- **Strictly Anonymous Auditing (Zero PII):** No personal identifiable information (names, CPFs, ID numbers, emails, or images) is recorded in logs or persisted to disk.
- **Network Isolation:** Application server bound strictly to local loopback (`127.0.0.1`), enforced with strict CSP headers and extension-level blocking of insecure public HTTP transport.

#### 3. Software Engineers & Solution Architects
- **Strict typing and predictable contracts:** Asynchronous backend built with **FastAPI** and **Pydantic v2**, enforcing rigid schema validation at API boundaries.
- **Structured Multimodal AI with PydanticAI:** Orchestration powered by Google Gemini 3.5 Flash-Lite under strict latency budgets and anti-hallucination guardrails (Modulo 11 mathematical validation for CPF and Gregorian chronological consistency).
- **Testability & Reliability:** Comprehensive test suite of **219 automated tests** (unit and headless E2E with **Playwright**), running 100% offline without consuming API tokens.

---

## 📊 Operational Impact & Performance Benchmarks

The benchmark below reflects real-world operational measurements during certification videoconferencing sessions:

| Operational Step | Traditional Manual Process | With ExtrAI | Efficiency Gain |
| :--- | :---: | :---: | :---: |
| **Document reading, rotation & visual inspection** | ~60 s | ~2 s | **96% faster** |
| **Typing 10 fields into certification portal** | ~120 s | < 1 s | **Instantaneous** |
| **Email confirmation (with paste blocked)** | ~45 s | 0 s (dual native injection) | **100% automated** |
| **Dual verification against typing mistakes** | ~60 s | ~10 s (quick visual sanity check) | **83% reduction** |
| **Total Time per Customer Session** | **~5 min 30 s** | **~15 seconds** | **🚀 95.4% faster** |

### Productivity Projection (10 Sessions / Week Baseline):
- **Weekly (10 issuances):** From 55 minutes down to **2.5 minutes** (~52 minutes saved).
- **Monthly (~45 issuances):** From ~4h10m down to **~11 minutes** (nearly half an operational workday recovered).
- **Annually (~500 issuances):** From ~46 hours down to **~2 hours** (**over 44 hours of tedious manual data entry eliminated**).

---

## ✨ Core Features

### 1. Intelligent Web Extractor
- **Multimodal Processing with PydanticAI:** Handles multi-page and scanned PDFs as well as images (`.pdf`, `.jpg`, `.jpeg`, `.png`, `.webp` up to 15 MB) using Google Gemini 3.5 Flash-Lite under bounded latency constraints.
- **Deterministic Anti-Hallucination Validation:** Algorithmic verification of Brazilian CPF digits (Modulo 11 check), Gregorian calendar checks, and chronological sanity (*Birth Date < Issue Date < Validity Date*). Invalid values are discarded and flagged with visual warnings, never inferred.
- **Active Clipboard Support:** Press `Ctrl + V` anywhere on screen to paste screenshots or images directly from the OS clipboard.
- **Forensic Document Viewer:** Smooth zoom from 0.5x to 5x, 90° rotation, interactive pan/drag, and mouse wheel navigation for document verification.
- **High-Velocity Export:** Dedicated shortcuts for essential field copy (`Alt + C`), tabular TSV copy for spreadsheets (`Alt + T`), and full JSON/CSV export.

### 2. Google Chrome Extension (Manifest V3 — ExtrAI Autofill)
- **Simultaneous 10-Field Autofill:**
  - *Document Data:* Full Name, CPF, Birth Date, ID / CNH number.
  - *Issuance Defaults:* Phone / Mobile, State (UF), City, Primary Email, Confirmation Email, and CNPJ (for corporate certificates).
- **Global Keyboard Shortcut (`Alt + P`):** Triggers instant background filling without requiring popup interactions.
- **Native Paste-Block Bypass:** Dispatches native synthetic events (`input`, `change`, `blur`, `keyup`) and interfaces with DOM prototype descriptors to fill confirmation fields that block `Ctrl + V`.
- **Asynchronous AJAX Dropdown Sync:** Mutation observer mechanism that handles dynamic municipality loading triggered by state selection.
- **Local Settings Persistence:** Stores frequent operational presets (e.g. State, City, corporate phone) via `chrome.storage.local` and synchronous `localStorage`.
- **Defensive, Non-Destructive Execution:** If optional fields are blank (e.g. Individual certificate with no CNPJ), the extension skips them without errors, without blocking execution, and without clearing existing portal data.

---

## 🔒 Information Security and Privacy (LGPD)

ExtrAI is built upon **Privacy by Design & Zero Trust Local Operation**:

| Security Invariant | Technical Implementation |
| :--- | :--- |
| **Zero Document Persistence** | Documents are parsed in volatile memory and discarded immediately upon request completion. |
| **In-Memory TTL Cache (30 min)** | Autofill endpoint (`/api/last-extraction`) automatically evicts cached data after 30 minutes via `time.monotonic()`. |
| **Strict Network Isolation** | Middleware restricts all traffic exclusively to local loopback (`127.0.0.1:8788`), rejecting external network origins. |
| **100% Anonymous Logs (Zero PII)** | No personal data (names, CPFs, ID numbers, emails, file names, or images) is ever logged or written to disk. |
| **Repository Sanitization** | Hardened `.gitignore` rules prevent accidental commit of digital certificates (`*.pfx`, `*.p12`, `*.pem`, `*.key`, `*.crt`) and real document directories. |
| **Secure Extension Transport** | Content script validates active tab protocols, refusing to execute over insecure public HTTP connections (restricted to `https://`, `file://`, or loopback). |
| **Strict Content Security Policy (CSP)** | Enforced on both web frontend and extension manifest (`object-src 'none'`, without `'unsafe-inline'`). |

---

## 🏛️ System Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        END-TO-END SYSTEM FLOW                          │
└────────────────────────────────────────────────────────────────────────┘

  [DOCUMENT (RG / CNH)]
          │
          ▼ (Web Drag-and-Drop / Ctrl+V)
  [FastAPI Backend - 127.0.0.1:8788]
     ├── LoopbackOnlyMiddleware (blocks non-local requests)
     ├── DocumentExtractor (in-memory preparation and normalization)
     └── PydanticAI Agent (Google Gemini 3.5 Flash-Lite multimodal)
          │
          ▼
  [Deterministic Pydantic Validation]
     ├── Modulo 11 CPF verification & Calendar validation
     └── Rejection of inconsistent inferences (zero hallucinations)
          │
          ▼
  [In-Memory Cache with TTL (30 min)]
          │
          │ (Secure loopback polling)
          ▼
  [Chrome Extension Manifest V3]
     ├── Popup: Defaults management (Phone, State, City, Email, CNPJ)
     ├── Content Script: Synthetic DOM event injection
     └── Global Shortcut: Alt + P
          │
          ▼
  [Videoconference Portal / Certifier (Soluti / Certisign)]
     └── 10 fields populated with high accuracy in < 1 second!
```

---

## 🛠️ Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend** | Python 3.11+, FastAPI, Uvicorn, Pydantic v2, PydanticAI |
| **AI Models** | Google Gemini 3.5 Flash-Lite (fast, low-cost multimodal extraction) |
| **Document Processing** | PyPDF, Pillow (PIL), NumPy |
| **Web Frontend** | Semantic HTML5, Modern Vanilla JavaScript, CSS3 with native Dark Mode |
| **Browser Extension** | Chrome Extension Manifest V3, Service Workers, Content Scripts, Chrome Storage API |
| **Testing & Quality** | Playwright (Headless E2E), Pytest, AnyIO, Ruff Linter, UV Package Manager |

---

## 🔌 API Contract

### 1. `GET /api/health`
Returns system health and verifies that provider credentials are ready.
```json
{
  "status": "ok",
  "storage": "temporary-only",
  "model": "google:gemini-3.5-flash-lite",
  "providerConfigured": true
}
```

### 2. `POST /api/extract`
Accepts document files via `multipart/form-data` on the `document` field.

**Extracted fields returned in `fields` object:**
- `name`: Full legal name
- `cpf`: CPF with checksum mathematical validation
- `birthDate`: Birth date (DD/MM/YYYY)
- `issueDate`: Document issuance date (DD/MM/YYYY)
- `validity`: Expiration date for driver licenses (DD/MM/YYYY)
- `firstLicenceDate`: First driver license issuance date (DD/MM/YYYY)
- `registration`: Document registration / CNH number
- `category`: Driver license categories (A, B, C, D, E, AB, etc.)
- `birthPlace`: Place of birth / Naturalidade
- `nationality`: Nationality
- `parentage`: Parents' names

### 3. `GET /api/last-extraction`
Polled by the Chrome Extension via loopback. Returns the active extraction payload or expires with `hasData: false` once the 30-minute in-memory TTL is exceeded:
```json
{
  "hasData": true,
  "data": {
    "kind": "cnh",
    "pages": 1,
    "fields": {
      "name": { "value": "MARIA DA SILVA" },
      "cpf": { "value": "123.456.789-09" },
      "birthDate": { "value": "15/05/1990" },
      "registration": { "value": "01234567890" }
    }
  }
}
```

---

## 🚀 Getting Started

### Prerequisites
- [Python 3.11+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/) (fast Python package manager)
- Google Chrome or Chromium-based browser (Edge, Brave, Opera)
- Google Gemini API Key (free tier available at [Google AI Studio](https://aistudio.google.com/))

### 1. Clone and Run the Backend

```powershell
# 1. Clone repository
git clone https://github.com/Mateusallz1/ExtrAI.git
cd ExtrAI

# 2. Install dependencies into virtual environment
uv sync --dev

# 3. Configure environment variables
Copy-Item .env.example .env
```

Edit `.env` with your API key:
```env
PYDANTIC_AI_MODEL=google:gemini-3.5-flash-lite
GEMINI_API_KEY=your_gemini_api_key_here
HOST=127.0.0.1
PORT=8788
```

Start the local server:
```powershell
uv run dev
```
Open your browser at: **`http://127.0.0.1:8788`**

---

### 2. Install Chrome Extension

1. Open Google Chrome and visit: `chrome://extensions/`
2. Enable **Developer mode** toggle in the top-right corner.
3. Click **Load unpacked**.
4. Select the `extension/` directory inside the `ExtrAI` project root.
5. Pin the **ExtrAI** icon to your browser toolbar!

---

### 3. Daily Usage Workflow

1. Open the ExtrAI web app (`http://127.0.0.1:8788`) and drop your document (or paste via `Ctrl + V`).
2. Data is extracted and verified on screen.
3. Switch to your Certifier portal tab (e.g. Soluti videoconferencing).
4. Open the extension popup: verify extracted data, enter Client Email and CNPJ (if applicable), and click **"Fill Form"** (or simply press **`Alt + P`**).
5. All 10 fields are filled and validated instantly!

---

## 🧪 Testing and Quality Assurance

ExtrAI enforces a strict quality policy with **219 automated tests** covering semantic business rules and full E2E form filling via Playwright without external provider token costs:

```powershell
# Run the complete test suite of 219 automated tests
uv run pytest

# Static analysis and linting with Ruff
uv run ruff check src tests

# Verify bytecode compilation
uv run python -m compileall -q src tests

# Dependency lockfile consistency check
uv lock --check
uv pip check

# Validate JavaScript syntax
node --check src/doc_extractor_pydantic/static/app.js
node --check extension/popup/popup.js
node --check extension/content/content.js
node --check extension/background.js

# Verify documentation and harness consistency
uv run python scripts/check_harness.py
```

---

## 🗺️ Documentation Map & Governance

For deep-dive architectural decisions and operational criteria:
- [ARCHITECTURE.md](ARCHITECTURE.md): System layers, data flow, and dependency boundaries.
- [docs/SECURITY.md](docs/SECURITY.md): Personal data policies, LGPD compliance, keys, and threat model.
- [docs/RELIABILITY.md](docs/RELIABILITY.md): Operational limits, latency budgets, and failure modes.
- [docs/QUALITY.md](docs/QUALITY.md): Acceptance criteria, coverage requirements, and quality gates.
- [docs/exec-plans/README.md](docs/exec-plans/README.md): Versioned execution plans.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
