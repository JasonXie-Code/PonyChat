"""
管理后台 — 系统状态与统计 API

🗄️ [2026-02-06] 全面迁移到数据库：
   - 统计数据全部从数据库读取
   - 文件系统回退仅在禁用文件系统为 False 时启用
"""
import os
import asyncio
import time
import datetime
import calendar
import psutil
from fastapi import APIRouter, HTTPException, Response
from pathlib import Path
from ...config import logger, model_manager
from ...websocket import manager

# 🗄️ [数据库] 导入数据库访问层
from ...db import get_database, get_users_dao

router = APIRouter()


def _usage_cost_cny(input_tokens: int, output_tokens: int) -> float:
    """用量费用（元）：输入 ¥2/百万 + 输出 ¥10/百万（与客户端展示口径一致）。"""
    return input_tokens / 1_000_000.0 * 2.0 + output_tokens / 1_000_000.0 * 10.0


def _disk_root() -> str:
    if os.name == "nt":
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


def _read_linux_cpu_totals() -> tuple[int, int] | None:
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            parts = f.readline().split()
    except Exception:
        return None
    if not parts or parts[0] != "cpu":
        return None
    try:
        values = [int(v) for v in parts[1:]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return idle, sum(values)


def _sample_linux_cpu_percent(interval: float = 0.25) -> float | None:
    first = _read_linux_cpu_totals()
    if first is None:
        return None
    time.sleep(interval)
    second = _read_linux_cpu_totals()
    if second is None:
        return None
    idle_delta = second[0] - first[0]
    total_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    busy_delta = max(0, total_delta - idle_delta)
    return max(0.0, min(100.0, busy_delta / total_delta * 100.0))


def _get_cpu_percent() -> float:
    if os.name != "nt" and os.path.exists("/proc/stat"):
        sampled = _sample_linux_cpu_percent()
        if sampled is not None:
            return round(sampled, 1)
    return round(psutil.cpu_percent(interval=0.25), 1)


@router.get("/system-status")
async def get_system_status(response: Response):
    """获取系统实时状态监控数据"""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    try:
        start_time = time.time()

        users_dao = get_users_dao()
        users_data = await users_dao.get_all_users()
        active_users = len(manager.active_connections)
        total_users = len(users_data)

        total_characters = 0
        total_messages = 0
        try:
            import aiosqlite

            db = get_database()
            await db.init()
            async with aiosqlite.connect(db.db_path) as conn:
                async with conn.execute("SELECT COUNT(*) FROM characters") as cursor:
                    row = await cursor.fetchone()
                    total_characters = row[0] if row else 0

                for table in ("messages", "galgame_messages", "galgame_lock_messages"):
                    try:
                        async with conn.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                            row = await cursor.fetchone()
                            total_messages += row[0] if row else 0
                    except Exception as e:
                        logger.warning(f"⚠️ [DB] 统计 {table} 消息数量失败: {e}")
        except Exception as e:
            logger.warning(f"⚠️ [DB] 统计角色/消息数量失败: {e}")

        storage_bytes = 0
        try:
            db_path = Path(__file__).resolve().parent.parent.parent / "database"
            if db_path.exists():
                for f in db_path.rglob("*"):
                    if f.is_file():
                        storage_bytes += f.stat().st_size
        except Exception:
            pass

        s_usage = f"{storage_bytes / (1024*1024):.1f} MB" if storage_bytes else "0 MB"
        active_model = model_manager.get_active_model()

        cpu_percent = await asyncio.to_thread(_get_cpu_percent)
        try:
            vm = psutil.virtual_memory()
            mem_used_mb = round(vm.used / (1024 * 1024), 1)
            mem_total_mb = round(vm.total / (1024 * 1024), 1)
            mem_percent = round(vm.percent, 1)
        except Exception:
            mem_used_mb = mem_total_mb = mem_percent = 0.0

        try:
            du = psutil.disk_usage(_disk_root())
            disk_percent = round(du.percent, 1)
            disk_free_gb = round(du.free / (1024**3), 2)
        except Exception:
            disk_percent = 0.0
            disk_free_gb = 0.0

        return {
            "backend_status": "运行中",
            "active_users": active_users,
            "total_users": total_users,
            "total_characters": total_characters,
            "total_messages": total_messages,
            "active_conversations": total_characters,
            "active_model": active_model["name"] if active_model else "未选择",
            "storage_usage": s_usage,
            "response_time": round((time.time() - start_time) * 1000, 2),
            "timestamp": datetime.datetime.now().isoformat(),
            "cpu_percent": cpu_percent,
            "memory_used_mb": mem_used_mb,
            "memory_total_mb": mem_total_mb,
            "memory_percent": mem_percent,
            "disk_percent": disk_percent,
            "disk_free_gb": disk_free_gb,
        }
    except Exception as e:
        logger.error(f"获取系统状态失败: {e}")
        return {
            "backend_status": "错误",
            "timestamp": datetime.datetime.now().isoformat(),
        }


@router.get("/uptime-heatmap")
async def get_uptime_heatmap(response: Response, days: int = 30, mode: str = "month"):
    """获取后端与语音系统最近 N 天可用性热力图数据。"""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    try:
        from ...uptime_monitor import build_uptime_heatmap

        return await build_uptime_heatmap(days=days, mode=mode, refresh=True)
    except Exception as e:
        logger.error(f"获取 uptime 热力图失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_admin_stats():
    """获取管理后台概览统计图表数据"""
    try:
        users_dao = get_users_dao()
        users_data = await users_dao.get_all_users()
        total_users = len(users_data)

        total_characters = 0
        total_conversations_msgs = 0
        active_users = len(manager.active_connections)

        today = datetime.date.today()
        dates = [(today - datetime.timedelta(days=i)) for i in range(6, -1, -1)]
        date_strs = [d.strftime("%Y-%m-%d") for d in dates]
        date_labels = [d.strftime("%m-%d") for d in dates]

        user_growth = {k: 0 for k in date_strs}
        msg_activity = {k: 0 for k in date_strs}
        token_by_day = {k: 0 for k in date_strs}

        cumulative_input_tokens = 0
        cumulative_output_tokens = 0

        today_input_tokens = 0
        today_output_tokens = 0
        today_chats = 0

        top_token_users = []

        try:
            import aiosqlite

            db = get_database()
            await db.init()
            async with aiosqlite.connect(db.db_path) as conn:
                async with conn.execute("SELECT COUNT(*) FROM characters") as cursor:
                    row = await cursor.fetchone()
                    total_characters = row[0] if row else 0

                async with conn.execute("SELECT COUNT(*) FROM messages") as cursor:
                    row = await cursor.fetchone()
                    total_conversations_msgs = row[0] if row else 0

                try:
                    async with conn.execute("SELECT COUNT(*) FROM galgame_messages") as cursor:
                        row = await cursor.fetchone()
                        total_conversations_msgs += row[0] if row else 0
                except Exception:
                    pass

                try:
                    async with conn.execute("SELECT COUNT(*) FROM galgame_lock_messages") as cursor:
                        row = await cursor.fetchone()
                        total_conversations_msgs += row[0] if row else 0
                except Exception:
                    pass

                async with conn.execute(
                    "SELECT created_at FROM users WHERE created_at IS NOT NULL"
                ) as cursor:
                    async for row in cursor:
                        try:
                            created_str = row[0]
                            if created_str:
                                reg_date = created_str[:10]
                                if reg_date in user_growth:
                                    user_growth[reg_date] += 1
                        except Exception:
                            pass

                seven_days_ago = today - datetime.timedelta(days=7)
                seven_days_ago_ts = int(calendar.timegm(seven_days_ago.timetuple())) * 1000

                if seven_days_ago_ts > 0:
                    async with conn.execute(
                        "SELECT timestamp FROM messages WHERE timestamp > ?",
                        (seven_days_ago_ts,),
                    ) as cursor:
                        async for row in cursor:
                            try:
                                ts = row[0]
                                if ts:
                                    if ts > 1000000000000:
                                        ts = ts / 1000
                                    msg_date = datetime.date.fromtimestamp(ts).strftime("%Y-%m-%d")
                                    if msg_date in msg_activity:
                                        msg_activity[msg_date] += 1
                            except Exception:
                                pass

                # 累计 token（全站，输入/输出合并口径）
                try:
                    async with conn.execute(
                        """
                        SELECT
                          COALESCE(SUM(
                            COALESCE(total_input_tokens, 0) + COALESCE(total_cache_read_tokens, 0)
                            + COALESCE(companion_input_tokens, 0) + COALESCE(companion_cache_read_tokens, 0)
                          ), 0),
                          COALESCE(SUM(
                            COALESCE(total_output_tokens, 0) + COALESCE(companion_output_tokens, 0)
                          ), 0)
                        FROM users
                        """
                    ) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            cumulative_input_tokens = int(row[0] or 0)
                            cumulative_output_tokens = int(row[1] or 0)
                except Exception as e:
                    logger.warning(f"⚠️ [stats] 累计 token 聚合失败: {e}")

                today_s = today.isoformat()
                # 今日大模型调用次数（daily_token_usage.llm_calls，含主对话/陪玩/记忆/主动消息等所有埋点）
                try:
                    async with conn.execute(
                        """
                        SELECT COALESCE(SUM(COALESCE(llm_calls, 0)), 0)
                        FROM daily_token_usage
                        WHERE usage_date = ?
                        """,
                        (today_s,),
                    ) as cursor:
                        row = await cursor.fetchone()
                        today_chats = int(row[0] or 0) if row else 0
                except Exception:
                    try:
                        async with conn.execute(
                            "SELECT COALESCE(SUM(usage_count), 0) FROM daily_chat_usage WHERE usage_date = ?",
                            (today_s,),
                        ) as cursor:
                            row = await cursor.fetchone()
                            today_chats = int(row[0] or 0) if row else 0
                    except Exception:
                        pass

                # 今日 token（日表：主对话与陪玩并入输入/输出）
                try:
                    async with conn.execute(
                        """
                        SELECT
                          COALESCE(SUM(input_tokens + companion_in), 0),
                          COALESCE(SUM(output_tokens + companion_out), 0)
                        FROM daily_token_usage
                        WHERE usage_date = ?
                        """,
                        (today_s,),
                    ) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            today_input_tokens = int(row[0] or 0)
                            today_output_tokens = int(row[1] or 0)
                except Exception:
                    pass

                # 7 日 token 趋势
                try:
                    d0 = date_strs[0]
                    d1 = date_strs[-1]
                    async with conn.execute(
                        """
                        SELECT usage_date,
                          COALESCE(SUM(input_tokens + output_tokens + companion_in + companion_out), 0)
                        FROM daily_token_usage
                        WHERE usage_date >= ? AND usage_date <= ?
                        GROUP BY usage_date
                        """,
                        (d0, d1),
                    ) as cursor:
                        async for row in cursor:
                            ds = row[0]
                            if ds in token_by_day:
                                token_by_day[ds] = int(row[1] or 0)
                except Exception as e:
                    logger.warning(f"⚠️ [stats] token 趋势失败: {e}")

                # Token 用量 Top 10 用户
                try:
                    async with conn.execute(
                        """
                        SELECT username,
                          COALESCE(total_input_tokens,0)+COALESCE(total_output_tokens,0)
                          +COALESCE(total_cache_read_tokens,0)
                          +COALESCE(companion_input_tokens,0)+COALESCE(companion_output_tokens,0)
                          +COALESCE(companion_cache_read_tokens,0) AS tot
                        FROM users
                        ORDER BY tot DESC
                        LIMIT 10
                        """
                    ) as cursor:
                        async for row in cursor:
                            top_token_users.append(
                                {"username": row[0], "total_tokens": int(row[1] or 0)}
                            )
                except Exception as e:
                    logger.warning(f"⚠️ [stats] top_token_users 失败: {e}")

            logger.info(f"📊 [DB] 统计数据: {total_characters} 角色, {total_conversations_msgs} 消息")

        except Exception as e:
            logger.warning(f"⚠️ [DB] 数据库统计失败: {e}")

        # 昨日对比（用于趋势箭头）
        def _yesterday_delta(series_dict, date_keys):
            if len(date_keys) < 2:
                return 0, 0
            last = date_keys[-1]
            prev = date_keys[-2]
            return series_dict.get(last, 0) - series_dict.get(prev, 0), series_dict.get(prev, 0)

        u_delta, _ = _yesterday_delta(user_growth, date_strs)
        m_delta, _ = _yesterday_delta(msg_activity, date_strs)
        t_delta, _ = _yesterday_delta(token_by_day, date_strs)

        return {
            "total_users": total_users,
            "total_characters": total_characters,
            "total_conversations": total_conversations_msgs,
            "active_users": active_users,
            "charts": {
                "dates": date_labels,
                "user_trend": [user_growth[d] for d in date_strs],
                "conversation_trend": [msg_activity[d] for d in date_strs],
                "token_trend": [token_by_day[d] for d in date_strs],
            },
            "deltas": {
                "users_vs_yesterday": u_delta,
                "msgs_vs_yesterday": m_delta,
                "tokens_vs_yesterday": t_delta,
            },
            "token_summary": {
                "today_input_tokens": today_input_tokens,
                "today_output_tokens": today_output_tokens,
                "today_total_tokens": today_input_tokens + today_output_tokens,
                "today_cost_cny": _usage_cost_cny(today_input_tokens, today_output_tokens),
                "cumulative_input_tokens": cumulative_input_tokens,
                "cumulative_output_tokens": cumulative_output_tokens,
                "cumulative_total_tokens": cumulative_input_tokens + cumulative_output_tokens,
                "cumulative_cost_cny": _usage_cost_cny(
                    cumulative_input_tokens, cumulative_output_tokens
                ),
            },
            "today_chats": today_chats,
            "today_llm_calls": today_chats,
            "top_token_users": top_token_users,
        }
    except Exception as e:
        logger.error(f"获取后台统计失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
