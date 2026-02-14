# sistema-contabilidade

Sistema de contabilidade para a lavanderia.

## Padrão do projeto (documentação + testes)

- Consulte `CONTRIBUTING.md` (regras de contribuição/Definition of Done).
- Consulte `docs/` (workflow, testes e registro de mudanças).

## Subir com Docker (recomendado)

1. Subir:
   
   ```bash
   docker compose up -d --build
   ```

2. Rodar migrations (primeira vez):

   ```bash
   docker compose exec web flask db init
   docker compose exec web flask db migrate -m "init"
   docker compose exec web flask db upgrade
   ```

3. Acessar:

- http://localhost:8008

## Desenvolvimento (sem Docker)

1. Crie/ative um venv e instale dependências:

```bash
pip install -r requirements.txt
```

2. Configure variáveis (ex.: copiar `.env.example` para `.env`).

3. Rode:

```bash
flask --app run.py --debug run
```
