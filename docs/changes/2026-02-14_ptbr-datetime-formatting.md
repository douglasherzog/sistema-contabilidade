# Padronização de datas/horas (pt-BR / São Paulo)

## Objetivo
Padronizar toda exibição de datas e horas na interface para o formato pt-BR e garantir que horários sejam exibidos no fuso de São Paulo.

- Data: `dd/mm/aaaa`
- Data e hora: `dd/mm/aaaa HH:MM`
- Fuso: `America/Sao_Paulo`

## O que foi implementado

### 1) Filtros globais Jinja
Foram adicionados filtros globais no `create_app()`:

- `fmt_date`: formata `date`/`datetime` para `dd/mm/aaaa`
- `fmt_dt`: formata `datetime` para `dd/mm/aaaa HH:MM`

Regras:
- Se o valor for `None`/vazio, retorna `—`.
- Se o valor for `datetime` sem timezone, assume UTC e converte para `America/Sao_Paulo` na exibição.

### 2) Padronização dos templates
Foi feita uma varredura e substituição dos usos de `strftime()` e `isoformat()` nos templates, trocando por:

- `{{ valor|fmt_date }}` para datas
- `{{ valor|fmt_dt }}` para data+hora

## Testes
- `smoke_test.py` executado com sucesso após reiniciar o container `web`.

## Observação
O objetivo é manter o armazenamento no banco como está (tipicamente UTC/naive), e **apenas converter/formatar na apresentação**.
