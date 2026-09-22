"""
管理后台 · 对话日志审计 API

接口：
  GET  /admin/llm-logs/summary       → 按日期/小时维度的统计摘要
  GET  /admin/llm-logs               → 查询日志列表（分页 / cursor）
  GET  /admin/llm-logs/{id}          → 单条日志完整详情
  POST /admin/llm-logs/reindex       → 触发重建索引
  GET  /admin/llm-logs/export        → 按筛选条件导出
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiosqlite
from fastapi import APIRouter, HTTPException, Query

from .llm_log_indexer import get_log_indexer, _loads_debug_log_literal, _extract_debug_log_literal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm-logs")

# 查询最大 limit
MAX_LIMIT = 200
DEFAULT_LIMIT = 50


def _get_db_path() -> str:
    """获取索引数据库路径，复用主库路径。"""
    try:
        from ...config import DB_PATH
        return DB_PATH
    except Exception:
        from ...db.database import resolve_database_path
        return resolve_database_path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def _ensure_indexer():
    """确保索引器已初始化（懒初始化模式）。"""
    db_path = _get_db_path()
    indexer = get_log_indexer(db_path)
    await indexer.init_schema()
    return indexer


# ── 辅助函数：解析日志文件获取完整内容 ──

def _read_log_detail(file_path: str) -> Optional[Dict[str, Any]]:
    """从日志文件读取完整 debug_log 内容（兼容 JS 模板字符串）。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    literal = _extract_debug_log_literal(content)
    if literal is None:
        return None

    return _loads_debug_log_literal(literal)


# ── API 端点 ──

@router.get("/summary")
async def get_summary(
    hours: int = Query(default=720, ge=1, le=8760, description="统计最近 N 小时，默认 720（30天）"),
):
    """返回按日期/小时维度的日志统计摘要。"""
    try:
        indexer = await _ensure_indexer()
    except Exception as e:
        logger.error(f"获取索引器失败: {e}")
        return {"days": []}

    db_path = _get_db_path()
    since = (datetime.now() - timedelta(hours=hours)).isoformat()

    try:
        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute(
                """SELECT date, hour, COUNT(*) as total,
                          SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as errors
                   FROM llm_log_index
                   WHERE log_timestamp >= ?
                   GROUP BY date, hour
                   ORDER BY date DESC, hour DESC""",
                (since,),
            ) as cur:
                rows = await cur.fetchall()

        # 组织为嵌套结构
        days_map: Dict[str, Dict] = {}
        for date, hour, total, errors in rows:
            if date not in days_map:
                days_map[date] = {"date": date, "total": 0, "errors": 0, "hours": []}
            days_map[date]["total"] += total
            days_map[date]["errors"] += errors or 0
            days_map[date]["hours"].append({
                "hour": hour,
                "total": total,
                "errors": errors or 0,
            })

        days = sorted(days_map.values(), key=lambda d: d["date"], reverse=True)
        return {"days": days}

    except Exception as e:
        logger.error(f"获取日志摘要失败: {e}")
        return {"days": []}


@router.get("")
async def list_logs(
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = Query(default=None),
    date: Optional[str] = Query(default=None, description="日期 YYYY-MM-DD"),
    hour: Optional[str] = Query(default=None, description="小时 HH"),
    user_id: Optional[str] = Query(default=None, alias="userId"),
    username: Optional[str] = Query(default=None),
    conversation_id: Optional[str] = Query(default=None, alias="conversationId"),
    request_id: Optional[str] = Query(default=None, alias="requestId"),
    trace_id: Optional[str] = Query(default=None, alias="traceId"),
    model: Optional[str] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    min_latency: Optional[int] = Query(default=None, alias="minLatency"),
    max_latency: Optional[int] = Query(default=None, alias="maxLatency"),
    min_tokens: Optional[int] = Query(default=None, alias="minTokens"),
    max_tokens: Optional[int] = Query(default=None, alias="maxTokens"),
    cursor: Optional[str] = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    sort: Optional[str] = Query(default="time_desc", description="time_desc / latency_desc / tokens_desc / errors_first"),
):
    """查询日志列表（分页 / cursor）。默认最近 24 小时。"""
    try:
        await _ensure_indexer()
    except Exception as e:
        return {"items": [], "nextCursor": None, "hasMore": False}

    db_path = _get_db_path()
    conditions = []
    params: List[Any] = []

    # 时间范围
    if date:
        conditions.append("date = ?")
        params.append(date)
        if hour:
            conditions.append("hour = ?")
            params.append(hour)
    elif not from_ and not to:
        # 默认最近 30 天
        since = (datetime.now() - timedelta(hours=720)).isoformat()
        conditions.append("log_timestamp >= ?")
        params.append(since)

    if from_:
        conditions.append("log_timestamp >= ?")
        params.append(from_)
    if to:
        conditions.append("log_timestamp <= ?")
        params.append(to)

    # 精确筛选
    if user_id:
        conditions.append("(user_id = ? OR username = ?)")
        params.extend([user_id, user_id])
    if username:
        conditions.append("username = ?")
        params.append(username)
    if conversation_id:
        conditions.append("conversation_id = ?")
        params.append(conversation_id)
    if request_id:
        conditions.append("request_id = ?")
        params.append(request_id)
    if trace_id:
        conditions.append("trace_id = ?")
        params.append(trace_id)
    if model:
        conditions.append("model = ?")
        params.append(model)
    if provider:
        conditions.append("provider = ?")
        params.append(provider)
    if status:
        conditions.append("status = ?")
        params.append(status)

    # 数值范围
    if min_latency is not None:
        conditions.append("latency_ms >= ?")
        params.append(min_latency)
    if max_latency is not None:
        conditions.append("latency_ms <= ?")
        params.append(max_latency)
    if min_tokens is not None:
        conditions.append("total_tokens >= ?")
        params.append(min_tokens)
    if max_tokens is not None:
        conditions.append("total_tokens <= ?")
        params.append(max_tokens)

    # 关键词搜索（走 FTS5）
    fts_join = ""
    if keyword:
        fts_join = " INNER JOIN llm_log_fts ON llm_log_index.id = llm_log_fts.rowid"
        conditions.append("llm_log_fts MATCH ?")
        params.append(keyword)

    is_time_desc = sort in (None, "", "time_desc")

    # cursor 分页：默认时间倒序用 timestamp + id 复合游标，避免重建索引后 id 与时间不同步。
    if cursor:
        try:
            if is_time_desc and "|" in cursor:
                cursor_ts, cursor_id_text = cursor.rsplit("|", 1)
                cursor_id = int(cursor_id_text)
                conditions.append("(log_timestamp < ? OR (log_timestamp = ? AND id < ?))")
                params.extend([cursor_ts, cursor_ts, cursor_id])
            else:
                cursor_id = int(cursor)
                conditions.append("id < ?")
                params.append(cursor_id)
        except (ValueError, TypeError):
            pass

    # 排序
    sort_clause = "log_timestamp DESC, id DESC"
    if sort == "latency_desc":
        sort_clause = "latency_ms DESC, id DESC"
    elif sort == "tokens_desc":
        sort_clause = "total_tokens DESC, id DESC"
    elif sort == "errors_first":
        sort_clause = "CASE WHEN status != 'success' THEN 0 ELSE 1 END, id DESC"
    # time_desc 默认走 id DESC（时间序一致）

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""SELECT id, log_timestamp, date, hour, status, model, user_id, username,
                     conversation_id, request_id, trace_id, latency_ms,
                     prompt_tokens, completion_tokens, total_tokens, cost,
                     error_code, error_message, stage, log_file_path
              FROM llm_log_index{fts_join}
              WHERE {where_clause}
              ORDER BY {sort_clause}
              LIMIT ?"""
    params.append(limit + 1)  # 多取一条判断 hasMore

    try:
        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute(sql, params) as cur:
                rows = await cur.fetchall()

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        items = []
        for row in rows:
            items.append({
                "id": row[0],
                "timestamp": row[1],
                "date": row[2],
                "hour": row[3],
                "status": row[4],
                "model": row[5],
                "userId": row[6] or "",
                "username": row[7] or row[6] or "",
                "conversationId": row[8] or "",
                "requestId": row[9] or "",
                "traceId": row[10] or "",
                "latencyMs": row[11] or 0,
                "promptTokens": row[12] or 0,
                "completionTokens": row[13] or 0,
                "totalTokens": row[14] or 0,
                "cost": row[15] or 0.0,
                "errorCode": row[16] or "",
                "errorMessage": row[17] or "",
                "stage": row[18] or "",
            })

        if items and has_more:
            if is_time_desc:
                next_cursor = f"{items[-1]['timestamp'] or ''}|{items[-1]['id']}"
            else:
                next_cursor = str(items[-1]["id"])
        else:
            next_cursor = None
        return {"items": items, "nextCursor": next_cursor, "hasMore": has_more}

    except Exception as e:
        logger.error(f"查询日志列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/{log_id:int}")
async def get_log_detail(log_id: int):
    """获取单条日志完整详情（含请求、响应、原始 JSON）。"""
    await _ensure_indexer()
    db_path = _get_db_path()

    try:
        async with aiosqlite.connect(db_path) as conn:
            async with conn.execute(
                "SELECT log_file_path FROM llm_log_index WHERE id = ?", (log_id,)
            ) as cur:
                row = await cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="日志不存在")

        file_path = row[0]
        log_data = await asyncio.to_thread(_read_log_detail, file_path)

        if not log_data:
            raise HTTPException(status_code=500, detail="无法读取原始日志文件")

        data = log_data.get("data")
        params = log_data.get("params")
        if not isinstance(params, dict):
            params = {}

        # 分离请求和响应
        request = {}
        response: Any = {}
        if isinstance(data, dict):
            kind = data.get("kind", "")
            if kind in ('agent_request', 'agent_run'):
                request = data.get('request') or {}
                response = data if kind == 'agent_run' else {}
            elif kind == "llm_call_response":
                # 非流式：有完整 request / response
                request = data if "messages" in data else params
                response = data.get("choices") or data.get("content") or data
            elif kind == "llm_stream_response":
                response = data
            else:
                response = data
        elif data is not None:
            response = data

        # 尝试从 params 中恢复请求
        if not request:
            request = params

        # 脱敏处理
        safe_request = _mask_sensitive(request)
        safe_response = _mask_sensitive(response)
        safe_raw = _mask_sensitive(log_data)

        return {
            "id": log_id,
            "timestamp": log_data.get("timestamp"),
            "status": _infer_status_from_log(log_data),
            "model": log_data.get("model"),
            "userId": log_data.get("username") or "",
            "username": log_data.get("username"),
            "mode": log_data.get("mode"),
            "stage": log_data.get("stage"),
            "characterId": log_data.get("character_id") or log_data.get("primary_character_id"),
            "characterName": log_data.get("character_name"),
            "conversationId": _extract_conversation_id(log_data),
            "request": safe_request,
            "response": safe_response,
            "raw": safe_raw,
            "errorCode": _extract_error_code(log_data),
            "errorMessage": _extract_error_msg(log_data),
            "latencyMs": _extract_latency(log_data),
            "promptTokens": _extract_prompt_tokens(log_data),
            "completionTokens": _extract_completion_tokens(log_data),
            "totalTokens": _extract_total_tokens(log_data),
            "cost": 0.0,
            "requestId": _extract_req_id(log_data) or "",
            "traceId": _extract_trace_id(log_data) or "",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取日志详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"读取失败: {str(e)}")


@router.post("/reindex")
async def rebuild_index():
    """触发重建全部索引（建议仅超级管理员使用）。"""
    try:
        indexer = await _ensure_indexer()
        result = await indexer.rebuild_index()
        return result
    except Exception as e:
        logger.error(f"重建索引失败: {e}")
        raise HTTPException(status_code=500, detail=f"重建索引失败: {str(e)}")


@router.get("/export")
async def export_logs(
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = Query(default=None),
    date: Optional[str] = Query(default=None),
    hour: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None, alias="userId"),
    conversation_id: Optional[str] = Query(default=None, alias="conversationId"),
    request_id: Optional[str] = Query(default=None, alias="requestId"),
    trace_id: Optional[str] = Query(default=None, alias="traceId"),
    model: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=10000),
):
    """按筛选条件导出日志为 JSON。"""
    from fastapi.responses import StreamingResponse
    import io

    await _ensure_indexer()
    db_path = _get_db_path()

    conditions = []
    params: List[Any] = []

    for column, value in (('conversation_id', conversation_id), ('request_id', request_id), ('trace_id', trace_id)):
        if value:
            conditions.append(f'{column} = ?')
            params.append(value)

    if date:
        conditions.append("date = ?")
        params.append(date)
        if hour:
            conditions.append("hour = ?")
            params.append(hour)
    if user_id:
        conditions.append("(user_id = ? OR username = ?)")
        params.extend([user_id, user_id])
    if model:
        conditions.append("model = ?")
        params.append(model)
    if status:
        conditions.append("status = ?")
        params.append(status)
    if from_:
        conditions.append("log_timestamp >= ?")
        params.append(from_)
    if to:
        conditions.append("log_timestamp <= ?")
        params.append(to)

    fts_join = ""
    if keyword:
        fts_join = " INNER JOIN llm_log_fts ON llm_log_index.id = llm_log_fts.rowid"
        conditions.append("llm_log_fts MATCH ?")
        params.append(keyword)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""SELECT log_file_path FROM llm_log_index{fts_join}
              WHERE {where_clause}
              ORDER BY log_timestamp DESC, id DESC
              LIMIT ?"""
    params.append(limit)

    async def generate_export():
        yield '[\n'
        first = True
        count = 0
        try:
            async with aiosqlite.connect(db_path) as conn:
                async with conn.execute(sql, params) as cur:
                    async for row in cur:
                        file_path = row[0]
                        log_data = await asyncio.to_thread(_read_log_detail, file_path)
                        if log_data:
                            if not first:
                                yield ',\n'
                            first = False
                            yield json.dumps(_mask_sensitive(log_data), ensure_ascii=False, default=str)
                            count += 1
        except Exception as e:
            if not first:
                yield ',\n'
            yield json.dumps({'error': _mask_string_value(str(e))}, ensure_ascii=False)
        yield '\n]\n'

    return StreamingResponse(
        generate_export(),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=llm-logs-export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"},
    )


# ── 敏感信息脱敏 ──

# 需要脱敏的字段名（匹配 JSON key）
_MASK_KEYS = {
    'api_key', 'apiKey', 'apikey', 'secret', 'password', 'passwd', 'token',
    'auth_token', 'authToken', 'access_token', 'accessToken', 'refresh_token',
    'bearer', 'authorization', 'x-api-key', 'x-api-key',
}

# 需要脱敏的值模式（正则）
_MASK_VALUE_PATTERNS = [
    (re.compile(r'sk-[a-zA-Z0-9_-]{20,}'), 'sk-***'),
    (re.compile(r'sk-or-[a-zA-Z0-9_-]{20,}'), 'sk-or-***'),
    (re.compile(r'xai-[a-zA-Z0-9_-]{20,}'), 'xai-***'),
    (re.compile(r'Bearer\s+[a-zA-Z0-9._-]{20,}', re.IGNORECASE), 'Bearer ***'),
    # 手机号
    (re.compile(r'1[3-9]\d{9}'), '1**********'),
    # 邮箱
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), '***@***.***'),
]


def _mask_sensitive(obj: Any, depth: int = 0) -> Any:
    """递归脱敏，max depth 10 防止循环引用。"""
    if depth > 10:
        return obj
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            key_lower = k.lower().replace('-', '_')
            if key_lower in _MASK_KEYS:
                result[k] = '***REDACTED***'
            elif isinstance(v, str):
                result[k] = _mask_string_value(v)
            else:
                result[k] = _mask_sensitive(v, depth + 1)
        return result
    if isinstance(obj, list):
        return [_mask_sensitive(item, depth + 1) for item in obj]
    if isinstance(obj, str):
        return _mask_string_value(obj)
    return obj


def _mask_string_value(s: str) -> str:
    """对字符串值应用脱敏正则。"""
    for pattern, replacement in _MASK_VALUE_PATTERNS:
        s = pattern.sub(replacement, s)
    return s


# ── 辅助函数 ──

def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str).lower()
    except Exception:
        return str(value).lower()


def _infer_status_from_log(log_data: dict) -> str:
    data = log_data.get("data") if isinstance(log_data, dict) else None
    if isinstance(data, dict):
        if data.get('status') in ('success', 'error', 'timeout', 'interrupted'):
            return data['status']
        if data.get('incomplete') is True:
            return 'error'
    text = _json_text(data)
    for kw in ["timeout", "timed out"]:
        if kw in text:
            return "timeout"
    for kw in ["interrupted", "connection", "broken pipe"]:
        if kw in text:
            return "interrupted"
    data_dict = _as_dict(data)
    error = data_dict.get("error") or {}
    if (isinstance(error, dict) and error.get("message")) or (isinstance(error, str) and error):
        return "error"
    return "success"


def _extract_error_code(log_data: dict) -> str:
    data = _as_dict(log_data.get("data") if isinstance(log_data, dict) else None)
    error = data.get("error") or {}
    if isinstance(error, dict):
        return str(error.get("code") or error.get("type") or "")
    return ""


def _extract_error_msg(log_data: dict) -> str:
    data = _as_dict(log_data.get("data") if isinstance(log_data, dict) else None)
    error = data.get("error") or {}
    if isinstance(error, dict):
        return str(error.get("message") or "")
    return str(error) if isinstance(error, str) and error else ""


def _extract_latency(log_data: dict) -> int:
    data = _as_dict(log_data.get("data") if isinstance(log_data, dict) else None)
    v = data.get("latency_ms") or data.get("latency") or data.get("elapsed") or 0
    if isinstance(v, float):
        return int(v * 1000) if v < 1000 else int(v)
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _extract_prompt_tokens(log_data: dict) -> int:
    data = _as_dict(log_data.get("data") if isinstance(log_data, dict) else None)
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        return 0
    return int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)


def _extract_completion_tokens(log_data: dict) -> int:
    data = _as_dict(log_data.get("data") if isinstance(log_data, dict) else None)
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        return 0
    return int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)


def _extract_total_tokens(log_data: dict) -> int:
    return _extract_prompt_tokens(log_data) + _extract_completion_tokens(log_data)


def _extract_req_id(log_data: dict) -> str:
    log_dict = _as_dict(log_data)
    data = _as_dict(log_dict.get("data"))
    params = _as_dict(log_dict.get("params"))
    for k in ("id", "request_id", "requestId", "trace_id", "traceId"):
        v = data.get(k) or params.get(k) or log_dict.get(k)
        if v and isinstance(v, str):
            return v
    return ""


def _extract_trace_id(log_data: dict) -> str:
    log_dict = _as_dict(log_data)
    data = _as_dict(log_dict.get("data"))
    params = _as_dict(log_dict.get("params"))
    for k in ("trace_id", "traceId", "request_id", "requestId", "id"):
        v = data.get(k) or params.get(k) or log_dict.get(k)
        if v and isinstance(v, str):
            return v
    return ""


def _extract_conversation_id(log_data: dict) -> str:
    log_dict = _as_dict(log_data)
    params = _as_dict(log_dict.get("params"))
    for k in ("conversation_id", "conversationId"):
        v = params.get(k) or log_dict.get(k)
        if v and isinstance(v, str):
            return v
    return ""
