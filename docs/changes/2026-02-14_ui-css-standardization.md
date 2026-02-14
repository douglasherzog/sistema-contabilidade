# Padronização visual (CSS) e remoção de warnings (Edge Tools)

## Objetivo
Padronizar a aparência do sistema com um estilo leve e elegante, mantendo usabilidade e tom didático.

Além disso, remover avisos comuns do Edge Tools, especialmente:
- CSS inline via `style="..."`
- marcação de listas (`<ul>/<ol>`) com filhos inválidos

## O que foi implementado

### 1) CSS central do projeto
Criado:
- `static/styles.css`

Inclui:
- sombreamento leve em cards
- bordas mais suaves
- helpers utilitários para tabelas e assinaturas

Carregado em:
- `templates/base.html`

### 2) Remoção de CSS inline
Foram removidos `style="..."` e substituídos por classes CSS:
- `lav-th-fit` para colunas pequenas (ações)
- `lav-cell-input-narrow` para célula de input mais estreita
- `lav-signature-line` para linha de assinatura no holerite

### 3) Ajuste de marcação
O bloco de configs IRRF (lista) foi substituído por `<div>` para evitar warnings do Edge Tools sobre filhos inválidos dentro de `<ul>`.

## Testes
- `smoke_test.py` executado com sucesso.

## Próximos passos sugeridos
- Evoluir gradualmente o `styles.css` com tokens de design (cores/espacamentos) e componentes didáticos (caixas de dica, passos, checklist mais visual).
