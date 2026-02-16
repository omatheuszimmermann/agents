#!/usr/bin/env python3
import datetime
import json
import os
import plistlib
import subprocess
import sys
from typing import Optional, List, Dict, Tuple
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
REPO_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
RUNNER_DIR = os.path.join(REPO_ROOT, "runner")
LAUNCHD_DIR = os.path.expanduser("~/Library/LaunchAgents")
STATE_DIR = os.path.join(RUNNER_DIR, "state")
LOG_DIR = os.path.join(RUNNER_DIR, "logs")
USAGE_FILE = os.path.join(STATE_DIR, "usage.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")
EXTRA_LOG_FILES = {
    "content-library/refresh_errors.log": os.path.join(
        REPO_ROOT,
        "agents",
        "content-library",
        "scripts",
        "outputs",
        "refresh_errors.log",
    )
}

WORKERS = {
    "notion_worker": {
        "label": "ai.agents.notion.worker",
        "script": os.path.join(RUNNER_DIR, "notion_worker.py"),
        "display_name": "Notion Worker (Queue Runner)",
    },
    "notion_scheduler": {
        "label": "ai.agents.notion.scheduler",
        "script": os.path.join(RUNNER_DIR, "notion_scheduler.py"),
        "display_name": "Notion Scheduler (Recorrencias)",
    },
}


def iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_json(path: str) -> Dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def load_usage() -> Dict:
    return load_json(USAGE_FILE)


def list_plists() -> List[Dict]:
    items = []
    if not os.path.isdir(LAUNCHD_DIR):
        return items
    for name in os.listdir(LAUNCHD_DIR):
        if not name.endswith(".plist"):
            continue
        path = os.path.join(LAUNCHD_DIR, name)
        try:
            with open(path, "rb") as f:
                data = plistlib.load(f)
        except Exception:
            continue
        label = data.get("Label")
        items.append({
            "label": label,
            "start_interval": data.get("StartInterval"),
            "program_arguments": data.get("ProgramArguments") or [],
            "path": path,
        })
    return items


def launchctl_status() -> Tuple[Dict, Optional[str]]:
    try:
        proc = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    except FileNotFoundError:
        return {}, "launchctl_not_found"
    if proc.returncode != 0:
        return {}, (proc.stderr.strip() or proc.stdout.strip() or "launchctl_error")

    status = {}
    for line in proc.stdout.splitlines():
        if not line.strip() or line.startswith("PID"):
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid_raw, exit_status, label = parts
        status[label] = {
            "pid": None if pid_raw == "-" else pid_raw,
            "last_exit_status": exit_status,
        }
    return status, None


def worker_state(worker_id: str) -> Dict:
    path = os.path.join(STATE_DIR, f"{worker_id}.json")
    return load_json(path)


def compute_next_check(last_check_at: Optional[str], interval: Optional[int]) -> Optional[str]:
    if not last_check_at or not interval:
        return None
    dt = parse_iso(last_check_at)
    if not dt:
        return None
    return (dt + datetime.timedelta(seconds=interval)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_log_index() -> Dict[str, str]:
    index: Dict[str, str] = {}
    if os.path.isdir(LOG_DIR):
        for name in os.listdir(LOG_DIR):
            path = os.path.join(LOG_DIR, name)
            if os.path.isfile(path):
                index[name] = path
    for name, path in EXTRA_LOG_FILES.items():
        if os.path.isfile(path):
            index[name] = path
    return index


def list_logs() -> List[Dict]:
    entries = []
    index = build_log_index()
    for name in sorted(index.keys()):
        path = index[name]
        stat = os.stat(path)
        entries.append({
            "name": name,
            "size": stat.st_size,
            "modified_at": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    return entries


def tail_file(path: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        max_bytes = 8192
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > max_bytes:
            f.seek(-max_bytes, os.SEEK_END)
        data = f.read()
    return data.decode("utf-8", errors="replace")


def safe_log_path(name: str) -> Optional[str]:
    index = build_log_index()
    return index.get(name)


def build_status_payload() -> Dict:
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)

    plists = list_plists()
    plists_by_label = {item.get("label"): item for item in plists if item.get("label")}
    launchctl, launchctl_error = launchctl_status()

    def status_for_label(label: str) -> Dict:
        entry = launchctl.get(label)
        loaded = label in launchctl
        active = bool(entry and entry.get("pid"))
        return {
            "loaded": loaded,
            "active": active,
            "pid": entry.get("pid") if entry else None,
            "last_exit_status": entry.get("last_exit_status") if entry else None,
        }

    workers = {}
    for worker_id, meta in WORKERS.items():
        label = meta["label"]
        plist = plists_by_label.get(label, {})
        state = worker_state(worker_id)
        interval = plist.get("start_interval")
        last_check_at = state.get("last_check_at")
        workers[worker_id] = {
            "id": worker_id,
            "label": label,
            "display_name": meta["display_name"],
            "interval_seconds": interval,
            "last_check_at": last_check_at,
            "next_check_at": compute_next_check(last_check_at, interval),
            "last_success_at": state.get("last_success_at"),
            "last_error_at": state.get("last_error_at"),
            "last_error": state.get("last_error"),
            "last_result": state.get("last_result"),
            "last_tasks_seen": state.get("last_tasks_seen"),
            "last_created": state.get("last_created"),
            "last_skipped": state.get("last_skipped"),
            **status_for_label(label),
        }

    processes = []
    for plist in plists:
        label = plist.get("label")
        if not label:
            continue
        status = status_for_label(label)
        program_args = plist.get("program_arguments") or []
        processes.append({
            "label": label,
            "start_interval": plist.get("start_interval"),
            "program": program_args[1] if len(program_args) > 1 else (program_args[0] if program_args else ""),
            **status,
        })

    processes.sort(key=lambda item: item.get("label", ""))

    return {
        "now": iso_now(),
        "workers": workers,
        "processes": processes,
        "logs": list_logs(),
        "launchctl_error": launchctl_error,
    }


def last_days(count: int) -> List[str]:
    today = datetime.datetime.now(datetime.timezone.utc).date()
    return [(today - datetime.timedelta(days=i)).isoformat() for i in reversed(range(count))]


def summarize_usage_entry(entry: Dict, days: List[str]) -> Dict:
    by_day = entry.get("by_day") or {}
    runs_last = sum(int(by_day.get(day, {}).get("runs", 0)) for day in days)
    failed_last = sum(int(by_day.get(day, {}).get("failed", 0)) for day in days)
    duration_last = sum(float(by_day.get(day, {}).get("duration_sec", 0.0)) for day in days)
    items_last = sum(int(by_day.get(day, {}).get("items", 0)) for day in days)
    total_runs = int(entry.get("runs_total", 0))
    total_failed = int(entry.get("runs_failed", 0))
    total_items = int(entry.get("total_items", 0))
    total_duration = float(entry.get("total_duration_sec", 0.0))
    avg_duration = (total_duration / total_runs) if total_runs else None
    avg_items = (total_items / total_runs) if total_runs else None
    failure_rate = (total_failed / total_runs) if total_runs else None
    trend = []
    for day in days:
        day_entry = by_day.get(day, {})
        trend.append({
            "date": day,
            "runs": int(day_entry.get("runs", 0)),
            "failed": int(day_entry.get("failed", 0)),
        })
    return {
        "runs_total": total_runs,
        "runs_failed": total_failed,
        "runs_last": runs_last,
        "failed_last": failed_last,
        "duration_last_sec": duration_last,
        "items_last": items_last,
        "total_items": total_items,
        "total_duration_sec": total_duration,
        "avg_duration_sec": avg_duration,
        "avg_items_per_run": avg_items,
        "failure_rate": failure_rate,
        "trend_last_days": trend,
    }


def build_dashboard_payload() -> Dict:
    usage = load_usage()
    days = last_days(7)
    now = datetime.datetime.now(datetime.timezone.utc)

    agents_payload = {}
    for worker_id in WORKERS.keys():
        entry = (usage.get("agents") or {}).get(worker_id, {})
        state = worker_state(worker_id)
        summary = summarize_usage_entry(entry, days)
        last_success_at = state.get("last_success_at")
        last_success_age = None
        dt = parse_iso(last_success_at) if last_success_at else None
        if dt:
            last_success_age = int((now - dt).total_seconds())
        agents_payload[worker_id] = {
            **summary,
            "last_success_at": last_success_at,
            "last_success_age_sec": last_success_age,
            "last_items_processed": state.get("last_items_processed"),
            "last_duration_sec": state.get("last_duration_sec"),
        }

    task_types_payload = {}
    for task_type, entry in (usage.get("task_types") or {}).items():
        task_types_payload[task_type] = summarize_usage_entry(entry, days)

    worker_state_data = worker_state("notion_worker")
    backlog = {
        "last_tasks_seen": worker_state_data.get("last_tasks_seen"),
        "last_tasks_seen_by_type": worker_state_data.get("last_tasks_seen_by_type") or {},
        "last_check_at": worker_state_data.get("last_check_at"),
    }

    return {
        "now": iso_now(),
        "days": days,
        "agents": agents_payload,
        "task_types": task_types_payload,
        "backlog_estimate": backlog,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._send_json(build_status_payload())
            return

        if parsed.path == "/api/logs":
            self._send_json({"logs": list_logs()})
            return

        if parsed.path == "/api/dashboard":
            self._send_json(build_dashboard_payload())
            return

        if parsed.path.startswith("/api/logs/"):
            name = parsed.path[len("/api/logs/") :]
            path = safe_log_path(name)
            if not path:
                self._send_json({"error": "log_not_found"}, status=404)
                return
            params = parse_qs(parsed.query)
            max_bytes = 20000
            if "tail" in params:
                try:
                    max_bytes = int(params["tail"][0])
                except Exception:
                    pass
            content = tail_file(path, max_bytes)
            self._send_json({"name": name, "content": content})
            return

        if parsed.path.startswith("/api/run/"):
            worker_id = parsed.path[len("/api/run/") :]
            meta = WORKERS.get(worker_id)
            if not meta:
                self._send_json({"error": "unknown_worker"}, status=404)
                return
            launchctl, launchctl_error = launchctl_status()
            if launchctl_error:
                self._send_json({"error": "launchctl_error", "detail": launchctl_error}, status=500)
                return
            label = meta.get("label")
            if not label or label not in launchctl:
                self._send_json({"error": "worker_not_loaded"}, status=409)
                return
            os.makedirs(LOG_DIR, exist_ok=True)
            out_path = os.path.join(LOG_DIR, f"panel.{worker_id}.out")
            err_path = os.path.join(LOG_DIR, f"panel.{worker_id}.err")
            out_f = open(out_path, "a", encoding="utf-8")
            err_f = open(err_path, "a", encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, meta["script"]],
                cwd=REPO_ROOT,
                stdout=out_f,
                stderr=err_f,
            )
            out_f.close()
            err_f.close()
            self._send_json({
                "ok": True,
                "worker": worker_id,
                "pid": proc.pid,
                "started_at": iso_now(),
            })
            return

        super().do_GET()


def main() -> None:
    port = int(os.getenv("PROCESS_PANEL_PORT", "8787"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Process panel running on http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
