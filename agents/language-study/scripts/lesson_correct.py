#!/usr/bin/env python3
import os
import sys
import json
import datetime
from typing import Any, Dict, List

# Import llm_client.py and notion_client.py from shared/python
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared", "python", "lib"))

from llm_client import load_llm_from_env  # noqa: E402
from notion_client import NotionClient  # noqa: E402

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


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


def extract_rich_text(prop: Dict[str, Any]) -> str:
    texts = prop.get("rich_text") or []
    return "".join(t.get("plain_text", "") for t in texts)


def get_select_name(prop: Dict[str, Any]) -> str:
    sel = prop.get("select") or {}
    return sel.get("name", "")


def send_discord(message: str) -> None:
    notify_script = os.path.join(REPO_ROOT, "integrations", "discord", "notify_discord.sh")
    if not os.path.exists(notify_script):
        return
    channel_id = os.getenv("DISCORD_LANGUAGE_CHANNEL_ID", "").strip() or os.getenv("DISCORD_LOG_CHANNEL_ID", "").strip()
    if not channel_id:
        return
    env = os.environ.copy()
    env["MSG_ARG"] = message
    try:
        import subprocess
        subprocess.run([notify_script, channel_id, message], check=False, env=env)
    except Exception:
        return


def build_prompt(language: str, lesson_type: str, content: str, responses: str) -> str:
    return (
        f"You are a language teacher. Correct the student's answers in {language}.\n"
        f"Lesson type: {lesson_type}.\n"
        "Return: corrected answers + short explanations for mistakes.\n\n"
        f"Lesson content:\n{content}\n\n"
        f"Student responses:\n{responses}\n"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: lesson_correct.py <project> [--limit N]", file=sys.stderr)
        sys.exit(1)

    project = sys.argv[1]
    _ = project  # project is ignored; kept for worker compatibility
    limit = 1
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    load_env_file(os.path.join(BASE_DIR, ".env"))
    load_env_file(os.path.join(REPO_ROOT, "integrations", "notion", ".env"))
    load_env_file(os.path.join(REPO_ROOT, "integrations", "discord", ".env"))

    api_key = os.getenv("NOTION_API_KEY", "").strip()
    language_db_id = os.getenv("NOTION_DB_LANGUAGE_ID", "").strip()
    if not api_key or not language_db_id:
        raise RuntimeError("Missing Notion config: NOTION_API_KEY / NOTION_DB_LANGUAGE_ID")

    notion = NotionClient(api_key=api_key, database_id=language_db_id)
    filt = {
        "and": [
            {"property": "Responses", "rich_text": {"is_not_empty": True}},
            {"property": "Correction", "rich_text": {"is_empty": True}},
        ]
    }
    pages = notion.query_database(filter_obj=filt, limit=max(1, min(limit, 10)))
    if not pages:
        print("NOTION_RESULT: no_responses")
        return

    llm = load_llm_from_env(prefix="LLM")
    corrected = 0

    for page in pages:
        props = page.get("properties", {})
        responses = extract_rich_text(props.get("Responses", {})).strip()
        if not responses:
            continue
        content = extract_rich_text(props.get("Content", {})).strip()
        lesson_type = get_select_name(props.get("Lesson Type", {}))
        language = get_select_name(props.get("Language", {})) or "en"

        prompt = build_prompt(language, lesson_type, content, responses)
        correction = llm.chat(
            messages=[
                {"role": "system", "content": "Return only the correction text."},
                {"role": "user", "content": prompt},
            ],
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "700")),
        )

        page_id = page.get("id")
        notion.update_page(page_id, {
            "Correction": {"rich_text": [{"text": {"content": correction[:2000]}}]},
            "Status": {"status": {"name": "done"}},
        })

        chunks = [correction[i:i+1800] for i in range(0, len(correction), 1800)]
        if chunks:
            notion.append_paragraphs(page_id, chunks)

        page_url = page.get("url", "")
        msg = "[language-study] Correction ready"
        if page_url:
            msg = f"{msg}\n{page_url}"
        send_discord(msg)
        corrected += 1

    print(f"NOTION_RESULT: corrected={corrected}")


if __name__ == "__main__":
    main()
