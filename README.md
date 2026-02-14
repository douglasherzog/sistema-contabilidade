# sistema-contabilidade

Sistema de contabilidade para a lavanderia.

## Padrão do projeto (documentação + testes)

- Consulte `CONTRIBUTING.md` (regras de contribuição/Definition of Done).
- Consulte `docs/` (workflow, testes e registro de mudanças).

## Subir com Docker (recomendado)

Este projeto agora roda com **2 ambientes locais isolados**:

- **Produção local (base quente):** `web` + `db` em `http://localhost:8008`
- **Desenvolvimento/testes:** `web_dev` + `db_dev` em `http://localhost:8010`

### 1) Subir os ambientes

```bash
docker compose up -d --build
```

### 2) Rodar migrations (primeira vez)

Base quente (produção local):

```bash
docker compose exec web flask db upgrade
```

Base de desenvolvimento/testes:

```bash
docker compose exec web_dev flask db upgrade
```

### 3) Acessar

- Produção local (uso real): http://localhost:8008
- Desenvolvimento/testes: http://localhost:8010

## Regra operacional (acordo do projeto)

- **Uso diário real do sistema:** sempre em `web`/`db` (porta 8008).
- **Smoke tests e validações automáticas:** sempre em `web_dev`/`db_dev` (porta 8010).

## Sincronização oficial de tabelas fiscais (INSS/IRRF)

Agora o disparo está disponível também pela interface:

- Tela: `Folha > Configurar INSS/IRRF` (`/payroll/config/taxes`)
- Ações:
  - **Simular busca (dry-run)**: mostra relatório/fonte, sem gravar no banco
  - **Aplicar no banco**: grava INSS/IRRF quando validações mínimas passam

Fontes consultadas pelo sistema:

- INSS HTML (gov.br)
- INSS fallback oficial (notícia gov.br e/ou portaria PDF por ano)
- IRRF HTML da Receita Federal (gov.br), incluindo dedução por dependente

Observação: o comando CLI continua disponível (`flask sync-taxes`).

## Auditoria rápida e prazos legais (na tela de fechamento)

Na tela `Fechamento` (`/payroll/close`) agora existem dois blocos novos:

- **Compliance-check (auditoria rápida)**
  - Botão para rodar checagem de conformidade
  - Botão para rodar checagem + atualizar tabelas fiscais automaticamente
  - Relatório visível na própria interface

- **Prazos legais do mês (semáforo)**
  - Verde: no prazo
  - Amarelo: vence em breve
  - Vermelho: atrasado
  - Usa vencimento da guia quando informado; caso contrário, usa prazo operacional padrão exibido na tela

Smoke (padrão já aponta para ambiente de testes):

```bash
python smoke_test.py
```

Opcional, explícito:

```bash
BASE_URL=http://localhost:8010 SMOKE_WEB_SERVICE=web_dev python smoke_test.py
```

---

## Histórico (comandos antigos)

Antes havia apenas um ambiente. Se você vir comandos antigos como `docker compose exec web ...` para smoke, troque para `web_dev`.

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
