"""Restart the local production Backend with a committed, scoped rollback set."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

import httpx
import psutil


ROOT = Path(__file__).resolve().parents[2]
MODEL_CONFIG_FILES = {"Backend/conf/model_config.json", "Backend/conf/models/deepseek.json",
                      "Backend/conf/models/local.json"}


def _normalized_hash(content: bytes) -> str:
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def _restart() -> int:
    status = json.loads((ROOT / "var/local-stack/status.json").read_text(encoding="utf-8"))
    parent = psutil.Process(status["chat"]["pid"])
    assert parent.cmdline()[-2:] == ["-m", "Backend"]
    assert Path(parent.cwd()).resolve() == ROOT.resolve()
    assert psutil.Process(status["supervisor_pid"]).is_running()
    children = parent.children(recursive=True)
    for child in reversed(children):
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    parent.terminate()
    _, remaining = psutil.wait_procs([parent, *children], timeout=5)
    assert not remaining, "Old backend processes did not stop"
    return parent.pid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--expected-deploy-token", required=True)
    parser.add_argument("--rollback-source", type=Path,
                        help="Pre-edit source snapshot; every scoped file must match the live marker hash.")
    parser.add_argument("--release-prefix", default="local-mouth-speech")
    parser.add_argument("--allow-unverified-rollback", action="store_true",
                        help="Proceed when an old marker hash has no recoverable source snapshot.")
    args = parser.parse_args()
    names = json.loads(args.manifest.read_text(encoding="utf-8"))
    assert isinstance(names, list) and names and len(names) == len(set(names))
    assert all(isinstance(name, str) and name.startswith("Backend/")
               and (name.endswith((".py", ".mjs")) or name in MODEL_CONFIG_FILES) for name in names)
    for args_for_diff in (("diff", "--name-only", "--"), ("diff", "--cached", "--name-only", "--")):
        dirty = subprocess.check_output(["git", *args_for_diff, *names], cwd=ROOT).decode().splitlines()
        assert not dirty, "Scoped runtime files have uncommitted changes: " + ", ".join(dirty)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    marker = ROOT / "Backend/.deploy_revision"
    previous = json.loads(marker.read_text(encoding="utf-8"))
    assert previous["deploy_token"] == args.expected_deploy_token, "Live release changed"
    previous_revision = previous["git_commit"]
    assert args.release_prefix and all(c.isascii() and (c.isalnum() or c == "-") for c in args.release_prefix)
    release = args.release_prefix + "-" + time.strftime("%Y%m%d-%H%M%S") + "-" + revision[:8]
    backup = ROOT / "var/local-stack/releases" / release
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(marker, backup / "deploy_revision.json")
    old = {}
    unverified_rollback = []
    new_files = []
    for name in names:
        current = (ROOT / name).read_bytes()
        committed = subprocess.check_output(["git", "show", revision + ":" + name], cwd=ROOT)
        assert _normalized_hash(current) == _normalized_hash(committed), name
        expected_hash = previous.get("files", {}).get(name)
        prior_exists = subprocess.run(['git', 'cat-file', '-e', previous_revision + ':' + name],
                                      cwd=ROOT, capture_output=True).returncode == 0
        if not expected_hash and not prior_exists:
            assert (ROOT / name).resolve().is_relative_to(ROOT.resolve())
            new_files.append(name)
            compile(current, name, 'exec') if name.endswith('.py') else None
            continue
        if not expected_hash and name in MODEL_CONFIG_FILES:
            prior_config = subprocess.check_output(["git", "show", previous_revision + ":" + name], cwd=ROOT)
            snapshot = (args.rollback_source / name).read_bytes() if args.rollback_source else prior_config
            assert _normalized_hash(snapshot) == _normalized_hash(prior_config), name
            expected_hash = hashlib.sha256(snapshot).hexdigest()
        if args.rollback_source:
            previous_bytes = (args.rollback_source / name).read_bytes()
            assert args.allow_unverified_rollback or (
                expected_hash and hashlib.sha256(previous_bytes).hexdigest() == expected_hash), name
        else:
            previous_bytes = subprocess.check_output(["git", "show", previous_revision + ":" + name], cwd=ROOT)
        verified = bool(expected_hash) and hashlib.sha256(previous_bytes).hexdigest() == expected_hash
        if not verified:
            assert args.allow_unverified_rollback, name
            unverified_rollback.append(name)
            # Preserve the supplied/previous committed rollback source, never
            # replace it with the candidate we are about to deploy. A missing
            # byte-for-byte match remains explicit in the deployment receipt.
        target = backup / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(previous_bytes)
        old[name] = expected_hash
        compile(current, name, "exec") if name.endswith(".py") else None
        if name in MODEL_CONFIG_FILES:
            json.loads(current)
    with sqlite3.connect((ROOT / "Backend/database/ponychat.db").as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(backup / "ponychat.db") as target:
            source.backup(target)
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    all_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                  for name in subprocess.check_output(["git", "ls-files", "Backend"], cwd=ROOT).decode().splitlines()
                  if (name.endswith((".py", ".mjs")) or name in MODEL_CONFIG_FILES) and (ROOT / name).is_file()}
    try:
        marker.write_text(json.dumps({**previous, "deploy_token": release, "git_commit": revision,
                                      "files": all_hashes}, indent=2), encoding="utf-8")
        previous_pid = _restart()
        with httpx.Client(trust_env=False, timeout=15) as client:
            for _ in range(45):
                try:
                    if client.get("http://127.0.0.1:5000/api/health").json().get("deploy_token") == release:
                        break
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(2)
            else:
                raise RuntimeError("Backend did not become healthy")
            health = {}
            for name, base in (("local", "http://127.0.0.1:5000"), ("cn", "https://39.101.74.217"),
                               ("official", "https://www.ponychat.org")):
                response = client.get(base + "/api/health")
                response.raise_for_status()
                health[name] = response.json()
                assert health[name].get("deploy_token") == release
        receipt = {"passed": True, "target": "Windows P:/PonyChat; CN and USA forwarding",
                   "release": release, "revision": revision, "previous_token": previous["deploy_token"],
                   "previous_pid": previous_pid, "backup": str(backup), "hashes": hashes,
                   "unverified_rollback_files": unverified_rollback, "new_files": new_files, "health": health}
        args.report.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
    except BaseException:
        for name in names:
            if name in new_files:
                target = (ROOT / name).resolve()
                assert target.is_relative_to(ROOT.resolve())
                target.unlink(missing_ok=True)
            else:
                shutil.copy2(backup / name, ROOT / name)
        shutil.copy2(backup / "deploy_revision.json", marker)
        _restart()
        raise


if __name__ == "__main__":
    main()
