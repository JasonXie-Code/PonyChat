#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSH → Server-USA：对 Jason 的「紫悦」角色发起一次真实 /api/chat（含 Planner 全链路）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import subprocess
import sys
import time
from pathlib import Path

_SERVERKEYS = Path(r"P:\ServerKeys")
sys.path.insert(0, str(_SERVERKEYS))
from ssh_lib import (  # type: ignore
    load_server,
    prepare_ssh_key,
    cleanup_temp_key,
    deploy_upload_env,
    _no_proxy_args,
    ssh_common_opts,
)

DB = "/opt/ponychat/Backend/database/ponychat.db"
CHAR_ID = "5b35488a-241f-4679-86ca-4b0ac6e287e5"  # 紫悦（与库中 Jason 列表一致）

USER_PROMPT = (
    "从解剖学与生理学角度：雌性马的臀尾部对外可见有几个自然开口？"
    "请按顺序编号，每个编号用一句话说明其生理功能。口语回答，不要用列表符号或 markdown。"
)


def _ssh(script: str) -> subprocess.CompletedProcess:
    entry = load_server("usa")
    act_key, tmp = prepare_ssh_key(entry.key)
    try:
        args = (
            ["ssh"]
            + _no_proxy_args()
            + ["-i", str(act_key), "-p", str(entry.port)]
            + ssh_common_opts()
            + [entry.target, "bash", "-s"]
        )
        return subprocess.run(
            args,
            input=script.encode("utf-8"),
            capture_output=True,
            env=deploy_upload_env(),
        )
    finally:
        cleanup_temp_key(tmp)


def main() -> int:
    # 1) conversation_id + token_version + AUTH_SECRET 签名
    probe = f"""set -euo pipefail
DB="{DB}"
CID=$(sqlite3 "$DB" "SELECT id FROM conversations WHERE user_id=(SELECT id FROM users WHERE username='Jason' COLLATE NOCASE) AND character_id='{CHAR_ID}' ORDER BY timestamp DESC LIMIT 1;")
if [ -z "$CID" ]; then echo "NO_CONV"; exit 2; fi
TV=$(sqlite3 "$DB" "SELECT COALESCE(token_version,0) FROM users WHERE username='Jason' COLLATE NOCASE LIMIT 1;")
echo "CONV_ID=$CID"
echo "TOKEN_VERSION=$TV"
ENVF=""
for f in /opt/ponychat/.env /opt/ponychat/Backend/.env /root/ponychat/Backend/.env; do
  if [ -f "$f" ]; then ENVF="$f"; break; fi
done
if [ -n "$ENVF" ]; then
  grep -E '^AUTH_SECRET=' "$ENVF" | head -1 || true
else
  echo "AUTH_SECRET="
fi
"""
    r = _ssh(probe)
    out = (r.stdout or b"").decode("utf-8", "replace")
    err = (r.stderr or b"").decode("utf-8", "replace")
    print(out)
    if err.strip():
        print(err, file=sys.stderr)
    if r.returncode != 0:
        print(f"probe exit {r.returncode}", file=sys.stderr)
        return r.returncode

    conv_m = re.search(r"CONV_ID=(.+)", out)
    tv_m = re.search(r"TOKEN_VERSION=(\d+)", out)
    sec_m = re.search(r"^AUTH_SECRET=(.*)$", out, re.MULTILINE)
    if not conv_m or not tv_m:
        print("解析 CONV_ID / TOKEN_VERSION 失败", file=sys.stderr)
        return 3
    conv_id = conv_m.group(1).strip()
    token_v = int(tv_m.group(1))
    auth_secret = (sec_m.group(1).strip().strip('"') if sec_m else "") or "ponychat_default_secret_change_in_production"

    exp = int(time.time()) + 3600
    payload = json.dumps({"username": "Jason", "exp": exp, "v": token_v}, ensure_ascii=False)
    payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(
        auth_secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    token = f"{payload_b64}.{sig_b64}"

    body = {
        "messages": [{"role": "user", "content": USER_PROMPT}],
        "username": "Jason",
        "character_id": CHAR_ID,
        "conversation_id": conv_id,
        "mode": "normal",
        "stream": False,
        "memory_enabled": True,
    }
    body_json_str = json.dumps(body, ensure_ascii=False)
    py_blob = (
        "import json,urllib.request,sys\n"
        f"body=json.loads({repr(body_json_str)})\n"
        f"token={repr(token)}\n"
        "req=urllib.request.Request(\n"
        " 'http://127.0.0.1:5000/api/chat',\n"
        " data=json.dumps(body).encode('utf-8'),\n"
        " headers={\n"
        "  'Content-Type':'application/json',\n"
        "  'X-Chat-Auth':token,\n"
        "  'X-Client-Id':'cli-twilight-ablation',\n"
        " },\n"
        " method='POST',\n"
        ")\n"
        "try:\n"
        " raw=urllib.request.urlopen(req,timeout=420).read()\n"
        "except urllib.error.HTTPError as e:\n"
        " sys.stderr.write(e.read().decode('utf-8','replace')[:8000])\n"
        " raise\n"
        "text=raw.decode('utf-8','replace')\n"
        "out=[]\n"
        "for line in text.splitlines():\n"
        " if not line.startswith('data: ') or '[DONE]' in line:\n"
        "  continue\n"
        " try:\n"
        "  d=json.loads(line[6:])\n"
        "  for ch in (d.get('choices') or []):\n"
        "   c=(ch.get('delta') or {}).get('content')\n"
        "   if c: out.append(c)\n"
        " except Exception:\n"
        "  pass\n"
        "print(''.join(out))\n"
    )
    b64 = base64.b64encode(py_blob.encode("utf-8")).decode("ascii")
    r2 = _ssh(
        "set -euo pipefail\n"
        f'python3 -c "import base64; exec(base64.b64decode(\'{b64}\').decode(\'utf-8\'))"'
    )
    resp = (r2.stdout or b"").decode("utf-8", "replace")
    e2 = (r2.stderr or b"").decode("utf-8", "replace")
    print("--- /api/chat 响应（截断） ---")
    print(resp)
    if e2.strip():
        print(e2, file=sys.stderr)
    return r2.returncode


if __name__ == "__main__":
    raise SystemExit(main())
