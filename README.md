# ExtrAI

> **Automação inteligente, privativa e homologada para extração de documentos brasileiros (RG e CNH) e autopreenchimento de portais de Certificação Digital (ICP-Brasil).**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-e92063.svg?logo=pydantic)](https://docs.pydantic.dev/)
[![PydanticAI](https://img.shields.io/badge/PydanticAI-Multimodal-purple.svg)](https://ai.pydantic.dev/)
[![Chrome Extension](https://img.shields.io/badge/Chrome_Extension-Manifest_V3-4285F4.svg?logo=googlechrome)](https://developer.chrome.com/docs/extensions/)
[![Playwright](https://img.shields.io/badge/Playwright-E2E_Tests-45ba4b.svg?logo=playwright)](https://playwright.dev/)
[![LGPD](https://img.shields.io/badge/LGPD-Privacy_by_Design-green.svg)](#seguranca-da-informacao-e-privacidade-lgpd)
[![Tests Passing](https://img.shields.io/badge/Tests-219%20passed-success.svg)](#testes-e-garantia-de-qualidade)

---

## Cenário e Propósito do Projeto

O **ExtrAI** é uma solução de engenharia desenvolvida para automatizar o pipeline de extração de dados e preenchimento cadastral no ecossistema de Certificação Digital (**ICP-Brasil** — Soluti, Certisign, Valid, Serasa, Safeweb). O sistema substitui a transcrição manual de documentos de identificação (RG e CNH) por extração multimodal com IA e injeção assistida no navegador via extensão Manifest V3.

### Para quem é este projeto?

#### 1. Equipes de Onboarding, Operações e RegTech (KYC)
- **Eliminação de transcrição manual:** Extração estruturada e determinística de 10 campos cadastrais críticos em menos de 2 segundos, mitigando riscos de glosa em auditorias do ITI por erros de digitação.
- **Automação de formulários legados (Chrome MV3):** Injeção de dados via eventos sintéticos nativos, contornando bloqueadores de colagem (`Ctrl + V`) em campos de confirmação e sincronizando seletores AJAX assíncronos de municípios.

#### 2. Engenharia de Segurança, Compliance e DPOs (LGPD)
- **Zero Persistência Documental:** Processamento efêmero em memória volátil; arquivos e imagens são descartados após a requisição.
- **Memória Temporária com TTL (30 min):** Descarte automático de cache em memória via `time.monotonic()`, impedindo retenção não autorizada de dados na estação de trabalho.
- **Auditoria Segura (Zero PII):** Nenhum dado pessoal (nomes, CPFs, registros, e-mails ou imagens) é gravado em logs ou mantido em disco.
- **Isolamento de Rede:** Servidor restrito ao *loopback* local (`127.0.0.1`), com CSP rigorosa e bloqueio de transporte HTTP público inseguro na extensão.

#### 3. Desenvolvedores e Engenheiros de Software
- **Tipagem estrita e contratos previsíveis:** Backend assíncrono em **FastAPI** e **Pydantic v2**, garantindo validação de schema rígida na entrada e saída da API.
- **IA Estruturada com PydanticAI:** Orquestração multimodal (Google Gemini 3.5 Flash-Lite) com orçamentos de latência estritos e regras anti-alucinação (validação de CPF por Módulo 11 e consistência cronológica).
- **Testabilidade e Qualidade:** Suíte com **219 testes automatizados** (unitários e E2E headless com **Playwright**), executados 100% offline sem consumo de tokens de API.

---

## Impacto Operacional e Métricas de Desempenho

O comparativo abaixo reflete a medição em ambiente real de videoconferência:

| Etapa Operacional | Modo Manual Tradicional | Com o ExtrAI | Ganho / Economia |
| :--- | :---: | :---: | :---: |
| **Leitura, rotação e inspeção do documento** | ~60 s | ~2 s | **96% mais ágil** |
| **Digitação de 10 campos no portal** | ~120 s | < 1 s | **Instantâneo** |
| **Confirmação de e-mail (com bloqueio de colar)** | ~45 s | 0 s (preenchimento duplo automático) | **100% automatizado** |
| **Dupla conferência contra erros de digitação** | ~60 s | ~10 s (bate-olho de conferência) | **83% de redução** |
| **Tempo Total por Atendimento** | **~5 min 30 s** | **~15 segundos** | **95,4% mais rápido** |

### Projeção de Produtividade (Régua de 10 Atendimentos / Semana):
- **Por Semana (10 emissões):** de 55 minutos para apenas **2,5 minutos** (~52 minutos livres).
- **Por Mês (~45 emissões):** de ~4h10m para **~11 minutos** (quase meio dia útil recuperado).
- **Por Ano (~500 emissões):** de ~46 horas para **~2 horas** (**mais de 44 horas de trabalho repetitivo eliminadas**).

---

## Funcionalidades Principais

### 1. Extrator Web Inteligente
- **Processamento Multimodal com PydanticAI:** Extração de PDFs (multifolhas ou escaneados) e imagens (`.jpg`, `.jpeg`, `.png`, `.webp` até 15 MB) usando Google Gemini 3.5 Flash-Lite com orçamento de latência estrito.
- **Validação Determinística Sem Alucinações:** Checagem algorítmica do CPF pelo Módulo 11 da Receita Federal, conferência de calendário gregoriano e consistência cronológica (*Nascimento < Emissão < Validade*). O backend **descarta** dados inválidos e emite alertas visuais, sem nunca "adivinhar" valores.
- **Área de Transferência Ativa:** Pressione `Ctrl + V` em qualquer ponto da tela para colar uma imagem ou captura de tela diretamente.
- **Visualizador Forense:** Zoom fluido de 0,5x a 5x, rotação em 90°, arrasto interativo (*pan*) e suporte à roda do mouse para conferência minuciosa dos detalhes do documento.
- **Exportação Ágil:** Botões dedicados para cópia rápida de essenciais (`Alt + C`), cópia tabular TSV para Excel/Sheets (`Alt + T`), ou download completo em JSON/CSV.

### 2. Extensão Google Chrome (Manifest V3 — ExtrAI Autofill)
- **Preenchimento Simultâneo de 10 Campos:**
  - *Dados do Documento:* Nome Completo, CPF, Data de Nascimento, Registro/CNH.
  - *Dados da Emissão:* Telefone, Estado (UF), Cidade, E-mail Principal, Confirmação de E-mail e CNPJ (para emissões de PJ).
- **Atalho Universal (`Alt + P`):** Dispara o preenchimento instantâneo em segundo plano, mesmo com a janela do popup fechada.
- **Bypass Nativo de Bloqueadores de Colar:** Injeta eventos sintéticos (`input`, `change`, `blur`, `keyup`) e manipula protótipos de propriedades do DOM, preenchendo campos de confirmação que bloqueiam a colagem manual.
- **Sincronização com Dropdowns AJAX Assíncronos:** Observador inteligente que aguarda o carregamento dinâmico da lista de municípios após a seleção do estado no portal da Soluti.
- **Persistência Local Inteligente:** Salva os padrões operacionais mais frequentes do AGR (ex: Piauí, Teresina, telefone corporativo) via `chrome.storage.local` e `localStorage` síncrono.
- **Execução Defensiva e Não-Destrutiva:** Se um campo opcional estiver em branco (ex: cliente Pessoa Física sem CNPJ), a extensão pula o campo sem gerar erros, sem travar o portal e sem apagar dados já existentes.

---

## Segurança da Informação e Privacidade (LGPD)

O ExtrAI foi construído sob o princípio de **Privacy by Design & Zero Trust Local**:

| Invariante de Segurança | Implementação Técnica |
| :--- | :--- |
| **Zero Persistência Documental** | Documentos são processados em memória volátil e descartados imediatamente após a extração. |
| **Memória Temporária com TTL (30 min)** | O cache de preenchimento (`/api/last-extraction`) expira automaticamente após 30 minutos via `time.monotonic()`, garantindo que dados do cliente não fiquem órfãos na memória da máquina. |
| **Isolamento Estrito de Rede** | Middleware que restringe o tráfego exclusivamente ao *loopback local* (`127.0.0.1:8788`), rejeitando origens externas. |
| **Logs 100% Anônimos (Zero PII)** | Nenhuma informação pessoal (nomes, CPFs, números de documento, e-mails ou nomes de arquivo) é gravada em disco ou logs da aplicação. |
| **Sanitização de Repositório** | Regras no `.gitignore` impedem expressamente o versionamento acidental de chaves criptográficas (`.pfx`, `.p12`, `.pem`, `.key`, `.crt`) e pastas de documentos reais. |
| **Transporte Seguro na Extensão** | O content script valida o protocolo da aba ativa e bloqueia execuções sobre conexões HTTP públicas inseguras (restringe a `https://`, `file://` ou loopback local). |
| **Content Security Policy (CSP)** | Regras estritas tanto no frontend web quanto no `manifest.json` da extensão (`object-src 'none'`, sem `'unsafe-inline'`). |

---

## Arquitetura do Sistema

```text
┌────────────────────────────────────────────────────────────────────────┐
│                 FLUXO OPERACIONAL COMPLETO (END-TO-END)                │
└────────────────────────────────────────────────────────────────────────┘

  [DOCUMENTO (RG / CNH)]
          │
          ▼ (Upload Web / Ctrl+V)
  [FastAPI Backend - 127.0.0.1:8788]
     ├── LoopbackOnlyMiddleware (barreira contra acessos externos)
     ├── DocumentExtractor (processamento e normalização em memória)
     └── PydanticAI Agent (Google Gemini 3.5 Flash-Lite multimodal)
          │
          ▼
  [Validação Determinística Pydantic]
     ├── Módulo 11 de CPF & Calendário
     └── Descarte determinístico de alucinações (zero palpites)
          │
          ▼
  [Cache Local em Memória (TTL 30 min)]
          │
          │ (Polling seguro via loopback)
          ▼
  [Extensão Chrome Manifest V3]
     ├── Popup: Gestão de Padrões (Telefone, UF, Cidade, E-mail, CNPJ)
     ├── Content Script: Injeção assistida por eventos sintéticos
     └── Atalho Global Alt + P
          │
          ▼
  [Portal de Videoconferência / Certificadora (Soluti / Certisign)]
     └── 10 campos preenchidos com precisão cirúrgica em < 1 segundo!
```

---

## Stack Tecnológico

| Camada | Tecnologias Utilizadas |
| :--- | :--- |
| **Backend** | Python 3.11+, FastAPI, Uvicorn, Pydantic v2, PydanticAI |
| **Modelos de IA** | Google Gemini 3.5 Flash-Lite (padrão multimodal de altíssima velocidade e baixo custo) |
| **Processamento de Mídia** | PyPDF, Pillow (PIL), NumPy |
| **Frontend Web** | HTML5 semântico, Vanilla JavaScript moderno, CSS3 com Dark Mode nativo |
| **Extensão de Navegador** | Google Chrome Extension Manifest V3, Service Workers, Content Scripts, Chrome Storage API |
| **Qualidade & Testes** | Playwright (E2E headless), Pytest, AnyIO, Ruff Linter, UV Package Manager |

---

## Contrato da API

### 1. `GET /api/health`
Retorna a saúde do serviço local e confirmação da configuração do provedor.
```json
{
  "status": "ok",
  "storage": "temporary-only",
  "model": "google:gemini-3.5-flash-lite",
  "providerConfigured": true
}
```

### 2. `POST /api/extract`
Recebe o documento via formulário `multipart/form-data` no campo `document`.

**Campos extraídos no objeto `fields`:**
- `name`: Nome completo
- `cpf`: CPF com validação matemática de dígito verificador
- `birthDate`: Data de nascimento (DD/MM/AAAA)
- `issueDate`: Data de emissão (DD/MM/AAAA)
- `validity`: Data de validade da CNH (DD/MM/AAAA)
- `firstLicenceDate`: Data da 1ª habilitação da CNH (DD/MM/AAAA)
- `registration`: Número de registro do documento
- `category`: Categoria de habilitação (A, B, C, D, E, AB, etc.)
- `birthPlace`: Naturalidade / Local de nascimento
- `nationality`: Nacionalidade
- `parentage`: Filiação

### 3. `GET /api/last-extraction`
Endpoint consumido pela Extensão do Chrome via loopback. Retorna os dados da extração ativa ou expira com `hasData: false` caso o TTL de 30 minutos tenha sido ultrapassado:
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

## Como Executar o Projeto

### Pré-requisitos
- [Python 3.11+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/) (gerenciador de pacotes ultrarrápido)
- Google Chrome ou qualquer navegador compatível com Chromium (Edge, Brave, Opera)
- Chave de API do Google Gemini (gratuita no [Google AI Studio](https://aistudio.google.com/))

### 1. Clonar e Iniciar o Backend

```powershell
# 1. Clone o repositório
git clone https://github.com/Mateusallz1/ExtrAI.git
cd ExtrAI

# 2. Instale as dependências e o ambiente virtual
uv sync --dev

# 3. Configure as variáveis de ambiente
Copy-Item .env.example .env
```

Edite o arquivo `.env` inserindo sua chave:
```env
PYDANTIC_AI_MODEL=google:gemini-3.5-flash-lite
GEMINI_API_KEY=sua_chave_do_google_gemini_aqui
HOST=127.0.0.1
PORT=8788
```

Inicie o servidor local:
```powershell
uv run dev
```
Acesse a aplicação no navegador em: **`http://127.0.0.1:8788`**

---

### 2. Instalar a Extensão no Google Chrome

1. Abra o Google Chrome e navegue até: `chrome://extensions/`
2. No canto superior direito, ative a chave **Modo do desenvolvedor**.
3. Clique no botão **Carregar sem compactação** (*Load unpacked*).
4. Selecione a pasta `extension/` localizada na raiz do projeto `ExtrAI`.
5. Fixe o ícone do **ExtrAI** na barra de ferramentas do seu navegador.

---

### 3. Como Utilizar no Dia a Dia

1. Abra a aplicação web do ExtrAI (`http://127.0.0.1:8788`) e arraste o documento (ou cole com `Ctrl+V`).
2. Os dados serão extraídos e validados na tela.
3. Acesse a aba do portal da Certificadora (ex: videoconferência Soluti).
4. Abra o popup da extensão: confira os dados extraídos, informe o E-mail e CNPJ (se PJ) e clique em **"Preencher Formulário"** (ou simplesmente tecle **`Alt + P`**).
5. O formulário é preenchido e validado instantaneamente.

---

## Testes e Garantia de Qualidade

O projeto adota uma política rigorosa de engenharia com **219 testes automatizados** cobrindo desde regras semânticas de negócio até a injeção em formulários reais via Playwright, sem consumir tokens de API:

```powershell
# Executar a suíte de 219 testes automatizados
uv run pytest

# Verificação estática de código (Linter Ruff)
uv run ruff check src tests

# Verificação de integridade do bytecode
uv run python -m compileall -q src tests

# Checagem de dependências e lockfile
uv lock --check
uv pip check

# Verificação sintática dos scripts JavaScript
node --check src/doc_extractor_pydantic/static/app.js
node --check extension/popup/popup.js
node --check extension/content/content.js
node --check extension/background.js

# Verificação de conformidade do Harness de Engenharia
uv run python scripts/check_harness.py
```

---

## Mapa de Conhecimento e Governança

Para detalhes aprofundados sobre decisões arquiteturais e operacionais:
- [ARCHITECTURE.md](ARCHITECTURE.md): Estrutura de camadas, fluxo de dados e limites de dependência.
- [docs/SECURITY.md](docs/SECURITY.md): Políticas de proteção de dados pessoais, LGPD, chaves e superfícies de ataque.
- [docs/RELIABILITY.md](docs/RELIABILITY.md): Limites operacionais, orçamentos de latência e modos de falha.
- [docs/QUALITY.md](docs/QUALITY.md): Critérios de aceite, cobertura e portões de qualidade.
- [docs/exec-plans/README.md](docs/exec-plans/README.md): Planos de execução versionados.

---

## Licença

Este projeto é disponibilizado sob a licença [MIT](LICENSE).
