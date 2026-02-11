# Launchd Manager

Esta pasta contem a lib e ferramentas para controle dos jobs do macOS (launchd) usando LaunchAgents.

## Uso rapido

- Modo interativo:

```bash
python3 apps/launchd-panel/launchd-manager/jobctl.py
```

- Listar jobs instalados:

```bash
python3 apps/launchd-panel/launchd-manager/jobctl.py --list
```

- Listar apenas jobs ativos (loaded):

```bash
python3 apps/launchd-panel/launchd-manager/jobctl.py --list-active
```

- Editar agendamento de um job:

```bash
python3 apps/launchd-panel/launchd-manager/jobctl.py --edit <label-ou-arquivo>
```

- Instalar um template do repo:

```bash
python3 apps/launchd-panel/launchd-manager/jobctl.py --install runner/launchd/<arquivo>.plist
```

- Remover um job:

```bash
python3 apps/launchd-panel/launchd-manager/jobctl.py --uninstall <label-ou-arquivo>
```

## Servidor HTTP (modo live)

```bash
python3 apps/launchd-panel/launchd-manager/server.py
```

Depois acesse a UI em `http://localhost:8787`.

## Como funciona

- Os templates ficam em `runner/launchd/`.
- Os jobs instalados ficam em `~/Library/LaunchAgents/`.
- Ao editar, o job e recarregado automaticamente com `launchctl`.
- Se existir um template com o mesmo nome do job instalado, ele tambem e atualizado.
- Ao criar/editar/excluir, o `runner/jobs.json` e sincronizado com o `Label` e `ProgramArguments`.

## Observacoes

- `launchd` exige caminhos absolutos em `ProgramArguments` e logs.
- Garanta que `runner/logs/` exista no servidor.
