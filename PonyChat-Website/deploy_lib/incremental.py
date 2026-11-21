#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Iterable, Sequence


MANIFEST_NAME = ".ponychat-deploy-manifest.json"
DELETE_NAME = ".ponychat-deploy-delete.json"

DEFAULT_EXCLUDES = {
    ".git",
    ".DS_Store",
    MANIFEST_NAME,
    DELETE_NAME,
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "backups",
    "deploy-backups",
    "logs",
    "models",
    "outputs",
    "uploads",
    "voices",
}


def ensure_utf8_stdio() -> None:
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    else:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
            except (AttributeError, OSError, ValueError):
                pass


def website_root(from_file: Path) -> Path:
    p = from_file.resolve()
    for parent in p.parents:
        if parent.name == "PonyChat-Website":
            return parent
    raise RuntimeError(f"Cannot find PonyChat-Website parent from {from_file}")


def serverkeys_dir() -> Path:
    env = os.environ.get("PONYCHAT_SERVERKEYS", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    p_drive = Path("P:/ServerKeys")
    if p_drive.is_dir():
        return p_drive.resolve()
    return (website_root(Path(__file__)) .parent.parent / "ServerKeys").resolve()


def load_ssh_lib():
    sk = serverkeys_dir()
    if str(sk) not in sys.path:
        sys.path.insert(0, str(sk))
    import ssh_lib  # type: ignore

    return ssh_lib


def load_target(kind: str, name: str):
    ssh_lib = load_ssh_lib()
    if kind == "server":
        return ssh_lib.load_server(name)
    if kind == "bridge":
        return ssh_lib.load_bridge(name)
    raise ValueError(f"Unknown target kind: {kind}")


def run(cmd: Sequence[str], *, cwd: Path | None = None, timeout: int | None = None) -> None:
    print("[local]", " ".join(map(str, cmd)))
    rc = subprocess.run(cmd, cwd=cwd, check=False, timeout=timeout).returncode
    if rc != 0:
        raise SystemExit(rc)


def npm_build(project_dir: Path) -> None:
    npm_bin = "npm.cmd" if os.name == "nt" else "npm"
    run([npm_bin, "run", "build"], cwd=project_dir, timeout=None)


def _ssh_args(entry, *, key: Path) -> list[str]:
    args = ["ssh"]
    if os.name == "nt":
        args += ["-F", "none"]
    args += [
        "-i",
        str(key),
        "-p",
        str(entry.port),
        "-o",
        "BatchMode=yes",
        "-o",
        "RequestTTY=no",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=25",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=4",
        entry.target,
    ]
    return args


def ssh_capture(entry, remote_cmd: str) -> tuple[int, str, str]:
    ssh_lib = load_ssh_lib()
    key, tmp = ssh_lib.prepare_ssh_key(entry.key)
    try:
        proc = subprocess.run(
            _ssh_args(entry, key=key) + [remote_cmd],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=ssh_lib.deploy_upload_env(),
        )
        return (
            proc.returncode,
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"),
        )
    finally:
        ssh_lib.cleanup_temp_key(tmp)


def _skip_rel(rel: Path, excludes: set[str]) -> bool:
    return any(part in excludes for part in rel.parts)


def manifest_for(root: Path, *, excludes: Iterable[str] = ()) -> dict[str, dict[str, object]]:
    root = root.resolve()
    exclude_set = DEFAULT_EXCLUDES | set(excludes)
    out: dict[str, dict[str, object]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root)
        if _skip_rel(rel_path, exclude_set):
            continue
        rel = rel_path.as_posix()
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        st = path.stat()
        out[rel] = {"sha256": h.hexdigest(), "size": st.st_size}
    return dict(sorted(out.items()))


def scan_remote_manifest(
    entry,
    remote_dir: str,
    *,
    excludes: Iterable[str] = (),
    reason: str,
) -> dict[str, dict[str, object]]:
    """Build a manifest from files already present on the remote host.

    This avoids a full upload when an older deployment directory already has
    the files but was created before deploy manifests existed.
    """
    exclude_json = json.dumps(sorted(DEFAULT_EXCLUDES | set(excludes)), ensure_ascii=False)
    script = f"""
python3 - <<'PY'
import hashlib
import json
import os
import time
from pathlib import Path

root = Path({remote_dir!r}).resolve()
excludes = set(json.loads({exclude_json!r}))
manifest_name = {MANIFEST_NAME!r}

root.mkdir(parents=True, exist_ok=True)
files = {{}}

for dirpath, dirnames, filenames in os.walk(root):
    current = Path(dirpath)
    rel_dir = current.relative_to(root) if current != root else Path()
    kept_dirs = []
    for name in dirnames:
        rel_parts = rel_dir.parts + (name,)
        if any(part in excludes for part in rel_parts):
            continue
        kept_dirs.append(name)
    dirnames[:] = kept_dirs

    for name in filenames:
        rel_path = rel_dir / name
        if any(part in excludes for part in rel_path.parts):
            continue
        path = current / name
        if path.is_symlink() or not path.is_file():
            continue
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        files[rel_path.as_posix()] = {{
            "sha256": h.hexdigest(),
            "size": path.stat().st_size,
        }}

manifest = {{
    "version": 1,
    "files": dict(sorted(files.items())),
    "updated_at": int(time.time()),
    "source": "remote_scan",
}}
tmp = root / (manifest_name + ".tmp")
tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
tmp.replace(root / manifest_name)
print(json.dumps(manifest["files"], ensure_ascii=False, sort_keys=True))
PY
"""
    print(f"remote manifest {reason}; scanning existing files on server ...", flush=True)
    rc, stdout, stderr = ssh_capture(entry, script)
    if rc != 0:
        raise RuntimeError(stderr.strip() or f"ssh failed while scanning {remote_dir}")
    try:
        data = json.loads(stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"remote manifest scan returned invalid JSON for {remote_dir}") from exc
    return data if isinstance(data, dict) else {}


def read_remote_manifest(
    entry,
    remote_dir: str,
    *,
    excludes: Iterable[str] = (),
) -> dict[str, dict[str, object]]:
    remote_manifest = f"{remote_dir.rstrip('/')}/{MANIFEST_NAME}"
    rc, stdout, stderr = ssh_capture(
        entry,
        f"cat {shlex.quote(remote_manifest)} 2>/dev/null || true",
    )
    if rc != 0:
        raise RuntimeError(stderr.strip() or f"ssh failed while reading {remote_manifest}")
    text = stdout.strip()
    if not text:
        return scan_remote_manifest(entry, remote_dir, excludes=excludes, reason="missing")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return scan_remote_manifest(entry, remote_dir, excludes=excludes, reason="invalid")
    if not isinstance(data, dict) or "files" not in data:
        return scan_remote_manifest(entry, remote_dir, excludes=excludes, reason="invalid")
    files = data.get("files")
    if not isinstance(files, dict):
        return scan_remote_manifest(entry, remote_dir, excludes=excludes, reason="invalid")
    return files


def _make_tarball(root: Path, changed: Sequence[str], manifest: dict, stale: Sequence[str]) -> Path:
    fd, tmp_name = tempfile.mkstemp(suffix=".tar.gz")
    os.close(fd)
    tar_path = Path(tmp_name)
    with tarfile.open(tar_path, "w:gz") as tar:
        for rel in changed:
            path = root / rel
            tar.add(path, arcname=rel)
        manifest_blob = json.dumps(
            {"version": 1, "files": manifest, "updated_at": int(time.time())},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(manifest_blob)
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(manifest_blob))
        delete_blob = json.dumps(list(stale), ensure_ascii=False).encode("utf-8")
        info = tarfile.TarInfo(DELETE_NAME)
        info.size = len(delete_blob)
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(delete_blob))
    return tar_path


def deploy_tree(
    *,
    local_dir: Path,
    target_kind: str,
    target_name: str,
    remote_dir: str,
    label: str,
    excludes: Iterable[str] = (),
    post_commands: Sequence[str] = (),
) -> None:
    ensure_utf8_stdio()
    local_dir = local_dir.resolve()
    if not local_dir.is_dir():
        raise SystemExit(f"Missing local deploy directory: {local_dir}")

    entry = load_target(target_kind, target_name)
    ssh_lib = load_ssh_lib()
    print(f"== {label} ==")
    print(f"local : {local_dir}")
    print(f"remote: {entry.target}:{remote_dir}")
    local_manifest = manifest_for(local_dir, excludes=excludes)
    remote_manifest = read_remote_manifest(entry, remote_dir, excludes=excludes)

    changed = [
        rel
        for rel, meta in local_manifest.items()
        if remote_manifest.get(rel, {}).get("sha256") != meta["sha256"]
    ]
    stale = [rel for rel in remote_manifest.keys() if rel not in local_manifest]

    print(f"files : {len(local_manifest)} local, {len(changed)} changed, {len(stale)} stale")

    if not changed and not stale:
        print("No file changes.")
        return

    tar_path = _make_tarball(local_dir, changed, local_manifest, stale)
    remote_tar = f"/tmp/ponychat-deploy-{label.replace(' ', '-').lower()}-{int(time.time())}.tar.gz"
    try:
        rc = ssh_lib.scp_to(entry, tar_path, remote_tar, env=ssh_lib.deploy_upload_env())
        if rc != 0:
            raise SystemExit(rc)
    finally:
        tar_path.unlink(missing_ok=True)

    remote_q = shlex.quote(remote_dir)
    tar_q = shlex.quote(remote_tar)
    script = f"""
set -euo pipefail
mkdir -p {remote_q}
tar -xzf {tar_q} -C {remote_q}
rm -f {tar_q}
python3 - <<'PY'
import json
import shutil
from pathlib import Path

root = Path({remote_dir!r}).resolve()
delete_file = root / {DELETE_NAME!r}
try:
    stale = json.loads(delete_file.read_text(encoding="utf-8"))
except FileNotFoundError:
    stale = []
for rel in stale:
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise SystemExit(f"unsafe stale path: {{rel}}")
    target = (root / rel_path).resolve()
    if target != root and root not in target.parents:
        raise SystemExit(f"escape stale path: {{rel}}")
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
delete_file.unlink(missing_ok=True)
PY
"""
    if post_commands:
        script += "\n" + "\n".join(post_commands) + "\n"

    rc = ssh_lib.ssh_bash_s(entry, script, env=ssh_lib.deploy_upload_env())
    if rc != 0:
        raise SystemExit(rc)
    print("Deploy complete.")


def stage_files(files: Sequence[tuple[Path, str]], dirs: Sequence[tuple[Path, str]] = ()) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for src, rel in files:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    for src, rel in dirs:
        dst = root / rel
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    return tmp
