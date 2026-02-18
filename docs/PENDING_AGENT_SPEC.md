# Pending Agent Spec (Draft)

This document captures the pending/critical criteria for each Notion database, per discussion. It is meant for review before implementation.

## Emails DB
- **Pending**: items with status `Pending` are pending (need to create a response before sending).

## Posts DB
- **Pending**: items with status `Pending` are pending (need to generate image from prompt and schedule posting, then move to `Ready`).
- **Ready**: items with status `Ready` become pending if:
  - `Scheduled At` is **today** (needs to be posted today).
  - `Scheduled At` is **overdue** (past date) and should be flagged as **critical**.

## Language Study DB
- **Pending**: items with status `Pending` are **critical** (exercise not done yet).
- **To Correct**: items with status `To Correct` are pending but **less critical** (agent needs to act).
- **Corrected**: items with status `Corrected` are **low priority** (waiting for your action to mark done).

## Agenda DB
- **Pending today**: items pending with date = today.
- **Overdue**: items pending with date < today should be flagged as **critical**.

## Weekly Summary
- Weekly recap should list completed items by DB (status `Done`), for the last 7 days.
- Include counts and top items per DB.

## Notification Summary (Desired)
- Provide a summary of pending items “as if charging me to resolve them.”
- Include counts per DB and highlight critical/overdue items.

## Open Questions
- Exact status field names and date field names in each DB (confirm before coding).
- “Today” timezone reference (default: Europe/Rome).
- Where to send Discord notifications (channel/DM, bot token already configured?).
