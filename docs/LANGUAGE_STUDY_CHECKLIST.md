# Language Study Agent - First Version Checklist

## Notion Setup
- [ ] Create the "Work Only" tasks DB (or confirm existing one) with required properties from `docs/EMAIL_AUTOMATION.md`.
- [ ] Create a new "Language Study" DB for lessons.
- [ ] Add these properties to the Language Study DB:
- [ ] `ID` (Campo ID autoincrement padrao do Notion)
- [ ] `Title` (title)
- [ ] `Status` (status: `pending`, `ready`, `done`)
- [ ] `Student` (select)
- [ ] `Language` (select: `en`, `it`)
- [ ] `Lesson Type` (select: `article`, `video`, `grammar`, `exercises`, `article_with_video`)
- [ ] `Topic` (select or text)
- [ ] `Source URL` (url)
- [ ] `Content` (rich text)
- [ ] `Responses` (rich text)
- [ ] `Correction` (rich text)
- [ ] `Parent Task` (relation to Work Only DB)
- [ ] `Received At`

## Repo Configuration
- [ ] Add `NOTION_DB_LANGUAGE_ID` to `integrations/notion/.env`.
- [ ] Confirm `NOTION_DB_ID` points to the Work Only DB.
- [ ] Confirm `NOTION_API_KEY` has access to both DBs.
- [ ] (Optional) Set `NOTION_RESULT_PROPERTY` if you want a custom result field.

## Content Library Agent
- [ ] Create `agents/content-library/` with:
- [ ] `sources.json` (trusted sources by language/topic/type).
- [ ] `library.json` (content cache).
- [ ] `scripts/refresh_library.py` (pulls RSS/YouTube and normalizes items).
- [ ] Decide refresh rules: `min_items` and `max_age_days` per category.
- [ ] Add a task type `content_refresh` in the Work Only DB.
- [ ] Wire `content_refresh` into `runner/notion_worker.py`.

## Teacher Agent
- [ ] Create `agents/language-study/` with:
- [ ] `profiles.json` (students: name, languages, channel preferences).
- [ ] `schedule.json` (weekly plan).
- [ ] `scripts/lesson_send.py` (selects content + uses LLM + creates lesson page).
- [ ] `scripts/lesson_correct.py` (reads `Responses`, writes `Correction`).
- [ ] Add task types `lesson_send` and `lesson_correct` in the Work Only DB.
- [ ] Wire both into `runner/notion_worker.py`.

## Discord Notifications (Outbound Only)
- [ ] Ensure `integrations/discord/.env` has `DISCORD_LOG_CHANNEL_ID`.
- [ ] Decide where to send lesson notifications (log channel or a new one).

## Scheduler / Bot
- [ ] Update `runner/notion_schedule.json` with `content_refresh` and `lesson_send`.
- [ ] Decide if Discord bot should create on-demand `lesson_send` tasks.

## LLM Prompting
- [ ] Define prompt templates for:
- [ ] `article` lesson
- [ ] `video` lesson
- [ ] `grammar` lesson
- [ ] `exercises` generation
- [ ] `correction` with explanations
- [ ] Set `LLM_*` env vars for llama-3b-instant.

## First Run Validation
- [ ] Run `content_refresh` manually and confirm `library.json` updated.
- [ ] Run `lesson_send` manually and confirm a page is created in Language Study DB.
- [ ] Paste answers into `Responses` and run `lesson_correct` manually.
- [ ] Confirm `Correction` is written and Discord gets a notification.
