#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速验收测试：验证新增 API 接口是否正确部署（通过 SSH 在服务器本地 curl）。

运行（仓库根）：
  python Backend/tests/test_new_endpoints.py
"""
from __future__ import annotations
import json, sys
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
import subprocess

BASE = "http://127.0.0.1:5000"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

passed = 0
failed = 0

def _ssh_curl(entry, path: str, method: str = "GET", data: str | None = None, headers: list[str] | None = None) -> tuple[int, dict | str]:
    """在服务器本地 curl，返回 (http_status, parsed_body)"""
    cmd = f"curl -sf -w '\\n__STATUS__:%{{http_code}}' -X {method}"
    if headers:
        for h in headers:
            cmd += f" -H '{h}'"
    if data:
        cmd += f" -H 'Content-Type: application/json' -d '{data}'"
    cmd += f" '{BASE}{path}' 2>&1"

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
        )
        out = result.stdout.strip()
    finally:
        cleanup_temp_key(tmp)

    # 分离 body 和 status
    if "__STATUS__:" in out:
        body_part, status_part = out.rsplit("__STATUS__:", 1)
        status = int(status_part.strip())
        body = body_part.strip()
    else:
        status = 0
        body = out

    try:
        return status, json.loads(body)
    except Exception:
        return status, body


def check(name: str, status: int, body: dict | str, *, expect_status: int = 200, check_keys: list[str] | None = None):
    global passed, failed
    ok = True
    issues = []

    if status != expect_status:
        ok = False
        issues.append(f"HTTP {status} (expected {expect_status})")
    if check_keys and isinstance(body, dict):
        for k in check_keys:
            if k not in body:
                ok = False
                issues.append(f"missing key '{k}'")

    if ok:
        passed += 1
        print(f"  {GREEN}[PASS]{RESET} {name}")
        if isinstance(body, dict):
            # 打印关键字段
            for k in (check_keys or []):
                v = body.get(k)
                if isinstance(v, list):
                    print(f"         {k}: ({len(v)} items)")
                else:
                    print(f"         {k}: {str(v)[:80]}")
    else:
        failed += 1
        print(f"  {RED}[FAIL]{RESET} {name}: {'; '.join(issues)}")
        if body:
            print(f"         body: {str(body)[:200]}")


def main():
    entry = load_server("usa")
    print(f"\n{CYAN}{'='*55}{RESET}")
    print(f"{CYAN}  PonyChat 新接口验收测试{RESET}")
    print(f"{CYAN}{'='*55}{RESET}")
    print(f"  目标: {entry.label} ({entry.user}@{entry.host}:{entry.port})\n")

    # ── T1: 健康检查（基准）──────────────────────────────────
    print(f"{CYAN}[T1]{RESET} 基准健康检查")
    s, b = _ssh_curl(entry, "/api/health")
    check("GET /api/health", s, b, check_keys=["status"])

    # ── T2: 分页消息接口（无 auth → 401）───────────────────
    print(f"\n{CYAN}[T2]{RESET} 分页消息接口 /api/conversation/messages")
    s, b = _ssh_curl(entry, "/api/conversation/messages?username=test&character_id=test&limit=5")
    check("无 auth → 401", s, b, expect_status=401)

    # ── T3: 消息搜索接口（无 auth → 401）───────────────────
    print(f"\n{CYAN}[T3]{RESET} 消息搜索接口 /api/messages/search")
    s, b = _ssh_curl(entry, "/api/messages/search?username=test&character_id=test&query=hello")
    check("有 query 无 auth → 401", s, b, expect_status=401)

    # 缺 query 参数 → FastAPI 先校验必填参数，返回 422（正常行为，不是路由错误）
    s2, b2 = _ssh_curl(entry, "/api/messages/search?username=test&character_id=test")
    check("缺必填 query → 422 FastAPI校验", s2, b2, expect_status=422)

    # ── T4: 对话合并迁移接口（admin，无 auth 要求）──────────
    print(f"\n{CYAN}[T4]{RESET} 对话合并迁移接口 /api/admin/migrate_merge_conversations")
    # 不存在的 username → 404
    payload = json.dumps({"username": "__nonexistent_test_user_xyz__"})
    s, b = _ssh_curl(entry, "/api/admin/migrate_merge_conversations",
                     method="POST", data=payload)
    check("不存在用户 → 404 or 200(success)", s, b,
          expect_status=200 if (isinstance(b, dict) and b.get("success") is False) else 404)

    # ── T5: 接口路由注册验证──────────────────────────────
    print(f"\n{CYAN}[T5]{RESET} 接口存在性验证")
    # GET /api/conversation/messages → 无 auth → 401（已注册）
    s, b = _ssh_curl(entry, "/api/conversation/messages?username=x&character_id=x")
    check("GET /api/conversation/messages → 401", s, b, expect_status=401)

    # GET /api/messages/search → 有 query 无 auth → 401（已注册）
    s, b = _ssh_curl(entry, "/api/messages/search?username=x&character_id=x&query=test")
    check("GET /api/messages/search → 401", s, b, expect_status=401)

    # POST /api/admin/migrate_merge_conversations → 用户不存在 → 404（路由已注册，404 是业务逻辑）
    s, b = _ssh_curl(entry, "/api/admin/migrate_merge_conversations",
                     method="POST", data='{"username":"__nonexistent__"}')
    check("POST /api/admin/migrate_merge_conversations → 404(user not found)", s, b, expect_status=404)

    # ── 结果 ────────────────────────────────────────────────
    print(f"\n{CYAN}{'='*55}{RESET}")
    total = passed + failed
    if failed == 0:
        print(f"  {GREEN}全部 {total} 项通过 ✓{RESET}")
    else:
        print(f"  {YELLOW}{passed}/{total} 通过，{failed} 项失败{RESET}")
    print(f"{CYAN}{'='*55}{RESET}\n")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
