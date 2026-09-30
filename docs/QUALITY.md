# Qualidade

## Gates obrigatórios

```powershell
uv run pytest
uv run ruff check src tests
uv run python -m compileall -q src tests
uv lock --check
uv pip check
node --check src/doc_extractor_pydantic/static/app.js
```

O check de estrutura do harness é executado com:

```powershell
uv run python scripts/check_harness.py
```

Os testes de navegador exigem o Chromium do Playwright uma única vez:

```powershell
uv run playwright install chromium
```

Sem ele, `tests/test_frontend_dom.py` falha em vez de passar em silêncio.

## Critérios de aceite

- Upload inválido é rejeitado antes do provider.
- Corpo acima do limite é recusado com 413 antes de o multipart ser processado.
- PDF precisa ser legível e conter entre uma página e o limite de páginas.
- O PDF é aberto uma única vez por requisição.
- Nenhuma imagem é decodificada ou codificada em base64 antes do corte final.
- Saída inválida é removida e acompanhada de aviso, inclusive quando o campo não
  pertence ao tipo identificado.
- Aviso do modelo sobre um campo que o tipo identificado não possui é descartado:
  um RG não avisa sobre registro, categoria ou validade.
- A interface não mistura resultados de arquivos diferentes.
- A extração inicia automaticamente quando um arquivo válido é selecionado, arrastado ou colado, mantendo reenvio manual via botão ou atalho.
- Quando existirem imagens incorporadas, a frente principal aparece em detalhe
  ampliável e os demais blocos aparecem como miniaturas.
- Quando coordenadas de localização (box_2d) estiverem disponíveis, passar o mouse ou dar foco em um campo destaca visualmente a região correspondente no documento.
- Copiar dados funciona ou exibe uma orientação manual amigável.
- Falha transitória ou degradação de tempo do modelo principal aciona fallback automático para os modelos configurados.
- Testes não fazem chamadas reais ao Gemini ou a outro provider.

## Limites atuais

- Não existe teste automatizado de acurácia contra documentos reais.
- Testes de provider são substituídos por agente falso e configuração local.
- A validação com `node` é apenas sintática. O comportamento é coberto por
  `tests/test_frontend_dom.py`, que roda a página real em Chromium headless e
  intercepta `/api/extract`: render de campos, avisos, cancelamento de
  requisição, erro da API, viewport estreito e cópia.
- `tests/test_frontend.py` continua verificando fragmentos do HTML. Serve como
  rede de segurança barata, não como prova de comportamento.
- Não há teste de aparência: cor, espaçamento e legibilidade continuam sendo
  conferidos a olho no navegador local.
- O foco visual por campo depende de o modelo conseguir identificar a região com clareza; campos em páginas não exibidas ou com coordenadas incertas continuam sem destaque sem afetar o dado extraído.
