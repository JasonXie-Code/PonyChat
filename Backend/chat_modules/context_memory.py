"""普通对话模式（mode="normal"）分层上下文记忆系统。

三层架构（参照 galgame/memory.py）：
  entries          — 最近若干轮的单轮中性改写（事实记录，含完整细节、无文风示范；逐轮生成）
  short_term_memory — entries 折叠后的中期事实摘要（< SHORT_TERM_MAX_TURNS 轮）
  long_term_memory  — short_term_memory 溢出后的长期事实摘要

主补全：最近少量真实尾部历史直接进入主模型，更早事实由【上下文记忆】提供；与主模型 user/assistant 段组装方式见 request_context.assemble_messages。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from typing import Any

from ..config import logger
from ..user_identity import USER_MEMORY_PLACEHOLDER, normalize_user_memory_text

# 分层阈值（与 galgame/memory.py 保持一致）
KEEP_VERBATIM_MAX = 15
KEEP_VERBATIM_AFTER_TRIM = 8
SHORT_TERM_MAX_TURNS = 16

# 单轮中性改写：输入截断与输出预算（与 galgame 记忆侧量级相近，避免长回合裁尾）
ENTRY_REWRITE_INPUT_MAX_CHARS = 1200
CTX_ENTRY_REWRITE_MAX_TOKENS = 16384
# 折叠摘要输出预算：统一 16384，避免模型超写时被厂商 max_tokens 截断
CTX_SHORT_MERGE_MAX_TOKENS = 16384
CTX_LONG_MERGE_MAX_TOKENS = 16384
# 最近若干「用户键入」为左边界，截取尾部聊天气泡（可含同侧连发，模拟 QQ/微信）
CTX_ENTRY_RECENT_USER_TURNS = 3
CTX_ENTRY_RECENT_BLOCK_MAX_CHARS = 5000
CTX_ENTRY_RECENT_BUBBLE_LINE_MAX = 2000
# 注入与折叠块中「第N轮」时间展示时区（便于角色感知跨时段）
CTX_ENTRY_DISPLAY_TZ = "Asia/Shanghai"

_ASSISTANT_RAW_CONTRAST_RE = re.compile(
    r"(?P<prefix>[^。！？；\n]{0,12}?)(?<!是)不是(?P<neg>[^。！？；\n]{1,80}?)(?:，|,)?而是(?P<pos>[^。！？；\n]+)"
)

_MINIGAME_MEMORY_PRESERVE_RULE = (
    "【小游戏/对局记忆保真】若输入是中国象棋、小游戏、对局结算或含有“棋局互动事实/最近棋局对话”，"
    "胜负和走法之外，闲聊内容、口令、留言、昵称、约定、赌注、赌约、兑现条件、投降/认输/悔棋、输赢挑衅、用户提出的要求和角色回应都属于高价值事实。"
    "只要原料里有明确记录，就必须中性保留具体内容和双方主体；不得因亲密/成人语义、篇幅压缩或摘要风格而删掉，"
    "也不得降级为“具体内容未记录”“只是一个要求”“只是闲聊”。可以去除口癖和剧本语气，但要保留可回答用户追问的事实。"
    "用户在本局原话中明说的闲聊内容、口令、赌注B、升级赌注C和兑现条件，是当前局事实锚；"
    "若输入含“用户明示当前局 A/B/C 事实锚”或 user_stated_current_game_abc_fact，摘要必须逐项保留这些用户原话锚点；"
    "若角色后续把这些内容复述成旧口令、旧赌注或其它跨局内容，只能记录为角色说错/串台，不得用角色错误复述覆盖用户明示事实。"
    "若同一约定/赌注在对局中被升级或改写，必须保留旧版本、新版本和角色是否接受，并标明当前有效版本。"
)

_MINIGAME_RECENT_REPLY_PRIORITY_RULE = (
    "【刚结束小游戏记忆优先】若记录中含有“中国象棋对局记忆”“棋局互动事实”或“最近棋局对话”，"
    "且用户当前问刚才、刚刚、刚退出、刚结束的游戏/这局/A/B/C/闲聊/口令/赌注/赌约/兑现/谁赢谁输/谁要做什么，"
    "必须把这条最近上下文记忆当作本轮最高优先级事实。长期记忆、跨会话旧摘要和角色设定只能作为背景，不能覆盖这条刚结束游戏记录。"
    "若同一块上下文记忆里有多条中国象棋/小游戏对局记录，必须按轮次编号、时间或出现顺序取最后一条/最新一条；"
    "更早条目只作历史背景，不能先命中旧 A/B/C 后停止。"
    "回答时要按记录保留 A 对应的闲聊内容或口令、B 的原始赌注、C 的最新赌注、胜负结果和兑现主体；"
    "若 B 已升级为 C，当前有效版本是 C，可简短说明 B 已被替代。"
    "若最新记录同时含用户明示 A/B/C 和角色把它答成旧 A/旧赌注的错答，用户问当前 A/B/C 时只答用户明示事实；"
    "角色错误复述只能作为错误背景，不要主动写进答案，除非用户问角色刚才答错了什么。"
    "不得用相似旧赌约或泛化说法替换成记录里没有的晚餐、短诗、合理要求、一个要求等内容。"
)

_MINIGAME_CONTEXT_ENTRY_RE = re.compile(r"(中国象棋|棋局互动事实|最近棋局对话|棋盘老师|赌注.?[BC]|升级为.?C)")


def _soften_recent_assistant_raw_text(text: str) -> str:
    """避免将近期 assistant 对照句式回喂为风格样例。"""
    if not isinstance(text, str) or ("不是" not in text and "而是" not in text):
        return text

    def _replace(match: re.Match) -> str:
        prefix = (match.group("prefix") or "").strip()
        pos = (match.group("pos") or "").strip()
        if not pos:
            return match.group(0)
        return f"{prefix}{pos}" if prefix else pos

    return _ASSISTANT_RAW_CONTRAST_RE.sub(_replace, text)


def _latest_minigame_context_entry(entries: Any) -> str:
    if not isinstance(entries, list):
        return ""
    for ent in reversed(entries):
        if isinstance(ent, dict):
            summary = str(ent.get("summary") or "").strip()
            turn = ent.get("turn")
            prefix = f"第{turn}轮：" if turn is not None else ""
            text = prefix + summary
        elif isinstance(ent, str):
            text = ent.strip()
        else:
            continue
        if text and _MINIGAME_CONTEXT_ENTRY_RE.search(text):
            return text[:2600]
    return ""

_pending_ctx_tasks: dict[str, asyncio.Task] = {}
_ctx_locks: dict[str, asyncio.Lock] = {}


def _session_key(username: str, character_id: str, conversation_id: str) -> str:
    return f"{username}\x00{character_id}\x00{conversation_id}"


def _get_lock(key: str) -> asyncio.Lock:
    if key not in _ctx_locks:
        _ctx_locks[key] = asyncio.Lock()
    return _ctx_locks[key]


def _now_shanghai() -> datetime:
    """返回当前上海时区的 datetime（供记忆分段默认基准）。"""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(tz=ZoneInfo(CTX_ENTRY_DISPLAY_TZ))
    except Exception:
        return datetime.now()


def _tod_label(hour: int) -> str:
    """将小时数映射为中文时段名。"""
    if hour < 6:
        return "凌晨"
    if hour < 12:
        return "上午"
    if hour < 14:
        return "中午"
    if hour < 18:
        return "下午"
    if hour < 22:
        return "晚上"
    return "深夜"


def _entry_segment_key(at_ms: int | float, now_dt: datetime) -> tuple[int, str]:
    """
    返回 (days_ago, 'YYYY-MM-DD') 作为分组 key。
    days_ago=0 → 今天，1 → 昨天，以此类推。
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(CTX_ENTRY_DISPLAY_TZ)
        entry_dt = datetime.fromtimestamp(float(at_ms) / 1000.0, tz=tz)
        now_local = now_dt.astimezone(tz)
        delta = (now_local.date() - entry_dt.date()).days
        return delta, entry_dt.strftime("%Y-%m-%d")
    except Exception:
        return -1, ""


def _segment_header(days_ago: int, date_str: str, entry_tod: str, now_dt: datetime) -> str:
    """
    生成注入到 prompt 的时间分段标题。

    例：
      ── 昨天晚上（2026-05-11）──
      ── 今天上午（2026-05-12）──
      ── 3天前（2026-05-09）──
    """
    if days_ago < 0 or not date_str:
        return ""
    try:
        from zoneinfo import ZoneInfo
        now_local = now_dt.astimezone(ZoneInfo(CTX_ENTRY_DISPLAY_TZ))
        now_tod = _tod_label(now_local.hour)
    except Exception:
        now_tod = ""

    if days_ago == 0:
        label = f"今天{entry_tod}（{date_str}"
        if entry_tod != now_tod and now_tod:
            label += f"，当前{now_tod}"
        label += "）"
    elif days_ago == 1:
        label = f"昨天{entry_tod}（{date_str}）"
    elif days_ago == 2:
        label = f"前天{entry_tod}（{date_str}）"
    else:
        label = f"{days_ago}天前{entry_tod}（{date_str}）"
    return f"── {label} ──"


def _format_entry_timestamp_for_prompt(at_ms: int | float | None) -> str:
    """将本条记忆对应时刻（epoch 毫秒）格式化为可读的墙钟时间，供注入提示使用。"""
    if at_ms is None:
        return ""
    try:
        v = float(at_ms)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    try:
        from zoneinfo import ZoneInfo

        dt = datetime.fromtimestamp(v / 1000.0, tz=ZoneInfo(CTX_ENTRY_DISPLAY_TZ))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _format_ctx_entry_line(turn: int, summary: str, at_ms: int | float | None) -> str:
    ts = _format_entry_timestamp_for_prompt(at_ms)
    s = (summary or "").strip()
    if not s:
        return ""
    if ts:
        return f"· 第{turn}轮，{ts}：{s}"
    return f"· 第{turn}轮：{s}"


# ── 数据库操作 ─────────────────────────────────────────────────────────────────

async def load_context_memory(
    username: str,
    character_id: str,
    conversation_id: str,
    db,
) -> dict | None:
    """从 normal_chat_memory 表加载记忆，返回 dict 或 None（无记录时）。"""
    conn = await db.acquire()
    try:
        cursor = await conn.execute(
            """SELECT char_memory_json, short_term_memory, long_term_memory,
                      entries_covered_count, lt_covered_count, updated_at
               FROM normal_chat_memory
               WHERE username=? AND character_id=? AND conversation_id=?""",
            (username, character_id, conversation_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        entries_raw, short_term, long_term, entries_covered, lt_covered, updated_at = row
        try:
            entries = json.loads(entries_raw or "[]")
            if not isinstance(entries, list):
                entries = []
        except Exception:
            entries = []
        return {
            "entries": entries,
            "short_term_memory": short_term or "",
            "long_term_memory": long_term or "",
            "entries_covered_count": entries_covered or 0,
            "lt_covered_count": lt_covered or 0,
            "updated_at": updated_at or 0,
        }
    except Exception as e:
        logger.warning("[CtxMemory] 加载记忆失败: %s", e)
        return None
    finally:
        await db.release(conn)


async def _save_context_memory(
    username: str,
    character_id: str,
    conversation_id: str,
    memory: dict,
    db,
) -> bool:
    """将记忆状态写回数据库（INSERT OR REPLACE）。"""
    conn = await db.acquire()
    try:
        entries_json = json.dumps(memory.get("entries", []), ensure_ascii=False)
        await conn.execute(
            """INSERT OR REPLACE INTO normal_chat_memory
                   (username, character_id, conversation_id, char_memory_json,
                    short_term_memory, long_term_memory, entries_covered_count,
                    lt_covered_count, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                username,
                character_id,
                conversation_id,
                entries_json,
                memory.get("short_term_memory", ""),
                memory.get("long_term_memory", ""),
                memory.get("entries_covered_count", 0),
                memory.get("lt_covered_count", 0),
                int(time.time()),
            ),
        )
        await conn.commit()
        return True
    except Exception as e:
        logger.warning("[CtxMemory] 保存记忆失败: %s", e)
        return False
    finally:
        await db.release(conn)


# ── 格式化与注入 ───────────────────────────────────────────────────────────────

def format_context_memory_for_prompt(
    memory_dict: dict,
    now_dt: datetime | None = None,
    recent_raw_turns: list[tuple[str, str]] | None = None,
    user_label: str = "用户",
    assistant_label: str = "角色",
) -> str:
    """格式化记忆为可注入 system prompt 的字符串。

    格式：
    【上下文记忆】
    （首行读者纪律：勿复述/模仿记录措辞）

    [中期记忆]
    ...

    [短期记忆]
    ...

    [近期对话（中性记录）]
    ── 昨天晚上（2026-05-11）──
    · 第N轮，YYYY-MM-DD HH:MM：...
    ── 今天上午（2026-05-12，当前中午）──
    · 第M轮，YYYY-MM-DD HH:MM：...

    [最近真实对话（原文）]
    ...（若提供 recent_raw_turns，在末尾附上近期完整原文）

    当 now_dt 为 None 时自动取服务端当前上海时间。
    recent_raw_turns 为 [(role, content), ...] 格式，role 为 "user"/"assistant"。
    """
    if now_dt is None:
        now_dt = _now_shanghai()

    blocks: list[str] = []
    entries = memory_dict.get("entries") or []

    latest_minigame = _latest_minigame_context_entry(entries)
    if latest_minigame:
        blocks.append(
            "[刚结束/最近小游戏对局记忆（最高优先级）]\n"
            "以下是本上下文记忆中最靠后的小游戏/棋局记录；用户问刚刚结束、刚退出、这局、A/B/C、赌注、兑现、胜负时先用这一条。"
            "若它与后面旧记录冲突，以此条为准，旧记录只能作背景。\n"
            f"{latest_minigame}"
        )

    lt = str(memory_dict.get("long_term_memory") or "").strip()
    if lt:
        blocks.append(f"[中期记忆]\n{lt}")

    st = str(memory_dict.get("short_term_memory") or "").strip()
    if st:
        blocks.append(f"[短期记忆]\n{st}")

    if isinstance(entries, list) and entries:
        lines = ["[近期对话（中性记录）]"]
        last_segment_key: tuple[int, str] | None = None

        for i, ent in enumerate(entries, 1):
            if isinstance(ent, dict):
                summary = str(ent.get("summary") or "").strip()
                turn = int(ent.get("turn", i) or i)
                at_m = ent.get("at_ms")
                if not summary:
                    continue

                # 分段标题：当 at_ms 存在时，按日期分组并插入日期标题
                if at_m is not None:
                    try:
                        seg_key = _entry_segment_key(float(at_m), now_dt)
                        if seg_key != last_segment_key and seg_key[1]:
                            days_ago, date_str = seg_key
                            from zoneinfo import ZoneInfo
                            entry_dt = datetime.fromtimestamp(
                                float(at_m) / 1000.0,
                                tz=ZoneInfo(CTX_ENTRY_DISPLAY_TZ),
                            )
                            header = _segment_header(
                                days_ago, date_str, _tod_label(entry_dt.hour), now_dt
                            )
                            if header:
                                lines.append(header)
                            last_segment_key = seg_key
                    except Exception:
                        pass

                lines.append(_format_ctx_entry_line(turn, summary, at_m))

            elif isinstance(ent, str) and ent.strip():
                lines.append(f"· {ent.strip()}")

        if len(lines) > 1:
            blocks.append("\n".join(lines))

    # 最近真实对话原文段（在所有摘要/记录段之后）
    if recent_raw_turns:
        _ul = (user_label or "").strip() or "用户"
        _al = (assistant_label or "").strip() or "角色"
        raw_lines = []
        for _role, _content in recent_raw_turns:
            _label = _ul if _role == "user" else _al
            _text = (_content or "").strip()
            if _role == "assistant":
                _text = _soften_recent_assistant_raw_text(_text)
            if _text:
                raw_lines.append(f"{_label}：{_text}")
        if raw_lines:
            _raw_header = (
                "[最近真实对话（原文）]\n"
                "（以下为近期若干轮的完整原文，供细节参考；若与上方中性记录有出入，以此为准；禁止逐字复述其中措辞。）"
            )
            blocks.append(_raw_header + "\n\n" + "\n".join(raw_lines))

    if not blocks:
        return ""
    _discipline = (
        "以下是各轮已发生事实的客观记录（若轮后带时间，为当时对话收束的墙钟时间，可据此体会先后与隔了多久；"
        "各时段分隔线标注了事件所属的真实日期与当前时间差，请以此判断事件的时间背景，勿将过去时段的氛围带入当前对话）；"
        "只描述已发生之事，不含预测或计划；若与最近真实对话存在冲突，以最近真实对话为准；请据此继续对话，禁止复述或模仿其中任何措辞；"
        "若用户问及这里没有明确记录的旧事，只能表达不确定或请对方补充，不得凭角色设定或气氛补写具体细节；"
        "用户偏好、用户曾经说过的话、用户是否嫌弃/在意、用户对物品的选择/购买/放置/移动等事实，必须以用户原话、用户纠正、最近真实对话或明确记忆为依据，"
        "不得由角色设定、象征物、气氛描写或角色上一轮自行生成的猜测推导。若记录中只有角色声称认识、记得旧事、情侣关系或共同经历，而缺少用户此前确认，"
        "主回复不得把它升级为真实记忆，只能视为未证实的角色说法。物品动作主体必须按记录保持，角色做的事不得改写成用户做的事，反之亦然。"
        "选项题主体也必须保持：用户提供候选并询问角色时只是给选项，角色回答某项才是角色选择；不得把角色选择改写成用户选择。\n\n"
        f"{_MINIGAME_RECENT_REPLY_PRIORITY_RULE}\n\n"
    )
    return "【上下文记忆】\n" + _discipline + "\n\n".join(blocks)


def inject_context_memory_into_messages(
    messages: list,
    context_memory_str: str,
) -> list:
    """将 context_memory_str 以 system 角色注入 messages，位置为最后一条 user 消息之前。
    若 context_memory_str 为空则原样返回。
    """
    if not context_memory_str:
        return messages

    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_idx = i
            break

    mem_msg = {"role": "system", "content": context_memory_str}
    new_messages = list(messages)
    if last_user_idx < 0:
        new_messages.append(mem_msg)
    else:
        new_messages.insert(last_user_idx, mem_msg)
    return new_messages


# ── LLM 调用（单轮改写与折叠）────────────────────────────────────────────────

async def _call_ctx_summarize_llm(
    prompt: str,
    *,
    username: str = "",
    character_id: str = "",
    stage: str = "CTX_MEMORY",
    max_tokens: int = 16384,
) -> str | None:
    """调用 for_summarize 模型；失败时返回 None。max_tokens 依 stage 由调用方指定。"""
    from .. import config as app_config
    from ..config import model_manager
    from ..providers.llm_call import call_llm_payload
    from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
    from ..reasoning_policy import resolve_software_reasoning_policy
    from ..utils import save_chat_debug_log

    active_model = model_manager.get_model_for_task("summarize")
    if not active_model:
        logger.warning("[CtxMemory] 无 for_summarize 模型，跳过记忆更新")
        return None
    if not app_config.httpx_client:
        return None

    model_name = active_model.get("model_name") or active_model.get("id", "")
    reasoning_policy = resolve_software_reasoning_policy(
        "context_memory",
        model_name,
        active_model=active_model,
        endpoint=str(active_model.get("endpoint") or ""),
        mode="normal",
        requested_enabled=False,
        requested_effort="minimal",
    )
    body: dict[str, Any] = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    apply_llm_task_payload_config(body, "context_memory", output_token_field="max_tokens")
    if max_tokens != 16384:
        body["max_tokens"] = max_tokens
    timeout_sec = llm_task_float("context_memory", "timeout_seconds", 60.0) or 60.0

    try:
        result = await asyncio.wait_for(
            call_llm_payload(
                body,
                active_model,
                task="ctx_memory",
                httpx_client=app_config.httpx_client,
                timeout=timeout_sec,
                chat_debug_request={
                    "username": username or None,
                    "character_id": character_id or None,
                    "mode": "normal",
                    "model_name": model_name,
                    "stage": stage,
                },
                record_usage="main",
                usage_meter_username=username or None,
                reasoning_policy=reasoning_policy,
            ),
            timeout=timeout_sec,
        )
    except Exception as e:
        logger.warning("[CtxMemory] LLM 请求异常: %s", e)
        await save_chat_debug_log(
            username or None, character_id or None, "normal", model_name,
            {"error": str(e)}, stage=f"{stage}_RESP",
        )
        return None

    if isinstance(result.raw_response.get("error"), dict):
        logger.warning("[CtxMemory] LLM 返回错误对象: %s", result.raw_response["error"])
        await save_chat_debug_log(
            username or None, character_id or None, "normal", model_name,
            result.raw_response, stage=f"{stage}_RESP",
        )
        return None

    raw_content = (result.text or "").strip() or None
    if raw_content:
        raw_content = re.sub(r"[（(][^）)]*[）)]", "", raw_content).strip() or None

    await save_chat_debug_log(
        username or None, character_id or None, "normal", model_name,
        raw_content or "", stage=f"{stage}_RESP",
    )
    return raw_content


def _split_window_to_prefix_and_focus(
    window: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """本回合收束＝紧挨最后一条助理回复之前的连续 user 与最后一条 assistant。之前为仅参考。"""
    if not window:
        return [], []
    if window[-1][0] != "assistant":
        return [], list(window)
    last_a = len(window) - 1
    i = last_a - 1
    while i >= 0 and window[i][0] == "user":
        i -= 1
    focus_start = i + 1
    return list(window[:focus_start]), list(window[focus_start:])


def _format_ctx_bubble_lines(
    w: list[tuple[str, str]], _ul: str, _al: str
) -> str:
    if not w:
        return ""
    return "\n".join(
        f"{_ul if r == 'user' else _al}：{t}" for r, t in w
    )


def build_ctx_entry_bubbles_for_rewrite(
    messages: list[Any],
    *,
    new_assistant_content: str,
    user_label: str,
    assistant_label: str,
    recent_user_turns: int = CTX_ENTRY_RECENT_USER_TURNS,
    max_total_chars: int = CTX_ENTRY_RECENT_BLOCK_MAX_CHARS,
) -> tuple[str, str]:
    """返回 (仅参考区、须改写区) 两段已带标题的文本；无有效窗口则 ("", "")。"""
    _ul = (user_label or "").strip() or "用户"
    _al = (assistant_label or "").strip() or "助手"
    rows: list[tuple[str, str]] = []

    for m in messages or []:
        if getattr(m, "isHidden", None):
            continue
        r = (getattr(m, "role", None) or "").strip().lower()
        if r not in ("user", "assistant"):
            continue
        text = getattr(m, "content", None)
        if not isinstance(text, str):
            text = str(text) if text is not None else ""
        im = getattr(m, "image_url", None) or getattr(m, "images", None)
        if (not text.strip()) and im:
            line = "[图片/附件]"
        else:
            line = (text or "").strip()
        if not line and im:
            line = "[图片/附件]"
        if not line:
            continue
        line = line[:CTX_ENTRY_RECENT_BUBBLE_LINE_MAX]
        rows.append((r, line))

    nac = (new_assistant_content or "").strip()[:CTX_ENTRY_RECENT_BUBBLE_LINE_MAX] or "（空回复）"
    if rows and rows[-1][0] == "assistant":
        rows[-1] = ("assistant", nac)
    else:
        rows.append(("assistant", nac))

    user_idx = [i for i, (r, _) in enumerate(rows) if r == "user"]
    if not user_idx:
        return "", ""
    start = user_idx[-recent_user_turns] if len(user_idx) > recent_user_turns else 0
    window = list(rows[start:])

    prefix_w, focus_w = _split_window_to_prefix_and_focus(window)
    if not focus_w:
        return "", ""

    REF = (
        "【上文，仅作指代/话题衔接参考；**禁止**在你输出的正文中叙述、概括、复述本段内容】\n"
    )
    FOC = (
        "【本条须改写：**只**根据以下对话写**一条**第三人称事实；同侧连发可合并为一句，不必逐条拆开】\n"
    )

    def pack(pref: list[tuple[str, str]], foc: list[tuple[str, str]]) -> tuple[str, str]:
        r_txt = (REF + _format_ctx_bubble_lines(pref, _ul, _al)) if pref else ""
        f_txt = FOC + _format_ctx_bubble_lines(foc, _ul, _al)
        return (r_txt.strip(), f_txt.strip())

    p_w, f_w = prefix_w, focus_w
    ref_block, focus_block = pack(p_w, f_w)
    while len(ref_block) + len(focus_block) > max_total_chars and len(p_w) > 0:
        p_w.pop(0)
        ref_block, focus_block = pack(p_w, f_w)
    return (ref_block, focus_block)


async def _generate_entry_summary(
    user_message: str,
    assistant_message: str,
    turn: int,
    *,
    username: str = "",
    character_id: str = "",
    user_label: str = "用户",
    assistant_label: str = "助手",
    recent_reference_block: str | None = None,
    recent_focus_block: str | None = None,
    planner_memory_notes: str = "",
    stage: str = "CTX_ENTRY_SUMMARY",
) -> str | None:
    """将单轮对话改写为客观、中性的第三人称事实记录，保留全部关键信息与细节，剥离文风。"""
    _ul = (user_label or "").strip() or "用户"
    _al = (assistant_label or "").strip() or "助手"
    _user_name_hint = (
        f"记录中须用「{_ul}」指代用户侧，勿使用「用户」一词；"
        if _ul != "用户"
        else ""
    )
    _asst_name_hint = (
        f"记录中须用「{_al}」指代角色侧，勿使用「助手」一词；"
        if _al != "助手"
        else ""
    )
    # 无分栏时：仅两条发言
    _referent_rule = (
        f"【指称】以下两句为本回合两位发言者：「{_ul}」（用户侧）与「{_al}」（角色侧）。"
        f"凡明确在指**这两位之一**时，须用全名「{_ul}」或「{_al}」，避免在可判为二者时仅用「某人、对方、他/她」等偷懒。"
        "若原文另有**第三方**（非上述二人），据实写姓名、身份、关系，或保留合理的中性说法；"
        "**勿**把真第三方与「"
        f"{_ul}」「{_al}」弄混、亦勿将二者中某一方的行为误记到第三方头上。"
    )
    # 有「仅参考 / 须改写」分栏时
    _referent_rule_paired = (
        f"【指称】「本条须改写」区内的用户侧为「{_ul}」、角色侧为「{_al}」。"
        f"凡明确在指**这两位之一**时，须用全名「{_ul}」或「{_al}」，避免在可判为二者时仅用「某人、对方、他/她」等偷懒。"
        "若原文另有**第三方**（非上述二人），据实写姓名、身份、关系，或保留合理的中性说法；"
        f"**勿**把真第三方与「{_ul}」「{_al}」弄混、亦勿将二者中某一方的行为误记到第三方头上。"
    )
    _evidence_rule = (
        "【用户事实证据】用户偏好、用户曾说过的话、用户是否嫌弃/在意、用户选择/购买/准备/放置/移动某物，"
        "只有在用户原话、用户当前纠正、或本条须改写中的明确事实支持时才可写入。"
        "角色设定、象征物、氛围描写、角色自己的推测、角色上一轮自行生成内容，均不得整理成用户偏好或用户动作。"
        "若角色声称认识用户、记得旧事、双方是情侣/恋人/朋友、用户曾说过某句话或发生过共同经历，"
        "但这些内容只来自角色本轮或上一轮自行生成，且用户在此前没有明确确认或提供事实来源，"
        "不得改写成已证实的关系或共同记忆；只能写成角色单方面声称或角色试图以未证实的旧事唤起用户记忆。"
        "用户被角色说法带着继续扮演、沉默、惊讶、表示可能失忆或询问后续，不等于确认这些旧事为真。"
        "旧记忆细节问答必须保持为问答元记录：用户问“上次/那次在哪里、用了什么、有没有、谁做的、第一次吗”只是在提出待核对槽位；"
        "角色随后回答或回忆 X，只能整理为角色回答/声称/回忆为 X，不能改写成 X 确实发生。"
        "若导演事实边界给出已核验事实，可以注明角色的回答与该事实一致或冲突，但不能把本轮角色回答本身当成事实来源。"
        "物品动作主体必须严格保持：角色做的事写角色，用户做的事写用户；证据不足时省略。"
        "当前随身物品、昨天/今早刚做好的食物、刚买好的礼物、已经完成的准备，必须有用户原话、当前事实锚、导演确认或本条须改写中的明确支持；"
        "角色偏好、职业习惯、旧记忆、过去承诺、表达调度或角色自己临时提出“我带/我准备/我有”时，若缺少当前证据，只能写成角色提出计划、打算或想法，不得整理成角色已经持有或已经刚刚完成。"
        "不得用“新烤的/新做的/昨天多做了/早上烤好了/已经放包里”等方式绕过证据不足。"
        "若【导演确认的当前事实/用户纠错】标明某物无证据当前持有、不能写成刚完成或存在行动顺序冲突，摘要必须遵守该边界，即使角色正文里用了更肯定的说法，也要降级为角色想带/打算准备/提议，或直接省略该物品当前状态。"
        "发言主体必须严格保持：角色自己说出的信息、经历、背景、原因或解释，不能改写成用户告诉/告知/分享给角色；"
        "用户只是倾听、碰杯、点头或回应时，应写用户倾听、回应或表示理解，不得写用户告知该事实。"
        "第一人称归属必须保持：user 消息中的“我/我的/我把/我不小心”指用户，assistant 消息中的“我/我的”指当时发言角色；"
        "用户后来询问“你的心理活动”不改变此前 user 消息中的动作主体。"
        "选项归属必须保持：用户问角色“你想 A 还是 B/要选哪个”只是提供候选，assistant/角色随后回答某个选项才表示角色选择、偏好或接受；"
        "不得改写成用户选择、用户决定或用户让角色这样。只有用户明确说“我选X/我决定X/就X/我要X/我让你X”时，才可写成用户选择。"
        "次数描述必须保持原文证据：只有输入文本、上文参考或已有记忆明确出现“第一次/首次/初次/头一次/第N次”等次数说法时，才能在事实记录中保留对应次数。"
        "不得因为某事在本轮、本批记录或当前摘要中第一次出现，就主动写成第一次发生、首次确认、初次尝试或第几次；证据不足时只写成发生过、确认了、本次、当天或一次。"
        "临时群聊发言标记必须保持：若 assistant 文本开头含有“【临时群聊发言｜实际发言者=A｜主聊天角色=B】”或同义标记，"
        "则本条实际说话/行动主体是 A，不是 B，也不是 assistant_label；为 B 更新上下文时，只能写 B 在自己的主聊天现场看见/听见 A 的临时发言，"
        "不得写成 B 临时发言、B 做了 A 的动作，或 B 说出了 A 的台词。"
        "第三方证言与指控必须降级：若某人责备、推测、辩解、嫁祸或安慰性归因称某角色做了某事，"
        "而本条须改写或上文事实并未明确支持该角色确实做了该动作，只能写成某人如此指责/认为/安慰/替其辩解，"
        "不要改写成该角色实际做过或亲口承认过。若已有明确事实主体与后续指控冲突，必须保留明确事实主体。"
        "被指角色在压力下道歉、说会补救、低头、沉默、难过、点头或没有立刻反驳，不等于事实承认；"
        "这种误会里，角色会用自己的方式处理，一般不会承认自己没有做过的事；除非该角色明确说“是我做的/我亲手弄坏的”且不与更早明确事实冲突，否则不要写成该角色承认实施了动作。"
        "称呼方向也必须严格保持：用户说“叫我X/以后叫我X/你可以叫我X”，只能改写为用户请求角色称呼用户为 X，"
        "不得写成用户称呼角色为 X；只有用户说“我叫你X/以后我叫你X”时，才可写成用户称呼角色为 X。"
    )
    _temporal_rule = (
        "【时间状态守恒】必须区分“已发生事实”和“计划/约定/预告/明天或第二天才会发生的事”。"
        "若本条须改写只说“明天要做/今晚打算/等会儿去/派对还没开始/准备去”，只能写成未完成计划，"
        "不得改写成已经到达、已经结束、已经喝酒、已经回家、已经过夜或第二天之后的结果。"
        "“等会儿带/到时带/我想带/我去拿/我去买/如果来得及准备”只能写成计划；"
        "“新烤的/新做的/昨天多做了/早上烤好了/刚烤好/还温着/已经放在包里”等物品状态若只来自角色自行发挥且导演边界未确认，不能固化为事实。"
        "只有当本条须改写中的用户或角色明确说出某活动已经发生、结束、回来、完成，才可记录为已发生。"
        "相对时间词必须锚定本条对话的墙钟日期，不得在合并时把同一天的“今晚”和次日的“今晚/第二天晚上”压成同一个夜晚。"
    )
    _uc = (user_message or "")[:ENTRY_REWRITE_INPUT_MAX_CHARS]
    _ac = (assistant_message or "")[:ENTRY_REWRITE_INPUT_MAX_CHARS]
    _planner_notes = (planner_memory_notes or "").strip()[:2000]
    _common_style = (
        "**信息零丢失**（时间顺序、谁说了什么、发生了什么、重要物品与细节、情绪与关系变化等须完整保留），"
        "同时彻底去除角色/用户特有的口癖、叠字、拟声、括号动作、剧本格式、语气与修辞，"
        "禁止照搬原话语气与句序；发言一律转为第三人称间接引语（用「X 表示/提出/请求/询问/承认/…」等陈述信息与意图，"
        "不可出现直接引号内的逐字台词）。\n"
        "若含多步或多地点，按时间顺序分步写清。禁止写未发生的计划/打算/接下来将……\n"
        "禁止输出任何括号（含全角）及括号内说明。"
        f"{_MINIGAME_MEMORY_PRESERVE_RULE}"
        f"{_referent_rule}\n"
        f"{_evidence_rule}\n"
        f"{_temporal_rule}\n"
        f"{_user_name_hint}{_asst_name_hint}\n\n"
    )
    _style_for_focus_only = (
        "对**「本条须改写」**中的对话，**信息零丢失**（时间顺序、谁说了什么、发生了什么、重要物品与细节、情绪与关系变化等须完整保留），"
        "同时彻底去除口癖、叠字、拟声、括号动作、剧本格式、语气与修辞，"
        "禁止照搬原话语气与句序；发言一律转为第三人称间接引语（用「X 表示/提出/请求/询问/承认/…」等陈述信息与意图，"
        "不可出现直接引号内的逐字台词）。\n"
        "若须改写内多步或多地点，按时间顺序分步写清。禁止写未发生的计划/打算/接下来将……\n"
        "禁止输出任何括号（含全角）及括号内说明。"
        f"{_MINIGAME_MEMORY_PRESERVE_RULE}"
        f"{_referent_rule_paired}\n"
        f"{_evidence_rule}\n"
        f"{_temporal_rule}\n"
        f"{_user_name_hint}{_asst_name_hint}\n"
    )
    if (recent_focus_block or "").strip():
        _ref = (recent_reference_block or "").strip()[:CTX_ENTRY_RECENT_BLOCK_MAX_CHARS]
        _foc = (recent_focus_block or "").strip()[:CTX_ENTRY_RECENT_BLOCK_MAX_CHARS]
        if _ref:
            _head = (
                "你是对话历史的**中性改写者**。你的**唯一**产出必须是**单段**客观、中性的第三人称事实，"
                "且**只**能依据「【本条须改写】」中的对话来生成正文。"
                "「【上文，仅作…参考】」中的内容**不得**在输出里以叙述、概括、续写方式展开；"
                "仅可在你脑中用于理解须改写里的代词、省略与话题，"
                "**严禁**单独复述上文已出现而须改写中**未重提**的独立情节；"
                "若须改写中明显承接上文，可用最少量词点明，勿展开过程。"
                "若「本条须改写」里的角色又询问了「上文」已经明确回答过的同一事实，"
                "不得把它整理成新的未解问题；应写成角色重复询问已知事实，并用最少量词保留上文答案，避免后续记忆误以为该事实仍未知。\n"
            )
        else:
            _head = (
                "你是对话历史的**中性改写者**。你的**唯一**产出必须是**单段**客观、中性的第三人称事实，"
                "**只**能依据「【本条须改写】」所框定的对话；全部改写规则仅对该段生效。\n"
            )
        parts: list[str] = [_head]
        if _ref:
            parts.append(_ref)
        if _planner_notes:
            parts.append(
                "【导演确认的当前事实/用户纠错】\n"
                "以下内容只用于本条事实改写中的指代、纠错和作废依据；若与旧记忆冲突，以这里为准，并明确保留纠错结论。\n"
                f"{_planner_notes}"
            )
        parts.append(_foc)
        parts.append(_style_for_focus_only)
        parts.append("请直接输出一段改写正文，不加标题或前缀。")
        prompt = "\n\n".join(parts)
    else:
        _planner_block = (
            "【导演确认的当前事实/用户纠错】\n"
            "若以下内容与旧记忆冲突，以这里为准，并明确保留纠错结论。\n"
            f"{_planner_notes}\n\n"
            if _planner_notes
            else ""
        )
        prompt = (
            "你是对话历史的**中性改写者**。将以下**一轮**对话改写为客观、中性的第三人称事实记录，"
            f"{_common_style}"
            f"{_planner_block}"
            f"{_ul}：{_uc}\n"
            f"{_al}：{_ac}\n\n"
            "请直接输出一段改写正文，不加标题或前缀。"
        )
    return await _call_ctx_summarize_llm(
        prompt,
        username=username,
        character_id=character_id,
        stage=stage,
        max_tokens=CTX_ENTRY_REWRITE_MAX_TOKENS,
    )


async def _llm_extend_short_term(
    prev_short: str,
    entries_block: str,
    *,
    username: str = "",
    character_id: str = "",
) -> str | None:
    prompt = (
        "你是对话记录整理助手。将「已有短期记忆」与「新增对话记录（中性）」合并为新的短期事实摘要。\n"
        "要求：客观中性；保留与近期对话直接相关的事实；禁止输出任何括号（含全角括号）及括号内说明；总字数不超过400字；"
        "提到用户时必须保留 {{USER}} 占位符原样输出，不得改写为 USER 或其他写法。"
        f"{_MINIGAME_MEMORY_PRESERVE_RULE}"
        "用户偏好、用户曾说过的话、用户是否嫌弃/在意、用户选择/购买/准备/放置/移动某物，必须有用户原话、用户纠正或明确对话事实支持；"
        "不得把角色设定、象征物、氛围描写或角色猜测整理成用户事实。若旧识、情侣、共同经历、用户曾说过的话只来自角色单方面声称且用户此前未确认，"
        "不得合并成真实关系记忆，只能保留为未证实的角色声称或直接省略。物品动作主体必须严格保持，证据不足则省略。"
        "若新增记录只是“用户询问旧事细节、角色回答/声称/回忆 X”，只能保留为问答发生过，不能把 X 合并成历史事件事实；"
        "只有同一记录明确标注 X 来自用户补充、用户纠正、此前直接事件记录或导演核验，才可沿用为事实。"
        "user 消息中的第一人称动作必须保留为用户动作，不得因后续心理描写请求倒改为角色动作。"
        "选项归属必须保持：用户提供 A/B 候选并询问角色时不等于用户选择；若新增记录显示角色回答某个选项，只能合并为角色选择/偏好/接受该选项，不能合并成 {{USER}} 选择或决定。"
        "其他角色或用户的责备、推测、辩解、嫁祸、安慰性归因或“某某已经知道错了”等，只能证明说话者当时这样说；"
        "没有明确事实支持时，不要合并成被指角色实际做过或承认过。被指角色道歉、沉默或说会补救，不等于事实承认；角色一般会用自己的方式处理误会，而不是承认没做过的事。"
        "次数描述必须保持原文证据：只有输入文本或已有记忆明确出现“第一次/首次/初次/头一次/第N次”等次数说法时，才能在摘要中保留对应次数。"
        "不得因为某事在本轮、本批记录或当前摘要中第一次出现，就主动写成第一次发生、首次确认、初次尝试或第几次；证据不足时只写成发生过、确认了、本次、当天或一次。"
        "称呼方向必须保持：“叫我X/以后叫我X/你可以叫我X”表示用户请求角色称呼用户为 X，不表示用户称呼角色为 X。\n\n"
        "时间状态必须保持：新增记录里仍是计划、约定、预告、明天/第二天才会发生的事，不得在短期摘要里写成已经发生或已经结束；"
        "只有记录明确说已经发生/完成/结束/回来，才可归纳为已发生。涉及“今天/今晚/明天/第二天”的内容必须保留相对日期差异，"
        "不得把前一晚的屋顶活动和次日晚上的派对结算混成同一个当前夜晚。\n\n"
        f"【已有短期记忆】\n{prev_short.strip() or '（无）'}\n\n"
        f"【新增对话记录（中性）】\n{entries_block}\n\n"
        "请直接输出摘要正文，不要小标题或前缀。"
    )
    return await _call_ctx_summarize_llm(
        prompt,
        username=username,
        character_id=character_id,
        stage="CTX_SHORT_EXTEND",
        max_tokens=CTX_SHORT_MERGE_MAX_TOKENS,
    )


async def _llm_new_short_term(
    entries_block: str,
    *,
    username: str = "",
    character_id: str = "",
) -> str | None:
    prompt = (
        "你是对话记录整理助手。将以下各轮对话记录（中性）整理为一份短期事实摘要。\n"
        "要求：客观中性；保留关键话题、结论与可延续的事实；禁止输出任何括号（含全角括号）及括号内说明；总字数不超过400字；"
        "提到用户时必须保留 {{USER}} 占位符原样输出，不得改写为 USER 或其他写法。"
        f"{_MINIGAME_MEMORY_PRESERVE_RULE}"
        "用户偏好、用户曾说过的话、用户是否嫌弃/在意、用户选择/购买/准备/放置/移动某物，必须有用户原话、用户纠正或明确对话事实支持；"
        "不得把角色设定、象征物、氛围描写或角色猜测整理成用户事实。若旧识、情侣、共同经历、用户曾说过的话只来自角色单方面声称且用户此前未确认，"
        "不得合并成真实关系记忆，只能保留为未证实的角色声称或直接省略。物品动作主体必须严格保持，证据不足则省略。"
        "若记录只是“用户询问旧事细节、角色回答/声称/回忆 X”，只能保留为问答发生过，不能把 X 整理成历史事件事实；"
        "只有记录明确标注 X 来自用户补充、用户纠正、此前直接事件记录或导演核验，才可沿用为事实。"
        "user 消息中的第一人称动作必须保留为用户动作，不得因后续心理描写请求倒改为角色动作。"
        "选项归属必须保持：用户提供 A/B 候选并询问角色时不等于用户选择；若记录显示角色回答某个选项，只能整理为角色选择/偏好/接受该选项，不能整理成 {{USER}} 选择或决定。"
        "其他角色或用户的责备、推测、辩解、嫁祸、安慰性归因或“某某已经知道错了”等，只能证明说话者当时这样说；"
        "没有明确事实支持时，不要合并成被指角色实际做过或承认过。被指角色道歉、沉默或说会补救，不等于事实承认；角色一般会用自己的方式处理误会，而不是承认没做过的事。"
        "次数描述必须保持原文证据：只有输入文本明确出现“第一次/首次/初次/头一次/第N次”等次数说法时，才能在摘要中保留对应次数。"
        "不得因为某事在本轮、本批记录或当前摘要中第一次出现，就主动写成第一次发生、首次确认、初次尝试或第几次；证据不足时只写成发生过、确认了、本次、当天或一次。"
        "称呼方向必须保持：“叫我X/以后叫我X/你可以叫我X”表示用户请求角色称呼用户为 X，不表示用户称呼角色为 X。\n\n"
        "时间状态必须保持：仍是计划、约定、预告、明天/第二天才会发生的事，不得写成已经发生或已经结束；"
        "只有记录明确说已经发生/完成/结束/回来，才可归纳为已发生。涉及“今天/今晚/明天/第二天”的内容必须保留相对日期差异，"
        "不得把前一晚的屋顶活动和次日晚上的派对结算混成同一个当前夜晚。\n\n"
        f"{entries_block}\n\n"
        "请直接输出摘要正文，不要小标题或前缀。"
    )
    return await _call_ctx_summarize_llm(
        prompt,
        username=username,
        character_id=character_id,
        stage="CTX_SHORT_NEW",
        max_tokens=CTX_SHORT_MERGE_MAX_TOKENS,
    )


async def _llm_merge_long_term(
    prev_long: str,
    prev_short: str,
    *,
    username: str = "",
    character_id: str = "",
) -> str | None:
    prompt = (
        "你是对话记录整理助手。将「已有长期记忆」与「已有短期事实摘要」合并为新的长期事实摘要。\n"
        "要求：客观中性；保留关键话题、重要结论、持续性偏好与用户特征；"
        "禁止输出任何括号（含全角括号）及括号内说明；总字数必须不超过600字；"
        "目标长度约500字，允许在450至580字之间；若核心事实较少可以更短，但不要为了压缩删掉关键关系状态。"
        "输出6到8句，每句只写一到两个核心事实；不得按日期逐轮流水账。"
        "宁可舍弃细节也不得超长；若接近600字，继续删除低价值细节直到低于600字。"
        "只保留会影响后续对话的稳定事实、关系状态、重要时间节点、角色长期偏好与用户明确表达的持续性偏好。"
        "删除场景描写、身体感受、重复动作、临时姿势、环境细节、心理铺陈、逐轮编号、无后续价值的互动细节。"
        "提到用户时必须保留 {{USER}} 占位符原样输出，不得改写为 USER 或其他写法。"
        f"{_MINIGAME_MEMORY_PRESERVE_RULE}"
        "持续性偏好与用户特征只能来自用户原话、用户纠正或明确记忆，不能由角色设定、象征物、氛围描写或助手猜测推导；"
        "旧识、情侣、共同经历、用户曾说过的话若只来自角色单方面声称或模型自行补写，不能写入长期记忆；"
        "短期摘要中的问答元记录，例如“用户询问上次细节，角色回答/回忆 X”，不能合并成 X 确实发生；"
        "只有摘要明确标注 X 来自用户陈述、用户纠正、此前直接事件记录或导演核验，才可作为旧事事实保留。"
        "涉及物品选择、购买、准备、放置、移动时必须保持原动作主体，证据不足则不写入长期记忆；"
        "涉及选项题时必须保持选择主体：用户问角色“你想 A 还是 B/要选哪个”只是提供候选，角色回答某项才是角色选择，不能写成 {{USER}} 选择或决定；"
        "次数描述必须保持原文证据：只有已有长期记忆或已有短期事实摘要明确出现“第一次/首次/初次/头一次/第N次”等次数说法时，才能在新的长期摘要中保留对应次数。"
        "不得因为某事在短期摘要中刚出现、在长期记忆中刚合并或显得重要，就主动写成第一次发生、首次确认、初次尝试或第几次；证据不足时只写成发生过、确认了、本次、当天或一次。"
        "称呼方向必须保持，“叫我X”是请求角色称呼用户为 X，不是用户称呼角色为 X。\n\n"
        "时间状态必须保持：短期摘要里仍是计划、约定、预告、明天/第二天才会发生的事，不得在长期记忆里写成已经发生或已经结束；"
        "只有摘要明确说已经发生/完成/结束/回来，才可归纳为已发生。涉及“今天/今晚/明天/第二天”的内容必须保留相对日期差异，"
        "不得把前一晚的屋顶活动和次日晚上的派对结算混成同一个当前夜晚。\n\n"
        f"【已有长期记忆】\n{prev_long.strip() or '（无）'}\n\n"
        f"【已有短期事实摘要】\n{prev_short.strip() or '（无）'}\n\n"
        "请直接输出摘要正文，不要小标题或前缀。"
    )
    return await _call_ctx_summarize_llm(
        prompt,
        username=username,
        character_id=character_id,
        stage="CTX_LONG_MERGE",
        max_tokens=CTX_LONG_MERGE_MAX_TOKENS,
    )


def _format_entries_block(entries: list) -> str:
    lines: list[str] = []
    for i, ent in enumerate(entries, 1):
        if isinstance(ent, dict):
            summary = str(ent.get("summary") or "").strip()
            turn = int(ent.get("turn", i) or i)
            if summary:
                lines.append(
                    _format_ctx_entry_line(turn, summary, ent.get("at_ms")),
                )
        elif isinstance(ent, str) and ent.strip():
            lines.append(f"· {ent.strip()}")
    return "\n".join(lines)


# ── 核心更新逻辑 ───────────────────────────────────────────────────────────────

async def _run_context_memory_update(
    username: str,
    character_id: str,
    conversation_id: str,
    user_message: str,
    assistant_message: str,
    db,
    messages_for_bubbles: list[Any] | None = None,
    entry_at_ms: int | None = None,
    planner_memory_notes: str = "",
    stage_prefix: str = "CTX",
) -> None:
    """加载 → 追加 entry → 按需折叠 → 保存。"""
    from .character import load_character_from_db

    _char = load_character_from_db(username, character_id) or {}
    _char_name = str(_char.get("name") or "").strip()
    assistant_label = _char_name or "助手"
    user_label = USER_MEMORY_PLACEHOLDER
    recent_reference_block: str | None = None
    recent_focus_block: str | None = None
    if messages_for_bubbles is not None:
        _rr, _rf = build_ctx_entry_bubbles_for_rewrite(
            messages_for_bubbles,
            new_assistant_content=assistant_message,
            user_label=user_label,
            assistant_label=assistant_label,
        )
        if (_rf or "").strip():
            recent_reference_block = _rr.strip() or None
            recent_focus_block = _rf.strip()

    memory = await load_context_memory(username, character_id, conversation_id, db) or {
        "entries": [],
        "short_term_memory": "",
        "long_term_memory": "",
        "entries_covered_count": 0,
        "lt_covered_count": 0,
    }

    entries = list(memory.get("entries") or [])
    # turn 编号 = 已折叠条目数 + 当前 entries 数 + 1
    turn = (memory.get("entries_covered_count") or 0) + len(entries) + 1

    summary = await _generate_entry_summary(
        user_message, assistant_message, turn,
        username=username, character_id=character_id,
        user_label=user_label,
        assistant_label=assistant_label,
        recent_reference_block=recent_reference_block,
        recent_focus_block=recent_focus_block,
        planner_memory_notes=planner_memory_notes,
        stage=f"{stage_prefix}_CTX_ENTRY_SUMMARY",
    )
    if not summary:
        logger.warning("[CtxMemory] 单轮记忆改写失败，跳过本轮记忆写入")
        return
    summary = normalize_user_memory_text(summary, username=username)

    _at = int(entry_at_ms) if (entry_at_ms is not None and int(entry_at_ms) > 0) else int(time.time() * 1000)
    entries.append({"turn": turn, "summary": summary, "at_ms": _at})

    if len(entries) > KEEP_VERBATIM_MAX:
        to_summarize = entries[:-KEEP_VERBATIM_AFTER_TRIM]
        keep_entries = entries[-KEEP_VERBATIM_AFTER_TRIM:]
        entries_block = _format_entries_block(to_summarize)

        prev_short = str(memory.get("short_term_memory") or "").strip()
        prev_long = str(memory.get("long_term_memory") or "").strip()
        lt_covered = memory.get("lt_covered_count") or 0
        new_entries_covered = (memory.get("entries_covered_count") or 0) + len(to_summarize)

        # short_term 覆盖轮数溢出时，先将其并入 long_term
        if lt_covered + len(to_summarize) > SHORT_TERM_MAX_TURNS and prev_short:
            merged_long = await _llm_merge_long_term(
                prev_long, prev_short,
                username=username, character_id=character_id,
            )
            if not merged_long:
                logger.warning("[CtxMemory] 长期合并失败，保留完整 entries")
                memory["entries"] = entries
                await _save_context_memory(username, character_id, conversation_id, memory, db)
                return

            new_short = await _llm_new_short_term(
                entries_block,
                username=username, character_id=character_id,
            )
            if not new_short:
                logger.warning("[CtxMemory] 新短期生成失败，保留完整 entries")
                memory["entries"] = entries
                await _save_context_memory(username, character_id, conversation_id, memory, db)
                return

            memory["long_term_memory"] = merged_long.strip()
            memory["short_term_memory"] = new_short.strip()
            memory["lt_covered_count"] = new_entries_covered
        else:
            if prev_short:
                new_short = await _llm_extend_short_term(
                    prev_short, entries_block,
                    username=username, character_id=character_id,
                )
            else:
                new_short = await _llm_new_short_term(
                    entries_block,
                    username=username, character_id=character_id,
                )
            if not new_short:
                logger.warning("[CtxMemory] 短期事实摘要生成失败，保留完整 entries")
                memory["entries"] = entries
                await _save_context_memory(username, character_id, conversation_id, memory, db)
                return

            memory["short_term_memory"] = new_short.strip()
            memory["lt_covered_count"] = lt_covered + len(to_summarize)

        memory["entries"] = keep_entries
        memory["entries_covered_count"] = new_entries_covered
    else:
        memory["entries"] = entries

    ok = await _save_context_memory(username, character_id, conversation_id, memory, db)
    if ok:
        logger.info(
            "🧠 [CtxMemory] 已写入 %s 条 entries | user=%s char=%s conv=%s",
            len(memory["entries"]),
            username,
            (character_id or "")[:8],
            (conversation_id or "")[:8],
        )


def schedule_context_memory_update(
    username: str,
    character_id: str,
    conversation_id: str,
    user_message: str,
    assistant_message: str,
    db,
    llm_call_func=None,
    messages_for_bubbles: list[Any] | None = None,
    entry_at_ms: int | None = None,
    planner_memory_notes: str = "",
) -> None:
    """每轮对话成功保存后调用：链式排队，避免并发写库冲突。
    内部创建 asyncio.Task，不阻塞调用方。
    entry_at_ms：本回合收束的 epoch 毫秒，写入条目的 at_ms 并在【近期对话】中展示；默认当前时间。
    llm_call_func 参数保留以备扩展，当前未使用。
    """
    key = _session_key(username, character_id, conversation_id)
    old = _pending_ctx_tasks.get(key)

    async def _chain() -> None:
        if old and not old.done():
            try:
                await old
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        async with _get_lock(key):
            try:
                await _run_context_memory_update(
                    username, character_id, conversation_id,
                    user_message, assistant_message, db,
                    messages_for_bubbles=messages_for_bubbles,
                    entry_at_ms=entry_at_ms,
                    planner_memory_notes=planner_memory_notes,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "🧠 [CtxMemory] 更新失败 | user=%s char=%s err=%s",
                    username, (character_id or "")[:8], e,
                )

    _pending_ctx_tasks[key] = asyncio.create_task(_chain())
