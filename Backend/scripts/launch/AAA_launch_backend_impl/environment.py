"""
AI 角色扮演对话 - Python 后端服务入口
支持多种 AI 模型提供商的统一推理服务
"""

import os
import sys
import psutil
import threading
import shutil
import logging
import atexit
import time
import re
import ssl
import traceback
import http.client
import socket
import select
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime

# 配置日志（在导入其他模块之前）
import sys

# 尝试安装并导入 colorama
try:
    import colorama
    colorama.init(autoreset=True)
    HAS_COLORAMA = True
except ImportError:
    # 尝试安装 colorama
    try:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "colorama"])
        import colorama
        colorama.init(autoreset=True)
        HAS_COLORAMA = True
    except:
        HAS_COLORAMA = False

# 颜色处理类
class Colors:
    def __init__(self):
        if HAS_COLORAMA:
            self.BLACK = colorama.Fore.BLACK
            self.RED = colorama.Fore.RED
            self.GREEN = colorama.Fore.GREEN
            self.YELLOW = colorama.Fore.YELLOW
            self.BLUE = colorama.Fore.BLUE
            self.MAGENTA = colorama.Fore.MAGENTA
            self.CYAN = colorama.Fore.CYAN
            self.WHITE = colorama.Fore.WHITE
            self.RESET = colorama.Style.RESET_ALL
        else:
            # 备用 ANSI 转义序列
            self.BLACK = '\033[30m'
            self.RED = '\033[31m'
            self.GREEN = '\033[32m'
            self.YELLOW = '\033[33m'
            self.BLUE = '\033[34m'
            self.MAGENTA = '\033[35m'
            self.CYAN = '\033[36m'
            self.WHITE = '\033[37m'
            self.RESET = '\033[0m'

# 创建颜色实例
colors = Colors()

# 保存原始的stdout引用（在重定向之前）
import sys
import types
from pathlib import Path as _Path

# 仓库根（含 Backend/ 与 misc/tools）；config.PROJECT_ROOT = dirname(Backend) 亦为该目录
_launch_parent = _Path(__file__).resolve().parent
if _launch_parent.name == "launch" and _launch_parent.parent.name == "scripts":
    _backend_dir = _launch_parent.parent.parent
    _proj_root = _backend_dir.parent
else:
    _backend_dir = _launch_parent
    _proj_root = _backend_dir.parent
os.chdir(_proj_root)
_proj_root_s = str(_proj_root)
if _proj_root_s not in sys.path:
    sys.path.insert(0, _proj_root_s)

# 物理目录名为 Backend，import 名为 backend；Windows 上大小写不自动等同，须用 importlib 显式加载
import importlib.util as _ilu
_backend_init_file = str(_backend_dir / "__init__.py")
_backend_spec = _ilu.spec_from_file_location(
    "backend",
    _backend_init_file,
    submodule_search_locations=[str(_backend_dir)],
)
_backend_pkg = _ilu.module_from_spec(_backend_spec)
_backend_pkg.__path__ = [str(_backend_dir)]
sys.modules["backend"] = _backend_pkg

from backend.config import BACKLOGS_DIR, CERTS_DIR

BACKEND_LOG_FILE = os.path.join(BACKLOGS_DIR, "backend.log")
ACCESS_FULL_LOG_FILE = os.path.join(BACKLOGS_DIR, "backend_access_full.log")


def _launcher_project_root() -> str:
    """与 chdir 后仓库根一致（含 Backend/）；支持脚本位于 scripts/launch/。"""
    p = _Path(__file__).resolve().parent
    if p.name == "launch" and p.parent.name == "scripts":
        return str(p.parent.parent.parent)
    return str(p.parent)


def _repo_root_for_misc() -> _Path:
    """含 misc/tools 的仓库根（与 Backend 同级）；勿使用 Backend 目录拼接 misc。"""
    p = _Path(__file__).resolve().parent
    for _ in range(18):
        if (p / "misc" / "tools").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    raise RuntimeError(
        "未找到 misc/tools。请将嵌入式工具链放在仓库根目录 misc/tools/（jdk、android-sdk、python 等）。"
    )


_original_stdout = sys.stdout
_original_stderr = sys.stderr

# 直接的彩色日志系统
class ColoredLogger:
    """
    带颜色的日志系统
    """
    def __init__(self):
        os.makedirs(BACKLOGS_DIR, exist_ok=True)
        self.log_file = BACKEND_LOG_FILE
        # 只有主进程才清空日志文件
        import sys
        if os.environ.get('RUN_MAIN') != 'true':  # 不是uvicorn子进程
            if os.path.exists(self.log_file):
                try:
                    open(self.log_file, 'w').close()
                except Exception:
                    pass
    
    def _format_message(self, level, message):
        """
        格式化带颜色的消息
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if level == 'INFO':
            color = colors.GREEN
        elif level == 'WARNING':
            color = colors.YELLOW
        elif level == 'ERROR':
            color = colors.RED
        else:
            color = colors.WHITE
        
        # 控制台输出（带颜色）
        console_msg = f"{timestamp} - {color}{level}{colors.RESET} - {message}"
        
        # 文件输出（无颜色）
        file_msg = f"{timestamp} - {level} - {message}"
        
        return console_msg, file_msg
    
    def info(self, message):
        """
        记录INFO级别日志
        """
        console_msg, file_msg = self._format_message('INFO', message)
        if not _access_tail_pause_event.is_set():
            _original_stdout.write(console_msg + '\n')
            _original_stdout.flush()
    
    def warning(self, message):
        """
        记录WARNING级别日志
        """
        console_msg, file_msg = self._format_message('WARNING', message)
        if not _access_tail_pause_event.is_set():
            _original_stdout.write(console_msg + '\n')
            _original_stdout.flush()
    
    def error(self, message):
        """
        记录ERROR级别日志
        """
        console_msg, file_msg = self._format_message('ERROR', message)
        # 直接写入原始stderr，避免循环
        _original_stderr.write(console_msg + '\n')
        _original_stderr.flush()

# 创建彩色日志实例
logger = ColoredLogger()

# 启动器单实例锁（仅主进程使用；热重载子进程 RUN_MAIN=true 不参与）
_launcher_lock_fp = None


def _terminate_process_tree(pid: int, reason: str = ""):
    """终止指定 PID 及其子进程，避免残留 reloader/worker。"""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return

    children = proc.children(recursive=True)
    # 先优雅终止子进程，再终止父进程
    for child in children:
        try:
            child.terminate()
        except Exception:
            pass
    try:
        proc.terminate()
    except Exception:
        pass

    gone, alive = psutil.wait_procs(children + [proc], timeout=3)
    if alive:
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass

    tip = f" ({reason})" if reason else ""
    logger.warning(f"⚠️  已清理旧后端进程树 PID={pid}{tip}")


def _cleanup_stale_launcher_processes():
    """
    清理残留的 AAA_launch_backend.py 进程（主进程 + reloader/worker）。
    仅在主进程执行，避免影响热重载子进程。
    """
    current_pid = os.getpid()
    target_name = os.path.basename(__file__).lower()
    stale_roots = []
    excluded = {current_pid}
    try:
        current_proc = psutil.Process(current_pid)
        for parent in current_proc.parents():
            excluded.add(parent.pid)
        for child in current_proc.children(recursive=True):
            excluded.add(child.pid)
    except Exception:
        pass

    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            pid = p.info['pid']
            if pid in excluded:
                continue
            cmdline = p.info.get('cmdline') or []
            cmd = " ".join(cmdline).lower()
            # 仅匹配同启动脚本，避免误伤其他 python 任务
            if target_name in cmd:
                stale_roots.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            continue

    # 去重并稳定排序，避免重复清理
    for pid in sorted(set(stale_roots)):
        _terminate_process_tree(pid, reason="stale launcher")


def _acquire_launcher_lock():
    """
    获取启动器单实例锁，保证同时只有一个主启动器在跑。
    - 主进程（RUN_MAIN!=true）必须持锁
    - 热重载子进程（RUN_MAIN=true）跳过锁
    """
    global _launcher_lock_fp

    if os.environ.get('RUN_MAIN') == 'true':
        return True

    lock_dir = BACKLOGS_DIR
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, 'backend_launcher.lock')

    try:
        fp = open(lock_path, 'a+', encoding='utf-8')
    except Exception as e:
        logger.warning(f"⚠️  无法创建启动器锁文件: {e}")
        return True

    try:
        import msvcrt
        fp.seek(0)
        # 锁定首字节，非阻塞
        msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
        fp.seek(0)
        fp.truncate()
        fp.write(str(os.getpid()))
        fp.flush()
        _launcher_lock_fp = fp

        def _release():
            global _launcher_lock_fp
            try:
                if _launcher_lock_fp:
                    _launcher_lock_fp.seek(0)
                    msvcrt.locking(_launcher_lock_fp.fileno(), msvcrt.LK_UNLCK, 1)
                    _launcher_lock_fp.close()
            except Exception:
                pass
            _launcher_lock_fp = None

        atexit.register(_release)
        return True
    except OSError:
        # 锁冲突：先关闭当前 fp，用 psutil 找到所有旧启动器进程并杀掉，再删锁文件重建
        try:
            fp.close()
        except Exception:
            pass

        current_pid = os.getpid()
        target_name = os.path.basename(__file__).lower()
        killed = []
        for proc in psutil.process_iter(['pid', 'cmdline']):
            if proc.pid == current_pid:
                continue
            try:
                cmdline = " ".join(proc.info['cmdline'] or []).lower()
                if target_name in cmdline:
                    killed.append(proc.pid)
                    _terminate_process_tree(proc.pid, reason="replaced by new launcher")
            except Exception:
                pass

        if killed:
            logger.warning(f"⚠️  已终止旧后端启动器进程: {killed}，等待释放锁文件...")
        else:
            logger.warning("⚠️  未找到旧启动器进程，尝试强制删除锁文件后重建...")

        import time as _time

        # 等旧进程完全退出后文件句柄才会释放，最多等 4 秒
        for _ in range(8):
            _time.sleep(0.5)
            try:
                os.remove(lock_path)
                break  # 删除成功则跳出
            except Exception:
                pass  # 旧进程还未完全退出，继续等待

        try:
            fp2 = open(lock_path, 'a+', encoding='utf-8')
            fp2.seek(0)
            msvcrt.locking(fp2.fileno(), msvcrt.LK_NBLCK, 1)
            fp2.seek(0)
            fp2.truncate()
            fp2.write(str(os.getpid()))
            fp2.flush()
            _launcher_lock_fp = fp2

            def _release():
                global _launcher_lock_fp
                try:
                    if _launcher_lock_fp:
                        _launcher_lock_fp.seek(0)
                        msvcrt.locking(_launcher_lock_fp.fileno(), msvcrt.LK_UNLCK, 1)
                        _launcher_lock_fp.close()
                except Exception:
                    pass
                _launcher_lock_fp = None

            atexit.register(_release)
            logger.info("✅  旧进程已终止，启动器锁已接管。")
            return True
        except Exception as retry_err:
            logger.error(f"重试获取启动器锁失败: {retry_err}，放弃启动。")
            return False

# 不再重定向 logging/sys.stdout/sys.stderr，避免与 uvicorn reload/access 日志链路冲突。
# 后端统一日志配置在 backend/config.py 中维护（文件 + 控制台）。

# 导入配置和应用实例
from backend.config import app
from backend import websocket
from backend.routes import (
    auth,
    chat,
    characters,
    models_api,
    admin,
    system,
    status,
)

# 执行 Backend/__init__.py：注册所有路由、静态文件挂载及 WebSocket 端点
if _backend_spec.loader:
    _backend_spec.loader.exec_module(_backend_pkg)


def save_logs():
    """
    保存服务器日志文件到 var/backlogs（或旧 .BackLogs）目录（备份当前日志）
    """
    backlog_dir = BACKLOGS_DIR
    os.makedirs(backlog_dir, exist_ok=True)
    
    source_backend_log = BACKEND_LOG_FILE
    source_access_full_log = ACCESS_FULL_LOG_FILE
    if not os.path.exists(source_backend_log) and not os.path.exists(source_access_full_log):
        logger.warning("⚠️  未找到可保存的日志文件，无法保存日志")
        return False
    
    try:
        # 刷新所有 logger 的处理器，确保后端日志 + uvicorn access 全量日志都已落盘
        seen_handlers = set()
        for logger_obj in [logging.getLogger()] + [
            lg for lg in logging.Logger.manager.loggerDict.values() if isinstance(lg, logging.Logger)
        ]:
            for handler in getattr(logger_obj, "handlers", []):
                try:
                    handler_id = id(handler)
                    if handler_id in seen_handlers:
                        continue
                    seen_handlers.add(handler_id)
                    handler.flush()
                except Exception:
                    pass
        
        # 生成带时间戳的日志文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        dest_log = os.path.join(backlog_dir, f'backend_{timestamp}.log')
        
        # 合并导出：backend.log（业务日志）+ backend_access_full.log（含完整 access/job 轮询）
        with open(dest_log, "w", encoding="utf-8", errors="replace") as out_fp:
            out_fp.write(f"# PonyChat 完整日志导出\n# 时间: {timestamp}\n\n")
            if os.path.exists(source_backend_log):
                out_fp.write(f"===== {BACKEND_LOG_FILE} =====\n")
                with open(source_backend_log, "r", encoding="utf-8", errors="replace") as src_fp:
                    shutil.copyfileobj(src_fp, out_fp)
                out_fp.write("\n\n")
            if os.path.exists(source_access_full_log):
                out_fp.write(f"===== {ACCESS_FULL_LOG_FILE} =====\n")
                with open(source_access_full_log, "r", encoding="utf-8", errors="replace") as src_fp:
                    shutil.copyfileobj(src_fp, out_fp)
                out_fp.write("\n")
        
        logger.info(f"✅ 完整日志已保存到: {dest_log}")
        return True
    except Exception as e:
        logger.error(f"❌ 保存日志时出错: {e}")
        return False


def print_console_help():
    """打印控制台所有可用指令（启动时与输入 help 时共用）。"""
    lines = [
        "",
        "  ─── 控制台可用指令 ───",
        "  log           保存完整日志到 var/backlogs（含 job 轮询访问日志）",
        "  tm            测试模型大厅可见模型可用性",
        "  tma           测试全部可见模型（含绘画模型）",
        "  backups       列出数据库备份（1=最新，需服务已启动）",
        "  restore <序号>    恢复第 N 个备份，如 restore 1",
        "  restore <文件名>  恢复指定备份，如 restore backup_20260212_120000.db",
        "  help 或 ? 或 h  再次显示本说明",
        "  ─────────────────────",
        "",
    ]
    for line in lines:
        print(line)


_access_tail_started = False
_access_tail_stop_event = threading.Event()
_access_tail_pause_event = threading.Event()   # 置位 = 暂停回显（菜单交互期间）
_access_tail_thread = None


class UvicornAccessNoiseFilter(logging.Filter):
    """
    过滤高频且成功的轮询访问日志，避免控制台刷屏。
    仅屏蔽 /api/chat/job/* 的 <400 状态码访问日志，错误请求仍保留。
    """
    _job_poll_fallback_pattern = re.compile(
        r'"[A-Z]+ (/api/chat/job/[^"]*) HTTP/\d+(?:\.\d+)?"\s+(\d{3})'
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # uvicorn.access 常见 args:
            # （client_addr, method, full_path, http_version, status_code）
            args = getattr(record, "args", ())
            if isinstance(args, tuple) and len(args) >= 5:
                full_path = str(args[2] or "")
                try:
                    status_code = int(args[4])
                except Exception:
                    status_code = 0
                if full_path.startswith("/api/chat/job/") and status_code < 400:
                    return False
                return True

            # 兜底：按格式化后的文本匹配
            msg = record.getMessage()
            m = self._job_poll_fallback_pattern.search(msg)
            if not m:
                return True
            try:
                status_code = int(m.group(2))
            except Exception:
                return True
            return status_code >= 400
        except Exception:
            # 过滤器异常时不影响正常日志输出
            return True


class UvicornRuntimeNoiseFilter(logging.Filter):
    """
    过滤已知的协议探测噪声日志，避免误导排障：
    - Invalid HTTP request received.
    - Windows Proactor 在协议错配断连时的 WinError 10022 清理异常
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage() or ""

            if "Invalid HTTP request received." in msg:
                return False

            if "_ProactorBasePipeTransport._call_connection_lost" in msg:
                if "WinError 10022" in msg:
                    return False
                if record.exc_info:
                    exc_text = "".join(traceback.format_exception(*record.exc_info))
                    if "WinError 10022" in exc_text:
                        return False
        except Exception:
            return True
        return True


def start_access_log_tail(log_file: str | None = None):
    """
    将 backend.log 的新增日志行全量回显到当前控制台。
    解决 Windows + reload 下子进程日志不稳定回显到启动终端的问题。
    """
    global _access_tail_started, _access_tail_thread
    if log_file is None:
        log_file = BACKEND_LOG_FILE
    if _access_tail_started:
        return
    _access_tail_started = True

    def _colorize_console_line(msg: str) -> str:
        """仅给控制台回显上色，不改文件日志原文。"""
        mappings = [
            (" - DEBUG - ", colors.CYAN),
            (" - INFO - ", colors.GREEN),
            (" - WARNING - ", colors.YELLOW),
            (" - ERROR - ", colors.RED),
            (" - CRITICAL - ", colors.MAGENTA),
            (" - DEBUG:     ", colors.CYAN),
            (" - INFO:     ", colors.GREEN),
            (" - WARNING:     ", colors.YELLOW),
            (" - ERROR:     ", colors.RED),
            (" - CRITICAL:     ", colors.MAGENTA),
        ]
        for token, color in mappings:
            if token in msg:
                return msg.replace(token, f" - {color}{token[3:-3].strip()}{colors.RESET} - ", 1) if token.endswith(" - ") else msg.replace(token, f" - {color}{token[3:].strip()}{colors.RESET} ", 1)
        return msg

    # 轮询接口日志过滤：/api/chat/job 仅在错误状态码时回显（避免 200 轮询刷屏）
    job_poll_line_pattern = re.compile(
        r'"[A-Z]+ /api/chat/job/[^"]* HTTP/\d+(?:\.\d+)?"\s+(\d{3})'
    )

    def _should_echo_console_line(msg: str) -> bool:
        if "Invalid HTTP request received." in msg:
            return False
        if "_ProactorBasePipeTransport._call_connection_lost" in msg and "WinError 10022" in msg:
            return False
        m = job_poll_line_pattern.search(msg)
        if not m:
            return True
        try:
            status_code = int(m.group(1))
        except Exception:
            return False
        return status_code >= 400

    def _tail():
        fp = None
        try:
            while not _access_tail_stop_event.is_set():
                # 暂停期间（菜单交互）不回显日志，持续等待直到恢复
                if _access_tail_pause_event.is_set():
                    time.sleep(0.1)
                    continue
                try:
                    if not os.path.exists(log_file):
                        time.sleep(0.2)
                        continue
                    if fp is None:
                        fp = open(log_file, "r", encoding="utf-8", errors="replace")
                        fp.seek(0, os.SEEK_END)

                    line = fp.readline()
                    if not line:
                        time.sleep(0.15)
                        continue

                    msg = line.rstrip("\r\n")
                    if msg:
                        if not _should_echo_console_line(msg):
                            continue
                        if _access_tail_stop_event.is_set() or sys.is_finalizing():
                            break
                        # 写入前再检查一次 pause，消除"读到行 → 暂停生效 → 仍写入"的竞态
                        if _access_tail_pause_event.is_set():
                            continue
                        _original_stdout.write(_colorize_console_line(msg) + "\n")
                        _original_stdout.flush()
                except Exception:
                    # 文件重建/轮转时重开
                    try:
                        if fp:
                            fp.close()
                    except Exception:
                        pass
                    fp = None
                    time.sleep(0.3)
        finally:
            try:
                if fp:
                    fp.close()
            except Exception:
                pass

    _access_tail_thread = threading.Thread(target=_tail, daemon=False, name="access-log-tail")
    _access_tail_thread.start()


def stop_access_log_tail(timeout: float = 1.5):
    """停止 access 日志回显线程，避免解释器退出阶段并发写 stdout。"""
    global _access_tail_thread, _access_tail_started
    _access_tail_stop_event.set()
    t = _access_tail_thread
    if t and t.is_alive():
        try:
            t.join(timeout=timeout)
        except Exception:
            pass
    _access_tail_thread = None
    _access_tail_started = False


class _SuppressAllFilter(logging.Filter):
    """进入交互菜单时临时屏蔽所有日志的控制台输出。"""
    def filter(self, record: logging.LogRecord) -> bool:
        return False

_suppress_console_filter = _SuppressAllFilter()
_suppressed_console_handlers: list = []


def _collect_console_handlers() -> list:
    """收集所有向终端（stdout/stderr）写入的 StreamHandler（不含 FileHandler）。"""
    seen = set()
    result = []
    all_loggers = [logging.getLogger()] + [
        lg for lg in logging.Logger.manager.loggerDict.values()
        if isinstance(lg, logging.Logger)
    ]
    for lgr in all_loggers:
        for handler in lgr.handlers:
            if id(handler) in seen:
                continue
            if isinstance(handler, logging.FileHandler):
                continue
            if isinstance(handler, logging.StreamHandler):
                seen.add(id(handler))
                result.append(handler)
    return result


def pause_access_log_tail():
    """暂停日志回显（进入交互菜单时调用），不终止线程。"""
    global _suppressed_console_handlers
    _access_tail_pause_event.set()
    # 同时给所有控制台 handler 加上全屏蔽过滤器，阻止 uvicorn 直接写入终端
    _suppressed_console_handlers = _collect_console_handlers()
    for h in _suppressed_console_handlers:
        h.addFilter(_suppress_console_filter)


def resume_access_log_tail():
    """恢复日志回显（退出交互菜单时调用）。"""
    global _suppressed_console_handlers
    _access_tail_pause_event.clear()
    for h in _suppressed_console_handlers:
        try:
            h.removeFilter(_suppress_console_filter)
        except Exception:
            pass
    _suppressed_console_handlers = []


def _api_backups(port: int):
    """请求本机管理接口列出备份，返回 (success, message_or_list)。"""
    try:
        import urllib.request
        import json
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/admin/backups",
            method="GET",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data.get("success"):
            return False, data.get("message", "请求失败")
        backups = data.get("backups") or []
        return True, backups
    except Exception as e:
        return False, str(e)


def _api_restore(port: int, backup_file: str = None, backup_index: int = None):
    """请求本机管理接口恢复指定备份，返回 (success, message)。"""
    try:
        import urllib.request
        import json
        body = {}
        if backup_file is not None:
            body["backup_file"] = backup_file
        if backup_index is not None:
            body["backup_index"] = backup_index
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/admin/restore",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("success"):
            return True, data.get("message", "恢复成功") + " " + data.get("restored_from", "")
        return False, data.get("message", "恢复失败")
    except Exception as e:
        return False, str(e)


def _api_test_models(port: int, mode: str = "chat"):
    """请求本机接口批量测试模型，返回 (success, message_or_list)。"""
    try:
        import urllib.request
        import json

        # 先获取模型列表用于 id->name 映射（展示更友好）
        req_models = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/models",
            method="GET",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req_models, timeout=8) as resp:
            models_data = json.loads(resp.read().decode("utf-8"))
        model_map = {m.get("id"): m.get("name", m.get("id", "")) for m in (models_data.get("models") or [])}

        payload = json.dumps({"mode": mode}).encode("utf-8")
        req_test = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/models/test_all",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req_test, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("status") != "success":
            return False, data.get("message", "模型测试失败")

        results = data.get("results") or {}
        rows = []
        for model_id, result in results.items():
            rows.append({
                "id": model_id,
                "name": model_map.get(model_id, model_id),
                "available": bool(result.get("available")),
                "message": str(result.get("message", "")),
            })
        return True, rows
    except Exception as e:
        return False, str(e)


def input_listener(port: int):
    """
    监听用户输入的线程函数
    - log: 保存日志到 var/backlogs
    - tm: 测试模型大厅可见模型可用性
    - tma: 测试全部可见模型（含绘画模型）
    - backups: 列出当前备份（需服务已启动）
    - restore <序号>: 恢复第 N 个备份（1 为最新）
    - restore <文件名>: 恢复指定备份文件
    """
    while True:
        try:
            user_input = input().strip()
            if not user_input:
                continue
            lower = user_input.lower()
            if lower == "log":
                save_logs()
                continue
            if lower in ("tm", "tma"):
                if lower == "tm":
                    print("开始测试模型大厅中的模型")
                    mode = "chat"
                else:
                    print("开始测试所有可见模型（包括绘画模型）")
                    mode = "all"

                ok, out = _api_test_models(port, mode=mode)
                if not ok:
                    logger.warning(f"🧪 模型测试失败: {out}")
                    print(f"🧪 模型测试失败: {out}")
                else:
                    total = len(out)
                    available = sum(1 for x in out if x["available"])
                    print(f"🧪 模型大厅测试完成：{total} 个模型，{available} 个可用")
                    for item in out:
                        status = "✅ 可用" if item["available"] else "❌ 不可用"
                        msg = item["message"] or "-"
                        print(f"  {status}  {item['name']} ({item['id']})")
                        if not item["available"]:
                            print(f"      原因: {msg}")
                continue
            if lower == "backups":
                ok, out = _api_backups(port)
                if not ok:
                    logger.warning(f"📋 获取备份列表失败: {out}")
                    print(f"📋 获取备份列表失败: {out}")
                else:
                    if not out:
                        print("📋 当前没有备份文件")
                    else:
                        print("📋 备份列表（1=最新，输入 restore <序号> 恢复）:")
                        for i, b in enumerate(out):
                            print(f"  [{b.get('index', i)}] {b.get('filename', '')}  {b.get('size', '')}  {b.get('display_name', '')}")
                continue
            if lower.startswith("restore "):
                arg = user_input[8:].strip()
                if not arg:
                    print("📋 用法: restore <序号> 或 restore <文件名>，例如 restore 1 或 restore backup_20260212_120000.db")
                    continue
                if arg.isdigit():
                    ok, msg = _api_restore(port, backup_index=int(arg))
                else:
                    ok, msg = _api_restore(port, backup_file=arg)
                if ok:
                    logger.info(f"✅ 数据库恢复成功: {msg}")
                    print(f"✅ 数据库恢复成功: {msg}")
                else:
                    logger.warning(f"❌ 恢复失败: {msg}")
                    print(f"❌ 恢复失败: {msg}")
                continue
            if lower in ("help", "?", "h"):
                print_console_help()
                continue
            # 未知命令时提示
            print("输入 help 或 h 查看可用命令")
        except KeyboardInterrupt:
            break
        except EOFError:
            break
        except Exception:
            pass


def kill_process_on_port(port: int):
    """
    检查并终止占用指定端口的进程
    
    Args:
        port: 要检查的端口号
    """
    killed = False
    for conn in psutil.net_connections(kind='inet'):
        if conn.laddr.port == port and conn.status == 'LISTEN':
            try:
                process = psutil.Process(conn.pid)
                logger.warning(f"⚠️  端口 {port} 被进程占用: PID={conn.pid}, 名称={process.name()}")
                logger.info(f"🔪 正在终止进程 PID={conn.pid}...")
                process.terminate()  # 优雅终止
                
                # 等待进程结束（最多3秒）
                try:
                    process.wait(timeout=3)
                    logger.info(f"✅ 进程 PID={conn.pid} 已终止")
                    killed = True
                except psutil.TimeoutExpired:
                    # 如果超时，强制杀掉
                    logger.warning(f"⚠️  进程 PID={conn.pid} 未响应，强制终止...")
                    process.kill()
                    logger.info(f"✅ 进程 PID={conn.pid} 已强制终止")
                    killed = True
            except psutil.NoSuchProcess:
                logger.warning(f"⚠️  进程 PID={conn.pid} 已不存在")
            except psutil.AccessDenied:
                logger.error(f"❌ 无权限终止进程 PID={conn.pid}，请以管理员权限运行")
                sys.exit(1)
            except Exception as e:
                logger.error(f"❌ 终止进程时出错: {e}")
                sys.exit(1)
    
    if killed:
        import time
        time.sleep(1)  # 等待端口释放
        logger.info(f"✅ 端口 {port} 已释放")
    
    return killed


def _check_portable_runtime() -> bool:
    """
    启动前自检（纯项目内依赖模式）：
    - 强制使用项目内 Python
    - 检查关键运行时文件是否存在
    - 检查后端核心 Python 依赖是否可导入
    """
    repo_root = _repo_root_for_misc()
    executable_norm = os.path.normcase(os.path.abspath(sys.executable))

    # 可信 Python 根目录列表（按优先级）：
    #   1. misc/tools/python  — 旧版项目内嵌
    #   2. P:\Tools\python    — 新版共享工具盘（同一台机器，工具统一放 P:\Tools）
    python_bases = [
        os.path.join(repo_root, "misc", "tools", "python"),
        r"P:\Tools\python",
    ]

    python_ok = False
    for python_base in python_bases:
        # 精确匹配 python_base/python.exe
        candidate_exact = os.path.join(python_base, "python.exe")
        if os.path.isfile(candidate_exact) and executable_norm == os.path.normcase(os.path.abspath(candidate_exact)):
            python_ok = True
            break
        # 模糊匹配 python_base/<子目录>/python.exe（如 python-3.x.x/python.exe）
        if os.path.isdir(python_base):
            try:
                for name in os.listdir(python_base):
                    candidate = os.path.join(python_base, name, "python.exe")
                    if os.path.isfile(candidate) and executable_norm == os.path.normcase(os.path.abspath(candidate)):
                        python_ok = True
                        break
            except Exception:
                pass
        if python_ok:
            break

    if python_ok:
        logger.info(f"✅ [便携自检] Python: {sys.executable}")
    else:
        logger.error(f"❌ [便携自检] 当前 Python 非项目内解释器: {sys.executable}")
        logger.error(f"   可接受路径: {', '.join(python_bases)}")
        return False

    # 每项为 (label, [(候选路径, required), ...])：找到任意一个即视为 OK，都没有则按最后一项的 required 决定是否中断。
    runtime_file_groups = [
        ("Cairo DLL", [
            (os.path.join(repo_root, "misc", "tools", "gtk", "bin", "libcairo-2.dll"), False),
            (r"P:\Tools\gtk\bin\libcairo-2.dll", False),
        ]),
        ("ADB", [
            (os.path.join(repo_root, "misc", "tools", "android-sdk", "platform-tools", "adb.exe"), False),
            (r"P:\Tools\android-sdk\platform-tools\adb.exe", False),
        ]),
        ("JDK", [
            (os.path.join(repo_root, "misc", "tools", "jdk-17", "bin", "java.exe"), False),
            (r"P:\Tools\jdk-17\bin\java.exe", False),
        ]),
    ]
    for label, candidates in runtime_file_groups:
        found_path = next((p for p, _ in candidates if os.path.exists(p)), None)
        required = candidates[-1][1]
        if found_path:
            logger.info(f"✅ [便携自检] {label}: {found_path}")
        else:
            msg = f"[便携自检] {label} 缺失（已检查 {len(candidates)} 个路径）"
            if required:
                logger.error(f"❌ {msg}")
                return False
            logger.warning(f"⚠️ {msg}")

    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        import httpx  # noqa: F401
        import aiosqlite  # noqa: F401
        import PIL  # noqa: F401
        logger.info("✅ [便携自检] 后端核心依赖导入正常")
    except Exception as dep_err:
        logger.error(f"❌ [便携自检] 后端依赖缺失或异常: {dep_err}")
        logger.error("   请先运行根目录 AAA一键绿色部署.bat（或 scripts\\launch\\AAA_deploy_portable.bat）安装项目内依赖")
        return False

    return True


def _collect_private_ipv4():
    ips = set()
    try:
        import ifaddr
        for adapter in ifaddr.get_adapters():
            for ip_obj in adapter.ips:
                if not ip_obj.is_IPv4:
                    continue
                ip = ip_obj.ip
                if not ip or ip == "127.0.0.1":
                    continue
                if ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("172."):
                    ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


def _ensure_https_cert_files():
    cert_file = os.getenv("PONYCHAT_SSL_CERTFILE", os.path.join(CERTS_DIR, "ponychat-lan-cert.pem"))
    key_file = os.getenv("PONYCHAT_SSL_KEYFILE", os.path.join(CERTS_DIR, "ponychat-lan-key.pem"))
    cert_file = os.path.abspath(cert_file)
    key_file = os.path.abspath(key_file)

    if os.path.exists(cert_file) and os.path.exists(key_file):
        return cert_file, key_file

    os.makedirs(os.path.dirname(cert_file), exist_ok=True)
    os.makedirs(os.path.dirname(key_file), exist_ok=True)

    try:
        import importlib
        from datetime import datetime, timedelta, timezone
        import ipaddress

        x509 = importlib.import_module("cryptography.x509")
        hashes = importlib.import_module("cryptography.hazmat.primitives.hashes")
        serialization = importlib.import_module("cryptography.hazmat.primitives.serialization")
        rsa = importlib.import_module("cryptography.hazmat.primitives.asymmetric.rsa")
        NameOID = importlib.import_module("cryptography.x509.oid").NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PonyChat"),
            x509.NameAttribute(NameOID.COMMON_NAME, "PonyChat LAN HTTPS"),
        ])

        san_items = [
            x509.DNSName("localhost"),
            x509.DNSName("ponychat.local"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]
        for ip in _collect_private_ipv4():
            try:
                san_items.append(x509.IPAddress(ipaddress.ip_address(ip)))
            except Exception:
                pass

        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san_items), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(private_key=key, algorithm=hashes.SHA256())
        )

        with open(key_file, "wb") as f:
            f.write(
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
        with open(cert_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        logger.info(f"🔐 已生成本地 HTTPS 证书: {cert_file}")
        logger.info(f"🔐 已生成本地 HTTPS 私钥: {key_file}")
        logger.warning("⚠️  该证书为本地自签名证书；浏览器可能提示不受信任（App 内 WebView 已允许继续）")
        return cert_file, key_file
    except Exception as cert_err:
        logger.error(f"❌ HTTPS 证书准备失败: {cert_err}")
        logger.error("   请检查 cryptography 依赖，或手动提供证书：")
        logger.error("   - 设置 PONYCHAT_SSL_CERTFILE=/path/to/cert.pem")
        logger.error("   - 设置 PONYCHAT_SSL_KEYFILE=/path/to/key.pem")
        return None, None
