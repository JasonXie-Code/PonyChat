#!/usr/bin/env python3
"""Run the supportive matrix test on the remote server and stream output."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJ_ROOT = Path(__file__).resolve().parent.parent
_SERVERKEYS = _PROJ_ROOT.parent / "ServerKeys"
if not _SERVERKEYS.is_dir():
    _SERVERKEYS = Path("P:/ServerKeys")

sys.path.insert(0, str(_SERVERKEYS))
from ssh_lib import (
    load_server, prepare_ssh_key, cleanup_temp_key,
    deploy_upload_env, _no_proxy_args, ssh_common_opts,
)

entry = load_server("Server-USA")
act_key, tmp = prepare_ssh_key(entry.key)

try:
    cmd = (
        "cd /opt/ponychat && "
        "/opt/ponychat/.venv/bin/python /opt/ponychat/Backend/scripts/test_supportive_matrix.py 2>&1"
    )
    args = (
        ["ssh"] + _no_proxy_args()
        + ["-i", str(act_key), "-p", str(entry.port)]
        + ssh_common_opts()
        + [entry.target, cmd]
    )
    # Stream output in real-time
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=deploy_upload_env(),
        stdin=subprocess.DEVNULL,
    )
    assert proc.stdout
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
    proc.wait()
    sys.exit(proc.returncode)
finally:
    cleanup_temp_key(tmp)
