# Receitas/Notas do mês + Guias sem PDF

## Objetivo
Adicionar funcionalidades que não dependem do enquadramento do Simples (Anexo) para apoiar o fechamento mensal de forma didática:

- Registro de **receitas/notas** por competência (base para relatórios e cálculo do Fator R).
- Permitir registrar **valor/vencimento/pagamento** das guias (DAS/FGTS/DARF) mesmo sem anexar PDF.

## O que foi implementado

### 1) Receitas / Notas
- Novo modelo `RevenueNote` com os campos:
  - `year`, `month`
  - `issued_at` (opcional)
  - `customer_name` (opcional)
  - `description` (opcional)
  - `amount` (obrigatório)
- Nova tela: `GET /payroll/revenue`
  - Lista lançamentos do mês e totaliza.
  - Formulário para registrar uma receita.
  - Ação para remover um lançamento.
- O Fechamento (`/payroll/close`) ganhou um item no checklist: **Receitas / notas do mês**.

### 2) Guias sem PDF
- `GuideDocument.filename` passou a aceitar `NULL`.
- A tela de Fechamento permite salvar/atualizar uma guia com:
  - `amount`, `due_date`, `paid_at`
  - **PDF opcional** (se anexado, continua disponível no botão “Abrir PDF”).

## Migração
Criada uma migration para:
- Alterar `guide_document.filename` para `nullable=True`.
- Criar tabela `revenue_note`.

Arquivo:
- `migrations/versions/2c3d4e5f6a7b_revenue_notes_and_guides_meta.py`

## Testes
- `smoke_test.py` foi atualizado para:
  - Registrar 1 receita de teste no mês da competência.
  - Validar que a tela de Receitas abre e mostra o valor esperado.
  - Validar que o Fechamento exibe o item de checklist de Receitas.

## Validação manual sugerida
- Abrir `Fechamento` e salvar uma guia preenchendo apenas valor e vencimento (sem PDF).
- Abrir `Receitas` e registrar 1 nota para o mês.
- Confirmar que o checklist marca as Receitas como OK após registrar ao menos 1 lançamento.
