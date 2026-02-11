# Jobs (launchd)

Esta pasta e o controle dos jobs do macOS (launchd) usando LaunchAgents.

## Uso rapido

- Modo interativo:

```bash
python3 frontend/launchd-manager/jobctl.py
```

- Listar jobs instalados:

```bash
python3 frontend/launchd-manager/jobctl.py --list
```

- Listar apenas jobs ativos (loaded):

```bash
python3 frontend/launchd-manager/jobctl.py --list-active
```

- Editar agendamento de um job:

```bash
python3 frontend/launchd-manager/jobctl.py --edit <label-ou-arquivo>
```

- Instalar um template do repo:

```bash
python3 frontend/launchd-manager/jobctl.py --install runner/launchd/<arquivo>.plist
```

- Remover um job:

```bash
python3 frontend/launchd-manager/jobctl.py --uninstall <label-ou-arquivo>
```

## Como funciona

- Os templates ficam em `runner/launchd/`.
- Os jobs instalados ficam em `~/Library/LaunchAgents/`.
- Ao editar, o job e recarregado automaticamente com `launchctl`.
- Se existir um template com o mesmo nome do job instalado, ele tambem e atualizado.

## Observacoes

- `launchd` exige caminhos absolutos em `ProgramArguments` e logs.
- Garanta que `runner/logs/` exista no servidor.
