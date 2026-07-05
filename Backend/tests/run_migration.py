#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对话合并迁移执行脚本：为所有用户的所有角色合并对话。

运行（仓库根）：
  python Backend/tests/run_migration.py
"""
from __future__ import annotations
import io, json, sys, subprocess
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_THIS = Path(__file__).resolve()
_PROJ_ROOT = _THIS.parent.parent.parent
_SERVERKEYS = _PROJ_ROOT.parent / "ServerKeys"
if not _SERVERKEYS.is_dir():
    _SERVERKEYS = Path("P:/ServerKeys")
sys.path.insert(0, str(_SERVERKEYS))

from ssh_lib import load_server, prepare_ssh_key, cleanup_temp_key, deploy_upload_env, _no_proxy_args, ssh_common_opts  # type: ignore

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

BASE = "http://127.0.0.1:5000"
DB_PATH = "/opt/ponychat/Backend/database/ponychat.db"


def _ssh_exec(entry, cmd: str) -> tuple[int, str, str]:
    act_key, tmp = prepare_ssh_key(entry.key)
    try:
        args = (["ssh"] + _no_proxy_args()
                + ["-i", str(act_key), "-p", str(entry.port)]
                + ssh_common_opts()
                + [entry.target, cmd])
        result = subprocess.run(
            args, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=deploy_upload_env(), stdin=subprocess.DEVNULL,
            timeout=120
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        cleanup_temp_key(tmp)


def main():
    entry = load_server("usa")
    print(f"\n{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}  PonyChat 对话合并迁移{RESET}")
    print(f"{CYAN}{'='*60}{RESET}")
    print(f"  目标服务器: {entry.label} ({entry.user}@{entry.host}:{entry.port})\n")

    # 1. 从数据库获取所有用户名
    print(f"[1/3] 获取数据库中所有用户...")
    rc, out, err = _ssh_exec(entry, f"sqlite3 {DB_PATH} \"SELECT username FROM users ORDER BY id;\"")
    if rc != 0:
        print(f"  {RED}[错误]{RESET} 无法读取用户列表: {err.strip()}")
        return 1

    usernames = [u.strip() for u in out.strip().splitlines() if u.strip()]
    print(f"  找到 {len(usernames)} 个用户: {', '.join(usernames)}\n")

    if not usernames:
        print(f"  {YELLOW}[跳过]{RESET} 没有用户需要迁移。")
        return 0

    # 2. 逐用户调用迁移接口
    print(f"[2/3] 为每个用户执行对话合并迁移...")
    total_merged = 0
    total_skipped = 0
    total_failed = 0

    for username in usernames:
        payload = json.dumps({"username": username})
        curl_cmd = (
            f"curl -sf -w '\\n__STATUS__:%{{http_code}}' "
            f"-X POST "
            f"-H 'Content-Type: application/json' "
            f"-d '{payload}' "
            f"'{BASE}/api/admin/migrate_merge_conversations'"
        )
        rc, out, err_out = _ssh_exec(entry, curl_cmd)

        # 解析响应
        status = 0
        body = {}
        if "__STATUS__:" in out:
            parts = out.rsplit("__STATUS__:", 1)
            try:
                status = int(parts[1].strip())
                body = json.loads(parts[0].strip()) if parts[0].strip() else {}
            except Exception:
                body = parts[0].strip()
        
        if status == 200 and isinstance(body, dict) and body.get("success"):
            results = body.get("results", [])
            merged = sum(1 for r in results if r.get("status") == "merged")
            skipped = sum(1 for r in results if r.get("status") == "skipped")
            msgs = sum(r.get("total_messages", 0) for r in results if r.get("status") == "merged")
            print(f"  {GREEN}[OK]{RESET}    {username}: 合并 {merged} 个角色（共 {msgs} 条消息），跳过 {skipped} 个")
            total_merged += merged
            total_skipped += skipped
        elif status == 404:
            print(f"  {YELLOW}[跳过]{RESET}  {username}: 用户不存在（404）")
            total_skipped += 1
        else:
            print(f"  {RED}[错误]{RESET}  {username}: status={status}, body={str(body)[:150]}")
            total_failed += 1

    # 3. 汇总
    print(f"\n[3/3] 迁移完成")
    print(f"  {CYAN}合并角色数：{total_merged}{RESET}")
    print(f"  跳过（无需合并）：{total_skipped}")
    if total_failed:
        print(f"  {RED}失败：{total_failed}{RESET}")
    print(f"\n{CYAN}{'='*60}{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
