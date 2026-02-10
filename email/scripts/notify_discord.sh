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

MSG="${1:- Notificação de teste do agente.}"

payload="{\"content\":$(python3 - <<'PY'
import json, os
msg = os.environ.get("MSG_ARG", "")
print(json.dumps(msg))
PY
)}"

# Prefer bot token + channel id when available
if [[ -n "${CHANNEL_ID:-}" && -n "${DISCORD_TOKEN:-}" ]]; then
  curl -sS -H "Content-Type: application/json" \
    -H "Authorization: Bot ${DISCORD_TOKEN}" \
    -d "$payload" \
    -o /dev/null \
    "https://discord.com/api/v10/channels/${CHANNEL_ID}/messages"
  exit 0
fi

if [[ -z "${DISCORD_WEBHOOK_URL:-}" ]]; then
  echo "DISCORD_WEBHOOK_URL or (CHANNEL_ID + DISCORD_TOKEN) must be set in $ENV_FILE" >&2
  exit 1
fi

# Fallback to webhook
curl -sS -H "Content-Type: application/json" \
  -d "$payload" \
  -o /dev/null \
  "$DISCORD_WEBHOOK_URL"
