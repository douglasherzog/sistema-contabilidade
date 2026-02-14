# Máscara segura para campos monetários (pt-BR)

## Objetivo
Facilitar a digitação de valores monetários no formato pt-BR sem prejudicar a experiência do usuário.

- Entrada amigável: aceita digitação com `,` como separador decimal.
- Permite colar valores em formatos diferentes.
- Não “briga” com o cursor (evita implementações que travam o usuário).
- Backend continua aceitando valores com vírgula e ponto.

## O que foi implementado

### 1) Script de máscara (JS)
Atualizado:
- `static/input_masks.js`

Comportamento para `input.js-money`:
- Durante digitação (`input`):
  - mantém apenas dígitos e uma vírgula
  - limita a 2 casas decimais
  - não adiciona separador de milhar enquanto digita (para evitar pulo de cursor)
- Ao sair do campo (`blur`):
  - formata para pt-BR com 2 casas (ex.: `150` -> `150,00`, `1234,5` -> `1.234,50`)

### 2) Campos onde a máscara foi aplicada
- Salário base do funcionário
- Valor das guias (DAS/FGTS/DARF) no Fechamento
- Valor de receitas/notas
- Valor/hora extra
- Campos monetários do Config INSS/IRRF (até, deduções)

### 3) Backend tolerante
O backend já usa `_to_decimal()` (tolerante a `1.234,56` e `1234.56`).

## Testes
- `smoke_test.py` executado com sucesso.

## Validação manual sugerida
Em um campo monetário:
- Digitar `150` e sair do campo -> deve virar `150,00`.
- Digitar `1234,5` e sair -> deve virar `1.234,50`.
- Colar `1.234,56` -> deve manter correto.
- Colar `1234.56` -> deve virar `1.234,56` ao sair.
- Apagar/backspace no meio do texto e confirmar que não trava.
