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

- **Fechamento assistido (próxima ação + bloqueio inteligente)**
  - Card "Próxima ação recomendada" aponta a tarefa mais importante para seguir
  - Exibe lista de pendências críticas (receitas, folha, tabelas fiscais, guias)
  - "Marcar como fechada" bloqueia quando houver pendência crítica e explica o motivo

- **Agenda automática de obrigações (proativa)**
  - Bloco com contadores de: atrasados, vencem hoje e próximos 7 dias
  - Lista didática de obrigações com "por que importa" e botão de ação
  - Inclui guias da competência (DAS/FGTS/DARF) e lembrete de compliance-check antes do vencimento

## Assistente IA na interface (Modo Guiado e Fechamento)

O sistema possui um assistente IA em duas telas:

- `Modo Guiado` (`/payroll/guide`)
- `Fechamento` (`/payroll/close`)

Se a chave de API não estiver configurada, o sistema continua funcionando e responde em **modo local de fallback** (sem chamada externa), priorizando ordem prática do checklist.

### Rotina pronta para configurar variáveis (Windows/PowerShell)

Foi adicionada a rotina:

- `scripts/set_ai_env.ps1`

Uso (define no `.env`):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\set_ai_env.ps1 -ApiKey "SEU_TOKEN"
```

Opcional: também definir no processo atual do terminal (além do `.env`):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\set_ai_env.ps1 -ApiKey "SEU_TOKEN" -AlsoSetProcessEnv
```

Opcional: usar outro arquivo de ambiente:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\set_ai_env.ps1 -ApiKey "SEU_TOKEN" -EnvFilePath ".env.local"
```

### Variáveis de ambiente

- `AI_ASSISTANT_ENABLED` (padrão: `true`)
- `AI_API_KEY` (obrigatória para IA externa)
- `AI_API_URL` (padrão: `https://api.openai.com/v1/chat/completions`)
- `AI_MODEL` (padrão: `gpt-4o-mini`)
- `AI_TIMEOUT_SECONDS` (padrão: `25`)
- `AI_KNOWLEDGE_ENABLED` (padrão: `false`)
- `AI_KNOWLEDGE_REFRESH_HOURS` (padrão: `24`)
- `AI_KNOWLEDGE_MAX_CHARS` (padrão: `12000`)
- `AI_KNOWLEDGE_TOP_K` (padrão: `3`)
- `AI_TRUSTED_SOURCES` (JSON ou lista separada por vírgula com URLs confiáveis)
- `AI_KNOWLEDGE_STRICT_WHITELIST` (padrão: `true`)
- `AI_KNOWLEDGE_ALLOWED_DOMAINS` (lista de domínios permitidos por vírgula)
- `AI_KNOWLEDGE_MIN_TRUST_SCORE` (padrão: `70`, escala 0-100)

### Aprendizado contínuo (RAG + experiência de uso)

- Quando `AI_KNOWLEDGE_ENABLED=true`, o sistema atualiza periodicamente um cache local com conteúdos de fontes confiáveis (CLT/Receita/eSocial/gov.br).
- O assistente usa esse cache como base externa (RAG) para melhorar respostas.
- Governança v2 aplicada antes da resposta:
  - whitelist estrita de domínio (quando ativada)
  - score de confiabilidade por fonte
  - revisão manual (approved/rejected/pending) na tela `Config IA`
- Endpoint para atualização manual do conhecimento:
  - `POST /payroll/ai/knowledge/refresh`
- Endpoint para registrar revisão de fonte aprendida:
  - `POST /payroll/ai/settings/knowledge/review`
- O uso do assistente é registrado em `instance/ai_assistant_usage.jsonl` para análise e melhoria contínua dos prompts e do fluxo.

### Segurança (recomendado)

- Nunca commitar `AI_API_KEY` no repositório.
- Definir chave apenas em ambiente (`.env` local ou variáveis do serviço).
- Revisar periodicamente logs e timeouts de integração externa.

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
