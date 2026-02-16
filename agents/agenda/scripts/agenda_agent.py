#!/usr/bin/env python3
import os
import sys
import datetime
import subprocess
from typing import Dict, Any, List, Optional, Tuple

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared", "python", "lib"))

NOTIFY_SCRIPT = os.path.join(REPO_ROOT, "integrations", "discord", "notify_discord.sh")

from notion_client import NotionClient  # noqa: E402


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


def today_date() -> datetime.date:
    return datetime.date.today()


def iso_date(d: datetime.date) -> str:
    return d.isoformat()


def parse_date(value: str) -> Optional[datetime.date]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(value)
        return dt.date()
    except Exception:
        try:
            return datetime.date.fromisoformat(value[:10])
        except Exception:
            return None


def add_months(d: datetime.date, months: int, day_override: Optional[int] = None) -> datetime.date:
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    day = day_override or d.day
    last_day = (datetime.date(year, month, 1) + datetime.timedelta(days=31)).replace(day=1) - datetime.timedelta(days=1)
    if day > last_day.day:
        day = last_day.day
    return datetime.date(year, month, day)


def next_due_date(due: datetime.date, recurrence: str, recurrence_day: Optional[int]) -> Optional[datetime.date]:
    if recurrence == "daily":
        return due + datetime.timedelta(days=1)
    if recurrence == "weekly":
        if recurrence_day is None:
            return due + datetime.timedelta(days=7)
        # recurrence_day: 0=Monday..6=Sunday
        target = int(recurrence_day)
        for i in range(1, 8):
            candidate = due + datetime.timedelta(days=i)
            if candidate.weekday() == target:
                return candidate
        return due + datetime.timedelta(days=7)
    if recurrence == "monthly":
        return add_months(due, 1, day_override=recurrence_day)
    if recurrence == "quarterly":
        return add_months(due, 3, day_override=recurrence_day)
    if recurrence == "yearly":
        return add_months(due, 12, day_override=recurrence_day)
    return None


def prop_select(value: str) -> Dict[str, Any]:
    return {"select": {"name": value}}


def prop_number(value: Optional[int]) -> Dict[str, Any]:
    if value is None:
        return {"number": None}
    return {"number": int(value)}


def prop_date(value: str) -> Dict[str, Any]:
    return {"date": {"start": value}}


def prop_title(value: str) -> Dict[str, Any]:
    return {"title": [{"text": {"content": value}}]}


def prop_relation(page_id: str) -> Dict[str, Any]:
    return {"relation": [{"id": page_id}]}


def get_prop_select(page: Dict[str, Any], key: str) -> str:
    prop = page.get("properties", {}).get(key, {})
    sel = prop.get("select") or {}
    return sel.get("name", "")


def get_prop_number(page: Dict[str, Any], key: str) -> Optional[int]:
    prop = page.get("properties", {}).get(key, {})
    num = prop.get("number")
    return int(num) if isinstance(num, (int, float)) else None


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


def send_discord(message: str) -> None:
    channel_id = os.getenv("DISCORD_AGENDA_CHANNEL_ID", "").strip() or os.getenv("DISCORD_LOG_CHANNEL_ID", "").strip()
    if not channel_id:
        return
    if not os.path.exists(NOTIFY_SCRIPT):
        return
    env = os.environ.copy()
    env["MSG_ARG"] = message
    subprocess.run([NOTIFY_SCRIPT, channel_id, message], check=False, env=env)


def notify_upcoming(notion: NotionClient) -> Tuple[int, List[str]]:
    today = today_date()
    today_str = iso_date(today)
    filt = {
        "and": [
            {"property": "Status", "select": {"equals": "Pending"}},
            {"property": "Due", "date": {"on_or_after": today_str}},
        ]
    }
    pages = notion.query_database_all(filter_obj=filt, page_size=100, max_pages=20)
    notified = 0
    lines: List[str] = []

    for page in pages:
        name = get_prop_title(page, "Name")
        due_raw = get_prop_date(page, "Due")
        due_date = parse_date(due_raw or "")
        if not due_date:
            continue
        notify_before = get_prop_number(page, "Notify Before Days")
        if notify_before is None:
            notify_before = 1
        days_until = (due_date - today).days
        if days_until != notify_before:
            continue

        last_notified_raw = get_prop_date(page, "Last Notified At")
        last_notified = parse_date(last_notified_raw or "")
        if last_notified == today:
            continue

        category = get_prop_select(page, "Category")
        priority = get_prop_select(page, "Priority")
        msg = f"Agenda: {name} | vence em {iso_date(due_date)} | {category or 'sem categoria'} | {priority or 'sem prioridade'}"
        send_discord(msg)
        notion.update_page(page.get("id", ""), {
            "Last Notified At": prop_date(today_str),
        })
        notified += 1
        lines.append(f"- {name} ({iso_date(due_date)})")

    return notified, lines


def has_pending_for_date(notion: NotionClient, name: str, due_date: datetime.date, parent_id: str) -> bool:
    start = iso_date(due_date)
    end = iso_date(due_date + datetime.timedelta(days=1))
    filt_and = [
        {"property": "Due", "date": {"on_or_after": start}},
        {"property": "Due", "date": {"before": end}},
    ]
    if parent_id:
        filt_and.append({"property": "Parent Task", "relation": {"contains": parent_id}})
    else:
        filt_and.append({"property": "Name", "title": {"equals": name}})
    filt = {"and": filt_and}
    res = notion.query_database(filter_obj=filt, limit=1)
    return len(res) > 0


def is_active_template_status(status: str) -> bool:
    return status in {"Pending", "Processing", "Done"}


def compute_next_due(base_due: datetime.date, recurrence: str, recurrence_day: Optional[int]) -> datetime.date:
    next_due = next_due_date(base_due, recurrence, recurrence_day) or base_due
    today = today_date()
    while next_due < today:
        next_due = next_due_date(next_due, recurrence, recurrence_day) or next_due
    return next_due


def create_recurring(notion: NotionClient) -> int:
    filt = {
        "and": [
            {"property": "Recurrence", "select": {"is_not_empty": True}},
        ]
    }
    pages = notion.query_database_all(filter_obj=filt, page_size=100, max_pages=20)
    created = 0

    for page in pages:
        status = get_prop_select(page, "Status")
        if not is_active_template_status(status):
            continue
        recurrence = get_prop_select(page, "Recurrence")
        if not recurrence or recurrence == "none":
            continue
        due_raw = get_prop_date(page, "Due")
        due_date = parse_date(due_raw or "")
        if not due_date:
            continue

        recurrence_day = get_prop_number(page, "Recurrence Day")
        next_due = compute_next_due(due_date, recurrence, recurrence_day)
        name = get_prop_title(page, "Name")
        if not name:
            continue

        page_id = page.get("id", "")
        if has_pending_for_date(notion, name, next_due, page_id):
            continue

        priority = get_prop_select(page, "Priority")
        category = get_prop_select(page, "Category")
        notify_before = get_prop_number(page, "Notify Before Days")

        props: Dict[str, Any] = {
            "Name": prop_title(name),
            "Status": prop_select("Pending"),
            "Due": prop_date(iso_date(next_due)),
        }
        if priority:
            props["Priority"] = prop_select(priority)
        if category:
            props["Category"] = prop_select(category)
        if notify_before is not None:
            props["Notify Before Days"] = prop_number(notify_before)

        if page_id:
            props["Parent Task"] = prop_relation(page_id)

        notion.create_page(properties=props)
        created += 1

    return created


def main() -> int:
    load_env_file(os.path.join(REPO_ROOT, "integrations", "notion", ".env"))
    load_env_file(os.path.join(REPO_ROOT, "integrations", "discord", ".env"))

    db_id = os.getenv("NOTION_DB_AGENDA_ID", "").strip()
    api_key = os.getenv("NOTION_API_KEY", "").strip()
    if not db_id or not api_key:
        raise RuntimeError("Missing Notion config: NOTION_API_KEY / NOTION_DB_AGENDA_ID")

    notion = NotionClient(api_key=api_key, database_id=db_id)
    notified, lines = notify_upcoming(notion)
    created = create_recurring(notion)

    summary = f"Agenda: notificadas={notified} | recorrencias_criadas={created}"
    if lines:
        summary = f"{summary}\n" + "\n".join(lines[:50])
    print(f"NOTION_RESULT: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
