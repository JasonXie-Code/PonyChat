#!/usr/bin/env python3
"""Run the scene position/state anchor matrix test on Server-USA."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJ_ROOT = Path(__file__).resolve().parent.parent
_SERVERKEYS = _PROJ_ROOT.parent / "ServerKeys"
if not _SERVERKEYS.is_dir():
    _SERVERKEYS = Path("P:/ServerKeys")

sys.path.insert(0, str(_SERVERKEYS))
from ssh_lib import (  # type: ignore  # noqa: E402
    _no_proxy_args,
    cleanup_temp_key,
    deploy_upload_env,
    load_server,
    prepare_ssh_key,
    ssh_common_opts,
)

entry = load_server("Server-USA")
act_key, tmp = prepare_ssh_key(entry.key)

try:
    cmd = (
        "cd /opt/ponychat && "
        "PONYCHAT_SCENE_POS_CONCURRENCY=${PONYCHAT_SCENE_POS_CONCURRENCY:-3} "
        "/opt/ponychat/.venv/bin/python -u "
        "/opt/ponychat/Backend/scripts/test_normal_scene_position_state_anchor_matrix.py 2>&1"
    )
    args = (
        ["ssh"]
        + _no_proxy_args()
        + ["-i", str(act_key), "-p", str(entry.port)]
        + ssh_common_opts()
        + [entry.target, cmd]
    )
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
    raise SystemExit(proc.returncode)
finally:
    cleanup_temp_key(tmp)
