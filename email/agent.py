#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
import json
import datetime
import urllib.request
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
            os.environ.setdefault(k.strip(), v.strip())


def run_email_fetch(project: str, limit: int, status: str, since: str, before: str) -> List[str]:
    email_script = os.path.join(BASE_DIR, "email.py")
    if not os.path.exists(email_script):
        raise RuntimeError(f"email.py not found at {email_script}")

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
        raise RuntimeError(f"email.py failed: {err}")

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if lines and lines[0].lower().startswith("no emails found"):
        return []
    return lines


def parse_email_lines(lines: List[str]) -> List[Dict[str, str]]:
    parsed = []
    for line in lines:
        # Expected: "1. date | sender | subject"
        if ". " in line:
            _, rest = line.split(". ", 1)
        else:
            rest = line
        parts = [p.strip() for p in rest.split("|")]
        if len(parts) < 3:
            continue
        date, sender, subject = parts[0], parts[1], "|".join(parts[2:]).strip()
        parsed.append({"date": date, "sender": sender, "subject": subject})
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


def send_discord_message(webhook_url: str, message: str) -> None:
    payload = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        url=webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        _ = resp.read()


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
    discord_webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not discord_webhook:
        print("DISCORD_WEBHOOK_URL is not set in email/.env", file=sys.stderr)
        sys.exit(1)

    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    os.makedirs(TMP_DIR, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    tmp_file = os.path.join(TMP_DIR, f"{args.project}_pending_{timestamp}.txt")
    output_file = os.path.join(OUTPUTS_DIR, f"{args.project}_classified_{timestamp}.json")

    lines = run_email_fetch(args.project, args.limit, args.status, args.since, args.before)
    with open(tmp_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))

    try:
        emails = parse_email_lines(lines)
        results = []
        for item in emails:
            label = classify_email(llm, item)
            result = {
                "date": item.get("date", ""),
                "sender": item.get("sender", ""),
                "subject": item.get("subject", ""),
                "type": label,
            }
            results.append(result)

            message = (
                f"[{label}] {result['subject']}\n"
                f"From: {result['sender']}\n"
                f"Date: {result['date']}"
            )
            try:
                send_discord_message(discord_webhook, message)
            except Exception as exc:
                print(f"Discord notify failed: {exc}", file=sys.stderr)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({"project": args.project, "results": results}, f, indent=2, ensure_ascii=False)

        print(output_file)
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)


if __name__ == "__main__":
    main()
