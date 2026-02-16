#!/usr/bin/env python3
import os
import sys
import json
import datetime
import subprocess
import time
from typing import Dict, Any, List

# Import Notion client
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared", "python", "lib"))

STATE_DIR = os.path.join(REPO_ROOT, "runner", "state")
STATE_FILE = os.path.join(STATE_DIR, "notion_worker.json")
USAGE_FILE = os.path.join(STATE_DIR, "usage.json")
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


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def prop_select(name: str) -> Dict[str, Any]:
    return {"select": {"name": name}}


def prop_text(value: str) -> Dict[str, Any]:
    return {"rich_text": [{"text": {"content": value}}]}


def prop_date(value: str) -> Dict[str, Any]:
    return {"date": {"start": value}}


def prop_number(value: int) -> Dict[str, Any]:
    return {"number": value}


def get_prop_select(page: Dict[str, Any], key: str) -> str:
    prop = page.get("properties", {}).get(key, {})
    sel = prop.get("select") or {}
    return sel.get("name", "")


def get_prop_text(page: Dict[str, Any], key: str) -> str:
    prop = page.get("properties", {}).get(key, {})
    texts = prop.get("rich_text") or []
    if not texts:
        return ""
    return "".join(t.get("plain_text", "") for t in texts)


def log(message: str) -> None:
    print(f"[{now_iso()}] {message}")

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
    state["updated_at"] = now_iso()
    save_state(state)


def load_usage() -> Dict[str, Any]:
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_usage(usage: Dict[str, Any]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(usage, f, indent=2, ensure_ascii=False)


def usage_day_key() -> str:
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def bump_usage_agent(agent_id: str, ok: bool, duration_sec: float, items: int) -> None:
    usage = load_usage()
    agents = usage.setdefault("agents", {})
    agent = agents.setdefault(agent_id, {})
    by_day = agent.setdefault("by_day", {})
    day = usage_day_key()
    day_entry = by_day.setdefault(day, {})

    agent["runs_total"] = int(agent.get("runs_total", 0)) + 1
    agent["runs_ok"] = int(agent.get("runs_ok", 0)) + (1 if ok else 0)
    agent["runs_failed"] = int(agent.get("runs_failed", 0)) + (0 if ok else 1)
    agent["total_duration_sec"] = float(agent.get("total_duration_sec", 0.0)) + float(duration_sec or 0.0)
    agent["total_items"] = int(agent.get("total_items", 0)) + int(items or 0)

    day_entry["runs"] = int(day_entry.get("runs", 0)) + 1
    day_entry["failed"] = int(day_entry.get("failed", 0)) + (0 if ok else 1)
    day_entry["duration_sec"] = float(day_entry.get("duration_sec", 0.0)) + float(duration_sec or 0.0)
    day_entry["items"] = int(day_entry.get("items", 0)) + int(items or 0)

    usage["updated_at"] = now_iso()
    save_usage(usage)


def bump_usage_task(task_type: str, ok: bool, duration_sec: float) -> None:
    if not task_type:
        return
    usage = load_usage()
    task_types = usage.setdefault("task_types", {})
    task_entry = task_types.setdefault(task_type, {})
    by_day = task_entry.setdefault("by_day", {})
    day = usage_day_key()
    day_entry = by_day.setdefault(day, {})

    task_entry["runs_total"] = int(task_entry.get("runs_total", 0)) + 1
    task_entry["runs_ok"] = int(task_entry.get("runs_ok", 0)) + (1 if ok else 0)
    task_entry["runs_failed"] = int(task_entry.get("runs_failed", 0)) + (0 if ok else 1)
    task_entry["total_duration_sec"] = float(task_entry.get("total_duration_sec", 0.0)) + float(duration_sec or 0.0)
    task_entry["total_items"] = int(task_entry.get("total_items", 0)) + 1

    day_entry["runs"] = int(day_entry.get("runs", 0)) + 1
    day_entry["failed"] = int(day_entry.get("failed", 0)) + (0 if ok else 1)
    day_entry["duration_sec"] = float(day_entry.get("duration_sec", 0.0)) + float(duration_sec or 0.0)
    day_entry["items"] = int(day_entry.get("items", 0)) + 1

    usage["updated_at"] = now_iso()
    save_usage(usage)


def run_command(command: List[str], cwd: str) -> Dict[str, Any]:
    start = time.time()
    proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    duration = time.time() - start
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "duration_sec": duration,
    }


def extract_notion_result(output: str) -> str:
    if not output:
        return ""
    for line in output.splitlines():
        if line.startswith("NOTION_RESULT: "):
            return line[len("NOTION_RESULT: "):].strip()
    return ""


def chunk_text(text: str, max_len: int = 1800) -> List[str]:
    if not text:
        return []
    chunks = []
    current = []
    size = 0
    for line in text.splitlines():
        line = line.rstrip()
        add_len = len(line) + (1 if current else 0)
        if size + add_len > max_len and current:
            chunks.append("\n".join(current))
            current = [line]
            size = len(line)
        else:
            if current:
                current.append(line)
                size += add_len
            else:
                current = [line]
                size = len(line)
    if current:
        chunks.append("\n".join(current))
    return chunks


def task_to_command(task_type: str, project: str, payload: str, page_id: str) -> List[str]:
    if task_type == "posts_create":
        return [
            "python3",
            "agents/social-posts/scripts/generate_post.py",
            project,
            "--parent-task-id",
            page_id,
        ]
    if task_type == "email_check":
        return [
            "python3",
            "agents/email-triage/scripts/agent.py",
            project,
            "20",
            "--status",
            "unread",
            "--parent-task-id",
            page_id,
        ]
    if task_type == "email_tasks_create":
        cmd = ["python3", "agents/email-triage/scripts/create_tasks.py", project]
        if payload:
            cmd.extend(["--source", payload])
        if page_id:
            cmd.extend(["--parent-task-id", page_id])
        return cmd
    if task_type == "content_refresh":
        return [
            "python3",
            "agents/content-library/scripts/refresh_library.py",
        ]
    if task_type == "lesson_send":
        cmd = [
            "python3",
            "agents/language-study/scripts/lesson_send.py",
            project,
        ]
        if payload:
            try:
                data = json.loads(payload)
                if isinstance(data, dict):
                    student_id = str(data.get("student_id", "")).strip()
                    topic = str(data.get("topic", "")).strip()
                    lesson_type = str(data.get("lesson_type", "")).strip()
                    if student_id:
                        cmd.extend(["--student-id", student_id])
                    if topic:
                        cmd.extend(["--topic", topic])
                    if lesson_type:
                        cmd.extend(["--lesson-type", lesson_type])
            except Exception:
                pass
        if page_id:
            cmd.extend(["--parent-task-id", page_id])
        return cmd
    if task_type == "lesson_correct":
        cmd = [
            "python3",
            "agents/language-study/scripts/lesson_correct.py",
            project,
        ]
        if payload:
            try:
                data = json.loads(payload)
                if isinstance(data, dict):
                    student_id = str(data.get("student_id", "")).strip()
                    if student_id:
                        cmd.extend(["--student-id", student_id])
            except Exception:
                pass
        return cmd
    if task_type == "agenda_reminder":
        return [
            "python3",
            "agents/agenda/scripts/agenda_agent.py",
        ]
    raise RuntimeError(f"Unknown task type: {task_type}")


def main() -> Dict[str, Any]:
    load_env_file(os.path.join(REPO_ROOT, "integrations", "notion", ".env"))
    load_env_file(os.path.join(REPO_ROOT, "integrations", "discord", ".env"))

    notion = load_notion_from_env(prefix="NOTION")
    max_tasks = int(os.getenv("NOTION_MAX_TASKS", "1"))
    result_prop = os.getenv("NOTION_RESULT_PROPERTY", "Result")
    tasks = notion.query_tasks(status="queued", limit=max_tasks)
    update_state({"last_tasks_seen": len(tasks)})
    tasks_by_type: Dict[str, int] = {}
    for task in tasks:
        ttype = str(get_prop_select(task, "Type")).strip()
        if not ttype:
            continue
        tasks_by_type[ttype] = tasks_by_type.get(ttype, 0) + 1
    update_state({"last_tasks_seen_by_type": tasks_by_type})

    if not tasks:
        log("No queued tasks.")
        update_state({"last_result": "no_tasks"})
        return {"tasks_processed": 0, "tasks_failed": 0, "tasks_by_type": tasks_by_type}

    tasks_processed = 0
    tasks_failed = 0
    for page in tasks:
        page_id = page.get("id")
        task_type = get_prop_select(page, "Type")
        project = get_prop_select(page, "Project")
        payload = get_prop_text(page, "Payload")
        run_count_raw = page.get("properties", {}).get("RunCount", {}).get("number")
        run_count = int(run_count_raw or 0) + 1
        log(f"Running task: type={task_type} project={project} run_count={run_count}")

        notion.update_page(page_id, {
            "Status": prop_select("running"),
            "StartedAt": prop_date(now_iso()),
            "RunCount": prop_number(run_count),
            "LastError": prop_text(""),
        })

        attempted = False
        try:
            cmd = task_to_command(task_type, project, payload, page_id)
            result = run_command(cmd, cwd=REPO_ROOT)
            tasks_processed += 1
            attempted = True
            if result["returncode"] != 0:
                error_text = result["stderr"] or result["stdout"] or "Unknown error"
                log(f"Task failed: {error_text}")
                send_error_to_discord(
                    f"[notion_worker] Task failed: type={task_type} project={project}\n{error_text}"
                )
                notion.update_page(page_id, {
                    "Status": prop_select("failed"),
                    "FinishedAt": prop_date(now_iso()),
                    "LastError": prop_text(error_text[:1500]),
                })
                tasks_failed += 1
                bump_usage_task(task_type, ok=False, duration_sec=result.get("duration_sec", 0.0))
                continue

            notion_result = extract_notion_result(result["stdout"])
            if not notion_result:
                notion_result = result["stdout"][:1500] if result["stdout"] else "ok"

            notion.update_page(page_id, {
                "Status": prop_select("done"),
                "FinishedAt": prop_date(now_iso()),
                result_prop: prop_text(notion_result[:1500]),
            })
            # Append result to page body (native text area)
            chunks = chunk_text(notion_result, max_len=1800)
            if chunks:
                notion.append_paragraphs(page_id, chunks)
            log("Task done.")
            bump_usage_task(task_type, ok=True, duration_sec=result.get("duration_sec", 0.0))
        except Exception as exc:
            log(f"Task exception: {exc}")
            notion.update_page(page_id, {
                "Status": prop_select("failed"),
                "FinishedAt": prop_date(now_iso()),
                "LastError": prop_text(str(exc)[:1500]),
            })
            if not attempted:
                tasks_processed += 1
            tasks_failed += 1
            bump_usage_task(task_type, ok=False, duration_sec=0.0)

    update_state({"last_result": "processed"})
    return {"tasks_processed": tasks_processed, "tasks_failed": tasks_failed, "tasks_by_type": tasks_by_type}


def safe_main() -> None:
    run_started = time.time()
    update_state({"last_check_at": now_iso(), "last_status": "running"})
    try:
        stats = main()
        run_duration = time.time() - run_started
        update_state({
            "last_finished_at": now_iso(),
            "last_success_at": now_iso(),
            "last_status": "ok",
            "last_duration_sec": round(run_duration, 3),
            "last_items_processed": stats.get("tasks_processed", 0),
        })
        bump_usage_agent(
            "notion_worker",
            ok=True,
            duration_sec=run_duration,
            items=int(stats.get("tasks_processed", 0)),
        )
    except Exception as exc:
        run_duration = time.time() - run_started
        log(f"Fatal error: {exc}")
        send_error_to_discord(f"[notion_worker] Fatal error: {exc}")
        update_state({
            "last_finished_at": now_iso(),
            "last_error_at": now_iso(),
            "last_error": str(exc)[:1500],
            "last_status": "failed",
            "last_duration_sec": round(run_duration, 3),
        })
        bump_usage_agent(
            "notion_worker",
            ok=False,
            duration_sec=run_duration,
            items=0,
        )
        raise


if __name__ == "__main__":
    safe_main()
