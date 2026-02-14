# Máscara segura para campos de data (pt-BR)

## Objetivo
Facilitar a digitação de datas no formato pt-BR sem prejudicar a experiência do usuário.

- Formato de entrada: `dd/mm/aaaa`
- O usuário pode **digitar**, **apagar**, **mover o cursor**, e **colar** sem travamentos.
- O backend aceita tanto `dd/mm/aaaa` quanto ISO `yyyy-mm-dd`.

## O que foi implementado

### 1) Script de máscara (JS)
Criado:
- `static/input_masks.js`

Comportamento:
- Aplica máscara apenas em `input.js-date`.
- Mantém o cursor o mais próximo possível do ponto de digitação.
- No `blur`, normaliza ISO (`yyyy-mm-dd`) para pt-BR (`dd/mm/aaaa`).

### 2) Aplicação nos formulários
Campos de data foram alterados de `type="date"` para `type="text"` com:
- classe `js-date`
- `placeholder="dd/mm/aaaa"`
- `inputmode="numeric"`

### 3) Backend tolerante
Foi criado o helper `_parse_date()` em `app/payroll.py` para aceitar:
- `yyyy-mm-dd` (ISO)
- `dd/mm/aaaa` (pt-BR)

E ele foi aplicado nos endpoints que recebem datas via formulário.

## Testes
- `smoke_test.py` executado com sucesso.

## Validação manual sugerida
Em qualquer campo com data:
- Digitar devagar `01022026` e verificar que vira `01/02/2026`.
- Apagar com backspace no meio do valor e confirmar que não “trava”.
- Colar `2026-02-01` e confirmar que vira `01/02/2026` ao sair do campo.
