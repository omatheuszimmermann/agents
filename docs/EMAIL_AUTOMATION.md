# Email Automation (Notion + Agents)

## Overview

This repo processes emails in two steps:
1. `email_check` classifies new emails and stores results in a daily JSON output.
2. `email_tasks_create` creates one Notion task per email in the Email Tasks database and notifies Discord.

All agent tasks live in the **main Notion DB** (configured by `NOTION_DB_ID`).
Email tasks live in the **Email Tasks DB** (configured by `NOTION_DB_EMAILS_ID`).

## Task Types (Main Notion DB)

- `email_check`: fetch + classify emails for a project.
- `email_tasks_create`: reads classified output and creates tasks in Email Tasks DB.
- `posts_create`: social posts agent.

Each task is created with an emoji icon by type:
- `email_check` → 📧
- `email_tasks_create` → 🧾
- `posts_create` → 📝
- default → ⚙️

## Email Tasks DB (Required Properties)

These property names are fixed and must match:
- `Subject` (title)
- `Status` (status: `pending`, `ready`, `done`)
- `Project` (select)
- `Classification` (select: `lead`, `support`, `billing`, `cancellation`, `features`, `spam`, `others`)
- `Message ID` (text)
- `Sender` (email)
- `Received At` (date)
- `Parent Task` (relation to the main Notion DB)
- `Ticket ID` (unique ID)

## Main Notion DB (Required Properties)

These property names are fixed and must match:
- `Name` (title)
- `Status` (select)
- `Type` (select)
- `Project` (select)
- `RequestedBy` (select)
- `Payload` (rich text)
- `Parent Task` (relation to the same DB)
- `ID` (unique ID)

## Output Files

- Classified results are stored daily per project:
  - `agents/email-triage/outputs/<project>_classified_YYYY-MM-DD.json`
- Old outputs are deleted after 30 days by default.

## Discord Notifications

- Discord notifications are sent only when email tasks are created (`email_tasks_create`).
- Classification does **not** notify Discord.

## Execution Flow

1. Scheduler creates `email_check` tasks daily per project.
2. Worker runs `email_check` tasks and classifies emails.
3. Classification enqueues `email_tasks_create` tasks with the output JSON path in `Payload`.
4. Worker runs `email_tasks_create` and creates tasks in Email Tasks DB.

## Manual Trigger (Discord Bot)

Use:
`@Silva email last <project>`

This creates an `email_check` task in the main Notion DB.
