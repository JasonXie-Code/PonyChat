"""Shared, non-destructive entry points for the three repository-root launchers."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path("P:/Tools")
STATE = ROOT / "var" / "local-stack"
SERVICES = {
    "chat": "http://127.0.0.1:5000/api/health",
    "cosyvoice": "http://127.0.0.1:18010/cosyvoice/health",
    "search": "http://127.0.0.1:18786/healthz",
}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def require(path: Path) -> Path:
    if not path.is_file():
        raise RuntimeError(f"Required file is missing: {path}")
    return path


def python_executable() -> Path:
    for candidate in (ROOT / ".venv/Scripts/python.exe", TOOLS / "python/python.exe"):
        if candidate.is_file():
            return candidate
    raise RuntimeError("Python is missing: .venv/Scripts/python.exe or P:/Tools/python/python.exe")


def android_sdk(required: str) -> Path:
    candidates = [TOOLS / "android-sdk"]
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]))
    properties = ROOT / "Android-App/local.properties"
    if properties.is_file():
        for line in properties.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("sdk.dir="):
                value = line.split("=", 1)[1].strip().replace("\\:", ":").replace("\\\\", "\\")
                candidates.append(Path(value))
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk")
    candidates.append(ROOT / "misc/tools/android-sdk")
    for candidate in candidates:
        if (candidate / required).is_file():
            return candidate
    raise RuntimeError(f"Android SDK containing {required} was not found")


def healthy(url: str) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def supervisor_running() -> bool:
    import psutil

    try:
        status = json.loads((STATE / "status.json").read_text(encoding="utf-8"))
        process = psutil.Process(int(status["supervisor_pid"]))
        command = process.cmdline()
        expected = str(ROOT / "scripts/ops/local_stack.py")
        return any(os.path.normcase(arg) == os.path.normcase(expected) for arg in command)
    except (OSError, ValueError, KeyError, TypeError):
        return False
    except psutil.Error:
        return False


def stack_status() -> bool:
    running = supervisor_running()
    print(f"Supervisor: {'running' if running else 'not running'}")
    ready = running
    for name, url in SERVICES.items():
        ok = healthy(url)
        print(f"{name}: {'healthy' if ok else 'not ready'}  {url}")
        ready = ready and ok
    try:
        status = json.loads((STATE / "status.json").read_text(encoding="utf-8"))
        if running and time.time() - status.get("updated_at", 0) < 60:
            for name in ("tunnel-usa", "tunnel-yuelimei"):
                item = status.get(name, {})
                print(f"{name}: last reported {'running' if item.get('running') else 'inactive'}")
    except (OSError, ValueError, TypeError):
        pass
    print(f"Logs: {STATE}")
    return ready


def backend(args) -> int:
    if args.status:
        return 0 if stack_status() else 1
    pythonw = require(ROOT / ".venv/Scripts/pythonw.exe")
    supervisor = require(ROOT / "scripts/ops/local_stack.py")
    for path in (ROOT / ".env.local-stack", STATE / "migration.ready",
                 ROOT / "var/services/searxng/.venv/Scripts/python.exe",
                 ROOT.parent / "ServerKeys/ssh_lib.py"):
        require(path)
    print(f"Backend: {supervisor}")
    print(f"Python: {pythonw}")
    if args.check:
        print("[OK] Local stack prerequisites are present.")
        return 0
    local_llm = ROOT / "LocalLLM/scripts/manage.py"
    model_manifest = ROOT / "Backend/conf/model_config.json"
    local_selected = (model_manifest.is_file() and
        json.loads(model_manifest.read_text(encoding="utf-8-sig")).get("active_model") == "qwen3.5-4b-local")
    if local_selected and local_llm.is_file() and (ROOT / "LocalLLM/server/bin/llama-server.exe").is_file():
        subprocess.run([str(python_executable()), str(local_llm), "start"], cwd=ROOT, check=True)
    if supervisor_running():
        print("Local stack is already running; checking health.")
        return 0 if stack_status() else 1
    child = subprocess.Popen([str(pythonw), str(supervisor), "supervise"], cwd=ROOT,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if supervisor_running() and all(healthy(url) for url in SERVICES.values()):
            return 0 if stack_status() else 1
        if child.poll() is not None and not supervisor_running():
            print(f"[X] Supervisor exited with code {child.returncode}.")
            break
        time.sleep(1)
    stack_status()
    print(f"[X] Startup is not ready. Inspect {STATE / 'supervisor.log'}")
    return 1


def app(args) -> int:
    interpreter = python_executable()
    script = require(ROOT / "Backend/scripts/launch/AAA_install_debug_app.py")
    sdk = android_sdk("platform-tools/adb.exe")
    jdk_candidates = [TOOLS / "jdk-17", ROOT / "misc/tools/jdk-17"]
    if os.environ.get("JAVA_HOME"):
        jdk_candidates.append(Path(os.environ["JAVA_HOME"]))
    jdk = next((path for path in jdk_candidates if (path / "bin/java.exe").is_file()), None)
    print(f"Python: {interpreter}")
    print(f"Android SDK: {sdk}")
    print(f"Java: {jdk or 'missing (building APKs will require a JDK)'}")
    if args.check:
        return 0 if jdk else 1
    env = os.environ.copy()
    env.update(ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk), PYTHONUTF8="1")
    if jdk:
        env["JAVA_HOME"] = str(jdk)
    if (TOOLS / "gradle-home").is_dir():
        env.setdefault("GRADLE_USER_HOME", str(TOOLS / "gradle-home"))
    return subprocess.call([str(interpreter), str(script)], cwd=ROOT, env=env)


def capture(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, timeout=15,
                            creationflags=NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Command failed: {command[0]}")
    return result.stdout


def running_avd(adb: Path, avd: str) -> str | None:
    for line in capture([str(adb), "devices"]).splitlines()[1:]:
        fields = line.split()
        if len(fields) < 2 or not fields[0].startswith("emulator-"):
            continue
        if fields[1] != "device":
            raise RuntimeError(f"{fields[0]} is {fields[1]}; wait for it before starting another emulator")
        name = capture([str(adb), "-s", fields[0], "emu", "avd", "name"]).splitlines()
        if name and name[0].strip() == avd:
            return fields[0]
    return None


def emulator(args) -> int:
    sdk = android_sdk("emulator/emulator.exe")
    executable = sdk / "emulator/emulator.exe"
    adb = require(sdk / "platform-tools/adb.exe")
    avds = capture([str(executable), "-list-avds"]).splitlines()
    if args.avd not in avds:
        raise RuntimeError(f"AVD {args.avd!r} is missing. Available: {', '.join(avds) or '(none)'}")
    print(f"Android SDK: {sdk}")
    print(f"AVD: {args.avd}")
    if args.check:
        print("[OK] Emulator and AVD are present.")
        return 0
    existing = running_avd(adb, args.avd)
    if existing:
        print(f"[OK] {args.avd} is already running on {existing}.")
        return 0
    log_dir = ROOT / "var/emulator"
    log_dir.mkdir(parents=True, exist_ok=True)
    command = [str(executable), "-avd", args.avd, "-no-snapshot-load", "-no-snapshot-save",
               "-no-boot-anim", "-cores", str(args.cores), "-memory", str(args.memory),
               "-gpu", args.gpu, "-netfast", "-cache-size", "512", "-accel", "on"]
    if args.gpu == "host":
        command.append("-use-host-vulkan")
    env = os.environ.copy()
    env.update(ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk))
    with (log_dir / "stdout.log").open("ab") as out, (log_dir / "stderr.log").open("ab") as err:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=err,
                                 creationflags=NO_WINDOW | getattr(subprocess, "HIGH_PRIORITY_CLASS", 0))
    try:
        code = child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        print(f"[OK] Emulator process started (PID {child.pid}); Android is still booting.")
        print(f"Logs: {log_dir}")
        return 0
    raise RuntimeError(f"Emulator exited during startup with code {code}. See {log_dir}")


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    targets = parser.add_subparsers(dest="target", required=True)
    for name, handler in (("backend", backend), ("app", app), ("emulator", emulator)):
        target = targets.add_parser(name)
        target.set_defaults(handler=handler)
        if name == "backend":
            mode = target.add_mutually_exclusive_group()
            mode.add_argument("--check", action="store_true", help="check local prerequisites without starting")
            mode.add_argument("--status", action="store_true", help="check running services without starting")
        else:
            target.add_argument("--check", action="store_true", help="check prerequisites without starting")
        if name == "emulator":
            target.add_argument("--avd", default="Medium_Phone_API_36.1")
            target.add_argument("--cores", type=positive, default=min(16, os.cpu_count() or 4))
            target.add_argument("--memory", type=positive, default=16384, help="RAM in MB")
            target.add_argument("--gpu", choices=("auto", "host", "swiftshader", "swiftshader_indirect"),
                                default="swiftshader_indirect",
                                help="graphics renderer; software is the compatible default")
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"[X] {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
