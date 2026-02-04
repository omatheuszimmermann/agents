#!/usr/bin/env python3
import os
import sys
import datetime
import json
import re
import subprocess

# Import llm_client.py from /agents/lib
BASE_AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(BASE_AGENTS_DIR, "lib"))

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

def extract_meta(markdown: str) -> dict:
    meta = {}
    allowed_keys = {"idea", "angle", "keywords", "format"}

    def normalize_key(raw_key: str) -> str:
        key = raw_key.strip()
        key = re.sub(r"^[-*+]\s*", "", key)  # Markdown list markers
        key = key.replace("`", "")
        key = key.replace("*", "")
        key = key.strip().lower()
        return key

    # Find a "Meta" section even if the model outputs numbering (e.g., "## 6. Meta").
    lines = markdown.splitlines()
    meta_start = None
    heading_re = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\d+[\)\.\-:]?\s*)?meta\b\s*$", re.IGNORECASE)
    for idx, line in enumerate(lines):
        if heading_re.match(line.strip()):
            meta_start = idx + 1
            break

    if meta_start is not None:
        for line in lines[meta_start:]:
            stripped = line.strip()
            if re.match(r"^\s*(?:#{1,6}\s*)?(?:\d+[\)\.\-:]?\s*)?(title|caption|hashtags|image prompt|cta|meta)\b", stripped, re.IGNORECASE):
                break  # Next Markdown heading
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            normalized = normalize_key(key)
            if normalized in allowed_keys:
                meta[normalized] = value.strip()

    # Fallback: extract expected keys from the full response if section detection fails.
    if not meta:
        for line in lines:
            stripped = line.strip()
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            normalized = normalize_key(key)
            if normalized in allowed_keys:
                meta[normalized] = value.strip()

    return meta

def extract_sections(markdown: str) -> dict:
    sections = {}
    lines = markdown.splitlines()
    heading_re = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:\d+[\)\.\-:]?\s*)?(title|caption|hashtags|image prompt|cta|meta)\s*$",
        re.IGNORECASE,
    )

    current_key = None
    buffer = []

    def normalize_heading(text: str) -> str:
        t = text.strip().lower()
        t = re.sub(r"[`*]+", "", t)
        if t == "caption":
            return "caption"
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
        m = heading_re.match(line.strip())
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

def build_discord_messages(markdown: str, post_number: int) -> tuple[str, str]:
    sections = extract_sections(markdown)
    description = sections.get("caption", "").strip()
    cta = sections.get("cta", "").strip()
    hashtags = sections.get("hashtags", "").strip()
    image_prompt = sections.get("image_prompt", "").strip()

    body_parts = [part for part in [description, cta, hashtags] if part]
    body = "\n\n".join(body_parts).strip()
    first_message = f"#{post_number}\n\n{body}".strip() if body else f"#{post_number}"
    prompt_message = f"#{post_number} Prompt:\n{image_prompt}".strip() if image_prompt else ""
    return first_message, prompt_message

def update_history(history_file: str, meta: dict) -> int:
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

    max_post_number = 0
    for post in history["posts"]:
        if not isinstance(post, dict):
            continue
        number = post.get("post_number", 0)
        if isinstance(number, int) and number > max_post_number:
            max_post_number = number
    post_number = max_post_number + 1

    history["posts"].append({
        "post_number": post_number,
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "idea": meta.get("idea", ""),
        "angle": meta.get("angle", ""),
        "keywords": [k.strip() for k in meta.get("keywords", "").split(",") if k.strip()],
        "format": meta.get("format", "")
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

    # Load .env from social-media root
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
        "If no topic is provided, you MUST choose a NEW topic/angle that is not repetitive.\n\n"
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
        "- Decide a fresh TOPIC + ANGLE (internally) that differs from past posts.\n"
        "- Then generate the post.\n\n"
        "MANDATORY OUTPUT STRUCTURE (use these exact section titles):\n"
        "1. Title\n"
        "2. Caption\n"
        "3. Hashtags\n"
        "4. Image Prompt (IN ENGLISH, DETAILED, FOLLOWING ALL IMAGE RULES)\n"
        "5. CTA\n"
        "6. Meta (for history tracking)\n\n"
        "In section 'Meta', output exactly these keys:\n"
        "- idea:\n"
        "- angle:\n"
        "- keywords: (comma-separated)\n"
        "- format: (educational|marketing|story|news|tutorial)\n"
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

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")

    # Update history.json with Meta section
    meta = extract_meta(content)
    post_number = update_history(history_file, meta)
        
    # Notify Discord (best-effort)
    notify_script = os.path.join(BASE_DIR, "scripts", "notify_discord.sh")
    if os.path.exists(notify_script):
        first_message, prompt_message = build_discord_messages(content, post_number)
        env = os.environ.copy()
        try:
            env["MSG_ARG"] = first_message
            subprocess.run([notify_script, first_message], check=False, env=env)
            if prompt_message:
                env["MSG_ARG"] = prompt_message
                subprocess.run([notify_script, prompt_message], check=False, env=env)
        except Exception:
            pass

    print(out_file)

if __name__ == "__main__":
    main()
