# Correções de privacidade, confiabilidade e conferência

## Objetivo e escopo

Corrigir os cenários reproduzidos na revisão do commit `5841ea8`: logs do parser
com conteúdo documental, limites incompletos de PDF, retries e uso acumulado,
cancelamento da tarefa HTTP, construção antecipada de fallbacks, perda de avisos
mistos, validação manual incompleta, CSV interpretável como fórmula e corte de
documentos/avisos na interface. Rejeitar também imagens estruturalmente inválidas.

Manter o contrato da API, o modelo padrão e seu thinking mínimo, loopback na porta
8788, revisão humana e ausência de persistência documental própria.

Não inclui novos providers, documentos reais, migração da interface, autenticação
de produção, commit, push, merge ou deploy.

## Etapas

1. Registrar o plano e trabalhar na branch local `fix/extraction-hardening`.
2. Aplicar as correções do backend e testes sintéticos de regressão.
3. Aplicar as correções da interface e testes comportamentais no Chromium.
4. Atualizar a documentação dos domínios com as decisões finais e seus limites.
5. Executar harness e todos os gates; revisar diff, staged, untracked e ignored.
6. Mover este plano para `completed/` após cumprir os critérios de conclusão.

## Decisões e riscos

- Controles de log precisam incluir a dependência de PDF, sem registrar mensagens
  ou valores provenientes do arquivo.
- Um timeout de coroutine não interrompe parsing/decodificação síncronos. O trabalho
  local será isolado em processo cancelável, com comunicação somente em memória.
- Os limites devem atuar antes do parsing/decoding caro e contar tentativas, não
  somente prévias retornadas com sucesso.
- Retries internos e externos devem compartilhar um orçamento; o uso informado
  precisa acumular execuções, sem prometer equivalência com a cobrança do provider.
- O orçamento atua em `Model.request`. Retries internos do SDK OpenAI são
  desativados para não multiplicar requisições HTTP abaixo desse limite.
- Criação do worker e espera de IPC/cleanup usam threads. O cleanup aguarda a
  criação pelo SO antes de encerrar o filho, preservando a responsividade.
- Não existe teto rígido de memória do SO. O limite de stream ainda é aplicado
  após descompressão; CPU documental fica isolada no filho cancelável.
- Edição manual continua permitida: valores incompletos serão sinalizados ao
  encerrar a edição; exportação não será silenciosa quando houver inconsistências.
- A revisão não autoriza chamadas reais ao provider nem leitura de segredos.

## Validação e conclusão

Usar somente documentos e respostas sintéticos. Exercitar logs de PDF malformado,
parsing/decoding limitado, legibilidade de imagens, timeout/cancelamento local,
cleanup HTTP, retries/uso acumulado/fallback, avisos mistos e os cenários da UI.

Executar `uv run python scripts/check_harness.py`, pytest, Ruff, compileall,
`uv lock --check`, `uv pip check` e `node --check` do frontend. Não instalar ou
sincronizar dependências sem necessidade; usar o ambiente local e cache local.

Conclusão exige todos os gates aprovados, revisão do diff e registro dos riscos
residuais. Aprovação para operações Git externas continua separada.

## Resultado e validação final

- Concluído na branch `fix/extraction-hardening`, com base em `5841ea8`.
- Os nove cenários da revisão e a validação de legibilidade de imagens foram
  corrigidos, mantendo o contrato HTTP e os invariantes do piloto.
- A suíte completa passou: **203 testes em 16,84 segundos**, incluindo worker real,
  cancelamento asyncio/AnyIO, transporte HTTP simulado e Chromium.
- Harness, Ruff, compileall, lockfile, dependências, sintaxe JavaScript e revisão
  de whitespace passaram. Nenhuma dependência foi instalada ou atualizada.
- Diff, staged, untracked e ignored foram revisados. Staged vazio; arquivos novos
  pertencem à implementação/plano/testes; caches técnicos continuam ignorados.
- Revisão independente do diff integrado não encontrou pendência material.
- Nenhum provider real ou documento real foi usado. Nenhum commit, push, merge ou
  deploy foi realizado; essas decisões continuam separadas.
- A suíte inicial revelou interferência do event loop da sessão síncrona do
  Playwright nos novos testes de provider. Esses testes agora usam um loop próprio
  em thread; a execução com navegador e provider no mesmo processo foi validada.

## Riscos residuais

- Descompressão pode alcançar o teto interno do `pypdf` antes do corte de 8 MB;
  não há limite rígido de memória do SO. O worker descartável isola CPU e prazo.
- A criação de processo pelo SO não é preemptível; o cleanup aguarda seu resultado
  em thread antes de encerrar o filho, mantendo o event loop responsivo.
- Helpers internos de `pypdf` exigem as regressões atuais em atualizações do lock.
- Tokens indisponíveis em respostas de erro não são estimados. Acurácia real e
  disponibilidade/latência dos providers não foram avaliadas nesta mudança.
