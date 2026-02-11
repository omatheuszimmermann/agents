# Notion Database Schema (Tasks)

Crie um database chamado `Tasks` com os seguintes campos:

## Campos obrigatorios
- **Name** (Title)
  - Nome curto da task. Ex: "posts create secureapix"

- **Status** (Select)
  - Valores: `queued`, `running`, `done`, `failed`

- **Type** (Select)
  - Valores iniciais: `posts_create`, `email_check`
  - Pode expandir depois

- **Project** (Select)
  - Ex: `secureapix`

## Campos recomendados
- **Payload** (Rich text)
  - JSON com parametros extras (opcional)

- **RequestedBy** (Select)
  - Valores: `discord`, `notion`, `manual`, `system`

- **RunCount** (Number)
  - Incrementa a cada execucao

- **StartedAt** (Date)
- **FinishedAt** (Date)
- **LastError** (Rich text)

- **Result** (Rich text)
  - Output curto ou link para arquivo gerado

## Observacoes
- O worker so busca `Status=queued`.
- Ao iniciar, seta `Status=running`, `StartedAt=now`, `RunCount++`.
- Ao finalizar, seta `Status=done` ou `failed`, `FinishedAt=now`, `LastError` se falhou.
