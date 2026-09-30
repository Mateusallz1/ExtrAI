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
- Imagens precisam ser legíveis, estáticas e respeitar o limite de pixels antes
  de carregar os dados. Apenas uma assinatura válida não basta.
- Corpo acima do limite é recusado com 413 antes de o multipart ser processado.
- PDF precisa ser legível e conter entre uma página e o limite de páginas.
- O PDF é aberto uma única vez por requisição.
- Nenhuma imagem é decodificada ou codificada em base64 antes do corte final.
- A prévia lê somente os XObjects selecionados: imagens inline não são
  decodificadas como efeito colateral. O limite de quatro conta tentativas.
- O stream do PDF é interpretado incrementalmente até o limite de operações,
  sem materializar a lista inteira primeiro.
- O processamento local roda em processo cancelável e não bloqueia o event loop
  durante parsing/decodificação. Timeout e cancelamento encerram o filho.
- Logs do parser não podem conter o marcador privado de um PDF sintético malformado.
- Saída inválida é removida e acompanhada de aviso, inclusive quando o campo não
  pertence ao tipo identificado.
- Aviso exclusivamente sobre um campo que o tipo identificado não possui é
  descartado. Avisos mistos preservam a informação sobre campos aplicáveis,
  como um alerta que menciona CPF e categoria em um RG.
- A interface não mistura resultados de arquivos diferentes.
- A extração inicia automaticamente quando um arquivo válido é selecionado, arrastado ou colado. O botão principal atua no envio/tentativa e se adapta para "Limpar análise" com resultados visíveis, mantendo reenvio via atalho (Ctrl+Enter).
- Quando existirem imagens incorporadas, a frente principal aparece em detalhe
  ampliável e os demais blocos aparecem como miniaturas.
- Copiar dados funciona ou exibe uma orientação manual amigável.
- CPF/datas incompletos são sinalizados ao encerrar a edição. Exportação manual
  continua permitida, com aviso explícito de inconsistência.
- CSV neutraliza prefixos de fórmula, inclusive após espaços/caracteres de controle.
- Imagens ficam integralmente enquadradas no zoom inicial e avisos permanecem
  acessíveis por rolagem em viewports estreitos ou de pouca altura.
- Falha transitória ou degradação de tempo do modelo principal aciona fallback automático para os modelos configurados.
- Cada modelo tem até três invocações, compartilhadas por retries de saída e de
  transporte. Uso inclui respostas anteriores e fallback; reservas só são
  construídas quando necessárias.
- Cancelar a tarefa HTTP cancela e aguarda seus filhos antes de liberar a vaga;
  falha/cancelamento da leitura também fecha o upload.
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
- O foco automático em regiões específicas dos campos ainda não faz parte do
  visualizador atual.
