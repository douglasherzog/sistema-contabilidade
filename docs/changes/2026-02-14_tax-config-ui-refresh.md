# Refresh visual do Config INSS/IRRF (UI/UX)

## Objetivo
Padronizar a tela de **Config INSS/IRRF** no mesmo estilo do restante do sistema:
- leve e elegante
- hierarquia visual clara
- texto didático e orientado a conferência

Sem alterar regras de negócio.

## O que foi alterado

- Cabeçalho padronizado (`lav-page-header`) com callout de atenção.
- Títulos de seção com `lav-section-title` + `lav-meta`.
- Microcopy didático para explicar o que cada tabela faz.

Arquivos:
- `templates/payroll/tax_config.html`

## Testes
- `smoke_test.py` executado com sucesso após o refresh.
