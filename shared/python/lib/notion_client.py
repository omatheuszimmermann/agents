#!/usr/bin/env python3
"""
Minimal Notion client for database query + page update/create.
"""
import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional
import ssl
import certifi


NOTION_VERSION = "2022-06-28"


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
        "User-Agent": "notion-client/1.0",
    }


def _request(token: str, method: str, url: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url=url, data=data, headers=_headers(token), method=method)
    try:
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Notion HTTP {e.code}: {e.reason} | body: {body}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Notion URL error: {e}") from None


class NotionClient:
    def __init__(self, api_key: str, database_id: str):
        self.api_key = api_key
        self.database_id = database_id
        self.base_url = "https://api.notion.com/v1"

    def query_tasks(self, status: str, limit: int = 1) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/databases/{self.database_id}/query"
        payload = {
            "page_size": max(1, min(limit, 100)),
            "filter": {
                "property": "Status",
                "select": {"equals": status},
            },
            "sorts": [
                {"timestamp": "created_time", "direction": "ascending"}
            ],
        }
        data = _request(self.api_key, "POST", url, payload)
        return data.get("results", [])

    def update_page(self, page_id: str, properties: Dict[str, Any]) -> None:
        url = f"{self.base_url}/pages/{page_id}"
        payload = {"properties": properties}
        _request(self.api_key, "PATCH", url, payload)

    def create_task(self, name: str, task_type: str, project: str, status: str,
                    requested_by: str, payload_text: str = "") -> Dict[str, Any]:
        url = f"{self.base_url}/pages"
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": {
                "Name": {"title": [{"text": {"content": name}}]},
                "Status": {"select": {"name": status}},
                "Type": {"select": {"name": task_type}},
                "Project": {"select": {"name": project}},
                "RequestedBy": {"select": {"name": requested_by}},
            },
        }
        if payload_text:
            payload["properties"]["Payload"] = {"rich_text": [{"text": {"content": payload_text}}]}
        return _request(self.api_key, "POST", url, payload)


def load_notion_from_env(prefix: str = "NOTION") -> NotionClient:
    api_key = os.getenv(f"{prefix}_API_KEY")
    db_id = os.getenv(f"{prefix}_DB_ID")
    if not api_key or not db_id:
        raise RuntimeError("Missing Notion config: NOTION_API_KEY / NOTION_DB_ID")
    return NotionClient(api_key=api_key, database_id=db_id)
