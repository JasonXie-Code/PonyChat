import asyncio
import os
import signal
import logging
import logging.handlers
import queue
import mimetypes
import httpx
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# 模型配置在导入 model_manager 时就会展开 ${ENV_NAME}。因此必须先加载
# 项目 .env，否则本机启动会把已保存的供应商密钥解析成空字符串。
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .model_manager import model_manager
from .runtime_paths import resolve_backup_dir, resolve_database_path
from .shutdown_state import request_shutdown

# 显式初始化 MIME 类型
mimetypes.init()
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('image/svg+xml', '.svg')

# 项目根目录（基于 backend 包位置，与启动 CWD 无关，从任意目录启动均可正确解析 html/、assets/ 等）
_backend_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_backend_dir)


def _resolve_frontend_root() -> str:
    """静态资源目录：优先 PonyChat-Website/Main/frontend/public/（Vue 构建），兼容旧路径 PonyChat-Website/frontend/public/；否则 staging/；再兼容根目录 frontend/。"""
    main_public = os.path.join(PROJECT_ROOT, "PonyChat-Website", "Main", "frontend", "public")
    if os.path.isdir(main_public):
        return main_public
    legacy_public = os.path.join(PROJECT_ROOT, "PonyChat-Website", "frontend", "public")
    if os.path.isdir(legacy_public):
        return legacy_public
    nested_staging = os.path.join(PROJECT_ROOT, "PonyChat-Website", "staging")
    if os.path.isdir(nested_staging):
        return nested_staging
    direct = os.path.join(PROJECT_ROOT, "frontend")
    if os.path.isdir(direct):
        return direct
    main_fe = os.path.join(PROJECT_ROOT, "PonyChat-Website", "Main", "frontend")
    if os.path.isdir(main_fe):
        return main_fe
    nested = os.path.join(PROJECT_ROOT, "PonyChat-Website", "frontend")
    if os.path.isdir(nested):
        return nested
    return nested_staging


FRONTEND_ROOT = _resolve_frontend_root()


def _runtime_dir(subdir: str, legacy_dot: str) -> str:
    """优先使用 var/<subdir>/，否则沿用根目录旧式点目录（迁移期兼容）。"""
    p = os.path.join(PROJECT_ROOT, "var", subdir)
    leg = os.path.join(PROJECT_ROOT, legacy_dot)
    if os.path.isdir(p):
        return p
    if os.path.isdir(leg):
        return leg
    os.makedirs(p, exist_ok=True)
    return p


def _recovery_subdir(*parts: str) -> str:
    """游戏/任务恢复快照：优先 var/recovery_snapshots/<parts>，否则 .RecoverySnapshots/<parts>。"""
    new_p = os.path.join(PROJECT_ROOT, "var", "recovery_snapshots", *parts)
    old_p = os.path.join(PROJECT_ROOT, ".RecoverySnapshots", *parts)
    if os.path.isdir(new_p):
        return new_p
    if os.path.isdir(old_p):
        return old_p
    os.makedirs(new_p, exist_ok=True)
    return new_p


BACKLOGS_DIR = _runtime_dir("backlogs", ".BackLogs")
CHATLOGS_DIR = _runtime_dir(".chatlogs", ".ChatLogs")
APPLOGS_DIR = _runtime_dir("applogs", ".AppLogs")
CERTS_DIR = _runtime_dir("certs", ".certs")
GALGAME_RECOVERY_SNAPSHOT_DIR = _recovery_subdir("galgame")

# 数据库绝对路径，避免相对路径 + 不同 cwd（如 uvicorn reload 子进程）导致读写到不同文件、出现“重启后数据全丢”
DB_PATH = resolve_database_path(_backend_dir)
BACKUP_DIR = resolve_backup_dir(_backend_dir, DB_PATH)

# 🛡️ [热重载防护] 收到 SIGTERM 时尝试同步做一次 WAL checkpoint，避免 uvicorn --reload 时 lifespan 未执行导致数据未落盘
_db_checkpoint_on_signal_done = False

def _sync_wal_checkpoint_on_signal(signum, frame):
    global _db_checkpoint_on_signal_done
    request_shutdown(f"signal:{signum}")
    if _db_checkpoint_on_signal_done:
        return
    _db_checkpoint_on_signal_done = True
    try:
        if os.path.exists(DB_PATH):
            import sqlite3
            # PASSIVE：只写回已提交页，不等其他连接释放，速度快。
            # lifespan shutdown 里 db.close() 会再做一次更彻底的 checkpoint，此处无需 TRUNCATE。
            conn = sqlite3.connect(DB_PATH, timeout=2.0)
            try:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            finally:
                conn.close()
            if logging.getLogger().handlers:
                logging.getLogger().info("🛑 [Signal] WAL PASSIVE checkpoint 完成（lifespan 退出时还会做兜底 checkpoint）")
    except Exception:
        pass

try:
    signal.signal(signal.SIGTERM, _sync_wal_checkpoint_on_signal)
except (ValueError, OSError, AttributeError):
    pass  # 非主线程或 Windows 下 SIGTERM 可能不可用；仅注册 SIGTERM，避免覆盖 uvicorn 的 Ctrl+C (SIGINT)

# 🔐 [鉴权] 用于签发/校验聊天等接口的 Auth Token（未设置时使用默认值，生产环境请设置 AUTH_SECRET）
AUTH_SECRET = os.getenv("AUTH_SECRET", "ponychat_default_secret_change_in_production")

# ── 主业务 WebSocket `/ws/{username}`（与 Android `SyncWebSocketManager` 对齐）──
# `receive_text` 最长等待（秒）：无上行则进入服务端 ping 探测；宜略大于客户端发 ping 的间隔；
# 前面若有 Nginx/Caddy，请把 `proxy_read_timeout` 设为 ≥ 本值 + WEBSOCKET_PROBE_TIMEOUT_SEC + 余量（建议 ≥120）。
WEBSOCKET_RECEIVE_TIMEOUT_SEC = float(os.getenv("WEBSOCKET_RECEIVE_TIMEOUT_SEC", "90"))
# 服务端已发探测 ping 后，等待客户端 `pong`/`ping` 文本的秒数
WEBSOCKET_PROBE_TIMEOUT_SEC = float(os.getenv("WEBSOCKET_PROBE_TIMEOUT_SEC", "15"))
# 服务端周期性 `send_text("ping")` 的间隔（秒），利于穿透部分中间层空闲断连；0=关闭
WEBSOCKET_SERVER_PING_INTERVAL_SEC = float(os.getenv("WEBSOCKET_SERVER_PING_INTERVAL_SEC", "45"))

# 🔧 [修复] 代理配置提前到 lifespan 之前，避免引用未定义变量
PROXY_ENABLED = os.getenv("PROXY_ENABLED", "false").lower() == "true"
PROXY_URL = os.getenv("PROXY_URL", "http://127.0.0.1:7890")

# 🔧 [优化] CORS 允许的来源可通过环境变量配置（逗号分隔），默认允许所有
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# 🎮 [陪玩] 精简 Prompt（长设定由 DeepSeek 压成 ≤2000 字）：默认关闭「启动预热」与「按需/保存后触发生成」；设 COMPANION_SLIM_PROMPT=1/true 可重新开启
_COMPANION_SLIM_RAW = (os.getenv("COMPANION_SLIM_PROMPT") or "").strip().lower()
COMPANION_SLIM_PROMPT_ENABLED = _COMPANION_SLIM_RAW in ("1", "true", "yes", "on")

# 🔧 [修复] 中国大陆 API 域名列表（这些域名不应该走代理）
NO_PROXY_DOMAINS = [
    "localhost",
    "127.0.0.1",
    "*.volces.com",
    "*.volcengine.com",
    "api.deepseek.com",
    "*.dashscope.aliyuncs.com",
    "*.aip.baidubce.com",
    "open.bigmodel.cn",
    "*.bigmodel.cn",
]

if PROXY_ENABLED:
    os.environ['HTTP_PROXY'] = PROXY_URL
    os.environ['HTTPS_PROXY'] = PROXY_URL
    os.environ['NO_PROXY'] = ",".join(NO_PROXY_DOMAINS)

# 全局 HTTP 客户端（单例连接池）
httpx_client: httpx.AsyncClient = None


async def _cancel_shutdown_task(name: str, task: asyncio.Task | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    timeout = float(os.getenv("PONYCHAT_SHUTDOWN_TASK_CANCEL_TIMEOUT_SECONDS") or "2")
    try:
        await asyncio.wait_for(task, timeout=max(0.1, timeout))
    except asyncio.CancelledError:
        pass
    except asyncio.TimeoutError:
        logger.warning("⚠️ [Shutdown] %s 未在 %.1fs 内停止，继续退出", name, timeout)
    except Exception as exc:
        logger.warning("⚠️ [Shutdown] %s 停止时异常: %s", name, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global httpx_client
    # 启动时：初始化高性能客户端
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
    
    if PROXY_ENABLED:
        proxy_config = PROXY_URL
    else:
        proxy_config = None
        # 清除可能存在的系统代理环境变量
        os.environ.pop('HTTP_PROXY', None)
        os.environ.pop('HTTPS_PROXY', None)
        os.environ.pop('http_proxy', None)
        os.environ.pop('https_proxy', None)
    
    # 游戏/锁分模式文本较长，与整轮 galgame_job 墙钟上限一致（600s）
    httpx_client = httpx.AsyncClient(
        timeout=httpx.Timeout(600.0, connect=10.0),
        limits=limits,
        verify=False,
        proxy=proxy_config
    )
    logger.info("🚀 全局 HTTPX 客户端已连接")
    
    # 🗄️ [数据库] 初始化 SQLite 数据库
    try:
        from .db import init_database, get_database, InviteCodesDAO
        # 确保 database 目录存在，使用绝对路径避免 reload 后 cwd 不同导致读写到另一个 DB 文件
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        await init_database(DB_PATH)
        logger.info("🗄️ SQLite 数据库已初始化")
        
        # 🔄 [迁移] 自动从旧文件迁移邀请码到数据库
        try:
            invite_file = os.path.join(_backend_dir, "data", "invite_codes.json")
            if os.path.exists(invite_file):
                db = get_database()
                invite_dao = InviteCodesDAO(db)
                migrated = await invite_dao.migrate_from_file(invite_file)
                if migrated > 0:
                    logger.info(f"🔄 已从文件迁移 {migrated} 个邀请码到数据库")
                    # 迁移成功后重命名旧文件
                    os.rename(invite_file, invite_file + ".migrated")
        except Exception as migrate_err:
            logger.warning(f"⚠️ 邀请码迁移失败（非致命）: {migrate_err}")

    except Exception as e:
        logger.warning(f"⚠️ 数据库初始化失败（将使用文件系统）: {e}")
    
    # ⏱️ [定时备份] 每 8 小时检查一次，内容变化时备份，最多保留 5 个
    backup_task = None
    try:
        from .db.backup_scheduler import backup_scheduler_loop
        backup_task = asyncio.create_task(
            backup_scheduler_loop(
                interval_sec=8 * 3600,
                db_path=DB_PATH,
                backup_dir=BACKUP_DIR,
                keep=5,
                logger=logger,
            )
        )
        logger.info("⏱️ 数据库定时备份已启动（每 8 小时检查，内容变化时备份，最多保留 5 个）")
    except Exception as e:
        logger.warning(f"⚠️ 定时备份调度启动失败: {e}")

    # 🧹 [Prompt Cache] 每 10 分钟清理一次后端缓存模拟器的过期条目
    prompt_cache_cleanup_task = None
    try:
        from .prompt_cache_sim import cleanup as _pcs_cleanup

        async def _prompt_cache_cleanup_loop():
            while True:
                await asyncio.sleep(600)
                try:
                    removed = await _pcs_cleanup()
                    if removed:
                        logger.info(f"🧹 [PromptCacheSim] 清理过期条目 {removed} 个")
                except Exception:
                    pass

        prompt_cache_cleanup_task = asyncio.create_task(_prompt_cache_cleanup_loop())
        logger.info("🧹 [PromptCacheSim] 缓存清理任务已启动（每 10 分钟）")
    except Exception as e:
        logger.warning(f"⚠️ [PromptCacheSim] 缓存清理任务启动失败（非致命）: {e}")

    # 🎤 [阿里云 NLS] Token 预热默认关闭；配置好 NLS 密钥后可显式开启。
    aliyun_nls_warmup_enabled = (
        os.getenv("PONYCHAT_ALIYUN_NLS_WARMUP_ENABLED", "0").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    if aliyun_nls_warmup_enabled:
        async def _warmup_aliyun_token():
            from .routes.system import _get_aliyun_nls_token
            delays = [2, 4]
            for attempt in range(1 + len(delays)):
                try:
                    await _get_aliyun_nls_token()
                    logger.info(f"🎤 [AliyunNLS] Token 预热完成（第{attempt + 1}次尝试），首次录音延迟已消除")
                    return
                except Exception as e:
                    if attempt < len(delays):
                        wait = delays[attempt]
                        logger.warning(f"⚠️ [AliyunNLS] Token 预热失败（第{attempt + 1}次），{wait}s 后重试: {type(e).__name__}: {e}")
                        await asyncio.sleep(wait)
                    else:
                        logger.warning(f"⚠️ [AliyunNLS] Token 预热全部失败，首次录音时将实时获取: {type(e).__name__}: {e}")
        asyncio.create_task(_warmup_aliyun_token())
        logger.info("🎤 [AliyunNLS] Token 预热任务已提交（后台获取中...）")

    # 🎮 [陪玩精简 Prompt] 启动时扫描并批量生成（仅当 COMPANION_SLIM_PROMPT 已启用）
    if COMPANION_SLIM_PROMPT_ENABLED:
        try:
            from .routes.companion_chat import companion_prompt_warmup
            asyncio.create_task(companion_prompt_warmup())
            logger.info("🎮 [Companion] 精简 Prompt 预热任务已提交（后台排队生成）")
        except Exception as e:
            logger.warning(f"⚠️ [Companion] 精简 Prompt 预热启动失败（非致命）: {e}")
    else:
        logger.info("🎮 [Companion] 精简 Prompt 预热已关闭（未设置 COMPANION_SLIM_PROMPT 或已禁用）")

    # Ordinary-chat memory is owned exclusively by the two Agent roles.
    auto_summarizer_task = None
    memory_consolidator_task = None
    from .agent_memory.jobs import initialize as initialize_agent_memory, worker_loop
    initialize_agent_memory(DB_PATH)
    memory_layer_task = asyncio.create_task(worker_loop())
    logger.info("[AgentMemory] Unified store and durable review worker started")

    relationship_page_task = None  # Review Agent owns relationship understanding too.

    scheduled_followup_task = None
    try:
        from .scheduled_followup import scheduled_followup_loop

        scheduled_followup_task = asyncio.create_task(scheduled_followup_loop())
        logger.info("[ScheduledFollowup] 延迟主动续接调度器已启动")
    except Exception as e:
        logger.warning(f"[ScheduledFollowup] 调度器启动失败（非致命）: {e}")

    pending_voice_recovery_task = None
    try:
        from .chat_modules.voice_messages import pending_voice_recovery_loop

        pending_voice_recovery_task = asyncio.create_task(pending_voice_recovery_loop())
        logger.info("[VoiceMsg] pending 语音恢复调度器已启动")
    except Exception as e:
        logger.warning(f"[VoiceMsg] pending 语音恢复调度器启动失败（非致命）: {e}")

    uptime_monitor_task = None
    try:
        from .uptime_monitor import uptime_monitor_loop

        uptime_monitor_task = asyncio.create_task(uptime_monitor_loop())
        logger.info("[UptimeMonitor] 服务可用性采样器已启动")
    except Exception as e:
        logger.warning(f"[UptimeMonitor] 采样器启动失败（非致命）: {e}")

    temp_user_cleanup_task = None
    try:
        from .maintenance.temp_user_cleanup import temp_user_cleanup_loop

        temp_user_cleanup_task = asyncio.create_task(temp_user_cleanup_loop())
        logger.info("[TempUserCleanup] 临时访客账号清理器已启动（每天运行一次）")
    except Exception as e:
        logger.warning(f"[TempUserCleanup] 清理器启动失败（非致命）: {e}")

    # 📋 [LLM日志索引] 每 30 秒增量扫描对话调试日志，写入索引库供管理台审计
    llm_log_indexer_task = None
    try:
        from .routes.admin.llm_log_indexer import get_log_indexer

        llm_indexer = get_log_indexer(DB_PATH)
        await llm_indexer.init_schema()
        # 启动时做一次全量扫描，之后走增量
        asyncio.create_task(llm_indexer.scan_all())
        llm_log_indexer_task = asyncio.create_task(llm_indexer.start_periodic_scan(interval=30))
        logger.info("📋 [LLMLogIndexer] 对话日志索引器已启动（每 30s 增量扫描）")
    except Exception as e:
        logger.warning(f"📋 [LLMLogIndexer] 索引器启动失败（非致命）: {e}")
        import traceback as _tb
        logger.warning(f"📋 [LLMLogIndexer] 堆栈: {_tb.format_exc()}")

    yield

    request_shutdown("lifespan-shutdown")
    logger.info("🛑 [Shutdown] 已进入快速退出模式：后台调度器只记录状态，不再启动重任务")

    if llm_log_indexer_task is not None:
        try:
            llm_indexer.stop_periodic_scan()
        except Exception:
            pass

    # 先停所有周期性后台循环，避免 shutdown 期间继续启动记忆固化、分层摘要或主动任务。
    for _name, _task in (
        ("pending_voice_recovery", pending_voice_recovery_task),
        ("uptime_monitor", uptime_monitor_task),
        ("temp_user_cleanup", temp_user_cleanup_task),
        ("llm_log_indexer", llm_log_indexer_task),
        ("scheduled_followup", scheduled_followup_task),
        ("prompt_cache_cleanup", prompt_cache_cleanup_task),
        ("backup_scheduler", backup_task),
        ("auto_summarizer", auto_summarizer_task),
        ("memory_consolidator", memory_consolidator_task),
        ("memory_layer", memory_layer_task),
        ("relationship_page", relationship_page_task),
    ):
        await _cancel_shutdown_task(_name, _task)

    try:
        from .background_jobs import drain_background_jobs

        drain_timeout = float(os.getenv("PONYCHAT_BACKGROUND_DRAIN_TIMEOUT_SECONDS") or "3")
        await drain_background_jobs(drain_timeout)
    except Exception as e:
        logger.warning(f"⚠️ [BackgroundJobs] shutdown drain failed: {e}")

    # 关闭时：释放连接。给连接池一个短窗口清理，不能拖住 systemd stop。
    if httpx_client is not None:
        try:
            await asyncio.wait_for(httpx_client.aclose(), timeout=3.0)
            logger.info("🛑 全局 HTTPX 客户端已关闭")
        except Exception as e:
            logger.warning(f"⚠️ 全局 HTTPX 客户端关闭超时/异常，继续退出: {e}")

    # 🔧 [优化] 关闭数据库连接池（先 WAL checkpoint 再关连接，防止热重载后新进程读不到未刷盘数据）
    try:
        from .db import get_database
        db = get_database()
        await asyncio.wait_for(db.close(), timeout=5.0)
        logger.info("🛑 [Database] 连接池已关闭，WAL 已落盘")
    except Exception as e:
        logger.warning(f"⚠️ [Database] 关闭时异常: {e}")

    # 停止日志队列监听器，确保队列中最后一批日志全部落盘后再退出
    try:
        _queue_listener.stop()
    except Exception:
        pass

# 统一日志格式（文件与控制台一致）
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

# 配置日志处理器，使用 'w' 模式确保每次都覆盖文件
# 确保后端日志目录存在（使用 PROJECT_ROOT，不依赖 CWD）
os.makedirs(BACKLOGS_DIR, exist_ok=True)

log_file = os.path.join(BACKLOGS_DIR, "backend.log")

# 清空日志文件（如果存在）
if os.path.exists(log_file):
    try:
        open(log_file, 'w').close()
    except Exception:
        pass

class CustomFormatter(logging.Formatter):
    def __init__(self):
        super().__init__(fmt=LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S')

    def format(self, record):
        return super().format(record)


class ConsoleColorFormatter(logging.Formatter):
    """仅用于控制台输出的彩色格式化器（文件日志保持纯文本）。"""
    _RESET = "\033[0m"
    _COLOR_MAP = {
        logging.DEBUG: "\033[36m",    # cyan
        logging.INFO: "\033[32m",     # green
        logging.WARNING: "\033[33m",  # yellow
        logging.ERROR: "\033[31m",    # red
        logging.CRITICAL: "\033[35m", # magenta
    }

    def __init__(self):
        super().__init__(fmt=LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S')

    def format(self, record):
        original_levelname = record.levelname
        try:
            color = self._COLOR_MAP.get(record.levelno)
            if color:
                record.levelname = f"{color}{original_levelname}{self._RESET}"
            return super().format(record)
        finally:
            record.levelname = original_levelname


# 真正写文件的 handler（只在 QueueListener 的专用线程里调用，无并发风险）
_file_handler = logging.FileHandler(log_file, encoding='utf-8')
_file_handler.setFormatter(CustomFormatter())

# 控制台输出：
#   - 本地启动：由 scripts/launch/AAA_launch_backend.py 的 tail 回显，默认不在 backend 进程直出。
#   - systemd 环境：自动启用 stdout 直出，确保 journalctl 能看到应用 WARNING/ERROR。
#   - 也可手动设置环境变量 PONYCHAT_DIRECT_CONSOLE=1 强制开启。
_is_systemd = bool(os.environ.get("JOURNAL_STREAM") or os.environ.get("INVOCATION_ID"))
_actual_handlers: list = [_file_handler]
if os.environ.get("PONYCHAT_DIRECT_CONSOLE") == "1" or _is_systemd:
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(ConsoleColorFormatter())
    _actual_handlers.append(_console_handler)

# QueueHandler + QueueListener：所有日志先入队，由单一后台线程串行写入文件，
# 彻底消除多线程/多协程并发写入导致的日志行截断和重复问题。
_log_queue: queue.Queue = queue.Queue(maxsize=-1)
_queue_handler = logging.handlers.QueueHandler(_log_queue)
_queue_listener = logging.handlers.QueueListener(
    _log_queue, *_actual_handlers, respect_handler_level=True
)
_queue_listener.start()

# 配置根日志器
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# 清除现有的处理器，统一走 QueueHandler
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)
root_logger.addHandler(_queue_handler)

# 配置所有相关的日志器
loggers = [
    'uvicorn',
    'uvicorn.access', 
    'uvicorn.error',
    'fastapi',
    'backend'
]

for logger_name in loggers:
    logger = logging.getLogger(logger_name)
    logger.handlers = []
    logger.propagate = True  # 让日志传播到根日志器，统一由根日志器输出
    logger.setLevel(logging.INFO)

# 获取本模块的日志器
logger = logging.getLogger(__name__)
# 确保这个 logger 也传播到根日志器
logger.propagate = True

# Android 客户端最低版本（仅当请求头 X-PonyChat-Client: android 时校验；Web 不受影响）
# ① 语义版本（优先）：X-App-Version-Name 头，格式 "主.次.修"，如 "3.8.0"
# ② 整数 versionCode（降级兜底）：X-App-Version 头
MIN_APP_VERSION_NAME = os.getenv("PONYCHAT_MIN_APP_VERSION_NAME", "5.6.19")
MIN_APP_VERSION = int(os.getenv("PONYCHAT_MIN_APP_VERSION", "359"))


def _parse_version_name(v: str) -> tuple:
    """将 '3.8.0' 解析为 (3, 8, 0) 元组，解析失败返回 (0, 0, 0)。"""
    try:
        return tuple(int(x) for x in str(v).strip().split(".")[:3])
    except Exception:
        return (0, 0, 0)


def _app_version_middleware_skip(path: str) -> bool:
    """不校验 App 版本的路径（健康检查、WebSocket、静态与官网重定向等）。
    注意：/api/auth/ 登录/注册路径故意不跳过，旧版客户端尝试登录时会收到 426 要求升级。
    """
    p = path or ""
    if p in ("/api/health", "/api/ping"):
        return True
    if p.startswith("/ws/"):
        return True
    if p.startswith("/chat_images/") or p.startswith("/character_voice_assets/") or p.startswith("/avatars/"):
        return True
    if p.startswith("/assets/") or p.startswith("/logo/") or p.startswith("/css/") or p.startswith("/js/"):
        return True
    if p.startswith("/fonts/"):
        return True
    if p in ("/", "/favicon.ico", "/download/apk", "/sw.js", "/detail"):
        return True
    if p.startswith("/html/"):
        return True
    if p.startswith("/admin"):
        return True
    return False


# FastAPI 实例
app = FastAPI(
    title="AI 角色扮演对话 API",
    description="支持多模型提供商的 AI 对话服务",
    version="3.2.2",
    lifespan=lifespan
)


@app.middleware("http")
async def app_version_gate(request: Request, call_next):
    """旧版 Android（带 X-PonyChat-Client: android 且版本过低）返回 426。
    优先以语义版本名（X-App-Version-Name）判断，降级兜底用整数 versionCode（X-App-Version）。
    """
    if request.method == "OPTIONS":
        return await call_next(request)
    if _app_version_middleware_skip(request.url.path):
        return await call_next(request)
    client = (request.headers.get("x-ponychat-client") or "").strip().lower()
    if client != "android":
        return await call_next(request)

    version_too_low = False
    ver_name = (request.headers.get("x-app-version-name") or "").strip()
    if ver_name:
        # 语义版本优先：X-App-Version-Name: "3.8.0"
        version_too_low = _parse_version_name(ver_name) < _parse_version_name(MIN_APP_VERSION_NAME)
    else:
        # 降级兜底：X-App-Version（整数 versionCode）
        try:
            ver_int = int((request.headers.get("x-app-version") or "0").strip())
        except ValueError:
            ver_int = 0
        version_too_low = ver_int < MIN_APP_VERSION

    if version_too_low:
        logger.warning(
            f"🚫 [VersionGate] 版本过低，拒绝请求: "
            f"version_name={ver_name or '(未提供)'}, "
            f"min={MIN_APP_VERSION_NAME}, path={request.url.path}"
        )
        return JSONResponse(
            status_code=426,
            content={
                "detail": f"当前版本已停止支持，请升级到 {MIN_APP_VERSION_NAME} 或更高版本的 PonyChat",
                "min_version": MIN_APP_VERSION_NAME,
                "upgrade_required": True,
            },
        )
    return await call_next(request)


# 1. 性能：Gzip 压缩（排除大文件下载路径和 SSE 聊天流）
_GZIP_EXCLUDE_PATHS = {"/download/apk", "/api/chat", "/api/drive/download"}

class _SelectiveGZipMiddleware(GZipMiddleware):
    """跳过指定路径的 Gzip 压缩，使浏览器能看到文件总大小并支持 Range 断点续传。"""
    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") in _GZIP_EXCLUDE_PATHS:
            await self.app(scope, receive, send)
        else:
            await super().__call__(scope, receive, send)

app.add_middleware(_SelectiveGZipMiddleware, minimum_size=1000)

# 2. 跨域：CORS 配置（通过环境变量 CORS_ORIGINS 可配置）
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. 安全屏蔽中间件 (Security Barrier)
@app.middleware("http")
async def security_barrier(request: Request, call_next):
    path = request.url.path.lower()
    
    try:
        # 静态文件路径（头像通过数据库服务，但 URL 路径保持不变）
        if path.startswith(("/js/", "/css/", "/logo/", "/html/index.html", "/sw.js", "/favicon.ico", "/user_data/", "/character_data/", "/chat_images/", "/character_voice_assets/")):
            return await call_next(request)
        
        sensitive_exts = ['.json', '.py', '.log', '.bat', '.sh', '.txt', '.md']
        if any(path.endswith(ext) for ext in sensitive_exts):
            if not path.startswith(("/api/", "/ws/")):
                if any(k in path for k in ["model_config", "users.json", "env", "backup"]):
                    return Response("Forbidden", status_code=403)
                    
        # 🔧 [修复] 确保 call_next 不会返回空响应
        response = await call_next(request)
        if response is None:
            logger.error(f"❌ [中间件] 响应为空: {request.url.path}")
            return Response(
                content='{"status": "error", "message": "Internal server error: empty response"}',
                status_code=500,
                media_type="application/json"
            )
        return response
    except (RuntimeError, Exception) as e:
        # 客户端中途断连时 Starlette BaseHTTPMiddleware 会抛 "No response returned."
        # 这属于正常的连接中断，降级为 WARNING 避免误报
        if "No response returned" in str(e):
            logger.warning(f"⚠️ [中间件] 客户端断连（流式响应未完成）: {request.url.path}")
            return Response(
                content='{"status": "error", "message": "Client disconnected"}',
                status_code=499,
                media_type="application/json"
            )
        # 🔧 [安全加固] 中间件异常时返回有效响应（不暴露内部错误细节）
        logger.error(f"❌ [中间件] 异常: {e}")
        import traceback
        logger.error(f"❌ [中间件] 异常堆栈: {traceback.format_exc()}")
        return Response(
            content='{"status": "error", "message": "Internal server error"}',
            status_code=500,
            media_type="application/json"
        )


@app.middleware("http")
async def backend_response_counter(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    finally:
        try:
            from .uptime_monitor import record_service_response

            record_service_response("backend")
        except Exception:
            pass


# 🗄️ [数据库模式] 所有数据仅通过数据库存取，不使用文件系统
DISABLE_FILESYSTEM = True

# 自动创建必要目录（仅日志）
os.makedirs(BACKLOGS_DIR, exist_ok=True)


# 🔧 [修复] 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理的异常，确保返回有效响应"""
    import traceback
    error_trace = traceback.format_exc()
    logger.error(f"❌ [全局异常] 未处理的异常: {exc}")
    logger.error(f"❌ [全局异常] 请求路径: {request.url.path}")
    logger.error(f"❌ [全局异常] 异常堆栈:\n{error_trace}")
    
    # 🔧 [安全加固] 返回 JSON 格式的错误响应（不暴露异常细节给客户端）
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "Internal server error"
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求验证错误"""
    logger.warning(f"⚠️ [验证错误] 请求路径: {request.url.path}, 错误: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "message": "Request validation error",
            "errors": exc.errors()
        }
    )

# 导出常用对象
__all__ = ['app', 'logger', 'model_manager', 'PROXY_ENABLED', 'PROXY_URL', 'CORS_ORIGINS', 'httpx_client', 'DISABLE_FILESYSTEM', 'MIN_APP_VERSION', 'MIN_APP_VERSION_NAME']

