# Email Agent CLI

## List emails (email.py)

Usage:
```bash
python3 email.py <project> [limit] [--status all|read|unread] [--since YYYY-MM-DD] [--before YYYY-MM-DD]
```

Parameters:
- `project`: Name of the project folder inside `email/projects/`.
- `limit`: Maximum number of emails to fetch (default: 10).
- `--status`: Filter by status. Options: `all`, `read`, `unread`.
- `--since`: Filter emails since a date (inclusive), format `YYYY-MM-DD`.
- `--before`: Filter emails before a date (exclusive), format `YYYY-MM-DD`.

Examples:
```bash
python3 email.py secureapix
python3 email.py secureapix 20 --status unread
python3 email.py secureapix --since 2026-02-01 --before 2026-02-10
```

## Agent (agent.py)

Usage:
```bash
python3 agent.py <project> [limit] [--status all|read|unread] [--since YYYY-MM-DD] [--before YYYY-MM-DD]
```

Parameters:
- Same as `email.py`.

Outputs:
- JSON file in `email/outputs/` with classified results.
- Sends a Discord message per classified email using `DISCORD_WEBHOOK_URL` from `email/.env`.

Examples:
```bash
python3 agent.py secureapix
python3 agent.py secureapix 50 --status read --since 2026-01-01
```
