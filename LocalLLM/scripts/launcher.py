#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcher.py — LocalLLM 一键启动器
· 部署检查：验证所有依赖是否就绪，缺失时自动尝试修复
· 每次启动尝试查询 GitHub 上 llama.cpp 最新 release 并比对本地 build；网络失败则跳过在线检查
· 启动服务：读取 server/config.json，调用 llama-server.exe；端口就绪后可自动打开浏览器
· 启动时可交互选择 models/ 下的主模型（或使用 --model / --no-menu）
按 Ctrl+C 停止服务。
"""

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

# ── 强制 UTF-8 输出（防止 Windows GBK 终端乱码）────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 路径 ──────────────────────────────────────────────────────
ROOT    = Path(__file__).resolve().parent.parent
CFG     = ROOT / "server" / "config.json"
BIN_DIR = ROOT / "server" / "bin"
LOG_DIR = ROOT / "logs"
SERVER  = BIN_DIR / "llama-server.exe"
# 记录已成功对齐过的 GitHub release，避免「本地已是该次下载的最新但仍被反复提示更新」
LLAMA_INSTALLED_STATE = BIN_DIR / "llama_installed.json"

# llama.cpp 下载参数（更换版本只需改这两行）
# b8638+ 含 gemma4 等新型架构；低于此版本的 llama-server 会报 unknown model architecture
LLAMA_VERSION = "b8638"
LLAMA_CUDA    = "12.4"
GH_PROXY      = "https://ghfast.top"
LLAMA_RELEASE_BASE = "https://github.com/ggml-org/llama.cpp/releases/download"
GITHUB_RELEASES_LATEST_API = (
    "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
)

# ── 颜色 ──────────────────────────────────────────────────────
ANSI = platform.system() == "Windows" and os.system("") == 0  # 激活 Win10 ANSI
def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if ANSI or platform.system() != "Windows" else text

def ok(msg):    print(_c("32", f"  ✓ {msg}"))
def err(msg):   print(_c("31", f"  ✗ {msg}"))
def warn(msg):  print(_c("33", f"  ⚠ {msg}"))
def info(msg):  print(_c("36", f"  → {msg}"))
def section(t): print(f"\n[ {t} ]")

def _norm_rel(p: str) -> str:
    return p.replace("\\", "/").strip()

def discover_main_models() -> list[str]:
    """扫描 models/ 下可作为主模型的 .gguf（排除文件名含 mmproj 的视觉编码器）。"""
    models_dir = ROOT / "models"
    if not models_dir.is_dir():
        return []
    out: list[str] = []
    for p in sorted(models_dir.rglob("*.gguf")):
        if "mmproj" in p.name.lower():
            continue
        try:
            out.append(p.relative_to(ROOT).as_posix())
        except ValueError:
            continue
    return out

def mmproj_for_main_model(model_rel: str) -> str | None:
    """与主模型同目录下查找 mmproj（*.gguf 且文件名含 mmproj）。"""
    main = ROOT / model_rel.replace("/", os.sep)
    if not main.is_file():
        return None
    parent = main.parent
    for c in sorted(parent.glob("*.gguf")):
        if c.resolve() == main.resolve():
            continue
        if "mmproj" in c.name.lower():
            return c.relative_to(ROOT).as_posix()
    return None

def interactive_pick_model(cfg: dict) -> dict:
    """在终端列出可选主模型；选 0 表示完全沿用 config.json。"""
    default_rel = _norm_rel(cfg.get("model", ""))
    others = [p for p in discover_main_models() if _norm_rel(p) != default_rel]

    section("选择模型")
    print(_c("36", "  0) 使用 server/config.json 中的配置（不改动 model / mmproj）"))
    if default_rel:
        info(f"当前默认主模型: {default_rel}")
    if not others:
        warn("未发现其他主模型（可在 models/ 各子目录放置 .gguf，文件名勿含 mmproj）")
    else:
        for i, rel in enumerate(others, start=1):
            print(_c("37", f"  {i}) {rel}"))

    choice_raw = input(_c("36", "\n请输入序号后回车 [0]: ")).strip() or "0"
    if not choice_raw.isdigit():
        warn("输入无效，已改用配置文件默认")
        return cfg
    choice = int(choice_raw)
    if choice == 0:
        return cfg
    if choice < 1 or choice > len(others):
        warn("序号超出范围，已改用配置文件默认")
        return cfg

    rel = others[choice - 1]
    cfg = dict(cfg)
    cfg["model"] = rel
    mp = mmproj_for_main_model(rel)
    if mp:
        cfg["mmproj"] = mp
        ok(f"已选择主模型，并自动匹配同目录 mmproj: {mp}")
    else:
        cfg.pop("mmproj", None)
        ok("已选择主模型（同目录无 mmproj，以纯文本模式运行）")
    return cfg

def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    p = argparse.ArgumentParser(description="LocalLLM 一键启动器")
    p.add_argument(
        "--no-menu",
        action="store_true",
        help="不显示选单，直接使用 server/config.json",
    )
    p.add_argument(
        "--model",
        type=str,
        default=None,
        metavar="REL_PATH",
        help="指定主模型相对项目根的路径（使用 / 或 \\），不显示选单；同目录 mmproj 会自动匹配",
    )
    return p.parse_known_args(argv)

# ── 下载工具 ──────────────────────────────────────────────────
def _download(url: str, dest: Path, label: str):
    """带进度条的下载（使用系统 curl.exe，支持代理跳转）"""
    info(f"下载 {label}...")
    info(f"来源 {url}")
    try:
        subprocess.run(
            ["curl.exe", "-L", url, "-o", str(dest), "--progress-bar"],
            check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        # 回退：urllib
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                total = int(r.headers.get("Content-Length", 0))
                done  = 0
                with dest.open("wb") as f:
                    while chunk := r.read(256 * 1024):
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            pct = done * 100 // total
                            print(f"\r    {pct}%  {done//1024//1024} MB / {total//1024//1024} MB", end="")
            print()
            return True
        except Exception as e:
            err(f"下载失败: {e}")
            return False

def _parse_release_tag_to_build(tag: str) -> int | None:
    """将 GitHub tag（如 b8638）解析为构建号；无法识别则返回 None。"""
    if not tag or not isinstance(tag, str):
        return None
    t = tag.strip().lstrip("vV")
    m = re.match(r"^[bB]?(\d+)$", t)
    if m:
        return int(m.group(1))
    return None

def fetch_latest_llama_release() -> tuple[str | None, int | None]:
    """
    查询 ggml-org/llama.cpp 最新 release 的 tag 与构建号。
    网络故障、限流或解析失败时返回 (None, None)，由调用方跳过在线更新逻辑。
    """
    req = urllib.request.Request(
        GITHUB_RELEASES_LATEST_API,
        headers={
            "User-Agent": "LocalLLM-Launcher/1.0",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        tag = (data.get("tag_name") or "").strip()
        if not tag:
            return None, None
        bnum = _parse_release_tag_to_build(tag)
        if bnum is None:
            return None, None
        return tag, bnum
    except Exception:
        return None, None

def _download_and_extract(zip_name: str, label: str, *, release_tag: str) -> bool:
    base = f"{LLAMA_RELEASE_BASE}/{release_tag}"
    proxy_url = f"{GH_PROXY}/{base}/{zip_name}"
    tmp = Path(os.environ.get("TEMP", "/tmp")) / zip_name
    if not _download(proxy_url, tmp, label):
        return False
    info(f"解压 {zip_name} ...")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(tmp, "r") as z:
            z.extractall(BIN_DIR)
    except zipfile.BadZipFile:
        err(f"压缩包损坏或下载不完整: {zip_name}")
        return False
    return True

def _load_installed_state() -> dict | None:
    if not LLAMA_INSTALLED_STATE.exists():
        return None
    try:
        return json.loads(LLAMA_INSTALLED_STATE.read_text(encoding="utf-8"))
    except Exception:
        return None

def _save_installed_state(remote_tag: str, remote_build: int, local_build: int) -> None:
    try:
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        LLAMA_INSTALLED_STATE.write_text(
            json.dumps(
                {
                    "remote_tag": remote_tag,
                    "remote_build": remote_build,
                    "local_build_verified": local_build,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass

def _aligned_with_github_latest(
    local_b: int | None,
    remote_tag: str | None,
    remote_build: int | None,
    state: dict | None,
) -> bool:
    """
    是否已与「当前 GitHub releases/latest」对齐。
    · 以 llama-server 解析到的 build 为准（若能解析）
    · 仅当完全无法解析版本时，才采信 llama_installed.json，避免记录与磁盘旧文件不一致时误判
    """
    if remote_build is None:
        return False
    if local_b is not None and local_b >= remote_build:
        return True
    if local_b is None and state and state.get("remote_build") == remote_build:
        v = state.get("local_build_verified")
        if isinstance(v, int) and v >= remote_build:
            return True
    return False

# ── 检查项 ────────────────────────────────────────────────────
def check_nvidia() -> bool:
    section("检查 NVIDIA GPU")
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            for line in r.stdout.strip().splitlines():
                ok(line.strip())
            return True
    except FileNotFoundError:
        pass
    err("未检测到 NVIDIA 驱动，服务将以纯 CPU 模式运行（速度慢）")
    return False

def _required_llama_build() -> int:
    """LLAMA_VERSION 形如 b8638 → 8638"""
    return int(LLAMA_VERSION[1:])

def _decode_windows_console_bytes(raw: bytes | None) -> str:
    """tasklist 等输出在中文 Windows 下多为系统 ANSI（mbcs），勿默认按 UTF-8 解码。"""
    if not raw:
        return ""
    if platform.system() == "Windows":
        return raw.decode("mbcs", errors="replace")
    return raw.decode("utf-8", errors="replace")

def _detect_llama_server_build() -> int | None:
    """解析 llama-server --version 中的 build 号（对输出做字节级匹配，避免编码误判）。"""
    if not SERVER.exists():
        return None
    try:
        r = subprocess.run(
            [str(SERVER), "--version"],
            capture_output=True,
            timeout=15,
        )
        blob = (r.stdout or b"") + (r.stderr or b"")
        # 取最后一次匹配：前面可能有 CUDA/后端日志，避免误抓到非版本数字
        matches = re.findall(rb"(?:build|version):\s*(\d+)", blob, re.I)
        if matches:
            return int(matches[-1])
        # 回退：按常见控制台编码解码后再匹配
        text = _decode_windows_console_bytes(r.stdout) + _decode_windows_console_bytes(
            r.stderr
        )
        matches2 = re.findall(r"(?:build|version):\s*(\d+)", text, re.I)
        if matches2:
            return int(matches2[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None

def check_server_bin() -> bool:
    section("检查 llama.cpp server 二进制")
    min_build = _required_llama_build()
    remote_tag, remote_build = fetch_latest_llama_release()
    state = _load_installed_state()

    if remote_tag and remote_build is not None:
        ok(f"在线最新版本: {remote_tag}（build {remote_build}）")
    else:
        warn("无法获取 GitHub 最新版本（网络或接口限制），跳过在线比对；仅按本地与项目保底版本处理")

    target_tag = remote_tag if (remote_tag and remote_build is not None) else LLAMA_VERSION

    if SERVER.exists():
        b = _detect_llama_server_build()
        # 已与 GitHub releases/latest 对齐：解析成功 或 安装记录可佐证（避免误反复下载）
        if remote_build is not None and _aligned_with_github_latest(
            b, remote_tag, remote_build, state
        ):
            sz = SERVER.stat().st_size // 1024 // 1024
            if b is not None:
                tag = f"build {b}"
            else:
                tag = "版本未知（以安装记录为准）"
            ok(f"llama-server.exe 已就绪（{sz} MB，{tag}）")
            if b is not None:
                ok("已与当前在线最新版本一致")
            else:
                info("无法解析 exe 版本号，依据 llama_installed.json 视为已与在线最新一致")
            if remote_tag and remote_build is not None:
                lb = b if b is not None else (state or {}).get("local_build_verified")
                if isinstance(lb, int):
                    _save_installed_state(remote_tag, remote_build, lb)
            return True

        # 无远程信息时：只保证不低于项目保底版本
        if remote_build is None:
            if b is not None and b >= min_build:
                sz = SERVER.stat().st_size // 1024 // 1024
                ok(f"llama-server.exe 已就绪（{sz} MB，build {b}）")
                info("未进行在线版本比对")
                return True
            warn(f"当前低于项目保底 build {min_build}，将下载 {LLAMA_VERSION} ...")
        else:
            if b is not None:
                warn(f"本地 build {b}，将更新为在线最新 {target_tag}（下载完成后覆盖 server\\bin，不在下载前删除旧文件）...")
            else:
                warn(f"无法解析本地 build，将重新下载 {target_tag} ...")
        info("开始下载...")
    else:
        err("未找到 llama-server.exe，开始下载...")

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    ok1 = _download_and_extract(
        f"llama-{target_tag}-bin-win-cuda-{LLAMA_CUDA}-x64.zip",
        "llama.cpp 主二进制",
        release_tag=target_tag,
    )
    ok2 = _download_and_extract(
        f"cudart-llama-bin-win-cuda-{LLAMA_CUDA}-x64.zip",
        "CUDA 运行时 DLL",
        release_tag=target_tag,
    )
    if ok1 and SERVER.exists():
        b3 = _detect_llama_server_build()
        if remote_tag and remote_build is not None and b3 is not None:
            _save_installed_state(remote_tag, remote_build, b3)
            ok(f"下载完成（校验 build {b3}）")
        else:
            ok("下载完成")
        return True
    err("下载失败，请手动运行 scripts\\setup.ps1")
    return False

def check_cuda_dll() -> bool:
    section("检查 CUDA 运行时 DLL")
    dll = BIN_DIR / f"cudart64_{LLAMA_CUDA.replace('.', '')}.dll"
    # 兼容 cudart64_12.dll 命名
    candidates = list(BIN_DIR.glob("cudart64_*.dll"))
    if candidates:
        ok(f"{candidates[0].name} 已就绪（项目自包含）")
        return True
    warn("未找到 CUDA DLL，将依赖系统 CUDA 安装")
    _download_and_extract(
        f"cudart-llama-bin-win-cuda-{LLAMA_CUDA}-x64.zip",
        "CUDA 运行时 DLL",
        release_tag=LLAMA_VERSION,
    )
    return True  # 非致命，继续启动

def check_model(cfg: dict) -> tuple[bool, bool]:
    """返回 (主模型就绪, mmproj就绪)"""
    section("检查模型文件")
    model_path  = ROOT / cfg["model"].replace("/", os.sep)
    mmproj_path = ROOT / cfg.get("mmproj", "").replace("/", os.sep) if cfg.get("mmproj") else None

    model_ok = model_path.exists()
    if model_ok:
        size_gb = model_path.stat().st_size / 1024**3
        ok(f"主模型 {model_path.name}  ({size_gb:.1f} GB)")
    else:
        err(f"未找到主模型：{model_path}")
        info("请将 .gguf 文件放到 models\\Qwen3.5-9B\\ 目录")

    mmproj_ok = False
    if mmproj_path:
        if mmproj_path.exists():
            size_mb = mmproj_path.stat().st_size / 1024**2
            ok(f"视觉编码器 {mmproj_path.name}  ({size_mb:.0f} MB)")
            mmproj_ok = True
        else:
            warn(f"未找到 mmproj，多模态视觉功能将不可用")

    return model_ok, mmproj_ok

def check_dirs():
    section("初始化目录")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ok(f"logs\\ 目录已就绪")

def kill_existing_server():
    """杀掉所有已在运行的 llama-server.exe，释放显存后再启动新实例。"""
    section("清理旧进程")
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            timeout=5,
        )
        out = _decode_windows_console_bytes(r.stdout)
        pids = [
            line.split(",")[1].strip('"')
            for line in out.strip().splitlines()
            if "llama-server.exe" in line
        ]
    except Exception:
        pids = []

    if not pids:
        ok("无旧进程，跳过")
        return

    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/PID", pid],
                           capture_output=True, timeout=5)
        except Exception:
            pass
    warn(f"已终止 {len(pids)} 个旧进程（PID: {', '.join(pids)}）")

    # 等待显存实际释放（最多 10 秒）
    info("等待显存释放...")
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                timeout=5,
            )
            stdout = _decode_windows_console_bytes(r.stdout)
        except Exception:
            stdout = ""
        if "llama-server.exe" not in stdout:
            ok("显存已释放，准备启动")
            return
        time.sleep(0.5)
    warn("旧进程可能仍在释放显存，继续启动...")

# ── 启动服务 ──────────────────────────────────────────────────
def start_server(cfg: dict, has_mmproj: bool):
    model_path  = str(ROOT / cfg["model"].replace("/", os.sep))
    mmproj_path = str(ROOT / cfg["mmproj"].replace("/", os.sep)) if cfg.get("mmproj") else None
    log_file    = str(LOG_DIR / "server.log")
    gpu_layers  = cfg.get("n_gpu_layers", 99)

    args = [
        str(SERVER),
        "--host",         cfg.get("host", "127.0.0.1"),
        "--port",         str(cfg.get("port", 8080)),
        "--model",        model_path,
        "--alias",        cfg.get("alias", "qwen3.5-4b-local"),
        "--cache-type-k", "q8_0",
        "--cache-type-v", "q8_0",
        "--jinja",
        "--ctx-size",     str(cfg.get("n_ctx", 4096)),
        "--n-gpu-layers", str(gpu_layers),
        "--batch-size",   str(cfg.get("n_batch", 512)),
        "--threads",      str(cfg.get("n_threads", 6)),
        "--parallel",     str(cfg.get("parallel", 1)),
        "--n-predict",       str(cfg.get("n_predict", 8192)),
        "--reasoning-budget", str(cfg.get("reasoning_budget", -1)),
        "--flash-attn",      "auto",
        "--log-file",     log_file,
    ]
    if cfg.get("cont_batching"):
        args.append("--cont-batching")
    if has_mmproj and mmproj_path:
        args += ["--mmproj", mmproj_path]

    host = cfg.get("host", "127.0.0.1")
    port = cfg.get("port", 8080)

    print()
    print(_c("36", "╔══════════════════════════════════════════════╗"))
    print(_c("36", "║          LocalLLM Server 启动中              ║"))
    print(_c("36", "╚══════════════════════════════════════════════╝"))
    print()
    info(f"模型    : {cfg['model']}")
    info(f"多模态  : {'启用（mmproj）' if has_mmproj else '未启用'}")
    info(f"GPU层数 : {gpu_layers}  |  上下文: {cfg.get('n_ctx', 4096)} tokens")
    info(f"API地址 : http://{host}:{port}/v1/chat/completions")
    info(f"日志    : logs\\server.log")
    print()
    info("按 Ctrl+C 停止服务")
    print()
    print(_c("36", "─" * 50))
    print(_c("36", "  服务器日志输出 ↓"))
    print(_c("36", "─" * 50))
    sys.stdout.flush()

    # 日志同时输出到终端和文件：
    # · llama-server 的 stdout/stderr 直接继承当前终端（用户能看到所有日志）
    # · --log-file 参数让服务器额外写一份到 logs/server.log
    try:
        proc = subprocess.Popen(args, cwd=str(ROOT))
        _wait_ready(
            host,
            port,
            open_browser=bool(cfg.get("open_browser", True)),
        )
        proc.wait()
    except KeyboardInterrupt:
        print()
        print(_c("36", "─" * 50))
        ok("服务已停止")
    except FileNotFoundError:
        err(f"找不到可执行文件：{SERVER}")
        sys.exit(1)

def _public_browser_host(host: str) -> str:
    """浏览器无法访问 0.0.0.0，统一改为本机回环。"""
    if host in ("0.0.0.0", "::", "::0"):
        return "127.0.0.1"
    return host

def _wait_ready(host: str, port: int, *, open_browser: bool = True, timeout: int = 60):
    import socket
    deadline = time.time() + timeout
    browse_host = _public_browser_host(host)
    connect_host = browse_host  # 监听 0.0.0.0 时应用 127.0.0.1 探测端口
    base_url = f"http://{browse_host}:{port}/"
    while time.time() < deadline:
        try:
            with socket.create_connection((connect_host, port), timeout=1):
                print()
                ok(f"服务已就绪 → http://{host}:{port}")
                ok(f"测试命令  → tools\\python\\python.exe scripts\\test_api.py")
                info("端口已通；模型可能仍在加载，请以日志为准（勿仅凭本行判断加载成功）")
                if open_browser:
                    info(f"正在打开浏览器: {base_url}")
                    try:
                        webbrowser.open(base_url)
                    except Exception:
                        warn("无法自动打开浏览器，请手动访问上述地址")
                return
        except OSError:
            time.sleep(1)

# ── 主流程 ────────────────────────────────────────────────────
def main():
    os.chdir(ROOT)

    print()
    print(_c("36", "═" * 50))
    print(_c("36", "  LocalLLM — 一键启动器"))
    print(_c("36", "═" * 50))

    args, unknown = parse_args(sys.argv[1:])
    if unknown:
        warn(f"未识别的参数已忽略: {' '.join(unknown)}")

    # 读取配置
    if not CFG.exists():
        err(f"配置文件不存在：{CFG}")
        sys.exit(1)
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    # 去掉以 _ 开头的注释键
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}

    # 命令行指定主模型（不显示选单）
    if args.model:
        cfg = dict(cfg)
        rel = _norm_rel(args.model)
        cfg["model"] = rel
        mp = mmproj_for_main_model(rel)
        if mp:
            cfg["mmproj"] = mp
            ok(f"--model 已应用，同目录 mmproj: {mp}")
        else:
            cfg.pop("mmproj", None)
            info("--model 已应用（同目录无 mmproj）")
    # 交互选模型（需终端；与 --no-menu / --model 互斥）
    elif not args.no_menu and sys.stdin.isatty() and sys.stdout.isatty():
        cfg = interactive_pick_model(cfg)

    # 检查各项
    check_nvidia()
    bin_ok    = check_server_bin()
    check_cuda_dll()
    model_ok, mmproj_ok = check_model(cfg)
    check_dirs()
    kill_existing_server()

    # 汇总
    print()
    print(_c("36", "═" * 50))
    if not bin_ok:
        err("llama-server.exe 不可用，无法启动，请检查网络或手动下载")
        input("\n按回车退出...")
        sys.exit(1)
    if not model_ok:
        err("主模型文件缺失，无法启动")
        input("\n按回车退出...")
        sys.exit(1)

    ok(f"部署检查完成，即将启动服务...")
    print(_c("36", "═" * 50))

    time.sleep(1)
    start_server(cfg, mmproj_ok)

    input("\n按回车退出...")

if __name__ == "__main__":
    main()
