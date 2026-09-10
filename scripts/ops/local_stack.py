"""Run and supervise PonyChat's local chat, CosyVoice and search services."""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "var" / "local-stack"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
LOG = logging.getLogger("ponychat.local-stack")


def environment(component: str, *, database: str | None = None, port: int | None = None):
    from dotenv import dotenv_values

    env = os.environ.copy()
    for file in [ROOT / ".env", ROOT / ".env.local-stack"]:
        env.update({k: v for k, v in dotenv_values(file).items() if v is not None})
    env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", UVICORN_WORKERS="1")
    if component == "cosyvoice":
        env.update({k: v for k, v in dotenv_values(
            ROOT / "var" / "services" / "cosyvoice" / ".env").items() if v is not None})
        env["COSYVOICE_DATA_ROOT"] = str(ROOT / "var" / "services" / "cosyvoice")
    if database:
        env["PONYCHAT_DB_PATH"] = str(Path(database).resolve())
        env["PONYCHAT_BACKUP_DIR"] = str(Path(database).resolve().parent / "backups")
    if port is not None:
        env["PORT"] = str(port)
    return env


def command(component: str):
    if component == "chat":
        return [str(PYTHON), "-m", "Backend"]
    if component == "cosyvoice":
        return [str(PYTHON), "-m", "uvicorn", "app_cosyvoice:app", "--app-dir",
                str(ROOT / "PonyChat-Website" / "TTS"), "--host", "127.0.0.1", "--port", "18010"]
    if component == "search":
        return [str(ROOT / "var" / "services" / "searxng" / ".venv" / "Scripts" / "python.exe"),
                str(Path(__file__).with_name("local_search.py"))]
    raise ValueError(component)


def healthy(url: str) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def stop_process(process: subprocess.Popen):
    """Terminate only a child owned by this supervisor, including SDK descendants."""
    import psutil

    if process.poll() is not None:
        return
    try:
        parent = psutil.Process(process.pid)
        descendants = parent.children(recursive=True)
        parent.terminate()
        _, remaining = psutil.wait_procs([parent, *descendants], timeout=8)
        for child in remaining:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass


def supervise():
    STATE.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=STATE / "supervisor.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if not (STATE / "migration.ready").exists():
        LOG.error("Migration is not marked ready; refusing to start the production database")
        return 2
    # A process-lifetime localhost socket prevents duplicate supervisors.
    singleton = socket.socket()
    try:
        singleton.bind(("127.0.0.1", 18690))
    except OSError:
        LOG.info("Local stack supervisor already running")
        return 0
    singleton.listen(1)
    stop_file = STATE / "stop.request"
    stop_file.unlink(missing_ok=True)
    children = {}
    output_handles = []
    temporary_keys = []
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    sys.path.insert(0, str(ROOT.parent / "ServerKeys"))
    import ssh_lib

    try:
        specs = {name: (command(name), environment(name)) for name in ("search", "cosyvoice", "chat")}
        for host, forwards in [
            ("usa", ["127.0.0.1:5000:127.0.0.1:5000", "127.0.0.1:18010:127.0.0.1:18010"]),
            ("yuelimei", ["127.0.0.1:18500:127.0.0.1:5000"]),
        ]:
            entry = ssh_lib.load_server(host)
            key, temporary = ssh_lib.prepare_ssh_key(entry.key)
            temporary_keys.append(temporary)
            tunnel = ssh_lib._ssh_base(key, entry.port) + ["-o", "ExitOnForwardFailure=yes", "-n", "-N"]
            for forward in forwards:
                tunnel += ["-R", forward]
            specs["tunnel-" + host] = (tunnel + [entry.target], ssh_lib.deploy_upload_env())
        next_start = {name: 0.0 for name in specs}
        failures = {name: 0 for name in ("chat", "cosyvoice", "search")}
        urls = {"chat": "http://127.0.0.1:5000/api/health",
                "cosyvoice": "http://127.0.0.1:18010/cosyvoice/health",
                "search": "http://127.0.0.1:18786/healthz"}
        started_at = {}
        last_health = 0.0
        LOG.info("Starting local stack root=%s", ROOT)
        while not stopping and not stop_file.exists():
            now = time.monotonic()
            for name, (args, env) in specs.items():
                if name.startswith("tunnel-") and not (STATE / "production.enabled").exists():
                    continue
                process = children.get(name)
                if process and process.poll() is not None:
                    LOG.warning("%s exited code=%s", name, process.returncode)
                    children.pop(name)
                    next_start[name] = now + 5
                    process = None
                if process is None and now >= next_start[name]:
                    out = (STATE / (name + ".stdout.log")).open("ab", buffering=0)
                    err = (STATE / (name + ".stderr.log")).open("ab", buffering=0)
                    output_handles.extend([out, err])
                    children[name] = subprocess.Popen(args, cwd=ROOT, env=env,
                        stdin=subprocess.DEVNULL, stdout=out, stderr=err, creationflags=FLAGS)
                    started_at[name] = now
                    LOG.info("Started %s pid=%s", name, children[name].pid)
            if now - last_health >= 20:
                last_health = now
                for name, url in urls.items():
                    if now - started_at.get(name, now) < 90:
                        continue
                    failures[name] = 0 if healthy(url) else failures[name] + 1
                    if failures[name] >= 3 and name in children:
                        LOG.error("%s failed three health checks; restarting owned process", name)
                        stop_process(children[name])
                        failures[name] = 0
                status = {name: {"pid": p.pid, "running": p.poll() is None} for name, p in children.items()}
                status.update(supervisor_pid=os.getpid(), root=str(ROOT), updated_at=time.time())
                pending = STATE / "status.json.tmp"
                pending.write_text(json.dumps(status, indent=2), encoding="utf-8")
                pending.replace(STATE / "status.json")
            time.sleep(2)
    finally:
        LOG.info("Stopping local stack")
        for process in reversed(list(children.values())):
            stop_process(process)
        for handle in output_handles:
            handle.close()
        for temporary in temporary_keys:
            ssh_lib.cleanup_temp_key(temporary)
        singleton.close()
        stop_file.unlink(missing_ok=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["supervise", "stop", "run"])
    parser.add_argument("--component", choices=["chat", "cosyvoice", "search"], default="chat")
    parser.add_argument("--database")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.action == "stop":
        STATE.mkdir(parents=True, exist_ok=True)
        (STATE / "stop.request").touch()
        return 0
    if args.action == "run":
        return subprocess.call(command(args.component), cwd=ROOT,
            env=environment(args.component, database=args.database, port=args.port))
    return supervise()


if __name__ == "__main__":
    raise SystemExit(main())
