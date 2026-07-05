from __future__ import annotations


import asyncio
import copy
import json
import random
import re
import time
import uuid
from typing import Any

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

from ..config import logger, model_manager
from ..db import get_membership_dao, get_users_dao
from ..assistant_sanitize import (
    sanitize_assistant_close_leading_fullwidth_parens,
    sanitize_assistant_strip_markers,
    sanitize_assistant_strip_thinking_blocks,
)
from ..providers.llm_call import call_llm_payload
from .species_anatomy import (
    equine_species_has_horn,
    equine_species_has_wings,
    equine_species_prompt_line,
)
from ..utils import save_chat_debug_log
from .assistant_units import build_assistant_units, is_asset_only_reply_sequence_with_assets
from .normal_speaker import (
    ensure_guest_private_context,
    guest_direct_memory_content,
    effective_speaker_character_id,
    guest_group_memory_extract_specs,
    guest_group_participant_character_ids,
    guest_main_memory_assistant_message,
    guest_memory_user_message,
    guest_private_recent_raw_turns,
    guest_scene_context_prompt,
    is_guest_speaker,
    main_character_id,
    main_display_name,
    normal_role_debug_params,
    speaker_event_fields,
    speaker_context_conversation_id,
    speaker_display_name,
    write_guest_direct_memory_once,
)
from .runtime import (
    estimate_output_tokens,
    extract_usage_from_response,
    run_conversation_persistence,
)
from .state import is_generation_current, is_summary_placeholder_message

_NORMAL_HANDOFF_ROUTER_RECENT_ASSISTANT_TURNS = 8
_MAX_STAGE3_STRUCTURE_RETRIES = 1

_NORMAL_STAGE3_OLD_QUOTE_RE = re.compile(r"[“\"『「]([^“”\"『』「」]{2,120})[”\"』」]")
_NORMAL_STAGE3_OLD_REFERENCE_RE = re.compile(
    r"说过|讲过|提过|喊过|叫过|问过|告诉过|承诺过|约定过|那句|那天|那次|当时|"
    r"以前|之前|曾经|记得|回忆|闪回|半梦半醒|嘟囔|呢喃|求婚"
)
_NORMAL_STAGE3_HIGH_RISK_UNSUPPORTED_DETAIL_TERMS = (
    "一周年",
    "周年",
    "半梦半醒",
    "嘟囔",
    "那句",
    "打瞌睡",
    "裱花袋",
)
_NORMAL_STAGE3_NAKED_DESCRIPTION_SIGNAL_RE = re.compile(
    r"身体|心跳|呼吸|脸颊|前蹄|后蹄|蹄子|尾巴|耳朵|鬃毛|翅膀|独角|"
    r"眼睛|嘴角|肩|背|腰|腿|心里|脑子|感觉|感到|颤抖|绷紧|发烫|"
    r"发软|僵住|深吸|屏住|低头|抬头|闭上|睁开|趴|坐|站|靠|贴|"
    r"蹭|刨|踢|抖|缩|咬|攥|握|抓|抱|搂|跪|弓起|发麻|涌上|热流"
)
_NORMAL_STAGE3_SHORT_DIALOGUE_TAIL_RE = re.compile(
    r"(?P<tail>[.…。!！?？,，、\s]*(?:嗯+|唔+|呃+|啊+|好+|可以|行|"
    r"来吧|继续吧|你继续吧|别停|再来|我准备好了|准备好了)[^（）()]*)$"
)

_DESCRIPTION_SHORTCUT_PATTERNS = (
    "（请详细写出当前你的心理活动）",
    "（请详细写出当前你的身体状态）",
    "（请详细写出当前你看到的画面）",
)
_STORY_PROGRESSION_SHORTCUT_TEXT = "（请推进剧情发展）"
_LEADING_SHORTCUT_AT_RE = re.compile(
    r"^\s*[@＠][^\s@＠,，。！？!?;；:：、（）()\[\]【】》」』\"'“”‘’…]+[\s,，:：、]*"
)
_DESCRIPTION_NONHUMAN_LIMB_RE = re.compile(
    r"(手指|指尖|手掌|掌心|手腕|手臂|双手|拳头|中指|竖中指|比中指)"
)
_SUPPORTIVE_LOW_INFO_GUARD_MARKERS = (
    "压力/疲惫倾诉后只回了一个低信息承接词",
    "低信息承接后，若使用动作，必须配一小句",
    "倾诉后低信息回应不得只输出纯动作",
)

_DESCRIPTION_PONY_SPECIES_KEYWORDS = (
    "马", "小马", "飞马", "天马", "陆马", "独角兽", "雌驹", "雄驹",
    "天角兽", "pony", "pegasus", "unicorn", "alicorn", "earth pony",
)
_DESCRIPTION_HUMAN_SPECIES_KEYWORDS = ("人类", "人族", "human")


def _clean_character_species_value(value: str, *, default: str = "陆马") -> str:
    text = str(value or "").strip().strip("`\"'“”‘’")
    text = re.split(r"[\n\r，,。；;|]", text, maxsplit=1)[0].strip()
    return text or default


def _extract_explicit_current_character_species_from_messages(msgs: list) -> str:
    """只从角色主页档案字段读取种族；失败返回空字符串，不看详细设定正文。"""
    jsonish_profile_species_re = re.compile(
        r"['\"]?profileSpecies['\"]?\s*[:：]\s*['\"]?([^'\"\n\r,，。；;}]+)"
    )
    profile_species_re = re.compile(
        r"(?:^|\n)\s*(?:[-*]\s*)?种族\s*[：:]\s*([^\n\r]+)"
    )
    for msg in msgs or []:
        if not isinstance(msg, dict):
            continue
        text = str(msg.get("content") or "")
        if "【角色档案】" not in text:
            continue
        match = profile_species_re.search(text)
        if match:
            return _clean_character_species_value(match.group(1), default="")
        match = jsonish_profile_species_re.search(text)
        if match:
            return _clean_character_species_value(match.group(1), default="")
    return ""


def _extract_current_character_species_from_messages(msgs: list) -> str:
    """从已注入的角色档案字段读取当前角色种族，失败时按陆马兜底。"""
    explicit = _extract_explicit_current_character_species_from_messages(msgs)
    if explicit:
        return explicit
    jsonish_profile_species_re = re.compile(
        r"['\"]?profileSpecies['\"]?\s*[:：]\s*['\"]?([^'\"\n\r,，。；;}]+)"
    )
    for msg in msgs or []:
        if not isinstance(msg, dict):
            continue
        text = str(msg.get("content") or "")
        match = jsonish_profile_species_re.search(text)
        if match:
            return _clean_character_species_value(match.group(1))
    return "陆马"


def _description_species_has_any(species: str, keywords: tuple[str, ...]) -> bool:
    text = (species or "").strip().lower()
    return any(kw in text for kw in keywords)


def _description_is_human_species(species: str) -> bool:
    text = (species or "").strip().lower()
    if any(marker in text for marker in ("非人类", "不是人类", "非人族", "non-human", "nonhuman")):
        return False
    return _description_species_has_any(species, _DESCRIPTION_HUMAN_SPECIES_KEYWORDS)


def _build_profile_equine_mammary_anatomy_guidance(
    species: str,
    *,
    explicit_profile_species: bool = False,
) -> str:
    if not explicit_profile_species:
        return ""
    if not _description_species_has_any(species, _DESCRIPTION_PONY_SPECIES_KEYWORDS):
        return ""
    return (
        "【角色档案种族解剖学补充】"
        f"角色主页档案的种族字段为「{species}」，属于马/小马类体态。"
        f"{equine_species_prompt_line(species)}"
        "日常描写和身体介绍里自然使用蹄子、前蹄、蹄尖等符合蹄类体态的表达，不要主动罗列缺失部位；"
        "只有用户直接询问手、手指、中指或替代写法时，才简短说明应按蹄类体态理解，并给出蹄尖/前蹄等替代表达。"
        "同种幼驹/小马驹/小雌驹/小雄驹也按四蹄体态理解；健康、全乎或完整不能写成六只蹄子、六蹄或额外蹄肢。"
        "若本轮需要回答或描写当前角色自己的乳房位置，按事实解剖学定义为位于胯间、后腿之间，一共两个乳房；"
        "不要写成四个或两对乳房，也不要把乳头数量当作乳房数量；"
        "不要写成人类胸前、胸口、胸部或上半身位置。"
        "只有角色主页档案种族字段明确属于马/小马类时才启用本条；详细设定正文或默认兜底不触发。"
    )


def _build_character_species_description_guidance(species: str) -> str:
    species = str(species or "").strip() or "陆马"
    if _description_species_has_any(species, _DESCRIPTION_PONY_SPECIES_KEYWORDS):
        is_pegasus = equine_species_has_wings(species)
        is_unicorn = equine_species_has_horn(species)
        body_parts = ["小马共有的蹄、尾巴、耳朵、鬃毛、身体重心、视线、表情、声音状态"]
        forbidden_parts = []
        if is_pegasus:
            body_parts.append("飞行种族明确拥有的翅膀相关部位")
        else:
            forbidden_parts.append("翅膀")
        if is_unicorn:
            body_parts.append("独角兽明确拥有的角或魔法表现")
        else:
            forbidden_parts.append("角/独角魔法")
        forbidden_parts.append("抬手/伸手/手中/用手/手指/手掌/手腕/手臂/中指等人类手部表达")
        forbidden = (
            "；不要写"
            + "、".join(forbidden_parts)
            if forbidden_parts
            else ""
        )
        species_organ_line = equine_species_prompt_line(species)
        return (
            f"当前角色档案种族：{species}。本轮直接按该种族注入体态规则："
            f"{species_organ_line}"
            f"描写角色身体、动作或感受时，优先使用{'、'.join(body_parts)}等符合该种族体态的表达；"
            "禁止使用不属于该角色种族的身体部位或跨物种肢体比喻"
            f"{forbidden}；需要表达手指/指尖功能时改用蹄尖等表达，需要表达手/手部动作时改用蹄子或前蹄等表达；"
            "普通身体介绍优先列当前角色实际拥有的结构和体态，不主动罗列缺失部位；"
            "只有用户直接询问手、手指、中指或替代写法时，才说明应按蹄类体态理解并给出替代表达；"
            "不确定时改用中性的姿态、视线、表情、声音状态或环境互动。"
        )
    if _description_is_human_species(species):
        return (
            f"当前角色档案种族：{species}。本轮直接按人类体态描写；"
            "可使用符合人类体态的身体部位或中性姿态，不要套用非人类种族的专属部位。"
        )
    return (
        f"当前角色档案种族：{species}。本轮直接按这个种族的设定体态描写；"
        "只使用角色档案或详细设定明确支持的身体结构；不要临时套用人类或小马等其他种族的专属部位。"
    )


def _strip_leading_shortcut_at_mentions(text: str) -> str:
    raw = str(text or "").strip()
    while True:
        new = _LEADING_SHORTCUT_AT_RE.sub("", raw, count=1).strip()
        if new == raw:
            return raw
        raw = new


def _is_description_shortcut_text(text: str) -> bool:
    return _strip_leading_shortcut_at_mentions(text) in _DESCRIPTION_SHORTCUT_PATTERNS


def _is_story_progression_shortcut_text(text: str) -> bool:
    return _strip_leading_shortcut_at_mentions(text) == _STORY_PROGRESSION_SHORTCUT_TEXT


def _description_shortcut_target(text: str) -> str:
    raw = str(text or "")
    if "身体状态" in raw:
        return "身体状态"
    if "看到的画面" in raw:
        return "看到的画面"
    return "心理活动"


def _description_shortcut_focus_guidance(target: str) -> str:
    target = str(target or "").strip() or "心理活动"
    common = (
        "用户明确点名要哪一种描写，就以该内容为主；不要把心理、身体、动作、环境、画面全部混成固定四件套。\n"
        "每个气泡只承载一个同类层次，宁可收束，也不要堆叠多种身体动作、物件、视线和环境细节。\n"
        "发言主体必须按历史消息角色保持：assistant/角色上一轮说过的话仍然是角色自己说的，不能写成用户问过、用户说过、用户牵着角色或用户主动提出；本轮快捷消息只是在请求描写角色此刻状态，不会改变前文发言归属。\n"
        "选项归属也必须保持：若前文是用户问角色“你想 A 还是 B/要选哪个”，随后 assistant/角色回答了某个选项，则该选项是角色自己的选择或偏好，不是用户选择；本轮描写不能写成“用户选择/用户决定/用户让我这样”。\n"
    )
    if target == "心理活动":
        return (
            "【描写内容主轴｜心理活动】\n"
            + common
            + "主内容写角色此刻的念头、判断、犹豫、害怕、压抑、关系理解或自我说服；外显动作/身体反应只作少量锚点。\n"
            "整轮最多使用 1-2 个很短的动作或身体锚点，可用呼吸、视线、姿态、表情或符合角色种族的部位；不要连续堆叠身体动作清单。\n"
            "不要把身体反应清单当成主要内容；这些只能服务于内心变化。\n"
        )
    if target == "身体状态":
        return (
            "【描写内容主轴｜身体状态】\n"
            + common
            + "主内容写身体感觉、姿态、疲惫、紧绷、疼痛、温度、呼吸、重心或肌肉反应；心理只可作为一句背景，不展开成内心独白。\n"
            "不要大段分析关系、回忆、猜测或情绪理由；环境只保留与身体接触有关的必要物件。\n"
        )
    if target == "看到的画面":
        return (
            "【描写内容主轴｜看到的画面】\n"
            + common
            + "主内容写视野里的对象、位置、动作、颜色、遮挡、远近和画面变化；只写看得见的内容。\n"
            "不要写角色看不见的心理推理、身体内部感觉或环境泛化氛围，除非它直接出现在画面里。\n"
        )
    return "【描写内容主轴】\n" + common


def _description_shortcut_stage3_contract(*, character_species: str = "", target: str = "心理活动") -> str:
    return (
        "【描写回合硬性输出合同】\n"
        "本轮是描写回合，不是普通聊天回合；dialogue_allowed=false。\n"
        "最终 bubbles[*].parts 只能写当前角色视角下的描写内容；每个 bubble.parts 只能包含一个非 speech part，不得包含 speech。\n"
        "非 speech part 的 kind 只能从 action/thought/body_state/expression/gaze/voice_state/scene/visual/sensory/emotion 中选择；后端会自动加全角括号。\n"
        "parts[*].text 里不能自己写括号，也不能写角色台词、普通聊天、反问、解释、补充说明、系统说明或“我是不是/你和她/要不要/可以吗”等对用户说出口的话。\n"
        "非 speech part 只能写当前角色的心理活动、身体状态、动作、神态、声音状态或当前画面；不能把准备说出口的话、聊天反问或解释塞进描写里。\n"
        "可以描写角色想说却没有说出口、喉咙发紧、视线停顿、动作迟疑，但不能让角色真的开口发问或推进对话。\n"
        "前文 assistant/角色消息里的“我”指角色自己，“你”指用户；用户本轮快捷请求里的“你”只指定描写对象是当前角色，不能倒改历史发言主体。\n"
        "若前文是用户给出 A/B 选项并询问角色想选哪个，assistant/角色回答某个选项，该选择归属于角色；本轮不得写成用户替角色选择、用户决定或用户让角色选了该项。\n"
        f"{_description_shortcut_focus_guidance(target)}"
        f"{_build_character_species_description_guidance(character_species)}"
    )


def _story_progression_shortcut_guidance() -> str:
    return (
        "【继续下一步｜后续动作素材】\n"
        "用户给出继续下一步信号，不是角色台词、单纯环境描写，也不是要求角色停在原地反问用户。\n"
        "无论角色偏内向还是外向，都必须基于当前已发生事实、角色性格、关系阶段和场景约束，合理推演接下来可能自然出现的事情。\n"
        "回复要让用户直接看到后续一小段世界内进展：必须至少落到一个具体可见的后续事件，例如角色走到某处、拿到/发现某物、打开门、进入某个房间、遇到新阻碍、听见新的动静、完成当前任务的一步，或让第三方角色产生明确反应。\n"
        "可以主动推进数个小节拍，但不得改写既有事实，不得替用户做明确决定、说用户台词或强迫用户动作；用户的反应应留出可接入空间。\n"
        "弱推进不合格：只写“嗯/好/走吧/带路吧/我们走/她迈步/跟上脚步/开始移动”，但没有新的地点、物品、发现、阻碍、任务进展或第三方反应。\n"
        "低证据支线禁入：除非最近真实对话、当前用户消息、场景锚点或角色设定已经出现，不得凭空把当前工作场景切成点餐、咖啡、蛋糕、快递、订单、签收、外卖、新客人、厨房/门口杂务等相邻日常支线；如果需要第三方反应，必须来自当前已在场角色或用户刚点名/刚播种的角色，并服务当前任务。\n"
        "如果上一轮或近几轮角色已经明确提出目标、任务或下一阶段，本轮必须越过原地准备、旧过渡点、重复许可和单纯带路，直接写抵达/进入该目标，或在该目标处开始任务、发现新情况、遇到阻碍或触发第三方反应。若最近证据显示前一任务或旧目标已经完成，并出现新的行动方向，旧任务只能作为历史背景，不得重新写成当前活动。\n"
        "如果现场是当前角色熟悉的地点、住所、家里、房间、店铺、工作地或她刚才明确知道目标位置，必须由当前角色自己带路、自己走向目标、自己指出方向或自己处理下一步；禁止让用户“带路/领路/你带我去/你想往哪边走”。\n"
        "如果上文硬锚说明当前是成人合意亲密场景里的内部继续信号：只有最近对话或当前事实锚已经明确出现高潮、顶峰、释放、余韵或事后，才可以写余韵、安抚、清理、确认感受、抱住休息或温柔收束；否则不要转去睡觉、休息、喝水、吃东西、聊天、散步、换地点、清理、毛巾、热水、厨房、饰品、动物、农场、任务或其他非亲密内容，必须把用户的继续信号当成亲密正反馈，保持当前亲密接触并继续加深到下一层节奏。反复收到继续信号时，每次都要比上一轮更接近当前亲密段落的高点；外向角色可以更快抵达，内向/害羞/温柔角色允许慢热但仍要主动推进。通用压力、第三人、公开场合和隐私边界低于已建立的特殊亲密关系或玩法约定；当前用户明确停止、不适、退出或不要继续时才按退出信号中断。\n"
        "如果当前关系或安全边界不允许某种升级，就把它推进到当前关系阶段允许的具体互动或事件，不要空泛地说“你决定吧/接下来会怎样”。\n"
    )


def _should_emit_json_compat_delta(*, voice_reply_generated: bool) -> bool:
    # JSON normal chat keeps the old OpenAI-style delta for text replies only.
    # Voice replies must arrive through assistant_paragraph so the app can attach audio state.
    return not bool(voice_reply_generated)


def _normalize_normal_reply_dash_style(text: str, *, single_bubble: bool = False) -> str:
    """Normalize Chinese double em-dash turns without touching math/minus signs."""
    raw = str(text or "")
    if not raw:
        return raw

    if single_bubble:
        normalized = re.sub(r"\s*—{2,}\s*", "，", raw)
        normalized = re.sub(r"，{2,}", "，", normalized)
        normalized = re.sub(r"([。！？!?…])，", r"\1", normalized)
        return normalized

    def _paren_depth(segment: str, depth: int) -> int:
        for ch in segment:
            if ch in "（(":
                depth += 1
            elif ch in "）)" and depth > 0:
                depth -= 1
        return depth

    parts: list[str] = []
    depth = 0
    cursor = 0
    for match in re.finditer(r"\s*—{2,}\s*", raw):
        before = raw[cursor:match.start()]
        parts.append(before)
        depth = _paren_depth(before, depth)
        parts.append("，" if depth > 0 else "\n\n")
        depth = _paren_depth(match.group(0), depth)
        cursor = match.end()
    parts.append(raw[cursor:])

    normalized = "".join(parts)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"([。！？!?…])\n\n([。！？!?…])", r"\1\2", normalized)
    normalized = re.sub(r"，{2,}", "，", normalized)
    normalized = re.sub(r"([。！？!?…])，", r"\1", normalized)
    return normalized


def _merge_adjacent_normal_bracket_descriptions(text: str) -> str:
    """Merge immediately adjacent full-bracket description fragments in one bubble."""
    merged = str(text or "")
    if not merged:
        return merged
    previous = None
    while previous != merged:
        previous = merged
        merged = re.sub(r"）[ \t\f\v]*（", "", merged)
        merged = re.sub(r"\)[ \t\f\v]*\(", "", merged)
    return merged


def _sanitize_normal_visible_reply(text: str, *, single_bubble: bool = False) -> str:
    text = sanitize_assistant_close_leading_fullwidth_parens(text)
    parts = re.split(r"(\n+)", text)
    fixed: list[str] = []
    for part in parts:
        if not part or part.startswith("\n"):
            fixed.append(part)
            continue
        opens = part.count("（")
        closes = part.count("）")
        if closes > opens:
            first_open = part.find("（")
            first_close = part.find("）")
            if first_close >= 0 and (first_open < 0 or first_close < first_open):
                left_ws_len = len(part) - len(part.lstrip())
                part = part[:left_ws_len] + "（" + part[left_ws_len:]
        fixed.append(part)
    text = "".join(fixed)
    text = _normalize_normal_reply_dash_style(text, single_bubble=single_bubble)
    return _merge_adjacent_normal_bracket_descriptions(text)


_BRACKET_SEGMENT_RE = re.compile(r"[（(]([^（）()]*)[）)]")
_BRACKET_CHAR_RE = re.compile(r"[（）()]")
_FULL_BRACKET_BUBBLE_RE = re.compile(r"^[（(][^（）()]{1,80}[）)]$")


def _normal_reply_level_from_speech_activity(score: int) -> int:
    score = max(0, min(100, int(score)))
    if score <= 8:
        return 1
    if score <= 35:
        return 2
    if score <= 65:
        return 3
    if score <= 85:
        return 4
    return 5


def _normal_reply_level_from_count(count: int, speech_activity: int | None = None) -> int:
    if speech_activity is not None:
        return _normal_reply_level_from_speech_activity(speech_activity)
    count = max(0, min(6, int(count or 0)))
    if count <= 0:
        return 1
    if count == 1:
        return 3
    if count <= 2:
        return 3
    if count <= 4:
        return 4
    return 5


def _normal_stage3_reply_level_from_planner(planner_result: dict | None) -> int:
    p = planner_result or {}
    if "speech_activity" in p:
        try:
            return _normal_reply_level_from_speech_activity(int(p.get("speech_activity") or 45))
        except Exception:
            return _normal_reply_level_from_speech_activity(45)
    try:
        return _normal_reply_level_from_count(int(p.get("bubble_count") or 1))
    except Exception:
        return _normal_reply_level_from_count(1)


def _normal_stage3_expected_bubble_count(planner_result: dict | None) -> int:
    p = planner_result or {}
    try:
        count = max(1, min(6, int(p.get("bubble_count") or 1)))
    except Exception:
        count = 1

    if "speech_activity" not in p:
        return count

    level = _normal_stage3_reply_level_from_planner(p)
    min_max_by_level = {
        1: (1, 1),
        2: (1, 1),
        3: (1, 2),
        4: (3, 4),
        5: (5, 6),
    }
    min_count, max_count = min_max_by_level.get(level, (1, 2))
    return max(min_count, min(max_count, count))


def _normal_reply_level_label(reply_level: int) -> str:
    return {
        1: "第一档：角色不回复",
        2: "第二档：一个短回复气泡，10字左右；无括号台词，或单独一个短括号动作气泡",
        3: "第三档：一到两个气泡，可选一个短括号描述",
        4: "第四档：三到四个气泡，可选少量括号描述气泡",
        5: "第五档：五到六个气泡，可选更充分但仍克制的括号描述气泡",
    }.get(max(1, min(5, int(reply_level or 3))), "第三档：一到两个气泡，可选一个短括号描述")


def _compact_visible_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", str(text or "")))


def _is_full_bracket_bubble(text: str) -> bool:
    return bool(_FULL_BRACKET_BUBBLE_RE.match(str(text or "").strip()))


def _supportive_low_info_guard_active(planner_result: dict | None) -> bool:
    if not isinstance(planner_result, dict):
        return False
    haystack = "\n".join(
        [
            str(planner_result.get("proactive_seed") or ""),
            str(planner_result.get("expression_policy") or ""),
            "\n".join(str(x or "") for x in (planner_result.get("avoid_contradictions") or [])),
        ]
    )
    return any(marker in haystack for marker in _SUPPORTIVE_LOW_INFO_GUARD_MARKERS)


def _normal_stage3_quote_guard_norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def _normal_stage3_material_has_fragment(source_text: str, fragment: str) -> bool:
    frag = _normal_stage3_quote_guard_norm(fragment)
    if not frag:
        return False
    return frag in _normal_stage3_quote_guard_norm(source_text)


def _normal_stage3_context_window(text: str, start: int, end: int, *, radius: int = 44) -> str:
    raw = str(text or "")
    return raw[max(0, start - radius): min(len(raw), end + radius)]


def _normal_stage3_unsupported_old_quote_or_detail_error(
    bubbles: list[str],
    *,
    source_text: str = "",
) -> str:
    """Reject Step 3 expansions that turn abstract memories into fake old quotes."""
    source = str(source_text or "")
    if not source.strip():
        return ""
    visible = "\n".join(str(x or "") for x in bubbles)
    if not visible.strip():
        return ""

    for match in _NORMAL_STAGE3_OLD_QUOTE_RE.finditer(visible):
        quote = str(match.group(1) or "").strip()
        if not quote or _normal_stage3_material_has_fragment(source, quote):
            continue
        window = _normal_stage3_context_window(visible, match.start(), match.end())
        if _NORMAL_STAGE3_OLD_REFERENCE_RE.search(window):
            return (
                "unsupported_old_quote_or_detail: Step 3 输出了素材中没有的旧事引语 "
                f"{quote[:60]!r}；只能改写为感受/理解，或删除该引语。"
            )

    for term in _NORMAL_STAGE3_HIGH_RISK_UNSUPPORTED_DETAIL_TERMS:
        if term not in visible or _normal_stage3_material_has_fragment(source, term):
            continue
        idx = visible.find(term)
        window = _normal_stage3_context_window(visible, idx, idx + len(term))
        if _NORMAL_STAGE3_OLD_REFERENCE_RE.search(window):
            return (
                "unsupported_old_quote_or_detail: Step 3 输出了素材中没有的旧事细节 "
                f"{term!r}；抽象记忆不能扩写成具体时间、场景或旧话。"
            )

    return ""


def _normal_stage3_safe_old_detail_replacement(content: str) -> str:
    text = str(content or "").strip()
    outside = ""
    if _BRACKET_SEGMENT_RE.search(text):
        outside_parts = [
            part.strip()
            for part in _BRACKET_SEGMENT_RE.sub("\n", text).splitlines()
            if part.strip() and not _NORMAL_STAGE3_NAKED_DESCRIPTION_SIGNAL_RE.search(part)
        ]
        outside = "".join(outside_parts)
    elif not _NORMAL_STAGE3_NAKED_DESCRIPTION_SIGNAL_RE.search(text):
        outside = text
    core = "我把那份甜意收回心口，呼吸轻轻乱了一下"
    return f"（{core}）{outside}".strip()


def _normal_stage3_repair_unsupported_old_quote_or_detail(
    bubbles: list[str],
    *,
    source_text: str = "",
) -> tuple[list[str], list[str]]:
    source = str(source_text or "")
    if not source.strip():
        return bubbles, []
    repaired = list(bubbles)
    warnings: list[str] = []

    for idx, content in enumerate(repaired):
        text = str(content or "")
        changed = False
        for match in list(_NORMAL_STAGE3_OLD_QUOTE_RE.finditer(text)):
            quote = str(match.group(1) or "").strip()
            if not quote or _normal_stage3_material_has_fragment(source, quote):
                continue
            window = _normal_stage3_context_window(text, match.start(), match.end())
            if not _NORMAL_STAGE3_OLD_REFERENCE_RE.search(window):
                continue
            text = text.replace(match.group(0), "那份感觉")
            changed = True
        replacements = {
            "一周年": "以后",
            "半梦半醒": "",
            "嘟囔": "浮起",
            "呢喃": "浮起",
            "那句": "那份",
            "打瞌睡": "靠着休息",
            "裱花袋": "手边的东西",
        }
        for term, replacement in replacements.items():
            if term not in text or _normal_stage3_material_has_fragment(source, term):
                continue
            term_idx = text.find(term)
            window = _normal_stage3_context_window(text, term_idx, term_idx + len(term))
            if _NORMAL_STAGE3_OLD_REFERENCE_RE.search(window):
                text = text.replace(term, replacement)
                changed = True
        text = re.sub(r"说起以后", "想到以后", text)
        text = re.sub(r"那份那份感觉", "那份感觉", text)
        text = re.sub(r"浮起的那份感觉", "浮起的感觉", text)
        if changed:
            check_error = _normal_stage3_unsupported_old_quote_or_detail_error(
                [text],
                source_text=source,
            )
            if check_error:
                text = _normal_stage3_safe_old_detail_replacement(content)
            repaired[idx] = text
            warnings.append(f"第 {idx + 1} 个气泡含素材外旧事/引语，已本地去具体化。")
    return repaired, warnings


def _normal_stage3_repair_description_boundary_text(content: str) -> tuple[str, bool]:
    text = str(content or "").strip()
    if not text:
        return text, False
    segments = _BRACKET_SEGMENT_RE.findall(text)
    outside = _BRACKET_SEGMENT_RE.sub("", text)
    outside = re.sub(r"[（）()]", "", outside).strip()
    if segments and (not outside or not _NORMAL_STAGE3_NAKED_DESCRIPTION_SIGNAL_RE.search(outside)):
        return text, False

    if not segments and _NORMAL_STAGE3_NAKED_DESCRIPTION_SIGNAL_RE.search(text):
        tail_match = _NORMAL_STAGE3_SHORT_DIALOGUE_TAIL_RE.search(text)
        if tail_match:
            tail = str(tail_match.group("tail") or "")
            head = text[: tail_match.start("tail")].strip()
            if head and _NORMAL_STAGE3_NAKED_DESCRIPTION_SIGNAL_RE.search(head):
                return f"（{head.rstrip('，,。.!！?？… ')}）{tail.strip()}", True
        return f"（{text}）", True

    if segments and outside and _NORMAL_STAGE3_NAKED_DESCRIPTION_SIGNAL_RE.search(outside):
        tail_match = _NORMAL_STAGE3_SHORT_DIALOGUE_TAIL_RE.search(outside)
        if tail_match:
            tail = str(tail_match.group("tail") or "").strip()
            head = outside[: tail_match.start("tail")].strip()
            if head:
                replacement = f"（{head.rstrip('，,。.!！?？… ')}）{tail}"
                return _BRACKET_SEGMENT_RE.sub(lambda m: m.group(0), text).replace(outside, replacement), True
        return f"（{outside}）", True
    return text, False


def _normal_stage3_repair_description_boundaries(
    bubbles: list[str],
    *,
    planner_result: dict | None = None,
) -> tuple[list[str], list[str]]:
    if not _planner_requires_full_bracket_description(planner_result):
        return bubbles, []
    repaired: list[str] = []
    warnings: list[str] = []
    for pos, bubble in enumerate(bubbles, start=1):
        fixed, changed = _normal_stage3_repair_description_boundary_text(bubble)
        repaired.append(fixed)
        if changed:
            warnings.append(f"第 {pos} 个气泡含括号外裸描写，已本地包入全角括号。")
    return repaired, warnings


def _normal_stage3_error_requires_retry(error: str) -> bool:
    return bool(str(error or "").strip())


def _normal_stage3_source_text_from_messages(messages: list | None) -> str:
    parts: list[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "")
        if role not in {"system", "user", "assistant"}:
            continue
        content = str(msg.get("content") or "").strip()
        if content:
            parts.append(content)
    return "\n\n".join(parts)


def _normal_stage3_reply_level_violation(
    texts: list[str],
    *,
    reply_level: int,
    action_style: str,
) -> str:
    level = max(1, min(5, int(reply_level or 3)))
    style = str(action_style or "plain_text").strip().lower()
    if style not in {"plain_text", "light_inline", "cinematic"}:
        style = "plain_text"
    if level <= 1:
        return "第一档表示角色不回复，Step 3 不应生成正文。"

    all_segments: list[str] = []
    for pos, text in enumerate(texts, start=1):
        content = str(text or "").strip()
        if _BRACKET_CHAR_RE.search(content):
            segments = _BRACKET_SEGMENT_RE.findall(content)
            if not segments:
                return f"第 {pos} 个气泡含括号但没有完整闭合；括号片段必须完整使用（……）。"
            all_segments.extend(segments)

    if level == 2:
        if len(texts) != 1:
            return "第二档只能输出 1 个短气泡。"
        content = texts[0].strip()
        if _BRACKET_CHAR_RE.search(content):
            if not _is_full_bracket_bubble(content):
                return "第二档若使用括号，只能让整个气泡都是一个短括号动作，例如（我点头），不能混合台词。"
            inner_len = _compact_visible_chars(_BRACKET_SEGMENT_RE.findall(content)[0])
            if inner_len > 20:
                return f"第二档括号动作应很短，当前约 {inner_len} 字；请缩短成一个动作或表情。"
        elif _compact_visible_chars(content) > 30:
            return f"第二档是约 10 字的短回应，当前约 {_compact_visible_chars(content)} 字；请压缩成一句短台词。"
        return ""

    if style == "cinematic":
        max_segments_by_level = {3: 2, 4: 4, 5: 6}
        max_inner_by_level = {3: 60, 4: 90, 5: 120}
    else:
        max_segments_by_level = {3: 1, 4: 2, 5: 3}
        max_inner_by_level = {3: 40, 4: 70, 5: 90}
    max_segments = max_segments_by_level.get(level, 1)
    max_inner = max_inner_by_level.get(level, 40)
    if len(all_segments) > max_segments:
        return f"{_normal_reply_level_label(level)}，括号片段最多 {max_segments} 个，当前为 {len(all_segments)} 个。"
    for seg in all_segments:
        inner_len = _compact_visible_chars(seg)
        if inner_len > max_inner:
            return f"{_normal_reply_level_label(level)}，单个括号描述应不超过 {max_inner} 字，当前约 {inner_len} 字。"
    return ""


def _is_soft_normal_stage3_reply_level_violation(error: str) -> bool:
    text = str(error or "")
    return "括号片段最多" in text or "单个括号描述应不超过" in text


def _loads_normal_stage3_json_object(raw: str) -> dict | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


_STAGE3_JSON_SCAFFOLD_KEY_RE = re.compile(
    r'(?m)^\s*,?\s*"(?:bubble_count|bubbles|index|type|content|purpose|used_facts)"\s*:'
)
_STAGE3_JSON_SCAFFOLD_LINE_RE = re.compile(r"^\s*[\{\}\[\]],?\s*$")
_STAGE3_CONTENT_KEY_RE = re.compile(r'(?m)(?<!\\)"content"\s*:')


def _looks_like_stage3_json_scaffold(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw).strip()
    if _STAGE3_JSON_SCAFFOLD_KEY_RE.search(raw):
        return True
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    scaffold_lines = sum(1 for line in lines if _STAGE3_JSON_SCAFFOLD_LINE_RE.match(line))
    return scaffold_lines >= 2 and any('"' in line and ":" in line for line in lines)


def _extract_stage3_content_fragments_from_json_scaffold(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw).strip()

    decoder = json.JSONDecoder()
    fragments: list[str] = []
    seen: set[str] = set()
    for match in _STAGE3_CONTENT_KEY_RE.finditer(raw):
        idx = match.end()
        while idx < len(raw) and raw[idx].isspace():
            idx += 1
        if idx >= len(raw):
            continue

        value = ""
        if raw[idx] == '"':
            try:
                decoded, _end = decoder.raw_decode(raw[idx:])
                if isinstance(decoded, str):
                    value = decoded
            except Exception:
                line_end = raw.find("\n", idx)
                candidate = raw[idx:] if line_end < 0 else raw[idx:line_end]
                candidate = candidate.strip().rstrip(",").strip()
                if candidate.startswith('"') and candidate.endswith('"'):
                    try:
                        decoded = json.loads(candidate)
                        if isinstance(decoded, str):
                            value = decoded
                    except Exception:
                        value = candidate[1:-1]
        else:
            line_end = raw.find("\n", idx)
            candidate = raw[idx:] if line_end < 0 else raw[idx:line_end]
            value = candidate.strip().rstrip(",").strip()

        value = re.sub(r"[\r\n]+", " ", str(value or "")).strip()
        if value and value not in seen and not _looks_like_stage3_json_scaffold(value):
            seen.add(value)
            fragments.append(value)
    return fragments


def _normal_stage3_clean_field_text(value: Any) -> str:
    return re.sub(r"[\r\n]+", " ", str(value or "")).strip()


def _normal_stage3_strip_bracket_terminal_period(text: str) -> str:
    return re.sub(r"。+$", "", str(text or "").rstrip()).rstrip()


def _normal_stage3_strip_terminal_speech_period(text: str) -> str:
    return re.sub(r"。+$", "", str(text or "").rstrip()).rstrip()


_NORMAL_STAGE3_PART_KINDS: set[str] = {
    "speech",
    "action",
    "thought",
    "body_state",
    "expression",
    "gaze",
    "voice_state",
    "scene",
    "visual",
    "sensory",
    "emotion",
}
_NORMAL_STAGE3_BRACKET_PART_KINDS = _NORMAL_STAGE3_PART_KINDS - {"speech"}


def _normal_stage3_render_parts_bubble(item: dict, pos: int) -> tuple[str, dict[str, Any], str]:
    parts = item.get("parts")
    if not isinstance(parts, list) or not parts:
        return "", {}, f"第 {pos} 个 bubble 必须包含非空 parts 数组；旧 content/bracket_content/speech_content 格式不再接受。"

    rendered_parts: list[str] = []
    kind_counts: dict[str, int] = {}
    speech_chars = 0
    bracket_chars = 0
    for part_pos, part in enumerate(parts, start=1):
        if not isinstance(part, dict):
            return "", {}, f"第 {pos} 个 bubble.parts[{part_pos}] 必须是 object，包含 kind/text。"
        kind = str(part.get("kind") or "").strip().lower()
        if kind not in _NORMAL_STAGE3_PART_KINDS:
            allowed = "/".join(sorted(_NORMAL_STAGE3_PART_KINDS))
            return "", {}, f"第 {pos} 个 bubble.parts[{part_pos}].kind 必须是 {allowed} 之一，当前为 {kind or '空'}。"
        raw_text = str(part.get("text") or "")
        if "\n" in raw_text or "\r" in raw_text:
            return "", {}, f"第 {pos} 个 bubble.parts[{part_pos}].text 内部含换行；每个 part 文本内部不得换行。"
        text = _normal_stage3_clean_field_text(raw_text)
        if not text:
            return "", {}, f"第 {pos} 个 bubble.parts[{part_pos}].text 不能为空。"
        if _BRACKET_CHAR_RE.search(text):
            return "", {}, f"第 {pos} 个 bubble.parts[{part_pos}].text 不得包含括号；后端会根据 kind 统一添加全角括号。"
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if kind == "speech":
            rendered_parts.append(text)
            speech_chars += len(text)
        else:
            text = _normal_stage3_strip_bracket_terminal_period(text)
            if not text:
                return "", {}, f"第 {pos} 个 bubble.parts[{part_pos}].text 去掉括号内句号后不能为空。"
            rendered_parts.append(f"（{text}）")
            bracket_chars += len(text)

    rendered = _merge_adjacent_normal_bracket_descriptions("".join(rendered_parts).strip())
    rendered = _normal_stage3_strip_terminal_speech_period(rendered)
    if not rendered:
        return "", {}, f"第 {pos} 个 bubble.parts 渲染后为空。"
    return rendered, {
        "render_mode": "parts",
        "part_count": len(parts),
        "part_kinds": kind_counts,
        "speech_chars": speech_chars,
        "bracket_chars": bracket_chars,
    }, ""


def _normal_stage3_has_strict_description_contract(source_text: str) -> bool:
    source = str(source_text or "")
    return (
        "【描写回合硬性输出合同】" in source
        and "本轮是描写回合，不是普通聊天回合；dialogue_allowed=false" in source
    )


def _coerce_normal_stage3_bubbles(
    raw: str,
    *,
    expected_count: int,
    action_style: str = "plain_text",
    reply_level: int | None = None,
    planner_result: dict | None = None,
    stage3_source_text: str = "",
) -> tuple[str, dict, str]:
    data = _loads_normal_stage3_json_object(raw)
    if not isinstance(data, dict):
        return "", {}, "Step 3 必须输出 JSON object，格式为 {\"bubble_count\":1,\"bubbles\":[{\"index\":1,\"type\":\"text\",\"parts\":[{\"kind\":\"speech\",\"text\":\"...\"}],\"purpose\":\"answer_user\"}],\"used_facts\":[]}。"

    expected = max(1, min(6, int(expected_count or 1)))
    effective_reply_level = (
        max(1, min(5, int(reply_level)))
        if reply_level is not None
        else _normal_reply_level_from_count(expected)
    )
    try:
        declared_count = int(data.get("bubble_count"))
    except Exception:
        return "", {}, "JSON 中必须包含整数 bubble_count。"
    if declared_count != expected:
        return "", {}, f"bubble_count 必须等于 Step 2 的 {expected}，当前为 {declared_count}。"

    raw_bubbles = data.get("bubbles")
    if not isinstance(raw_bubbles, list):
        return "", {}, "JSON 中必须包含 bubbles 数组。"
    if len(raw_bubbles) != expected:
        return "", {}, f"bubbles 数组必须正好 {expected} 项，当前为 {len(raw_bubbles)} 项。"

    raw_used_facts = data.get("used_facts")
    used_facts = (
        [str(x).strip()[:200] for x in raw_used_facts if str(x or "").strip()]
        if isinstance(raw_used_facts, list)
        else []
    )

    bubbles: list[str] = []
    bubble_meta: list[dict[str, Any]] = []
    strict_description_contract = _normal_stage3_has_strict_description_contract(stage3_source_text)
    for pos, item in enumerate(raw_bubbles, start=1):
        if not isinstance(item, dict):
            return "", {}, f"第 {pos} 个 bubble 必须是 object，包含 index/type/parts/purpose。"
        try:
            index = int(item.get("index"))
        except Exception:
            return "", {}, f"第 {pos} 个 bubble 必须包含整数 index。"
        if index != pos:
            return "", {}, f"bubble index 必须从 1 开始连续；第 {pos} 项当前 index={index}。"
        typ = str(item.get("type") or "").strip().lower()
        if typ != "text":
            return "", {}, f"第 {pos} 个 bubble.type 必须是 text，当前为 {typ or '空'}。"
        text, field_meta, field_error = _normal_stage3_render_parts_bubble(item, pos)
        if field_error:
            return "", {}, field_error
        if strict_description_contract:
            kind_counts = field_meta.get("part_kinds") if isinstance(field_meta, dict) else {}
            if field_meta.get("part_count") != 1 or not isinstance(kind_counts, dict) or kind_counts.get("speech"):
                return "", {}, f"第 {pos} 个 bubble 处于描写回合硬性输出合同，parts 只能包含一个非 speech 描写段。"
        if not text:
            return "", {}, f"第 {pos} 个 bubble.parts 渲染后不能为空。"
        if "\n" in text or "\r" in text:
            return "", {}, f"第 {pos} 个 bubble 可见正文内部含换行；每个数组项就是一个气泡，字符串内部不得换行。"
        text = _normalize_normal_reply_dash_style(text, single_bubble=True).strip()
        purpose = str(item.get("purpose") or "").strip()
        if not purpose:
            return "", {}, f"第 {pos} 个 bubble.purpose 不能为空。"
        bubbles.append(text)
        bubble_meta.append(
            {
                "index": index,
                "type": typ,
                "purpose": purpose[:80],
                "content_chars": len(text),
                **field_meta,
            }
        )

    repair_warnings: list[str] = []
    bubbles, description_repair_warnings = _normal_stage3_repair_description_boundaries(
        bubbles,
        planner_result=planner_result,
    )
    repair_warnings.extend(description_repair_warnings)

    bubbles, old_detail_repair_warnings = _normal_stage3_repair_unsupported_old_quote_or_detail(
        bubbles,
        source_text=stage3_source_text,
    )
    repair_warnings.extend(old_detail_repair_warnings)

    level_error = _normal_stage3_reply_level_violation(
        bubbles,
        reply_level=effective_reply_level,
        action_style=action_style,
    )
    level_warning = ""
    if level_error and _is_soft_normal_stage3_reply_level_violation(level_error):
        level_warning = level_error
    elif level_error:
        return "", {}, level_error

    unsupported_old_quote_error = _normal_stage3_unsupported_old_quote_or_detail_error(
        bubbles,
        source_text=stage3_source_text,
    )
    if unsupported_old_quote_error:
        repair_warnings.append(unsupported_old_quote_error)
        bubbles = [
            _normal_stage3_safe_old_detail_replacement(text)
            if _normal_stage3_unsupported_old_quote_or_detail_error([text], source_text=stage3_source_text)
            else text
            for text in bubbles
        ]
    for idx, text in enumerate(bubbles):
        if idx < len(bubble_meta):
            bubble_meta[idx]["content_chars"] = len(text)

    parsed = {
        "bubble_count": declared_count,
        "reply_level": effective_reply_level,
        "action_style": str(action_style or "plain_text").strip().lower(),
        "bubbles": bubble_meta,
        "used_facts": used_facts,
    }
    if level_warning:
        parsed["reply_level_warning"] = level_warning
    if repair_warnings:
        parsed["local_repairs"] = repair_warnings
    return "\n".join(bubbles), parsed, ""


def _best_effort_normal_stage3_bubbles(
    raw: str,
    *,
    expected_count: int,
) -> tuple[str, dict]:
    expected = max(1, min(6, int(expected_count or 1)))
    data = _loads_normal_stage3_json_object(raw)
    bubbles: list[str] = []
    declared_count = None
    repaired_json_scaffold = False
    if isinstance(data, dict):
        try:
            declared_count = int(data.get("bubble_count"))
        except Exception:
            declared_count = None
        raw_bubbles = data.get("bubbles")
        if isinstance(raw_bubbles, list):
            for pos, item in enumerate(raw_bubbles, start=1):
                if isinstance(item, dict):
                    content, _field_meta, _field_error = _normal_stage3_render_parts_bubble(item, pos)
                else:
                    content = item
                text = re.sub(r"[\r\n]+", " ", str(content or "")).strip()
                if text:
                    bubbles.append(text)
        if not bubbles:
            for key in ("content", "text", "reply", "message"):
                text = re.sub(r"[\r\n]+", " ", str(data.get(key) or "")).strip()
                if text:
                    bubbles.append(text)
                    break

    if not bubbles:
        text = str(raw or "").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
        if text:
            scaffold_like = _looks_like_stage3_json_scaffold(text) or text.startswith(("{", "["))
            if scaffold_like:
                repaired = _extract_stage3_content_fragments_from_json_scaffold(text)
                if repaired:
                    bubbles = repaired
                    repaired_json_scaffold = True
                else:
                    return "", {
                        "best_effort": True,
                        "declared_bubble_count": declared_count,
                        "rendered_bubble_count": 0,
                        "json_scaffold_unrepairable": True,
                    }
            else:
                bubbles = [line.strip() for line in re.split(r"\n+", text) if line.strip()]

    if not bubbles:
        return "", {
            "best_effort": True,
            "declared_bubble_count": declared_count,
            "rendered_bubble_count": 0,
        }

    if expected == 1:
        rendered = [" ".join(bubbles)]
    elif len(bubbles) > expected:
        rendered = bubbles[: expected - 1] + [" ".join(bubbles[expected - 1 :])]
    else:
        rendered = bubbles
    meta = {
        "best_effort": True,
        "declared_bubble_count": declared_count,
        "rendered_bubble_count": len(rendered),
    }
    if repaired_json_scaffold:
        meta["json_scaffold_repaired"] = True
    return "\n".join(rendered), meta


def _normal_stage3_handoff_candidates(request, *, current_character_id: str = "") -> list[dict[str, str]]:
    current_character_id = str(current_character_id or "").strip()
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(cid: str, name: str, role: str) -> None:
        cid = str(cid or "").strip()
        name = str(name or "").strip()
        if not cid or cid == current_character_id or cid in seen:
            return
        seen.add(cid)
        candidates.append(
            {
                "reply_character_id": cid,
                "name": name or cid,
                "role": role,
            }
        )

    add(main_character_id(request), main_display_name(request), "main")
    for msg in getattr(request, "messages", None) or []:
        if getattr(msg, "role", None) != "assistant":
            continue
        sid = str(getattr(msg, "speaker_character_id", "") or "").strip() or main_character_id(request)
        sname = str(getattr(msg, "speaker_name", "") or "").strip()
        add(sid, sname or (main_display_name(request) if sid == main_character_id(request) else sid), "recent_speaker")
    return candidates[:6]


def _normal_handoff_message_visible(msg) -> bool:
    if getattr(msg, "isHidden", False):
        return False
    try:
        if is_summary_placeholder_message(msg):
            return False
    except Exception:
        pass
    return getattr(msg, "role", None) in {"user", "assistant"}


def _normal_handoff_speaker_id_for_message(request, msg) -> str:
    if getattr(msg, "role", None) != "assistant":
        return ""
    return str(getattr(msg, "speaker_character_id", "") or "").strip() or main_character_id(request)
