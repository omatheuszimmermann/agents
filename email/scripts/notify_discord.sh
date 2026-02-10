#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="email/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE" >&2
  exit 1
fi

# Load env vars
set -a
source "$ENV_FILE"
set +a

if [[ -z "${DISCORD_WEBHOOK_URL:-}" ]]; then
  echo "DISCORD_WEBHOOK_URL is not set in $ENV_FILE" >&2
  exit 1
fi

MSG="${1:- Notificação de teste do agente.}"

# Send message
curl -sS -H "Content-Type: application/json" \
  -d "{\"content\":$(python3 - <<'PY'
import json, os
msg = os.environ.get("MSG_ARG", "")
print(json.dumps(msg))
PY
)}" \
  -o /dev/null \
  "$DISCORD_WEBHOOK_URL"
