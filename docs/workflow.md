# Workflow e checklist

## 1) Antes de codar

- Definir escopo e comportamento esperado.
- Identificar quais partes precisam ser documentadas.
- Decidir quais testes serão adicionados/atualizados.

## 2) Durante a implementação

- Manter a mudança pequena e revisável.
- Registrar as decisões e detalhes da implementação em um arquivo em `docs/changes/`.

## 3) Checklist obrigatório (antes de finalizar)

- Documentação criada/atualizada em `docs/changes/`.
- Smoke test atualizado quando aplicável (`smoke_test.py`).
- Execução local dos testes/validações.
- Verificar se o fluxo com Docker continua funcional.

## 4) Estrutura sugerida de arquivo em docs/changes/

Crie um arquivo com prefixo de data e título curto, por exemplo:

- `docs/changes/2026-02-14_tax-sync-source-and-smoke-robustness.md`

Estrutura recomendada:

- Contexto
- Mudança
- Detalhes de implementação
- Testes/validações executadas
- Como reproduzir
- Riscos/observações
