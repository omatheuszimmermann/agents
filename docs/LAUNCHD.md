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

## Gerenciamento rapido

Use o gerenciador em `frontend/launchd-manager/jobctl.py` para listar, instalar, editar ou remover jobs. Ele aplica as mudancas automaticamente no macOS.

```bash
python3 frontend/launchd-manager/jobctl.py
```

## Arquivos existentes

- `runner/launchd/ai.agents.runner.plist`
  - Executa o runner em horário fixo.
- `runner/launchd/ai.mz.bot.plist`
  - Mantém o bot do Discord ativo.
- `runner/launchd/ai.agents.email.secureapix.plist`
  - Verifica emails não lidos do projeto `secureapix` diariamente.

## Observacoes

- `launchd` exige caminhos absolutos.
- Garanta que `runner/logs/` exista no servidor.
