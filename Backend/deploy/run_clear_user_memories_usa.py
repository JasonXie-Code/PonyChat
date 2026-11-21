#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 Server-USA 上执行 clear_user_character_memories.py，清空指定用户 character_memories
（生产库路径默认 /opt/ponychat/Backend/database/ponychat.db）。
用法（仓库根）:
  python Backend/deploy/run_clear_user_memories_usa.py [username]
"""
from __future__ import annotations

import io
import shlex
import subprocess
import sys
from pathlib import Path

_PROJ = Path(__file__).resolve().parent.parent.parent
_SERVERKEYS = _PROJ.parent / "ServerKeys"
if not _SERVERKEYS.is_dir():
    _SERVERKEYS = Path("P:/ServerKeys")
sys.path.insert(0, str(_SERVERKEYS))
from ssh_lib import (  # type: ignore
    cleanup_temp_key,
    deploy_upload_env,
    load_server,
    prepare_ssh_key,
    _no_proxy_args,
    ssh_common_opts,
    scp_to,
)

REMOTE_DB = "/opt/ponychat/Backend/database/ponychat.db"
SCRIPTS_LOCAL = _PROJ / "Backend" / "scripts" / "clear_user_character_memories.py"
REMOTE_SCRIPT = "/tmp/clear_user_character_memories.py"


def _ssh_cmd(entry, remote: str) -> tuple[int, str, str]:
    act_key, tmp = prepare_ssh_key(entry.key)
    try:
        args = (
            ["ssh"] + _no_proxy_args()
            + ["-i", str(act_key), "-p", str(entry.port)]
            + ssh_common_opts()
            + [entry.target, remote]
        )
        r = subprocess.run(
            args, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=deploy_upload_env(), stdin=subprocess.DEVNULL,
        )
        return r.returncode, r.stdout, r.stderr
    finally:
        cleanup_temp_key(tmp)


def main() -> int:
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    u = (sys.argv[1] if len(sys.argv) > 1 else "Jason").strip()
    if not SCRIPTS_LOCAL.is_file():
        print("local script missing:", SCRIPTS_LOCAL, file=sys.stderr)
        return 1
    entry = load_server("usa")
    c = scp_to(entry, SCRIPTS_LOCAL, REMOTE_SCRIPT)
    if c != 0:
        print("scp failed:", c, file=sys.stderr)
        return c
    cmd = f"python3 {REMOTE_SCRIPT} {shlex.quote(u)} {shlex.quote(REMOTE_DB)}"
    code, out, err = _ssh_cmd(entry, cmd)
    if out:
        print(out, end="")
    if err:
        print(err, end="", file=sys.stderr)
    return code or 0


if __name__ == "__main__":
    raise SystemExit(main())
