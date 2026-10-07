# Execution Plan: Document Integrity and Visual Fraud Inspection (AI Documentoscopy)

- **Status:** Completed
- **Date:** 2026-10-07
- **Goal:** Empower ExtrAI with automated documentoscopy signals, classifying document media types, detecting digital tampering or screen recaptures, and providing an authenticity risk score to assist human operators in compliance and fraud prevention.

---

## 1. Context and Problem

ExtrAI extracts structured fields (Name, CPF, Dates, Registration, etc.) from Brazilian identity documents (RG, CNH, CIN). However, in digital certificate issuance (ICP-Brasil), banking KYC, and notary environments, operators must also ensure document authenticity and integrity.

Common operational fraud vectors include:
1. **Screen Recaptures (Fotos de tela):** Photographs taken of a computer monitor, tablet, or smartphone displaying a document image, often hiding artifacts or indicating non-possession of the original.
2. **Digital Tampering (Fotomontagens):** Digitally manipulated documents where names, numbers, or 3x4 photos were replaced or edited using graphic software, often exhibiting misaligned fonts, resolution mismatch, or cut boundaries.
3. **Low-Quality Photocopies:** Monochromatic photocopies (xerox) lacking security guilloche and relief patterns.

Currently, operators must inspect these visual indicators manually without automated assistance.

---

## 2. Goals and Non-Goals

### Goals
1. **Media Type Classification (`media_type`):**
   - `physical_original`: Physical document photographed or scanned.
   - `digital_official`: Native digital document (official e-PDF, CNH-e, RG digital).
   - `photocopy`: Monochromatic reprographic copy / xerox.
   - `screen_capture`: Photograph of a screen / display showing another document (detected by moire patterns, subpixel raster, display reflections, monitor bezels).
   - `unknown`: Indeterminate media.
2. **Digital Tampering Detection (`tampering_detected`):**
   - Boolean flag indicating visible evidence of digital modification (photo replacement, font mismatch, blurred patches covering fields).
3. **Authenticity Risk Level (`risk_level`):**
   - `low`: Original physical/digital document with consistent graphical patterns.
   - `medium`: Screen recapture or degraded photocopy without explicit tampering, requiring extra operator attention.
   - `high`: Obvious digital manipulation, cutouts, or inconsistent text overlays.
4. **Specific Integrity Flags (`flags`):**
   - List of concise, human-readable observations (e.g., "foto de tela detectada", "padrao grafico integro", "bordas de montagem digital").
5. **Frontend Ergonomics:**
   - Dedicated integrity status badge and visual indicators in the results view.
   - Warning box for elevated risk (`medium` / `high`) with clear explanations.
   - Integration with "Ficha cadastral" copy and JSON export.
6. **Automated Testing:**
   - Unit tests covering Pydantic models, default fallbacks, and API contracts.
   - Headless Playwright DOM tests validating badge rendering, warning states, and exports.

### Non-Goals
- Automated hard-rejection: ExtrAI remains an assistive tool; human operators retain final operational authority.
- No PII logging: Only risk level and media type metadata may be logged; zero document or personal values in logs.

---

## 3. Architecture and Data Flow

```text
Uploaded Image / PDF
  |
  v
FastAPI /api/extract
  |
  v
PydanticAI Multimodal Agent (Gemini 3.5 Flash Lite)
  | (Extracts fields AND evaluates visual integrity signals)
  v
DocumentExtraction Schema
  |-- kind: cnh | rg | cin | unknown
  |-- fields: DocumentFields
  |-- transcription: str
  |-- warnings: list[str]
  +-- integrity: DocumentIntegrity
        |-- media_type: physical_original | digital_official | photocopy | screen_capture | unknown
        |-- risk_level: low | medium | high
        |-- tampering_detected: bool
        +-- flags: list[str]
  |
  v
Frontend UI (app.js / index.html / app.css)
  |-- Visual integrity badge (Neutral/Green, Amber, or Red)
  |-- Specific warning cards for recaptures or tampering
  +-- Audit trail in JSON / Ficha copy
```

---

## 4. Implementation Details

1. **Pydantic Schemas (`src/doc_extractor_pydantic/models.py`):**
   - Defined `MediaType` and `IntegrityRisk` literals.
   - Defined `DocumentIntegrity` model with `ConfigDict(extra="forbid")` and safe defaults.
   - Added automatic risk consistency validator (`tampering_detected => risk_level=high`, `screen_capture => risk_level=medium`).
   - Added `integrity: DocumentIntegrity = Field(default_factory=DocumentIntegrity)` to `DocumentExtraction`.
   - Injected warnings into `warnings` list when tampering or screen capture is observed.
2. **Multimodal Prompts (`src/doc_extractor_pydantic/prompts.py`):**
   - Added Rule 10 with clear multimodal instructions for evaluating media type, tampering, risk level, and flags.
3. **API Contract & Response (`src/doc_extractor_pydantic/extractor.py` and `main.py`):**
   - Mapped `integrity` in `to_api_response()`.
   - Included `INTEGRIDADE DO DOCUMENTO` section in `format_text()`.
   - Included `media_type` and `risk_level` in operational log without PII.
4. **Web Frontend (`index.html`, `app.css`, `app.js`):**
   - Added `#integrity-box` container in `index.html`.
   - Styled badges and risk indicators in `app.css` (both light and dark modes).
   - Rendered integrity badge, risk level, and flags in `renderResult()` in `app.js`.
   - Integrated integrity details into "Copiar ficha" (Ficha cadastral) and JSON download.
   - Reset integrity elements in `clearExtraction()` and `input.change`.
5. **Testing & Quality Gates:**
   - 7 new unit tests in `tests/test_extractor.py`.
   - 3 new Playwright tests in `tests/test_frontend_dom.py`.
   - Total test suite: 234 passing tests.
   - Ruff lint, python compileall, uv lock, uv pip check, and check_harness all verified green.
