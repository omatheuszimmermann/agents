#!/usr/bin/env python3
import os
import sys
import datetime
import json
import re
import subprocess

# Import llm_client.py from shared/python
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "shared", "python"))

from llm_client import load_llm_from_env  # noqa: E402


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


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

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

def render_output_markdown(post_number: int, sections: dict) -> str:
    description = sections.get("description", "").strip()
    cta = sections.get("cta", "").strip()
    hashtags = sections.get("hashtags", "").strip()
    image_prompt = sections.get("image_prompt", "").strip()

    blocks = [f"Post Number: #{post_number}"]
    if description:
        blocks.extend(["Description", description])
    if cta:
        blocks.extend(["CTA", cta])
    if hashtags:
        blocks.extend(["Hashtags", hashtags])
    if image_prompt:
        blocks.extend(["Image Prompt", image_prompt])
    return "\n\n".join(blocks).strip() + "\n"

def build_discord_messages(markdown: str, post_number: int) -> tuple[str, str]:
    sections = extract_sections(markdown)
    description = sections.get("description", "").strip()
    cta = sections.get("cta", "").strip()
    hashtags = sections.get("hashtags", "").strip()
    image_prompt = sections.get("image_prompt", "").strip()

    body_parts = [part for part in [description, cta, hashtags] if part]
    body = "\n\n".join(body_parts).strip()
    first_message = f"#{post_number}\n\n{body}".strip() if body else f"#{post_number}"
    prompt_message = f"#{post_number} Prompt:\n{image_prompt}".strip() if image_prompt else ""
    return first_message, prompt_message

def update_history(history_file: str, description: str) -> int:
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

    normalized_posts = []
    max_existing_number = 0
    for post in history["posts"]:
        if isinstance(post, dict):
            number = post.get("post_number")
            if isinstance(number, int) and number > max_existing_number:
                max_existing_number = number

    max_post_number = max_existing_number
    auto_number = max_existing_number + 1
    for post in history["posts"]:
        if not isinstance(post, dict):
            continue
        number = post.get("post_number")
        if not isinstance(number, int):
            number = auto_number
            auto_number += 1
        date = post.get("date")
        if not isinstance(date, str) or not date.strip():
            date = datetime.datetime.now().strftime("%Y-%m-%d")
        old_description = (
            post.get("description")
            or post.get("caption")
            or post.get("idea")
            or ""
        )
        if not str(old_description).strip():
            continue
        normalized_posts.append({
            "post_number": number,
            "date": date,
            "description": str(old_description).strip(),
        })
        if number > max_post_number:
            max_post_number = number

    history["posts"] = normalized_posts
    post_number = max_post_number + 1

    history["posts"].append({
        "post_number": post_number,
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "description": description.strip(),
    })

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    return post_number

def main():
    if len(sys.argv) < 2:
        print("Usage: generate_post.py <project> [topic]", file=sys.stderr)
        sys.exit(1)

    project = sys.argv[1]
    topic = sys.argv[2] if len(sys.argv) >= 3 else ""

    project_file = os.path.join(PROJECTS_DIR, project, "project.md")
    if not os.path.exists(project_file):
        print(f"Project file not found: {project_file}", file=sys.stderr)
        sys.exit(1)

    # Load .env from social-posts root
    env_file = os.path.join(BASE_DIR, ".env")
    load_env_file(env_file)

    llm = load_llm_from_env(prefix="LLM")

    project_spec = read_file(project_file)
    os.makedirs(HISTORY_DIR, exist_ok=True)
    history_file = os.path.join(HISTORY_DIR, f"{project}.json")

    history_text = ""
    if os.path.exists(history_file):
        try:
            history_text = read_file(history_file).strip()
        except Exception:
            history_text = ""


    system_prompt = (
        "You are a social media content generator.\n"
        "Return ONLY the final Markdown content.\n"
        "Do not include JSON, metadata, or explanations."
    )

    topic_line = f"TOPIC (manual override): {topic}\n\n" if topic else ""

    user_prompt = (
        "Generate ONE complete social media post using the project specification below.\n"
        "If no topic is provided, you MUST choose a NEW description angle that is not repetitive.\n\n"
        "PROJECT SPEC:\n"
        "--------------------\n"
        f"{project_spec}\n"
        "--------------------\n\n"
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
    post_number = update_history(history_file, description)

    # Save normalized output structure with post number.
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(render_output_markdown(post_number, sections))

    # Notify Discord (best-effort)
    notify_script = os.path.join(REPO_ROOT, "integrations", "discord", "notify_discord.sh")
    if os.path.exists(notify_script):
        channel_id = os.getenv("CHANNEL_ID", "").strip()
        if channel_id:
            normalized_content = render_output_markdown(post_number, sections)
            first_message, prompt_message = build_discord_messages(normalized_content, post_number)
            env = os.environ.copy()
            try:
                env["MSG_ARG"] = first_message
                subprocess.run([notify_script, channel_id, first_message], check=False, env=env)
                if prompt_message:
                    env["MSG_ARG"] = prompt_message
                    subprocess.run([notify_script, channel_id, prompt_message], check=False, env=env)
            except Exception:
                pass

    print(out_file)
    try:
        normalized_content = render_output_markdown(post_number, sections)
        first_message, prompt_message = build_discord_messages(normalized_content, post_number)
        if prompt_message:
            notion_text = f"{first_message}\n\n{prompt_message}"
        else:
            notion_text = first_message
        print(f"NOTION_RESULT: {notion_text}")
    except Exception:
        pass

if __name__ == "__main__":
    main()
