# Implementação do módulo de Férias

## Objetivo
Adicionar suporte a registro de férias (gozo e venda/abono) no sistema, integrando:
- Cadastro de férias por funcionário (dias de gozo + dias vendidos)
- Cálculo didático (salário fixo, sem médias)
- Recibo imprimível
- Integração no Fechamento e no Painel do mês (Home)

## O que foi implementado

### 1) Modelo e migration
- `EmployeeVacation` com campos: employee_id, year, month, start_date, days, sell_days, pay_date, base_salary_at_calc, valores calculados (vacation_pay, vacation_one_third, abono_pay, abono_one_third, gross_total) e estimativas de descontos (inss_est, irrf_est, net_est).
- Migration: `4a6b1c2d3e4f_employee_vacations.py`

### 2) Backend (payroll.py)
- Helper `_calc_vacation_amounts()`: cálculo baseado em salário fixo (base/30).
- Helper `_calc_vacations_month_summary()`: resumo por competência.
- Rotas:
  - `GET /employees/<id>/vacations`: lista de férias do funcionário.
  - `POST /employees/<id>/vacations`: cadastra férias (validações: 1-30 dias, 0-10 vendidos, soma <= 30).
  - `GET /vacations/<id>/receipt`: recibo imprimível.
- Integração no `close_home()`: checklist "Férias no mês" + resumo no card de totais.

### 3) Backend (main.py)
- Import `EmployeeVacation` e cálculo de resumo de férias.
- Status "vacations" no painel da Home com count e total_gross.

### 4) Templates
- `employee_vacations.html`: tela para agendar/listar férias (competência seletor + formulário + histórico com link para recibo).
- `vacation_receipt.html`: recibo com dados do funcionário, valores (férias, 1/3, abono, 1/3 do abono), descontos estimados e assinaturas.
- `employee_detail.html`: botão "Abrir férias".
- `close_home.html`: checklist com meta (count/total) e resumo de férias no mês.
- `index.html`: card "Férias no mês" no painel de status.

### 5) Testes
- `smoke_test.py` atualizado com passos [7.3], [7.4], [7.5]:
  - Registra férias (15 dias + 5 vendidos).
  - Valida página de férias e recibo.
  - Valida exibição no Fechamento.

## Validação
- `flask db upgrade` executado com sucesso.
- `smoke_test.py` passou.

## Notas
- O cálculo é didático para salário fixo (sem médias de variáveis).
- INSS/IRRF são estimativas, igual ao holerite.
- "Dias vendidos" (abono pecuniário) pode ser 0-10 dias.
