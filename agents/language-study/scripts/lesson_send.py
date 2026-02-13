#!/usr/bin/env python3
import os
import sys
import json
import datetime
from typing import Any, Dict, List, Optional

# Import llm_client.py and notion_client.py from shared/python
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared", "python", "lib"))

from llm_client import load_llm_from_env  # noqa: E402
from notion_client import NotionClient  # noqa: E402

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")
CONTENT_LIBRARY = os.path.join(REPO_ROOT, "agents", "content-library", "library.json")
PROFILES_FILE = os.path.join(BASE_DIR, "profiles.json")
SCHEDULE_FILE = os.path.join(BASE_DIR, "schedule.json")


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


def read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def weekday_key(dt: datetime.date) -> str:
    mapping = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return mapping[dt.weekday()]


def get_student(profiles: Dict[str, Any], student_id: str) -> Dict[str, Any]:
    for student in profiles.get("students", []):
        if student.get("id") == student_id:
            return student
    raise RuntimeError(f"Student not found: {student_id}")


def select_lesson_type(schedule: Dict[str, Any], override: Optional[str] = None) -> str:
    if override:
        return override
    today = datetime.date.today()
    key = weekday_key(today)
    return schedule.get("week", {}).get(key, "exercises")


def pick_content(items: List[Dict[str, Any]], language: str, lesson_type: str, topic: str) -> Optional[Dict[str, Any]]:
    candidates = []
    for item in items:
        if item.get("status") != "available":
            continue
        if language and item.get("language") != language:
            continue
        if lesson_type and item.get("type") != lesson_type:
            continue
        if topic and item.get("topic") != topic:
            continue
        candidates.append(item)
    if not candidates:
        # fallback: ignore topic
        for item in items:
            if item.get("status") != "available":
                continue
            if language and item.get("language") != language:
                continue
            if lesson_type and item.get("type") != lesson_type:
                continue
            candidates.append(item)
    return candidates[0] if candidates else None


def build_prompt(lesson_type: str, language: str, item: Optional[Dict[str, Any]]) -> str:
    header = (
        f"You are a language teacher. Create a lesson in {language}.\n"
        "Return ONLY the lesson text.\n"
        "Use short sections and bullet points where helpful.\n"
    )
    if lesson_type in ("article", "video", "article_with_video") and item:
        content_block = (
            f"SOURCE TITLE: {item.get('title','')}\n"
            f"SOURCE URL: {item.get('url','')}\n"
            f"SUMMARY: {item.get('summary','')}\n"
            "Create: brief intro, key vocabulary, 5 comprehension questions, and 5 exercises.\n"
        )
        return header + content_block
    if lesson_type == "grammar":
        return header + "Create a short grammar lesson with examples and 5 exercises.\n"
    if lesson_type == "exercises":
        return header + "Create 10 mixed exercises (reading, writing, and short answers).\n"
    if lesson_type == "review":
        return header + "Create a weekly review: recap + 8 exercises.\n"
    return header + "Create a general lesson with 5 exercises.\n"


def send_discord(message: str) -> None:
    notify_script = os.path.join(REPO_ROOT, "integrations", "discord", "notify_discord.sh")
    if not os.path.exists(notify_script):
        return
    channel_id = os.getenv("DISCORD_LOG_CHANNEL_ID", "").strip()
    if not channel_id:
        return
    env = os.environ.copy()
    env["MSG_ARG"] = message
    try:
        import subprocess
        subprocess.run([notify_script, channel_id, message], check=False, env=env)
    except Exception:
        return


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: lesson_send.py <project> [--lesson-type <type>] [--parent-task-id <notion_page_id>]", file=sys.stderr)
        sys.exit(1)

    project = sys.argv[1]
    lesson_override = ""
    parent_task_id = ""
    if "--lesson-type" in sys.argv:
        idx = sys.argv.index("--lesson-type")
        if idx + 1 < len(sys.argv):
            lesson_override = sys.argv[idx + 1]
    if "--parent-task-id" in sys.argv:
        idx = sys.argv.index("--parent-task-id")
        if idx + 1 < len(sys.argv):
            parent_task_id = sys.argv[idx + 1]

    project_dir = os.path.join(PROJECTS_DIR, project)
    config_path = os.path.join(project_dir, "config.json")
    if not os.path.exists(config_path):
        print(f"Project config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    # Load envs
    load_env_file(os.path.join(project_dir, ".env"))
    load_env_file(os.path.join(BASE_DIR, ".env"))
    load_env_file(os.path.join(REPO_ROOT, "integrations", "notion", ".env"))
    load_env_file(os.path.join(REPO_ROOT, "integrations", "discord", ".env"))

    profiles = read_json(PROFILES_FILE, {"students": []})
    schedule = read_json(SCHEDULE_FILE, {"week": {}})
    config = read_json(config_path, {})

    student_id = config.get("student_id", "")
    if not student_id:
        raise RuntimeError("config.json missing student_id")

    student = get_student(profiles, student_id)
    language = config.get("language") or (student.get("languages") or [""])[0]
    topic = config.get("topic", "")
    schedule_override = config.get("schedule_override") or {}
    if schedule_override:
        merged_week = dict(schedule.get("week", {}))
        merged_week.update(schedule_override)
        schedule = {"week": merged_week}

    lesson_type = select_lesson_type(schedule, lesson_override)

    library = read_json(CONTENT_LIBRARY, {"items": []})
    items = library.get("items", []) if isinstance(library, dict) else []

    selected_item = None
    if lesson_type in ("article", "video", "article_with_video"):
        selected_item = pick_content(items, language, lesson_type, topic)
        if not selected_item:
            msg = f"[language-study] No content available for {language}/{lesson_type}."
            send_discord(msg)
            print("NOTION_RESULT: no_content")
            return
        selected_item["status"] = "used"
        selected_item["used_at"] = now_iso()
        write_json(CONTENT_LIBRARY, library)

    llm = load_llm_from_env(prefix="LLM")
    prompt = build_prompt(lesson_type, language, selected_item)
    lesson_text = llm.chat(
        messages=[
            {"role": "system", "content": "Return only the lesson text."},
            {"role": "user", "content": prompt},
        ],
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.4")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "700")),
    )

    api_key = os.getenv("NOTION_API_KEY", "").strip()
    language_db_id = os.getenv("NOTION_DB_LANGUAGE_ID", "").strip()
    if not api_key or not language_db_id:
        raise RuntimeError("Missing Notion config: NOTION_API_KEY / NOTION_DB_LANGUAGE_ID")

    notion = NotionClient(api_key=api_key, database_id=language_db_id)
    title = f"{datetime.date.today().isoformat()} - {student.get('name','Student')} - {lesson_type}"
    props: Dict[str, Any] = {
        "Title": {"title": [{"text": {"content": title}}]},
        "Status": {"status": {"name": "pending"}},
        "Student": {"select": {"name": student.get("name", "")}},
        "Language": {"select": {"name": language}},
        "Lesson Type": {"select": {"name": lesson_type}},
        "Received At": {"date": {"start": now_iso()}},
    }
    if topic:
        props["Topic"] = {"select": {"name": topic}}
    if selected_item:
        if selected_item.get("url"):
            props["Source URL"] = {"url": selected_item.get("url")}
        if selected_item.get("summary"):
            props["Content"] = {"rich_text": [{"text": {"content": selected_item.get("summary")[:2000]}}]}
    if parent_task_id:
        props["Parent Task"] = {"relation": [{"id": parent_task_id}]}

    page = notion.create_page(properties=props)
    page_id = page.get("id", "")
    page_url = page.get("url", "")

    if lesson_text:
        chunks = [lesson_text[i:i+1800] for i in range(0, len(lesson_text), 1800)]
        notion.append_paragraphs(page_id, chunks)

    notify = student.get("notify", {}).get("discord", False)
    if notify:
        msg = f"[language-study] Lesson ready: {title}"
        if page_url:
            msg = f"{msg}\n{page_url}"
        send_discord(msg)

    print(f"NOTION_RESULT: lesson_created {title}")


if __name__ == "__main__":
    main()
