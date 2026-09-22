"""
LLM 对话日志索引器

扫描 var/.chatlogs/ 下按天/小时分片的调试日志，
提取摘要字段写入 SQLite 索引表，供管理台快速检索。

特性：
- 增量索引：记录每个文件的已索引 offset，只处理新增内容
- 容错：单条日志解析失败不中断整个索引任务
- 实时：每 30s 扫描当前小时日志文件（允许追加读取）
- 历史文件默认认为稳定，减少重复扫描
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 索引数据库表 DDL ──
LLM_LOG_INDEX_DDL = """
CREATE TABLE IF NOT EXISTS llm_log_index (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 索引摘要字段（与方案设计对齐）
    log_timestamp   TEXT    NOT NULL,        -- 原始日志时间戳 ISO
    date            TEXT    NOT NULL,        -- YYYY-MM-DD
    hour            TEXT    NOT NULL,        -- HH
    status          TEXT    NOT NULL DEFAULT 'success',  -- success / error / timeout / interrupted
    provider        TEXT    DEFAULT '',       -- 供应商（从 endpoint / type 推断）
    model           TEXT    NOT NULL DEFAULT '',
    user_id         TEXT    DEFAULT '',       -- username
    username        TEXT    DEFAULT '',
    conversation_id TEXT    DEFAULT '',
    request_id      TEXT    DEFAULT '',       -- traceId / requestId
    trace_id        TEXT    DEFAULT '',
    latency_ms      INTEGER DEFAULT 0,
    prompt_tokens   INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens    INTEGER DEFAULT 0,
    cost            REAL    DEFAULT 0.0,
    error_code      TEXT    DEFAULT '',
    error_message   TEXT    DEFAULT '',
    stage           TEXT    DEFAULT '',       -- 调试阶段名
    log_file_path   TEXT    NOT NULL,         -- 原始日志文件路径（相对）
    byte_offset     INTEGER NOT NULL DEFAULT 0,
    byte_length     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- 加速常见筛选
CREATE INDEX IF NOT EXISTS idx_llm_log_date     ON llm_log_index(date);
CREATE INDEX IF NOT EXISTS idx_llm_log_hour     ON llm_log_index(date, hour);
CREATE INDEX IF NOT EXISTS idx_llm_log_model    ON llm_log_index(model);
CREATE INDEX IF NOT EXISTS idx_llm_log_user     ON llm_log_index(user_id);
CREATE INDEX IF NOT EXISTS idx_llm_log_status   ON llm_log_index(status);
CREATE INDEX IF NOT EXISTS idx_llm_log_reqid    ON llm_log_index(request_id);
CREATE INDEX IF NOT EXISTS idx_llm_log_trace    ON llm_log_index(trace_id);
CREATE INDEX IF NOT EXISTS idx_llm_log_ts       ON llm_log_index(log_timestamp);
CREATE INDEX IF NOT EXISTS idx_llm_log_conv     ON llm_log_index(conversation_id);

-- FTS5 全文搜索（关键词搜索 prompt / response / 错误信息）
CREATE VIRTUAL TABLE IF NOT EXISTS llm_log_fts USING fts5(
    error_message,
    model,
    username,
    request_id,
    content='llm_log_index',
    content_rowid='id'
);

-- 触发器：自动同步 FTS
CREATE TRIGGER IF NOT EXISTS llm_log_ai AFTER INSERT ON llm_log_index BEGIN
    INSERT INTO llm_log_fts(rowid, error_message, model, username, request_id)
    VALUES (new.id, new.error_message, new.model, new.username, new.request_id);
END;

CREATE TRIGGER IF NOT EXISTS llm_log_ad AFTER DELETE ON llm_log_index BEGIN
    INSERT INTO llm_log_fts(llm_log_fts, rowid, error_message, model, username, request_id)
    VALUES ('delete', old.id, old.error_message, old.model, old.username, old.request_id);
END;

-- 索引进度追踪（每个文件的已处理字节数）
CREATE TABLE IF NOT EXISTS llm_log_index_progress (
    file_path       TEXT PRIMARY KEY,
    file_size       INTEGER NOT NULL DEFAULT 0,
    file_mtime      REAL    NOT NULL DEFAULT 0.0,
    indexed_offset  INTEGER NOT NULL DEFAULT 0,
    indexed_count   INTEGER NOT NULL DEFAULT 0,
    error_count     INTEGER NOT NULL DEFAULT 0,
    last_scan_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- 索引错误记录
CREATE TABLE IF NOT EXISTS llm_log_index_errors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path       TEXT    NOT NULL,
    byte_offset     INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT    NOT NULL DEFAULT '',
    raw_preview     TEXT    DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

# Match only the declaration. Scanning a multi-MB body with a lazy regex and
# overlapping whitespace suffixes holds the GIL for seconds, even in to_thread.
_DEBUG_LOG_PREFIX_RE = re.compile(r'const\s+debug_log\s*=\s*')


def _extract_debug_log_literal(content: str) -> Optional[str]:
    match = _DEBUG_LOG_PREFIX_RE.search(content)
    if match is None:
        return None
    body = content[match.end():].rstrip()
    if body.endswith(';'):
        body = body[:-1].rstrip()
    return body or None


def _js_template_to_json(js_text: str) -> str:
    """将 JS 字面量中的模板字符串（反引号）转为 JSON 兼容格式。"""
    out = []
    i = 0
    while i < len(js_text):
        ch = js_text[i]
        if ch == '"':
            # SDK streamed chunks can contain a literal backtick in a normal
            # JSON string. It must not start a template or consume later fields.
            j = i + 1
            while j < len(js_text):
                if js_text[j] == '\\' and j + 1 < len(js_text):
                    j += 2
                    continue
                if js_text[j] == '"':
                    break
                j += 1
            out.append(js_text[i:j + 1])
            i = j + 1
        elif ch == '`':
            # 模板字符串开始，找到匹配的结束反引号
            j = i + 1
            while j < len(js_text):
                if js_text[j] == '\\' and j + 1 < len(js_text):
                    j += 2  # 跳过转义对
                    continue
                if js_text[j] == '`':
                    break
                j += 1
            # 提取原始内容并做 JSON 编码
            raw = js_text[i + 1:j]
            # 反转义 JS 模板字面量
            unescaped = []
            ki = 0
            while ki < len(raw):
                if raw[ki] == '\\' and ki + 1 < len(raw):
                    nxt = raw[ki + 1]
                    if nxt in ('`', '$', '\\'):
                        unescaped.append(nxt)
                        ki += 2
                        continue
                unescaped.append(raw[ki])
                ki += 1
            out.append(json.dumps(''.join(unescaped), ensure_ascii=False))
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def _normalize_debug_log_literal(js_text: str) -> str:
    """将现有 debug_log JS 字面量修整成更接近 JSON 的文本。"""
    js_text = (js_text or "").strip()
    if js_text.endswith(";"):
        js_text = js_text[:-1].rstrip()
    # 兼容 companion 日志里的 `..."timestamp": ...` 写法。
    js_text = re.sub(r'(^\s*)\.\.\.(?=\s*["\'])', r'\1', js_text, flags=re.MULTILINE)
    return js_text


def _loads_debug_log_literal(js_text: str) -> Optional[Dict[str, Any]]:
    """解析 const debug_log 右侧的 JS 字面量，兼容模板字符串。"""
    js_body = _normalize_debug_log_literal(js_text)
    candidates = [js_body]
    try:
        converted = _js_template_to_json(js_body)
        if converted != js_body:
            candidates.append(_normalize_debug_log_literal(converted))
    except Exception:
        pass

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return None

# 状态推断关键词
_ERROR_KEYWORDS = ['error', 'fail', 'exception', 'timeout', 'refused', 'denied', 'invalid']
_TIMEOUT_KEYWORDS = ['timeout', 'timed out', 'timed_out']
_INTERRUPTED_KEYWORDS = ['interrupted', 'connection', 'broken pipe', 'reset']


def _resolve_logs_root() -> str:
    """解析日志根目录，与 utils._chatlogs_dir_from_backend 对齐。"""
    try:
        from ...config import CHATLOGS_DIR
        return os.path.normpath(CHATLOGS_DIR)
    except Exception:
        pass
    # 回退
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    project_root = os.path.dirname(backend_dir)
    if os.path.basename(project_root) == "backend-server":
        project_root = os.path.dirname(project_root)

    p = os.path.join(project_root, "var", ".chatlogs")
    leg = os.path.join(project_root, ".ChatLogs")
    backend_p = os.path.join(backend_dir, "var", ".chatlogs")
    backend_leg = os.path.join(backend_dir, ".ChatLogs")
    if os.path.isdir(p):
        return os.path.normpath(p)
    if os.path.isdir(leg):
        return os.path.normpath(leg)
    if os.path.isdir(backend_p):
        return os.path.normpath(backend_p)
    if os.path.isdir(backend_leg):
        return os.path.normpath(backend_leg)
    os.makedirs(p, exist_ok=True)
    return os.path.normpath(p)


def _date_hour_from_path(file_path: str) -> Tuple[str, str]:
    """从 .../YYYY-MM-DD/HH/*.js 路径兜底提取日期和小时。"""
    parts = Path(file_path).parts
    if len(parts) < 3:
        return "", ""
    date_part = parts[-3]
    hour_part = parts[-2]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_part) and re.fullmatch(r"\d{2}", hour_part):
        return date_part, hour_part
    return "", ""


def _infer_status(data: Any, error_msg: str = "") -> str:
    """根据日志内容推断调用状态。"""
    if isinstance(data, dict):
        explicit = data.get('status')
        if explicit in ('success', 'error', 'timeout', 'interrupted'):
            return explicit
        if data.get('incomplete') is True:
            return 'error'
    text = json.dumps(data, ensure_ascii=False).lower() if data else ""
    if error_msg:
        text += " " + error_msg.lower()
    for kw in _TIMEOUT_KEYWORDS:
        if kw in text:
            return "timeout"
    for kw in _INTERRUPTED_KEYWORDS:
        if kw in text:
            return "interrupted"
    for kw in _ERROR_KEYWORDS:
        if kw in text:
            return "error"
    return "success"


def _extract_tokens(data: dict) -> Tuple[int, int, int]:
    """从 data 中提取 token 统计。"""
    prompt = 0
    completion = 0
    if isinstance(data, dict):
        if data.get('usage_scope') == 'summary':
            return 0, 0, 0
        usage = data.get("usage") or {}
        if isinstance(usage, dict):
            prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
            completion = usage.get("completion_tokens") or usage.get("output_tokens") or 0
    return int(prompt or 0), int(completion or 0), int(prompt or 0) + int(completion or 0)


def _extract_request_id(data: dict) -> str:
    """从 data 中提取 requestId / traceId。"""
    if not isinstance(data, dict):
        return ""
    for k in ("id", "request_id", "requestId", "trace_id", "traceId"):
        v = data.get(k)
        if v and isinstance(v, str):
            return v
    return ""


def _extract_error(data: dict) -> Tuple[str, str]:
    """从 data 中提取错误码和错误消息。"""
    if not isinstance(data, dict):
        return "", ""
    error = data.get("error") or {}
    if isinstance(error, dict):
        code = str(error.get("code") or error.get("type") or "")
        msg = str(error.get("message") or "")
        return code, msg
    if isinstance(error, str) and error:
        return "", error
    return "", ""


def _parse_log_file(file_path: str) -> List[Dict[str, Any]]:
    """
    解析单个 .js 日志文件，返回索引条目列表。
    文件格式为 JS 字面量（const debug_log = {...};），可能含模板字符串。
    容错：解析失败返回空列表，不抛异常。
    """
    entries = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.debug(f"[LLMLogIndex] 读取跳过 {file_path}: {e}")
        return entries

    literal = _extract_debug_log_literal(content)
    if literal is None:
        logger.debug(f"[LLMLogIndex] 未匹配 debug_log 格式: {file_path}")
        return entries

    log_data = _loads_debug_log_literal(literal)
    if log_data is None:
        logger.debug(f"[LLMLogIndex] JSON 解析失败 {file_path}")
        return entries

    data = log_data.get("data") or {}
    params = log_data.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    # 提取字段
    log_ts = str(log_data.get("timestamp") or "")
    username = str(log_data.get("username") or "")
    model = str(log_data.get("model") or "")
    mode = str(log_data.get("mode") or "")
    stage = str(log_data.get("stage") or "")
    char_id = str(log_data.get("character_id") or "")
    primary_char_id = str(log_data.get("primary_character_id") or char_id or "")

    # 从 params 提取更多上下文
    conv_id = str(
        params.get("conversation_id")
        or params.get("conversationId")
        or log_data.get("conversation_id")
        or log_data.get("conversationId")
        or ""
    )
    speaker_id = str(params.get("speaker_character_id") or log_data.get("speaker_character_id") or "")

    request_id = (
        _extract_request_id(data)
        or str(params.get("request_id") or params.get("requestId") or "")
        or str(log_data.get("request_id") or log_data.get("requestId") or "")
    )
    trace_id = str(params.get("trace_id") or params.get("traceId") or "")
    if not trace_id:
        trace_id = request_id

    prompt_t, completion_t, total_t = _extract_tokens(data)
    error_code, error_msg = _extract_error(data)
    status = _infer_status(data, error_msg)

    # 推断延迟（如果有的话）
    latency_ms = 0
    if isinstance(data, dict):
        latency_ms = data.get("latency_ms") or data.get("latency") or data.get("elapsed") or 0
        if isinstance(latency_ms, float):
            latency_ms = int(latency_ms * 1000) if latency_ms < 1000 else int(latency_ms)

    fallback_date, fallback_hour = _date_hour_from_path(file_path)
    if not log_ts and fallback_date and fallback_hour:
        log_ts = f"{fallback_date}T{fallback_hour}:00:00"
    date_value = log_ts[:10] if len(log_ts) >= 10 else fallback_date
    hour_value = log_ts[11:13] if len(log_ts) >= 13 else fallback_hour

    entry = {
        "log_timestamp": log_ts,
        "date": date_value,
        "hour": hour_value,
        "status": status,
        "provider": "",
        "model": model,
        "user_id": username,
        "username": username,
        "conversation_id": conv_id,
        "request_id": request_id,
        "trace_id": trace_id,
        "latency_ms": int(latency_ms or 0),
        "prompt_tokens": prompt_t,
        "completion_tokens": completion_t,
        "total_tokens": total_t,
        "cost": 0.0,
        "error_code": error_code,
        "error_message": error_msg,
        "stage": stage,
        "log_file_path": file_path,
        "byte_offset": 0,
        "byte_length": len(content.encode("utf-8")),
    }
    entries.append(entry)
    return entries


class LLMLogIndexer:
    """日志索引器：扫描 → 解析 → 写入索引表。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.logs_root = _resolve_logs_root()
        self._scan_task: Optional[asyncio.Task] = None
        self._scan_interval = 30  # 秒
        self._running = False
        self._scan_lock = asyncio.Lock()
        self._progress_snapshot = None
        self._change_cursor = 0
        self._full_scan_at = float('-inf')
        self._reconcile_interval = 300  # seconds; external writers are reconciled too

    async def init_schema(self) -> None:
        """初始化索引表结构。"""
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            # 使用 executescript 处理多语句 DDL（对触发器、FTS 等更友好）
            await conn.executescript(LLM_LOG_INDEX_DDL)
            await conn.commit()

    async def _get_progress(self, file_path: str) -> Tuple[int, float, int]:
        """获取文件的索引进度。"""
        if self._progress_snapshot is not None:
            return self._progress_snapshot.get(file_path, (0, 0.0, 0))
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT indexed_offset, file_mtime, indexed_count, error_count FROM llm_log_index_progress WHERE file_path = ?",
                (file_path,),
            ) as cur:
                row = await cur.fetchone()
                if row:
                    return (row[0] if not row[3] else -1), row[1], row[2]
        return 0, 0.0, 0

    async def _save_progress(self, file_path: str, file_size: int, file_mtime: float,
                              indexed_offset: int, count: int, errors: int) -> None:
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                """INSERT OR REPLACE INTO llm_log_index_progress
                   (file_path, file_size, file_mtime, indexed_offset, indexed_count, error_count, last_scan_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                (file_path, file_size, file_mtime, indexed_offset, count, errors),
            )
            await conn.commit()

    async def _insert_entries(self, entries: List[Dict[str, Any]]) -> Tuple[int, int]:
        """批量插入索引条目。"""
        if not entries:
            return 0, 0
        import aiosqlite
        inserted = 0
        errors = 0
        async with aiosqlite.connect(self.db_path) as conn:
            for e in entries:
                try:
                    await conn.execute(
                        """INSERT INTO llm_log_index
                           (log_timestamp, date, hour, status, model, user_id, username,
                            conversation_id, request_id, trace_id, latency_ms,
                            prompt_tokens, completion_tokens, total_tokens, cost,
                            error_code, error_message, stage,
                            log_file_path, byte_offset, byte_length)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            e.get("log_timestamp", ""),
                            e.get("date", ""),
                            e.get("hour", ""),
                            e.get("status", "success"),
                            e.get("model", ""),
                            e.get("user_id", ""),
                            e.get("username", ""),
                            e.get("conversation_id", ""),
                            e.get("request_id", ""),
                            e.get("trace_id", ""),
                            e.get("latency_ms", 0),
                            e.get("prompt_tokens", 0),
                            e.get("completion_tokens", 0),
                            e.get("total_tokens", 0),
                            e.get("cost", 0.0),
                            e.get("error_code", ""),
                            e.get("error_message", ""),
                            e.get("stage", ""),
                            e.get("log_file_path", ""),
                            e.get("byte_offset", 0),
                            e.get("byte_length", 0),
                        ),
                    )
                    inserted += 1
                except Exception as exc:
                    logger.warning(f"⚠️ [LLMLogIndex] 插入索引条目失败: {exc}")
                    errors += 1
                    # 记录错误
                    try:
                        await conn.execute(
                            "INSERT INTO llm_log_index_errors (file_path, byte_offset, error_message, raw_preview) VALUES (?, ?, ?, ?)",
                            (e.get("log_file_path", ""), 0, str(exc), str(e.get("request_id", ""))),
                        )
                    except Exception:
                        pass
            await conn.commit()
        return inserted, errors

    async def _scan_file(self, file_path: str, *, skip_duplicate_check: bool = False, file_stat=None) -> Tuple[int, int]:
        """扫描单个日志文件，增量解析并索引。"""
        try:
            stat = file_stat if file_stat is not None else await asyncio.to_thread(os.stat, file_path)
            file_size = stat.st_size
            file_mtime = stat.st_mtime
        except FileNotFoundError:
            return 0, 0
        except OSError as exc:
            logger.warning('[LLMLogIndex] 文件状态读取失败，将重试: %s: %s', file_path, exc)
            return 0, 1

        indexed_offset, prev_mtime, prev_count = await self._get_progress(file_path)

        # Current-hour files are immutable too unless size or mtime changes.
        # Exact mtime comparison detects same-size rewrites within one second.
        if indexed_offset == file_size and file_mtime == prev_mtime:
            return 0, 0  # 已完整索引，跳过

        # 如果文件变小了（被截断重建），重新索引
        if file_size < indexed_offset:
            indexed_offset = 0
            prev_count = 0
            # 删除旧索引
            import aiosqlite
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute("DELETE FROM llm_log_index WHERE log_file_path = ?", (file_path,))
                await conn.commit()

        # 解析文件
        entries = await asyncio.to_thread(_parse_log_file, file_path)
        if not entries:
            logger.warning("[LLMLogIndex] 日志解析未完成，将重试: %s", file_path)
            return 0, 1

        # 去重：避免重复索引同一条日志（按 log_timestamp + model + request_id 组合去重）
        if skip_duplicate_check:
            new_entries = entries
        else:
            new_entries = []
            for e in entries:
                if not await self._is_duplicate(e):
                    new_entries.append(e)

        if new_entries:
            inserted, errs = await self._insert_entries(new_entries)
            # Never mark a failed insert as consumed. Successful rows are
            # deduplicated on retry, including after a progress-write failure.
            if not errs:
                await self._save_progress(file_path, file_size, file_mtime, file_size, len(entries), 0)
            return inserted, errs
        else:
            await self._save_progress(file_path, file_size, file_mtime, file_size, len(entries), 0)
            return 0, 0

    async def _is_duplicate(self, entry: Dict[str, Any]) -> bool:
        """检查是否已索引（按时间戳 + 模型 + request_id 唯一）。"""
        import aiosqlite
        ts = entry.get("log_timestamp", "")
        model = entry.get("model", "")
        rid = entry.get("request_id", "")
        if not ts:
            return False
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute(
                "SELECT 1 FROM llm_log_index WHERE log_timestamp = ? AND model = ? AND request_id = ? AND log_file_path = ? LIMIT 1",
                (ts, model, rid, entry.get("log_file_path", "")),
            ) as cur:
                row = await cur.fetchone()
                return row is not None

    def _is_current_hour_file(self, file_path: str) -> bool:
        """判断文件是否属于当前小时。"""
        try:
            now = datetime.now()
            # 文件路径格式：.../YYYY-MM-DD/HH/filename.js
            parts = Path(file_path).parts
            if len(parts) >= 2:
                hour_dir = parts[-2]
                date_dir = parts[-3]
                today = now.strftime("%Y-%m-%d")
                cur_hour = now.strftime("%H")
                return date_dir == today and hour_dir == cur_hour
        except Exception:
            pass
        return False

    def _iter_log_files(self, recent_days: Optional[int] = None):
        """迭代日志文件；recent_days=None 表示全量。"""
        roots = []
        root = Path(self.logs_root)
        if recent_days is None:
            for dirpath, _dirnames, filenames in os.walk(self.logs_root):
                for fn in filenames:
                    if fn.endswith(".js"):
                        yield os.path.join(dirpath, fn)
            return

        cutoff = datetime.now().date() - timedelta(days=max(0, recent_days - 1))
        if root.exists():
            roots = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)
        for day_dir in roots:
            try:
                day = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < cutoff:
                continue
            for file_path in day_dir.rglob("*.js"):
                yield str(file_path)

    async def scan_all(
        self,
        *,
        recent_days: Optional[int] = 2,
        skip_duplicate_check: bool = False,
    ) -> Dict[str, Any]:
        """全量扫描日志目录，返回统计。"""
        async with self._scan_lock:
            return await self._scan_with_progress(recent_days, skip_duplicate_check)

    async def _scan_with_progress(self, recent_days, skip_duplicate_check=False):
        """Caller owns the scan lock, including automatic reconciliation."""
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as conn:
            query = 'SELECT file_path,indexed_offset,file_mtime,indexed_count,error_count FROM llm_log_index_progress'
            args = ()
            if recent_days is not None:
                cutoff = (datetime.now().date() - timedelta(days=max(0, recent_days-1))).isoformat()
                prefix = os.path.join(self.logs_root, '')
                query += ' WHERE file_path >= ? AND file_path < ?'
                args = (prefix+cutoff, prefix+'\uffff')
            async with conn.execute(
                query, args
            ) as cur:
                self._progress_snapshot = {
                    row[0]: (row[1] if not row[4] else -1, row[2], row[3])
                    for row in await cur.fetchall()
                }
        try:
            result = await self._scan_all(recent_days=recent_days, skip_duplicate_check=skip_duplicate_check)
            if result['success'] and (recent_days is None or recent_days >= 2):
                self._full_scan_at = time.monotonic()
            return result
        finally:
            self._progress_snapshot = None

    def _changed_files(self, recent_days, progress):
        """Enumerate and stat off-loop; unchanged files need no async DB work."""
        changed, skipped = [], 0
        for file_path in self._iter_log_files(recent_days=recent_days):
            try:
                stat = os.stat(file_path)
            except FileNotFoundError:
                skipped += 1
                continue
            except OSError:
                changed.append((file_path, None))  # retry/report through _scan_file
                continue
            offset, mtime, _ = progress.get(file_path, (0, 0.0, 0))
            if offset == stat.st_size and mtime == stat.st_mtime:
                skipped += 1
            else:
                changed.append((file_path, stat))
        return changed, skipped

    async def _scan_all(self, *, recent_days=2, skip_duplicate_check=False):
        start = time.time()
        total_inserted = 0
        total_errors = 0
        files_scanned = 0
        files_skipped = 0

        changed, files_skipped = await asyncio.to_thread(
            self._changed_files, recent_days, dict(self._progress_snapshot or {}))
        for file_path, file_stat in changed:
            try:
                inserted, errs = await self._scan_file(
                    file_path,
                    skip_duplicate_check=skip_duplicate_check, file_stat=file_stat,
                )
                if inserted == 0 and errs == 0:
                    files_skipped += 1
                else:
                    files_scanned += 1
                    total_inserted += inserted
                    total_errors += errs
            except Exception as e:
                logger.warning(f"⚠️ [LLMLogIndex] 扫描文件异常 {file_path}: {e}")
                total_errors += 1

        elapsed = time.time() - start
        result = {
            "success": total_errors == 0,
            "status": "partial" if total_errors else "success",
            "elapsed_sec": round(elapsed, 2),
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "entries_inserted": total_inserted,
            "errors": total_errors,
            "recent_days": recent_days,
        }
        if total_errors:
            logger.warning("[LLMLogIndex] 扫描部分失败，将重试: %s", result)
        else:
            logger.info(f"✅ [LLMLogIndex] 全量扫描完成: {result}")
        return result

    async def scan_incremental(self):
        """Use write notifications; reconcile disk after restart, overflow or age."""
        from ...log_index_changes import changes
        async with self._scan_lock:
            sequence, paths, overflow = changes.since(self._change_cursor)
            if overflow or time.monotonic() - self._full_scan_at >= self._reconcile_interval:
                result = await self._scan_with_progress(2)
                result['scan_mode'] = 'reconcile'
            else:
                root = os.path.normcase(os.path.abspath(self.logs_root))
                selected = []
                for path in paths:
                    try:
                        if os.path.commonpath((root, os.path.normcase(path))) == root and path.endswith('.js'):
                            selected.append(path)
                    except ValueError:
                        continue  # different drive; belongs to another indexer
                started = time.monotonic()
                inserted = errors = skipped = 0
                for path in selected:
                    try:
                        count, failures = await self._scan_file(path)
                        inserted += count
                        errors += failures
                        skipped += count == 0 and failures == 0
                    except Exception as exc:
                        errors += 1
                        logger.warning('[LLMLogIndex] 变化文件索引失败，将重试: %s: %s', path, exc)
                result = {'success': errors == 0, 'status': 'partial' if errors else 'success',
                          'entries_inserted': inserted, 'errors': errors,
                          'files_scanned': len(selected) - skipped, 'files_skipped': skipped,
                          'elapsed_sec': round(time.monotonic() - started, 3), 'scan_mode': 'changes'}
                if selected:
                    logger.info('[LLMLogIndex] 变化文件扫描: %s', result)
            if result['success']:
                # A write occurring during the scan has a newer sequence and
                # remains pending. Failed scans retain the old cursor to retry.
                self._change_cursor = sequence
            return result

    async def start_periodic_scan(self, interval: int = 30) -> None:
        """启动定时增量扫描（后台任务）。"""
        self._scan_interval = interval
        self._running = True
        logger.info(f"🔄 [LLMLogIndex] 定时增量扫描已启动 (间隔 {interval}s)")
        while self._running:
            try:
                await asyncio.sleep(interval)
                await self.scan_incremental()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ [LLMLogIndex] 增量扫描异常: {e}")
                traceback.print_exc()

    def stop_periodic_scan(self) -> None:
        """停止定时扫描。"""
        self._running = False

    async def rebuild_index(self) -> Dict[str, Any]:
        """重建全部索引（清空旧索引后重新扫描）。"""
        return await self.rebuild_index_fast()

    async def rebuild_index_fast(self) -> Dict[str, Any]:
        """Admin rebuild and automatic scans must never interleave DB writes."""
        async with self._scan_lock:
            return await self._rebuild_index_fast_locked()

    async def _rebuild_index_fast_locked(self) -> Dict[str, Any]:
        """高吞吐重建索引：全量解析文件，批量写入 SQLite。"""
        import aiosqlite

        start = time.time()
        logger.info("🔄 [LLMLogIndex] 开始快速重建全部索引…")
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM llm_log_index")
            await conn.execute("DELETE FROM llm_log_fts")
            await conn.execute("DELETE FROM llm_log_index_progress")
            await conn.execute("DELETE FROM llm_log_index_errors")
            await conn.execute("INSERT INTO llm_log_fts(llm_log_fts) VALUES ('rebuild')")
            await conn.commit()

        entries_batch: List[Dict[str, Any]] = []
        progress_batch: List[Tuple[str, int, float, int, int, int]] = []
        files_seen = 0
        files_parsed = 0
        files_skipped = 0
        inserted_total = 0
        errors = 0

        async def flush() -> None:
            nonlocal inserted_total, errors
            if not entries_batch and not progress_batch:
                return
            async with aiosqlite.connect(self.db_path) as conn:
                if entries_batch:
                    try:
                        await conn.executemany(
                            """INSERT INTO llm_log_index
                               (log_timestamp, date, hour, status, model, user_id, username,
                                conversation_id, request_id, trace_id, latency_ms,
                                prompt_tokens, completion_tokens, total_tokens, cost,
                                error_code, error_message, stage,
                                log_file_path, byte_offset, byte_length)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            [
                                (
                                    e.get("log_timestamp", ""),
                                    e.get("date", ""),
                                    e.get("hour", ""),
                                    e.get("status", "success"),
                                    e.get("model", ""),
                                    e.get("user_id", ""),
                                    e.get("username", ""),
                                    e.get("conversation_id", ""),
                                    e.get("request_id", ""),
                                    e.get("trace_id", ""),
                                    e.get("latency_ms", 0),
                                    e.get("prompt_tokens", 0),
                                    e.get("completion_tokens", 0),
                                    e.get("total_tokens", 0),
                                    e.get("cost", 0.0),
                                    e.get("error_code", ""),
                                    e.get("error_message", ""),
                                    e.get("stage", ""),
                                    e.get("log_file_path", ""),
                                    e.get("byte_offset", 0),
                                    e.get("byte_length", 0),
                                )
                                for e in entries_batch
                            ],
                        )
                        inserted_total += len(entries_batch)
                    except Exception as exc:
                        logger.warning(f"⚠️ [LLMLogIndex] 批量插入失败: {exc}")
                        errors += len(entries_batch)
                if progress_batch:
                    await conn.executemany(
                        """INSERT OR REPLACE INTO llm_log_index_progress
                           (file_path, file_size, file_mtime, indexed_offset, indexed_count, error_count, last_scan_at)
                           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                        progress_batch,
                    )
                await conn.commit()
            entries_batch.clear()
            progress_batch.clear()

        for file_path in self._iter_log_files(recent_days=None):
            files_seen += 1
            try:
                stat = os.stat(file_path)
                entries = _parse_log_file(file_path)
                if entries:
                    files_parsed += 1
                    entries_batch.extend(entries)
                else:
                    files_skipped += 1
                progress_batch.append(
                    (file_path, stat.st_size, stat.st_mtime, stat.st_size, len(entries), 0 if entries else 1)
                )
                if len(entries_batch) >= 1000 or len(progress_batch) >= 2000:
                    await flush()
            except Exception as exc:
                logger.warning(f"⚠️ [LLMLogIndex] 快速重建扫描异常 {file_path}: {exc}")
                errors += 1

        await flush()
        elapsed = time.time() - start
        result = {
            "success": True,
            "elapsed_sec": round(elapsed, 2),
            "files_seen": files_seen,
            "files_parsed": files_parsed,
            "files_skipped": files_skipped,
            "entries_inserted": inserted_total,
            "errors": errors,
        }
        logger.info(f"✅ [LLMLogIndex] 快速重建完成: {result}")
        return result


# 全局单例
_indexer: Optional[LLMLogIndexer] = None


def get_log_indexer(db_path: str) -> LLMLogIndexer:
    global _indexer
    if _indexer is None:
        _indexer = LLMLogIndexer(db_path)
    elif _indexer.db_path != db_path:
        _indexer = LLMLogIndexer(db_path)
    return _indexer
