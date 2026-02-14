# Implementação do módulo de 13º Salário (CLT)

## Objetivo
Adicionar suporte ao 13º salário conforme CLT brasileira, incluindo:
- Parcelas (1ª e 2ª) com prazos legais
- Cálculo proporcional (salário / 12 × meses trabalhados)
- Recibo com avisos CLT
- Integração no Fechamento e Painel do mês

## Regras CLT Implementadas

### 1) Cálculo do 13º
- **Fórmula**: (salário base / 12) × meses trabalhados
- **Meses**: 1 a 12 (validação no backend)
- **Snapshot**: salário no momento do cálculo é congelado para auditoria

### 2) Parcelas e Prazos (CLT)
- **1ª parcela**: até 30 de novembro
  - Sem descontos de INSS/IRRF (conforme lei)
  - Recibo mostra aviso se pagamento for fora de novembro
- **2ª parcela**: até 20 de dezembro
  - Com descontos de INSS/IRRF
  - Recibo mostra aviso se pagamento for fora de dezembro
- **Integral (full)**: único pagamento
  - Com descontos aplicados

### 3) Descontos
- **1ª parcela**: sem descontos (estimativa = None)
- **2ª parcela e integral**: INSS progressivo + IRRF com dedução por dependente
- **Estimativas**: calculadas apenas se tabelas INSS/IRRF estiverem configuradas

## O que foi implementado

### Modelo (EmployeeThirteenth)
- `reference_year`: ano-base do cálculo
- `payment_year/month`: competência do pagamento
- `payment_type`: 1st_installment, 2nd_installment, full
- `months_worked`: 1-12
- `gross_amount`: valor bruto calculado
- `inss_est`, `irrf_est`, `net_est`: estimativas de descontos
- `base_salary_at_calc`: snapshot para auditoria

### Backend (payroll.py)
- Helper `_calc_thirteenth_amount()`: cálculo CLT
- Helper `_calc_thirteenth_month_summary()`: resumo por competência
- Rotas:
  - `GET /employees/<id>/thirteenth`: lista de pagamentos
  - `POST /employees/<id>/thirteenth`: cadastra pagamento
  - `GET /thirteenth/<id>/receipt`: recibo com avisos CLT
- Integração em `close_home()`: checklist e resumo

### Backend (main.py)
- Cálculo de resumo de 13º na Home
- Status card "13º no mês" no Painel

### Templates
- `employee_thirteenth.html`: tela de gestão do 13º com seletor de parcela e avisos CLT
- `thirteenth_receipt.html`: recibo imprimível com:
  - Dados do pagamento
  - Fórmula CLT explicada
  - Descontos (quando aplicável)
  - Avisos sobre prazos legais
- `employee_detail.html`: botão "Abrir 13º" ao lado de férias
- `close_home.html`: resumo de 13º na seção "Resumo do mês"
- `index.html`: card "13º no mês" no Painel

### Testes (smoke_test.py)
- Passos [7.5] e [7.6]: registro de 13º (2ª parcela, 12 meses)
- Validação de página, recibo e exibição no fechamento

## Validação
- `flask db upgrade` executado com sucesso (migration 5b7c2d3e4f5g)
- `smoke_test.py` passou (incluindo novos passos de 13º)

## Notas
- Cálculo didático para salário fixo (sem médias de variáveis)
- INSS/IRRF são estimativas para conferência (igual holerite)
- Avisos CLT no recibo ajudam a manter conformidade legal
- O sistema já possui `sync-taxes` para manter tabelas INSS/IRRF atualizadas
