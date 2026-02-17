#!/usr/bin/env python3
import os
import sys
import json
import datetime
import subprocess
from typing import Any, Dict, List, Optional, Tuple

# Import Notion client
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared", "python", "lib"))

from notion_client import NotionClient  # noqa: E402

NOTIFY_SCRIPT = os.path.join(REPO_ROOT, "integrations", "discord", "notify_discord.sh")
DEFAULT_TZ = "Europe/Rome"


def load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            val = v.strip().strip('"').strip("'")
            os.environ.setdefault(k.strip(), val)


def get_tz() -> datetime.tzinfo:
    tz_name = os.getenv("PENDING_ASSISTANT_TZ", DEFAULT_TZ).strip() or DEFAULT_TZ
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        return datetime.timezone.utc


def now_tz(tz: datetime.tzinfo) -> datetime.datetime:
    return datetime.datetime.now(tz)


def iso_dt(dt: datetime.datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def today_date(tz: datetime.tzinfo) -> datetime.date:
    return now_tz(tz).date()


def parse_date(value: str, tz: datetime.tzinfo) -> Optional[datetime.date]:
    if not value:
        return None
    raw = value.strip()
    try:
        if "T" not in raw and len(raw) >= 10:
            return datetime.date.fromisoformat(raw[:10])
        if raw.endswith("Z"):
            raw = raw.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(tz).date()
    except Exception:
        return None


def parse_dt(value: str, tz: datetime.tzinfo) -> Optional[datetime.datetime]:
    if not value:
        return None
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    except Exception:
        return None


def get_prop_date(page: Dict[str, Any], key: str) -> Optional[str]:
    prop = page.get("properties", {}).get(key, {})
    date_obj = prop.get("date") or {}
    return date_obj.get("start")


def get_prop_title(page: Dict[str, Any], key: str) -> str:
    prop = page.get("properties", {}).get(key, {})
    titles = prop.get("title") or []
    if not titles:
        return ""
    return "".join(t.get("plain_text", "") for t in titles)


def get_best_title(page: Dict[str, Any], keys: List[str]) -> str:
    for key in keys:
        title = get_prop_title(page, key).strip()
        if title:
            return title
    return "(sem titulo)"


def status_filter(prop: str, values: List[str], prop_type: str) -> Dict[str, Any]:
    vals = [v for v in values if v]
    if not vals:
        return {}
    if len(vals) == 1:
        return {"property": prop, prop_type: {"equals": vals[0]}}
    return {"or": [{"property": prop, prop_type: {"equals": v}} for v in vals]}


def and_filter(filters: List[Dict[str, Any]]) -> Dict[str, Any]:
    clean = [f for f in filters if f]
    if not clean:
        return {}
    if len(clean) == 1:
        return clean[0]
    return {"and": clean}


def query_all(notion: NotionClient, filt: Dict[str, Any], page_size: int = 100, max_pages: int = 10) -> List[Dict[str, Any]]:
    return notion.query_database_all(filter_obj=filt, page_size=page_size, max_pages=max_pages)


def send_discord(channel_id: str, message: str) -> None:
    if not channel_id:
        return
    if not os.path.exists(NOTIFY_SCRIPT):
        return
    if len(message) > 1900:
        message = message[:1900].rstrip() + "\n..."
    env = os.environ.copy()
    env["MSG_ARG"] = message
    subprocess.run([NOTIFY_SCRIPT, channel_id, message], check=False, env=env)


def limit_lines(items: List[str], limit: int) -> List[str]:
    if limit <= 0:
        return []
    return items[:limit]


def format_item(title: str, date_str: Optional[str] = None, url: Optional[str] = None) -> str:
    parts = [title]
    if date_str:
        parts.append(date_str)
    line = " | ".join(parts)
    if url:
        line = f"{line} -> {url}"
    return line


def collect_emails(notion: NotionClient) -> List[str]:
    filt = status_filter("Status", ["Pending", "pending"], "status")
    pages = query_all(notion, filt)
    items: List[str] = []
    for page in pages:
        title = get_best_title(page, ["Subject", "Title", "Name"])
        url = page.get("url")
        items.append(format_item(title, None, url))
    return items


def collect_posts(notion: NotionClient, tz: datetime.tzinfo) -> Tuple[List[str], List[str], List[str]]:
    pending_filt = status_filter("Status", ["Pending", "pending"], "status")
    pending_pages = query_all(notion, pending_filt)
    pending_items: List[str] = []
    for page in pending_pages:
        title = get_best_title(page, ["Title", "Name", "Subject"])
        url = page.get("url")
        pending_items.append(format_item(title, None, url))

    ready_filt = and_filter([
        status_filter("Status", ["Ready", "ready"], "status"),
        {"property": "Scheduled At", "date": {"is_not_empty": True}},
    ])
    ready_pages = query_all(notion, ready_filt)
    today = today_date(tz)
    ready_today: List[str] = []
    ready_overdue: List[str] = []

    for page in ready_pages:
        sched_raw = get_prop_date(page, "Scheduled At")
        sched_date = parse_date(sched_raw or "", tz)
        if not sched_date:
            continue
        title = get_best_title(page, ["Title", "Name", "Subject"])
        url = page.get("url")
        date_txt = sched_date.isoformat()
        if sched_date < today:
            ready_overdue.append(format_item(title, date_txt, url))
        elif sched_date == today:
            ready_today.append(format_item(title, date_txt, url))

    return pending_items, ready_today, ready_overdue


def collect_language(notion: NotionClient) -> Tuple[List[str], List[str], List[str]]:
    pending_filt = status_filter("Status", ["Pending", "pending"], "status")
    to_correct_filt = status_filter("Status", ["To Correct"], "status")
    corrected_filt = status_filter("Status", ["Corrected"], "status")

    pending_pages = query_all(notion, pending_filt)
    to_correct_pages = query_all(notion, to_correct_filt)
    corrected_pages = query_all(notion, corrected_filt)

    pending_items = []
    to_correct_items = []
    corrected_items = []

    for page in pending_pages:
        title = get_best_title(page, ["Title", "Name", "Subject"])
        url = page.get("url")
        pending_items.append(format_item(title, None, url))
    for page in to_correct_pages:
        title = get_best_title(page, ["Title", "Name", "Subject"])
        url = page.get("url")
        to_correct_items.append(format_item(title, None, url))
    for page in corrected_pages:
        title = get_best_title(page, ["Title", "Name", "Subject"])
        url = page.get("url")
        corrected_items.append(format_item(title, None, url))

    return pending_items, to_correct_items, corrected_items


def collect_agenda(notion: NotionClient, tz: datetime.tzinfo) -> Tuple[List[str], List[str]]:
    today = today_date(tz).isoformat()
    filt = and_filter([
        status_filter("Status", ["Pending", "pending"], "select"),
        {"property": "Due", "date": {"on_or_before": today}},
    ])
    pages = query_all(notion, filt)
    due_today: List[str] = []
    overdue: List[str] = []
    today_date_value = today_date(tz)

    for page in pages:
        title = get_best_title(page, ["Name", "Title", "Subject"])
        url = page.get("url")
        due_raw = get_prop_date(page, "Due")
        due_date = parse_date(due_raw or "", tz)
        if not due_date:
            continue
        date_txt = due_date.isoformat()
        if due_date < today_date_value:
            overdue.append(format_item(title, date_txt, url))
        else:
            due_today.append(format_item(title, date_txt, url))

    return due_today, overdue


def query_done_last_week(notion: NotionClient, status_prop_type: str, tz: datetime.tzinfo) -> List[Dict[str, Any]]:
    now = now_tz(tz)
    start_date = (now.date() - datetime.timedelta(days=7))
    start_dt = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=tz)
    filt = and_filter([
        status_filter("Status", ["Done", "done"], status_prop_type),
        {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": iso_dt(start_dt)}},
    ])
    pages = query_all(notion, filt)
    return pages


def sort_by_last_edited(pages: List[Dict[str, Any]], tz: datetime.tzinfo) -> List[Dict[str, Any]]:
    def key_fn(p: Dict[str, Any]) -> float:
        dt = parse_dt(p.get("last_edited_time", ""), tz)
        if not dt:
            return 0.0
        return dt.timestamp()
    return sorted(pages, key=key_fn, reverse=True)


def build_daily_message(tz: datetime.tzinfo, emails: List[str], posts_pending: List[str], posts_today: List[str], posts_overdue: List[str],
                        lang_pending: List[str], lang_to_correct: List[str], lang_corrected: List[str], agenda_today: List[str], agenda_overdue: List[str]) -> str:
    today = today_date(tz).isoformat()
    lines: List[str] = []
    lines.append(f"🧭 Assistente Pessoal — Pendências ({today})")

    critical_items = []
    if posts_overdue:
        critical_items.extend([f"[Posts atrasados] {item}" for item in posts_overdue])
    if agenda_overdue:
        critical_items.extend([f"[Agenda vencida] {item}" for item in agenda_overdue])
    if lang_pending:
        critical_items.extend([f"[Language Pending] {item}" for item in lang_pending])

    if critical_items:
        lines.append("Críticos:")
        lines.extend([f"- {item}" for item in limit_lines(critical_items, 10)])

    lines.append(f"Emails pendentes: {len(emails)}")
    if emails:
        lines.extend([f"- {item}" for item in limit_lines(emails, 10)])

    lines.append(f"Posts pendentes: {len(posts_pending)}")
    if posts_pending:
        lines.extend([f"- {item}" for item in limit_lines(posts_pending, 10)])

    lines.append(f"Posts Ready hoje: {len(posts_today)}")
    if posts_today:
        lines.extend([f"- {item}" for item in limit_lines(posts_today, 10)])

    lines.append(f"Posts Ready atrasados: {len(posts_overdue)}")

    lines.append(f"Language Pending (critico): {len(lang_pending)}")
    if lang_pending:
        lines.extend([f"- {item}" for item in limit_lines(lang_pending, 10)])

    lines.append(f"Language To Correct: {len(lang_to_correct)}")
    if lang_to_correct:
        lines.extend([f"- {item}" for item in limit_lines(lang_to_correct, 10)])

    lines.append(f"Language Corrected (baixo): {len(lang_corrected)}")

    lines.append(f"Agenda hoje: {len(agenda_today)}")
    if agenda_today:
        lines.extend([f"- {item}" for item in limit_lines(agenda_today, 10)])

    lines.append(f"Agenda atrasados: {len(agenda_overdue)}")

    return "\n".join(lines).strip()


def build_weekly_message(tz: datetime.tzinfo, emails_done: List[Dict[str, Any]], posts_done: List[Dict[str, Any]], language_done: List[Dict[str, Any]], agenda_done: List[Dict[str, Any]]) -> str:
    now = now_tz(tz)
    start_date = (now.date() - datetime.timedelta(days=7))
    lines: List[str] = []
    lines.append(f"📊 Resumo semanal — {start_date.isoformat()} a {now.date().isoformat()}")

    def summarize(name: str, pages: List[Dict[str, Any]], title_keys: List[str]) -> None:
        lines.append(f"{name} concluídos: {len(pages)}")
        if not pages:
            return
        for page in limit_lines(pages, 10):
            title = get_best_title(page, title_keys)
            url = page.get("url")
            lines.append(f"- {format_item(title, None, url)}")

    emails_sorted = sort_by_last_edited(emails_done, tz)
    posts_sorted = sort_by_last_edited(posts_done, tz)
    language_sorted = sort_by_last_edited(language_done, tz)
    agenda_sorted = sort_by_last_edited(agenda_done, tz)

    summarize("Emails", emails_sorted, ["Subject", "Title", "Name"])
    summarize("Posts", posts_sorted, ["Title", "Name", "Subject"])
    summarize("Language Study", language_sorted, ["Title", "Name", "Subject"])
    summarize("Agenda", agenda_sorted, ["Name", "Title", "Subject"])

    return "\n".join(lines).strip()


def parse_mode(payload: str) -> str:
    if not payload:
        return "daily"
    raw = payload.strip()
    if not raw:
        return "daily"
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                mode = str(data.get("mode", "")).strip().lower()
                if mode:
                    return mode
        except Exception:
            pass
    return raw.lower()


def main() -> int:
    load_env_file(os.path.join(REPO_ROOT, "integrations", "notion", ".env"))
    load_env_file(os.path.join(REPO_ROOT, "integrations", "discord", ".env"))

    payload = ""
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv):
            payload = sys.argv[idx + 1]
    elif len(sys.argv) > 1:
        # allow simple positional mode
        payload = sys.argv[1]
    mode = parse_mode(payload)

    tz = get_tz()

    api_key = os.getenv("NOTION_API_KEY", "").strip()
    db_emails = os.getenv("NOTION_DB_EMAILS_ID", "").strip()
    db_posts = os.getenv("NOTION_DB_POSTS_ID", "").strip()
    db_language = os.getenv("NOTION_DB_LANGUAGE_ID", "").strip()
    db_agenda = os.getenv("NOTION_DB_AGENDA_ID", "").strip()

    if not api_key:
        raise RuntimeError("Missing Notion config: NOTION_API_KEY")

    if mode in {"daily", "all"}:
        if not (db_emails and db_posts and db_language and db_agenda):
            raise RuntimeError("Missing Notion DB IDs for daily summary.")

        emails_notion = NotionClient(api_key=api_key, database_id=db_emails)
        posts_notion = NotionClient(api_key=api_key, database_id=db_posts)
        language_notion = NotionClient(api_key=api_key, database_id=db_language)
        agenda_notion = NotionClient(api_key=api_key, database_id=db_agenda)

        emails = collect_emails(emails_notion)
        posts_pending, posts_today, posts_overdue = collect_posts(posts_notion, tz)
        lang_pending, lang_to_correct, lang_corrected = collect_language(language_notion)
        agenda_today, agenda_overdue = collect_agenda(agenda_notion, tz)

        message = build_daily_message(
            tz,
            emails,
            posts_pending,
            posts_today,
            posts_overdue,
            lang_pending,
            lang_to_correct,
            lang_corrected,
            agenda_today,
            agenda_overdue,
        )

        channel_id = os.getenv("DISCORD_PENDING_CHANNEL_ID", "").strip() or os.getenv("DISCORD_LOG_CHANNEL_ID", "").strip()
        send_discord(channel_id, message)
        print(f"NOTION_RESULT: daily pending sent (emails={len(emails)} posts_pending={len(posts_pending)} agenda_today={len(agenda_today)})")

    if mode in {"weekly", "all"}:
        if not (db_emails and db_posts and db_language and db_agenda):
            raise RuntimeError("Missing Notion DB IDs for weekly summary.")

        emails_notion = NotionClient(api_key=api_key, database_id=db_emails)
        posts_notion = NotionClient(api_key=api_key, database_id=db_posts)
        language_notion = NotionClient(api_key=api_key, database_id=db_language)
        agenda_notion = NotionClient(api_key=api_key, database_id=db_agenda)

        emails_done = query_done_last_week(emails_notion, "status", tz)
        posts_done = query_done_last_week(posts_notion, "status", tz)
        language_done = query_done_last_week(language_notion, "status", tz)
        agenda_done = query_done_last_week(agenda_notion, "select", tz)

        message = build_weekly_message(tz, emails_done, posts_done, language_done, agenda_done)
        channel_id = os.getenv("DISCORD_WEEKLY_CHANNEL_ID", "").strip() or os.getenv("DISCORD_LOG_CHANNEL_ID", "").strip()
        send_discord(channel_id, message)
        print(f"NOTION_RESULT: weekly summary sent (emails={len(emails_done)} posts={len(posts_done)} agenda={len(agenda_done)})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
