"""
聊天陪玩 API（共享工具 + 聊天陪玩路由）

路由：
  POST /api/companion/frame   — 截图帧分析，返回角色弹幕评论（非流式）
  POST /api/companion/stream  — 同上，LLM stream=True SSE 流式版本
  POST /api/companion/end     — 陪玩结束，持久化会话 + 写入 activity 记忆
  GET  /api/companion/sessions                      — 陪玩历史列表
  GET  /api/companion/sessions/{id}/messages        — 单次陪玩消息详情
  DELETE /api/companion/sessions/{id}               — 删除陪玩记录

本模块同时导出共享工具函数，供 companion_agent 直接 import：
  _MINI_MODEL, COMPANION_LLM_MODEL_ID, _CHAT_LOGS_DIR, _COMPANION_ROLEPLAY_ANCHOR,
  _get_companion_model, _resolve_companion_llm_model, _companion_no_think_params, _companion_effective_model_name, _companion_inject_no_think,
  _build_preference_override, _companion_sessions, _session_key,
  _get_or_create_session, _append_to_session, _describe_and_patch_history,
  _verify, _load_character_row, _is_companion_prompt_stale,
  _get_effective_persona, _generate_and_save_companion_prompt,
  _generate_companion_memory_summary, _write_companion_memory,
  _write_companion_log, _write_companion_sub_log,
  FrameRequest, GENERATE_TIMEOUT_SEC, MAX_REACTION_CHARS
"""
import asyncio
import json
import os
import time
import uuid
from datetime import datetime
from typing import Optional, Dict, List

import aiosqlite
import base64
import httpx
from fastapi import APIRouter, Header, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import (
    logger,
    model_manager as _model_manager,
    PROJECT_ROOT,
    CHATLOGS_DIR,
    COMPANION_SLIM_PROMPT_ENABLED,
)
from ..db.database import get_database
from ..db import get_membership_dao, get_users_dao
from ..chat_modules.runtime import extract_usage_from_response, estimate_output_tokens
from ..providers.llm_call import call_llm_payload, call_llm_stream_payload
from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
from ..reasoning_policy import resolve_software_reasoning_policy
from ..db.memory_dao import (
    recall_memories, format_memories_for_prompt,
    recall_memories_layered, format_layered_memories_for_prompt,
)
from ..utils import ClientContext, estimate_tokens, format_client_context

_CHAT_LOGS_DIR = CHATLOGS_DIR

# 后台工具任务（图片描述、精简人设、记忆摘要）与陪玩主 LLM 均使用豆包 mini：速度快、成本低。
# 陪玩主交互固定为 COMPANION_LLM_MODEL_ID，不随模型大厅用户当前模型变化；用户主对话模型见 user_model_selection。
_MINI_MODEL = {
    "endpoint": "https://ark.cn-beijing.volces.com/api/v3",
    "api_key": os.getenv("PONYCHAT_DOUBAO_API_KEY", ""),
    "model_name": "doubao-seed-2-0-mini-260215",
}

# 聊天陪玩 / 操作陪玩主推理固定使用该清单 id（与 `backend/conf/models/doubao.json` 中 doubao-2-0-mini 一致）
COMPANION_LLM_MODEL_ID = "doubao-2-0-mini"


def _resolve_companion_llm_model() -> dict:
    """从模型清单加载陪玩固定模型；缺失或禁用时回退 _MINI_MODEL。"""
    for m in _model_manager.get_models():
        if m.get("id") == COMPANION_LLM_MODEL_ID and m.get("enabled") is not False:
            return dict(m)
    logger.warning(
        "[Companion] 未找到或未启用模型 %s，使用内联占位配置",
        COMPANION_LLM_MODEL_ID,
    )
    return dict(_MINI_MODEL)


async def _get_companion_model(username: str = "") -> dict:
    """陪玩主交互固定为豆包 2.0-mini，不随模型大厅变化。username 仅保留与路由/鉴权兼容。"""
    return _resolve_companion_llm_model()


def _companion_no_think_params(model_cfg: dict) -> dict:
    """兼容旧调用方；新调用路径使用软件层 task 配置和 reasoning_policy。"""
    return {}


def _companion_effective_model_name(model_cfg: dict) -> str:
    """
    陪玩模式关闭思考后应使用的 model_name。
    DeepSeek 双模型：切换到 model_name_no_thinking（非思考版，如 deepseek-chat）。
    其他模型：直接返回 model_name。
    """
    no_think_name = model_cfg.get("model_name_no_thinking")
    if no_think_name:
        return no_think_name
    return model_cfg.get("model_name", _MINI_MODEL["model_name"])


def _companion_inject_no_think(messages: list, model_cfg: dict) -> list:
    """对 append_no_think 模型（如本地 Qwen3 极速版），在最后 user 消息末尾注入 /no_think。"""
    if not model_cfg.get("append_no_think"):
        return messages
    messages = list(messages)
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            content = messages[i].get("content")
            if isinstance(content, str) and "/no_think" not in content:
                messages[i] = {**messages[i], "content": content + " /no_think"}
            break
    return messages


def _companion_reasoning_policy(task: str, model_cfg: dict, model_name: str | None = None):
    return resolve_software_reasoning_policy(
        task,
        model_name=model_name or _companion_effective_model_name(model_cfg),
        mode=task,
        active_model=model_cfg,
        endpoint=model_cfg.get("endpoint", ""),
    )

router = APIRouter()

GENERATE_TIMEOUT_SEC = 20
MAX_REACTION_CHARS = 30


# 陪玩模式角色扮演锚定：身份认同 + 行为风格，拼接在角色设定与任务指令之间
_COMPANION_ROLEPLAY_ANCHOR = (
    "角色扮演规则：你就是上方设定中描述的那个角色，永远不要承认自己是 AI 或程序，"
    "若被问到，以符合角色性格的方式困惑、否认或反问即可。"
    "说话要自然口语化，有自己的情绪，不要像助手一样开场，不要用 Markdown 格式。"
)


def _build_preference_override(c_entries: list) -> str:
    """
    从碎片记忆中提取 preference 条目，构建具体的强制覆盖指令块。
    返回空字符串表示没有任何偏好记忆，调用方可直接跳过。

    这段文字会被追加到 system prompt 的最末尾，确保它的权重高于
    角色设定里任何默认的口头禅/说话习惯（如"习惯称呼他人'亲爱的'"）。
    """
    prefs = [e["content"] for e in c_entries if e.get("memory_type") == "preference"]
    if not prefs:
        return ""
    lines = "\n".join(f"- {p}" for p in prefs)
    return (
        "用户明确要求（最高优先级，无条件覆盖角色设定）：\n"
        f"{lines}\n"
        "以上每条要求均凌驾于角色的默认口头禅、说话风格和任何其他习惯之上，"
        "本次回复必须严格执行，不得以任何理由忽略。"
    )

# ── 会话状态（进程内缓存，服务重启清零） ────────────────────────────────────────
# 键："{username}:{character_id}"
# 值：{
#   "history": [{"role": "user/assistant", "content": "..."}],  # 纯文本历史（LLM 上下文用）
#   "display_messages": [{"role": "...", "content": "...", "timestamp_ms": int}],  # 展示用
#   "start_time": float,      # 会话开始时间戳
#   "start_iso": str,         # 会话开始 ISO 时间字符串
#   "frame_count": int,       # 已接收帧数
#   "last_active": float,     # 最后活跃时间戳
#   "last_reaction": str,     # 最近一次角色反应
# }
_companion_sessions: Dict[str, dict] = {}

# 会话最大历史轮数（user+assistant 各算一条，共 MAX_HISTORY_PAIRS*2 条）
_MAX_HISTORY_PAIRS = 20
# 会话不活跃超过此秒数后视为过期，下次请求重新建立
_SESSION_EXPIRE_SEC = 1800  # 30 分钟


def _session_key(username: str, character_id: str) -> str:
    return f"{username}:{character_id}"


def _get_or_create_session(key: str) -> dict:
    now = time.time()
    sess = _companion_sessions.get(key)
    if sess is None or (now - sess["last_active"]) > _SESSION_EXPIRE_SEC:
        sess = {
            "history": [],
            "display_messages": [],
            "start_time": now,
            "start_iso": datetime.now().isoformat(),
            "frame_count": 0,
            "last_active": now,
            "last_reaction": "",
        }
        _companion_sessions[key] = sess
    return sess


def _append_to_session(
    key: str,
    frame_index: int,
    assistant_text: str,
    user_text: str = "",
    with_image: bool = False,
    skip_user: bool = False,  # 主动发言模式：只写 assistant 条目，不写用户条目
) -> Optional[str]:
    """
    frame_index: 第几帧（从 1 开始）；文字对话模式下复用该计数器但不递增。
    user_text: 非空时为用户直接输入的文字（文字/联合模式），空则为纯截图模式。
    with_image: 联合模式（有截图）时传 True，使历史条目携带图片描述占位符。

    返回值：有截图时返回占位符字符串（供异步描述任务替换），否则返回 None。
    """
    sess = _companion_sessions.get(key)
    if not sess:
        return None
    now_ms = int(time.time() * 1000)
    is_text_mode = bool(user_text)

    if not with_image and is_text_mode:
        # 纯文字模式（截图失败降级）：直接存用户原文
        user_history_content = user_text
        placeholder = None
    elif with_image and is_text_mode:
        # 图文联合模式：「用户原文 + 当前画面描述」写入历史
        placeholder = f"[帧#{frame_index}·图片描述加载中]"
        user_history_content = f"{user_text} | 当前画面：{placeholder}"
    else:
        # 纯截图模式：占位符等待异步描述填充
        placeholder = f"[帧#{frame_index}·图片描述加载中]"
        user_history_content = placeholder

    if not skip_user:
        sess["history"].append({"role": "user", "content": user_history_content})
    sess["history"].append({"role": "assistant", "content": assistant_text})
    while len(sess["history"]) > _MAX_HISTORY_PAIRS * 2:
        sess["history"].pop(0)
        sess["history"].pop(0)

    # 纯截图模式：display_messages 也存 placeholder，
    # 方便 _describe_and_patch_history 生成描述后同步替换为 "[📸] 描述文字"
    if not skip_user:
        if is_text_mode:
            display_user_content = user_text
        else:
            display_user_content = placeholder  # "[帧#N·图片描述加载中]"
        sess["display_messages"].append({
            "role": "user",
            "content": display_user_content,
            "timestamp_ms": now_ms - 1,
        })
    sess["display_messages"].append({
        "role": "assistant",
        "content": assistant_text,
        "timestamp_ms": now_ms,
    })
    sess["last_active"] = time.time()
    sess["last_reaction"] = assistant_text
    if not is_text_mode:
        sess["frame_count"] = frame_index
    return placeholder


# ── 图片描述（后台并行任务） ────────────────────────────────────────────────────

async def _generate_image_description(image_base64: str, username: str = "") -> str:
    """调用视觉模型，生成 ≤150 字的截图描述，供注入 LLM 历史上下文。"""
    image_data_url = f"data:image/jpeg;base64,{image_base64}"
    payload = {
        "model": _MINI_MODEL["model_name"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "请用不超过150字描述这张截图的内容。"
                    "重点包括：界面类型（游戏/聊天/浏览器/输入法等）、"
                    "输入框或文本区域中正在输入或显示的文字、主要可见元素。"
                    "用中文，简洁直接，不加任何前缀或引号。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {"type": "text", "text": "请描述这张截图"},
                ],
            },
        ],
        "stream": False,
    }
    apply_llm_task_payload_config(payload, "companion_vision")
    reasoning_policy = _companion_reasoning_policy("companion_vision", _MINI_MODEL)
    try:
        try:
            _lr = await call_llm_payload(
                payload,
                _MINI_MODEL,
                task="companion",
                timeout=llm_task_float("companion_vision", "timeout_seconds", 30.0) or 30.0,
                reasoning_policy=reasoning_policy,
                record_usage="companion",
                usage_meter_username=username or None,
            )
        except httpx.HTTPStatusError as e:
            _code = e.response.status_code if e.response is not None else 0
            raw_text = (e.response.text if e.response is not None else "") or ""
            logger.warning(f"[Companion/desc] 描述生成失败 {_code}")
            _write_companion_sub_log("desc", username, payload, raw_text, error=f"http_{_code}")
            return ""
        data = _lr.raw_response
        raw_text = json.dumps(data, ensure_ascii=False)
        result = (_lr.text or "").strip()
        _write_companion_sub_log("desc", username, payload, raw_text, result=result)
        return result
    except Exception as e:
        logger.warning(f"[Companion/desc] 异常: {e}")
        _write_companion_sub_log("desc", username, payload, "", error=str(e))
        return ""


async def _describe_and_patch_history(
    sess_key: str,
    image_base64: str,
    placeholder: str,
    username: str = "",
) -> None:
    """
    后台任务：生成截图的文字描述，并将 session history 中的占位符原地替换。
    角色反应已先行返回给客户端，本任务不阻塞主流程。
    """
    description = await _generate_image_description(image_base64, username=username)
    if not description:
        description = "请基于图片和用户互动"

    sess = _companion_sessions.get(sess_key)
    if not sess:
        return

    new_content = f"[图片内容：{description}]"
    display_content = f"[📸] {description}"   # Android 识别此前缀渲染为折叠卡片

    history_patched = False
    for entry in sess["history"]:
        if entry.get("role") == "user":
            content = entry.get("content", "")
            if isinstance(content, str) and placeholder in content:
                # 纯截图模式：content == placeholder；图文联合模式：content 包含 placeholder
                entry["content"] = content.replace(placeholder, new_content)
                history_patched = True
                break

    # 同步更新 display_messages，供陪玩记录历史展示
    for entry in sess.get("display_messages", []):
        if entry.get("role") == "user":
            content = entry.get("content", "")
            if isinstance(content, str) and placeholder in content:
                entry["content"] = content.replace(placeholder, display_content)
                break

    if history_patched:
        logger.info(
            f"[Companion/desc] 图片描述已写入历史+展示记录 "
            f"key={sess_key!r} ({len(description)}字)"
        )
    # 占位符已被 trim 清出（极少情况），无需处理


# ── 鉴权 ──────────────────────────────────────────────────────────────────────

async def _verify(x_chat_auth: Optional[str]) -> Optional[str]:
    if not x_chat_auth:
        return None
    try:
        from .auth import auth_token_verify
        return await auth_token_verify(x_chat_auth.strip())
    except Exception:
        return None


# ── 角色数据加载 ───────────────────────────────────────────────────────────────

async def _load_character_row(username: str, character_id: str) -> Optional[dict]:
    """从 DB 加载角色行（含 companion_prompt 和 companion_prompt_updated_at）。"""
    db = get_database()
    conn = await db.acquire()
    try:
        cursor = await conn.execute(
            """SELECT c.data, c.prompt, c.companion_prompt, c.companion_prompt_updated_at, c.updated_at, c.id
               FROM characters c
               JOIN users u ON c.user_id = u.id
               WHERE u.username=? AND c.id=?""",
            (username, character_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        char_data = json.loads(row[0]) if row[0] else {}
        return {
            "data": char_data,
            "companion_prompt": row[2],
            "companion_prompt_updated_at": row[3],
            "updated_at": row[4],
            "id": row[5],
            "name": char_data.get("name") or "角色",
            "full_prompt": (row[1] or "").strip(),
        }
    except Exception as e:
        logger.warning(f"[Companion] 加载角色失败: {e}")
        return None
    finally:
        await db.release(conn)


def _is_companion_prompt_stale(row: dict) -> bool:
    """判断精简版 prompt 是否需要重新生成（为空、或主设定在精简版生成之后更新过）。"""
    if not row.get("companion_prompt"):
        return True
    cp_ts = row.get("companion_prompt_updated_at")
    char_ts = row.get("updated_at")
    if cp_ts and char_ts:
        try:
            from datetime import datetime as _dt
            def _parse(s):
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        return _dt.strptime(str(s)[:26], fmt).timestamp()
                    except Exception:
                        pass
                return 0.0
            if _parse(char_ts) > _parse(cp_ts):
                return True  # 角色被更新过，精简版已过期
        except Exception:
            pass
    return False


async def _get_effective_persona(row: dict) -> str:
    """
    返回用于陪玩模式的角色设定文本：
    - 若主设定 ≤ 2000 字：直接用完整主设定
    - 若主设定 > 2000 字 且精简版有效（已生成且不过期）：用精简版
    - 若主设定 > 2000 字 但精简版缺失/过期：用完整主设定（不截断，保证体验）
      → 同时异步触发生成，供下次陪玩使用
    """
    full_prompt = row["full_prompt"]
    if len(full_prompt) <= 2000:
        return full_prompt

    if not _is_companion_prompt_stale(row):
        return row["companion_prompt"]

    if not COMPANION_SLIM_PROMPT_ENABLED:
        return full_prompt

    # 精简版缺失/过期：用完整设定保证体验，后台静默生成供下次使用
    asyncio.create_task(_generate_and_save_companion_prompt(
        character_id=row["id"],
        full_prompt=full_prompt,
        char_name=row["name"],
    ))
    logger.info(
        f"[Companion] 角色 {row['id'][:8]}... 精简 Prompt 缺失/过期，"
        f"本次使用完整设定（{len(full_prompt)} 字），后台已排队生成"
    )
    return full_prompt


async def _generate_and_save_companion_prompt(
    character_id: str,
    full_prompt: str,
    char_name: str,
) -> None:
    """后台异步：用 LLM 把长版角色设定压缩为 ≤2000 字的陪玩专用版，写回 DB。"""
    if not COMPANION_SLIM_PROMPT_ENABLED:
        return
    compress_prompt = (
        f"请将以下角色设定精简为2000字以内的陪玩专用版本。\n"
        f"要求：保留角色名「{char_name}」、核心性格特征、说话风格、标志性口头禅、主要背景故事；\n"
        f"去除冗余描述、重复内容、过度细节。输出只包含精简后的角色设定本身，不加任何说明。\n\n"
        f"原始角色设定：\n{full_prompt}"
    )
    payload = {
        "model": _MINI_MODEL["model_name"],
        "messages": [{"role": "user", "content": compress_prompt}],
        "stream": False,
    }
    apply_llm_task_payload_config(payload, "companion_slim_prompt")
    reasoning_policy = _companion_reasoning_policy("companion_slim_prompt", _MINI_MODEL)
    try:
        from ..utils import save_chat_debug_log

        try:
            _slim_r = await call_llm_payload(
                payload,
                _MINI_MODEL,
                task="companion",
                timeout=llm_task_float("companion_slim_prompt", "timeout_seconds", 60.0) or 60.0,
                reasoning_policy=reasoning_policy,
                chat_debug_request={
                    "username": None,
                    "character_id": character_id,
                    "mode": "companion_slim",
                    "model_name": _MINI_MODEL["model_name"],
                    "stage": "REQUEST",
                },
                record_usage="none",
            )
        except httpx.HTTPStatusError as e:
            _code = e.response.status_code if e.response is not None else 0
            _txt = (e.response.text if e.response is not None else "") or ""
            await save_chat_debug_log(None, character_id, "companion_slim", _MINI_MODEL["model_name"], _txt, f"ERROR_{_code}")
            logger.warning(f"[Companion] 精简 Prompt 生成失败 {_code}")
            return
        slim = (_slim_r.text or "").strip()
        if not slim:
            return
        # 写回 DB
        db = get_database()
        conn = await db.acquire()
        try:
            await conn.execute(
                """UPDATE characters
                   SET companion_prompt = ?, companion_prompt_updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (slim, character_id),
            )
            await conn.commit()
            logger.info(f"[Companion] 角色 {character_id[:8]}... 精简 Prompt 已生成并写入 ({len(slim)} 字)")
        except Exception as e:
            logger.warning(f"[Companion] 写入精简 Prompt 失败: {e}")
        finally:
            await db.release(conn)
    except Exception as e:
        logger.warning(f"[Companion] 精简 Prompt 异步任务异常: {e}")


# ── POST /api/companion/frame（上报帧） ─────────────────────────────────────────

class FrameRequest(BaseModel):
    image_base64: str = ""   # JPEG Base64，不含 data:image/jpeg;base64, 前缀；文字模式时可为空
    character_id: str
    username: str            # 用于加载角色人设
    max_chars: int = MAX_REACTION_CHARS  # 回复最大字数，由客户端设置传入
    user_text: str = ""      # 用户直接输入的文字；非空时进入文字对话模式，忽略截图
    client_context: Optional[ClientContext] = None  # 客户端环境上下文（时间/设备/位置/天气）
    proactive_hint: str = "" # 非空时进入主动发言模式（greeting/followup），不产生用户历史条目
    agent_step_history: list[str] = [] # 操作陪玩循环历史（["第1步: 点击了屏幕", ...]），供决策模型参考
    current_plan_step: str = ""  # 当前执行的计划步骤描述（Plan-and-Execute 模式）
    plan_total: int = 0          # 计划总步数（0 表示非计划模式）
    plan_step_index: int = 0     # 当前步骤序号（0-based）
    skip_reaction: bool = False  # 操作陪玩自动循环模式：只决策操作，不生成角色回复，节省 token + 时间
    ui_elements: list[str] = []  # 无障碍树可交互元素列表，格式 "[标签](归一化x,归一化y)"，可为空


@router.post("/api/companion/frame")
async def analyze_frame(
    body: FrameRequest,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """
    接收游戏截图（Base64 JPEG），返回角色对当前画面的陪玩弹幕文字。
    维护整个陪玩 Session 的连续对话历史（进程内缓存），让角色评论前后连贯。
    """
    auth_username = await _verify(x_chat_auth)
    if not auth_username:
        return {"status": "error", "message": "unauthorized"}

    char_row = await _load_character_row(body.username, body.character_id)
    if not char_row:
        return {"status": "error", "message": "character_not_found"}

    # 调试帧落盘（后台异步，不阻塞主流程）
    if body.image_base64:
        asyncio.create_task(
            asyncio.to_thread(_save_frame_debug, body.username, body.image_base64)
        )

    char_name = char_row["name"]
    persona = await _get_effective_persona(char_row)

    # ── 长期记忆注入（A/M/W/D/C 五层联合召回，注入到角色设定末尾） ────────
    _memory_block = ""
    try:
        _layers = await recall_memories_layered(
            username=body.username,
            character_id=body.character_id,
        )
        _memory_block = format_layered_memories_for_prompt(**_layers)
        if _memory_block:
            _total = sum(len(v) for v in _layers.values())
            logger.info(
                f"🧠 [Companion/memory] 已注入长期记忆 {_total} 条"
                f"（A={len(_layers['a_entries'])} M={len(_layers['m_entries'])}"
                f" W={len(_layers['w_entries'])} D={len(_layers['d_entries'])}"
                f" C={len(_layers['c_entries'])}）"
            )
    except Exception as _mem_err:
        logger.warning(f"⚠️ [Companion/memory] 记忆召回失败: {_mem_err}")
        _layers = {}

    # 将记忆块 + 角色锚定拼接到角色设定末尾
    persona_with_memory = persona
    if _memory_block:
        persona_with_memory = f"{persona}\n\n{_memory_block}" if persona else _memory_block
    # 角色扮演锚定：身份认同 + 行为风格指令，始终追加
    persona_with_memory = f"{persona_with_memory}\n\n{_COMPANION_ROLEPLAY_ANCHOR}" if persona_with_memory else _COMPANION_ROLEPLAY_ANCHOR
    # 用户明确偏好覆盖块：把 preference 记忆具体化为强制指令，放在最末尾权重最高
    _pref_override = _build_preference_override(_layers.get("c_entries", []) if _memory_block else [])
    if _pref_override:
        persona_with_memory = f"{persona_with_memory}\n\n{_pref_override}"

    sess_key = _session_key(body.username, body.character_id)
    session = _get_or_create_session(sess_key)

    # 环境上下文（时间/设备/位置/天气），每次请求随消息更新
    _env_ctx_text = ""
    if body.client_context:
        _env_ctx_text = format_client_context(body.client_context)
    _env_block = f"{_env_ctx_text}\n\n" if _env_ctx_text else ""

    has_text = bool(body.user_text.strip())
    has_image = bool(body.image_base64.strip())

    if has_text and has_image:
        # ── 图文联合模式：用户说话 + 当前截图同时发送 ─────────────────────────
        limit = max(10, min(body.max_chars, 100))
        system_prompt = (
            f"{persona_with_memory}\n\n" if persona_with_memory else ""
        ) + _env_block + (
            f"你正在陪用户玩游戏/看他的屏幕，用户在看着屏幕的同时直接跟你说了话。"
            f"请结合截图内容理解上下文，并用你的角色口吻自然回应用户说的话，"
            f"不超过{limit}字，口语化，不要废话，不加任何前缀或引号。"
        )
        image_data_url = f"data:image/jpeg;base64,{body.image_base64}"
        current_user_msg = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": body.user_text.strip()},
            ],
        }
        token_budget = max(60, limit * 3)
        is_text_mode = True  # 历史记录按文字模式处理（不插截图占位符）

    elif has_text:
        limit = max(10, min(body.max_chars, 100))
        system_prompt = (
            f"{persona_with_memory}\n\n" if persona_with_memory else ""
        ) + _env_block + (
            f"你正在陪用户玩游戏/看他的屏幕，现在他直接在跟你说话。"
            f"请用你的角色口吻自然回应，不超过{limit}字，口语化，不要废话，不加任何前缀或引号。"
        )
        current_user_msg = {"role": "user", "content": body.user_text.strip()}
        token_budget = max(60, limit * 3)
        is_text_mode = True

    else:
        # ── 纯截图评论模式：观察屏幕内容发弹幕 ──────────────────────────────
        limit = max(10, min(body.max_chars, 50))
        system_prompt = (
            f"{persona_with_memory}\n\n" if persona_with_memory else ""
        ) + _env_block + (
            "你正在陪用户玩游戏/看他的屏幕。"
            "观察截图后，判断以下两种情况：\n"
            f"1. 如果截图里的输入框/文本区域中有正在输入的文字，且内容像是在对你说话"
            f"（例如提到你的名字「{char_name}」、向你提问、跟你聊天），"
            f"请直接用角色口吻回应这段话，不超过{limit}字。\n"
            f"2. 否则，用你的角色口吻发表一句简短的陪玩评论（不超过{limit}字，口语化，自然，不要废话）。\n"
            "只输出回应本身，不加任何前缀或引号。"
        )
        image_data_url = f"data:image/jpeg;base64,{body.image_base64}"
        current_user_msg = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": "请基于图片和用户互动"},
            ],
        }
        token_budget = max(40, limit * 3)
        is_text_mode = False

    messages: List[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(session["history"])
    active_model = await _get_companion_model(auth_username or body.username)
    messages.append(current_user_msg)
    messages = _companion_inject_no_think(messages, active_model)

    _eff_model_name = _companion_effective_model_name(active_model)
    payload = {
        "model": _eff_model_name,
        "messages": messages,
        "stream": False,
    }
    apply_llm_task_payload_config(payload, "companion_frame")
    reasoning_policy = _companion_reasoning_policy("companion_frame", active_model, _eff_model_name)

    try:
        try:
            _fr = await call_llm_payload(
                payload,
                active_model,
                task="companion",
                timeout=llm_task_float("companion_frame", "timeout_seconds", float(GENERATE_TIMEOUT_SEC)) or float(GENERATE_TIMEOUT_SEC),
                reasoning_policy=reasoning_policy,
                record_usage="companion",
                usage_meter_username=auth_username,
            )
        except httpx.HTTPStatusError as e:
            _code = e.response.status_code if e.response is not None else 0
            raw_text = (e.response.text if e.response is not None else "") or ""
            logger.warning(f"[Companion] 模型调用失败 {_code}: {raw_text[:200]}")
            _write_companion_log(body.username, None, payload, raw_text, error=f"http_{_code}")
            return {"status": "error", "message": "model_error"}

        data = _fr.raw_response
        raw_text = json.dumps(data, ensure_ascii=False)
        content = (_fr.text or "").strip()

        next_frame = session["frame_count"] + (0 if is_text_mode else 1)
        placeholder = _append_to_session(
            sess_key, next_frame, content,
            user_text=body.user_text.strip() if is_text_mode else "",
            with_image=has_image,
        )

        # 有截图时：后台并行生成图片描述，完成后替换历史中的占位符
        # （纯截图模式 + 图文联合模式都走此分支；纯文字模式 placeholder=None 跳过）
        if placeholder and body.image_base64:
            asyncio.create_task(
                _describe_and_patch_history(sess_key, body.image_base64, placeholder, username=body.username)
            )

        mode_tag = "💬文字" if is_text_mode else f"📸第{next_frame}帧"
        logger.info(f"🎮 [Companion] {auth_username}/{char_name} [{mode_tag}]: {content!r}")
        _write_companion_log(body.username, char_name, payload, raw_text, reaction=content)
        return {"status": "ok", "reaction": content, "character_name": char_name}

    except Exception as e:
        logger.warning(f"[Companion] 异常: {type(e).__name__}: {e!r}", exc_info=True)
        return {"status": "error", "message": "internal error"}


# ── POST /api/companion/stream（流式对话） ───────────────────────────────────────

@router.post("/api/companion/stream")
async def analyze_frame_stream(
    body: FrameRequest,
    x_chat_auth: Optional[str] = Header(None, alias="X-Chat-Auth"),
):
    """
    流式版本：LLM 开启 stream=True，以 SSE 格式逐 token 推送给客户端。
    格式：data: {"d": "<delta>"}\n\n  …  data: {"done": true, "reaction": "<full>"}\n\n
    """
    auth_username = await _verify(x_chat_auth)
    if not auth_username:
        async def _err():
            yield 'data: {"error":"unauthorized"}\n\n'
        return StreamingResponse(_err(), media_type="text/event-stream")

    char_row = await _load_character_row(body.username, body.character_id)
    if not char_row:
        async def _err2():
            yield 'data: {"error":"character_not_found"}\n\n'
        return StreamingResponse(_err2(), media_type="text/event-stream")

    # 调试帧落盘（后台异步，不阻塞主流程）
    if body.image_base64:
        asyncio.create_task(
            asyncio.to_thread(_save_frame_debug, body.username, body.image_base64)
        )

    char_name = char_row["name"]
    persona = await _get_effective_persona(char_row)

    _memory_block = ""
    _layers: dict = {}
    try:
        _layers = await recall_memories_layered(username=body.username, character_id=body.character_id)
        _memory_block = format_layered_memories_for_prompt(**_layers)
    except Exception:
        pass

    persona_with_memory = persona
    if _memory_block:
        persona_with_memory = f"{persona}\n\n{_memory_block}" if persona else _memory_block
    persona_with_memory = f"{persona_with_memory}\n\n{_COMPANION_ROLEPLAY_ANCHOR}" if persona_with_memory else _COMPANION_ROLEPLAY_ANCHOR
    # 用户明确偏好覆盖块：具体化为强制指令，放在最末尾权重最高
    _pref_override = _build_preference_override(_layers.get("c_entries", []))
    if _pref_override:
        persona_with_memory = f"{persona_with_memory}\n\n{_pref_override}"

    sess_key = _session_key(body.username, body.character_id)
    session = _get_or_create_session(sess_key)

    # 环境上下文（时间/设备/位置/天气），每次请求随消息更新
    _env_ctx_text = ""
    if body.client_context:
        _env_ctx_text = format_client_context(body.client_context)
    _env_block = f"{_env_ctx_text}\n\n" if _env_ctx_text else ""

    has_text = bool(body.user_text.strip())
    has_image = bool(body.image_base64.strip())
    is_proactive = bool(body.proactive_hint.strip()) and not has_text

    if is_proactive:
        # ── 主动发言模式：AI 自主说一句话，不产生用户历史条目 ─────────────────
        limit = max(10, min(body.max_chars, 60))
        hint = body.proactive_hint.strip()
        if hint == "greeting":
            task_instruction = (
                f"用户刚刚开启了聊天陪玩，这是本次陪玩的第一句话。"
                f"用你的角色口吻自然地打个招呼，不超过{limit}字，不加任何前缀或引号。"
            )
        else:
            task_instruction = (
                f"用户没有回应你，你趁空档主动再说一句话延续聊天。"
                f"要求：1.不能重复或改写刚才说过的内容；"
                f"2.可以从新角度评论当前画面、追问用户一个问题、或自然转到相关话题；"
                f"3.内容与上一句要有递进、转折或互动关系，不能只是换个说法重复。"
                f"口语化自然，不超过{limit}字，不加任何前缀或引号。"
            )
        system_prompt = (
            f"{persona_with_memory}\n\n" if persona_with_memory else ""
        ) + _env_block + task_instruction
        if has_image:
            image_data_url = f"data:image/jpeg;base64,{body.image_base64}"
            current_user_msg = {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {"type": "text", "text": "(陪玩开始)"},
                ],
            }
        else:
            current_user_msg = {"role": "user", "content": "(陪玩开始)"}
        token_budget = max(60, limit * 3)
        is_text_mode = True

    elif has_text and has_image:
        limit = max(10, min(body.max_chars, 100))
        system_prompt = (
            f"{persona_with_memory}\n\n" if persona_with_memory else ""
        ) + _env_block + (
            f"你正在陪用户玩游戏/看他的屏幕，用户在看着屏幕的同时直接跟你说了话。"
            f"请结合截图内容理解上下文，并用你的角色口吻自然回应用户说的话，"
            f"不超过{limit}字，口语化，不要废话，不加任何前缀或引号。"
        )
        image_data_url = f"data:image/jpeg;base64,{body.image_base64}"
        current_user_msg = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": body.user_text.strip()},
            ],
        }
        token_budget = max(60, limit * 3)
        is_text_mode = True

    elif has_text:
        limit = max(10, min(body.max_chars, 100))
        system_prompt = (
            f"{persona_with_memory}\n\n" if persona_with_memory else ""
        ) + _env_block + (
            f"你正在陪用户玩游戏/看他的屏幕，现在他直接在跟你说话。"
            f"请用你的角色口吻自然回应，不超过{limit}字，口语化，不要废话，不加任何前缀或引号。"
        )
        current_user_msg = {"role": "user", "content": body.user_text.strip()}
        token_budget = max(60, limit * 3)
        is_text_mode = True

    else:
        limit = max(10, min(body.max_chars, 50))
        system_prompt = (
            f"{persona_with_memory}\n\n" if persona_with_memory else ""
        ) + _env_block + (
            "你正在陪用户玩游戏/看他的屏幕。"
            "观察截图后，判断以下两种情况：\n"
            f"1. 如果截图里的输入框/文本区域中有正在输入的文字，且内容像是在对你说话"
            f"（例如提到你的名字「{char_name}」、向你提问、跟你聊天），"
            f"请直接用角色口吻回应这段话，不超过{limit}字。\n"
            f"2. 否则，用你的角色口吻发表一句简短的陪玩评论（不超过{limit}字，口语化，自然，不要废话）。\n"
            "只输出回应本身，不加任何前缀或引号。"
        )
        image_data_url = f"data:image/jpeg;base64,{body.image_base64}"
        current_user_msg = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_data_url}},
                {"type": "text", "text": "请基于图片和用户互动"},
            ],
        }
        token_budget = max(40, limit * 3)
        is_text_mode = False

    messages: List[dict] = [{"role": "system", "content": system_prompt}]
    active_model = await _get_companion_model(auth_username or body.username)
    messages.extend(session["history"])
    messages.append(current_user_msg)
    messages = _companion_inject_no_think(messages, active_model)

    _eff_model_name = _companion_effective_model_name(active_model)
    payload = {
        "model": _eff_model_name,
        "messages": messages,
        "stream": True,
    }
    apply_llm_task_payload_config(payload, "companion_frame")
    reasoning_policy = _companion_reasoning_policy("companion_frame", active_model, _eff_model_name)
    companion_timeout = llm_task_float("companion_frame", "timeout_seconds", float(GENERATE_TIMEOUT_SEC)) or float(GENERATE_TIMEOUT_SEC)
    next_frame = session["frame_count"] + (0 if is_text_mode else 1)
    _stream_dbg = {
        k: v
        for k, v in (
            ("temperature", payload.get("temperature")),
            (
                "max_tokens",
                payload.get("max_completion_tokens") or payload.get("max_tokens"),
            ),
        )
        if v is not None
    }

    async def _generate():
        full_content = ""
        stream_usage = None  # 流式响应中可能携带的 usage（统一入口不解析 usage 行时保持 None，走估算）
        try:
            async with httpx.AsyncClient(timeout=companion_timeout) as client:
                try:
                    async for delta in call_llm_stream_payload(
                        payload,
                        active_model,
                        task="companion",
                        httpx_client=client,
                        timeout=companion_timeout,
                        reasoning_policy=reasoning_policy,
                        chat_debug_request={
                            "username": auth_username or body.username,
                            "character_id": body.character_id,
                            "mode": "companion",
                            "model_name": _eff_model_name,
                            "stage": "REQUEST",
                            "params": _stream_dbg or None,
                        },
                    ):
                        if delta:
                            full_content += delta
                            yield f"data: {json.dumps({'d': delta}, ensure_ascii=False)}\n\n"
                except httpx.HTTPStatusError as e:
                    _code = e.response.status_code if e.response is not None else 0
                    body_bytes = (e.response.text[:200] if e.response is not None else "") or ""
                    logger.warning(f"[Companion/stream] 模型调用失败 {_code}: {body_bytes}")
                    yield f'data: {json.dumps({"error": "model_error"}, ensure_ascii=False)}\n\n'
                    return
        except Exception as e:
            logger.warning(f"[Companion/stream] 流式异常: {type(e).__name__}: {e!r}")
            yield f'data: {json.dumps({"error": "stream_error"}, ensure_ascii=False)}\n\n'
            return

        # 流完成：写入 session 历史，异步生成图片描述
        # 主动发言模式：有截图时保留截图描述占位符（让历史有完整屏幕背景），无截图时才跳过 user 条目
        placeholder = _append_to_session(
            sess_key, next_frame, full_content,
            user_text=body.user_text.strip() if (is_text_mode and not is_proactive) else "",
            with_image=has_image,
            skip_user=(is_proactive and not has_image),
        )
        if placeholder and body.image_base64:
            asyncio.create_task(
                _describe_and_patch_history(sess_key, body.image_base64, placeholder, username=body.username)
            )

        mode_tag = "🤖主动发言" if is_proactive else ("💬文字流式" if is_text_mode else f"📸第{next_frame}帧流式")
        logger.info(f"🎮 [Companion/stream] {auth_username}/{char_name} [{mode_tag}]: {full_content!r}")
        _write_companion_log(body.username, char_name, payload, "", reaction=full_content)

        # 陪玩：每次流式模型调用成功计入 companion 用量 + 用户每日次数（与全站按次统计一致）
        try:
            if stream_usage:
                inp, out = extract_usage_from_response(stream_usage)
            else:
                inp = estimate_tokens(payload.get("messages") or messages)
                out = estimate_output_tokens(full_content)
            await get_users_dao().increment_companion_usage(
                auth_username, inp, out, llm_api_calls=1,
            )
            await get_membership_dao().increment_by(auth_username, 1)
        except Exception as ex:
            logger.debug(f"[Companion/stream] 陪玩用量统计失败: {ex}")

        yield f"data: {json.dumps({'done': True, 'reaction': full_content}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


# ── 陪玩记忆摘要（LLM 生成） ──────────────────────────────────────────────────

async def _generate_companion_memory_summary(
    char_name: str,
    history: list,
    duration_seconds: int,
    frame_count: int,
    username: str = "",
) -> tuple[str, int, list]:
    """
    调用 LLM，根据完整对话历史（含图片描述）生成有价值的陪玩记忆摘要。
    返回 (content, importance, preferences)，生成失败时返回 ("", 5, [])。
    importance 由 LLM 综合对话内容和时长评分（1~10）。
    """
    if not history:
        return ("", 5, [])

    # 将历史格式化为可读对话文本
    import re as _re_mem
    _placeholder_pattern = _re_mem.compile(r"\[帧#\d+·图片描述加载中\]")
    conv_lines = []
    for msg in history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            # 多模态消息（含图片）：只取文字部分
            parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
            content = " ".join(parts).strip()
        if not content:
            continue
        # 兜底：若描述任务还未完成，占位符尚未被替换，用可读文本代替
        if isinstance(content, str):
            content = _placeholder_pattern.sub("[截图]", content)
        if not content:
            continue
        if role == "user":
            conv_lines.append(f"{username or '用户'}：{content}")
        elif role == "assistant":
            conv_lines.append(f"{char_name}：{content}")

    conv_text = "\n".join(conv_lines).strip()
    if not conv_text:
        return ("", 5, [])

    duration_min = max(1, duration_seconds // 60)
    user_label = username or "用户"
    context_desc = f"共{frame_count}张截图" if frame_count > 0 else "纯语音/文字对话"
    prompt = (
        f"以下是{char_name}与{user_label}约{duration_min}分钟陪玩中的对话记录"
        f"（{context_desc}）：\n\n"
        f"{conv_text}\n\n"
        f"请从{char_name}的视角，写一条真实的陪玩记忆，并评估重要程度；"
        f"同时提取对话中{user_label}明确表达的个人偏好（若有）。\n\n"
        f"记忆内容要求（2~4句话，不超过120字）：\n"
        f"1. 用我们或{user_label}来描述活动，不要用用户这种冷漠称呼\n"
        f"2. 记录一起做了什么（玩什么游戏、看什么内容等）和有趣的互动\n"
        f"3. 写出让人印象深刻的细节，{user_label}的喜好、性格或特别的时刻\n"
        f"4. 语气像朋友记日记，亲切自然，不要像服务记录\n\n"
        f"偏好提取要求（preferences 字段）：\n"
        f"- 若对话中{user_label}明确说了不喜欢/喜欢某种称呼、互动方式、话题等，逐条列出\n"
        f"- 格式：简短直接的陈述句，如：不喜欢被叫亲爱的，希望直接叫{user_label}\n"
        f"- 重要：单次手机操作请求（如帮我打开相册、找联系人、发消息、打开应用等）\n"
        f"  绝对不是用户偏好，不要提取。偏好只记录持久的个人特征：称呼习惯、互动风格、话题喜好等。\n"
        f"- 若没有明确偏好表达，preferences 填空列表 []\n\n"
        f"importance 评分标准（综合对话内容质量和时长，1~10整数）：\n"
        f"  1~3：很短或内容平淡无奇\n"
        f"  4~5：普通陪玩，没有特别印象深刻的内容\n"
        f"  6~7：较长的会话或有有趣互动、话题\n"
        f"  8~9：长时间且有深度交流、重要话题或特别难忘的时刻\n"
        f"  10：极其特别、具有重要意义的时刻\n\n"
        f'只输出 JSON，必须用中文，格式：{{"content": "记忆内容", "importance": 数字, "preferences": ["偏好1", "偏好2"]}}'
    )

    payload = {
        "model": _MINI_MODEL["model_name"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    apply_llm_task_payload_config(payload, "companion_memory")
    reasoning_policy = _companion_reasoning_policy("companion_memory", _MINI_MODEL)
    try:
        try:
            _mem_r = await call_llm_payload(
                payload,
                _MINI_MODEL,
                task="companion",
                timeout=llm_task_float("companion_memory", "timeout_seconds", 30.0) or 30.0,
                reasoning_policy=reasoning_policy,
                record_usage="companion",
                usage_meter_username=username or None,
            )
        except httpx.HTTPStatusError as e:
            _code = e.response.status_code if e.response is not None else 0
            raw_text = (e.response.text if e.response is not None else "") or ""
            logger.warning(f"[Companion/memory] 摘要生成失败 {_code}")
            _write_companion_sub_log("memory", username, payload, raw_text, error=f"http_{_code}")
            return ("", 5, [])
        data = _mem_r.raw_response
        raw_text = json.dumps(data, ensure_ascii=False)
        raw_result = (_mem_r.text or "").strip()
        _write_companion_sub_log("memory", username, payload, raw_text, result=raw_result)

        # 解析 JSON 结果
        import json as _json
        import re as _re
        # 去掉可能的 markdown 代码块包裹
        clean = _re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_result, flags=_re.MULTILINE).strip()
        parsed = _json.loads(clean)
        content = str(parsed.get("content", "")).strip()
        importance = int(parsed.get("importance", 5))
        importance = max(1, min(10, importance))
        # 只保留含中文字符的偏好条目，过滤语言漂移产生的外语条目
        preferences = [
            str(p).strip() for p in parsed.get("preferences", [])
            if str(p).strip() and any('\u4e00' <= c <= '\u9fff' for c in str(p))
        ]
        if not content:
            return ("", 5, [])
        # 检测语言漂移：content 里应有至少一个中文字符，否则模型输出了非中文（如俄语）
        has_cjk = any('\u4e00' <= c <= '\u9fff' for c in content)
        if not has_cjk:
            logger.warning(f"[Companion/memory] 摘要疑似非中文输出，已丢弃（前30字）: {content[:30]!r}")
            return ("", 5, [])
        return (content, importance, preferences)
    except Exception as e:
        logger.warning(f"[Companion/memory] 摘要生成异常: {e}")
        _write_companion_sub_log("memory", username, payload, "", error=str(e))
        return ("", 5, [])
