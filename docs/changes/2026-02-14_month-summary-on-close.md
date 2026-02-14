# Resumo do mês no Fechamento (estimativas)

## Contexto

Após implementar o Fechamento de competência (warn-only), o próximo passo foi dar mais utilidade prática e didática à tela `/payroll/close` sem depender ainda do enquadramento do Simples Nacional (Anexo/Fator R).

## Mudança

A tela de Fechamento passou a exibir um **Resumo do mês (estimativa)** com:

- Quantidade de funcionários na folha
- Total bruto do mês
- INSS estimado (empregado) total
- IRRF estimado total
- Líquido estimado (bruto - INSS - IRRF)
- Vigências das tabelas (INSS/IRRF) usadas

Observação de UX: o texto deixa explícito que os valores são **estimativas** baseadas:

- na folha do mês (linhas/holerites)
- nas tabelas de INSS/IRRF configuradas

## Detalhes de implementação

- Backend:
  - Função `_calc_month_summary(run)` em `app/payroll.py`.
  - Cálculo reutiliza as mesmas funções do holerite:
    - `_calc_inss_progressive`
    - `_calc_irrf`
  - Para dependentes, usa `EmployeeDependent.count()` por funcionário.

- Template:
  - Bloco novo em `templates/payroll/close_home.html`.

## Testes/validações

- `python smoke_test.py`
  - valida que a página de fechamento contém o bloco "Resumo do mês" (sem comparar valores exatos)

## Como validar manualmente

1. Crie/abra uma folha para uma competência.
2. Acesse:

- `/payroll/close?year=YYYY&month=MM`

3. Confirme que o bloco "Resumo do mês (estimativa)" aparece e mostra os totais.

## Observações

- Este resumo não depende do Anexo/PGDAS/Fator R.
- As estimativas são úteis para conferência e aprendizado, mas não substituem a apuração oficial.
