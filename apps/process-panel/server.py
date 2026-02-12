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
STATIC_DIR = os.path.join(BASE_DIR, "static")

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


def list_logs() -> List[Dict]:
    if not os.path.isdir(LOG_DIR):
        return []
    entries = []
    for name in sorted(os.listdir(LOG_DIR)):
        path = os.path.join(LOG_DIR, name)
        if not os.path.isfile(path):
            continue
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
    if not os.path.isdir(LOG_DIR):
        return None
    candidate = os.path.abspath(os.path.join(LOG_DIR, name))
    if not candidate.startswith(os.path.abspath(LOG_DIR) + os.sep):
        return None
    if not os.path.isfile(candidate):
        return None
    return candidate


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
