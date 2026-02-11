# Frontend Launchd Control

Interface visual para listar, editar, instalar e remover jobs do launchd.

## Como usar

- Modo local (mock): abra `frontend/index.html` no navegador.
- Modo live (dados reais): rode o servidor abaixo e abra a URL.

```bash
python3 frontend/launchd-manager/server.py
```

Acesse `http://localhost:8787`.

## Modos

- `mock`: usa dados locais (localStorage) para demonstracao.
- `live`: usa endpoints HTTP reais (launchctl/plists).

Para forcar um modo:

```
frontend/index.html?mode=live
frontend/index.html?mode=mock
```

## Endpoints esperados (modo live)

- `GET /api/launchd/jobs`
- `POST /api/launchd/jobs`
- `PATCH /api/launchd/jobs/:id`
- `DELETE /api/launchd/jobs/:id`

As rotas acionam `launchctl` no macOS e atualizam os plists reais.
