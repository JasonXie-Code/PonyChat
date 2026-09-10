"""SSH transport for the explicitly scoped Server-USA to local migration.

Archives and credentials belong under ignored var/, never in tracked reports.
Remote file removal is deliberately not implemented by this transport.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "var" / "migration-20260909"
sys.path.insert(0, str(ROOT.parent / "ServerKeys"))
import ssh_lib  # noqa: E402


def ssh_run(script: str, *, output: Path | None = None, timeout: int = 600, host: str = "usa"):
    """Run a Bash stdin script; binary output can be streamed directly to disk."""
    entry = ssh_lib.load_server(host)
    key, temporary_key = ssh_lib.prepare_ssh_key(entry.key)
    args = ssh_lib._ssh_base(key, entry.port) + [entry.target, "bash", "-s"]
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
    handle = output.open("wb") if output else None
    try:
        result = subprocess.run(
            args, input=script.encode("utf-8"),
            stdout=handle or subprocess.PIPE, stderr=subprocess.PIPE,
            env=ssh_lib.deploy_upload_env(), timeout=timeout,
        )
        if result.returncode:
            raise RuntimeError(
                f"SSH exit {result.returncode}: "
                + result.stderr.decode("utf-8", errors="replace")[-2000:]
            )
        return result.stdout
    finally:
        if handle:
            handle.close()
        ssh_lib.cleanup_temp_key(temporary_key)


def download(name: str, paths: list[str], excludes: list[str]) -> Path:
    """Fetch only explicit root-relative paths; ignore archive links on extraction."""
    if not paths or any(p.startswith("/") or ".." in PurePosixPath(p).parts for p in paths):
        raise ValueError("Expected explicit paths relative to remote /")
    archive = STATE / (name + ".tar.gz")
    partial = archive.with_suffix(archive.suffix + ".part")
    args = ["tar", "--ignore-failed-read", "-C", "/"]
    args += ["--exclude=" + pattern for pattern in excludes]
    args += ["-cf", "-", "--", *paths]
    command = "set -o pipefail\n" + shlex.join(args) + " | gzip -1\n"
    started = time.monotonic()
    ssh_run(command, output=partial, timeout=7200)
    partial.replace(archive)
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size,
                      "seconds": round(time.monotonic() - started, 1)}), flush=True)
    return archive


def extract(archive: Path, destination: Path):
    """Extract regular files with path validation; do not execute archived content."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    files = 0
    with tarfile.open(archive, "r|gz") as package:
        for member in package:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError(f"Unsafe archive member: {member.name}")
            target = destination.joinpath(*name.parts).resolve()
            if not target.is_relative_to(destination):
                raise ValueError(f"Archive escapes destination: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.extractfile(member) as source, target.open("wb") as out:
                    shutil.copyfileobj(source, out, 1024 * 1024)
                os.utime(target, (member.mtime, member.mtime))
                files += 1
            elif not (member.issym() or member.islnk()):
                raise ValueError(f"Unexpected archive member type: {member.name}")
    print(json.dumps({"extracted": str(destination), "files": files}), flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--extract-to", type=Path)
    options = parser.parse_args()
    result = download(options.name, options.paths, options.exclude)
    if options.extract_to:
        extract(result, options.extract_to)
