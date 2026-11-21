"""
空闲期记忆固化调度器

用户与某角色的非流式普通对话结束 IDLE_THRESHOLD_SEC 秒后（默认10分钟），
后台自动提炼新对话内容，写入长期记忆。

相比逐条触发的旧方案，优势：
  1. 基于完整 session，上下文连贯，提取质量更高
  2. 零感知：对话过程中完全不触发，不影响响应速度
  3. 天然防重复：固化游标落库，只处理上次固化后新产生的消息
  4. 批量高效：多轮对话合并一次 LLM 调用
"""

import asyncio
import time
from typing import Dict, Set, List, Any

from ..config import logger
from ..shutdown_state import is_shutdown_requested

# ── 调度参数 ──────────────────────────────────────────────────────────────────
IDLE_THRESHOLD_SEC  = 600    # 用户停止聊天多久后触发固化（10分钟）
CHECK_INTERVAL_SEC  = 120    # 调度循环扫描间隔（2分钟）
INITIAL_DELAY_SEC   = 90     # 首次延迟（等待 DB / 模型就绪）
MAX_PAIRS_PER_CYCLE = 5      # 每轮最多处理的用户-角色对数量
CHUNK_SIZE          = 40     # 单次 LLM 调用处理的消息数上限
MIN_USER_TURNS      = 8      # 新内容中 user 消息数低于此值则跳过

# ── 内存状态 ──────────────────────────────────────────────────────────────────
# 键：f"{username}:{character_id}"
_chat_activity: Dict[str, Dict] = {}
# 值：{ "username": str, "character_id": str, "last_chat_at": float }

_consolidation_running: Set[str] = set()


# ── 公开接口 ──────────────────────────────────────────────────────────────────

def register_chat_activity(username: str, character_id: str) -> None:
    """
    在每次普通模式非流式对话完成后调用，记录最新活动时间。
    不阻塞，不触发任何提取，仅更新内存字典。
    """
    key = f"{username}:{character_id}"
    _chat_activity[key] = {
        "username": username,
        "character_id": character_id,
        "last_chat_at": time.time(),
    }


# ── 内部实现 ──────────────────────────────────────────────────────────────────

async def _resolve_user_id(conn, username: str) -> int | None:
    row_cur = await conn.execute("SELECT id FROM users WHERE username = ?", (username,))
    row = await row_cur.fetchone()
    return int(row[0]) if row else None


async def _get_last_consolidated_ms(username: str, character_id: str) -> int:
    from ..db.database import get_database

    db = get_database()
    conn = await db.acquire()
    try:
        user_id = await _resolve_user_id(conn, username)
        if user_id is None:
            return 0
        cur = await conn.execute(
            """SELECT last_consolidated_message_ts
               FROM memory_consolidation_state
               WHERE user_id=? AND character_id=?""",
            (user_id, character_id),
        )
        row = await cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception as e:
        logger.warning(f"⚠️ [MemConsolidator] 读取固化游标失败: {e}")
        return 0
    finally:
        await db.release(conn)


async def _set_last_consolidated_ms(username: str, character_id: str, last_ms: int) -> None:
    if last_ms <= 0:
        return

    from ..db.database import get_database

    db = get_database()
    conn = await db.acquire()
    try:
        user_id = await _resolve_user_id(conn, username)
        if user_id is None:
            return
        await conn.execute(
            """INSERT INTO memory_consolidation_state
                   (user_id, character_id, last_consolidated_message_ts, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id, character_id) DO UPDATE SET
                   last_consolidated_message_ts=excluded.last_consolidated_message_ts,
                   updated_at=CURRENT_TIMESTAMP""",
            (user_id, character_id, int(last_ms)),
        )
        await conn.commit()
    except Exception as e:
        logger.warning(f"⚠️ [MemConsolidator] 写入固化游标失败: {e}")
    finally:
        await db.release(conn)


async def _refresh_layers_after_consolidation(username: str, character_id: str) -> None:
    """新 Fragment 记忆写入后，尽力刷新 D/W/M/A 层。"""
    if is_shutdown_requested():
        return
    from ..db.database import get_database
    from .scheduler import process_pair_once

    db = get_database()
    conn = await db.acquire()
    try:
        cur = await conn.execute("SELECT name FROM characters WHERE id = ?", (character_id,))
        row = await cur.fetchone()
        char_name = str((row[0] if row else None) or "角色")
    except Exception:
        char_name = "角色"
    finally:
        await db.release(conn)

    try:
        await process_pair_once(username, character_id, char_name)
        logger.info(f"📅 [LayerScheduler] 固化后补跑完成: {username}/{character_id[:12]}...")
    except Exception as e:
        logger.warning(f"⚠️ [LayerScheduler] 固化后补跑失败 {username}/{character_id[:12]}...: {e}")


async def _load_new_messages_after_ms(
    username: str,
    character_id: str,
    since_ms: int,
) -> List[Dict[str, Any]]:
    """
    从 DB 加载该用户-角色组合中 since_ms 之后产生的全部可见消息。
    since_ms=0 时加载所有历史消息。
    """
    from ..db.database import get_database

    db = get_database()
    conn = await db.acquire()
    try:
        user_id = await _resolve_user_id(conn, username)
        if user_id is None:
            return []

        cursor = await conn.execute(
            """
            SELECT m.role, m.content, m.timestamp
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            WHERE c.user_id = ?
              AND c.character_id = ?
              AND COALESCE(c.is_hidden, 0) = 0
              AND COALESCE(m.is_hidden, 0) = 0
              AND m.deleted_at IS NULL
              AND COALESCE(m.timestamp, 0) > ?
            ORDER BY m.timestamp ASC, m.rowid ASC
            """,
            (user_id, character_id, since_ms),
        )
        rows = await cursor.fetchall()
        return [
            {"role": r[0], "content": str(r[1] or ""), "timestamp": r[2]}
            for r in rows
            if r[0] in ("user", "assistant")
        ]
    except Exception as e:
        logger.warning(f"⚠️ [MemConsolidator] 加载消息失败: {e}")
        return []
    finally:
        await db.release(conn)


async def _load_new_messages(
    username: str,
    character_id: str,
    since_ts: float,
) -> List[Dict[str, Any]]:
    """兼容旧调用：since_ts 为秒级 Unix 时间戳。"""
    return await _load_new_messages_after_ms(username, character_id, int(since_ts * 1000))


async def consolidate_pair_now(
    username: str,
    character_id: str,
    *,
    since_ms: int | None = None,
    source: str = "chat",
    update_state: bool = True,
    min_user_turns: int = MIN_USER_TURNS,
    chunk_size: int = CHUNK_SIZE,
) -> int:
    """
    立即固化一个 user-character 对，供后台空闲调度和历史回填脚本复用。

    since_ms=None 时读取落库游标；since_ms=0 表示从全部历史开始。
    返回本次写入的 C 层记忆条数。
    """
    from .extractor import do_extract

    cursor_ms = await _get_last_consolidated_ms(username, character_id) if since_ms is None else max(0, int(since_ms))
    messages = await _load_new_messages_after_ms(username, character_id, cursor_ms)
    if not messages:
        return 0

    user_turns = sum(1 for m in messages if m.get("role") == "user")
    if user_turns < min_user_turns:
        logger.info(
            f"⏭️ [MemConsolidator] 暂缓固化 {username}/{character_id[:12]}..."
            f" 新 user 轮数 {user_turns} < {min_user_turns}"
        )
        return 0

    logger.info(
        f"🧠 [MemConsolidator] 开始固化 | {username}/{character_id[:12]}... "
        f"| 新消息 {len(messages)} 条（user: {user_turns} 轮）"
    )

    chunks = [messages[i : i + chunk_size] for i in range(0, len(messages), chunk_size)]
    total_written = 0
    for idx, chunk in enumerate(chunks):
        written = await do_extract(username, character_id, chunk, source=source)
        total_written += written
        logger.info(
            f"🧠 [MemConsolidator] 块 {idx + 1}/{len(chunks)} 完成，写入 {written} 条"
        )

    if update_state:
        max_ts = max(int(m.get("timestamp") or 0) for m in messages)
        await _set_last_consolidated_ms(username, character_id, max_ts)

    if total_written > 0 and source != "chat_backfill" and not is_shutdown_requested():
        asyncio.create_task(_refresh_layers_after_consolidation(username, character_id))

    return total_written


async def _consolidate_pair(
    username: str,
    character_id: str,
) -> bool:
    """
    对一个用户-角色对执行一次完整记忆固化。
    只处理落库游标之后的新消息。
    消息量大时分块（每块 CHUNK_SIZE 条）分批提取。
    返回 True 表示成功提取了至少一条记忆。
    """
    return (await consolidate_pair_now(username, character_id)) > 0


async def _startup_recovery_scan() -> int:
    """
    服务启动时扫描 DB，找出所有"有待固化 user 消息"的用户-角色对并注入
    _chat_activity，避免重启后这些对话永久得不到固化。

    将 last_chat_at 设为足够早的时间（超过 IDLE_THRESHOLD_SEC），
    使其在 consolidation_loop 首轮扫描时就能被纳入候选。
    """
    from ..db.database import get_database

    db = get_database()
    conn = await db.acquire()
    try:
        cursor = await conn.execute(
            """
            SELECT u.username, c.character_id
            FROM conversations c
            JOIN users u ON c.user_id = u.id
            JOIN messages m ON m.conversation_id = c.id
            LEFT JOIN memory_consolidation_state mcs
                   ON mcs.user_id = c.user_id AND mcs.character_id = c.character_id
            WHERE COALESCE(c.is_hidden, 0) = 0
              AND COALESCE(m.is_hidden, 0) = 0
              AND m.deleted_at IS NULL
              AND m.role = 'user'
              AND COALESCE(m.timestamp, 0) > COALESCE(mcs.last_consolidated_message_ts, 0)
            GROUP BY u.username, c.character_id
            HAVING COUNT(*) > 0
            """
        )
        rows = await cursor.fetchall()
        count = 0
        past_ts = time.time() - IDLE_THRESHOLD_SEC - 1  # 让首轮扫描立即命中
        for username, character_id in rows:
            key = f"{username}:{character_id}"
            if key not in _chat_activity:
                _chat_activity[key] = {
                    "username": username,
                    "character_id": character_id,
                    "last_chat_at": past_ts,
                }
                count += 1
        return count
    except Exception as e:
        logger.warning(f"⚠️ [MemConsolidator] 启动补录扫库失败: {e}")
        return 0
    finally:
        await db.release(conn)


async def consolidation_loop() -> None:
    """
    后台调度主循环，每 CHECK_INTERVAL_SEC 秒扫描一次。
    找出"空闲超过 IDLE_THRESHOLD_SEC 且有未固化新内容"的用户-角色对，
    按空闲时长降序排列，每轮处理最多 MAX_PAIRS_PER_CYCLE 对。
    """
    await asyncio.sleep(INITIAL_DELAY_SEC)
    if is_shutdown_requested():
        logger.info("🛑 [MemConsolidator] shutdown 已请求，跳过启动补录")
        return

    recovered = await _startup_recovery_scan()
    if is_shutdown_requested():
        logger.info("🛑 [MemConsolidator] shutdown 已请求，启动补录状态留给下次启动处理")
        return
    if recovered > 0:
        logger.info(f"🔄 [MemConsolidator] 启动补录：注册 {recovered} 个重启前未固化的对话对")

    logger.info(
        f"🧠 [MemConsolidator] 空闲记忆固化调度器已启动"
        f"（空闲>{IDLE_THRESHOLD_SEC}s 触发，每 {CHECK_INTERVAL_SEC}s 扫描）"
    )

    while not is_shutdown_requested():
        try:
            now = time.time()
            candidates = []

            for key, info in list(_chat_activity.items()):
                last_chat = info.get("last_chat_at", 0.0)
                idle_sec = now - last_chat

                # 未到空闲阈值
                if idle_sec < IDLE_THRESHOLD_SEC:
                    continue
                # 正在固化中
                if key in _consolidation_running:
                    continue

                candidates.append((key, info, idle_sec))

            # 空闲最久的优先处理
            candidates.sort(key=lambda x: x[2], reverse=True)

            for key, info, idle_sec in candidates[:MAX_PAIRS_PER_CYCLE]:
                if is_shutdown_requested():
                    logger.info("🛑 [MemConsolidator] shutdown 已请求，剩余固化留给下次启动")
                    return
                _consolidation_running.add(key)
                username = info["username"]
                char_id = info["character_id"]

                try:
                    logger.info(
                        f"🕐 [MemConsolidator] 触发 {username}/{char_id[:12]}..."
                        f" 已空闲 {idle_sec / 60:.1f} 分钟"
                    )
                    ok = await _consolidate_pair(username, char_id)
                    if ok:
                        logger.info(f"✅ [MemConsolidator] 固化完成: {username}/{char_id[:12]}...")
                    else:
                        logger.info(f"⏭️ [MemConsolidator] 跳过（无有效新内容）: {username}/{char_id[:12]}...")
                    _chat_activity.pop(key, None)
                except Exception as e:
                    logger.warning(f"⚠️ [MemConsolidator] 固化异常 {key}: {e}")
                finally:
                    _consolidation_running.discard(key)

        except Exception as e:
            logger.warning(f"⚠️ [MemConsolidator] 调度循环异常: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SEC)

    logger.info("🛑 [MemConsolidator] shutdown 已请求，调度循环退出")
