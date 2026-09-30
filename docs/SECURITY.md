# Segurança e privacidade

## Fluxo de dados

O arquivo recebido é processado pelo backend e enviado ao provider multimodal
configurado. Em PDFs com imagens incorporadas, a imagem principal também é
enviada como parte complementar da mesma análise. A aplicação não cria
armazenamento permanente próprio, mas o
provider externo possui suas próprias políticas de retenção e uso de dados.

Não use documentos reais na camada gratuita sem avaliar essa política e obter a
autorização adequada.

## Regras

- Nunca colocar API keys no código, no Git, em testes ou na documentação.
- Nunca enviar o nome do arquivo ao modelo.
- Nunca registrar conteúdo, campos extraídos, imagens, PDFs ou nomes de arquivo.
- O logger de `pypdf` é suprimido antes do parsing, pois seus diagnósticos podem
  incluir tokens do conteúdo. Essa regra tem regressão com PDF sintético malformado.
- Responder com `Cache-Control: no-store` e headers de proteção para evitar cache
  ou interpretação indevida no navegador.
- Manter CSS e JavaScript em arquivos próprios: a CSP não usa `'unsafe-inline'`
  e define `frame-ancestors 'none'`. Não reintroduzir `<style>`, `<script>` ou
  atributo `style` no HTML.
- Servir apenas os arquivos estáticos declarados em `STATIC_ASSETS`, nunca um
  caminho vindo da URL.
- Fechar explicitamente o upload ao terminar a requisição para liberar qualquer
  spool temporário usado pelo parser multipart.
- Usar `textContent` na interface para dados vindos do modelo.
- Manter a revisão humana antes de qualquer uso operacional.
- Usar apenas arquivos sintéticos nos testes automatizados.
- Parsing/decodificação local ocorre em um processo descartável. A comunicação é
  feita por pipe em memória, passando somente extensão e bytes; timeout ou
  cancelamento encerra o processo e fecha o pipe antes de liberar a vaga.
- Arquivos CSV neutralizam conteúdo interpretável como fórmula. Isso não altera
  o valor original exibido ou exportado em JSON.

## Exposição do endpoint

O piloto atende somente o computador local e não possui autenticação. Duas
barreiras aplicam isso:

- `HOST` fora de loopback aborta a inicialização em `Settings.from_env()`.
- `LoopbackOnlyMiddleware` responde `403` quando o cliente não é loopback,
  qualquer que seja o endereço em que o servidor foi colocado para escutar, e
  também quando a requisição traz um `Origin` de outro host.
- `ConcurrencyLimit` responde `429` acima de duas análises simultâneas, para que
  um cliente local não consuma a chave do provedor em rajada.

Antes de publicar em rede, isso não basta: é preciso autenticação, host
permitido, rate limit por cliente e revisão do controle de concorrência.

## Revisão de mudança

Antes de alterar o fluxo de documentos, verificar: destino dos bytes, mensagens
de erro e logs, arquivos temporários, limites de tamanho/páginas, tratamento de
segredos e possibilidade de o conteúdo instruir o modelo a ignorar as regras.
