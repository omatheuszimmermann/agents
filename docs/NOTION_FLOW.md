# Notion Flow (Tasks)

## Fluxo
1. Discord recebe comando (ex: `@MZ posts create secureapix`).
2. Bot cria uma task no Notion com `Status=queued`.
3. Worker (`runner/notion_worker.py`) roda periodicamente via Launchd.
4. Worker busca tasks `queued`, marca como `running`, executa o agente.
5. Worker atualiza status para `done` ou `failed` e grava `Result/LastError`.

## Componentes
- Bot: `bots/discord-cmd-bot/index.js`
- Worker: `runner/notion_worker.py`
- Cliente Notion: `shared/python/lib/notion_client.py`
- Env Notion: `integrations/notion/.env`
- Launchd template: `runner/launchd/ai.agents.notion.worker.plist`

## Types suportados (iniciais)
- `posts_create` -> `agents/social-posts/scripts/generate_post.py <project>`
- `email_check` -> `agents/email-triage/scripts/agent.py <project> 20 --status unread`

## Observacoes
- Se o Mac ficar desligado, as tasks ficam `queued` e serao processadas na proxima execucao do worker.
- `NOTION_MAX_TASKS` limita quantas tasks sao processadas por ciclo.
