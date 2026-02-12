#!/usr/bin/env python3
import os
import sys
import json
import argparse
from typing import Any, Dict, List, Optional
from email.utils import parseaddr, parsedate_to_datetime
import datetime

# Import Notion client
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared", "python", "lib"))

from notion_client import NotionClient  # noqa: E402

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
AGENT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
PROJECTS_DIR = os.path.join(AGENT_DIR, "projects")
OUTPUTS_DIR = os.path.join(AGENT_DIR, "outputs")
NOTIFY_SCRIPT = os.path.join(REPO_ROOT, "integrations", "discord", "notify_discord.sh")


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
            os.environ.setdefault(k.strip(), val)


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log(message: str) -> None:
    print(f"[{now_iso()}] {message}")


def send_discord_message(message: str) -> None:
    channel_id = os.getenv("CHANNEL_ID", "").strip()
    if not channel_id:
        return
    if not os.path.exists(NOTIFY_SCRIPT):
        return
    env = os.environ.copy()
    env["MSG_ARG"] = message
    try:
        import subprocess
        subprocess.run([NOTIFY_SCRIPT, channel_id, message], check=True, env=env)
    except Exception:
        return


def find_latest_output(project: str) -> Optional[str]:
    if not os.path.isdir(OUTPUTS_DIR):
        return None
    prefix = f"{project}_classified_"
    candidates = []
    for name in os.listdir(OUTPUTS_DIR):
        if not name.startswith(prefix) or not name.endswith(".json"):
            continue
        path = os.path.join(OUTPUTS_DIR, name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        candidates.append((mtime, path))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def parse_email_date(raw: str) -> str:
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        else:
            dt = dt.astimezone(datetime.timezone.utc)
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return ""


def extract_email(sender: str) -> str:
    if not sender:
        return ""
    _, addr = parseaddr(sender)
    return addr.strip()


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


def build_body_text(item: Dict[str, str], project: str) -> str:
    lines = [
        f"Subject: {item.get('subject', '')}",
        f"From: {item.get('sender', '')}",
        f"Date: {item.get('date', '')}",
        f"Message ID: {item.get('message_id', '')}",
        f"Classification: {item.get('type', '')}",
        f"Project: {project}",
    ]
    return "\n".join(lines)


def get_ticket_id_text(page: Dict[str, Any], prop_name: str = "Ticket ID") -> str:
    prop = page.get("properties", {}).get(prop_name, {})
    unique_id = prop.get("unique_id") or {}
    number = unique_id.get("number")
    if number is None:
        return ""
    prefix = unique_id.get("prefix") or ""
    if prefix:
        return f"{prefix}-{number}"
    return str(number)


def ensure_title_with_ticket_id(notion: NotionClient, page: Dict[str, Any], subject: str) -> None:
    ticket = get_ticket_id_text(page)
    if not ticket:
        return
    subject = subject or "(no subject)"
    title = f"(#{ticket}) {subject}".strip()
    notion.update_page(page.get("id"), {
        "Subject": {"title": [{"text": {"content": title}}]},
    })


def main() -> None:
    parser = argparse.ArgumentParser(description="Create email tasks in Notion from classified JSON.")
    parser.add_argument("project", help="Project name in agents/email-triage/projects/<project>/.env")
    parser.add_argument("--source", help="Path to classified JSON output")
    parser.add_argument("--parent-task-id", help="Notion page ID of the parent task", default="")
    args = parser.parse_args()

    env_file = os.path.join(PROJECTS_DIR, args.project, ".env")
    if not os.path.exists(env_file):
        print(f"Project .env not found: {env_file}", file=sys.stderr)
        sys.exit(1)

    load_env_file(env_file)
    load_env_file(os.path.join(AGENT_DIR, ".env"))
    load_env_file(os.path.join(REPO_ROOT, "integrations", "notion", ".env"))

    api_key = os.getenv("NOTION_API_KEY", "").strip()
    db_id = os.getenv("NOTION_DB_EMAILS_ID", "").strip()
    if not api_key or not db_id:
        raise RuntimeError("Missing Notion config: NOTION_API_KEY / NOTION_DB_EMAILS_ID")

    source_path = args.source or find_latest_output(args.project)
    if not source_path or not os.path.exists(source_path):
        raise RuntimeError("Classified JSON not found.")

    with open(source_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = data.get("results")
    if not isinstance(results, list):
        raise RuntimeError("Invalid classified JSON: missing results list.")

    notion = NotionClient(api_key=api_key, database_id=db_id)
    created = 0
    skipped = 0

    for item in results:
        message_id = str(item.get("message_id", "")).strip()
        subject = str(item.get("subject", "")).strip() or "(no subject)"
        sender = str(item.get("sender", "")).strip()
        date_raw = str(item.get("date", "")).strip()
        classification = str(item.get("type", "")).strip() or "others"

        if message_id:
            filt = {
                "and": [
                    {"property": "Message ID", "rich_text": {"equals": message_id}},
                    {"property": "Project", "select": {"equals": args.project}},
                ]
            }
            existing = notion.query_database(filter_obj=filt, limit=1)
            if existing:
                skipped += 1
                continue

        props: Dict[str, Any] = {
            "Subject": {"title": [{"text": {"content": subject}}]},
            "Status": {"select": {"name": "pending"}},
            "Project": {"select": {"name": args.project}},
            "Classification": {"select": {"name": classification}},
        }
        if message_id:
            props["Message ID"] = {"rich_text": [{"text": {"content": message_id}}]}
        sender_email = extract_email(sender)
        if sender_email:
            props["Sender"] = {"email": sender_email}
        received_at = parse_email_date(date_raw)
        if received_at:
            props["Received At"] = {"date": {"start": received_at}}
        if args.parent_task_id:
            props["Parent Task"] = {"relation": [{"id": args.parent_task_id}]}

        page = notion.create_page(properties=props)
        page_url = page.get("url", "")
        ensure_title_with_ticket_id(notion, page, subject)
        ticket_id = get_ticket_id_text(page)

        body_text = build_body_text(item, args.project)
        chunks = chunk_text(body_text, max_len=1800)
        if chunks:
            notion.append_paragraphs(page.get("id"), chunks)

        notify_subject = subject
        if ticket_id:
            notify_subject = f"(#{ticket_id}) {subject}"
        message = (
            f"[{classification}] {notify_subject}\n"
            f"From: {sender}\n"
            f"Date: {date_raw}"
        )
        if page_url:
            message = f"{message}\n{page_url}"
        send_discord_message(message)
        created += 1

    print(f"NOTION_RESULT: Created {created} tasks, skipped {skipped}. Source: {os.path.basename(source_path)}")


if __name__ == "__main__":
    main()
