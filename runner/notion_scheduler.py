#!/usr/bin/env python3
import os
import sys
import json
import datetime
from typing import Dict, Any, List, Tuple

# Import Notion client
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared", "python", "lib"))

STATE_DIR = os.path.join(REPO_ROOT, "runner", "state")
STATE_FILE = os.path.join(STATE_DIR, "notion_scheduler.json")
NOTIFY_SCRIPT = os.path.join(REPO_ROOT, "integrations", "discord", "notify_discord.sh")

from notion_client import load_notion_from_env  # noqa: E402


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


def now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def iso_z(dt: datetime.datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log(message: str) -> None:
    print(f"[{iso_z(now_utc())}] {message}")

def send_error_to_discord(message: str) -> None:
    channel_id = os.getenv("DISCORD_LOG_CHANNEL_ID", "").strip()
    if not channel_id:
        return
    if not os.path.exists(NOTIFY_SCRIPT):
        return
    env = os.environ.copy()
    env["MSG_ARG"] = message
    subprocess.run([NOTIFY_SCRIPT, channel_id, message], check=False, env=env)


def load_state() -> Dict[str, Any]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_state(state: Dict[str, Any]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def update_state(patch: Dict[str, Any]) -> None:
    state = load_state()
    state.update(patch)
    state["updated_at"] = iso_z(now_utc())
    save_state(state)


def daily_window_utc() -> Tuple[str, str]:
    n = now_utc().date()
    start = datetime.datetime(n.year, n.month, n.day, tzinfo=datetime.UTC)
    end = start + datetime.timedelta(days=1)
    return iso_z(start), iso_z(end)


def twice_week_window_utc() -> Tuple[str, str]:
    today = now_utc().date()
    # Monday=0..Sunday=6
    dow = today.weekday()
    if dow <= 2:
        # Window 1: Mon-Thu 00:00
        start = today - datetime.timedelta(days=dow)
        end = start + datetime.timedelta(days=3)
    else:
        # Window 2: Thu-Mon 00:00
        start = today - datetime.timedelta(days=(dow - 3))
        end = start + datetime.timedelta(days=4)
    start_dt = datetime.datetime(start.year, start.month, start.day, tzinfo=datetime.UTC)
    end_dt = datetime.datetime(end.year, end.month, end.day, tzinfo=datetime.UTC)
    return iso_z(start_dt), iso_z(end_dt)


def projects_list() -> List[str]:
    raw = os.getenv("NOTION_PROJECTS", "secureapix")
    return [p.strip() for p in raw.split(",") if p.strip()]


def load_schedule(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        raise RuntimeError(f"Schedule file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items")
    if not isinstance(items, list):
        raise RuntimeError("Schedule file invalid: expected 'items' list")
    return items


def should_create_task(notion, task_type: str, project: str, window: Tuple[str, str]) -> bool:
    start, end = window
    filt = {
        "and": [
            {"property": "Type", "select": {"equals": task_type}},
            {"property": "Project", "select": {"equals": project}},
            {"property": "RequestedBy", "select": {"equals": "system"}},
            {"timestamp": "created_time", "created_time": {"on_or_after": start}},
            {"timestamp": "created_time", "created_time": {"before": end}},
        ]
    }
    results = notion.query_database(filter_obj=filt, limit=1)
    return len(results) == 0


def create_task(notion, task_type: str, project: str) -> None:
    name = f"{task_type} {project}"
    notion.create_task(
        name=name,
        task_type=task_type,
        project=project,
        status="queued",
        requested_by="system",
    )


def main() -> None:
    load_env_file(os.path.join(REPO_ROOT, "integrations", "notion", ".env"))
    load_env_file(os.path.join(REPO_ROOT, "integrations", "discord", ".env"))
    notion = load_notion_from_env(prefix="NOTION")
    schedule_path = os.getenv("NOTION_SCHEDULE_FILE", os.path.join(REPO_ROOT, "runner", "notion_schedule.json"))
    rules = load_schedule(schedule_path)

    created = 0
    skipped = 0
    for project in projects_list():
        for rule in rules:
            task_type = rule.get("type", "").strip()
            frequency = rule.get("frequency", "").strip()
            if not task_type or not frequency:
                continue
            if frequency == "daily":
                window = daily_window_utc()
            elif frequency == "twice_per_week":
                window = twice_week_window_utc()
            else:
                continue
            if should_create_task(notion, task_type, project, window):
                create_task(notion, task_type, project)
                log(f"Created task: type={task_type} project={project} freq={frequency}")
                created += 1
            else:
                log(f"Skip (already exists): type={task_type} project={project} freq={frequency}")
                skipped += 1
    update_state({"last_created": created, "last_skipped": skipped})


def safe_main() -> None:
    update_state({"last_check_at": iso_z(now_utc()), "last_status": "running"})
    try:
        main()
        update_state({
            "last_finished_at": iso_z(now_utc()),
            "last_success_at": iso_z(now_utc()),
            "last_status": "ok",
        })
    except Exception as exc:
        log(f"Fatal error: {exc}")
        send_error_to_discord(f"[notion_scheduler] Fatal error: {exc}")
        update_state({
            "last_finished_at": iso_z(now_utc()),
            "last_error_at": iso_z(now_utc()),
            "last_error": str(exc)[:1500],
            "last_status": "failed",
        })
        raise


if __name__ == "__main__":
    safe_main()
