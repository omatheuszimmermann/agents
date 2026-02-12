# Process Panel

Painel simples para monitorar os workers do Notion e processos do launchd.

## Como rodar

```bash
python3 apps/process-panel/server.py
```

Acesse em `http://localhost:8787`.

## Observacoes

- Os dados de ultima verificacao ficam em `runner/state/notion_worker.json` e `runner/state/notion_scheduler.json`.
- Os logs exibidos sao os arquivos presentes em `runner/logs/`.
