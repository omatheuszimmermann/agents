# Launchd (macOS)

Os arquivos `.plist` ficam versionados em `runner/launchd/`.

## Como instalar

1. Copie o `.plist` para `~/Library/LaunchAgents/`.
2. Ajuste os caminhos absolutos dentro do arquivo para o seu repo.
3. Carregue o job:

```bash
launchctl unload ~/Library/LaunchAgents/<arquivo>.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/<arquivo>.plist
```

## Arquivos existentes

- `runner/launchd/ai.mz.bot.plist`
  - Mantém o bot do Discord ativo.
- `runner/launchd/ai.agents.notion.worker.plist`
  - Worker que consome tasks do Notion periodicamente.
- `runner/launchd/ai.agents.notion.scheduler.plist`
  - Scheduler que cria tasks recorrentes no Notion.

## Observacoes

- `launchd` exige caminhos absolutos.
- Garanta que `runner/logs/` exista no servidor.
