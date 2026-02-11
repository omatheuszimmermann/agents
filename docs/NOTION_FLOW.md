# Notion Flow (Tasks)

## Fluxo
1. Discord recebe comando (ex: `@MZ posts create secureapix`).
2. Bot cria uma task no Notion com `Status=queued`.
3. Scheduler (`runner/notion_scheduler.py`) cria tasks recorrentes no Notion com base em `runner/notion_schedule.json`.
4. Worker (`runner/notion_worker.py`) roda periodicamente via Launchd.
5. Worker busca tasks `queued`, marca como `running`, executa o agente.
6. Worker atualiza status para `done` ou `failed` e grava `Result/LastError`.

## Componentes
- Bot: `bots/discord-cmd-bot/index.js`
- Scheduler: `runner/notion_scheduler.py`
- Worker: `runner/notion_worker.py`
- Cliente Notion: `shared/python/lib/notion_client.py`
- Env Notion: `integrations/notion/.env`
- Launchd templates:
  - `runner/launchd/ai.agents.notion.worker.plist`
  - `runner/launchd/ai.agents.notion.scheduler.plist`

## Types suportados (iniciais)
- `posts_create` -> `agents/social-posts/scripts/generate_post.py <project>`
- `email_check` -> `agents/email-triage/scripts/agent.py <project> 20 --status unread`

## Observacoes
- O scheduler cria tasks **somente** se ele mesmo nao criou no periodo (RequestedBy=system).
- Tasks criadas manualmente nao contam como duplicadas.
- Se o Mac ficar desligado, as tasks ficam `queued` e serao processadas na proxima execucao do worker.
- `NOTION_MAX_TASKS` limita quantas tasks sao processadas por ciclo.
