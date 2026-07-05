#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 Server-USA 上生成一条有效 X-Chat-Auth，并对公网 GET /api/proactive/pending 发起 curl，
用于确认 JSON 中含 created_at_ms（需本机可 SSH usa、可访问 https://www.ponychat.org）。

用法（仓库根）：
  python misc/dev/probe_proactive_pending.py
"""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_THIS = Path(__file__).resolve()
_PROJ_ROOT = _THIS.parent.parent
_SERVERKEYS = _PROJ_ROOT.parent / "ServerKeys"
if not _SERVERKEYS.is_dir():
    _SERVERKEYS = Path("P:/ServerKeys")

sys.path.insert(0, str(_SERVERKEYS))
from ssh_lib import (  # type: ignore
    load_server,
    prepare_ssh_key,
    cleanup_temp_key,
    deploy_upload_env,
    _no_proxy_args,
    ssh_common_opts,
    scp_to,
)

REMOTE_MINT = r'''#!/usr/bin/env python3
"""仅用 stdlib：读库 + .env 签发与 Backend.routes.auth 一致的 X-Chat-Auth（无需 aiosqlite）。"""
import base64
import hmac
import json
import sqlite3
import sys
import time

DB = "/opt/ponychat/Backend/database/ponychat.db"
ENV = "/opt/ponychat/.env"


def read_auth_secret() -> str:
    try:
        with open(ENV, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if s.startswith("AUTH_SECRET="):
                    return s.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return "ponychat_default_secret_change_in_production"


def mint_token(username: str, token_version: int, secret: str) -> str:
    exp = int(time.time()) + 7 * 24 * 3600
    payload = json.dumps({"username": username, "exp": exp, "v": token_version}, ensure_ascii=False)
    payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), "sha256").digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def main() -> None:
    conn = sqlite3.connect(DB)
    cur = conn.execute(
        "SELECT username, COALESCE(token_version, 0) FROM users ORDER BY id LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        print("NO_USER", file=sys.stderr)
        sys.exit(2)
    u, v = str(row[0]), int(row[1])
    tok = mint_token(u, v, read_auth_secret())
    print("TOKEN=" + tok)
    print("USER=" + u)


if __name__ == "__main__":
    main()
'''


def _ssh_capture(entry, remote_cmd: str) -> tuple[int, str, str]:
    act_key, tmp = prepare_ssh_key(entry.key)
    try:
        args = (
            ["ssh"]
            + _no_proxy_args()
            + ["-i", str(act_key), "-p", str(entry.port)]
            + ssh_common_opts()
            + [entry.target, remote_cmd]
        )
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=deploy_upload_env(),
            stdin=subprocess.DEVNULL,
        )
        return r.returncode, r.stdout, r.stderr
    finally:
        cleanup_temp_key(tmp)


def main() -> int:
    entry = load_server("usa")
    target = "https://www.ponychat.org/api/proactive/pending"

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
        tf.write(REMOTE_MINT)
        local_py = Path(tf.name)

    remote_py = "/tmp/_probe_mint_token.py"
    try:
        if scp_to(entry, local_py, remote_py) != 0:
            print("scp 上传 mint 脚本失败", file=sys.stderr)
            return 1
        code, out, err = _ssh_capture(entry, f"python3 {remote_py}")
        if code != 0:
            print("远端生成 token 失败:", err or out, file=sys.stderr)
            return code
        token = ""
        for line in (out or "").splitlines():
            if line.startswith("TOKEN="):
                token = line[len("TOKEN=") :].strip()
                break
        if not token:
            print("未解析到 TOKEN:", out, err, file=sys.stderr)
            return 1
    finally:
        local_py.unlink(missing_ok=True)
        _ssh_capture(entry, f"rm -f {remote_py}")

    print("--- curl GET", target, "---\n")
    curl = [
        "curl",
        "-sS",
        "-w",
        "\n\n--- HTTP %{http_code} ---\n",
        target,
        "-H",
        f"X-Chat-Auth: {token}",
        "-H",
        "X-PonyChat-Client: android",
        "-H",
        "X-App-Version: 99",
    ]
    r2 = subprocess.run(curl, capture_output=True, text=True, encoding="utf-8", errors="replace")
    sys.stdout.write(r2.stdout or "")
    if r2.stderr:
        sys.stderr.write(r2.stderr)
    body = r2.stdout or ""
    if '"created_at_ms"' in body or "'created_at_ms'" in body:
        print("\n[OK] 响应体中出现字段名 created_at_ms")
    else:
        print("\n[!] 响应体中未看到 created_at_ms（可能 messages 为空数组，属正常）")
    return r2.returncode


if __name__ == "__main__":
    raise SystemExit(main())
