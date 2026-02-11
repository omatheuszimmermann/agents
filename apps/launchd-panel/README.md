# Frontend Launchd Control

Interface visual para listar, editar, instalar e remover jobs do launchd.

## Como usar

- Rode o servidor abaixo e abra a URL.

```bash
python3 apps/launchd-panel/launchd-manager/server.py
```

Acesse `http://localhost:8787`.

## Modos

Os dados sempre sao reais (launchctl/plists).

## Agendamentos

- Diario: HH:MM
- Semanal: selecione dias + HH:MM
- Intervalo: segundos

## Endpoints esperados (modo live)

- `GET /api/launchd/jobs`
- `POST /api/launchd/jobs`
- `PATCH /api/launchd/jobs/:id`
- `DELETE /api/launchd/jobs/:id`

As rotas acionam `launchctl` no macOS e atualizam os plists reais.
