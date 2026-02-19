#!/usr/bin/env python3
import os
import sys
import datetime
import json
import re
import subprocess

# Import llm_client.py from shared/python
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared", "python", "lib"))

from llm_client import load_llm_from_env  # noqa: E402
from notion_client import NotionClient  # noqa: E402


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
HISTORY_DIR = os.path.join(BASE_DIR, "history")


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


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def extract_project_section(markdown: str, heading: str) -> str:
    if not markdown:
        return ""
    heading_re = re.compile(rf"^#{1,6}\s*{re.escape(heading)}\s*$", re.IGNORECASE)
    lines = markdown.splitlines()
    in_section = False
    buf = []
    for line in lines:
        if heading_re.match(line.strip()):
            in_section = True
            continue
        if in_section and re.match(r"^#{1,6}\s+\S", line.strip()):
            break
        if in_section:
            buf.append(line)
    return "\n".join(buf).strip()

def extract_sections(markdown: str) -> dict:
    sections = {}
    lines = markdown.splitlines()
    inline_heading_re = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:\d+[\)\.\-:]?\s*)?(?:\*\*|__)?\s*"
        r"(title|description|caption|hashtags|image prompt|prompt|cta|meta)\s*"
        r"(?:\*\*|__)?\s*:\s*(.+?)\s*$",
        re.IGNORECASE,
    )
    heading_re = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:\d+[\)\.\-:]?\s*)?(?:\*\*|__)?\s*"
        r"(title|description|caption|hashtags|image prompt|prompt|cta|meta)\s*"
        r"(?:\*\*|__)?\s*$",
        re.IGNORECASE,
    )

    current_key = None
    buffer = []

    def normalize_heading(text: str) -> str:
        t = text.strip().lower()
        t = re.sub(r"[`*]+", "", t)
        if t in {"description", "caption"}:
            return "description"
        if t == "hashtags":
            return "hashtags"
        if t == "cta":
            return "cta"
        if t in {"image prompt", "image_prompt", "prompt"} or t.startswith("image prompt"):
            return "image_prompt"
        return ""

    def flush():
        nonlocal buffer, current_key
        if current_key:
            sections[current_key] = "\n".join(buffer).strip()
        buffer = []

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        m_inline = inline_heading_re.match(stripped)
        if m_inline:
            found = normalize_heading(m_inline.group(1))
            if found:
                flush()
                sections[found] = m_inline.group(2).strip()
                current_key = None
                continue

        m = heading_re.match(stripped)
        if m:
            found = normalize_heading(m.group(1))
            if found:
                flush()
                current_key = found
                continue
            if current_key:
                flush()
                current_key = None
            continue
        if current_key:
            buffer.append(line)

    flush()
    return sections

def render_output_markdown(sections: dict) -> str:
    description = sections.get("description", "").strip()
    cta = sections.get("cta", "").strip()
    hashtags = sections.get("hashtags", "").strip()
    image_prompt = sections.get("image_prompt", "").strip()

    blocks = []
    if description:
        blocks.extend(["Description", description])
    if cta:
        blocks.extend(["CTA", cta])
    if hashtags:
        blocks.extend(["Hashtags", hashtags])
    if image_prompt:
        blocks.extend(["Image Prompt", image_prompt])
    return "\n\n".join(blocks).strip() + "\n"

def build_task_body_text(sections: dict) -> str:
    description = sections.get("description", "").strip()
    cta = sections.get("cta", "").strip()
    hashtags = sections.get("hashtags", "").strip()
    parts = [part for part in [description, cta, hashtags] if part]
    return "\n\n".join(parts).strip()

def chunk_text(text: str, max_len: int = 1800) -> list[str]:
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
def build_discord_message(sections: dict, project: str) -> str:
    date_str = datetime.datetime.now().strftime("%d/%m")
    description = sections.get("description", "").strip()
    cta = sections.get("cta", "").strip()
    hashtags = sections.get("hashtags", "").strip()
    image_prompt = sections.get("image_prompt", "").strip()
    parts = [f"{date_str} - {project}"]
    if description:
        parts.append(description)
    if cta:
        parts.append(cta)
    if hashtags:
        parts.append(hashtags)
    if image_prompt:
        parts.append(f"Prompt: {image_prompt}")
    return "\n\n".join(parts).strip()

def update_history(history_file: str, description: str) -> None:
    history = {"posts": []}

    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {"posts": []}
    if not isinstance(history, dict):
        history = {"posts": []}
    if not isinstance(history.get("posts"), list):
        history["posts"] = []

    history["posts"].append({
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "description": description.strip(),
    })

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    return None

def main():
    if len(sys.argv) < 2:
        print("Usage: generate_post.py <project> [topic] [--parent-task-id <notion_page_id>]", file=sys.stderr)
        sys.exit(1)

    project = sys.argv[1]
    topic = ""
    parent_task_id = ""
    if len(sys.argv) >= 3:
        if sys.argv[2] == "--parent-task-id":
            parent_task_id = sys.argv[3] if len(sys.argv) >= 4 else ""
        else:
            topic = sys.argv[2]
            if len(sys.argv) >= 5 and sys.argv[3] == "--parent-task-id":
                parent_task_id = sys.argv[4]

    project_file = os.path.join(PROJECTS_DIR, project, "project.md")
    if not os.path.exists(project_file):
        print(f"Project file not found: {project_file}", file=sys.stderr)
        sys.exit(1)

    # Load .env from social-posts root
    env_file = os.path.join(BASE_DIR, ".env")
    load_env_file(env_file)
    load_env_file(os.path.join(REPO_ROOT, "integrations", "notion", ".env"))

    llm = load_llm_from_env(prefix="LLM")

    project_spec = read_file(project_file)
    base_image_prompt = extract_project_section(project_spec, "Base Image Prompt")
    os.makedirs(HISTORY_DIR, exist_ok=True)
    history_file = os.path.join(HISTORY_DIR, f"{project}.json")

    history_text = ""
    if os.path.exists(history_file):
        try:
            raw_history = read_file(history_file).strip()
            history_data = json.loads(raw_history) if raw_history else {}
            posts = history_data.get("posts", []) if isinstance(history_data, dict) else []
            if isinstance(posts, list):
                posts = posts[-20:]
            history_text = json.dumps({"posts": posts}, ensure_ascii=False, indent=2)
        except Exception:
            history_text = ""


    system_prompt = (
        "You are a social media content generator.\n"
        "Return ONLY the final Markdown content.\n"
        "Do not include JSON, metadata, or explanations."
    )

    topic_line = f"TOPIC (manual override): {topic}\n\n" if topic else ""

    base_prompt_block = ""
    if base_image_prompt:
        base_prompt_block = (
            "BASE IMAGE PROMPT (fixed style):\n"
            f"{base_image_prompt}\n"
            "The Image Prompt MUST start with this base prompt verbatim, then add only scene details derived "
            "from the Description.\n\n"
        )

    user_prompt = (
        "Generate ONE complete social media post using the project specification below.\n"
        "If no topic is provided, you MUST choose a NEW description angle that is not repetitive.\n\n"
        "PROJECT SPEC:\n"
        "--------------------\n"
        f"{project_spec}\n"
        "--------------------\n\n"
        f"{base_prompt_block}"
        f"{topic_line}"
        "PAST POSTS (JSON history):\n"
        "--------------------\n"
        f"{history_text}\n"
        "--------------------\n\n"
        "TASK:\n"
        "- Decide a fresh content angle (internally) that differs from past posts.\n"
        "- Then generate the post.\n\n"
        "MANDATORY OUTPUT STRUCTURE (use these exact section titles):\n"
        "1. Description\n"
        "2. CTA\n"
        "3. Hashtags\n"
        "4. Image Prompt (IN ENGLISH, DETAILED, FOLLOWING ALL IMAGE RULES)\n"
    )


    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    out_file = os.path.join(
        OUTPUTS_DIR,
        f"{project}_post_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.md",
    )

    content = llm.chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "600")),
    )

    sections = extract_sections(content)
    description = sections.get("description", "").strip()
    if not description:
        description = sections.get("title", "").strip()
    update_history(history_file, description)

    # Save normalized output structure.
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(render_output_markdown(sections))

    notion_page_url = ""
    try:
        api_key = os.getenv("NOTION_API_KEY", "").strip()
        posts_db_id = os.getenv("NOTION_DB_POSTS_ID", "").strip()
        if api_key and posts_db_id:
            notion = NotionClient(api_key=api_key, database_id=posts_db_id)
            title = f"{datetime.datetime.now().strftime('%d/%m')} - {project}"
            body_text = build_task_body_text(sections)
            props = {
                "Title": {"title": [{"text": {"content": title}}]},
                "Project": {"select": {"name": project}},
                "Status": {"status": {"name": "pending"}},
                "Received At": {"date": {"start": datetime.datetime.now().isoformat()}},
                "Prompt": {"rich_text": [{"text": {"content": sections.get("image_prompt", "").strip()}}]},
            }
            if parent_task_id:
                props["Parent Task"] = {"relation": [{"id": parent_task_id}]}
            page = notion.create_page(properties=props)
            chunks = chunk_text(body_text, max_len=1800)
            if chunks:
                notion.append_paragraphs(page.get("id"), chunks)
            notion_page_url = page.get("url", "")
    except Exception as exc:
        send_error_to_discord(f"[social-posts] Notion create failed: {exc}")

    # Notify Discord (best-effort)
    notify_script = os.path.join(REPO_ROOT, "integrations", "discord", "notify_discord.sh")
    if os.path.exists(notify_script):
        channel_id = os.getenv("CHANNEL_ID", "").strip()
        if channel_id:
            first_message = build_discord_message(sections, project)
            prompt_message = ""
            env = os.environ.copy()
            try:
                if notion_page_url:
                    first_message = f"{first_message}\n{notion_page_url}"
                env["MSG_ARG"] = first_message
                subprocess.run([notify_script, channel_id, first_message], check=False, env=env)
            except Exception:
                pass

    print(out_file)
    try:
        normalized_content = render_output_markdown(sections)
        print(f"NOTION_RESULT: {normalized_content}")
    except Exception:
        pass

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        send_error_to_discord(f"[social-posts] Fatal error: {exc}")
        raise
