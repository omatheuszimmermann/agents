# Configuracao de ambiente (.env)

Este repo usa arquivos `.env` por componente. Sempre crie o `.env` a partir do `.env.example` na mesma pasta.

## Onde ficam os .env

1. Bot de comandos (Discord)
- Arquivo: `bots/discord-cmd-bot/.env`
- Exemplo: `bots/discord-cmd-bot/.env.example`
- Variaveis:
  - `DISCORD_TOKEN` (token do bot)

2. Integracao Discord (notificacoes)
- Arquivo: `integrations/discord/.env`
- Exemplo: `integrations/discord/.env.example`
- Variaveis:
  - `DISCORD_TOKEN` (ou)
  - `DISCORD_WEBHOOK_URL`

3. Agente Email (nivel do agente)
- Arquivo: `agents/email-triage/.env`
- Exemplo: `agents/email-triage/.env.example`
- Variaveis:
  - `CHANNEL_ID` (canal para notificacoes)
  - `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`

4. Agente Email (nivel do projeto)
- Arquivo: `agents/email-triage/projects/<projeto>/.env`
- Exemplo: `agents/email-triage/projects/<projeto>/.env.example`
- Variaveis:
  - `EMAIL_ADDRESS`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`
  - `IMAP_HOST`, `IMAP_PORT`, `IMAP_SECURE`
  - `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURE`

5. Agente Social Posts
- Arquivo: `agents/social-posts/.env`
- Exemplo: `agents/social-posts/.env.example`
- Variaveis:
  - `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`
  - `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`
  - `CHANNEL_ID` (opcional, para notificar no Discord)

## Ordem de carregamento (agente de emails)

O agente de emails carrega primeiro o `.env` do projeto e depois o `.env` do agente para completar valores faltantes.

## Passo rapido

1. Copie cada `.env.example` para `.env` na mesma pasta.
2. Preencha as variaveis obrigatorias.
3. Rode o agente/bot.
