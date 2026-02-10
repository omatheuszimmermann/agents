#!/usr/bin/env python3
import os
import sys
import imaplib
import email
import argparse
from email.header import decode_header
from typing import List, Tuple

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")


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


def _decode_header(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                decoded.append(text.decode(charset or "utf-8", errors="replace"))
            except Exception:
                decoded.append(text.decode("utf-8", errors="replace"))
        else:
            decoded.append(text)
    return "".join(decoded).strip()


def _imap_connect(host: str, port: int, secure: bool) -> imaplib.IMAP4:
    if secure:
        return imaplib.IMAP4_SSL(host, port)
    return imaplib.IMAP4(host, port)


def _to_imap_date(iso_date: str) -> str:
    try:
        parts = iso_date.split("-")
        if len(parts) != 3:
            raise ValueError
        year, month, day = parts
        months = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ]
        month_idx = int(month)
        if month_idx < 1 or month_idx > 12:
            raise ValueError
        return f"{int(day):02d}-{months[month_idx - 1]}-{year}"
    except Exception as exc:
        raise RuntimeError("Date must be in YYYY-MM-DD format") from exc


def fetch_email_headers(limit: int, status: str, since: str, before: str) -> List[Tuple[str, str, str]]:
    host = os.getenv("IMAP_HOST", "").strip()
    if not host:
        raise RuntimeError("IMAP_HOST is required in the project .env")

    port_raw = os.getenv("IMAP_PORT", "993").strip()
    secure = os.getenv("IMAP_SECURE", "true").strip().lower() in {"1", "true", "yes"}

    username = os.getenv("EMAIL_USERNAME", "").strip() or os.getenv("EMAIL_ADDRESS", "").strip()
    password = os.getenv("EMAIL_PASSWORD", "").strip()

    if not username or not password:
        raise RuntimeError("EMAIL_USERNAME (or EMAIL_ADDRESS) and EMAIL_PASSWORD are required")

    try:
        port = int(port_raw)
    except ValueError:
        raise RuntimeError("IMAP_PORT must be a number")

    mail = _imap_connect(host, port, secure)
    mail.login(username, password)
    mail.select("INBOX")

    search_tokens = []
    if status == "unread":
        search_tokens.append("UNSEEN")
    elif status == "read":
        search_tokens.append("SEEN")
    elif status != "all":
        raise RuntimeError("status must be one of: all, read, unread")

    if since:
        search_tokens.append("SINCE")
        search_tokens.append(_to_imap_date(since))
    if before:
        search_tokens.append("BEFORE")
        search_tokens.append(_to_imap_date(before))

    if not search_tokens:
        search_tokens = ["ALL"]

    search_status, data = mail.search(None, *search_tokens)
    if search_status != "OK":
        raise RuntimeError("Failed to search inbox")

    ids = data[0].split()
    if limit > 0:
        ids = ids[-limit:]

    results: List[Tuple[str, str, str]] = []
    for msg_id in reversed(ids):
        status, msg_data = mail.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if status != "OK" or not msg_data:
            continue
        msg_bytes = msg_data[0][1]
        msg = email.message_from_bytes(msg_bytes)
        subject = _decode_header(msg.get("Subject", ""))
        sender = _decode_header(msg.get("From", ""))
        date = _decode_header(msg.get("Date", ""))
        results.append((date, sender, subject))

    mail.logout()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch email headers via IMAP.")
    parser.add_argument("project", help="Project name in email/projects/<project>/.env")
    parser.add_argument("limit", nargs="?", default=10, type=int, help="Max emails to fetch (default: 10)")
    parser.add_argument("--status", choices=["all", "read", "unread"], default="all", help="Filter by status")
    parser.add_argument("--since", help="Filter emails since date (YYYY-MM-DD)")
    parser.add_argument("--before", help="Filter emails before date (YYYY-MM-DD)")
    args = parser.parse_args()

    project = args.project
    limit = args.limit

    env_file = os.path.join(PROJECTS_DIR, project, ".env")
    if not os.path.exists(env_file):
        print(f"Project .env not found: {env_file}", file=sys.stderr)
        sys.exit(1)

    load_env_file(env_file)

    try:
        headers = fetch_email_headers(limit, args.status, args.since, args.before)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not headers:
        print("No emails found.")
        return

    for idx, (date, sender, subject) in enumerate(headers, start=1):
        print(f"{idx}. {date} | {sender} | {subject}")


if __name__ == "__main__":
    main()
