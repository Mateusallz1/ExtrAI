# Plano de Execução: Foco Visual por Campo (Field Highlighting / Bounding Boxes)

## Objetivo
Permitir que o usuário visualize instantaneamente no documento a região exata de onde cada dado foi extraído. Ao passar o mouse ou dar foco em um campo (ex: Nome, CPF, Registro, Filiação), uma moldura de destaque ilumina o trecho correspondente no visualizador do documento.

Resolve o limite técnico documentado em `docs/QUALITY.md`:
> *"O foco automático em regiões específicas dos campos ainda não faz parte do visualizador atual."*

---

## Escopo
1. **Modelo de Dados (`models.py`):**
   - Adicionar campo opcional `box_2d: list[int] | None` em `ExtractedField`.
   - Coordenadas normalizadas `[ymin, xmin, ymax, xmax]` no intervalo `0` a `1000`.
   - Validação semântica: 4 inteiros ordenados (`ymin < ymax` e `xmin < xmax`) entre 0 e 1000; coordenadas inválidas são descartadas como `None` sem quebrar a extração.

2. **Instruções ao Modelo (`prompts.py`):**
   - Instruir o Gemini a fornecer `box_2d` para campos identificados na imagem/PDF, usando o padrão nativo `[ymin, xmin, ymax, xmax]` (0-1000).

3. **Serialização e Contrato da API (`extractor.py`):**
   - Em `to_api_response`, repassar `box2d` no dicionário de cada campo identificado quando disponível.

4. **Visualizador Frontend (`index.html`, `app.css`, `app.js`):**
   - Estrutura de viewport sincronizada com zoom, pan e rotação.
   - Elemento de overlay `#focus-highlight` posicionado em percentuais (`top: ymin/10%`, `left: xmin/10%`, etc.).
   - Eventos de `mouseenter`, `mouseleave`, `focusin` e `focusout` nos `.field-card` para ligar e desligar o destaque visual no documento.

5. **Testes e Qualidade:**
   - Testes unitários de validação de `box_2d` em `tests/test_models.py` ou `tests/test_extractor.py`.
   - Testes DOM em `tests/test_frontend_dom.py` verificando a exibição e posicionamento do destaque ao interagir com os campos.
   - Atualização da documentação em `docs/QUALITY.md`.

---

## Não-objetivos
- Não recortar nem gerar arquivos de imagem separados por campo (mantém o documento íntegro e evita consumo excessivo de memória/CPU).
- Não forçar `box_2d` como campo obrigatório (se o modelo não retornar ou a região for incerta, a extração de texto continua funcionando perfeitamente).
- Não persistir nem salvar coordenadas ou arquivos no servidor.

---

## Riscos e Mitigações
1. **Alucinação ou coordenadas fora de escala:**
   - *Mitigação:* Validador Pydantic estrito em `ExtractedField` que descarta `box_2d` inválido (ex: fora de 0-1000 ou invertido) convertendo-o para `None`.
2. **Transformações de Zoom/Pan/Rotate descalibrarem o highlight:**
   - *Mitigação:* Posicionar o `#focus-highlight` dentro do mesmo contêiner transformado que a imagem ou aplicar a mesma matriz de transformação.
3. **Imagens com aspect ratio variável e PDFs multipágina:**
   - *Mitigação:* Coordenadas percentuais relativas às dimensões renderizadas da imagem base no visualizador.
