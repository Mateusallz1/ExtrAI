# Confiabilidade

## Operação esperada

- Host local: `127.0.0.1`.
- Porta padrão: `8788`.
- Configuração: `.env` carregado pelo comando do Uvicorn.
- Entradas: PDF, JPG, JPEG e PNG até 15 MB.
- Resultado: sempre sujeito à revisão humana.

## Limites de consumo

Os limites ficam em `limits.py` e são aplicados antes de qualquer trabalho caro
sobre o documento.

| Limite | Valor | Onde age |
| --- | --- | --- |
| Corpo da requisição | upload + 64 KB de envelope | Middleware ASGI, antes do parser multipart |
| Tamanho do upload | `MAX_UPLOAD_BYTES` (15 MB) | `validate_upload` |
| Páginas do PDF | 20 | `validate_upload` |
| Páginas percorridas por prévia | 4 | Varredura de imagens incorporadas |
| Candidatas a detalhe | 24 | Varredura de imagens incorporadas |
| Pixels por imagem incorporada | 40 MP | Lido do `/Width` e `/Height` declarados |
| Content stream por página | 8 MB descomprimidos | Antes de interpretar os operadores |
| Detalhes retornados | 4 | Corte antes de decodificar e codificar em base64 |
| Análises simultâneas | 2 | `/api/extract`, com `429` acima disso |
| Tempo de resposta do provedor | 90 s | `asyncio.timeout` global na chamada do extrator, com `504` |
| Tempo por modelo antes de fallback | 45 s | Failover para o próximo modelo quando houver reserva |
| Tentativas do agente | 2 adicionais por modelo | Falhas transitórias (503/timeout) ou saída inválida |

O PDF é aberto uma única vez por requisição: `validate_upload` devolve o
`PdfReader` já validado e o restante do fluxo reaproveita esse objeto.

A seleção dos detalhes usa apenas metadados declarados no PDF. Só as quatro
imagens escolhidas são decodificadas e convertidas em base64; um XObject
desenhado várias vezes na mesma página vira um único detalhe.

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
- O retry do agente pode repetir uma chamada em caso de falha transitória (503/timeout) ou saída inválida,
  até 2 vezes adicionais por modelo e dentro do tempo limite global.
- A extração de imagens incorporadas é uma melhoria de prévia; se falhar, o PDF
  não impede a análise, e a interface informa que não há detalhe ampliado.
- A camada gratuita do provider pode apresentar variação de latência e políticas
  próprias de uso de dados.

Esses limites devem ser tratados antes de qualquer uso multiusuário ou produção.
