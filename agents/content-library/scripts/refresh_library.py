#!/usr/bin/env python3
import os
import sys
import json
import hashlib
import datetime
import urllib.request
import urllib.error
import ssl
import certifi
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_SOURCES = os.path.join(BASE_DIR, "sources.json")
DEFAULT_LIBRARY = os.path.join(BASE_DIR, "library.json")
LIBRARY_FILES = {
    "article": os.path.join(BASE_DIR, "library.article.json"),
    "video": os.path.join(BASE_DIR, "library.video.json"),
}
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def fetch_url(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url=url, headers={"User-Agent": "curl/8.0.1"})
    try:
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.reason} ({url})") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"URL error: {e} ({url})") from None


def _tag_endswith(elem: ET.Element, name: str) -> bool:
    return elem.tag.lower().endswith(name.lower())


def _first_child_text(elem: ET.Element, names: List[str]) -> str:
    for child in elem:
        for name in names:
            if _tag_endswith(child, name):
                if child.text:
                    return child.text.strip()
    return ""


def _first_child_attr(elem: ET.Element, name: str, attr: str) -> str:
    for child in elem:
        if _tag_endswith(child, name):
            value = child.attrib.get(attr, "").strip()
            if value:
                return value
    return ""


def _atom_link(elem: ET.Element) -> str:
    for child in elem:
        if not _tag_endswith(child, "link"):
            continue
        rel = (child.attrib.get("rel") or "").strip()
        href = (child.attrib.get("href") or "").strip()
        if rel in ("alternate", "") and href:
            return href
    return ""


def parse_feed(xml_text: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    # RSS
    channel = None
    for child in root:
        if _tag_endswith(child, "channel"):
            channel = child
            break
    if channel is not None:
        for item in channel:
            if not _tag_endswith(item, "item"):
                continue
            title = _first_child_text(item, ["title"]) or ""
            link = _first_child_text(item, ["link"]) or ""
            summary = _first_child_text(item, ["description", "summary"]) or ""
            pub_date = _first_child_text(item, ["pubDate", "date", "updated", "published"]) or ""
            items.append({
                "title": title,
                "url": link,
                "summary": summary,
                "published_raw": pub_date,
            })
        return items

    # Atom
    for entry in root:
        if not _tag_endswith(entry, "entry"):
            continue
        title = _first_child_text(entry, ["title"]) or ""
        link = _atom_link(entry) or _first_child_text(entry, ["link"]) or ""
        summary = _first_child_text(entry, ["summary", "content"]) or ""
        pub_date = _first_child_text(entry, ["updated", "published"]) or ""
        items.append({
            "title": title,
            "url": link,
            "summary": summary,
            "published_raw": pub_date,
        })
    return items


def parse_date(raw: str) -> str:
    if not raw:
        return ""
    # Best-effort: try several formats
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ]:
        try:
            dt = datetime.datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            else:
                dt = dt.astimezone(datetime.timezone.utc)
            return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            continue
    return ""


def hash_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:12]


def normalize_item(source: Dict[str, Any], raw: Dict[str, str]) -> Dict[str, Any]:
    url = raw.get("url", "").strip()
    title = raw.get("title", "").strip()
    published_raw = raw.get("published_raw", "")
    published_at = parse_date(published_raw)
    summary = raw.get("summary", "").strip()
    stable = url or f"{title}-{published_raw}"
    item_id = f"{source.get('id','src')}-{hash_id(stable)}"
    return {
        "id": item_id,
        "language": source.get("language", "").strip(),
        "type": source.get("type", "").strip(),
        "topic": source.get("topic", "").strip(),
        "title": title,
        "url": url,
        "summary": summary,
        "source": source.get("name", source.get("id", "")),
        "published_at": published_at,
        "added_at": now_iso(),
        "status": "available",
    }


def ensure_library_index(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index = {}
    for item in items:
        url = (item.get("url") or "").strip()
        item_id = (item.get("id") or "").strip()
        key = url or item_id
        if key:
            index[key] = item
    return index


def mark_stale(items: List[Dict[str, Any]], max_age_days: int) -> None:
    if max_age_days <= 0:
        return
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=max_age_days)
    for item in items:
        published = item.get("published_at") or ""
        if not published:
            continue
        try:
            dt = datetime.datetime.fromisoformat(published.replace("Z", "+00:00"))
        except Exception:
            continue
        if dt < cutoff and item.get("status") == "available":
            item["status"] = "stale"


def main() -> None:
    sources_path = DEFAULT_SOURCES
    library_path = DEFAULT_LIBRARY
    if len(sys.argv) > 1:
        sources_path = sys.argv[1]
    if len(sys.argv) > 2:
        library_path = sys.argv[2]

    sources_data = load_json(sources_path, {"rules": {}, "sources": []})
    rules = sources_data.get("rules", {}) or {}
    sources = sources_data.get("sources", []) or []
    min_items = int(rules.get("min_items", 8))
    max_age_days = int(rules.get("max_age_days", 45))
    max_items_per_source = int(rules.get("max_items_per_source", 50))

    libraries: Dict[str, Dict[str, Any]] = {}
    items_by_type: Dict[str, List[Dict[str, Any]]] = {}
    total_existing = 0
    for t, path in LIBRARY_FILES.items():
        lib = load_json(path, {"items": [], "updated_at": ""})
        libs_items = lib.get("items", []) if isinstance(lib, dict) else []
        if not isinstance(libs_items, list):
            libs_items = []
        libraries[t] = lib
        items_by_type[t] = libs_items
        total_existing += len(libs_items)

    index = {}
    for t_items in items_by_type.values():
        index.update(ensure_library_index(t_items))
    added = 0

    for src in sources:
        feed_url = (src.get("feed_url") or "").strip()
        if not feed_url:
            continue
        try:
            xml_text = fetch_url(feed_url)
            raw_items = parse_feed(xml_text)
        except Exception as exc:
            os.makedirs(OUTPUTS_DIR, exist_ok=True)
            error_path = os.path.join(OUTPUTS_DIR, "refresh_errors.log")
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(error_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {feed_url}\n{exc}\n\n")
            continue

        max_items = int(src.get("max_items", max_items_per_source))
        raw_items = raw_items[:max_items]
        for raw in raw_items:
            normalized = normalize_item(src, raw)
            key = normalized.get("url") or normalized.get("id")
            if not key or key in index:
                continue
            item_type = normalized.get("type") or ""
            if item_type not in items_by_type:
                continue
            items_by_type[item_type].append(normalized)
            index[key] = normalized
            added += 1

    # Enforce minimum counts by category (best-effort)
    # If below min_items, we keep everything and rely on next refresh.
    total_items = 0
    for t, items in items_by_type.items():
        mark_stale(items, max_age_days)
        library = {
            "updated_at": now_iso(),
            "items": items,
            "rules": {
                "min_items": min_items,
                "max_age_days": max_age_days,
                "max_items_per_source": max_items_per_source,
            },
        }
        save_json(LIBRARY_FILES[t], library)
        total_items += len(items)

    # keep legacy library.json as a small index only
    legacy = {
        "updated_at": now_iso(),
        "total_items": total_items,
        "by_type": {t: len(items) for t, items in items_by_type.items()},
    }
    save_json(library_path, legacy)
    print(f"NOTION_RESULT: content_refresh added={added} total={total_items}")


if __name__ == "__main__":
    main()
