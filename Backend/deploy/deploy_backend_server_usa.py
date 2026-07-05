#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将本地 Backend/ 增量同步到 Server-USA 并重启后端服务。

用法（仓库根）：
  python Backend/deploy/deploy_backend_server_usa.py

流程：
  1. 定位服务器上的 Backend 目录
  2. 生成本次 deploy_token 并写入 Backend/.deploy_revision（供健康检查与探活校验）
  3. MD5 比对，找出 本地新增 / 内容变更 的文件
  4. 打包为 tar.gz，一次性上传并解压（**永不**打包或覆盖 `database/`；`data/` 只允许 mlp-database）
  5. 重启后端 systemd 服务
  6. 探活 GET /api/health，直到 JSON 中 deploy_token 与本次令牌一致（确保新进程已加载）
"""
from __future__ import annotations

import hashlib
import io
import json
import secrets
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

# Windows 控制台统一 UTF-8；行缓冲便于在 Cursor/管道里实时看到进度（默认块缓冲会整段滞后）
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
else:
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        pass

# ── 路径配置 ───────────────────────────────────────────────────────────────────
# Backend/deploy/xxx.py → .parent×3 = 仓库根（deploy → Backend → 仓库根）
_THIS        = Path(__file__).resolve()
_PROJ_ROOT   = _THIS.parent.parent.parent
_SERVERKEYS  = _PROJ_ROOT.parent / "ServerKeys"
if not _SERVERKEYS.is_dir():
    _SERVERKEYS = Path("P:/ServerKeys")

sys.path.insert(0, str(_SERVERKEYS))
from ssh_lib import (  # type: ignore
    load_server, prepare_ssh_key, cleanup_temp_key,
    deploy_upload_env, _no_proxy_args, ssh_common_opts,
    ssh_exec, ssh_bash_s, scp_to,
)

LOCAL_BACKEND   = _PROJ_ROOT / "Backend"
LOCAL_UNIT_FILE = LOCAL_BACKEND / "deploy" / "ponychat-backend.service"
REMOTE_UNIT_FILE = "/etc/systemd/system/ponychat-backend.service"
# 与 LOCAL_UNIT_FILE 中 Environment=UVICORN_WORKERS 保持一致（当前为 1：单进程，后台 lifespan 任务不重复）。

# 不同步到服务器的目录（服务器专属运行数据 + 本目录仅含部署脚本）
# database/：生产 SQLite（ponychat.db 及 WAL/SHM）所在，禁止纳入 MD5 与 tar，避免覆盖远端库。
SKIP_DIRS = {
    "__pycache__", ".git", "backups", "data", "database", "deploy",
    "portrait_candidates", "refined", "refined_pony",
    "portrait",
}
SKIP_EXTS = {
    ".pyc", ".pyo", ".db", ".db-shm", ".db-wal", ".log", ".lock",
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".mp3", ".mp4", ".zip", ".tar", ".gz",
    ".bz2", ".xz", ".7z", ".pem", ".ppk", ".pub",
}
SKIP_FILES = {
    "backend.log", "backend_access_full.log", ".backup_scheduler.lock",
    "tags.jsonl", "fetch_portrait_candidates_log.jsonl", "fetch_portraits_log.jsonl",
}
ALLOWED_DATA_DIRS = {"mlp-database"}

# ANSI 终端颜色码
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

def ok(s):    print(f"  {GREEN}[OK]{RESET}  {s}", flush=True)
def warn(s):  print(f"  {YELLOW}[!]{RESET}   {s}", flush=True)
def err(s):   print(f"  {RED}[X]{RESET}   {s}", flush=True)
def info(s):  print(f"         {s}", flush=True)
def step(n, total, s): print(f"\n{CYAN}[{n}/{total}]{RESET} {s}", flush=True)


def _phase_end(label: str, t0: float, phases: list[tuple[str, float]]) -> None:
    """记录并打印某一阶段耗时（秒），用于定位部署慢在哪。"""
    elapsed = time.monotonic() - t0
    phases.append((label, elapsed))
    info(f"⏱ {label}: {elapsed:.2f}s")


def _print_timing_summary(phases: list[tuple[str, float]], t_wall0: float) -> None:
    info(f"{CYAN}─── 耗时汇总（monotonic，供对比） ───{RESET}")
    total_phases = sum(s for _, s in phases)
    if phases:
        for name, sec in phases:
            pct = (100.0 * sec / total_phases) if total_phases > 0 else 0.0
            info(f"    {name:32s} {sec:7.2f}s  ({pct:5.1f}%)")
        info(f"    {'以上各阶段合计':32s} {total_phases:7.2f}s")
    else:
        info("    （尚无分阶段计时数据）")
    info(f"    {'自启动至结束（wall）':32s} {time.monotonic() - t_wall0:7.2f}s")
    info(
        "    提示: 5b 占比高时，缩短重启可看服务端 UVICORN_WORKERS、"
        "lifespan 重预热是否延后、Aliyun NLS 等是否在启动关键路径。"
    )


# ── SSH 辅助 ───────────────────────────────────────────────────────────────────

def _ssh_capture(entry, remote_cmd: str) -> tuple[int, str, str]:
    act_key, tmp = prepare_ssh_key(entry.key)
    try:
        args = (["ssh"] + _no_proxy_args()
                + ["-i", str(act_key), "-p", str(entry.port)]
                + ssh_common_opts()
                + [entry.target, remote_cmd])
        result = subprocess.run(
            args, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=deploy_upload_env(), stdin=subprocess.DEVNULL,
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        cleanup_temp_key(tmp)


# ── 查找远端 Backend 路径 ──────────────────────────────────────────────────────

def find_remote_backend(entry) -> str | None:
    print("  在服务器上搜索 Backend 目录...", flush=True)
    cmd = (
        "find /root /home /opt /srv /var/www /app 2>/dev/null "
        "-maxdepth 8 -name 'config.py' "
        r"| xargs grep -l 'PROJECT_ROOT\|BACKLOGS_DIR' 2>/dev/null "
        "| sed 's|/config\\.py||' | head -5"
    )
    _, out, _ = _ssh_capture(entry, cmd)
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    if lines:
        return lines[0]
    cmd2 = (
        "find /root /home /opt /srv /app 2>/dev/null "
        "-maxdepth 6 -type d -name 'Backend' | head -5"
    )
    _, out2, _ = _ssh_capture(entry, cmd2)
    lines2 = [l.strip() for l in out2.strip().splitlines() if l.strip()]
    return lines2[0] if lines2 else None


# ── MD5 对比 ───────────────────────────────────────────────────────────────────

def get_remote_md5s(entry, remote_dir: str) -> tuple[dict[str, str], str]:
    """返回 (Backend 文件 MD5 字典, unit 文件远端 MD5 或空字符串)。
    两个 md5sum 合并到同一次 SSH 调用，节省一次 RTT。"""
    print(f"  获取服务器文件 MD5：{remote_dir} ...", flush=True)
    cmd = (
        f"find {remote_dir} "
        + " ".join(f"-path '{remote_dir}/{d}' -prune -o" for d in SKIP_DIRS)
        + " -type f ! -name '*.pyc' ! -name '*.pyo' ! -name '*.db'"
        + " ! -name '*.log' ! -name '*.lock' ! -name '*.jpg' ! -name '*.jpeg'"
        + " ! -name '*.png' ! -name '*.gif' ! -name '*.webp'"
        + " ! -name '*.pem' ! -name '*.ppk' ! -name '*.pub'"
        + " ! -name '*.zip' ! -name '*.tar' ! -name '*.gz'"
        + " -print0 2>/dev/null"
        + " | xargs -0 md5sum 2>/dev/null"
        # data/ 默认整目录跳过；只有 mlp-database 是只读资料库，允许随 Backend 部署。
        + f"; if [ -d '{remote_dir}/data/mlp-database' ]; then "
        + f"find '{remote_dir}/data/mlp-database' "
        + "-path '*/__pycache__' -prune -o "
        + "-type f ! -name '*.pyc' ! -name '*.pyo' ! -name '*.db-shm' ! -name '*.db-wal' "
        + "! -name '*.log' ! -name '*.lock' -print0 2>/dev/null "
        + "| xargs -r -0 md5sum 2>/dev/null; fi"
        # 同时输出 unit 文件 MD5（用特殊前缀与 Backend 文件区分）
        + f"; echo '__UNIT__' ; md5sum {REMOTE_UNIT_FILE} 2>/dev/null || true"
    )
    _, out, _ = _ssh_capture(entry, cmd)

    result: dict[str, str] = {}
    unit_md5 = ""
    prefix = remote_dir.rstrip("/") + "/"
    in_unit = False
    for line in out.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line == "__UNIT__":
            in_unit = True
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        md5, path = parts[0], parts[1].strip()
        if in_unit:
            unit_md5 = md5
        else:
            rel = path.removeprefix(prefix)
            if Path(rel).name not in SKIP_FILES:
                result[rel] = md5
    return result, unit_md5


def get_local_md5s() -> dict[str, str]:
    print(f"  计算本地文件 MD5：{LOCAL_BACKEND} ...", flush=True)
    result: dict[str, str] = {}

    def _allowed_data_file(rel: Path) -> bool:
        if len(rel.parts) < 2 or rel.parts[0] != "data":
            return False
        if rel.parts[1] not in ALLOWED_DATA_DIRS:
            return False
        if any(part == "__pycache__" for part in rel.parts):
            return False
        if rel.suffix in {".pyc", ".pyo", ".db-shm", ".db-wal", ".log", ".lock"}:
            return False
        return True

    def _skip(p: Path) -> bool:
        rel = p.relative_to(LOCAL_BACKEND)
        if rel.parts and rel.parts[0] == "data":
            return not _allowed_data_file(rel)
        if p.name in SKIP_DIRS or p.name in SKIP_FILES:
            return True
        if p.suffix in SKIP_EXTS:
            return True
        for part in rel.parts[:-1]:
            if part in SKIP_DIRS:
                return True
        return False

    for f in LOCAL_BACKEND.rglob("*"):
        if not f.is_file() or _skip(f):
            continue
        rel = f.relative_to(LOCAL_BACKEND).as_posix()
        try:
            result[rel] = hashlib.md5(f.read_bytes()).hexdigest()
        except Exception:
            pass
    return result


def compute_diff(local: dict[str, str], remote: dict[str, str]) -> tuple[list[str], list[str]]:
    """返回 (需上传文件列表, 仅服务器有的文件列表)。"""
    to_upload = sorted(
        k for k in local
        if k not in remote or local[k] != remote[k]
    )
    only_remote = sorted(set(remote) - set(local))
    return to_upload, only_remote


# ── 打包并上传 ─────────────────────────────────────────────────────────────────

def _reject_database_paths(files: list[str]) -> None:
    """硬拒绝：即使上游逻辑疏漏，也禁止把 database/ 打入部署包。"""
    bad = [rel for rel in files if Path(rel).parts and Path(rel).parts[0] == "database"]
    if bad:
        raise ValueError(
            "部署包中不允许包含 database/ 下文件（避免覆盖生产库）：" + ", ".join(bad[:10])
            + (" …" if len(bad) > 10 else "")
        )


def make_tarball(files: list[str]) -> Path:
    """将指定文件打包（路径相对 LOCAL_BACKEND）为临时 tar.gz，包内保留相对路径。"""
    _reject_database_paths(files)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tf:
        tar_path = Path(tf.name)
    with tarfile.open(tar_path, "w:gz") as tar:
        for rel in files:
            local_f = LOCAL_BACKEND / Path(rel)
            tar.add(local_f, arcname=rel)
    return tar_path


def upload_and_extract(
    entry,
    tar_path: Path,
    remote_dir: str,
    unit_src: Path | None = None,
) -> int:
    """上传 tar.gz 并解压；若 unit_src 不为 None，同时上传 unit 文件并 daemon-reload。"""
    remote_tmp     = "/tmp/_ponychat_backend_deploy.tar.gz"
    remote_unit_tmp = "/tmp/_ponychat_backend_unit.service"

    rc = scp_to(entry, tar_path, remote_tmp)
    if rc != 0:
        return rc

    if unit_src is not None:
        rc = scp_to(entry, unit_src, remote_unit_tmp)
        if rc != 0:
            warn(f"unit 文件上传失败（exit {rc}），继续部署但 unit 未更新")
            unit_src = None   # 后续脚本跳过

    lines = [
        "set -e",
        f"cd {remote_dir}",
        f"tar -xzf {remote_tmp}",
        f"rm -f {remote_tmp}",
        "find . -name '*.pyc' -delete 2>/dev/null || true",
        "echo '[done] 解压完成'",
    ]
    if unit_src is not None:
        lines += [
            f"cp {remote_unit_tmp} {REMOTE_UNIT_FILE}",
            f"rm -f {remote_unit_tmp}",
            "systemctl daemon-reload",
            "echo '[done] unit 文件已更新，daemon-reload 完成'",
        ]
    return ssh_bash_s(entry, "\n".join(lines))


# ── 重启服务 ───────────────────────────────────────────────────────────────────

def detect_service(entry) -> str | None:
    """在服务器上找后端 systemd 服务名。"""
    _, out, _ = _ssh_capture(
        entry,
        "systemctl list-units --type=service --state=loaded --no-legend 2>/dev/null"
        " | awk '{print $1}'"
        " | grep -iE 'pony|ponychat' | head -5"
    )
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    return lines[0] if lines else None



def _ssh_restart_sync(entry, service: str) -> int:
    """同步执行 systemctl restart，等待服务进入 active 后再返回。
    专门为 restart 延长 SSH 保活（ServerAliveInterval=30 × 10 = 300s），
    避免后端初始化耗时超过默认 60s 保活导致 SSH exit 255 断开。
    """
    act_key, tmp = prepare_ssh_key(entry.key)
    try:
        args = (
            ["ssh"] + _no_proxy_args()
            + ["-i", str(act_key), "-p", str(entry.port)]
            + ["-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=10"]
            + ssh_common_opts()
            + [entry.target, f"systemctl restart {service}"]
        )
        result = subprocess.run(
            args, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=deploy_upload_env(), stdin=subprocess.DEVNULL,
        )
        return result.returncode
    finally:
        cleanup_temp_key(tmp)


def restart_service(entry, service: str) -> int:
    print(f"  重启服务 {service}（同步等待 active）...", flush=True)
    rc = _ssh_restart_sync(entry, service)
    if rc == 0:
        ok(f"服务 {service} 已重启并进入 active 状态")
    else:
        err(f"重启失败（exit {rc}），请手动检查：journalctl -u {service} -n 40")
    return rc


# ── 探活 ──────────────────────────────────────────────────────────────────────

def health_check(entry) -> None:
    print("  探活 http://127.0.0.1:5000/api/health ...", flush=True)
    _, out, _ = _ssh_capture(
        entry,
        "curl -sf --max-time 10 http://127.0.0.1:5000/api/health 2>&1 || echo '[FAIL]'",
    )
    resp = out.strip()
    if resp and "[FAIL]" not in resp:
        ok(f"后端响应正常: {resp[:80]}")
    else:
        warn(f"探活未返回预期响应: {resp[:120]!r}  （服务可能仍在启动）")


def _health_body_matches_deploy_token(body: str, expect: str) -> bool:
    try:
        data = json.loads(body.strip())
        return data.get("deploy_token") == expect
    except json.JSONDecodeError:
        return False


# ── 主流程 ─────────────────────────────────────────────────────────────────────

def check_py_syntax(files: list[str]) -> list[tuple[str, str]]:
    """对 to_upload 中的 .py 文件做本地语法检查，返回 [(rel_path, error_msg), ...]。"""
    import py_compile
    errors: list[tuple[str, str]] = []
    for rel in files:
        if not rel.endswith(".py"):
            continue
        local_f = LOCAL_BACKEND / Path(rel)
        try:
            py_compile.compile(str(local_f), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append((rel, str(e)))
    return errors


def main() -> int:
    TOTAL = 7
    t_wall0 = time.monotonic()
    phases: list[tuple[str, float]] = []

    def finish(code: int) -> int:
        _print_timing_summary(phases, t_wall0)
        return code

    print(f"\n{CYAN}{'='*55}{RESET}", flush=True)
    print(f"{CYAN}  PonyChat Backend — 增量部署到 Server-USA{RESET}", flush=True)
    print(f"{CYAN}{'='*55}{RESET}", flush=True)
    print(f"  本地路径: {LOCAL_BACKEND}", flush=True)

    entry = load_server("usa")
    print(f"  目标服务器: {entry.label}  ({entry.user}@{entry.host}:{entry.port})\n", flush=True)

    # ── 1. 定位远端 Backend ────────────────────────────────────────────────────
    step(1, TOTAL, "定位服务器 Backend 目录")
    _t = time.monotonic()
    remote_dir = find_remote_backend(entry)
    if not remote_dir:
        err("未找到服务器 Backend 目录，请确认部署路径。")
        return finish(1)
    ok(f"服务器 Backend: {remote_dir}")
    _phase_end("1 定位远端 Backend", _t, phases)

    deploy_token = secrets.token_hex(16)
    rev_path = LOCAL_BACKEND / ".deploy_revision"
    rev_path.write_text(
        json.dumps({"deploy_token": deploy_token}, ensure_ascii=False),
        encoding="utf-8",
    )
    info(f"本次 deploy_token（探活校验）: {deploy_token}")

    # ── 2. MD5 对比 ────────────────────────────────────────────────────────────
    step(2, TOTAL, "计算文件差异")
    _t = time.monotonic()
    remote_md5s, remote_unit_md5 = get_remote_md5s(entry, remote_dir)
    _phase_end("2a 远端 find+md5sum（含 unit 文件）", _t, phases)
    _t = time.monotonic()
    local_md5s = get_local_md5s()
    _phase_end("2b 本地 MD5", _t, phases)
    _t = time.monotonic()
    to_upload, only_remote = compute_diff(local_md5s, remote_md5s)
    _phase_end("2c 差异比对（内存）", _t, phases)

    # 检查 unit 文件是否需要更新（与远端 MD5 比对，无需额外 SSH）
    unit_needs_update = False
    if LOCAL_UNIT_FILE.exists():
        local_unit_md5 = hashlib.md5(LOCAL_UNIT_FILE.read_bytes()).hexdigest()
        if local_unit_md5 != remote_unit_md5:
            unit_needs_update = True
            marker = "（首次部署）" if not remote_unit_md5 else f"（本地 {local_unit_md5[:8]}… vs 远端 {remote_unit_md5[:8]}…）"
            info(f"  ★ systemd unit 文件已变更 {marker}，将随本次上传一并同步")
        else:
            info(f"  systemd unit 文件无变化（MD5 一致），跳过 unit 同步")

    info(f"本地文件（过滤后）: {len(local_md5s)} 个")
    info(f"服务器文件（过滤后）: {len(remote_md5s)} 个")

    if not to_upload:
        ok("本地与服务器完全一致，无需上传。")
    else:
        info(f"需上传（新增 + 变更）: {len(to_upload)} 个")
        for f in to_upload:
            marker = "+" if f not in remote_md5s else "~"
            info(f"  {marker} {f}")

    if only_remote:
        warn(f"仅服务器存在（本地已删除）{len(only_remote)} 个文件，本次不自动删除：")
        for f in only_remote:
            info(f"  - {f}")

    if not to_upload:
        # 已写入 .deploy_revision，至少会推送该文件并重启，以便探活校验新进程
        ok("除 deploy 令牌外无其它差异；将上传 .deploy_revision 并重启。")
        to_upload = [".deploy_revision"]

    # ── 3. Python 语法检查 ─────────────────────────────────────────────────────
    py_files = [f for f in to_upload if f.endswith(".py")]
    if py_files:
        step(3, TOTAL, f"Python 语法检查（{len(py_files)} 个 .py 文件）")
        _t = time.monotonic()
        syntax_errors = check_py_syntax(to_upload)
        _phase_end("3 py_compile 语法检查", _t, phases)
        if syntax_errors:
            for rel, msg in syntax_errors:
                err(f"语法错误：{rel}")
                info(f"    {msg}")
            err(f"共 {len(syntax_errors)} 个文件有语法错误，已中止部署。")
            return finish(1)
        ok(f"全部 {len(py_files)} 个 .py 文件语法正确")
    else:
        step(3, TOTAL, "Python 语法检查（无 .py 变更，跳过）")
        phases.append(("3 py_compile（跳过）", 0.0))

    # ── 4. 打包上传（含 unit 文件，若有变更） ──────────────────────────────────
    unit_src = LOCAL_UNIT_FILE if unit_needs_update else None
    step_label = f"打包并上传 {len(to_upload)} 个文件" + ("（含 unit 文件）" if unit_src else "")
    step(4, TOTAL, step_label)
    _t = time.monotonic()
    tar_path = make_tarball(to_upload)
    _phase_end("4a 本地打包 tar.gz", _t, phases)
    size_kb = tar_path.stat().st_size // 1024
    info(f"压缩包大小: {size_kb} KB")
    _t = time.monotonic()
    rc = upload_and_extract(entry, tar_path, remote_dir, unit_src=unit_src)
    _phase_end("4b scp + 远端解压" + ("+ unit 同步 + daemon-reload" if unit_src else ""), _t, phases)
    tar_path.unlink(missing_ok=True)
    if rc != 0:
        err(f"上传/解压失败（exit {rc}）")
        return finish(rc)
    ok("文件已同步到服务器" + ("（unit 文件已更新）" if unit_src else ""))

    # ── 5. 检测并重启服务 ──────────────────────────────────────────────────────
    step(5, TOTAL, "重启后端服务")
    _t = time.monotonic()
    service = detect_service(entry)
    _phase_end("5a systemctl 检测服务名", _t, phases)
    if service:
        info(f"检测到服务: {service}")
        _t = time.monotonic()
        rc = restart_service(entry, service)
        _phase_end("5b systemctl restart（阻塞至 active）", _t, phases)
        if rc != 0:
            return finish(rc)
    else:
        warn("未检测到 systemd 服务，尝试通用方式...")
        _t = time.monotonic()
        rc = ssh_exec(
            entry,
            "pkill -f 'python.*__main__' 2>/dev/null; sleep 1; "
            "cd $(dirname $(find /root /home /opt -name '__main__.py' 2>/dev/null "
            "| grep -i backend | head -1)) && "
            "nohup python -m Backend >> /tmp/ponychat_restart.log 2>&1 &",
        )
        _phase_end("5b 通用 pkill+nohup 重启", _t, phases)
        if rc == 0:
            ok("已尝试后台重启，请确认日志")
        else:
            warn("自动重启失败，请手动重启后端")

    # ── 6. 探活 ────────────────────────────────────────────────────────────────
    # systemctl restart 已同步阻塞到 active，此处只需校验 deploy_token 确认新代码已加载。
    step(6, TOTAL, "探活（校验 deploy_token 确认新代码已生效）")
    out_h = ""
    health_rounds = 0

    # 轮询 /api/health，直到返回本次 deploy_token（新进程启动时读取 .deploy_revision 写入）。
    # 同步重启后服务通常已 active，正常 1-2 轮即可命中；保留最多 60s 容错数据库初始化耗时。
    info("轮询 /api/health，确认 deploy_token 与本次部署一致...")
    _t6 = time.monotonic()
    health_ok = False
    for i in range(12):
        time.sleep(5)
        health_rounds = i + 1
        _rc_h, out_h, _ = _ssh_capture(
            entry, "curl -sf --max-time 5 http://127.0.0.1:5000/api/health 2>&1 || echo [FAIL]"
        )
        if "[FAIL]" not in out_h and out_h.strip():
            if _health_body_matches_deploy_token(out_h, deploy_token):
                health_ok = True
                ok(f"新进程已就绪，deploy_token 一致: {out_h.strip()[:100]}")
                break
            warn("健康检查已通，但 deploy_token 与本次部署不一致（可能仍为旧进程）；继续等待…")
            info(f"  响应片段: {out_h.strip()[:160]!r}")
        info(f"  等待中... ({health_rounds * 5}s / 60s)")
    _phase_end(f"6 探活（{health_rounds} 轮，每轮先睡5s+curl）", _t6, phases)
    if not health_ok:
        svc_hint = service or "ponychat-backend"
        warn(
            f"探活超时或 deploy_token 始终未匹配，最后响应: {out_h.strip()[:120]!r}\n"
            f"         请执行：journalctl -u {svc_hint} -n 60"
        )
        return finish(1)

    # ── 7. 完成 ────────────────────────────────────────────────────────────────
    step(7, TOTAL, "部署完成")
    ok("增量部署流程结束（新进程 deploy_token 已验证）。")
    return finish(0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消", flush=True)
        sys.exit(1)
    except Exception as e:
        import traceback
        err(f"部署异常: {e}")
        traceback.print_exc()
        sys.exit(1)
