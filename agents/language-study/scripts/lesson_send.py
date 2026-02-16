#!/usr/bin/env python3
import os
import sys
import json
import datetime
import random
import re
from html import unescape
from urllib.parse import urlparse, parse_qs
from typing import Any, Dict, List, Optional

# Import llm_client.py and notion_client.py from shared/python
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared", "python", "lib"))

from llm_client import load_llm_from_env  # noqa: E402
from notion_client import NotionClient  # noqa: E402

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CONTENT_LIBRARY_DIR = os.path.join(REPO_ROOT, "agents", "content-library")
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


def parse_iso(raw: str) -> Optional[datetime.datetime]:
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def is_within_days(dt: Optional[datetime.datetime], days: int) -> bool:
    if not dt or days <= 0:
        return False
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return dt >= cutoff


def get_last_used_for_user(item: Dict[str, Any], student_id: str) -> Optional[datetime.datetime]:
    used_by = item.get("used_by") or {}
    if isinstance(used_by, dict):
        raw = used_by.get(student_id, "")
        return parse_iso(raw)
    return None


def pick_content(
    items: List[Dict[str, Any]],
    language: str,
    lesson_type: str,
    topic: str,
    student_id: str,
    cooldown_days: int,
) -> Optional[Dict[str, Any]]:
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
        last_used = get_last_used_for_user(item, student_id)
        if is_within_days(last_used, cooldown_days):
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
            last_used = get_last_used_for_user(item, student_id)
            if is_within_days(last_used, cooldown_days):
                continue
            candidates.append(item)
    return candidates[0] if candidates else None


def language_label(language: str) -> str:
    if language == "en":
        return "English"
    if language == "it":
        return "Italian"
    return language


def build_prompt(lesson_type: str, language: str, item: Optional[Dict[str, Any]]) -> str:
    lang_label = language_label(language)
    header = (
        f"You are a language teacher. Create a lesson in {lang_label}.\n"
        f"Write ONLY in {lang_label}. Do not use any other language.\n"
        "Return ONLY the lesson text.\n"
        "Do NOT provide answer keys or solutions.\n"
        "Do NOT repeat questions; each question must be unique.\n"
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


def fetch_url_text(url: str, timeout: int = 30) -> str:
    import ssl
    import certifi
    import urllib.request
    import urllib.error

    req = urllib.request.Request(url=url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.reason} ({url})") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"URL error: {e} ({url})") from None


def extract_article_text(html: str) -> str:
    if not html:
        return ""
    cleaned = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\\1>", " ", html)
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)
    paragraphs = re.findall(r"(?is)<p[^>]*>(.*?)</p>", cleaned)
    if not paragraphs:
        return ""
    texts = []
    for p in paragraphs:
        p = re.sub(r"(?is)<[^>]+>", " ", p)
        p = unescape(p)
        p = re.sub(r"\\s+", " ", p).strip()
        if len(p) >= 40:
            texts.append(p)
    return "\n".join(texts).strip()


def extract_youtube_id(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.netloc.endswith("youtube.com"):
        qs = parse_qs(parsed.query)
        return (qs.get("v") or [""])[0]
    if parsed.netloc.endswith("youtu.be"):
        return parsed.path.lstrip("/")
    return ""


def fetch_youtube_caption(video_id: str, language: str) -> str:
    if not video_id:
        return ""
    lang = "en" if language == "en" else "it"
    url = f"https://video.google.com/timedtext?lang={lang}&v={video_id}"
    xml_text = fetch_url_text(url, timeout=20)
    # captions are XML with <text> nodes
    parts = re.findall(r"(?is)<text[^>]*>(.*?)</text>", xml_text)
    if not parts:
        return ""
    text = " ".join(unescape(p) for p in parts)
    text = re.sub(r"\\s+", " ", text).strip()
    return text


def build_prompt_with_article(
    lesson_type: str,
    language: str,
    item: Optional[Dict[str, Any]],
    article_text: str,
) -> str:
    lang_label = language_label(language)
    header = (
        f"You are a language teacher. Create a lesson in {lang_label}.\n"
        f"Write ONLY in {lang_label}. Do not use any other language.\n"
        "Return ONLY the lesson text.\n"
        "Use short sections and bullet points where helpful.\n"
    )
    if article_text:
        return (
            header
            + "Use ONLY the article text below. Do not invent facts.\n"
            + "Include 3 short quotes from the article (<=12 words each).\n"
            + "Vocabulary must come from the article text.\n"
            + "Do NOT provide answer keys or solutions.\n\n"
            + "Do NOT repeat questions; each question must be unique.\n\n"
            + f"ARTICLE TITLE: {item.get('title','') if item else ''}\n"
            + f"ARTICLE URL: {item.get('url','') if item else ''}\n"
            + "ARTICLE TEXT:\n"
            + article_text
            + "\n\n"
            + "Create: brief intro, key vocabulary, 5 comprehension questions, and 5 exercises.\n"
        )
    return build_prompt(lesson_type, language, item)


def split_bold_segments(text: str) -> List[Dict[str, Any]]:
    parts = text.split("**")
    if len(parts) == 1:
        return [{"type": "text", "text": {"content": text}}]
    segments: List[Dict[str, Any]] = []
    bold = False
    for part in parts:
        if part:
            seg = {"type": "text", "text": {"content": part}}
            if bold:
                seg["annotations"] = {"bold": True}
            segments.append(seg)
        bold = not bold
    return segments


def line_to_block(line: str) -> Optional[Dict[str, Any]]:
    raw = line.rstrip()
    if not raw:
        return None
    if raw.startswith("#"):
        title = raw.lstrip("#").strip()
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": split_bold_segments(title),
            },
        }
    if raw.startswith("- ") or raw.startswith("* "):
        content = raw[2:].strip()
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": split_bold_segments(content),
            },
        }
    if len(raw) >= 3 and raw[0].isdigit() and raw[1] == "." and raw[2] == " ":
        content = raw[3:].strip()
        return {
            "object": "block",
            "type": "numbered_list_item",
            "numbered_list_item": {
                "rich_text": split_bold_segments(content),
            },
        }
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": split_bold_segments(raw),
        },
    }


def lesson_text_to_blocks(text: str) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for line in text.splitlines():
        block = line_to_block(line)
        if block:
            blocks.append(block)
    return blocks


def language_icon(language: str) -> str:
    if language == "en":
        return "🇺🇸"
    if language == "it":
        return "🇮🇹"
    return "📘"


def truncate_title(text: str, max_len: int = 90) -> str:
    if not text:
        return "Lesson"
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 2].rstrip() + ".."


def lesson_title_fallback(lesson_type: str, language: str) -> str:
    label = lesson_type.replace("_", " ").title()
    return f"{label} ({language.upper()})"


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


def resolve_student_configs(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(config.get("students"), list):
        return [c for c in config["students"] if isinstance(c, dict)]
    return [config]


def library_path_for_type(lesson_type: str) -> str:
    if lesson_type == "video":
        return os.path.join(CONTENT_LIBRARY_DIR, "library.video.json")
    return os.path.join(CONTENT_LIBRARY_DIR, "library.article.json")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: lesson_send.py <project> [--student-id <id>] [--topic <name>] [--lesson-type <type>] [--parent-task-id <notion_page_id>]", file=sys.stderr)
        sys.exit(1)

    project = sys.argv[1]
    _ = project  # project is ignored; kept for worker compatibility
    lesson_override = ""
    parent_task_id = ""
    student_filter = ""
    topic_filter = ""
    if "--student-id" in sys.argv:
        idx = sys.argv.index("--student-id")
        if idx + 1 < len(sys.argv):
            student_filter = sys.argv[idx + 1]
    if "--topic" in sys.argv:
        idx = sys.argv.index("--topic")
        if idx + 1 < len(sys.argv):
            topic_filter = sys.argv[idx + 1]
    if "--lesson-type" in sys.argv:
        idx = sys.argv.index("--lesson-type")
        if idx + 1 < len(sys.argv):
            lesson_override = sys.argv[idx + 1]
    if "--parent-task-id" in sys.argv:
        idx = sys.argv.index("--parent-task-id")
        if idx + 1 < len(sys.argv):
            parent_task_id = sys.argv[idx + 1]

    if not os.path.exists(CONFIG_FILE):
        print(f"Config not found: {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)

    # Load envs
    load_env_file(os.path.join(BASE_DIR, ".env"))
    load_env_file(os.path.join(REPO_ROOT, "integrations", "notion", ".env"))
    load_env_file(os.path.join(REPO_ROOT, "integrations", "discord", ".env"))

    profiles = read_json(PROFILES_FILE, {"students": []})
    schedule = read_json(SCHEDULE_FILE, {"week": {}})
    config = read_json(CONFIG_FILE, {})

    api_key = os.getenv("NOTION_API_KEY", "").strip()
    language_db_id = os.getenv("NOTION_DB_LANGUAGE_ID", "").strip()
    if not api_key or not language_db_id:
        raise RuntimeError("Missing Notion config: NOTION_API_KEY / NOTION_DB_LANGUAGE_ID")

    notion = NotionClient(api_key=api_key, database_id=language_db_id)
    llm = load_llm_from_env(prefix="LLM")
    student_configs = resolve_student_configs(config)
    if student_filter:
        student_configs = [c for c in student_configs if c.get("student_id") == student_filter]
    if not student_configs:
        raise RuntimeError("config.json missing student configs")

    created = 0
    for student_cfg in student_configs:
        student_id = student_cfg.get("student_id", "")
        if not student_id:
            continue

        student = get_student(profiles, student_id)
        language = student_cfg.get("language") or (student.get("languages") or [""])[0]
        topics_cfg = student_cfg.get("topics")
        if isinstance(topics_cfg, list):
            topics = [str(t).strip() for t in topics_cfg if str(t).strip()]
        else:
            topic_single = str(student_cfg.get("topic", "")).strip()
            topics = [topic_single] if topic_single else []
        if topic_filter:
            topic = topic_filter
        else:
            topic = random.choice(topics) if topics else ""
        cooldown_days = int(student_cfg.get("cooldown_days", 30))
        schedule_override = student_cfg.get("schedule_override") or {}
        local_schedule = schedule
        if schedule_override:
            merged_week = dict(schedule.get("week", {}))
            merged_week.update(schedule_override)
            local_schedule = {"week": merged_week}

        lesson_type = select_lesson_type(local_schedule, lesson_override)

        selected_item = None
        if lesson_type in ("article", "video"):
            library_path = library_path_for_type(lesson_type)
            library = read_json(library_path, {"items": []})
            items = library.get("items", []) if isinstance(library, dict) else []
            selected_item = pick_content(items, language, lesson_type, topic, student_id, cooldown_days)
            if not selected_item:
                msg = f"[language-study] No content available for {language}/{lesson_type}."
                send_discord(msg)
                continue
            selected_item["status"] = "used"
            used_by = selected_item.get("used_by") or {}
            if not isinstance(used_by, dict):
                used_by = {}
            used_by[student_id] = now_iso()
            selected_item["used_by"] = used_by
            write_json(library_path, library)

        article_text = ""
        if selected_item and selected_item.get("url"):
            try:
                if lesson_type == "video":
                    video_id = extract_youtube_id(selected_item.get("url"))
                    caption = fetch_youtube_caption(video_id, language)
                    max_chars = int(student_cfg.get("video_max_chars", 1500))
                    if caption:
                        article_text = caption[:max_chars]
                else:
                    raw_html = fetch_url_text(selected_item.get("url"))
                    extracted = extract_article_text(raw_html)
                    max_chars = int(student_cfg.get("article_max_chars", 2000))
                    if extracted:
                        article_text = extracted[:max_chars]
            except Exception:
                article_text = ""

        prompt = build_prompt_with_article(lesson_type, language, selected_item, article_text)
        lesson_text = llm.chat(
            messages=[
                {"role": "system", "content": "Return only the lesson text."},
                {"role": "user", "content": prompt},
            ],
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.4")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "700")),
        )

        base_title = selected_item.get("title", "") if selected_item else ""
        if not base_title:
            base_title = lesson_title_fallback(lesson_type, language)
        title = truncate_title(base_title)
        props: Dict[str, Any] = {
            "Title": {"title": [{"text": {"content": title}}]},
            "Status": {"status": {"name": "pending"}},
            "Student": {"select": {"name": student.get("name", "")}},
            "Language": {"select": {"name": language}},
            "Lesson Type": {"select": {"name": lesson_type}},
            "Received At": {"date": {"start": now_iso()}},
        }
        if topic:
            props["Topic"] = {"rich_text": [{"text": {"content": topic}}]}
        if selected_item:
            if selected_item.get("url"):
                props["Source URL"] = {"url": selected_item.get("url")}
            content_value = ""
            if article_text:
                content_value = article_text[:2000]
            elif selected_item.get("summary"):
                content_value = selected_item.get("summary")[:2000]
            if content_value:
                props["Content"] = {"rich_text": [{"text": {"content": content_value}}]}
        if parent_task_id:
            props["Parent Task"] = {"relation": [{"id": parent_task_id}]}

        page = notion.create_page(properties=props, icon_emoji=language_icon(language))
        page_id = page.get("id", "")
        page_url = page.get("url", "")

        if lesson_text:
            blocks = lesson_text_to_blocks(lesson_text)
            for i in range(0, len(blocks), 80):
                notion.append_blocks(page_id, blocks[i:i + 80])

        notify = student.get("notify", {}).get("discord", False)
        if notify:
            msg_lines = [
                f"{language_icon(language)} {title}",
                f"👤 {student.get('name', 'Student')}",
            ]
            if page_url:
                msg_lines.append(page_url)
            send_discord("\n".join(msg_lines))

        created += 1

    print(f"NOTION_RESULT: lesson_created count={created}")


if __name__ == "__main__":
    main()
