#!/usr/bin/env python3
import os
import sys
import json
import datetime
import subprocess
from typing import Dict, Any, List

# Import Notion client
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared", "python", "lib"))

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
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


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


def run_command(command: List[str], cwd: str) -> Dict[str, Any]:
    proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def task_to_command(task_type: str, project: str, payload: str) -> List[str]:
    if task_type == "posts_create":
        return ["python3", "agents/social-posts/scripts/generate_post.py", project]
    if task_type == "email_check":
        return [
            "python3",
            "agents/email-triage/scripts/agent.py",
            project,
            "20",
            "--status",
            "unread",
        ]
    raise RuntimeError(f"Unknown task type: {task_type}")


def main() -> None:
    load_env_file(os.path.join(REPO_ROOT, "integrations", "notion", ".env"))

    notion = load_notion_from_env(prefix="NOTION")
    max_tasks = int(os.getenv("NOTION_MAX_TASKS", "1"))
    tasks = notion.query_tasks(status="queued", limit=max_tasks)

    if not tasks:
        return

    for page in tasks:
        page_id = page.get("id")
        task_type = get_prop_select(page, "Type")
        project = get_prop_select(page, "Project")
        payload = get_prop_text(page, "Payload")
        run_count_raw = page.get("properties", {}).get("RunCount", {}).get("number")
        run_count = int(run_count_raw or 0) + 1

        # mark running
        notion.update_page(page_id, {
            "Status": prop_select("running"),
            "StartedAt": prop_date(now_iso()),
            "RunCount": prop_number(run_count),
            "LastError": prop_text(""),
        })

        try:
            cmd = task_to_command(task_type, project, payload)
            result = run_command(cmd, cwd=REPO_ROOT)
            if result["returncode"] != 0:
                error_text = result["stderr"] or result["stdout"] or "Unknown error"
                notion.update_page(page_id, {
                    "Status": prop_select("failed"),
                    "FinishedAt": prop_date(now_iso()),
                    "LastError": prop_text(error_text[:1500]),
                })
                continue

            notion.update_page(page_id, {
                "Status": prop_select("done"),
                "FinishedAt": prop_date(now_iso()),
                "Result": prop_text(result["stdout"][:1500] if result["stdout"] else "ok"),
            })
        except Exception as exc:
            notion.update_page(page_id, {
                "Status": prop_select("failed"),
                "FinishedAt": prop_date(now_iso()),
                "LastError": prop_text(str(exc)[:1500]),
            })


if __name__ == "__main__":
    main()
