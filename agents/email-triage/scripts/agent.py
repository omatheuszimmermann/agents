#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
import json
import datetime
from typing import List, Dict

# Import llm_client.py from shared/python
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared", "python", "lib"))

from llm_client import load_llm_from_env  # noqa: E402
from notion_client import load_notion_from_env, icon_for_task_type  # noqa: E402

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
AGENT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
PROJECTS_DIR = os.path.join(AGENT_DIR, "projects")
OUTPUTS_DIR = os.path.join(AGENT_DIR, "outputs")
TMP_DIR = os.path.join(AGENT_DIR, "tmp")


def load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            val = v.strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            os.environ[k.strip()] = val


def run_email_fetch(project: str, limit: int, status: str, since: str, before: str) -> List[str]:
    email_script = os.path.join(SCRIPT_DIR, "fetch_emails.py")
    if not os.path.exists(email_script):
        raise RuntimeError(f"fetch_emails.py not found at {email_script}")

    cmd = [sys.executable, email_script, project, str(limit)]
    if status:
        cmd.extend(["--status", status])
    if since:
        cmd.extend(["--since", since])
    if before:
        cmd.extend(["--before", before])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr.strip() or "Unknown error"
        raise RuntimeError(f"fetch_emails.py failed: {err}")

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if lines and lines[0].lower().startswith("no emails found"):
        return []
    return lines


def parse_email_lines(lines: List[str]) -> List[Dict[str, str]]:
    parsed = []
    for line in lines:
        if line.startswith("{") and line.endswith("}"):
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    parsed.append({
                        "date": str(obj.get("date", "")),
                        "sender": str(obj.get("sender", "")),
                        "subject": str(obj.get("subject", "")),
                        "message_id": str(obj.get("message_id", "")),
                        "body": str(obj.get("body", "")),
                    })
                    continue
            except Exception:
                pass
        # Expected: "1. date | sender | subject | message_id"
        if ". " in line:
            _, rest = line.split(". ", 1)
        else:
            rest = line
        parts = [p.strip() for p in rest.split("|")]
        if len(parts) < 3:
            continue
        date = parts[0]
        sender = parts[1]
        subject = parts[2] if len(parts) >= 3 else ""
        message_id = parts[3] if len(parts) >= 4 else ""
        parsed.append({
            "date": date,
            "sender": sender,
            "subject": subject,
            "message_id": message_id,
            "body": "",
        })
    return parsed


def classify_email(llm, email_item: Dict[str, str]) -> str:
    system_prompt = (
        "You are an email classifier. Return ONLY one label from: "
        "lead, support, billing, cancellation, features, spam, others."
    )
    user_prompt = (
        "Classify this email by type.\n"
        f"Date: {email_item.get('date', '')}\n"
        f"From: {email_item.get('sender', '')}\n"
        f"Subject: {email_item.get('subject', '')}\n"
        "Return only the label. If unsure, use 'others'."
    )

    raw = llm.chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        max_tokens=10,
    )

    label = raw.strip().lower().replace(" ", "_")
    allowed = {"lead", "support", "billing", "cancellation", "features", "spam", "others"}
    if label not in allowed:
        return "others"
    return label


def send_error_to_discord(message: str) -> None:
    notify_script = os.path.join(REPO_ROOT, "integrations", "discord", "notify_discord.sh")
    if not os.path.exists(notify_script):
        return
    channel_id = os.getenv("DISCORD_LOG_CHANNEL_ID", "").strip()
    if not channel_id:
        return
    env = os.environ.copy()
    env["MSG_ARG"] = message
    subprocess.run([notify_script, channel_id, message], check=False, env=env)

def maybe_enqueue_task_creation(project: str, output_file: str, count: int, parent_task_id: str) -> None:
    if count <= 0:
        return
    try:
        notion = load_notion_from_env(prefix="NOTION")
        name = f"email_tasks_create {project}"
        notion.create_task(
            name=name,
            task_type="email_tasks_create",
            project=project,
            status="queued",
            requested_by="system",
            payload_text=output_file,
            parent_task_id=parent_task_id or None,
            title_event=f"email_tasks_create {project}",
            icon_emoji=icon_for_task_type("email_tasks_create"),
        )
    except Exception as exc:
        print(f"Failed to enqueue email_tasks_create: {exc}", file=sys.stderr)
        send_error_to_discord(f"[email-triage] Failed to enqueue email_tasks_create: {exc}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Email agent: fetch and classify emails.")
    parser.add_argument("project", help="Project name in agents/email-triage/projects/<project>/.env")
    parser.add_argument("limit", nargs="?", default=10, type=int, help="Max emails to fetch (default: 10)")
    parser.add_argument("--status", choices=["all", "read", "unread"], default="all", help="Filter by status")
    parser.add_argument("--since", help="Filter emails since date (YYYY-MM-DD)")
    parser.add_argument("--before", help="Filter emails before date (YYYY-MM-DD)")
    parser.add_argument("--parent-task-id", help="Notion page ID of the parent task", default="")
    args = parser.parse_args()

    env_file = os.path.join(PROJECTS_DIR, args.project, ".env")
    if not os.path.exists(env_file):
        print(f"Project .env not found: {env_file}", file=sys.stderr)
        sys.exit(1)

    # Load project .env first, then base .env to fill missing values.
    load_env_file(env_file)
    load_env_file(os.path.join(AGENT_DIR, ".env"))
    load_env_file(os.path.join(REPO_ROOT, "integrations", "notion", ".env"))

    llm = load_llm_from_env(prefix="LLM")

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    tmp_file = os.path.join(TMP_DIR, f"{args.project}_pending_{timestamp}.txt")
    output_file = os.path.join(OUTPUTS_DIR, f"{args.project}_classified_{timestamp}.json")
    seen_file = os.path.join(OUTPUTS_DIR, f"{args.project}_seen_ids.json")

    lines = run_email_fetch(args.project, args.limit, args.status, args.since, args.before)
    with open(tmp_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))

    try:
        emails = parse_email_lines(lines)
        seen_ids = set()
        if os.path.exists(seen_file):
            try:
                with open(seen_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        seen_ids = set(str(x) for x in data if x)
            except Exception:
                seen_ids = set()

        results = []
        for item in emails:
            message_id = item.get("message_id", "")
            if message_id and message_id in seen_ids:
                continue

            label = classify_email(llm, item)
            result = {
                "date": item.get("date", ""),
                "sender": item.get("sender", ""),
                "subject": item.get("subject", ""),
                "message_id": message_id,
                "body": item.get("body", ""),
                "type": label,
            }
            results.append(result)

            if message_id:
                seen_ids.add(message_id)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({"project": args.project, "results": results}, f, indent=2, ensure_ascii=False)

        with open(seen_file, "w", encoding="utf-8") as f:
            json.dump(sorted(seen_ids), f, indent=2, ensure_ascii=False)

        print(output_file)
        maybe_enqueue_task_creation(args.project, output_file, len(results), args.parent_task_id)
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        send_error_to_discord(f"[email-triage] Fatal error: {exc}")
        raise
