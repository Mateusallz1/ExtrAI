# Confiabilidade

## Operação esperada

- Host local: `127.0.0.1`.
- Porta padrão: `8788`.
- Configuração: `.env` carregado pelo comando do Uvicorn.
- Entradas: PDF, JPG, JPEG, PNG e WebP até 15 MB; imagens estáticas e legíveis.
- Resultado: sempre sujeito à revisão humana.

## Limites de consumo

Os limites ficam em `limits.py`. Tamanho/pixels são verificados antes da leitura
de pixels; parsing/decodificação roda em processo descartável com prazo próprio.

| Limite | Valor | Onde age |
| --- | --- | --- |
| Corpo da requisição | upload + 64 KB de envelope | Middleware ASGI, antes do parser multipart |
| Tamanho do upload | `MAX_UPLOAD_BYTES` (15 MB) | `validate_upload` |
| Páginas do PDF | 20 | `validate_upload` |
| Páginas percorridas por prévia | 4 | Varredura de imagens incorporadas |
| Candidatas a detalhe | 24 | Varredura de imagens incorporadas |
| Pixels por imagem incorporada | 40 MP | Lido do `/Width` e `/Height` declarados |
| Pixels por imagem enviada | 40 MP | Antes da verificação/carregamento com Pillow |
| Content stream por página | 8 MB descomprimidos | Antes de interpretar os operadores |
| Operações do content stream | 10.000 | Parser incremental, antes de ler a próxima operação |
| Tentativas de prévia | 4 | Corte antes de decodificar e codificar em base64 |
| Análises simultâneas | 2 | `/api/extract`, com `429` acima disso |
| Processamento local | 15 s | Processo descartável, encerrado em timeout/cancelamento |
| Tempo de análise | 90 s | Inclui processamento local e retries do provider, com `504` |
| Tempo por modelo antes de fallback | 45 s | Failover para o próximo modelo quando houver reserva |
| Invocações de modelo | 3 por modelo | Um orçamento para retries internos e externos, inclusive falhas |

O PDF é aberto uma única vez por requisição: `validate_upload` devolve o
`PdfReader` já validado e o restante do fluxo reaproveita esse objeto.

A seleção dos detalhes usa metadados declarados no PDF. Até quatro candidatos
são tentados, incluindo falhas de decodificação; somente XObjects escolhidos e
suas máscaras são decodificados. Imagens inline não são carregadas por enumeração
da página. Um XObject desenhado várias vezes na mesma página vira um único detalhe.
Dimensões reais de JPEG/JPX e dimensões das máscaras também são limitadas.

O nome original fica no processo HTTP para validar a extensão; o worker recebe
somente a extensão e o conteúdo, sem criar arquivos documentais. O parser multipart
pode usar spool temporário, fechado ao terminar a requisição.

`usage.requests` conta invocações no limite do modelo, inclusive falhas. Tokens
somam somente o consumo informado nas respostas recebidas, inclusive respostas
inválidas e fallback; não estimam tokens de falhas sem métricas nem cobrança real.
O orçamento de três é por modelo: uma reserva configurada possui seu próprio
orçamento, ainda sujeita ao prazo global.

## Dependências críticas

1. O servidor FastAPI precisa estar ativo.
2. O provider configurado precisa aceitar entrada multimodal e estar autenticado.
3. A rede externa precisa estar disponível para providers remotos.
4. A resposta precisa obedecer ao modelo `DocumentExtraction`.

## Falhas conhecidas

- Falha transitória ou degradação no modelo primário aciona automaticamente os modelos de
  reserva configurados em `PYDANTIC_AI_FALLBACK_MODELS` (padrão: `google:gemini-3-flash-preview`),
  garantindo resiliência sem intervenção manual.
- Se todos os modelos falharem, o resultado é HTTP 503 após retries; quota ou limite
  resulta em HTTP 429. Falhas não transitórias (como credenciais inválidas) não acionam fallback.
  Provider lento resulta em HTTP 504 quando o tempo limite local de 90s estoura; a
  chamada é cancelada, mas o custo já consumido no provedor não volta atrás.
- O piloto não possui autenticação nem rate limit por cliente: acima de duas
  análises simultâneas a resposta é `429`, sem fila e sem nova tentativa
  automática. Ver [SECURITY.md](SECURITY.md).
- Um único stream comprimido ainda pode ocupar até o teto do `pypdf` (75 MB) ao
  ser descomprimido, antes de o limite de 8 MB por página descartá-lo.
- Reservas são construídas quando necessárias; providers não suportados ou sem
  credenciais são excluídos. Falha de construção de uma reserva não substitui o
  erro original do primário nem impede um primário saudável de executar.
- Retries de saída e transporte compartilham três invocações por modelo. Não há
  reinício do orçamento a cada `agent.run()`.
- Os retries internos do SDK OpenAI são desativados; o backoff e o orçamento ficam
  sob controle da aplicação tanto em Chat quanto em Responses.
- A extração de imagens incorporadas é uma melhoria de prévia; se falhar, o PDF
  não impede a análise, e a interface informa que não há detalhe ampliado.
- A camada gratuita do provider pode apresentar variação de latência e políticas
  próprias de uso de dados.
- O processo descartável limita tempo e isola CPU documental, mas não impõe um
  teto rígido de memória do sistema operacional. Criação do processo e espera de
  IPC/limpeza usam threads; o processamento documental ocorre no filho. Se o SO
  demora a criar o processo, o cleanup precisa esperar essa criação terminar
  antes de encerrá-lo; o event loop continua responsivo durante essa espera.
- O parser incremental e o decoder de XObjects usam helpers internos do `pypdf`.
  Atualizações dessa dependência exigem reexecutar as regressões de preparação.
- Imagens animadas e cadeias de máscaras com mais de quatro imagens são recusadas
  ou omitidas da prévia; não fazem parte do fluxo de identificação estática.

Esses limites devem ser tratados antes de qualquer uso multiusuário ou produção.
