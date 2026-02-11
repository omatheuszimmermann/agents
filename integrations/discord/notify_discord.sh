#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE" >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

CHANNEL_ID="${1:-}"
MSG="${2:- Notificação de teste do agente.}"

if [[ -z "$CHANNEL_ID" ]]; then
  echo "CHANNEL_ID is required as first argument" >&2
  exit 1
fi

export MSG_ARG="${MSG_ARG:-$MSG}"
payload="{\"content\":$(python3 - <<'PY'
import json, os
msg = os.environ.get("MSG_ARG", "")
print(json.dumps(msg))
PY
)}"

if [[ -n "${DISCORD_TOKEN:-}" ]]; then
  tmp_body="$(mktemp)"
  http_code="$(
    curl -sS -H "Content-Type: application/json" \
      -H "Authorization: Bot ${DISCORD_TOKEN}" \
      -d "$payload" \
      -o "$tmp_body" \
      -w "%{http_code}" \
      "https://discord.com/api/v10/channels/${CHANNEL_ID}/messages"
  )"
  if [[ "$http_code" != 2* ]]; then
    echo "Discord API error: HTTP $http_code" >&2
    cat "$tmp_body" >&2
    rm -f "$tmp_body"
    exit 1
  fi
  rm -f "$tmp_body"
  exit 0
fi

if [[ -z "${DISCORD_WEBHOOK_URL:-}" ]]; then
  echo "DISCORD_TOKEN or DISCORD_WEBHOOK_URL must be set in $ENV_FILE" >&2
  exit 1
fi

tmp_body="$(mktemp)"
http_code="$(
  curl -sS -H "Content-Type: application/json" \
    -d "$payload" \
    -o "$tmp_body" \
    -w "%{http_code}" \
    "$DISCORD_WEBHOOK_URL"
)"
if [[ "$http_code" != 2* ]]; then
  echo "Discord webhook error: HTTP $http_code" >&2
  cat "$tmp_body" >&2
  rm -f "$tmp_body"
  exit 1
fi
rm -f "$tmp_body"
