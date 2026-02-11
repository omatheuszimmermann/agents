#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from datetime import datetime, date

BASE = os.path.abspath(os.path.dirname(__file__))
STATE_DIR = os.path.join(BASE, "state")
LOG_DIR = os.path.join(BASE, "logs")
JOBS_FILE = os.path.join(BASE, "jobs.json")

os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

def today_str() -> str:
    return date.today().isoformat()

def dow() -> int:
    # 1=Mon .. 7=Sun
    return date.today().isoweekday()

def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def state_path(job_id: str) -> str:
    return os.path.join(STATE_DIR, f"{job_id}.json")

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    with open(os.path.join(LOG_DIR, "runner.log"), "a", encoding="utf-8") as f:
        f.write(line)

def should_run_twice_per_week_windows(st: dict) -> bool:
    """
    2x/semana com catch-up simples:
    - Janela 1: Seg-Ter-Qua (executa 1x nessa janela)
    - Janela 2: Qui-Sex-Sab-Dom (executa 1x nessa janela)
    Se o Mac estiver desligado no dia ideal, vai rodar no próximo dia disponível da janela.
    """
    d = dow()
    t = today_str()

    if 1 <= d <= 3:
        last = st.get("last_run_window1")
        return last != t
    else:
        last = st.get("last_run_window2")
        return last != t

def mark_run_twice_per_week_windows(st: dict):
    d = dow()
    t = today_str()
    if 1 <= d <= 3:
        st["last_run_window1"] = t
    else:
        st["last_run_window2"] = t

def run_job(job: dict):
    job_id = job["id"]
    cwd = job["cwd"]
    cmd = job["command"]
    args = job.get("args", [])

    st = load_json(state_path(job_id), {})

    policy = job.get("policy", {})
    policy_type = policy.get("type")

    if policy_type == "twice_per_week_windows":
        if not should_run_twice_per_week_windows(st):
            log(f"SKIP {job_id} (already ran today in this window)")
            return
    else:
        log(f"SKIP {job_id} (unknown policy: {policy_type})")
        return

    log(f"RUN  {job_id}: {cmd} {' '.join(args)} (cwd={cwd})")
    try:
        proc = subprocess.run(
            [cmd, *args],
            cwd=cwd,
            text=True,
            capture_output=True
        )
        out = proc.stdout.strip()
        err = proc.stderr.strip()

        if out:
            log(f"OUT  {job_id}: {out}")
        if err:
            log(f"ERR  {job_id}: {err}")

        if proc.returncode != 0:
            log(f"FAIL {job_id}: exit={proc.returncode} (will retry next day)")
            return

        # success -> mark state
        if policy_type == "twice_per_week_windows":
            mark_run_twice_per_week_windows(st)

        st["last_success_at"] = datetime.now().isoformat(timespec="seconds")
        save_json(state_path(job_id), st)
        log(f"OK   {job_id}")

    except Exception as e:
        log(f"FAIL {job_id}: exception={e} (will retry next day)")

def run_job_forced(job: dict):
    job_id = job["id"]
    cwd = job["cwd"]
    cmd = job["command"]
    args = job.get("args", [])

    st = load_json(state_path(job_id), {})

    log(f"FORCE {job_id}: {cmd} {' '.join(args)} (cwd={cwd})")
    try:
        proc = subprocess.run(
            [cmd, *args],
            cwd=cwd,
            text=True,
            capture_output=True
        )
        out = proc.stdout.strip()
        err = proc.stderr.strip()

        if out:
            log(f"OUT  {job_id}: {out}")
        if err:
            log(f"ERR  {job_id}: {err}")

        if proc.returncode != 0:
            log(f"FAIL {job_id}: exit={proc.returncode}")
            return

        # marca sucesso e registra horário
        st["last_forced_at"] = datetime.now().isoformat(timespec="seconds")
        st["last_success_at"] = datetime.now().isoformat(timespec="seconds")
        save_json(state_path(job_id), st)
        log(f"OK   {job_id} (forced)")

    except Exception as e:
        log(f"FAIL {job_id}: exception={e}")


def main():
    # Usage:
    #   run_jobs.py                -> run all scheduled
    #   run_jobs.py --force <id>   -> run one job immediately (ignore policy windows)
    force_id = None
    if len(sys.argv) >= 3 and sys.argv[1] == "--force":
        force_id = sys.argv[2]

    cfg = load_json(JOBS_FILE, {"jobs": []})
    jobs = cfg.get("jobs", [])
    if not jobs:
        log("No jobs configured.")
        return

    if force_id:
        found = False
        for job in jobs:
            if job.get("id") == force_id:
                found = True
                run_job_forced(job)
                break
        if not found:
            log(f"FAIL unknown job id: {force_id}")
        return

    for job in jobs:
        run_job(job)

if __name__ == "__main__":
    main()
