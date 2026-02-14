# Refresh visual do Fechamento (UI/UX)

## Objetivo
Melhorar a tela de **Fechamento** para:
- ficar mais leve e elegante
- ter hierarquia visual clara
- reforçar a didática (o que fazer / por quê / para onde ir)

Sem quebrar o fluxo existente nem alterar textos-chave usados no `smoke_test.py`.

## O que foi alterado

### 1) Hierarquia e layout
- Cabeçalho da página com estrutura padrão (`lav-page-header`).
- Status da competência como callout (aberta/fechada) com melhor leitura.
- Checklist dentro de um card “Checklist guiado”, com microcopy orientando o usuário.

### 2) Checklist mais guiado
- Cards do checklist com destaque lateral (`lav-check-card`) e estados visuais:
  - `is-ok`
  - `is-pending`

### 3) Resumo do mês e Guias do mês
- Ajuste de títulos/meta para leitura rápida.
- Seção “Guias do mês” passou a ter título e explicação didática.

## CSS
- Reuso de componentes do `static/styles.css`.

## Testes
- `smoke_test.py` executado com sucesso após o refresh.
