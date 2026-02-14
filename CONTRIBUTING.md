# Contribuindo

## Padrão do projeto (obrigatório)

Neste repositório, **toda mudança** precisa atender os requisitos abaixo antes de ser considerada concluída.

- Documentar nos mínimos detalhes o que foi feito.
- Toda implementação deve ser testada.
- Tudo deve ser didático e auto-explicativo na interface.

## 1) Definição de pronto (Definition of Done)

Uma alteração só está pronta quando:

- Existe documentação explicando:
  - O objetivo.
  - O comportamento esperado.
  - Como reproduzir/validar.
  - Quais decisões foram tomadas e por quê.
  - Impacto em dados/migrações.
- Existe validação automatizada:
  - Atualização/adição de smoke test (quando aplicável), e/ou
  - Testes automatizados adicionais.
- O procedimento para rodar os testes está descrito.

Além disso, para mudanças que afetam UI/UX:

- A interface deve ser **didática** e **auto-explicativa** (usuário leigo em contabilidade).
- Campos e telas devem responder:
  - O que é isso?
  - Por que eu preciso preencher?
  - Onde encontro essa informação?
  - Qual o impacto no cálculo/relatório?
- Erros de validação devem orientar o usuário sobre como corrigir.
- Sempre que possível, incluir exemplos de preenchimento e textos de ajuda.

## 2) Fluxo de trabalho

1. Descreva a mudança em detalhes em `docs/changes/` (um arquivo por mudança).
2. Implemente o código.
3. Adicione/atualize testes.
4. Revise a UX e adicione textos de ajuda/explicações quando aplicável.
4. Execute as validações localmente.
5. Só então faça commit e push.

## 3) Como executar validações

### 3.1) Smoke test

Com Docker:

```bash
docker compose up -d --build
docker compose exec web_dev flask db upgrade
python smoke_test.py
```

Observação: o smoke test pode depender de rede (ex.: extração de tabelas oficiais). Para pular a parte de sync:

```bash
SMOKE_SKIP_DOCKER_SYNC=1 python smoke_test.py
```

### 3.2) Comandos úteis

- Ver status:

```bash
docker compose ps
```

- Rodar sync de tabelas tributárias:

```bash
docker compose exec web_dev flask sync-taxes
```

- Aplicar/gravar no banco:

```bash
docker compose exec web_dev flask sync-taxes --apply
```

## 4) Ambientes locais (isolamento obrigatório)

- Produção local (base quente): `web` + `db` em `http://localhost:8008`
- Desenvolvimento/testes: `web_dev` + `db_dev` em `http://localhost:8010`

Regra: toda validação automatizada (smoke/compliance) deve rodar no ambiente `web_dev`.
