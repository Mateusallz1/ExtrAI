# DocLume (Doc Extractor PydanticAI)

Extrator inteligente, privativo e auditável de documentos de identificação brasileiros (**RG** e **CNH**).

O **DocLume** processa imagens e arquivos PDF (incluindo documentos escaneados e multifolhas), identifica o tipo do documento e extrai dados cadastrais estruturados para conferência humana, combinando processamento local, validação semântica determinística e inteligência artificial multimodal via [PydanticAI](https://ai.pydantic.dev/). Não há avaliação automatizada de acurácia em documentos reais.

---

## Para quem é este projeto?

### 1. Operadores e Equipes de Negócios (KYC, RH, Onboarding)
- **Elimine a digitação manual**: extraia nome, CPF, datas e número de registro em segundos.
- **Fluxo ágil de trabalho**: cole imagens diretamente da área de transferência com `Ctrl + V`, use o botão **"Copiar essenciais"** para colar em formulários com um clique ou exporte relatórios em **CSV** e **JSON**.
- **Conferência visual facilitada**: pré-visualize imagens do documento com zoom fluido (0,5x a 5x), rotação em 90° e arrasto interativo lado a lado com os dados extraídos.
- **Validação imediata**: campos com potenciais inconsistências de digitação ou formatação recebem alertas visuais em tempo real na tela.

### 2. Gestores de Segurança, Compliance e DPO (LGPD)
- **Sem persistência documental própria**: processamento local e comunicação com o worker ocorrem em memória; o parser multipart pode usar spool temporário, fechado ao terminar a requisição. O conteúdo é enviado ao provider, sujeito às políticas dele.
- **Logs estritamente anônimos (Zero PII)**: nenhum nome, CPF, foto, documento ou texto extraído é gravado em arquivos de log.
- **Isolamento de rede**: o servidor roda exclusivamente em *loopback* (`127.0.0.1`), bloqueando chamadas de hosts externos ou de origens cruzadas não autorizadas.
- **Consumo acompanhado**: a API acumula invocações e tokens informados nas respostas, incluindo retries e fallback. Falhas sem métricas não permitem estimar todos os tokens ou a cobrança real; custos e termos dependem do provider contratado.

### 3. Desenvolvedores e Engenheiros de Software
- **Tipagem estrita e contratos previsíveis**: construído com **FastAPI** e **Pydantic v2**, garantindo validação de schema rígida na entrada e saída da API.
- **IA com limites operacionais (PydanticAI)**: até três invocações por modelo, compartilhadas entre retries de saída e transporte; 15 segundos para processamento local em processo cancelável e 90 segundos para a análise, incluindo preparação e provider.
- **Validação determinística no backend**: validação matemática do CPF, conferência de calendário e checagem cronológica. As instruções proíbem adivinhar valores; o backend descarta valores inválidos e apresenta avisos para revisão.
- **Frontend sem dependências pesadas**: interface construída em HTML5, Vanilla JS e CSS puro, compatível nativamente com Modo Escuro e com Content Security Policy (CSP) rigorosa (sem `'unsafe-inline'`).
- **Suíte de testes sem custo**: 100% dos testes unitários e de integração E2E com Playwright rodam localmente com mocks seguros, sem fazer chamadas externas nem gastar sua chave de API.

---

## Funcionalidades em Destaque

| Recurso | Descrição |
| :--- | :--- |
| **Formatos Suportados** | `.pdf`, `.jpg`, `.jpeg`, `.png` e `.webp` (até 15 MB; PDF até 20 páginas; imagens estáticas e legíveis até 40 MP). |
| **Área de Transferência** | Pressione `Ctrl + V` em qualquer ponto da tela para colar uma imagem ou captura de tela. |
| **Copiar Essenciais** | Copia instantaneamente Nome, CPF, Data de Nascimento e Registro para colar em cadastros. |
| **Exportação CSV & JSON** | Baixe a extração estruturada diretamente no navegador com 1 clique. |
| **Visualizador Interativo** | Zoom (0,5x a 5x), movimentação por arrasto (pan), roda do mouse e rotação em 90°. |
| **Validação em Tempo Real** | Alerta visual de borda vermelha se um CPF ou data editada estiver fora dos padrões oficiais. |
| **Detecção de Miniaturas** | Em PDFs de RG/CNH, extrai e amplia automaticamente as imagens embutidas (frente e verso). |
| **Modo Escuro NATIVO** | Adaptação automática à preferência do sistema operacional (`prefers-color-scheme`). |
| **Controle de Tokens** | Métricas transparentes de tokens de entrada/saída e latência retornadas na API. |

---

## Arquitetura do Sistema

```text
[Navegador / Cliente HTTP]
        │
        ▼ (POST /api/extract - multipart/form-data)
[FastAPI Middleware]
  ├── LoopbackOnlyMiddleware (rejeita tráfego não-local)
  └── RequestSizeLimitMiddleware (rejeita uploads > 15MB antes do spool em disco)
        │
        ▼
[DocumentExtractor & PyPDF]
  ├── Worker cancelável em memória: validação de legibilidade e limites
  └── Preparação de XObjects selecionados, com parsing incremental do PDF
        │
        ▼
[PydanticAI Agent]
  ├── Entrada multimodal (documento original + imagem de apoio)
  ├── Google Gemini 3.5 Flash-Lite (thinking_level=MINIMAL)
  └── UsageLimits (limite estrito de tokens e requests)
        │
        ▼
[Pydantic Validation & Sanitization]
  ├── Validação matemática de CPF (módulo 11)
  ├── Validação de calendário e regras cronológicas (nascimento < emissão < validade)
  └── Remoção determinística de valores inválidos + geração de warnings
        │
        ▼
[Resposta JSON Estruturada] ──> Revisão do Operador na Interface Web
```

---

## Início Rápido (Quickstart)

### Pré-requisitos
- **Python 3.11** ou superior
- Gerenciador de pacotes [uv](https://docs.astral.sh/uv/)
- Chave de API do **Google Gemini** (gratuita no [Google AI Studio](https://aistudio.google.com/)) ou OpenAI.

### Passo a Passo

1. **Clone o repositório e instale as dependências:**
   ```powershell
   git clone https://github.com/Mateusallz1/doclume.git
   cd doclume
   uv sync --dev
   ```

2. **Configure o arquivo de ambiente:**
   ```powershell
   Copy-Item .env.example .env
   ```
   Abra o arquivo `.env` e preencha sua chave:
   ```env
   PYDANTIC_AI_MODEL=google:gemini-3.5-flash-lite
   GEMINI_API_KEY=sua_chave_do_google_gemini_aqui
   HOST=127.0.0.1
   PORT=8788
   ```

3. **Inicie o servidor de desenvolvimento:**
   ```powershell
   uv run dev
   ```

4. **Acesse a aplicação:**
   Abra no seu navegador: <http://127.0.0.1:8788>

---

## Contrato da API

### 1. `GET /api/health`
Retorna o status da aplicação e a confirmação de que as credenciais do provedor estão configuradas.

### 2. `POST /api/extract`
Recebe o documento via formulário `multipart/form-data` no campo `document`.

**Campos extraídos no objeto `fields`:**
- `name`: Nome completo
- `cpf`: CPF com pontuação preservada
- `birthDate`: Data de nascimento (DD/MM/AAAA)
- `issueDate`: Data de emissão (DD/MM/AAAA)
- `validity`: Data de validade da CNH (DD/MM/AAAA)
- `registration`: Número de registro do documento
- `category`: Categoria de habilitação (A, B, C, D, E, AB, etc.)
- `birthPlace`: Naturalidade / Local de nascimento
- `nationality`: Nacionalidade
- `parentage`: Filiação (um nome por linha)

**Exemplo de Resposta:**
```json
{
  "kind": "cnh",
  "pages": 1,
  "fields": {
    "name": { "value": "MARIA DA SILVA", "confidence": "high", "label": "Nome" },
    "cpf": { "value": "123.456.789-09", "confidence": "high", "label": "CPF" },
    "birthDate": { "value": "15/05/1990", "confidence": "high", "label": "Data de nascimento" },
    "registration": { "value": "01234567890", "confidence": "medium", "label": "Registro" },
    "category": { "value": "B", "confidence": "high", "label": "Categoria" }
  },
  "missing": [],
  "warnings": [],
  "durationMs": 1420,
  "usage": {
    "requests": 1,
    "inputTokens": 1120,
    "outputTokens": 185
  },
  "previews": [
    {
      "label": "Frente",
      "primary": true,
      "src": "data:image/jpeg;base64,..."
    }
  ]
}
```

---

## Testes e Gates de Qualidade

O projeto conta com rigorosos portões de qualidade automatizados. Nenhuma alteração é promovida sem a aprovação de todos os gates:

```powershell
# Executar a suíte completa de testes (unitários e Playwright E2E)
uv run pytest

# Verificação estática de código e tipagem com Ruff
uv run ruff check src tests

# Verificação de compilação de bytecode
uv run python -m compileall -q src tests

# Verificação de dependências e integridade do lockfile
uv lock --check
uv pip check

# Sintaxe do script frontend
node --check src/doc_extractor_pydantic/static/app.js

# Verificação de integridade da documentação interna
uv run python scripts/check_harness.py
```

---

## Mapa da Documentação

- [ARCHITECTURE.md](ARCHITECTURE.md): Detalhamento do fluxo, camadas e limites de dependência.
- [docs/SECURITY.md](docs/SECURITY.md): Políticas de privacidade, dados pessoais, conformidade LGPD e segurança de rede.
- [docs/RELIABILITY.md](docs/RELIABILITY.md): Operação local, orçamentos de tempo, limites de tamanho e riscos conhecidos.
- [docs/QUALITY.md](docs/QUALITY.md): Critérios de aceite, cobertura de testes e validações.
- [docs/exec-plans/README.md](docs/exec-plans/README.md): Planos de execução versionados.
