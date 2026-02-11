# Email Agent CLI

## List emails (fetch_emails.py)

Usage:
```bash
python3 agents/email-triage/scripts/fetch_emails.py <project> [limit] [--status all|read|unread] [--since YYYY-MM-DD] [--before YYYY-MM-DD]
```

Parameters:
- `project`: Name of the project folder inside `agents/email-triage/projects/`.
- `limit`: Maximum number of emails to fetch (default: 10).
- `--status`: Filter by status. Options: `all`, `read`, `unread`.
- `--since`: Filter emails since a date (inclusive), format `YYYY-MM-DD`.
- `--before`: Filter emails before a date (exclusive), format `YYYY-MM-DD`.

Examples:
```bash
python3 agents/email-triage/scripts/fetch_emails.py secureapix
python3 agents/email-triage/scripts/fetch_emails.py secureapix 20 --status unread
python3 agents/email-triage/scripts/fetch_emails.py secureapix --since 2026-02-01 --before 2026-02-10
```

## Agent (agent.py)

Usage:
```bash
python3 agents/email-triage/scripts/agent.py <project> [limit] [--status all|read|unread] [--since YYYY-MM-DD] [--before YYYY-MM-DD]
```

Parameters:
- Same as `fetch_emails.py`.

Outputs:
- JSON file in `agents/email-triage/outputs/` with classified results.
- Sends a Discord message per classified email using the global notifier in `integrations/discord/notify_discord.sh`.
- Requires `CHANNEL_ID` in `agents/email-triage/.env` and `DISCORD_TOKEN` (or `DISCORD_WEBHOOK_URL`) in `integrations/discord/.env`.

Examples:
```bash
python3 agents/email-triage/scripts/agent.py secureapix
python3 agents/email-triage/scripts/agent.py secureapix 50 --status read --since 2026-01-01
```
