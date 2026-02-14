# Testes e validação

## Smoke test (principal)

### Rodar com Docker

```bash
docker compose up -d --build
docker compose exec web_dev flask db upgrade
python smoke_test.py
```

### Pular sync externo (quando estiver sem rede/instável)

```bash
SMOKE_SKIP_DOCKER_SYNC=1 python smoke_test.py
```

## Validação manual

- `docker compose exec web_dev flask sync-taxes`
- `docker compose exec web_dev flask sync-taxes --apply`

## Regra do projeto (obrigatória)

- Smoke e validações automatizadas: **sempre no ambiente de testes** (`web_dev`/`db_dev`, porta `8010`).
- Uso real diário: **sempre no ambiente de produção local** (`web`/`db`, porta `8008`).

## Observações

O bloco de sync pode depender de rede e de mudanças em páginas oficiais. Quando houver instabilidade:

- Use `SMOKE_SKIP_DOCKER_SYNC=1` para validar o restante do sistema.
- Registre no arquivo de mudança em `docs/changes/` qual fallback foi utilizado (html/news/pdf) e o output relevante.
