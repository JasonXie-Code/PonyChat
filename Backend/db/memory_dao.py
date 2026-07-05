"""
长期记忆数据访问对象（DAO）
管理 character_memories 表：跨会话、跨活动的用户-角色关系记忆
"""
import re
from typing import List, Optional, Dict, Any, Tuple
from .database import get_database
from ..config import logger


async def add_memory(
    username: str,
    character_id: str,
    memory_type: str,
    content: str,
    source: str = "chat",
    importance: int = 5,
    created_at: Optional[str] = None,
) -> Optional[int]:
    """
    写入一条记忆。
    memory_type: 'preference' | 'episode' | 'relationship' | 'activity'
    importance: 1~10，值越高越优先注入上下文
    返回新记忆的 id，失败返回 None。
    """
    db = get_database()
    conn = await db.acquire()
    try:
        user_row = await conn.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_row = await user_row.fetchone()
        if not user_row:
            return None
        user_id = user_row[0]

        if created_at:
            cursor = await conn.execute(
                """INSERT INTO character_memories
                   (user_id, character_id, memory_type, content, source, importance, is_active, layer, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?)""",
                (user_id, character_id, memory_type, content, source, importance, created_at),
            )
        else:
            cursor = await conn.execute(
                """INSERT INTO character_memories
                   (user_id, character_id, memory_type, content, source, importance, is_active, layer)
                   VALUES (?, ?, ?, ?, ?, ?, 1, 0)""",
                (user_id, character_id, memory_type, content, source, importance),
            )
        await conn.commit()
        return cursor.lastrowid
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] 写入记忆失败: {e}")
        return None
    finally:
        await db.release(conn)


async def recall_memories(
    username: str,
    character_id: str,
    top_n: int = 12,
    memory_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    按重要度降序召回 top_n 条活跃记忆，并更新 last_recalled_at / recall_count。
    memory_types 为 None 时召回全部类型。
    """
    db = get_database()
    conn = await db.acquire()
    try:
        user_row = await conn.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_row = await user_row.fetchone()
        if not user_row:
            return []
        user_id = user_row[0]

        if memory_types:
            placeholders = ",".join("?" * len(memory_types))
            query = f"""
                SELECT id, memory_type, content, source, importance, created_at
                FROM character_memories
                WHERE user_id = ? AND character_id = ? AND is_active = 1
                  AND memory_type IN ({placeholders})
                ORDER BY importance DESC, created_at DESC
                LIMIT ?
            """
            params = (user_id, character_id, *memory_types, top_n)
        else:
            query = """
                SELECT id, memory_type, content, source, importance, created_at
                FROM character_memories
                WHERE user_id = ? AND character_id = ? AND is_active = 1
                ORDER BY importance DESC, created_at DESC
                LIMIT ?
            """
            params = (user_id, character_id, top_n)

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        if not rows:
            return []

        ids = [r[0] for r in rows]
        id_placeholders = ",".join("?" * len(ids))
        await conn.execute(
            f"""UPDATE character_memories
                SET last_recalled_at = CURRENT_TIMESTAMP,
                    recall_count = recall_count + 1
                WHERE id IN ({id_placeholders})""",
            ids,
        )
        await conn.commit()

        return [
            {
                "id": r[0],
                "memory_type": r[1],
                "content": r[2],
                "source": r[3],
                "importance": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] 召回记忆失败: {e}")
        return []
    finally:
        await db.release(conn)


async def deactivate_memories(
    username: str,
    character_id: str,
    memory_ids: List[int],
) -> None:
    """将指定记忆标记为非活跃（软删除），不实际删除。"""
    if not memory_ids:
        return
    db = get_database()
    conn = await db.acquire()
    try:
        placeholders = ",".join("?" * len(memory_ids))
        await conn.execute(
            f"UPDATE character_memories SET is_active = 0 WHERE id IN ({placeholders})",
            memory_ids,
        )
        await conn.commit()
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] 失效记忆失败: {e}")
    finally:
        await db.release(conn)


async def get_memory_count(username: str, character_id: str) -> int:
    """返回当前活跃记忆数量。"""
    db = get_database()
    conn = await db.acquire()
    try:
        user_row = await conn.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_row = await user_row.fetchone()
        if not user_row:
            return 0
        user_id = user_row[0]
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM character_memories WHERE user_id=? AND character_id=? AND is_active=1",
            (user_id, character_id),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0
    finally:
        await db.release(conn)


async def list_memories(
    username: str,
    character_id: str,
    memory_types: Optional[List[str]] = None,
    include_inactive: bool = False,
    layer: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    列出用户-角色的记忆，供管理界面展示。
    - layer=None  返回全部层（默认）
    - layer=0     只返回 Fragment 碎片层
    - layer=1/2/3/4  只返回 Daily/Weekly/Monthly/Annual 层
    - memory_types  仅对 Fragment 层（layer=0）有意义
    - include_inactive=True 时也返回已软删除的条目
    排序：Fragment 层按重要度降序；摘要层按 period 降序（最新的在前）。
    """
    db = get_database()
    conn = await db.acquire()
    try:
        user_row = await conn.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_row = await user_row.fetchone()
        if not user_row:
            return []
        user_id = user_row[0]

        is_active_filter = "" if include_inactive else "AND is_active = 1"
        layer_filter = f"AND COALESCE(layer, 0) = {int(layer)}" if layer is not None else ""
        order = "period DESC, id DESC" if (layer is not None and layer > 0) else "importance DESC, created_at DESC"

        if memory_types and (layer is None or layer == 0):
            placeholders = ",".join("?" * len(memory_types))
            query = f"""
                SELECT id, memory_type, content, source, importance, is_active,
                       created_at, last_recalled_at, recall_count,
                       COALESCE(layer, 0) as layer, period
                FROM character_memories
                WHERE user_id = ? AND character_id = ? {is_active_filter} {layer_filter}
                  AND memory_type IN ({placeholders})
                ORDER BY {order}
            """
            params = (user_id, character_id, *memory_types)
        else:
            query = f"""
                SELECT id, memory_type, content, source, importance, is_active,
                       created_at, last_recalled_at, recall_count,
                       COALESCE(layer, 0) as layer, period
                FROM character_memories
                WHERE user_id = ? AND character_id = ? {is_active_filter} {layer_filter}
                ORDER BY {order}
            """
            params = (user_id, character_id)

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        return [
            {
                "id": r[0],
                "memory_type": r[1],
                "content": r[2],
                "source": r[3],
                "importance": r[4],
                "is_active": bool(r[5]),
                "created_at": r[6],
                "last_recalled_at": r[7],
                "recall_count": r[8] or 0,
                "layer": r[9],
                "period": r[10],
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] 列出记忆失败: {e}")
        return []
    finally:
        await db.release(conn)


async def update_memory(
    username: str,
    character_id: str,
    memory_id: int,
    content: Optional[str] = None,
    importance: Optional[int] = None,
    memory_type: Optional[str] = None,
) -> bool:
    """更新指定记忆的内容/重要度/类型，返回是否成功。"""
    db = get_database()
    conn = await db.acquire()
    try:
        user_row = await conn.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_row = await user_row.fetchone()
        if not user_row:
            return False
        user_id = user_row[0]

        sets = []
        params: list = []
        if content is not None:
            sets.append("content = ?")
            params.append(content.strip())
        if importance is not None:
            sets.append("importance = ?")
            params.append(max(1, min(10, importance)))
        if memory_type is not None:
            sets.append("memory_type = ?")
            params.append(memory_type)
        if not sets:
            return False

        params += [memory_id, user_id, character_id]
        await conn.execute(
            f"UPDATE character_memories SET {', '.join(sets)} "
            f"WHERE id = ? AND user_id = ? AND character_id = ?",
            params,
        )
        await conn.commit()
        return True
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] 更新记忆失败: {e}")
        return False
    finally:
        await db.release(conn)


async def reactivate_memory(username: str, character_id: str, memory_id: int) -> bool:
    """将已软删除的记忆重新激活。"""
    db = get_database()
    conn = await db.acquire()
    try:
        user_row = await conn.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_row = await user_row.fetchone()
        if not user_row:
            return False
        user_id = user_row[0]
        await conn.execute(
            "UPDATE character_memories SET is_active = 1 WHERE id = ? AND user_id = ? AND character_id = ?",
            (memory_id, user_id, character_id),
        )
        await conn.commit()
        return True
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] 重新激活记忆失败: {e}")
        return False
    finally:
        await db.release(conn)


def format_memories_for_prompt(memories: List[Dict[str, Any]]) -> str:
    """
    将记忆列表格式化为注入 System Prompt 的文本块。
    返回空字符串表示无记忆可注入。
    """
    if not memories:
        return ""

    type_labels = {
        "preference": "偏好",
        "episode":    "经历",
        "relationship": "关系节点",
        "activity":   "共同活动",
    }

    lines = []
    for m in memories:
        label = type_labels.get(m.get("memory_type", ""), "记忆")
        lines.append(f"- [{label}] {m['content']}")

    return "【你记得和这位朋友共同经历的这些事】\n" + "\n".join(lines)


# ── 分层记忆（碎片 / 日 / 周 / 月 / 年 五层）──────────────
#
# layer 常量：
#   LAYER_FRAGMENT = 0  碎片（原始提取）       period = NULL
#   LAYER_DAILY    = 1  日摘要                 period = "YYYY-MM-DD"
#   LAYER_WEEKLY   = 2  周摘要                 period = "YYYY-WXX"  例如 "2026-W10"
#   LAYER_MONTHLY  = 3  月摘要                 period = "YYYY-MM"
#   LAYER_ANNUAL   = 4  年意识（追加演进历史）  period = "YYYY"
#
LAYER_FRAGMENT, LAYER_DAILY, LAYER_WEEKLY, LAYER_MONTHLY, LAYER_ANNUAL = 0, 1, 2, 3, 4

# 向后兼容别名（勿在新代码中使用）
LAYER_C, LAYER_D, LAYER_W, LAYER_M, LAYER_A = (
    LAYER_FRAGMENT, LAYER_DAILY, LAYER_WEEKLY, LAYER_MONTHLY, LAYER_ANNUAL
)

C_LAYER_RECALL_MAX = 36
C_LAYER_PINNED_RELATIONSHIP_MAX = 8
C_LAYER_PREFERENCE_MAX = 8
C_LAYER_RECENT_MAX = 12
C_LAYER_RELEVANT_MAX = 10
C_LAYER_RECENT_DAYS = 30


def _extract_recall_terms(query: str, *, limit: int = 8) -> List[str]:
    text = (query or "").strip()
    if not text:
        return []
    stopwords = {
        "你", "我", "他", "她", "它", "们", "的", "了", "吗", "呢", "啊", "吧",
        "现在", "当前", "刚才", "之前", "记得", "是不是", "什么", "怎么", "这个", "那个",
    }
    candidates: List[str] = []
    noise_chars = set("你我他她它们的了吗呢啊吧和在是有还哪什怎么当前之前刚才记得")
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,24}", text):
        if len(chunk) <= 6:
            candidates.append(chunk)
        for size in (4, 3, 2):
            if len(chunk) <= size:
                continue
            for i in range(0, len(chunk) - size + 1):
                gram = chunk[i:i + size]
                if not any(ch in noise_chars for ch in gram):
                    candidates.append(gram)
    candidates.extend(re.findall(r"[A-Za-z][A-Za-z0-9_]{2,24}", text))
    seen: set[str] = set()
    terms: List[str] = []
    for raw in candidates:
        term = raw.strip()
        if len(term) < 2 or term in stopwords:
            continue
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def _date_label(created_at: Any) -> str:
    text = str(created_at or "").strip()
    if not text:
        return ""
    return text[:10] if len(text) >= 10 else text


def _bridge_prev_month_iso_week(month_period: str) -> str | None:
    """
    A→M 桥接辅助：给定 'YYYY-MM'，返回其**上一个月最后一天**所在的 ISO 周字符串。
    用作 M→W 桥接的上边界：查询 period <= 此值 的周摘要，得到 M 窗口开始前的过渡周。
    """
    try:
        from datetime import date, timedelta
        year, month = map(int, month_period.split("-"))
        last_of_prev = date(year, month, 1) - timedelta(days=1)
        iso = last_of_prev.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except Exception:
        return None


def _bridge_iso_week_monday(week_period: str) -> str | None:
    """
    M→W 桥接辅助：给定 'YYYY-Www'，返回该周**周一**的日期字符串（'YYYY-MM-DD'）。
    用作 W→D 桥接的上边界：查询 period < 此值 的日摘要，得到 W 窗口开始前的过渡日。
    """
    try:
        from datetime import date
        parts = week_period.split("-W")
        if len(parts) != 2:
            return None
        monday = date.fromisocalendar(int(parts[0]), int(parts[1]), 1)
        return monday.isoformat()
    except Exception:
        return None


async def _resolve_user_id(conn, username: str) -> Optional[int]:
    """内部工具：用 username 查 user_id，不存在返回 None。"""
    row = await (await conn.execute("SELECT id FROM users WHERE username = ?", (username,))).fetchone()
    return row[0] if row else None


async def get_layer_periods(
    username: str,
    character_id: str,
    layer: int,
) -> List[str]:
    """
    返回指定层已有的 period 列表（升序），供调度器判断哪些周期尚未摘要。
    """
    db = get_database()
    conn = await db.acquire()
    try:
        uid = await _resolve_user_id(conn, username)
        if uid is None:
            return []
        cursor = await conn.execute(
            """SELECT DISTINCT period FROM character_memories
               WHERE user_id=? AND character_id=? AND layer=? AND is_active=1
                 AND period IS NOT NULL
               ORDER BY period ASC""",
            (uid, character_id, layer),
        )
        return [r[0] for r in await cursor.fetchall()]
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] get_layer_periods 失败: {e}")
        return []
    finally:
        await db.release(conn)


async def get_c_layer_periods(username: str, character_id: str) -> List[str]:
    """
    返回 C 层记忆所覆盖的自然日列表（YYYY-MM-DD），用于判断哪些天需要生成 D 层摘要。
    """
    db = get_database()
    conn = await db.acquire()
    try:
        uid = await _resolve_user_id(conn, username)
        if uid is None:
            return []
        cursor = await conn.execute(
            """SELECT DISTINCT strftime('%Y-%m-%d', created_at) as day
               FROM character_memories
               WHERE user_id=? AND character_id=? AND layer=0 AND is_active=1
               ORDER BY day ASC""",
            (uid, character_id),
        )
        return [r[0] for r in await cursor.fetchall() if r[0]]
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] get_c_layer_periods 失败: {e}")
        return []
    finally:
        await db.release(conn)


async def get_c_memories_for_period(
    username: str,
    character_id: str,
    period: str,
    period_type: str,  # "day" | "week" | "month" | "year"
) -> List[Dict[str, Any]]:
    """
    获取特定时间段内的 C 层记忆（供生成 D 层摘要）。
    period_type="day"   period="2026-03-05"
    period_type="week"  period="2026-W10"（ISO 周）
    period_type="month" period="2026-03"
    period_type="year"  period="2026"
    """
    db = get_database()
    conn = await db.acquire()
    try:
        uid = await _resolve_user_id(conn, username)
        if uid is None:
            return []

        if period_type == "day":
            date_filter = "strftime('%Y-%m-%d', created_at) = ?"
            params = (uid, character_id, period)
        elif period_type == "week":
            # period = "2026-W10"，转为 strftime('%Y-W%W', ...)
            date_filter = "strftime('%Y-W%W', created_at) = ?"
            params = (uid, character_id, period)
        elif period_type == "month":
            date_filter = "strftime('%Y-%m', created_at) = ?"
            params = (uid, character_id, period)
        else:  # 按年筛选
            date_filter = "strftime('%Y', created_at) = ?"
            params = (uid, character_id, period)

        cursor = await conn.execute(
            f"""SELECT id, memory_type, content, importance, created_at
                FROM character_memories
                WHERE user_id=? AND character_id=? AND layer=0 AND is_active=1
                  AND {date_filter}
                ORDER BY created_at ASC, importance DESC, id ASC""",
            params,
        )
        rows = await cursor.fetchall()
        return [
            {"id": r[0], "memory_type": r[1], "content": r[2],
             "importance": r[3], "created_at": r[4]}
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] get_c_memories_for_period 失败: {e}")
        return []
    finally:
        await db.release(conn)


async def get_raw_chat_messages_for_day(
    username: str,
    character_id: str,
    day: str,
) -> List[Dict[str, Any]]:
    """
    获取某个自然日内该用户-角色的完整可见原始对话，供 Daily 日摘生成使用。
    day 使用 YYYY-MM-DD，并与现有 C/D 层 period 的 SQLite UTC 日期口径保持一致。
    """
    db = get_database()
    conn = await db.acquire()
    try:
        uid = await _resolve_user_id(conn, username)
        if uid is None:
            return []
        cursor = await conn.execute(
            """SELECT m.id, m.role, m.content, COALESCE(m.timestamp, 0),
                      m.message_id, COALESCE(m.sequence_number, 0)
               FROM messages m
               JOIN conversations c ON m.conversation_id = c.id
               WHERE c.user_id=?
                 AND c.character_id=?
                 AND COALESCE(c.is_hidden, 0)=0
                 AND COALESCE(m.is_hidden, 0)=0
                 AND m.deleted_at IS NULL
                 AND m.role IN ('user', 'assistant')
                 AND date(COALESCE(m.timestamp, 0) / 1000, 'unixepoch') = ?
               ORDER BY COALESCE(m.timestamp, 0) ASC,
                        COALESCE(m.sequence_number, 0) ASC,
                        m.rowid ASC""",
            (uid, character_id, day),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": r[0],
                "role": r[1],
                "content": str(r[2] or ""),
                "timestamp": int(r[3] or 0),
                "message_id": r[4],
                "sequence_number": int(r[5] or 0),
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] get_raw_chat_messages_for_day 失败: {e}")
        return []
    finally:
        await db.release(conn)


async def get_layer_memories_all(
    username: str,
    character_id: str,
    layer: int,
) -> List[Dict[str, Any]]:
    """
    获取某层全部活跃记忆（按 period 升序），用于生成上层摘要。
    """
    db = get_database()
    conn = await db.acquire()
    try:
        uid = await _resolve_user_id(conn, username)
        if uid is None:
            return []
        cursor = await conn.execute(
            """SELECT id, period, content, created_at
               FROM character_memories
               WHERE user_id=? AND character_id=? AND layer=? AND is_active=1
               ORDER BY period ASC, id ASC""",
            (uid, character_id, layer),
        )
        return [
            {"id": r[0], "period": r[1], "content": r[2], "created_at": r[3]}
            for r in await cursor.fetchall()
        ]
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] get_layer_memories_all 失败: {e}")
        return []
    finally:
        await db.release(conn)


async def add_layer_memory(
    username: str,
    character_id: str,
    layer: int,
    content: str,
    period: str,
    importance: int = 7,
) -> Optional[int]:
    """
    写入 D/W/M/A 层摘要条目。
    memory_type 固定为 'summary'，source 固定为 'consolidator'。
    返回新记忆 id，失败返回 None。
    """
    db = get_database()
    conn = await db.acquire()
    try:
        uid = await _resolve_user_id(conn, username)
        if uid is None:
            return None
        cursor = await conn.execute(
            """INSERT INTO character_memories
               (user_id, character_id, memory_type, content, source, importance, is_active, layer, period)
               VALUES (?, ?, 'summary', ?, 'consolidator', ?, 1, ?, ?)""",
            (uid, character_id, content, importance, layer, period),
        )
        await conn.commit()
        return cursor.lastrowid
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] add_layer_memory 失败: {e}")
        return None
    finally:
        await db.release(conn)


async def recall_memories_layered(
    username: str,
    character_id: str,
    current_query: str = "",
) -> Dict[str, List[Dict[str, Any]]]:
    """
    滑动窗口联合召回，每层过渡带 2 条桥接条目防止记忆断层：

      A 层：全量年意识（所有年份，按 period ASC）
      A→M 桥接：最新年份的最后 2 个月摘
      M 层：最近 3 个月摘（与桥接去重合并）
      M→W 桥接：M 窗口最早月的前一个月最后 2 个周摘
      W 层：最近 4 个周摘（与桥接去重合并）
      W→D 桥接：W 窗口最早周开始前的最后 2 个日摘
      D 层：最近 5 个日摘（与桥接去重合并；滚动上下文记忆覆盖时由调用方 suppress）
      C 层：高重要关系节点、用户偏好、近期碎片、当前话题相关碎片多路合并，最多 36 条。

    同时更新 recall_count / last_recalled_at。
    """
    db = get_database()
    conn = await db.acquire()
    try:
        uid = await _resolve_user_id(conn, username)
        if uid is None:
            return {"a_entries": [], "m_entries": [], "w_entries": [],
                    "d_entries": [], "c_entries": []}

        def _rows(cursor_rows) -> List[Dict]:
            return [
                {"id": r[0], "memory_type": r[1], "content": r[2],
                 "period": r[3], "importance": r[4], "created_at": r[5]}
                for r in cursor_rows
            ]

        async def _fetch_raw(layer: int, where_extra: str = "", params_extra: tuple = (),
                             order: str = "period DESC", limit: int | None = None) -> List[Dict]:
            limit_clause = f"LIMIT {limit}" if limit is not None else ""
            cur = await conn.execute(
                f"""SELECT id, memory_type, content, period, importance, created_at
                    FROM character_memories
                    WHERE user_id=? AND character_id=? AND COALESCE(layer, 0)=? AND is_active=1
                    {where_extra}
                    ORDER BY {order}
                    {limit_clause}""",
                (uid, character_id, layer, *params_extra),
            )
            return _rows(await cur.fetchall())

        def _merge_dedup(*lists: List[Dict]) -> List[Dict]:
            seen: set = set()
            result: List[Dict] = []
            for lst in lists:
                for e in lst:
                    if e["id"] not in seen:
                        seen.add(e["id"])
                        result.append(e)
            return result

        # ── A 层：全量年意识 ──
        a = await _fetch_raw(LAYER_ANNUAL, order="period ASC")

        # ── A→M 桥接：最新年份的最后 2 个月摘 ──
        a_bridge_m: List[Dict] = []
        if a:
            latest_a_year = max((e["period"] or "") for e in a if e.get("period"))
            if latest_a_year:
                a_bridge_m = await _fetch_raw(
                    LAYER_MONTHLY,
                    where_extra="AND period LIKE ?",
                    params_extra=(f"{latest_a_year}-%",),
                    order="period DESC", limit=2,
                )

        # ── M 层：最近 3 个月摘 ──
        m_recent = await _fetch_raw(LAYER_MONTHLY, order="period DESC", limit=3)
        m_all = _merge_dedup(a_bridge_m, m_recent)

        # ── M→W 桥接：M 窗口最早月之前的最后 2 个周摘 ──
        m_bridge_w: List[Dict] = []
        if m_all:
            oldest_m = min((e["period"] or "") for e in m_all if e.get("period"))
            boundary_w = _bridge_prev_month_iso_week(oldest_m) if oldest_m else None
            if boundary_w:
                m_bridge_w = await _fetch_raw(
                    LAYER_WEEKLY,
                    where_extra="AND period <= ?",
                    params_extra=(boundary_w,),
                    order="period DESC", limit=2,
                )

        # ── W 层：最近 4 个周摘 ──
        w_recent = await _fetch_raw(LAYER_WEEKLY, order="period DESC", limit=4)
        w_all = _merge_dedup(m_bridge_w, w_recent)

        # ── W→D 桥接：W 窗口最早周开始前的最后 2 个日摘 ──
        w_bridge_d: List[Dict] = []
        if w_all:
            oldest_w = min((e["period"] or "") for e in w_all if e.get("period"))
            boundary_d = _bridge_iso_week_monday(oldest_w) if oldest_w else None
            if boundary_d:
                w_bridge_d = await _fetch_raw(
                    LAYER_DAILY,
                    where_extra="AND period < ?",
                    params_extra=(boundary_d,),
                    order="period DESC", limit=2,
                )

        # ── D 层：最近 5 个日摘 ──
        d_recent = await _fetch_raw(LAYER_DAILY, order="period DESC", limit=5)
        d_all = _merge_dedup(w_bridge_d, d_recent)

        # ── C 层：关键关系节点保底 + 普通碎片（不变） ──
        pin_cur = await conn.execute(
            """SELECT id, memory_type, content, period, importance, created_at
               FROM character_memories
               WHERE user_id=? AND character_id=? AND COALESCE(layer, 0)=? AND is_active=1
                 AND memory_type='relationship' AND importance>=9
               ORDER BY importance DESC, created_at DESC
               LIMIT ?""",
            (uid, character_id, LAYER_FRAGMENT, C_LAYER_PINNED_RELATIONSHIP_MAX),
        )
        pinned = _rows(await pin_cur.fetchall())

        async def _fetch_c(where_extra: str = "", params_extra: tuple = (),
                           order: str = "importance DESC, created_at DESC",
                           limit: int | None = None) -> List[Dict]:
            limit_clause = f"LIMIT {limit}" if limit is not None else ""
            cur = await conn.execute(
                f"""SELECT id, memory_type, content, period, importance, created_at
                    FROM character_memories
                    WHERE user_id=? AND character_id=? AND COALESCE(layer, 0)=? AND is_active=1
                    {where_extra}
                    ORDER BY {order}
                    {limit_clause}""",
                (uid, character_id, LAYER_FRAGMENT, *params_extra),
            )
            return _rows(await cur.fetchall())

        preferences = await _fetch_c(
            where_extra="AND memory_type='preference'",
            order="importance DESC, created_at DESC",
            limit=C_LAYER_PREFERENCE_MAX,
        )
        recent = await _fetch_c(
            where_extra=f"AND datetime(created_at) >= datetime('now', '-{C_LAYER_RECENT_DAYS} days')",
            order="created_at DESC, importance DESC",
            limit=C_LAYER_RECENT_MAX,
        )

        relevant: List[Dict] = []
        recall_terms = _extract_recall_terms(current_query)
        if recall_terms:
            where = "AND (" + " OR ".join(["content LIKE ?"] * len(recall_terms)) + ")"
            params = tuple(f"%{term}%" for term in recall_terms)
            relevant = await _fetch_c(
                where_extra=where,
                params_extra=params,
                order="importance DESC, created_at DESC",
                limit=C_LAYER_RELEVANT_MAX,
            )

        important = await _fetch_c(
            order="importance DESC, created_at DESC",
            limit=C_LAYER_RECALL_MAX,
        )
        c = _merge_dedup(pinned, preferences, recent, relevant, important)[:C_LAYER_RECALL_MAX]

        # ── 更新召回统计 ──
        all_ids = [e["id"] for e in (*a, *m_all, *w_all, *d_all, *c)]
        if all_ids:
            placeholders = ",".join("?" * len(all_ids))
            await conn.execute(
                f"""UPDATE character_memories
                    SET last_recalled_at=CURRENT_TIMESTAMP, recall_count=recall_count+1
                    WHERE id IN ({placeholders})""",
                all_ids,
            )
            await conn.commit()

        logger.info(
            "🧠 [长期记忆] 滑动窗口召回 | user=%s char=%s "
            "A=%d M=%d(含桥接%d) W=%d(含桥接%d) D=%d(含桥接%d) C=%d",
            username, (character_id or "")[:8],
            len(a),
            len(m_all), len(a_bridge_m),
            len(w_all), len(m_bridge_w),
            len(d_all), len(w_bridge_d),
            len(c),
        )
        return {"a_entries": a, "m_entries": m_all, "w_entries": w_all,
                "d_entries": d_all, "c_entries": c}
    except Exception as e:
        logger.warning(f"⚠️ [MemoryDAO] recall_memories_layered 失败: {e}")
        return {"a_entries": [], "m_entries": [], "w_entries": [],
                "d_entries": [], "c_entries": []}
    finally:
        await db.release(conn)


def format_layered_memories_for_prompt(
    a_entries: List[Dict[str, Any]],
    m_entries: List[Dict[str, Any]],
    w_entries: List[Dict[str, Any]],
    d_entries: List[Dict[str, Any]],
    c_entries: List[Dict[str, Any]],
    suppress_d_layer: bool = False,
    compact_cross_chat_fragments: bool = False,
    fragments_first: bool = False,
) -> str:
    """
    将五层记忆格式化为注入 System Prompt 的文本块。
    只包含有内容的层，空层不输出标题。
    suppress_d_layer=True 时跳过 D 层（日摘），用于新系统（context_memory）已覆盖近期时，
    避免两套记忆在近几天的时间段上重叠输出。
    各层均按 period 升序（ASC）排列，桥接条目自然融入其所属层的时间位置。
    """
    type_labels = {
        "preference": "偏好",
        "episode":    "经历",
        "relationship": "关系节点",
        "activity":   "共同活动",
        "summary":    "摘要",
    }

    def _sort_asc(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """按 period 升序（ASC）排序；period 为 None 的条目置于末尾。"""
        return sorted(entries, key=lambda e: (e.get("period") or "9999"))

    def _sort_fragment_timeline(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """碎片层按时间线从旧到新展示；无时间的条目置于末尾。"""
        return sorted(
            entries,
            key=lambda e: (
                e.get("created_at") or e.get("period") or "9999",
                e.get("id") or 0,
            ),
        )

    def _content_for_prompt(content: Any) -> str:
        text = str(content or "").strip()
        if not compact_cross_chat_fragments or not text:
            return text
        is_cross_chat = (
            "临时群聊" in text
            or "主聊天里被用户 @" in text
            or "主聊天形成" in text
            or "被用户 @ 临时加入发言" in text
        )
        if not is_cross_chat:
            return text
        for marker in ("；此前可见现场：", "；当时部分上下文：", "\n\n当时可见的部分上下文："):
            idx = text.find(marker)
            if idx >= 0:
                text = text[:idx].rstrip("；; \n")
        if len(text) > 900:
            text = text[:900].rstrip() + "……"
        return text + "（跨主聊天临时群聊摘要；详细现场原文仅供前置事实判断，不直接注入正文写作。）"

    sections: List[str] = []

    if a_entries:
        lines = [f"- [{e['period'] or ''}] {_content_for_prompt(e.get('content'))}" for e in _sort_asc(a_entries)]
        sections.append("【对你的整体认识（意识层）】\n" + "\n".join(lines))

    if m_entries:
        lines = [f"- [{e['period'] or ''}] {_content_for_prompt(e.get('content'))}" for e in _sort_asc(m_entries)]
        sections.append("【近期月度记忆】\n" + "\n".join(lines))

    if w_entries:
        lines = [f"- [{e['period'] or ''}] {_content_for_prompt(e.get('content'))}" for e in _sort_asc(w_entries)]
        sections.append("【近期周记忆】\n" + "\n".join(lines))

    if d_entries and not suppress_d_layer:
        lines = [f"- [{e['period'] or ''}] {_content_for_prompt(e.get('content'))}" for e in _sort_asc(d_entries)]
        sections.append("【近几天的记忆】\n" + "\n".join(lines))

    fragment_section = ""
    if c_entries:
        # 将 preference 类型单独提前，以加强指令权重
        pref_lines = []
        other_lines = []
        for e in c_entries:
            when = _date_label(e.get("created_at"))
            prefix = f"[{when}]" if when else "[未知时间]"
            if e.get("memory_type") == "preference":
                pref_lines.append(f"- {prefix} {_content_for_prompt(e.get('content'))}")
        for e in _sort_fragment_timeline(
            [entry for entry in c_entries if entry.get("memory_type") != "preference"]
        ):
            label = type_labels.get(e.get("memory_type", ""), "记忆")
            when = _date_label(e.get("created_at"))
            prefix = f"[{when}]" if when else "[未知时间]"
            other_lines.append(f"- {prefix}[{label}] {_content_for_prompt(e.get('content'))}")
        result_lines = []
        if pref_lines:
            result_lines.append("⚠️ 用户明确偏好（必须严格遵守）：\n" + "\n".join(pref_lines))
        if other_lines:
            result_lines.append("近期记忆碎片：\n" + "\n".join(other_lines))
        fragment_section = "【记忆碎片】\n" + "\n\n".join(result_lines)

    if fragment_section:
        if fragments_first:
            sections.insert(0, fragment_section)
        else:
            sections.append(fragment_section)

    return "\n\n".join(sections)
