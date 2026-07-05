from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from ..chat_modules.character import build_character_profile_prompt_block, load_character_from_db
from ..chat_modules.context_memory import format_context_memory_for_prompt, load_context_memory
from ..db import get_database
from ..db.conversations_dao import ConversationsDAO
from ..db.memory_dao import recall_memories
from .minigames_xiangqi_common import _clip_text, _opponent_side, _safe_user_display_name, _side_label

def _merge_dict(defaults: dict[str, Any], value: Any) -> dict[str, Any]:
    merged = deepcopy(defaults)
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, dict) and isinstance(merged.get(key), dict):
                merged[key] = _merge_dict(merged[key], item)
            else:
                merged[key] = item
    return merged


def _point_text(value: Any) -> str:
    if not isinstance(value, dict):
        return "(?,?)"
    return f"({value.get('x', '?')},{value.get('y', '?')})"


def _history_entry_summary(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    actor = str(entry.get("actor") or "").strip()
    actor_label = "角色" if actor == "character" else "用户" if actor == "user" else actor or "未知"
    side = _side_label(entry.get("side", "black"))
    piece = str(entry.get("piece") or "棋子")
    move_summary = str(entry.get("move_summary") or "").strip()
    if not move_summary:
        capture = f"，吃掉{entry.get('captured_piece')}" if entry.get("captured_piece") else ""
        check = "，形成将军" if entry.get("is_check") else ""
        move_summary = f"{side}{piece}从{_point_text(entry.get('from'))}到{_point_text(entry.get('to'))}{capture}{check}"
    reply_text = _clip_text(entry.get("reply_text"), 80)
    return {
        "actor": actor,
        "actor_label": actor_label,
        "side": entry.get("side"),
        "side_label": entry.get("side_label") or side,
        "piece": piece,
        "piece_kind": entry.get("piece_kind"),
        "from": entry.get("from"),
        "to": entry.get("to"),
        "is_capture": bool(entry.get("is_capture")),
        "captured_piece": entry.get("captured_piece"),
        "is_check": bool(entry.get("is_check")),
        "notation": entry.get("notation"),
        "direction": entry.get("direction"),
        "river_event": entry.get("river_event"),
        "move_summary": move_summary,
        "reply_hint": entry.get("reply_hint") or move_summary,
        "reply_text": reply_text,
    }


def _compact_move_history(history: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for entry in history[-limit:]:
        summary = _history_entry_summary(entry)
        if summary:
            compact.append(summary)
    return compact


def _compact_move_history_json(history: list[dict[str, Any]], limit: int = 10, char_limit: int = 5200) -> str:
    compact = _compact_move_history(history, limit=limit)
    while compact:
        text = json.dumps(compact, ensure_ascii=False)
        if len(text) <= char_limit:
            return text
        compact = compact[1:]
    return "[]"


def _last_move_facts(history: list[dict[str, Any]]) -> dict[str, Any]:
    entries = [_history_entry_summary(entry) for entry in history]
    entries = [entry for entry in entries if entry]

    def last_by_actor(actor: str) -> dict[str, Any] | None:
        return next((entry for entry in reversed(entries) if entry.get("actor") == actor), None)

    return {
        "last_move": entries[-1] if entries else None,
        "last_character_move": last_by_actor("character"),
        "last_user_move": last_by_actor("user"),
    }


def _piece_survival_context(
    board_state: dict[str, Any] | None,
    move_history: list[dict[str, Any]],
) -> dict[str, Any]:
    side_names = {"red": "红方", "black": "黑方"}
    kind_labels = {
        "general": "将/帅",
        "advisor": "士/仕",
        "elephant": "象/相",
        "horse": "马",
        "rook": "车",
        "cannon": "炮",
        "soldier": "卒/兵",
    }
    counts: dict[str, dict[str, int]] = {"red": {}, "black": {}}
    pieces = (board_state or {}).get("pieces")
    if isinstance(pieces, list):
        for piece in pieces:
            if not isinstance(piece, dict):
                continue
            side = str(piece.get("side") or "").strip().lower()
            if side not in counts:
                continue
            label = str(piece.get("text") or "").strip()
            if not label:
                label = kind_labels.get(str(piece.get("kind") or "").strip().lower(), "棋子")
            counts[side][label] = counts[side].get(label, 0) + 1

    captures: list[dict[str, Any]] = []
    for entry in move_history:
        if not isinstance(entry, dict) or not entry.get("is_capture"):
            continue
        captured_piece = str(entry.get("captured_piece") or "").strip()
        if not captured_piece:
            continue
        capturing_side = str(entry.get("side") or "").strip().lower()
        captured_side = _opponent_side(capturing_side) if capturing_side in side_names else ""
        captures.append(
            {
                "captured_side": captured_side,
                "captured_side_label": side_names.get(captured_side, "未知方"),
                "captured_piece": captured_piece,
                "captured_at": entry.get("to"),
                "capturing_side": capturing_side,
                "capturing_side_label": side_names.get(capturing_side, "未知方"),
                "capturing_piece": entry.get("piece"),
                "move_summary": _clip_text(entry.get("move_summary"), 90),
            }
        )

    return {
        "current_piece_counts": {
            side_names[side]: counts.get(side, {}) for side in ("red", "black")
        },
        "recent_captures": captures[-8:],
        "rule": (
            "recent_captures 里的棋子已经离开棋盘；除非 current_piece_counts 与当前棋盘明确仍有同方同类棋子参与，"
            "不要说后续走法是在和已被吃掉的棋子协同、保护它或借它进攻。"
        ),
    }


def _compact_dialogue_history_json(history: list[dict[str, Any]], limit: int = 12, char_limit: int = 2200) -> str:
    compact: list[dict[str, str]] = []
    for entry in history[-limit:]:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or entry.get("actor") or "").strip()
        text = _clip_text(entry.get("text") or entry.get("content") or entry.get("reply_text"), 120)
        if not role or not text:
            continue
        label = "角色" if role in {"character", "assistant"} else "用户" if role == "user" else role
        compact.append({"role": role, "label": label, "text": text})
    while compact:
        text = json.dumps(compact, ensure_ascii=False)
        if len(text) <= char_limit:
            return text
        compact = compact[1:]
    return "[]"


def _recent_character_replies(
    history: list[dict[str, Any]],
    dialogue_history: list[dict[str, Any]] | None = None,
    limit: int = 4,
) -> list[str]:
    replies: list[str] = []
    for entry in reversed(history):
        if not isinstance(entry, dict) or entry.get("actor") != "character":
            continue
        reply = _clip_text(entry.get("reply_text"), 80)
        if reply:
            replies.append(reply)
        if len(replies) >= limit:
            break
    if len(replies) < limit and dialogue_history:
        for entry in reversed(dialogue_history):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("role") or entry.get("actor") or "") not in {"character", "assistant"}:
                continue
            reply = _clip_text(entry.get("text") or entry.get("content") or entry.get("reply_text"), 80)
            if reply and reply not in replies:
                replies.append(reply)
            if len(replies) >= limit:
                break
    return list(reversed(replies))


_XIANGQI_REPLY_OPENERS = (
    "哇",
    "哇！",
    "嘿",
    "嘿嘿",
    "哈哈",
    "好呀",
    "嗯",
    "等下",
    "糟糕",
    "别急",
)

_XIANGQI_REPEATABLE_PHRASES = (
    "嘿嘿",
    "那我",
    "好凶",
    "看看能不能",
    "碰到",
    "挪一下",
    "往前挪",
    "往后挪",
    "横着挪",
    "躲开",
    "再说",
    "顺便",
    "是想",
    "过河去玩玩",
    "将你一军",
    "看你怎么",
    "这下看你",
    "换一手",
    "换个走法",
    "换个玩法",
    "瞄到",
    "瞄一下",
    "顺便瞄",
)

_XIANGQI_SINGLE_USE_FLOURISHES = {
    "嘿嘿",
    "将你一军",
    "换一手",
    "换个走法",
    "换个玩法",
    "瞄到",
    "瞄一下",
    "顺便瞄",
}


def _xiangqi_reply_opener(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    for opener in _XIANGQI_REPLY_OPENERS:
        if cleaned.startswith(opener):
            return opener
    return re.split(r"[，。！？!?~～\s]", cleaned, maxsplit=1)[0][:12]


def _xiangqi_emotional_arc(history: list[dict[str, Any]]) -> dict[str, Any]:
    high_value_kinds = {"rook", "horse", "cannon", "advisor", "elephant"}
    recent = [entry for entry in history[-12:] if isinstance(entry, dict)]
    character_losses: list[str] = []
    user_losses: list[str] = []
    character_high_losses: list[str] = []
    user_high_losses: list[str] = []
    checks_against_character = 0
    checks_against_user = 0
    for entry in recent:
        actor = str(entry.get("actor") or "").strip()
        captured_piece = str(entry.get("captured_piece") or "").strip()
        captured_kind = str(entry.get("captured_piece_kind") or "").strip().lower()
        if captured_piece and entry.get("is_capture"):
            if actor == "user":
                character_losses.append(captured_piece)
                if captured_kind in high_value_kinds:
                    character_high_losses.append(captured_piece)
            elif actor == "character":
                user_losses.append(captured_piece)
                if captured_kind in high_value_kinds:
                    user_high_losses.append(captured_piece)
        if entry.get("is_check"):
            if actor == "user":
                checks_against_character += 1
            elif actor == "character":
                checks_against_user += 1

    hints: list[str] = []
    if character_high_losses:
        hints.append(
            f"角色刚丢过大子（{ '、'.join(character_high_losses[-2:]) }），下一句应有心疼、嘴硬、慌一下或急着找补，别只说“好凶”。"
        )
    elif len(character_losses) >= 3:
        hints.append("角色这局已经被连续吃子，情绪应从轻松转为不服、慌张或嘴硬，而不是每次重置成同一句惊讶。")
    if user_high_losses:
        hints.append(
            f"角色刚吃到用户大子（{ '、'.join(user_high_losses[-2:]) }），可以明显得意、兴奋或松一口气，但要贴合角色。"
        )
    elif len(user_losses) >= 3 or checks_against_user >= 2:
        hints.append("角色正在打出压力，可以更得意或更有节奏地推进，不要只做平铺走法说明。")
    if checks_against_character >= 2:
        hints.append("角色近期多次被将军，回应应有被逼迫的连续感，避免反复“又将军/好凶/躲开”。")

    return {
        "recent_character_losses": character_losses[-5:],
        "recent_user_losses": user_losses[-5:],
        "checks_against_character": checks_against_character,
        "checks_against_user": checks_against_user,
        "hint": " ".join(hints) or "暂无强烈情绪线；仍需承接最近台词，避免每步像独立开场。",
    }


def _xiangqi_reply_style_state(
    history: list[dict[str, Any]],
    dialogue_history: list[dict[str, Any]] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    replies = _recent_character_replies(history, dialogue_history, limit=limit)
    opener_counts: dict[str, int] = {}
    for reply in replies:
        opener = _xiangqi_reply_opener(reply)
        if opener:
            opener_counts[opener] = opener_counts.get(opener, 0) + 1

    phrase_counts: dict[str, int] = {}
    joined_recent = "\n".join(replies)
    for phrase in _XIANGQI_REPEATABLE_PHRASES:
        count = joined_recent.count(phrase)
        if count:
            phrase_counts[phrase] = count

    overused_openers = [
        opener for opener, count in opener_counts.items()
        if count >= 2 or (len(replies) >= 2 and all(_xiangqi_reply_opener(reply) == opener for reply in replies[-2:]))
    ]
    overused_phrases = [
        phrase for phrase, count in phrase_counts.items()
        if count >= 2
        or phrase in _XIANGQI_SINGLE_USE_FLOURISHES
        or any(phrase in reply for reply in replies[-2:])
    ]
    avoid = list(dict.fromkeys(overused_openers + overused_phrases))

    if avoid:
        next_reply_guidance = (
            "下一句应主动换一种开头、句式骨架和收尾；除非是在引用用户原话，角色可见文本不得再出现 overused_phrases 里的词组。"
            "可以换成短促吐槽、嘴硬、自言自语、承认压力、突然得意、接用户玩笑、直接说棋子动作等角度。"
        )
    else:
        next_reply_guidance = "下一句仍要承接最近台词，不要套上一轮相同的默认骨架。"

    latest_user_texts: list[str] = []
    for entry in reversed(dialogue_history or []):
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or entry.get("actor") or "").strip()
        if role != "user":
            continue
        text = _clip_text(entry.get("text") or entry.get("content"), 80)
        if text:
            latest_user_texts.append(text)
        if len(latest_user_texts) >= 3:
            break

    return {
        "recent_replies": replies,
        "recent_openers": [_xiangqi_reply_opener(reply) for reply in replies if _xiangqi_reply_opener(reply)],
        "overused_phrases": avoid[:12],
        "phrase_counts": phrase_counts,
        "latest_user_texts": list(reversed(latest_user_texts)),
        "emotional_arc": _xiangqi_emotional_arc(history),
        "next_reply_guidance": next_reply_guidance,
    }


def _coerce_repeated_terms(value: Any, limit: int = 8) -> list[str]:
    if value is None:
        return []
    raw_items: list[Any]
    if isinstance(value, str):
        raw_items = re.split(r"[、,，\s]+", value)
    elif isinstance(value, list):
        raw_items = value
    else:
        return []

    terms: list[str] = []
    for item in raw_items:
        term = _clip_text(item, 16).strip()
        if not term or term in terms:
            continue
        terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def _recent_model_repeated_terms(
    history: list[dict[str, Any]],
    dialogue_history: list[dict[str, Any]] | None = None,
    limit: int = 10,
) -> list[str]:
    entries: list[dict[str, Any]] = []
    for entry in (history or [])[-12:]:
        if isinstance(entry, dict) and str(entry.get("actor") or "") == "character":
            entries.append(entry)
    for entry in (dialogue_history or [])[-12:]:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or entry.get("actor") or "").strip()
        if role in {"character", "assistant"}:
            entries.append(entry)

    terms: list[str] = []
    for entry in reversed(entries):
        for key in ("近期重复词", "recent_repeated_terms"):
            for term in _coerce_repeated_terms(entry.get(key), limit=limit):
                if term not in terms:
                    terms.append(term)
                if len(terms) >= limit:
                    return list(reversed(terms))
    return list(reversed(terms))


def _normalize_execute_result(parsed: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(parsed) if isinstance(parsed, dict) else {}
    result["schema_version"] = 2
    result["近期重复词"] = _coerce_repeated_terms(
        result.get("近期重复词") or result.get("recent_repeated_terms"),
        limit=8,
    )

    reply = result.get("character_reply")
    if not isinstance(reply, dict):
        reply = {}
    reply = dict(reply)
    legacy_text = _clip_text(reply.get("text"), 120)
    reaction_text = _clip_text(reply.get("reaction_text"), 80)
    move_reason_text = _clip_text(reply.get("move_reason_text"), 80)
    casual_chat_text = _clip_text(reply.get("casual_chat_text"), 80)
    if not reaction_text and not move_reason_text and not casual_chat_text and legacy_text:
        reaction_text = legacy_text
    combined_text = " ".join(
        part for part in [reaction_text, move_reason_text, casual_chat_text] if part
    ).strip()
    reply["reaction_text"] = reaction_text
    reply["move_reason_text"] = move_reason_text
    reply["casual_chat_text"] = casual_chat_text
    reply["text"] = _clip_text(combined_text or legacy_text, 140)
    if not str(reply.get("tts_text") or "").strip():
        reply["tts_text"] = reply["text"]
    result["character_reply"] = reply

    action = str(result.get("action") or "").strip().lower()
    result["action"] = action
    if action == "move_silent":
        reply["reaction_text"] = ""
        reply["move_reason_text"] = ""
        reply["casual_chat_text"] = ""
        reply["text"] = ""
        reply["tts_text"] = ""
    if action not in {"move", "move_silent"}:
        result["selected_move_id"] = None
        result["move"] = None
    return result


def _coerce_xiangqi_undo_result(req: XiangqiExecuteRequest, result: dict[str, Any]) -> dict[str, Any]:
    event_type = str((req.event_context or {}).get("event_type") or "").strip()
    if event_type != "user_undo_request":
        return result
    action = str(result.get("action") or "").strip()
    if action in {"approve_undo", "reject_undo"}:
        result["selected_move_id"] = None
        result["move"] = None
        return result

    coerced = deepcopy(result)
    coerced["action"] = "reject_undo"
    coerced["selected_move_id"] = None
    coerced["move"] = None
    reply = coerced.get("character_reply")
    if not isinstance(reply, dict):
        reply = {}
    text = _clip_text(
        reply.get("reaction_text") or reply.get("text") or "我先不悔这步，继续下吧。",
        80,
    )
    reply["reaction_text"] = text
    reply["move_reason_text"] = ""
    reply["casual_chat_text"] = ""
    reply["text"] = text
    reply["tts_text"] = reply.get("tts_text") or text
    reply["emotion"] = reply.get("emotion") or "calm"
    reply["style_tags"] = reply.get("style_tags") or ["自然", "拒绝悔棋"]
    coerced["character_reply"] = reply
    coerced["private"] = {
        **(coerced.get("private") if isinstance(coerced.get("private"), dict) else {}),
        "undo_coerced": True,
    }
    return coerced


def _xiangqi_user_resigned_fallback_text(req: XiangqiExecuteRequest) -> str:
    surrender = (req.event_context or {}).get("surrender")
    if not isinstance(surrender, dict):
        surrender = {}
    phase = str(surrender.get("phase") or "").strip()
    pressure = str(surrender.get("pressure_hint") or "").strip()
    user_text = str(surrender.get("user_text") or req.user_message or "").strip()
    if any(word in user_text for word in ["累", "不想下", "先不玩", "算了"]):
        return "好，那这局先到这里。你想再来时我再陪你下。"
    if phase in {"before_first_move", "opening_very_early"}:
        return "这么快就认输了呀？那这局我先收下，下一局再好好来。"
    if pressure in {"character_in_check", "user_ahead_by_captures"}:
        return "欸？我刚才还挺危险的，你认输我有点意外。"
    if pressure in {"player_in_check", "character_ahead_by_captures"}:
        return "好，这局我先收下。刚才给你的压力确实不小。"
    return "好，这局算我赢。我们下一局再慢慢下。"

def _build_xiangqi_character_profile(char: dict[str, Any] | None, *, detail_limit: int = 3200) -> str:
    if not isinstance(char, dict):
        return ""

    parts: list[str] = []
    profile = build_character_profile_prompt_block(char)
    if profile:
        parts.append(profile)

    detail_prompt = _clip_text(char.get("prompt"), detail_limit)
    if detail_prompt:
        parts.append("【角色详细设定】\n" + detail_prompt)

    return "\n\n".join(parts).strip()


async def _load_prepare_context(req: XiangqiPrepareRequest) -> dict[str, Any]:
    username = str(req.username or "").strip()
    character_id = str(req.character_id or "").strip()
    char = load_character_from_db(username, character_id) if username and character_id else None
    profile = _build_xiangqi_character_profile(char)
    return {
        "character": char or {},
        "character_profile": _clip_text(profile, 4200),
    }


async def _load_xiangqi_recent_dialogue(
    *,
    username: str,
    character_id: str,
    conversation_id: str,
    user_name: str,
    character_name: str,
    max_messages: int = 40,
) -> tuple[str, list[str], list[tuple[str, str]]]:
    if not username or not character_id:
        return "", [], []
    conversations = await ConversationsDAO(get_database()).load_conversations(username, character_id)
    target_conv = None
    if conversation_id:
        target_conv = next((c for c in conversations if c.get("id") == conversation_id), None)
    if target_conv is None and conversations:
        target_conv = conversations[0]
    if not target_conv:
        return conversation_id, [], []

    resolved_id = str(target_conv.get("id") or conversation_id or "").strip()
    recent_lines: list[str] = []
    raw_turns: list[tuple[str, str]] = []
    for msg in list((target_conv or {}).get("messages") or [])[-max_messages:]:
        role = str(msg.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = _clip_text(msg.get("content") or msg.get("displayContent") or "", 260)
        if not content:
            continue
        speaker = user_name if role == "user" else (msg.get("speaker_name") or character_name)
        recent_lines.append(f"{speaker}: {content}")
        raw_turns.append((role, content))
    return resolved_id, recent_lines, raw_turns


def _format_xiangqi_memory_fragments(memories: list[dict[str, Any]], *, limit: int = 14) -> str:
    lines = []
    for memory in memories[:limit]:
        content = _clip_text(memory.get("content"), 220)
        if not content:
            continue
        memory_type = str(memory.get("memory_type") or "memory").strip() or "memory"
        lines.append(f"- {memory_type}: {content}")
    return "\n".join(lines)


async def _load_execute_context(req: XiangqiExecuteRequest) -> dict[str, Any]:
    username = str(req.username or "").strip()
    character_id = str(req.character_id or "").strip()
    character_name = str(req.character_name or "").strip() or "角色"
    user_name = _safe_user_display_name(req.user_name)
    char = load_character_from_db(username, character_id) if username and character_id else None
    profile = _build_xiangqi_character_profile(char, detail_limit=9000)
    memories: list[dict[str, Any]] = []
    context_memory = ""
    recent_lines: list[str] = []
    if username and character_id:
        memories = await recall_memories(username, character_id, top_n=14, memory_types=None)
        resolved_conv_id, recent_lines, raw_turns = await _load_xiangqi_recent_dialogue(
            username=username,
            character_id=character_id,
            conversation_id=str(req.conversation_id or "").strip(),
            user_name=user_name,
            character_name=character_name,
        )
        if resolved_conv_id:
            memory_dict = await load_context_memory(username, character_id, resolved_conv_id, get_database())
            if memory_dict:
                context_memory = format_context_memory_for_prompt(
                    memory_dict,
                    recent_raw_turns=raw_turns[-12:],
                    user_label=user_name,
                    assistant_label=character_name,
                )
    return {
        "character_profile": _clip_text(profile, 11000),
        "memory_fragments": _format_xiangqi_memory_fragments(memories),
        "context_memory": _clip_text(context_memory, 9000),
        "recent_dialogue": "\n".join(recent_lines[-24:]),
    }


def _format_execute_role_context(ctx: dict[str, Any]) -> str:
    profile = ctx.get("character_profile") or "暂无角色资料。"
    context_memory = ctx.get("context_memory") or "暂无普通对话中期/短期记忆。"
    memory_fragments = ctx.get("memory_fragments") or "暂无跨会话长期记忆碎片。"
    recent_dialogue = ctx.get("recent_dialogue") or "暂无最近普通对话。"
    return f"""【普通角色设定】
{profile}

【普通对话上下文记忆】
{context_memory}

【跨会话长期记忆碎片】
{memory_fragments}

【最近普通对话兜底】
{recent_dialogue}"""


_XIANGQI_SALIENT_DIALOGUE_RE = re.compile(
    r"(赌|赌注|赌约|愿赌服输|兑现|答应|要求|惩罚|输了|赢了|"
    r"投降|认输|服输|输定|赢定|陪我|让我|服不服|刚才|之前|"
    r"记得|记住|约定|约好|口令|留言|昵称|升级|改成|改为|说过|聊过|问过|提过|承诺)"
)


def _xiangqi_dialogue_text(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    return _clip_text(entry.get("text") or entry.get("content") or entry.get("reply_text"), 220)


def _xiangqi_dialogue_role(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("role") or entry.get("actor") or "").strip()


def _xiangqi_role_label(role: str, *, user_name: str, character_name: str) -> str:
    role = str(role or "").strip()
    if role == "user":
        return user_name
    if role in {"character", "assistant"}:
        return character_name
    return role or "unknown"


def _xiangqi_salient_interaction_facts(
    record: dict[str, Any],
    *,
    user_name: str,
    character_name: str,
    limit: int = 18,
) -> list[dict[str, str]]:
    facts: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def append_fact(role: str, text: str) -> None:
        clean_role = str(role or "").strip()
        clean_text = _clip_text(text, 220)
        if not clean_role or not clean_text:
            return
        key = (clean_role, clean_text)
        if key in seen:
            return
        seen.add(key)
        facts.append(
            {
                "speaker": _xiangqi_role_label(
                    clean_role,
                    user_name=user_name,
                    character_name=character_name,
                ),
                "role": clean_role,
                "text": clean_text,
            }
        )

    salient = record.get("salient_interactions")
    if isinstance(salient, list):
        for entry in salient:
            append_fact(_xiangqi_dialogue_role(entry), _xiangqi_dialogue_text(entry))
            if len(facts) >= limit:
                return facts[:limit]

    recent_challenges = record.get("recent_user_challenges")
    if isinstance(recent_challenges, list):
        for text in recent_challenges:
            append_fact("user", str(text or ""))
            if len(facts) >= limit:
                return facts[:limit]

    dialogue = record.get("dialogue") if isinstance(record.get("dialogue"), list) else []
    selected_indices: set[int] = set()
    for index, entry in enumerate(dialogue):
        role = _xiangqi_dialogue_role(entry)
        text = _xiangqi_dialogue_text(entry)
        if not text:
            continue
        if role == "user" or _XIANGQI_SALIENT_DIALOGUE_RE.search(text):
            selected_indices.add(index)
        if role == "user" and index + 1 < len(dialogue):
            next_role = _xiangqi_dialogue_role(dialogue[index + 1])
            if next_role in {"character", "assistant"}:
                selected_indices.add(index + 1)

    for index in sorted(selected_indices):
        entry = dialogue[index]
        text = _xiangqi_dialogue_text(entry)
        role = _xiangqi_dialogue_role(entry)
        append_fact(role, text)
        if len(facts) >= limit:
            break
    return facts


_XIANGQI_USER_STATED_ABC_RE = re.compile(
    r"(闲聊内容\s*A\s*是|内容\s*A\s*是|口令\s*是|赌注\s*B\s*是|赌注升级为\s*C|升级为\s*C|当前有效赌注|输的人|赢家|棋盘老师)",
    re.I,
)


def _xiangqi_user_stated_abc_anchors(record: dict[str, Any], *, limit: int = 12) -> list[dict[str, str]]:
    anchors: list[dict[str, str]] = []
    seen: set[str] = set()

    def append_text(value: Any, role: str = "user") -> None:
        if role != "user":
            return
        text = _clip_text(value, 260)
        if not text or text in seen or not _XIANGQI_USER_STATED_ABC_RE.search(text):
            return
        seen.add(text)
        anchors.append(
            {
                "role": "user",
                "text": text,
                "priority": "user_stated_current_game_abc_fact",
            }
        )

    for key in ("salient_interactions", "dialogue"):
        values = record.get(key)
        if not isinstance(values, list):
            continue
        for entry in values:
            if isinstance(entry, dict):
                append_text(_xiangqi_dialogue_text(entry), _xiangqi_dialogue_role(entry))
            elif isinstance(entry, str):
                append_text(entry, "user")
            if len(anchors) >= limit:
                return anchors[:limit]
    for key in ("recent_user_challenges", "recent_user_messages"):
        values = record.get(key)
        if not isinstance(values, list):
            continue
        for text in values:
            append_text(text, "user")
            if len(anchors) >= limit:
                return anchors[:limit]
    return anchors


def _xiangqi_memory_commit_messages(req: XiangqiMemoryCommitRequest) -> tuple[str, str, str]:
    record = req.game_record if isinstance(req.game_record, dict) else {}
    character_name = str(req.character_name or "角色").strip() or "角色"
    user_name = _safe_user_display_name(req.user_name)
    summary = _clip_text(record.get("summary"), 900)
    character_result = _clip_text(record.get("character_result"), 40)
    completed_reason = _clip_text(record.get("completed_reason") or req.reason, 80)
    move_count = record.get("move_count")
    winner = _clip_text(record.get("winner"), 40)
    capture_stats = json.dumps(record.get("capture_stats") or {}, ensure_ascii=False)[:1800]
    key_moments = json.dumps(record.get("key_moments") or [], ensure_ascii=False)[:1800]
    salient_interactions = json.dumps(record.get("salient_interactions") or [], ensure_ascii=False)[:1800]
    recent_user_challenges = json.dumps(record.get("recent_user_challenges") or [], ensure_ascii=False)[:1200]
    interaction_facts = json.dumps(
        _xiangqi_salient_interaction_facts(
            record,
            user_name=user_name,
            character_name=character_name,
        ),
        ensure_ascii=False,
    )[:2400]
    user_stated_anchors = json.dumps(
        _xiangqi_user_stated_abc_anchors(record),
        ensure_ascii=False,
    )[:1600]
    dialogue = json.dumps(record.get("dialogue") or [], ensure_ascii=False)[:1600]
    moves = json.dumps(record.get("moves") or [], ensure_ascii=False)[:2200]
    user_message = f"{user_name}和{character_name}结束/记录了一局中国象棋。"
    assistant_message = f"""【中国象棋对局记忆】
记录原因：{completed_reason or "game_finished"}
结果：角色={character_result or "unknown"}；winner={winner or "unknown"}；总手数={move_count if move_count is not None else "unknown"}
摘要：{summary or "这局没有可用摘要。"}
用户明示当前局 A/B/C 事实锚（最高优先级，只能从用户原话改写，角色不同复述只能当错答背景）：{user_stated_anchors}
吃子统计：{capture_stats}
关键片段：{key_moments}
明确互动摘录（来自客户端完整对话，不受最近对话截断影响）：{salient_interactions}
用户挑战/约定/闲聊原话：{recent_user_challenges}
棋局互动事实（高优先级，后续普通聊天问“刚才闲聊/约定/口令/留言/赌注/投降/你还记得吗”时优先使用）：{interaction_facts}
当前局事实优先级：用户在本局原话中明说的闲聊内容、口令、赌注B、升级赌注C和兑现条件，是后续摘要与普通聊天的事实锚。若角色后续回复把这些内容说成旧口令、旧赌注或其它跨局内容，只能记录为角色当时说错/串台，不得用角色错误复述覆盖用户明示事实。
最近棋局对话：{dialogue}
最近走法明细：{moves}
请把这条作为小游戏经历写入普通对话记忆：后续普通聊天可以记得这局的胜负、吃子数量、悔棋/投降/关键转折、闲聊内容、口令、留言、昵称、约定、赌注/赌约/兑现条件和双方互动语气；不要把本局棋盘位置当成当前仍在进行的事实。"""
    planner_notes = (
        "这是一条刚结束或刚退出时写入的中国象棋小游戏记忆。保留可验证事实：胜负、总手数、吃子统计、关键走法、"
        "悔棋/投降/最近棋局对话，尤其保留闲聊内容、口令、留言、昵称、约定、赌注/赌约/兑现条件、用户挑衅和角色回应等互动事实。"
        "用户在本局原话中明说的闲聊内容、口令、赌注B、升级赌注C和兑现条件优先级最高；若角色回复把这些内容复述成旧局口令或旧赌注，"
        "只能写成角色说错/串台，不能把错误复述当成当前局事实。"
        "若存在“用户明示当前局 A/B/C 事实锚”，摘要必须优先采用这些用户原话；角色错答不得覆盖，旧错答不要主动写进后续普通聊天答案。"
        "若同一赌注或约定从旧版本升级为新版本，后续回答以最新明确升级后的版本为准，同时可说明旧版本已被替代。"
        "后续用户问刚才棋局闲聊、约定或赌注时，应能按这些明确记录回答；不要把过去棋盘状态写成当前现场。"
    )
    return user_message, assistant_message, planner_notes
