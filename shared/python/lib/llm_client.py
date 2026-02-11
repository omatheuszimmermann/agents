#!/usr/bin/env python3
"""
Generic LLM client (OpenAI-compatible APIs)

Reads config from env:
  LLM_API_KEY
  LLM_BASE_URL   e.g. https://api.groq.com/openai/v1
  LLM_MODEL
"""

import os
import json
import urllib.request
import urllib.error
from typing import List, Dict, Optional
import ssl
import certifi


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 60):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        req = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Cloudflare/anti-bot sometimes blocks Python-urllib user-agent
                "User-Agent": "curl/8.0.1",
            },
            method="POST",
        )

        try:
            ctx = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {e.code}: {e.reason} | body: {body}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"LLM URL error: {e}") from None

        return data["choices"][0]["message"]["content"].strip()


def load_llm_from_env(prefix: str = "LLM") -> LLMClient:
    api_key = os.getenv(f"{prefix}_API_KEY")
    base_url = os.getenv(f"{prefix}_BASE_URL")
    model = os.getenv(f"{prefix}_MODEL")

    if not api_key or not base_url or not model:
        raise RuntimeError(
            f"Missing LLM config in env. Expected {prefix}_API_KEY, {prefix}_BASE_URL, {prefix}_MODEL"
        )

    return LLMClient(api_key=api_key, base_url=base_url, model=model)
