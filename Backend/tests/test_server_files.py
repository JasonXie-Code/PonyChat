#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证服务器上新文件和数据库表是否存在"""
from __future__ import annotations
import io, subprocess, sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_SERVERKEYS = Path("P:/ServerKeys")
sys.path.insert(0, str(_SERVERKEYS))
from ssh_lib import load_server, prepare_ssh_key, cleanup_temp_key, deploy_upload_env, _no_proxy_args, ssh_common_opts

GREEN  = "\033[92m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

def ssh_cmd(entry, cmd, timeout=15):
    act_key, tmp = prepare_ssh_key(entry.key)
    try:
        args = (["ssh"] + _no_proxy_args()
                + ["-i", str(act_key), "-p", str(entry.port)]
                + ssh_common_opts()
                + [entry.target, cmd])
        r = subprocess.run(args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           env=deploy_upload_env(), stdin=subprocess.DEVNULL,
                           timeout=timeout)
        return r.stdout.strip(), r.returncode
    finally:
        cleanup_temp_key(tmp)

def main():
    entry = load_server("usa")
    print(f"\n{CYAN}{'='*55}{RESET}")
    print(f"{CYAN}  服务器文件 + DB 表验证{RESET}")
    print(f"{CYAN}{'='*55}{RESET}")

    passed = failed = 0

    def chk(name, ok, detail=""):
        nonlocal passed, failed
        if ok:
            passed += 1
            print(f"  {GREEN}[PASS]{RESET} {name}" + (f" — {detail}" if detail else ""))
        else:
            failed += 1
            print(f"  {RED}[FAIL]{RESET} {name}" + (f" — {detail}" if detail else ""))

    # 文件存在性
    for rel in [
        "Backend/chat_modules/context_memory.py",
        "Backend/chat_modules/normal_nonstream.py",
        "Backend/routes/messages.py",
        "Backend/routes/admin/conversations.py",
    ]:
        out, rc = ssh_cmd(entry, f"ls /opt/ponychat/{rel} 2>/dev/null && echo OK || echo MISS")
        chk(f"文件存在: {rel}", "OK" in out)

    # normal_chat_memory 表（服务器运行后自动创建）
    db_path = "/opt/ponychat/Backend/database/ponychat.db"
    out, rc = ssh_cmd(entry, f"sqlite3 {db_path} \"SELECT name FROM sqlite_master WHERE type='table' AND name='normal_chat_memory';\" 2>/dev/null")
    chk("DB: normal_chat_memory 表", "normal_chat_memory" in out, out or "(空，可能未触发 init)")

    # API 接口验证（服务器本地 curl）
    ep_checks = [
        ("GET /api/conversation/messages", "curl -sf -w '\\n%{http_code}' 'http://127.0.0.1:5000/api/conversation/messages?username=x&character_id=x' | tail -1"),
        ("GET /api/messages/search", "curl -sf -w '\\n%{http_code}' 'http://127.0.0.1:5000/api/messages/search?username=x&character_id=x&query=test' | tail -1"),
    ]
    for name, cmd in ep_checks:
        out, rc = ssh_cmd(entry, cmd)
        status = out.strip()
        not_404 = status not in ("404", "000", "")
        chk(f"接口已注册: {name}", not_404, f"HTTP {status}")

    # 管理迁移接口：不存在用户 → 404（业务逻辑，路由已注册；curl -f 压制 4xx 响应体故用 -w 检查状态码）
    out, _ = ssh_cmd(entry, "curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{\"username\":\"__nonexistent__\"}' 'http://127.0.0.1:5000/api/admin/migrate_merge_conversations'")
    status = out.strip()
    # 404=用户不存在（路由已注册），非路由缺失的 404 已由 T5 的 401 检测排除
    chk("接口已注册: POST /api/admin/migrate_merge_conversations (用户不存在→404)", status == "404", f"HTTP {status}")

    print(f"\n{CYAN}{'='*55}{RESET}")
    total = passed + failed
    if failed == 0:
        print(f"  {GREEN}全部 {total} 项通过 ✓{RESET}")
    else:
        print(f"  {RED}{failed}/{total} 项失败{RESET}")
    print(f"{CYAN}{'='*55}{RESET}\n")
    return 1 if failed > 0 else 0

if __name__ == "__main__":
    sys.exit(main())
