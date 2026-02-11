# Frontend Launchd Control

Interface visual para listar, editar, instalar e remover jobs do launchd.

## Como usar

Abra `frontend/index.html` no navegador.

## Modos

- `mock`: usa dados locais (localStorage) para demonstracao.
- `live`: usa endpoints HTTP quando existe um backend.

Para ativar o modo live:

```
frontend/index.html?mode=live
```

## Endpoints esperados (modo live)

- `GET /api/launchd/jobs`
- `POST /api/launchd/jobs`
- `PATCH /api/launchd/jobs/:id`
- `DELETE /api/launchd/jobs/:id`

As rotas devem acionar `launchctl` no macOS e atualizar os plists reais.
