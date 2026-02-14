# Fechamento de competência (warn-only)

## Contexto

Precisávamos iniciar a entrega de **Fechamento da competência** como uma experiência didática e guiada, para conferir o mês antes de pagar guias e encerrar a competência.

Requisito: permitir marcar o mês como **FECHADO**, porém **sem bloqueio** (apenas aviso). O objetivo é organizar e reduzir risco de inconsistências sem atrapalhar correções.

## Mudança

- Foi criado um registro de competência fechada (`year`/`month`).
- A tela `/payroll/close` passou a exibir:
  - status de competência (em aberto / fechada)
  - botão para marcar como fechada
  - botão para reabrir
  - checklist didático com pendências e links diretos
- Ao alterar uma competência marcada como fechada:
  - salvar a folha emite aviso
  - anexar/substituir guia emite aviso

## Detalhes de implementação

- Novo model: `CompetenceClose` em `app/models.py`.
- Nova migration (alembic): `migrations/versions/0f7e5a9b2c1a_competence_close.py`.
- Novas rotas:
  - `POST /payroll/close/mark` (`payroll.close_mark`)
  - `POST /payroll/close/reopen` (`payroll.close_reopen`)
- Checklist na tela de fechamento é montado no backend e renderizado em `templates/payroll/close_home.html`.

## Testes/validações executadas

- `docker compose exec web flask db upgrade`
- `python smoke_test.py`
  - valida: anexar guia
  - valida: marcar competência como fechada e verificar UI
  - valida: reabrir competência e verificar UI

## Como reproduzir manualmente

1. Abra `/payroll/close?year=YYYY&month=MM`.
2. Clique em "Marcar como fechada".
3. Volte na folha e clique em "Salvar" (deve exibir aviso).
4. Na tela de fechamento, anexe/substitua um PDF (deve exibir aviso).
5. Clique em "Reabrir competência".

## Observações

- O fechamento é **organizacional** (warn-only): não impede alterações.
- O objetivo é guiar o usuário e reduzir risco de inconsistências.
