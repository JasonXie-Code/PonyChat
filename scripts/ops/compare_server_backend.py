#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比对服务器 Backend 目录与本地代码仓库的差异。
用法: python scripts/ops/compare_server_backend.py
"""
import sys
import os
import subprocess
import hashlib
import json
from pathlib import Path

# Windows 控制台统一用 UTF-8 输出
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── 路径配置 ──────────────────────────────────────────────────────────────────
_THIS = Path(__file__).resolve()
_PROJ_ROOT = _THIS.parents[2]
_SERVERKEYS = _PROJ_ROOT.parent / "ServerKeys"
if not _SERVERKEYS.is_dir():
    # 备用：P:\ServerKeys
    _SERVERKEYS = Path("P:/ServerKeys")

sys.path.insert(0, str(_SERVERKEYS))
from ssh_lib import load_server, prepare_ssh_key, cleanup_temp_key, deploy_upload_env, _no_proxy_args, ssh_common_opts

LOCAL_BACKEND = _PROJ_ROOT / "Backend"

# 忽略的文件/目录（不参与比对）
IGNORE_DIRS = {
    "__pycache__", ".git", "backups", "data", "portrait_candidates",
    "refined", "refined_pony", "portrait", "tags.jsonl",
    "fetch_portrait_candidates_log.jsonl", "fetch_portraits_log.jsonl",
}
IGNORE_EXTS = {".pyc", ".pyo", ".db", ".log", ".lock", ".jpg", ".png",
               ".jpeg", ".gif", ".webp", ".mp3", ".mp4", ".zip", ".tar",
               ".gz", ".bz2", ".xz", ".7z", ".pem", ".ppk", ".pub"}
IGNORE_FILES = {
    "backend.log", "backend_access_full.log",
    ".backup_scheduler.lock",
}


def _ssh_capture(entry, remote_cmd: str) -> tuple[int, str, str]:
    """执行远端命令并捕获 stdout/stderr，返回 (rc, stdout, stderr)。"""
    act_key, tmp = prepare_ssh_key(entry.key)
    try:
        args = (["ssh"] + _no_proxy_args()
                + ["-i", str(act_key), "-p", str(entry.port)]
                + ssh_common_opts()
                + [entry.target, remote_cmd])
        env = deploy_upload_env()
        result = subprocess.run(args, capture_output=True, text=True,
                                encoding="utf-8", errors="replace",
                                env=env, stdin=subprocess.DEVNULL)
        return result.returncode, result.stdout, result.stderr
    finally:
        cleanup_temp_key(tmp)


def find_remote_backend(entry) -> str | None:
    """在服务器上搜索 Backend 目录（含 config.py）。"""
    print("  正在服务器上搜索 Backend 部署路径...")
    cmd = (
        "find /root /home /opt /srv /var/www /app 2>/dev/null "
        "-maxdepth 8 -name 'config.py' "
        r"| xargs grep -l 'PROJECT_ROOT\|BACKLOGS_DIR' 2>/dev/null "
        "| sed 's|/config\\.py||' | head -5"
    )
    rc, out, err = _ssh_capture(entry, cmd)
    lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
    if lines:
        return lines[0]
    # 备用：直接按目录名搜索
    cmd2 = (
        "find /root /home /opt /srv /app 2>/dev/null "
        "-maxdepth 6 -type d -name 'Backend' | head -5"
    )
    rc2, out2, _ = _ssh_capture(entry, cmd2)
    lines2 = [l.strip() for l in out2.strip().splitlines() if l.strip()]
    return lines2[0] if lines2 else None


def get_remote_md5s(entry, remote_dir: str) -> dict[str, str]:
    """获取服务器上 Backend 目录所有文件的 MD5（跳过忽略项）。"""
    print(f"  正在获取服务器文件 MD5：{remote_dir} ...")
    ignore_ext_str = " ".join(f"-o -name '*{e}'" for e in IGNORE_EXTS)
    ignore_dir_str = " ".join(
        f"-path '{remote_dir}/{d}' -prune -o" for d in IGNORE_DIRS
    )
    cmd = (
        f"find {remote_dir} "
        + " ".join(f"-path '{remote_dir}/{d}' -prune -o" for d in IGNORE_DIRS)
        + f" -type f ! -name '*.pyc' ! -name '*.pyo' ! -name '*.db'"
        + f" ! -name '*.log' ! -name '*.lock' ! -name '*.jpg' ! -name '*.jpeg'"
        + f" ! -name '*.png' ! -name '*.gif' ! -name '*.webp'"
        + f" ! -name '*.pem' ! -name '*.ppk' ! -name '*.pub'"
        + f" ! -name '*.zip' ! -name '*.tar' ! -name '*.gz'"
        + " -print0 2>/dev/null"
        + f" | xargs -0 md5sum 2>/dev/null"
    )
    rc, out, err = _ssh_capture(entry, cmd)
    result = {}
    prefix = remote_dir.rstrip("/") + "/"
    for line in out.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        md5, path = parts[0], parts[1].strip()
        rel = path.removeprefix(prefix)
        # 跳过忽略文件
        fname = Path(rel).name
        if fname in IGNORE_FILES:
            continue
        result[rel] = md5
    return result


def get_local_md5s() -> dict[str, str]:
    """计算本地 Backend 目录所有文件的 MD5。"""
    print(f"  正在计算本地文件 MD5：{LOCAL_BACKEND} ...")
    result = {}

    def _should_skip(p: Path) -> bool:
        if p.name in IGNORE_DIRS or p.name in IGNORE_FILES:
            return True
        if p.suffix in IGNORE_EXTS:
            return True
        # 检查祖先目录是否在忽略列表
        for part in p.relative_to(LOCAL_BACKEND).parts[:-1]:
            if part in IGNORE_DIRS:
                return True
        return False

    for f in LOCAL_BACKEND.rglob("*"):
        if not f.is_file():
            continue
        if _should_skip(f):
            continue
        rel = f.relative_to(LOCAL_BACKEND).as_posix()
        try:
            md5 = hashlib.md5(f.read_bytes()).hexdigest()
            result[rel] = md5
        except Exception:
            pass
    return result


def compare(local: dict, remote: dict, remote_dir: str):
    """输出对比结果。"""
    local_keys = set(local)
    remote_keys = set(remote)

    only_local = sorted(local_keys - remote_keys)
    only_remote = sorted(remote_keys - local_keys)
    both = local_keys & remote_keys
    different = sorted(k for k in both if local[k] != remote[k])
    same_count = sum(1 for k in both if local[k] == remote[k])

    print()
    print("=" * 70)
    print(f"  比对结果  本地: Backend/  vs  服务器: {remote_dir}")
    print("=" * 70)
    print(f"  相同文件: {same_count} 个")
    print()

    if different:
        print(f"【内容有差异】 {len(different)} 个文件")
        for f in different:
            print(f"    ~ {f}")
        print()

    if only_local:
        print(f"【仅本地存在（服务器缺少）】 {len(only_local)} 个文件")
        for f in only_local:
            print(f"    + {f}")
        print()

    if only_remote:
        print(f"【仅服务器存在（本地无此文件）】 {len(only_remote)} 个文件")
        for f in only_remote:
            print(f"    - {f}")
        print()

    if not different and not only_local and not only_remote:
        print("  ✅ 本地与服务器完全一致，无差异。")
    print("=" * 70)

    return {
        "different": different,
        "only_local": only_local,
        "only_remote": only_remote,
        "same_count": same_count,
    }


def main():
    print("【PonyChat Backend 服务器比对工具】")
    print(f"  本地路径: {LOCAL_BACKEND}")
    print()

    entry = load_server("usa")
    print(f"  目标服务器: {entry.target}:{entry.port}  ({entry.label})")
    print()

    # 1. 查找远端 Backend 路径
    remote_dir = find_remote_backend(entry)
    if not remote_dir:
        print("  ❌ 未能找到服务器上的 Backend 目录，请手动确认部署路径。")
        sys.exit(1)
    print(f"  ✅ 找到服务器 Backend: {remote_dir}")
    print()

    # 2. 获取远端 md5
    remote_md5s = get_remote_md5s(entry, remote_dir)
    print(f"  服务器文件数（过滤后）: {len(remote_md5s)}")

    # 3. 计算本地 md5
    local_md5s = get_local_md5s()
    print(f"  本地文件数（过滤后）:   {len(local_md5s)}")

    # 4. 比对输出
    result = compare(local_md5s, remote_md5s, remote_dir)

    # 5. 保存 JSON 报告（可选）
    report_path = _PROJ_ROOT / "var" / "server_diff_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "remote_dir": remote_dir,
            "local_dir": str(LOCAL_BACKEND),
            "different": result["different"],
            "only_local": result["only_local"],
            "only_remote": result["only_remote"],
            "same_count": result["same_count"],
        }, f, ensure_ascii=False, indent=2)
    print(f"\n  报告已保存: {report_path}")


if __name__ == "__main__":
    main()
