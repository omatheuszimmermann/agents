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
python3 agents/email-triage/scripts/agent.py <project> [limit] [--status all|read|unread] [--since YYYY-MM-DD] [--before YYYY-MM-DD] [--parent-task-id <notion_page_id>]
```

Parameters:
- Same as `fetch_emails.py`.

Outputs:
- JSON file in `agents/email-triage/outputs/` with classified results.
- Requires `CHANNEL_ID` in `agents/email-triage/.env` and `DISCORD_TOKEN` (or `DISCORD_WEBHOOK_URL`) in `integrations/discord/.env`.
- Classification labels: `lead`, `support`, `billing`, `cancellation`, `features`, `spam`, `others`.
- When new emails are classified, enqueues a Notion task of type `email_tasks_create` with the JSON output path in `Payload`.

Examples:
```bash
python3 agents/email-triage/scripts/agent.py secureapix
python3 agents/email-triage/scripts/agent.py secureapix 50 --status read --since 2026-01-01
```

## Create Email Tasks (create_tasks.py)

Usage:
```bash
python3 agents/email-triage/scripts/create_tasks.py <project> [--source <json_path>] [--parent-task-id <notion_page_id>]
```

Notes:
- If `--source` is omitted, it uses the latest classified JSON for the project.
- Creates tasks in the Notion Email Tasks database (`NOTION_DB_EMAILS_ID`).
- Sends a Discord message per created email task using the global notifier in `integrations/discord/notify_discord.sh`.
