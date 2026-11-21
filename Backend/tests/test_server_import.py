#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过 SSH 验证 context_memory 模块和 normal_chat_memory 表在服务器上正确部署"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

_THIS = Path(__file__).resolve()
_PROJ_ROOT = _THIS.parent.parent.parent
_SERVERKEYS = _PROJ_ROOT.parent / "ServerKeys"
if not _SERVERKEYS.is_dir():
    _SERVERKEYS = Path("P:/ServerKeys")
sys.path.insert(0, str(_SERVERKEYS))

from ssh_lib import load_server, prepare_ssh_key, cleanup_temp_key, deploy_upload_env, _no_proxy_args, ssh_common_opts

GREEN  = "\033[92m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

REMOTE_SCRIPT = r"""/opt/ponychat/.venv/bin/python - <<'PYEOF'
import sys, asyncio
sys.path.insert(0, '/opt/ponychat/Backend')
sys.path.insert(0, '/opt/ponychat')

# 1. 导入 context_memory
try:
    from Backend.chat_modules.context_memory import (
        load_context_memory,
        format_context_memory_for_prompt,
        inject_context_memory_into_messages,
        schedule_context_memory_update,
    )
    print("OK: context_memory module imported")
except Exception as e:
    print(f"FAIL: context_memory import: {e}")
    sys.exit(1)

# 2. 检查 normal_chat_memory 表
try:
    from Backend.db.database import get_database
    import aiosqlite

    async def check_table():
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='normal_chat_memory'"
            ) as cur:
                row = await cur.fetchone()
        return row is not None

    exists = asyncio.run(check_table())
    print("OK: normal_chat_memory table exists" if exists else "FAIL: normal_chat_memory table NOT found")
except Exception as e:
    print(f"FAIL: DB check: {e}")

# 3. 检查 messages.py 新路由已注册
try:
    import httpx, json
    resp = httpx.get("http://127.0.0.1:5000/openapi.json", timeout=5)
    spec = resp.json()
    paths = list(spec.get("paths", {}).keys())
    for ep in ["/api/conversation/messages", "/api/messages/search", "/api/admin/migrate_merge_conversations"]:
        if ep in paths:
            print(f"OK: route {ep} registered")
        else:
            print(f"FAIL: route {ep} NOT in OpenAPI spec")
except Exception as e:
    print(f"WARN: OpenAPI check: {e}")

PYEOF
"""

def main():
    entry = load_server("usa")
    print(f"\n{CYAN}{'='*55}{RESET}")
    print(f"{CYAN}  服务器端模块 + 数据库验证{RESET}")
    print(f"{CYAN}{'='*55}{RESET}")
    print(f"  目标: {entry.label} ({entry.user}@{entry.host}:{entry.port})\n")

    act_key, tmp = prepare_ssh_key(entry.key)
    try:
        args = (["ssh"] + _no_proxy_args()
                + ["-i", str(act_key), "-p", str(entry.port)]
                + ssh_common_opts()
                + [entry.target, REMOTE_SCRIPT])
        result = subprocess.run(
            args, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=deploy_upload_env(), stdin=subprocess.DEVNULL,
        )
        output = result.stdout.strip()
    finally:
        cleanup_temp_key(tmp)

    for line in output.splitlines():
        if line.startswith("OK:"):
            print(f"  {GREEN}[PASS]{RESET} {line}")
        elif line.startswith("FAIL:"):
            print(f"  {RED}[FAIL]{RESET} {line}")
        elif line.startswith("WARN:"):
            print(f"  \033[93m[WARN]{RESET} {line}")
        else:
            print(f"  {line}")

    fails = sum(1 for l in output.splitlines() if l.startswith("FAIL:"))
    print(f"\n{CYAN}{'='*55}{RESET}")
    if fails == 0:
        print(f"  {GREEN}全部通过 ✓{RESET}")
    else:
        print(f"  {RED}{fails} 项失败{RESET}")
    print(f"{CYAN}{'='*55}{RESET}\n")
    return 1 if fails > 0 else 0

if __name__ == "__main__":
    sys.exit(main())
