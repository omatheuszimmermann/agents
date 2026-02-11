#!/usr/bin/env python3
import json
import os
import shlex
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

import jobctl

API_PREFIX = "/api/launchd/jobs"
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
}


def json_response(handler: BaseHTTPRequestHandler, status: int, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def read_json(handler: BaseHTTPRequestHandler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def job_payload(job: dict) -> dict:
    return {
        "id": job["label"],
        "label": job["label"],
        "filename": job["filename"],
        "loaded": job["loaded"],
        "scheduleType": job["scheduleType"],
        "scheduleValue": job["scheduleValue"],
        "scheduleDays": job.get("scheduleDays", []),
        "runAtLoad": bool(job.get("runAtLoad")),
        "keepAlive": bool(job.get("keepAlive")),
        "programArgs": job.get("programArgs", ""),
        "stdoutPath": job.get("stdoutPath", ""),
        "stderrPath": job.get("stderrPath", ""),
    }


def parse_time(value: str) -> str:
    if ":" not in value:
        raise ValueError("Horario invalido")
    h_str, m_str = value.split(":", 1)
    if not (h_str.isdigit() and m_str.isdigit()):
        raise ValueError("Horario invalido")
    h = int(h_str)
    m = int(m_str)
    if h < 0 or h > 23 or m < 0 or m > 59:
        raise ValueError("Horario invalido")
    return f"{h:02d}:{m:02d}"


def parse_weekdays(values) -> list:
    days = []
    for item in values:
        if not isinstance(item, int) and not (isinstance(item, str) and item.isdigit()):
            raise ValueError("Dia da semana invalido")
        day = int(item)
        if day < 1 or day > 7:
            raise ValueError("Dia da semana invalido")
        days.append(day)
    if not days:
        raise ValueError("Selecione pelo menos um dia da semana")
    return sorted(set(days))


def parse_interval(value: str) -> int:
    if not value.isdigit() or int(value) <= 0:
        raise ValueError("Intervalo invalido")
    return int(value)


def default_log_paths(label: str):
    logs_dir = os.path.join(jobctl.REPO_ROOT, "runner", "logs")
    return (
        os.path.join(logs_dir, f"{label}.out"),
        os.path.join(logs_dir, f"{label}.err"),
    )


def apply_updates(data: dict, updates: dict):
    if "label" in updates and updates["label"]:
        data["Label"] = updates["label"]

    if "programArgs" in updates:
        args_text = updates.get("programArgs", "")
        data["ProgramArguments"] = jobctl.parse_program_args(args_text)

    if "runAtLoad" in updates:
        data["RunAtLoad"] = bool(updates.get("runAtLoad"))

    if "keepAlive" in updates:
        if updates.get("keepAlive"):
            data["KeepAlive"] = True
        else:
            data.pop("KeepAlive", None)

    if "stdoutPath" in updates:
        data["StandardOutPath"] = updates.get("stdoutPath", "")

    if "stderrPath" in updates:
        data["StandardErrorPath"] = updates.get("stderrPath", "")

    if "scheduleType" in updates:
        schedule_type = updates.get("scheduleType") or "none"
        schedule_value = (updates.get("scheduleValue") or "").strip()
        schedule_days = updates.get("scheduleDays") or []
        data.pop("StartCalendarInterval", None)
        data.pop("StartInterval", None)
        if schedule_type == "calendar":
            parsed = parse_time(schedule_value)
            h, m = parsed.split(":", 1)
            data["StartCalendarInterval"] = {"Hour": int(h), "Minute": int(m)}
        elif schedule_type == "weekly":
            parsed = parse_time(schedule_value)
            days = parse_weekdays(schedule_days)
            h, m = parsed.split(":", 1)
            data["StartCalendarInterval"] = [
                {"Weekday": day, "Hour": int(h), "Minute": int(m)} for day in days
            ]
        elif schedule_type == "interval":
            data["StartInterval"] = parse_interval(schedule_value)


class LaunchdHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith(API_PREFIX):
            if parsed.path == API_PREFIX or parsed.path == API_PREFIX + "/":
                jobs = jobctl.build_installed_jobs()
                json_response(self, 200, [job_payload(job) for job in jobs])
                return
            json_response(self, 404, {"error": "Rota nao encontrada"})
            return

        self.serve_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != API_PREFIX:
            json_response(self, 404, {"error": "Rota nao encontrada"})
            return

        payload = read_json(self)
        label = (payload.get("label") or payload.get("id") or "").strip()
        filename = (payload.get("filename") or f"{label}.plist").strip()

        if not label:
            json_response(self, 400, {"error": "Label obrigatorio"})
            return
        if not filename.endswith(".plist"):
            json_response(self, 400, {"error": "Arquivo deve terminar com .plist"})
            return

        existing = jobctl.find_job(label)
        if existing:
            json_response(self, 409, {"error": "Label ja existe"})
            return

        dest_path = os.path.join(jobctl.LAUNCH_AGENTS_DIR, filename)
        if os.path.exists(dest_path):
            json_response(self, 409, {"error": "Arquivo ja existe"})
            return

        args_text = payload.get("programArgs", "")
        if not args_text:
            json_response(self, 400, {"error": "ProgramArguments obrigatorio"})
            return

        try:
            program_args = jobctl.parse_program_args(args_text)
        except ValueError:
            json_response(self, 400, {"error": "ProgramArguments invalido"})
            return

        schedule_type = payload.get("scheduleType", "none")
        schedule_value = (payload.get("scheduleValue") or "").strip()
        schedule_days = payload.get("scheduleDays") or []

        if schedule_type == "calendar":
            try:
                schedule_value = parse_time(schedule_value)
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
                return
        elif schedule_type == "weekly":
            try:
                schedule_value = parse_time(schedule_value)
                schedule_days = parse_weekdays(schedule_days)
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
                return
        elif schedule_type == "interval":
            try:
                schedule_value = str(parse_interval(schedule_value))
            except ValueError as exc:
                json_response(self, 400, {"error": str(exc)})
                return
        else:
            schedule_type = "none"
            schedule_value = ""

        run_at_load = bool(payload.get("runAtLoad", True))
        keep_alive = bool(payload.get("keepAlive", False))
        stdout_path = payload.get("stdoutPath") or ""
        stderr_path = payload.get("stderrPath") or ""
        if not stdout_path or not stderr_path:
            default_out, default_err = default_log_paths(label)
            stdout_path = stdout_path or default_out
            stderr_path = stderr_path or default_err

        jobctl.ensure_launch_agents_dir()
        os.makedirs(jobctl.TEMPLATES_DIR, exist_ok=True)

        data = jobctl.build_new_plist(
            label=label,
            program_args=program_args,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            run_at_load=run_at_load,
            keep_alive=keep_alive,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )

        if schedule_type == "weekly":
            h, m = schedule_value.split(":", 1)
            data.pop("StartCalendarInterval", None)
            data["StartCalendarInterval"] = [
                {"Weekday": day, "Hour": int(h), "Minute": int(m)} for day in schedule_days
            ]

        template_path = os.path.join(jobctl.TEMPLATES_DIR, filename)
        jobctl.save_plist(template_path, data)
        jobctl.save_plist(dest_path, data)
        jobctl.launchctl_reload(dest_path)
        jobctl.upsert_runner_job(label, program_args)

        job = jobctl.build_job_entry(dest_path, set(jobctl.launchctl_labels()))
        json_response(self, 201, job_payload(job))

    def do_PATCH(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith(API_PREFIX + "/"):
            json_response(self, 404, {"error": "Rota nao encontrada"})
            return

        target = unquote(parsed.path[len(API_PREFIX) + 1 :])
        job = jobctl.find_job(target)
        if not job:
            json_response(self, 404, {"error": "Job nao encontrado"})
            return

        payload = read_json(self)
        new_label = (payload.get("label") or job["label"]).strip()
        new_filename = (payload.get("filename") or job["filename"]).strip()

        if not new_label:
            json_response(self, 400, {"error": "Label obrigatorio"})
            return
        if not new_filename.endswith(".plist"):
            json_response(self, 400, {"error": "Arquivo deve terminar com .plist"})
            return

        plist_path = job["path"]
        old_label = job["label"]
        data = jobctl.load_plist(plist_path)
        payload["label"] = new_label
        try:
            apply_updates(data, payload)
        except ValueError as exc:
            json_response(self, 400, {"error": str(exc)})
            return

        if new_filename != job["filename"]:
            new_path = os.path.join(jobctl.LAUNCH_AGENTS_DIR, new_filename)
            if os.path.exists(new_path):
                json_response(self, 409, {"error": "Arquivo ja existe"})
                return
            jobctl.launchctl_unload(plist_path)
            os.rename(plist_path, new_path)
            plist_path = new_path

            old_template = os.path.join(jobctl.TEMPLATES_DIR, job["filename"])
            if os.path.isfile(old_template):
                new_template = os.path.join(jobctl.TEMPLATES_DIR, new_filename)
                os.rename(old_template, new_template)
        else:
            old_template = os.path.join(jobctl.TEMPLATES_DIR, job["filename"])
            new_template = old_template

        jobctl.save_plist(plist_path, data)
        if os.path.isfile(new_template):
            jobctl.save_plist(new_template, data)

        jobctl.launchctl_reload(plist_path)
        jobctl.upsert_runner_job(new_label, data.get("ProgramArguments", []))
        if old_label != new_label:
            jobctl.remove_runner_job(old_label)
        updated = jobctl.build_job_entry(plist_path, set(jobctl.launchctl_labels()))
        json_response(self, 200, job_payload(updated))

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith(API_PREFIX + "/"):
            json_response(self, 404, {"error": "Rota nao encontrada"})
            return

        target = unquote(parsed.path[len(API_PREFIX) + 1 :])
        job = jobctl.find_job(target)
        if not job:
            json_response(self, 404, {"error": "Job nao encontrado"})
            return

        jobctl.launchctl_unload(job["path"])
        os.remove(job["path"])
        jobctl.remove_runner_job(job["label"])
        self.send_response(204)
        self.end_headers()

    def serve_static(self, path: str):
        if path == "/":
            path = "/index.html"
        safe_path = os.path.normpath(path).lstrip("/")
        target = os.path.abspath(os.path.join(FRONTEND_DIR, safe_path))
        if not target.startswith(FRONTEND_DIR):
            self.send_response(403)
            self.end_headers()
            return
        if not os.path.isfile(target):
            self.send_response(404)
            self.end_headers()
            return

        ext = os.path.splitext(target)[1].lower()
        content_type = MIME_TYPES.get(ext, "application/octet-stream")
        with open(target, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("LAUNCHD_UI_PORT", "8787"))
    server = ThreadingHTTPServer((host, port), LaunchdHandler)
    print(f"Launchd UI: http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
