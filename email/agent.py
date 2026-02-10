#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
import json
import datetime
from typing import List, Dict

# Import llm_client.py from /agents/lib
BASE_AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(BASE_AGENTS_DIR, "lib"))

from llm_client import load_llm_from_env  # noqa: E402

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
TMP_DIR = os.path.join(BASE_DIR, "tmp")


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
    email_script = os.path.join(BASE_DIR, "fetch_emails.py")
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
        })
    return parsed


def classify_email(llm, email_item: Dict[str, str]) -> str:
    system_prompt = (
        "You are an email classifier. Return ONLY one label from: "
        "suporte, novo_cliente, duvida, spam, descartavel, outro."
    )
    user_prompt = (
        "Classify this email by type.\n"
        f"Date: {email_item.get('date', '')}\n"
        f"From: {email_item.get('sender', '')}\n"
        f"Subject: {email_item.get('subject', '')}\n"
        "Return only the label. If unsure, use 'outro'."
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
    allowed = {"suporte", "novo_cliente", "duvida", "spam", "descartavel", "outro"}
    if label not in allowed:
        return "outro"
    return label


def send_discord_message(message: str) -> None:
    notify_script = os.path.join(BASE_DIR, "scripts", "notify_discord.sh")
    if not os.path.exists(notify_script):
        raise RuntimeError(f"notify_discord.sh not found at {notify_script}")
    env = os.environ.copy()
    env["MSG_ARG"] = message
    subprocess.run([notify_script, message], check=True, env=env)


def main() -> None:
    parser = argparse.ArgumentParser(description="Email agent: fetch and classify emails.")
    parser.add_argument("project", help="Project name in email/projects/<project>/.env")
    parser.add_argument("limit", nargs="?", default=10, type=int, help="Max emails to fetch (default: 10)")
    parser.add_argument("--status", choices=["all", "read", "unread"], default="all", help="Filter by status")
    parser.add_argument("--since", help="Filter emails since date (YYYY-MM-DD)")
    parser.add_argument("--before", help="Filter emails before date (YYYY-MM-DD)")
    args = parser.parse_args()

    env_file = os.path.join(PROJECTS_DIR, args.project, ".env")
    if not os.path.exists(env_file):
        print(f"Project .env not found: {env_file}", file=sys.stderr)
        sys.exit(1)

    # Load project .env first, then base .env to fill missing values.
    load_env_file(env_file)
    load_env_file(os.path.join(BASE_DIR, ".env"))

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
                "type": label,
            }
            results.append(result)

            message = (
                f"[{label}] {result['subject']}\n"
                f"From: {result['sender']}\n"
                f"Date: {result['date']}"
            )
            try:
                send_discord_message(message)
            except Exception as exc:
                print(f"Discord notify failed: {exc}", file=sys.stderr)

            if message_id:
                seen_ids.add(message_id)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({"project": args.project, "results": results}, f, indent=2, ensure_ascii=False)

        with open(seen_file, "w", encoding="utf-8") as f:
            json.dump(sorted(seen_ids), f, indent=2, ensure_ascii=False)

        print(output_file)
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)


if __name__ == "__main__":
    main()
