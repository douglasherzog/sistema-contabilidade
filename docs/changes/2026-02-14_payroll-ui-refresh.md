# Refresh visual da Folha e Holerite (UI/UX)

## Objetivo
Melhorar as telas de **Folha** e **Holerite** para:
- ficar mais leve e elegante
- ter hierarquia visual clara
- reforçar a didática (o que fazer / por quê / próximo passo)

Mantendo compatibilidade com o `smoke_test.py`.

## O que foi alterado

### 1) Folha (home)
- Cabeçalho padronizado (`lav-page-header`).
- Seletor de competência com título e meta.

Arquivos:
- `templates/payroll/payroll_home.html`

### 2) Folha (edição)
- Cabeçalho padronizado e callout didático “Como preencher”.
- Seções “Parâmetros do mês” e “Lançamentos por funcionário”.

Importante:
- A estrutura da tabela e os textos-chave foram mantidos para não quebrar o `smoke_test.py`.

Arquivos:
- `templates/payroll/payroll_edit.html`

### 3) Holerite
- Cabeçalho padronizado com callout “Como usar este holerite”.
- Troca de containers para `lav-panel` (estilo consistente).

Arquivos:
- `templates/payroll/holerite.html`

## CSS
- Novos helpers no `static/styles.css`:
  - `lav-panel`
  - `lav-kv`

## Testes
- `smoke_test.py` executado com sucesso após o refresh.
