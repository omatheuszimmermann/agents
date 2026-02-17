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


def item_title(item: str) -> str:
    if " -> " in item:
        return item.split(" -> ", 1)[0].strip()
    return item.strip()


def item_url(item: str) -> str:
    if " -> " in item:
        return item.split(" -> ", 1)[1].strip()
    return ""


def first_url(items: List[str]) -> str:
    for item in items:
        url = item_url(item)
        if url:
            return url
    return ""


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


def query_created_last_week(notion: NotionClient, tz: datetime.tzinfo) -> List[Dict[str, Any]]:
    now = now_tz(tz)
    start_date = (now.date() - datetime.timedelta(days=7))
    start_dt = datetime.datetime.combine(start_date, datetime.time.min, tzinfo=tz)
    filt = {
        "timestamp": "created_time",
        "created_time": {"on_or_after": iso_dt(start_dt)},
    }
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
    today_dt = today_date(tz)
    today = today_dt.strftime("%d/%m/%Y")
    lines: List[str] = []
    lines.append(f"🧠 DAILY CONTROL — {today}")
    lines.append("")

    critical_lines: List[str] = []
    for item in limit_lines(posts_overdue, 10):
        title = item_title(item)
        url = item_url(item)
        line = f"• {title} → [abrir]" if not url else f"• {title} → [abrir]({url})"
        critical_lines.append(line)
    for item in limit_lines(agenda_overdue, 10):
        title = item_title(item)
        url = item_url(item)
        line = f"• {title} → [abrir]" if not url else f"• {title} → [abrir]({url})"
        critical_lines.append(line)
    for item in limit_lines(lang_pending, 10):
        title = item_title(item)
        url = item_url(item)
        line = f"• {title} → [abrir]" if not url else f"• {title} → [abrir]({url})"
        critical_lines.append(line)

    lines.append(f"🚨 CRÍTICO ({len(critical_lines)})")
    if critical_lines:
        lines.extend(critical_lines)
    lines.append("")

    posts_pending_url = first_url(posts_pending)
    agenda_today_url = first_url(agenda_today)
    emails_url = first_url(emails)

    posts_pending_link = "[ver]" if not posts_pending_url else f"[ver]({posts_pending_url})"
    agenda_today_link = "[ver]" if not agenda_today_url else f"[ver]({agenda_today_url})"
    emails_link = "[ver]" if not emails_url else f"[ver]({emails_url})"

    lines.append("📌 HOJE")
    lines.append(f"• Posts pendentes: {len(posts_pending)} → {posts_pending_link}")
    lines.append(f"• Agenda: {len(agenda_today)} → {agenda_today_link}")
    lines.append(f"• Emails: {len(emails)} → {emails_link}")
    lines.append("")

    lang_pending_url = first_url(lang_pending)
    lang_to_correct_url = first_url(lang_to_correct)
    lang_corrected_url = first_url(lang_corrected)

    lang_pending_link = "[ver]" if not lang_pending_url else f"[ver]({lang_pending_url})"
    lang_to_correct_link = "[ver]" if not lang_to_correct_url else f"[ver]({lang_to_correct_url})"
    lang_corrected_link = "[ver]" if not lang_corrected_url else f"[ver]({lang_corrected_url})"

    lines.append("🌍 LANGUAGES")
    lines.append(f"• Pending: {len(lang_pending)} → {lang_pending_link}")
    lines.append(f"• To Correct: {len(lang_to_correct)} → {lang_to_correct_link}")
    lines.append(f"• Corrected: {len(lang_corrected)} → {lang_corrected_link}")
    lines.append("")

    posts_ready_total = len(posts_today) + len(posts_overdue)
    posts_ready_url = first_url(posts_today) or first_url(posts_overdue)
    posts_ready_link = "[ver]" if not posts_ready_url else f"[ver]({posts_ready_url})"

    atrasados_total = len(posts_overdue) + len(agenda_overdue)
    atrasados_url = first_url(posts_overdue) or first_url(agenda_overdue)
    atrasados_link = "[ver]" if not atrasados_url else f"[ver]({atrasados_url})"

    lines.append("📊 GERAL")
    lines.append(f"• Posts Ready: {posts_ready_total} → {posts_ready_link}")
    lines.append(f"• Atrasados: {atrasados_total} → {atrasados_link}")

    return "\n".join(lines).strip()


def build_weekly_message(
    tz: datetime.tzinfo,
    emails_done: List[Dict[str, Any]],
    posts_done: List[Dict[str, Any]],
    language_done: List[Dict[str, Any]],
    agenda_done: List[Dict[str, Any]],
    critical_active: int,
    posts_pending_count: int,
    new_tasks_created: int,
    tasks_accumulated: int,
) -> str:
    now = now_tz(tz)
    start_date = (now.date() - datetime.timedelta(days=7))

    def fmt_day(d: datetime.date) -> str:
        return d.strftime("%d/%m")

    lines: List[str] = []
    lines.append(f"📊 WEEKLY SNAPSHOT — {fmt_day(start_date)} a {fmt_day(now.date())}")
    lines.append("")

    posts_done_count = len(posts_done)
    language_done_count = len(language_done)
    total_done = len(emails_done) + len(posts_done) + len(language_done) + len(agenda_done)

    lines.append("Entregas:")
    lines.append(f"• Posts: {posts_done_count}")
    lines.append(f"• Languages: {language_done_count}")
    lines.append(f"• Total concluídas: {total_done}")
    lines.append("")

    lines.append("Pendências:")
    lines.append(f"• Críticos ativos: {critical_active}")
    lines.append(f"• Posts pendentes: {posts_pending_count}")
    lines.append("")

    acc_prefix = "+" if tasks_accumulated > 0 else ""
    lines.append("Fluxo:")
    lines.append(f"• Novas tasks criadas: {new_tasks_created}")
    lines.append(f"• Tasks acumuladas: {acc_prefix}{tasks_accumulated}")
    lines.append("")

    if critical_active >= 5 or tasks_accumulated >= 5:
        indicator = "🔴 Atenção: críticos altos ou acúmulo forte"
    elif critical_active >= 1 or tasks_accumulated > 0:
        indicator = "🟡 Estável, mas com acúmulo leve"
    else:
        indicator = "🟢 Saudável"
    lines.append(f"Indicador: {indicator}")

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

        # Current pending/critical snapshot for weekly
        emails = collect_emails(emails_notion)
        posts_pending, posts_today, posts_overdue = collect_posts(posts_notion, tz)
        lang_pending, lang_to_correct, lang_corrected = collect_language(language_notion)
        agenda_today, agenda_overdue = collect_agenda(agenda_notion, tz)

        critical_active = len(posts_overdue) + len(agenda_overdue) + len(lang_pending)
        posts_pending_count = len(posts_pending)

        # Created in last 7 days across DBs
        emails_created = query_created_last_week(emails_notion, tz)
        posts_created = query_created_last_week(posts_notion, tz)
        language_created = query_created_last_week(language_notion, tz)
        agenda_created = query_created_last_week(agenda_notion, tz)
        new_tasks_created = len(emails_created) + len(posts_created) + len(language_created) + len(agenda_created)

        done_total = len(emails_done) + len(posts_done) + len(language_done) + len(agenda_done)
        tasks_accumulated = new_tasks_created - done_total

        message = build_weekly_message(
            tz,
            emails_done,
            posts_done,
            language_done,
            agenda_done,
            critical_active,
            posts_pending_count,
            new_tasks_created,
            tasks_accumulated,
        )
        channel_id = os.getenv("DISCORD_WEEKLY_CHANNEL_ID", "").strip() or os.getenv("DISCORD_LOG_CHANNEL_ID", "").strip()
        send_discord(channel_id, message)
        print(f"NOTION_RESULT: weekly summary sent (emails={len(emails_done)} posts={len(posts_done)} agenda={len(agenda_done)})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
