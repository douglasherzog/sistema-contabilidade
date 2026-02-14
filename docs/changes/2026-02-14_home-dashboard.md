# Home como Painel do mês (competência atual + seletor)

## Objetivo
Transformar a Home (`/`) em um painel didático do mês:
- mostra a competência atual por padrão
- permite selecionar outra competência (ano/mês)
- exibe status rápido (Receitas, Folha, Tabelas INSS/IRRF, Guias, Competência)
- sugere um “próximo passo” para o usuário

## O que foi implementado

### 1) Rota Home com resumo de status
- A rota `GET /` agora aceita `?year=YYYY&month=MM`.
- Se não informar, usa o mês/ano atuais.
- Calcula status para:
  - receitas (`RevenueNote`)
  - folha (`PayrollRun`)
  - tabelas (`TaxInssBracket`, `TaxIrrfBracket`, `TaxIrrfConfig`)
  - guias (`GuideDocument`)
  - competência fechada (`CompetenceClose`)

### 2) UI do Painel
- Seletor de competência
- Callout “Próximo passo sugerido”
- Cards “Status rápido” com OK/Pendente e links

Arquivos:
- `app/main.py`
- `templates/index.html`

## Testes
- `smoke_test.py` executado com sucesso.
