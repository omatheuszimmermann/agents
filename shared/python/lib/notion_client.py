#!/usr/bin/env python3
"""Minimal Notion client for database query + page update/create."""
import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional
import ssl
import certifi
import datetime

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

    def query_database(self, filter_obj: Dict[str, Any], limit: int = 1) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/databases/{self.database_id}/query"
        payload = {
            "page_size": max(1, min(limit, 100)),
            "filter": filter_obj,
            "sorts": [
                {"timestamp": "created_time", "direction": "ascending"}
            ],
        }
        data = _request(self.api_key, "POST", url, payload)
        return data.get("results", [])

    def query_tasks(self, status: str, limit: int = 1) -> List[Dict[str, Any]]:
        filt = {
            "property": "Status",
            "select": {"equals": status},
        }
        return self.query_database(filter_obj=filt, limit=limit)

    def update_page(self, page_id: str, properties: Dict[str, Any]) -> None:
        url = f"{self.base_url}/pages/{page_id}"
        payload = {"properties": properties}
        _request(self.api_key, "PATCH", url, payload)

    def create_task(self, name: str, task_type: str, project: str, status: str,
                    requested_by: str, payload_text: str = "",
                    parent_task_id: Optional[str] = None,
                    title_event: Optional[str] = None,
                    icon_emoji: Optional[str] = None,
                    title_prop: str = "Name",
                    id_prop: Optional[str] = None) -> Dict[str, Any]:
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
        if icon_emoji:
            payload["icon"] = {"emoji": icon_emoji}
        if payload_text:
            payload["properties"]["Payload"] = {"rich_text": [{"text": {"content": payload_text}}]}
        if parent_task_id:
            payload["properties"]["Parent Task"] = {"relation": [{"id": parent_task_id}]}
        page = _request(self.api_key, "POST", url, payload)
        if title_event:
            prop_name = id_prop or os.getenv("NOTION_TASK_ID_PROPERTY", "ID")
            ticket = _get_unique_id_text(page, prop_name)
            if ticket:
                title = _format_task_title(ticket, title_event)
                self.update_page(page.get("id"), {
                    title_prop: {"title": [{"text": {"content": title}}]},
                })
        return page

    def create_page(self, properties: Dict[str, Any], children: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/pages"
        payload: Dict[str, Any] = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
        }
        if children:
            payload["children"] = children
        return _request(self.api_key, "POST", url, payload)

    def append_paragraphs(self, block_id: str, texts: List[str]) -> None:
        if not texts:
            return
        url = f"{self.base_url}/blocks/{block_id}/children"
        children = []
        for text in texts:
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": text}}],
                },
            })
        _request(self.api_key, "PATCH", url, {"children": children})


def load_notion_from_env(prefix: str = "NOTION") -> NotionClient:
    api_key = os.getenv(f"{prefix}_API_KEY")
    db_id = os.getenv(f"{prefix}_DB_ID")
    if not api_key or not db_id:
        raise RuntimeError("Missing Notion config: NOTION_API_KEY / NOTION_DB_ID")
    return NotionClient(api_key=api_key, database_id=db_id)


def icon_for_task_type(task_type: str) -> str:
    mapping = {
        "email_check": "📧",
        "email_tasks_create": "🧾",
        "posts_create": "📝",
    }
    return mapping.get(task_type, "⚙️")


def _get_unique_id_text(page: Dict[str, Any], prop_name: str) -> str:
    prop = page.get("properties", {}).get(prop_name, {})
    unique_id = prop.get("unique_id") or {}
    number = unique_id.get("number")
    if number is None:
        return ""
    prefix = unique_id.get("prefix") or ""
    if prefix:
        return f"{prefix}-{number}"
    return str(number)


def _format_task_title(ticket: str, event: str) -> str:
    date_str = datetime.datetime.now().strftime("%d/%m")
    return f"#{ticket} {date_str} - {event}".strip()
