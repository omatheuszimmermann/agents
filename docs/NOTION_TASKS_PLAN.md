# Notion Tasks - Checklist

## Objetivo
Usar o Notion como fila unica de execucao. O runner busca tasks pendentes, executa agentes e atualiza status.

## Checklist
1. Definir o schema do Database no Notion (campos e tipos).
2. Criar credenciais e variaveis de ambiente do Notion.
3. Implementar cliente Notion (list, create, update).
4. Criar worker (poller) que consome tasks pendentes.
5. Mapear types -> comandos dos agentes.
6. Ajustar bot para criar tasks no Notion (nao executar direto).
7. Criar Launchd para rodar o worker periodicamente.
8. Documentar fluxo end-to-end.

## Status
- [x] 1. Definir o schema do Database no Notion (campos e tipos).
- [x] 2. Criar credenciais e variaveis de ambiente do Notion.
- [x] 3. Implementar cliente Notion (list, create, update).
- [x] 4. Criar worker (poller) que consome tasks pendentes.
- [x] 5. Mapear types -> comandos dos agentes.
- [x] 6. Ajustar bot para criar tasks no Notion (nao executar direto).
- [x] 7. Criar Launchd para rodar o worker periodicamente.
- [x] 8. Documentar fluxo end-to-end.
