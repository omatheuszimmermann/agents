#!/usr/bin/env python3
import argparse
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEMPLATES_DIR = os.path.join(REPO_ROOT, "runner", "launchd")
LAUNCH_AGENTS_DIR = os.path.expanduser("~/Library/LaunchAgents")


def _run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def run_launchctl(cmd: List[str]) -> bool:
    proc = _run(cmd, check=False)
    if proc.returncode != 0:
        print(f"Erro ao executar: {' '.join(cmd)}")
        if proc.stderr.strip():
            print(proc.stderr.strip())
        elif proc.stdout.strip():
            print(proc.stdout.strip())
        return False
    return True


def ensure_launch_agents_dir() -> None:
    os.makedirs(LAUNCH_AGENTS_DIR, exist_ok=True)


def load_plist(path: str) -> Dict:
    with open(path, "rb") as f:
        return plistlib.load(f)


def save_plist(path: str, data: Dict) -> None:
    with open(path, "wb") as f:
        plistlib.dump(data, f, fmt=plistlib.FMT_XML, sort_keys=False)


def list_plists(dir_path: str) -> List[str]:
    if not os.path.isdir(dir_path):
        return []
    return sorted([f for f in os.listdir(dir_path) if f.endswith(".plist")])


def launchctl_labels() -> List[str]:
    try:
        proc = _run(["launchctl", "list"], check=False)
    except FileNotFoundError:
        return []
    labels: List[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("PID"):
            continue
        parts = line.split()
        if len(parts) >= 3:
            labels.append(parts[2])
    return labels


def parse_schedule(plist: Dict) -> Tuple[str, str]:
    if "StartCalendarInterval" in plist:
        sci = plist["StartCalendarInterval"]
        if isinstance(sci, list):
            times = []
            for item in sci:
                h = item.get("Hour")
                m = item.get("Minute")
                if h is not None and m is not None:
                    times.append(f"{int(h):02d}:{int(m):02d}")
            if times:
                return "calendar", ", ".join(times)
            return "calendar", ""
        if isinstance(sci, dict):
            h = sci.get("Hour")
            m = sci.get("Minute")
            if h is not None and m is not None:
                return "calendar", f"{int(h):02d}:{int(m):02d}"
            return "calendar", ""
    if "StartInterval" in plist:
        try:
            seconds = int(plist["StartInterval"])
            return "interval", str(seconds)
        except Exception:
            return "interval", ""
    return "none", ""


def format_schedule(plist: Dict) -> str:
    schedule_type, schedule_value = parse_schedule(plist)
    if schedule_type == "calendar":
        if schedule_value:
            return f"calendar: {schedule_value}"
        return "calendar: custom"
    if schedule_type == "interval":
        if schedule_value:
            return f"interval: {schedule_value}s"
        return "interval: custom"
    return "no schedule"


def bool_str(value: Optional[bool]) -> str:
    if value is None:
        return "-"
    return "yes" if value else "no"


def program_args_to_text(args) -> str:
    if isinstance(args, list):
        return shlex.join([str(item) for item in args])
    if isinstance(args, str):
        return args
    return ""


def parse_program_args(text: str) -> List[str]:
    return shlex.split(text) if text else []


def build_job_entry(plist_path: str, loaded_labels: Optional[set] = None) -> Dict:
    filename = os.path.basename(plist_path)
    try:
        data = load_plist(plist_path)
    except Exception:
        data = {}

    label = data.get("Label", os.path.splitext(filename)[0])
    schedule_type, schedule_value = parse_schedule(data)
    run_at_load = data.get("RunAtLoad")
    keep_alive = data.get("KeepAlive")

    entry = {
        "id": label,
        "label": label,
        "filename": filename,
        "path": plist_path,
        "loaded": label in loaded_labels if loaded_labels is not None else False,
        "scheduleType": schedule_type,
        "scheduleValue": schedule_value,
        "schedule": format_schedule(data),
        "runAtLoad": run_at_load,
        "keepAlive": bool(keep_alive) if keep_alive is not None else False,
        "programArgs": program_args_to_text(data.get("ProgramArguments", [])),
        "stdoutPath": data.get("StandardOutPath", ""),
        "stderrPath": data.get("StandardErrorPath", ""),
        "has_template": os.path.isfile(os.path.join(TEMPLATES_DIR, filename)),
    }
    return entry


def build_installed_jobs() -> List[Dict]:
    installed = []
    loaded_labels = set(launchctl_labels())
    for filename in list_plists(LAUNCH_AGENTS_DIR):
        plist_path = os.path.join(LAUNCH_AGENTS_DIR, filename)
        installed.append(build_job_entry(plist_path, loaded_labels))
    return installed


def find_job(target: str, jobs: Optional[List[Dict]] = None) -> Optional[Dict]:
    if jobs is None:
        jobs = build_installed_jobs()
    for item in jobs:
        if item["label"] == target or item["filename"] == target or item["path"] == target:
            return item
    return None


def print_jobs(jobs: List[Dict], only_loaded: bool = False) -> None:
    rows = [job for job in jobs if (job["loaded"] or not only_loaded)]
    if not rows:
        print("Nenhum job encontrado.")
        return

    label_w = max(len(job["label"]) for job in rows)
    sched_w = max(len(job["schedule"]) for job in rows)
    print("#  Label".ljust(4 + label_w) + "  Loaded  RunAtLoad  Schedule".ljust(2 + sched_w + 21) + "  File")
    for idx, job in enumerate(rows, start=1):
        label = job["label"].ljust(label_w)
        loaded = "yes" if job["loaded"] else "no"
    run_at_load = bool_str(job["runAtLoad"]).ljust(9)
        schedule = job["schedule"].ljust(sched_w)
        print(f"{str(idx).rjust(2)}  {label}  {loaded.ljust(6)}  {run_at_load}  {schedule}  {job['filename']}")


def choose_index(max_index: int, prompt: str) -> Optional[int]:
    while True:
        raw = input(prompt).strip()
        if raw == "":
            return None
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= max_index:
                return idx - 1
        print("Opcao invalida. Digite o numero ou pressione Enter para cancelar.")


def launchctl_reload(plist_path: str) -> bool:
    run_launchctl(["launchctl", "unload", plist_path])
    return run_launchctl(["launchctl", "load", plist_path])


def launchctl_unload(plist_path: str) -> bool:
    return run_launchctl(["launchctl", "unload", plist_path])


def edit_schedule(plist_path: str, template_path: Optional[str]) -> None:
    data = load_plist(plist_path)
    print(f"Arquivo: {plist_path}")
    print(f"Label: {data.get('Label', '-')}")
    print(f"Schedule atual: {format_schedule(data)}")

    current_type, current_value = parse_schedule(data)

    default_choice = {"calendar": "1", "interval": "2", "none": "3"}.get(current_type, "1")

    print("\nEscolha o tipo de agendamento:")
    print("1. Diario (StartCalendarInterval)\n2. Intervalo em segundos (StartInterval)\n3. Sem agendamento")
    choice = input(f"Opcao [1/2/3] (default {default_choice}): ").strip() or default_choice

    if choice == "1":
        while True:
            prompt = "Hora (HH:MM)"
            if current_type == "calendar" and current_value:
                prompt += f" [{current_value}]"
            time_raw = input(f"{prompt}: ").strip()
            if time_raw == "" and current_type == "calendar" and current_value:
                time_raw = current_value
            if ":" in time_raw:
                h_str, m_str = time_raw.split(":", 1)
                if h_str.isdigit() and m_str.isdigit():
                    h = int(h_str)
                    m = int(m_str)
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        data.pop("StartInterval", None)
                        data["StartCalendarInterval"] = {"Hour": h, "Minute": m}
                        break
            print("Horario invalido. Use HH:MM (00-23:00-59).")
    elif choice == "2":
        while True:
            prompt = "Intervalo em segundos"
            if current_type == "interval" and current_value:
                prompt += f" [{current_value}]"
            sec_raw = input(f"{prompt}: ").strip()
            if sec_raw == "" and current_type == "interval" and current_value:
                sec_raw = current_value
            if sec_raw.isdigit() and int(sec_raw) > 0:
                data.pop("StartCalendarInterval", None)
                data["StartInterval"] = int(sec_raw)
                break
            print("Intervalo invalido.")
    else:
        data.pop("StartCalendarInterval", None)
        data.pop("StartInterval", None)

    run_at_load_raw = input("RunAtLoad? (s/N): ").strip().lower()
    if run_at_load_raw in {"s", "y", "yes"}:
        data["RunAtLoad"] = True
    elif run_at_load_raw in {"n", "no"}:
        data["RunAtLoad"] = False

    save_plist(plist_path, data)
    if template_path and os.path.isfile(template_path):
        save_plist(template_path, data)
        print(f"Template atualizado: {template_path}")

    launchctl_reload(plist_path)
    print("Job recarregado com novo agendamento.")


def uninstall_job(plist_path: str) -> None:
    launchctl_unload(plist_path)
    os.remove(plist_path)


def install_from_template(template_path: str) -> str:
    ensure_launch_agents_dir()
    dest_path = os.path.join(LAUNCH_AGENTS_DIR, os.path.basename(template_path))
    shutil.copy2(template_path, dest_path)
    launchctl_reload(dest_path)
    return dest_path


def build_new_plist(label: str, program_args: List[str], schedule_type: str, schedule_value: Optional[str],
                    run_at_load: bool, keep_alive: bool, stdout_path: str, stderr_path: str) -> Dict:
    data: Dict = {
        "Label": label,
        "ProgramArguments": program_args,
        "RunAtLoad": run_at_load,
        "StandardOutPath": stdout_path,
        "StandardErrorPath": stderr_path,
    }
    if keep_alive:
        data["KeepAlive"] = True
    if schedule_type == "calendar":
        h, m = schedule_value.split(":", 1)
        data["StartCalendarInterval"] = {"Hour": int(h), "Minute": int(m)}
    elif schedule_type == "interval":
        data["StartInterval"] = int(schedule_value)
    return data


def create_new_job_interactive() -> None:
    ensure_launch_agents_dir()

    label = input("Label do job (ex: ai.meu.job): ").strip()
    if not label:
        print("Label obrigatorio.")
        return

    args_raw = input("ProgramArguments (ex: /usr/bin/python3 /path/script.py arg1): ").strip()
    if not args_raw:
        print("ProgramArguments obrigatorio.")
        return
    program_args = shlex.split(args_raw)

    print("\nTipo de agendamento:")
    print("1. Diario (HH:MM)\n2. Intervalo em segundos\n3. Sem agendamento")
    sched_choice = input("Opcao [1/2/3]: ").strip() or "1"

    schedule_type = "none"
    schedule_value = None
    if sched_choice == "1":
        while True:
            time_raw = input("Hora (HH:MM): ").strip()
            if ":" in time_raw:
                h_str, m_str = time_raw.split(":", 1)
                if h_str.isdigit() and m_str.isdigit():
                    h = int(h_str)
                    m = int(m_str)
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        schedule_type = "calendar"
                        schedule_value = f"{h:02d}:{m:02d}"
                        break
            print("Horario invalido. Use HH:MM (00-23:00-59).")
    elif sched_choice == "2":
        while True:
            sec_raw = input("Intervalo em segundos: ").strip()
            if sec_raw.isdigit() and int(sec_raw) > 0:
                schedule_type = "interval"
                schedule_value = sec_raw
                break
            print("Intervalo invalido.")

    run_at_load = input("RunAtLoad? (s/N): ").strip().lower() in {"s", "y", "yes"}
    keep_alive = input("KeepAlive? (s/N): ").strip().lower() in {"s", "y", "yes"}

    logs_dir = os.path.join(REPO_ROOT, "runner", "logs")
    default_out = os.path.join(logs_dir, f"{label}.out")
    default_err = os.path.join(logs_dir, f"{label}.err")

    stdout_path = input(f"StandardOutPath [{default_out}]: ").strip() or default_out
    stderr_path = input(f"StandardErrorPath [{default_err}]: ").strip() or default_err

    data = build_new_plist(
        label=label,
        program_args=program_args,
        schedule_type=schedule_type,
        schedule_value=schedule_value,
        run_at_load=run_at_load,
        keep_alive=keep_alive,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )

    template_path = os.path.join(TEMPLATES_DIR, f"{label}.plist")
    save_plist(template_path, data)
    dest_path = os.path.join(LAUNCH_AGENTS_DIR, f"{label}.plist")
    save_plist(dest_path, data)
    launchctl_reload(dest_path)

    print(f"Job criado e instalado: {dest_path}")


def interactive() -> None:
    while True:
        print("\nJobs instalados em LaunchAgents:")
        jobs = build_installed_jobs()
        print_jobs(jobs)

        print("\nAcoes:")
        print("1. Inserir novo job\n2. Editar agendamento\n3. Excluir job\n4. Instalar template\n5. Sair")
        choice = input("Opcao: ").strip()

        if choice == "1":
            create_new_job_interactive()
            continue
        if choice == "2":
            if not jobs:
                print("Nenhum job para editar.")
                continue
            idx = choose_index(len(jobs), "Numero do job para editar (Enter para cancelar): ")
            if idx is None:
                continue
            job = jobs[idx]
            template_path = os.path.join(TEMPLATES_DIR, job["filename"]) if job["has_template"] else None
            edit_schedule(job["path"], template_path)
            continue
        if choice == "3":
            if not jobs:
                print("Nenhum job para excluir.")
                continue
            idx = choose_index(len(jobs), "Numero do job para excluir (Enter para cancelar): ")
            if idx is None:
                continue
            job = jobs[idx]
            confirm = input(f"Excluir {job['label']}? (s/N): ").strip().lower()
            if confirm in {"s", "y", "yes"}:
                uninstall_job(job["path"])
                print("Job removido.")
            continue
        if choice == "4":
            templates = list_plists(TEMPLATES_DIR)
            if not templates:
                print("Nenhum template encontrado em runner/launchd.")
                continue
            for i, name in enumerate(templates, start=1):
                print(f"{i}. {name}")
            idx = choose_index(len(templates), "Numero do template para instalar (Enter para cancelar): ")
            if idx is None:
                continue
            template_path = os.path.join(TEMPLATES_DIR, templates[idx])
            dest_path = install_from_template(template_path)
            print(f"Template instalado: {dest_path}")
            continue
        if choice == "5":
            return
        print("Opcao invalida.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerenciador de jobs launchd (LaunchAgents).")
    parser.add_argument("--list", action="store_true", help="Lista jobs instalados")
    parser.add_argument("--list-active", action="store_true", help="Lista apenas jobs ativos (loaded)")
    parser.add_argument("--install", metavar="PLIST", help="Instala um template (caminho para .plist)")
    parser.add_argument("--uninstall", metavar="LABEL_OR_FILE", help="Remove job por label ou arquivo")
    parser.add_argument("--edit", metavar="LABEL_OR_FILE", help="Edita agendamento por label ou arquivo")

    args = parser.parse_args()

    if args.list or args.list_active:
        jobs = build_installed_jobs()
        print_jobs(jobs, only_loaded=args.list_active)
        return

    if args.install:
        template_path = os.path.abspath(args.install)
        if not os.path.isfile(template_path):
            print("Arquivo .plist nao encontrado.")
            sys.exit(1)
        dest_path = install_from_template(template_path)
        print(f"Instalado: {dest_path}")
        return

    if args.uninstall:
        jobs = build_installed_jobs()
        target = args.uninstall
        job = find_job(target, jobs)
        if not job:
            print("Job nao encontrado.")
            sys.exit(1)
        uninstall_job(job["path"])
        print("Job removido.")
        return

    if args.edit:
        jobs = build_installed_jobs()
        target = args.edit
        job = find_job(target, jobs)
        if not job:
            print("Job nao encontrado.")
            sys.exit(1)
        template_path = os.path.join(TEMPLATES_DIR, job["filename"]) if job["has_template"] else None
        edit_schedule(job["path"], template_path)
        return

    interactive()


if __name__ == "__main__":
    main()
