from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import aiosqlite

from ..config import logger
from ..db import get_database
from ..utils import ClientContext, format_client_context

POWER_TIER_ORDER = ["novice", "junior", "intermediate", "advanced"]
POWER_TIER_LABELS = {
    "novice": "新手",
    "junior": "初级",
    "intermediate": "中级",
    "advanced": "高级",
}
PLAY_STYLE_LABELS = {
    "attacking": "进攻型",
    "cautious": "谨慎型",
    "playful": "调皮型",
    "textbook": "教科书型",
}
PLAY_STYLE_ALIASES = {
    "attacking": "attacking",
    "attack": "attacking",
    "active": "attacking",
    "aggressive": "attacking",
    "进攻型": "attacking",
    "攻击型": "attacking",
    "主动型": "attacking",
    "cautious": "cautious",
    "careful": "cautious",
    "defensive": "cautious",
    "solid": "cautious",
    "safe": "cautious",
    "谨慎型": "cautious",
    "防守型": "cautious",
    "稳健型": "cautious",
    "playful": "playful",
    "tricky": "playful",
    "chaotic": "playful",
    "random": "playful",
    "mischievous": "playful",
    "调皮型": "playful",
    "乱下型": "playful",
    "整活型": "playful",
    "textbook": "textbook",
    "book": "textbook",
    "bookish": "textbook",
    "standard": "textbook",
    "classical": "textbook",
    "教科书型": "textbook",
    "棋谱型": "textbook",
    "标准型": "textbook",
}
POWER_TIER_ALIASES = {
    "novice": "novice",
    "newbie": "novice",
    "beginner": "novice",
    "新手": "novice",
    "junior": "junior",
    "basic": "junior",
    "初级": "junior",
    "intermediate": "intermediate",
    "medium": "intermediate",
    "中级": "intermediate",
    "advanced": "advanced",
    "expert": "advanced",
    "高级": "advanced",
}
POWER_TIER_WINDOW_MS = 7 * 24 * 60 * 60 * 1000
POWER_TIER_CHESS_STYLE = {
    "novice": {
        "skill": (1, 3, 2),
        "depth": (1, 2, 1),
        "blunder_tier": (3, 5, 4),
    },
    "junior": {
        "skill": (4, 6, 5),
        "depth": (2, 3, 2),
        "blunder_tier": (1, 3, 2),
    },
    "intermediate": {
        "skill": (7, 8, 7),
        "depth": (3, 3, 3),
        "blunder_tier": (0, 2, 1),
    },
    "advanced": {
        "skill": (9, 9, 9),
        "depth": (4, 4, 4),
        "blunder_tier": (0, 1, 0),
    },
}

def _clip_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _side_label(side: str) -> str:
    return "红方" if str(side).lower() == "red" else "黑方"


def _opponent_side(side: str) -> str:
    return "black" if str(side).lower() == "red" else "red"


_XIANGQI_DEFERRED_DIRECTIVE_RE = re.compile(
    r"(等一下|等下|待会儿?|一会儿?|下回合|下一回合|下一手|下一步|下步|"
    r"等轮到你|轮到你|你走的时候|你再|之后|然后你)"
)
_XIANGQI_IMMEDIATE_TURN_REQUEST_RE = re.compile(
    r"(现在|马上|立刻|立即|赶紧|快点|快|先|直接).{0,12}(走|下|动|行棋|出招|把|用)|"
    r"(你先走|你先下|你先来|该你走|该你下)"
)
_XIANGQI_CHARACTER_MOVE_SUBJECT_RE = re.compile(
    r"(你|你的|帮我|替我|请你|让你|叫你).{0,24}"
    r"(车|马|炮|砲|象|相|士|仕|将|帅|卒|兵|棋|走|下|动|行棋|出招|吃|打|拿|捉|收|兑|将|盯|威胁|躲|挡|退|进|平|移|放|跳)"
)
_XIANGQI_UNDO_DISCUSSION_RE = re.compile(
    r"(悔棋|重走|走错|下错|点错|手滑|撤回|收回|退一步|让一步|重新走|重新下|这步不算|刚才那步|看漏)"
)
_XIANGQI_USER_SELF_SURRENDER_RE = re.compile(
    r"(我|我要|我想|我这边).{0,12}(投降|认输|服输|弃局)"
)
_XIANGQI_CHARACTER_SURRENDER_RE = re.compile(
    r"(你|你的|要不要|能不能|可不可以|劝你|让你|叫你|直接|干脆|别撑|别挣扎|没救|无力回天|救不回).{0,24}"
    r"(投降|认输|服输|弃局)|"
    r"(投降吧|认输吧|服输吧|弃局吧)"
)
_XIANGQI_TERMINAL_EVENT_TYPES = {"character_lost", "character_won", "postgame_chat", "user_resigned"}
_XIANGQI_WAGER_RECALL_RE = re.compile(
    r"(赌|赌注|赌约|答应|承诺|惩罚|赢家|输.*要|输了.*要|愿赌服输|"
    r"刚才|之前|前面|聊过|聊了|说过|说了|问过|提过|约定|记得|记住|"
    r"口令|留言|昵称|约好|升级|改成|改为|改赌注|答应过|承诺过)"
)


def _xiangqi_is_terminal_or_postgame(req: "XiangqiExecuteRequest") -> bool:
    event_context = req.event_context if isinstance(req.event_context, dict) else {}
    event_type = str(event_context.get("event_type") or "").strip()
    return event_type in _XIANGQI_TERMINAL_EVENT_TYPES or isinstance(event_context.get("postgame_review"), dict)


def _xiangqi_terminal_state_hint(req: "XiangqiExecuteRequest") -> str:
    event_context = req.event_context if isinstance(req.event_context, dict) else {}
    event_type = str(event_context.get("event_type") or "").strip()
    postgame_review = event_context.get("postgame_review") if isinstance(event_context.get("postgame_review"), dict) else {}
    if event_type not in _XIANGQI_TERMINAL_EVENT_TYPES and not postgame_review:
        return ""

    winner = _clip_text(event_context.get("winner") or postgame_review.get("winner"), 40)
    character_result = _clip_text(event_context.get("character_result") or postgame_review.get("character_result"), 40)
    recent_challenges = postgame_review.get("recent_user_challenges") or []
    if not isinstance(recent_challenges, list):
        recent_challenges = []
    salient_interactions = postgame_review.get("salient_interactions") or []
    if not isinstance(salient_interactions, list):
        salient_interactions = []
    recent_user_messages = postgame_review.get("recent_user_messages") or []
    if not isinstance(recent_user_messages, list):
        recent_user_messages = []
    dialogue = postgame_review.get("dialogue") or []
    if not isinstance(dialogue, list):
        dialogue = []
    interaction_recall_requested = bool(_XIANGQI_WAGER_RECALL_RE.search(str(req.user_message or "")))

    lines = [
        "【终局/赛后硬状态】",
        f"event_type={event_type or 'postgame_review'}；winner={winner or 'unknown'}；character_result={character_result or 'unknown'}。",
        "当前请求已经离开走棋阶段：turn 只是客户端旧值或无意义残留，不代表还要继续等用户走棋。",
        "必须 action=chat_only，selected_move_id=null；不得说还没轮到我、你先走、你先下、我等着接招、下一步再看、继续走或继续下。",
    ]
    if character_result == "lost" or event_type == "character_lost":
        lines.append("角色已经输掉本局；本轮回复要承认输局并承接本局聊天，不要写成仍在对弈。")
    elif character_result == "won" or event_type in {"character_won", "user_resigned"}:
        lines.append("角色已经赢下本局或用户已认输；本轮回复要按赛后聊天处理，不要再选择棋步。")
    if recent_challenges:
        lines.append(
            "postgame_review.recent_user_challenges："
            + json.dumps(recent_challenges[:8], ensure_ascii=False)[:800]
        )
    if salient_interactions:
        lines.append(
            "postgame_review.salient_interactions（本局长程闲聊/约定摘录）："
            + json.dumps(salient_interactions[:16], ensure_ascii=False)[:1400]
        )
    if recent_user_messages:
        lines.append(
            "postgame_review.recent_user_messages："
            + json.dumps(recent_user_messages[-12:], ensure_ascii=False)[:900]
        )
    if interaction_recall_requested and dialogue:
        lines.append(
            "postgame_review.dialogue（本局最近与已保留对话）："
            + json.dumps(dialogue[-24:], ensure_ascii=False)[:1800]
        )
    if interaction_recall_requested:
        lines.append(
            "本轮用户正在追问本局闲聊、约定、赌注、承诺或答应过什么：必须直接读取 salient_interactions、recent_user_messages、dialogue 和【最近小游戏对话】说出具体内容与双方主体，不能泛化成“有个约定”，也不能只复盘胜负或最后一手。"
            "如果同一类约定/赌注出现升级、改成或改为，回答和兑现以最新明确升级后的版本为准；可简短说明旧版本如何被新版本替代。"
        )
    return "\n".join(lines)


def _xiangqi_waiting_directive_hint(req: "XiangqiExecuteRequest") -> str:
    if _xiangqi_is_terminal_or_postgame(req):
        return ""
    if str(req.turn or "").lower() == _opponent_side(req.player_side):
        return ""
    message = str(req.user_message or "").strip()
    if not message:
        return ""
    if _XIANGQI_CHARACTER_SURRENDER_RE.search(message) and not _XIANGQI_USER_SELF_SURRENDER_RE.search(message):
        return (
            "【当前回合投降解读】\n"
            "当前不是角色走棋，但用户正在劝角色认输/投降。"
            "投降不是走棋，角色如果认为局面压力太大、已经无法挽回，或性格上愿意承认失败，"
            "可以立刻返回 action=resign，不需要等到再次轮到角色。"
            "如果不想投降，可以 action=chat_only 角色化拒绝或逞强；不要说“要等轮到我才能投降”。"
        )
    if not _XIANGQI_CHARACTER_MOVE_SUBJECT_RE.search(message):
        return ""
    if _XIANGQI_UNDO_DISCUSSION_RE.search(message):
        return (
            "【当前回合悔棋解读】\n"
            "当前不是角色走棋，但用户正在询问或劝角色撤回刚才一步。"
            "如果【最近一步事实】显示 last_move.actor=character，说明角色刚下完、现在轮到用户，"
            "角色可以立刻用 action=request_undo 主动申请悔棋，不需要等到再次轮到角色。"
            "如果不想悔棋，可以 action=chat_only 角色化拒绝；不要说“要等轮到我才能悔棋”。"
        )
    if _XIANGQI_WAGER_RECALL_RE.search(message):
        return ""

    deferred = bool(_XIANGQI_DEFERRED_DIRECTIVE_RE.search(message))
    immediate = bool(_XIANGQI_IMMEDIATE_TURN_REQUEST_RE.search(message))
    if immediate and not deferred:
        return (
            "【当前回合指令解读】\n"
            "当前不是角色走棋。用户这句话更像是在要求角色现在/抢先下棋，"
            "这是违反回合规则的请求。请 action=chat_only，用角色语气说明还没到自己的回合，"
            "需要等用户先走完，不能假装已经走棋，也不要承诺立刻执行。"
        )
    return (
        "【当前回合指令解读】\n"
        "当前不是角色走棋，但用户这句话是在给角色下一回合提出走棋请求/建议，不是硬性命令。"
        "请 action=chat_only，先按角色性格和棋局态度回应：可以答应、说会考虑、调皮地先记下，"
        "也可以婉拒或表示这步未必合适；如果愿意尝试，只能说等用户走完/轮到我时再考虑或尽量照做，"
        "不能假装已经走棋，也不要承诺一定执行。"
    )


def _safe_user_display_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw or raw.lower() == "system":
        return "用户"
    return _clip_text(raw, 32)


def _coerce_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(min_value, min(max_value, n))


def _with_default_time(ctx: Optional[ClientContext]) -> ClientContext:
    now_iso = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    return ClientContext(
        time_iso=getattr(ctx, "time_iso", None) or now_iso,
        device_model=getattr(ctx, "device_model", None) if ctx else None,
        os_version=getattr(ctx, "os_version", None) if ctx else None,
        battery=getattr(ctx, "battery", None) if ctx else None,
        network=getattr(ctx, "network", None) if ctx else None,
        location_name=getattr(ctx, "location_name", None) if ctx else None,
        weather_desc=getattr(ctx, "weather_desc", None) if ctx else None,
        temperature=getattr(ctx, "temperature", None) if ctx else None,
        os_flavor=getattr(ctx, "os_flavor", None) if ctx else None,
        nav_mode=getattr(ctx, "nav_mode", None) if ctx else None,
    )


def _xiangqi_environment_context(ctx: Optional[ClientContext]) -> str:
    text = format_client_context(_with_default_time(ctx)).strip()
    return text or "【当前环境】\n时间：当前北京时间。"


def _normalize_power_tier(value: Any, default: str = "junior") -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in POWER_TIER_ALIASES:
        return POWER_TIER_ALIASES[text]
    raw = str(value or "").strip()
    if raw in POWER_TIER_ALIASES:
        return POWER_TIER_ALIASES[raw]
    return default if default in POWER_TIER_ORDER else "junior"


def _normalize_play_style(value: Any, style: dict[str, Any] | None = None, default: str = "textbook") -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in PLAY_STYLE_ALIASES:
        return PLAY_STYLE_ALIASES[text]
    raw = str(value or "").strip()
    if raw in PLAY_STYLE_ALIASES:
        return PLAY_STYLE_ALIASES[raw]
    style = style or {}
    attack = _coerce_int(style.get("attack_bias"), 3, 1, 5)
    defense = _coerce_int(style.get("defense_bias"), 3, 1, 5)
    risk = _coerce_int(style.get("risk_tolerance"), 3, 1, 5)
    if risk >= 5:
        return "playful"
    if attack >= 4 and attack >= defense:
        return "attacking"
    if defense >= 4 and defense > attack:
        return "cautious"
    return default if default in PLAY_STYLE_LABELS else "textbook"


def _candidate_tags_for_policy(power_tier: str, play_style: str) -> list[str]:
    tier = _normalize_power_tier(power_tier)
    style = _normalize_play_style(play_style)
    orders = {
        "novice": {
            "attacking": ["random_safe", "active", "risky", "good", "random", "blunder", "best", "book"],
            "cautious": ["random_safe", "solid", "good", "random", "blunder", "best", "risky", "book"],
            "playful": ["novelty", "random_safe", "random", "blunder", "risky", "good", "active", "best", "book"],
            "textbook": ["random_safe", "good", "book", "solid", "random", "blunder", "best", "risky"],
        },
        "junior": {
            "attacking": ["active", "risky", "good", "best", "random_safe", "random", "blunder", "book"],
            "cautious": ["solid", "good", "best", "random_safe", "book", "random", "risky", "blunder"],
            "playful": ["novelty", "random_safe", "good", "risky", "random", "active", "blunder", "best", "book"],
            "textbook": ["book", "good", "best", "solid", "random_safe", "risky", "random", "blunder"],
        },
        "intermediate": {
            "attacking": ["active", "best", "risky", "good", "book", "solid", "random_safe", "random", "blunder"],
            "cautious": ["solid", "best", "good", "book", "random_safe", "risky", "random", "blunder"],
            "playful": ["good", "active", "random_safe", "risky", "best", "book", "random", "blunder"],
            "textbook": ["book", "best", "good", "solid", "active", "random_safe", "risky", "random", "blunder"],
        },
        "advanced": {
            "attacking": ["active", "best", "risky", "good", "book", "solid", "random_safe", "random", "blunder"],
            "cautious": ["solid", "best", "book", "good", "active", "random_safe", "risky", "random", "blunder"],
            "playful": ["best", "active", "good", "random_safe", "risky", "book", "random", "blunder"],
            "textbook": ["book", "best", "solid", "good", "active", "random_safe", "risky", "random", "blunder"],
        },
    }
    return orders[tier][style]


def _power_tier_index(tier: str) -> int:
    normalized = _normalize_power_tier(tier)
    return POWER_TIER_ORDER.index(normalized)


def _power_tier_from_skill(skill_level: Any) -> str:
    skill = _coerce_int(skill_level, 5, 1, 9)
    if skill <= 3:
        return "novice"
    if skill <= 6:
        return "junior"
    if skill <= 8:
        return "intermediate"
    return "advanced"


def _clamp_power_tier_from_window(proposed: str, window_start: str) -> str:
    proposed_idx = _power_tier_index(proposed)
    base_idx = _power_tier_index(window_start)
    # 用户要求一周内不能从“新手”跳到“中级”，所以同一窗口最多移动 1 档。
    clamped_idx = max(base_idx - 1, min(base_idx + 1, proposed_idx))
    return POWER_TIER_ORDER[clamped_idx]


def _apply_power_tier_to_card(
    card: dict[str, Any],
    final_tier: str,
    *,
    model_tier: str | None = None,
    stability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tier = _normalize_power_tier(final_tier)
    updated = deepcopy(card)
    updated["power_tier"] = tier
    updated["power_tier_label"] = POWER_TIER_LABELS[tier]
    if model_tier:
        updated["model_power_tier"] = _normalize_power_tier(model_tier)
    if stability:
        updated["power_tier_stability"] = stability

    style = updated.get("chess_style")
    if not isinstance(style, dict):
        style = {}
    style = dict(style)
    style_bounds = POWER_TIER_CHESS_STYLE[tier]
    skill_min, skill_max, skill_default = style_bounds["skill"]
    depth_min, depth_max, depth_default = style_bounds["depth"]
    blunder_min, blunder_max, blunder_default = style_bounds["blunder_tier"]
    style["skill_level"] = _coerce_int(style.get("skill_level"), skill_default, skill_min, skill_max)
    style["calculation_depth"] = _coerce_int(style.get("calculation_depth"), depth_default, depth_min, depth_max)
    style["blunder_tier"] = _coerce_int(style.get("blunder_tier"), blunder_default, blunder_min, blunder_max)
    style["play_style"] = _normalize_play_style(style.get("play_style"), style)
    style["play_style_label"] = PLAY_STYLE_LABELS[style["play_style"]]
    updated["chess_style"] = style

    policy = updated.get("execution_policy")
    if not isinstance(policy, dict):
        policy = {}
    policy = dict(policy)
    policy["prefer_candidate_tags"] = _candidate_tags_for_policy(tier, style["play_style"])
    updated["execution_policy"] = policy
    return updated


async def _ensure_xiangqi_power_tier_table() -> None:
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA busy_timeout = 30000")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS xiangqi_power_tier_state (
                username TEXT NOT NULL,
                character_key TEXT NOT NULL,
                power_tier TEXT NOT NULL,
                model_power_tier TEXT NOT NULL DEFAULT '',
                window_start_tier TEXT NOT NULL,
                window_start_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (username, character_key)
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_xiangqi_power_tier_updated "
            "ON xiangqi_power_tier_state(updated_at_ms)"
        )
        await conn.commit()


async def _stabilize_power_tier(
    req: XiangqiPrepareRequest,
    card: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    style = card.get("chess_style") if isinstance(card.get("chess_style"), dict) else {}
    model_tier = _normalize_power_tier(
        card.get("power_tier"),
        default=_power_tier_from_skill((style or {}).get("skill_level")),
    )
    username = str(req.username or "").strip()
    character_key = str(req.character_id or "").strip() or f"name:{str(req.character_name or '').strip()}"
    now_ms = int(time.time() * 1000)
    stability = {
        "model_power_tier": model_tier,
        "final_power_tier": model_tier,
        "window_limited": False,
        "window_days": 7,
    }
    if not username or not character_key:
        final_card = _apply_power_tier_to_card(card, model_tier, model_tier=model_tier, stability=stability)
        return final_card, stability

    await _ensure_xiangqi_power_tier_table()
    db = get_database()
    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("PRAGMA busy_timeout = 30000")
        async with conn.execute(
            """
            SELECT power_tier, model_power_tier, window_start_tier, window_start_ms, updated_at_ms
            FROM xiangqi_power_tier_state
            WHERE username = ? AND character_key = ?
            """,
            (username, character_key),
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            previous_tier = _normalize_power_tier(row[0])
            window_start_tier = _normalize_power_tier(row[2] or previous_tier)
            window_start_ms = int(row[3] or row[4] or now_ms)
            if now_ms - window_start_ms < POWER_TIER_WINDOW_MS:
                final_tier = _clamp_power_tier_from_window(model_tier, window_start_tier)
            else:
                final_tier = model_tier
                window_start_tier = final_tier
                window_start_ms = now_ms
            stability.update(
                {
                    "previous_power_tier": previous_tier,
                    "window_start_tier": window_start_tier,
                    "window_start_ms": window_start_ms,
                    "final_power_tier": final_tier,
                    "window_limited": final_tier != model_tier,
                }
            )
        else:
            final_tier = model_tier
            window_start_tier = final_tier
            window_start_ms = now_ms
            stability.update(
                {
                    "previous_power_tier": None,
                    "window_start_tier": window_start_tier,
                    "window_start_ms": window_start_ms,
                    "final_power_tier": final_tier,
                }
            )

        evidence = {
            "character_name": req.character_name,
            "player_side": req.player_side,
            "model_power_tier": model_tier,
            "final_power_tier": final_tier,
            "power_tier_reason": _clip_text(card.get("power_tier_reason"), 120),
        }
        await conn.execute(
            """
            INSERT INTO xiangqi_power_tier_state (
                username, character_key, power_tier, model_power_tier,
                window_start_tier, window_start_ms, updated_at_ms, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username, character_key) DO UPDATE SET
                power_tier = excluded.power_tier,
                model_power_tier = excluded.model_power_tier,
                window_start_tier = excluded.window_start_tier,
                window_start_ms = excluded.window_start_ms,
                updated_at_ms = excluded.updated_at_ms,
                evidence_json = excluded.evidence_json
            """,
            (
                username,
                character_key,
                final_tier,
                model_tier,
                window_start_tier,
                window_start_ms,
                now_ms,
                json.dumps(evidence, ensure_ascii=False),
            ),
        )
        await conn.commit()

    final_card = _apply_power_tier_to_card(card, final_tier, model_tier=model_tier, stability=stability)
    return final_card, stability


async def _safe_stabilize_power_tier(
    req: XiangqiPrepareRequest,
    card: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return await _stabilize_power_tier(req, card)
    except Exception as exc:
        logger.warning("⚠️ [Xiangqi] 棋力等级稳定化失败，使用模型建议等级: %s", exc)
        style = card.get("chess_style") if isinstance(card.get("chess_style"), dict) else {}
        model_tier = _normalize_power_tier(
            card.get("power_tier"),
            default=_power_tier_from_skill((style or {}).get("skill_level")),
        )
        stability = {
            "model_power_tier": model_tier,
            "final_power_tier": model_tier,
            "window_limited": False,
            "window_days": 7,
            "persistence_error": str(exc),
        }
        return _apply_power_tier_to_card(card, model_tier, model_tier=model_tier, stability=stability), stability
