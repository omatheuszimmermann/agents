#!/usr/bin/env python3
import os
import sys
import datetime
import json
import re

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
    heading_re = re.compile(r"^\s{0,3}#{1,6}\s*(?:\d+[\)\.\-:]?\s*)?meta\b", re.IGNORECASE)
    for idx, line in enumerate(lines):
        if heading_re.match(line.strip()):
            meta_start = idx + 1
            break

    if meta_start is not None:
        for line in lines[meta_start:]:
            stripped = line.strip()
            if re.match(r"^\s{0,3}#{1,6}\s+\S+", stripped):
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

def update_history(history_file: str, meta: dict):
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
        "idea": meta.get("idea", ""),
        "angle": meta.get("angle", ""),
        "keywords": [k.strip() for k in meta.get("keywords", "").split(",") if k.strip()],
        "format": meta.get("format", "")
    })

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

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
    update_history(history_file, meta)
        
    # Notify Discord (best-effort)
    notify_script = os.path.join(BASE_DIR, "scripts", "notify_discord.sh")
    if os.path.exists(notify_script):
        message = f" Post gerado ({project}): {os.path.basename(out_file)}"
        os.system(f'MSG_ARG="{message}" "{notify_script}" "{message}"')

    print(out_file)

if __name__ == "__main__":
    main()
