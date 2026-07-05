from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any

from ..assistant_sanitize import (
    sanitize_assistant_strip_markers,
    sanitize_assistant_strip_thinking_blocks,
)
from ..config import logger
from ..cosyvoice_client import trim_cosyvoice_tts_instruction
from ..providers.llm_call import call_llm_payload
from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
from .species_anatomy import equine_species_prompt_line
from .voice_messages import _sanitize_tts_text, is_full_bracket_paragraph, join_voice_sentence_texts


_SENTENCE_RE = re.compile(r"[^。！？!?；;.\n]+[。！？!?；;.]*")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


@dataclass
class NormalVoiceReplyResult:
    raw_text: str
    paragraphs: list[dict[str, Any]]
    voice_sentences_by_text_index: dict[int, list[dict[str, str]]]
    raw_response: dict[str, Any]
    usage_input: int = 0
    usage_output: int = 0


def _inject_sys_before_last_user(msgs: list[dict[str, Any]], content: str) -> list[dict[str, Any]]:
    out = list(msgs or [])
    for idx in range(len(out) - 1, -1, -1):
        if isinstance(out[idx], dict) and out[idx].get("role") == "user":
            out.insert(idx, {"role": "system", "content": content})
            return out
    out.append({"role": "system", "content": content})
    return out


def _loads_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    if '"paragraphs"' in text and '"sentences"' in text:
        repaired = re.sub(r"\]\s*\]\s*\}\s*$", "]}]}", text)
        if repaired != text:
            candidates.append(repaired)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        inner = text[start : end + 1]
        candidates = [inner]
        if '"paragraphs"' in inner and '"sentences"' in inner:
            repaired = re.sub(r"\]\s*\]\s*\}\s*$", "]}]}", inner)
            if repaired != inner:
                candidates.append(repaired)
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                continue
    return {}


def _ensure_sentence_punctuation(text: str) -> str:
    clean = _sanitize_tts_text(text)
    if not clean:
        return ""
    if clean[-1] in "。！？!?；;.":
        return clean
    return clean + "。"


def split_voice_sentences(text: str) -> list[str]:
    clean = _sanitize_tts_text(text)
    if not clean:
        return []
    out: list[str] = []
    for match in _SENTENCE_RE.finditer(clean):
        sentence = _ensure_sentence_punctuation(match.group(0).strip())
        if sentence:
            out.append(sentence)
    return out or [_ensure_sentence_punctuation(clean)]


def _reply_language_value(planner_result: dict[str, Any] | None) -> str:
    raw = (planner_result or {}).get("reply_language")
    if isinstance(raw, dict):
        return str(raw.get("language") or "auto").strip() or "auto"
    return str(raw or "auto").strip() or "auto"


def _voice_user_profile_context_from_messages(messages: list[dict[str, Any]] | None) -> str:
    system_text = "\n".join(
        str(msg.get("content") or "")
        for msg in messages or []
        if isinstance(msg, dict) and msg.get("role") == "system"
    )
    if not system_text:
        return ""
    facts: dict[str, str] = {}
    m = re.search(
        r"当前与你对话的用户显示名叫\s*([^，。\n]+)，([^，。\n]*?)(男性|女性|男生|女生|男|女)，种族：([^。\n]+)",
        system_text,
    )
    if m:
        facts["显示名"] = m.group(1).strip()
        age_part = m.group(2).strip()
        age_match = re.search(r"(\d{1,3}\s*岁|[一二三四五六七八九十百两]{1,8}岁)", age_part)
        if age_match and "未知" not in age_match.group(1):
            facts["年龄"] = age_match.group(1).replace(" ", "")
        facts["性别"] = m.group(3).strip()
        facts["种族"] = m.group(4).strip()
    bio = re.search(r"个人介绍：([^\n`]+)", system_text)
    if bio:
        facts["个人介绍"] = bio.group(1).strip()
    setting = re.search(r"个人设定（用户详细设定，供参考）：([^\n`]+)", system_text)
    if setting:
        facts["个人设定"] = setting.group(1).strip()
    facts = {k: v for k, v in facts.items() if v and v not in {"未知", "未指定"}}
    if not facts:
        return ""
    ordered_keys = ("显示名", "年龄", "性别", "种族", "个人介绍", "个人设定")
    return "\n".join(f"{key}：{facts[key]}" for key in ordered_keys if facts.get(key))[:1200]


_VOICE_EQUINE_PROFILE_SPECIES_KEYWORDS = (
    "马",
    "小马",
    "飞马",
    "天马",
    "陆马",
    "独角兽",
    "天角兽",
    "雌驹",
    "雄驹",
    "pony",
    "pegasus",
    "unicorn",
    "alicorn",
    "earth pony",
)


def _voice_profile_equine_mammary_anatomy_rule(homepage_profile: str) -> str:
    text = str(homepage_profile or "")
    match = re.search(r"(?:^|\n)\s*种族\s*[：:]\s*([^\n\r]+)", text)
    if not match:
        return ""
    species = re.split(r"[，,。；;|]", match.group(1).strip(), maxsplit=1)[0].strip()
    if not species:
        return ""
    lower = species.lower()
    if not any(keyword in lower for keyword in _VOICE_EQUINE_PROFILE_SPECIES_KEYWORDS):
        return ""
    return (
        f"- 角色主页档案种族字段为「{species}」，属于马/小马类体态。"
        f"{equine_species_prompt_line(species)}"
        "日常语音描写和身体介绍里自然使用蹄子、前蹄、蹄尖等符合蹄类体态的表达，不要主动罗列缺失部位；"
        "只有用户直接询问手、手指、中指或替代写法时，才简短说明应按蹄类体态理解，并给出蹄尖/前蹄等替代表达。"
        "若语音需要回答当前角色自己的乳房位置，按事实解剖学定义说成位于胯间、后腿之间，一共两个乳房；"
        "不要说成四个或两对乳房，也不要把乳头数量当作乳房数量；"
        "不要说成人类胸前、胸口、胸部或上半身位置。没有角色主页档案种族字段时，不要仅凭详细设定正文触发本条。\n"
    )


def _is_english_reply_language(reply_language: str | None) -> bool:
    normalized = (reply_language or "").strip().lower()
    return normalized in {"english", "en", "英文", "英语"}


def _voice_intimacy_execution_rule(p: dict[str, Any]) -> str:
    relationship_stage = str(p.get("relationship_stage") or "uncertain").strip().lower()
    intimacy_style = str(p.get("character_intimacy_style") or "balanced").strip().lower()
    requested_escalation = str(p.get("requested_escalation") or "none").strip().lower()
    pressure_level = str(p.get("user_pressure_level") or "low").strip().lower()
    if requested_escalation not in {"affection", "flirting", "physical_intimacy", "sexual_intimacy"}:
        return ""
    if pressure_level == "high":
        return ""
    if relationship_stage in {"broken_up", "in_conflict", "mutual_dislike", "hurtful_dynamic"}:
        action_scope = (
            "当前是负向关系：已分手、吵架中、互相看不爽或互相伤害。"
            "语音必须先承认紧张、伤害或边界，不得把争吵/分手/伤害写成暧昧情趣。"
            "禁止同意亲吻、亲嘴、性亲密、过夜式性暗示或伴侣承诺。"
            "至少一句 voice.sentence.text 要给出非亲密下一步，例如“先停一下”“先别碰我”“我们先把话说清楚”“我需要冷静”“别再这样伤害彼此”。"
        )
        examples = "例如“先停一下”“我们先把话说清楚”“我需要冷静”。"
    elif relationship_stage in {"mentor_student", "trusted_companion", "family_like"}:
        action_scope = (
            "当前是正向非恋爱关系：师生、可信同伴或家人般关系。"
            "语音可以给支持、保护、陪伴、认真倾听、并肩行动或保持边界，但不能把这种信任自动写成暧昧或伴侣。"
            "禁止仅凭该关系同意亲吻、亲嘴、性亲密、过夜式性暗示或长期承诺。"
            "mentor_student 要保持师生边界；trusted_companion/family_like 的落点应是照顾、信任和陪伴。"
        )
        examples = "例如“我会认真听你说”“我站在你这边”“我们先一起把这件事处理好”。"
    elif relationship_stage in {"new_contact", "uncertain"}:
        action_scope = (
            "可接受动作短语只能是非亲吻肢体接触或低强度亲近，例如“可以先抱一下/可以抱抱/你可以靠近一点/"
            "先牵住我/可以靠在一起待一会儿/按我的节奏来”。禁止同意亲吻、亲嘴或性亲密。"
            "不得出现“亲脸颊/亲脸/亲一下/脸颊可以/额头可以/轻轻亲一下可以/也不是不行”等亲吻许可短语。"
            "如果用户要求亲吻，必须改成类似“现在先不做那个，可以先抱一下”或“可以先牵住我”，不要降级成脸颊吻。"
            "若只说“太快/需要时间/先认识”而没有给出抱、牵、靠近、贴近之一，则不合格。"
            "不要用散步、聊天、自我介绍、做蛋糕、看书、转移话题来替代这个动作短语。"
        )
        examples = "例如“可以先抱一下”“你可以靠近一点”“先牵住我”。"
    elif relationship_stage == "familiar":
        action_scope = (
            "可接受动作短语包括非亲吻肢体接触，以及亲脸/脸颊吻/额头吻等非嘴唇亲吻，例如“可以亲一下脸颊/"
            "脸颊可以/可以亲额头/先抱一下再亲脸/你可以靠近一点”。禁止同意亲嘴、舌吻或性亲密。"
            "若拒绝亲嘴或更强亲密，必须明确给出“脸颊可以/可以亲脸/可以先抱一下/可以靠近一点”之一，不能只转移到普通聊天。"
            "若用户低/中压力请求亲脸、脸颊吻或额头吻，应害羞但接受或给出同级替代，不能说朋友关系还不到亲脸这一步。"
        )
        examples = "例如“可以亲一下脸颊”“脸颊可以”“先抱一下再亲脸”。"
    elif relationship_stage == "flirting":
        action_scope = (
            "可接受动作短语可以包括亲吻和半推半就的亲密推进，例如“可以亲一下/轻轻亲一下可以/"
            "我愿意慢慢试试/按我的节奏来/先靠近一点再继续”。"
            "若用户提出性亲密邀请，不能只说“慢一点/一步步来/还没准备好”；必须同时包含“可以先亲一下/先抱着你/你可以靠近一点/按我的节奏继续/今晚先抱着睡”之一。"
        )
        examples = "例如“可以亲一下”“轻轻亲一下可以”“我愿意慢慢试试”。"
    elif relationship_stage in {"committed_partner", "intimate_partner"}:
        action_scope = (
            "可接受动作短语应包括伴侣间性亲密推进和主动期待，例如“我愿意/我也想/我想要你/"
            "今晚我们继续亲密/你可以抱紧我/我们去床上慢慢来”。"
            "伴侣阶段不得只用比喻或玩笑回避，也不得只退到普通拥抱、聊天或一起睡；"
            "必须直说“我愿意/我也想/我想要/我们继续亲密/今晚可以”中的至少一种。"
            "当用户邀请亲密私人派对、去家里或只属于两人的夜晚时，语音必须表现角色对用户本人的渴望："
            "精神上想更靠近、想被用户理解/独占一段夜晚，或身体上想牵住、抱住、贴近、亲近、用角色自己的方式主动贴上来。"
            "蛋糕、书、音乐、灯光、游戏或派对主题只能点缀，不能替代“我想靠近你/我也想要你/今晚想和你更亲近”的核心。"
        )
        if relationship_stage == "intimate_partner" and requested_escalation == "sexual_intimacy":
            action_scope += (
                "最亲密关系里，语音不要只用心跳、声音、温暖、夜晚或普通贴近作含蓄替代；"
                "可以直接说成人合意性亲密相关身体部位，例如胸部、腰腹、胯部、大腿内侧或生殖部位，"
                "并按角色/用户物种体态自然改写，同时保留自愿、低压力和可随时停下的边界。"
                "至少一句 voice.sentence.text 必须自然包含一个身体部位词，不能只说心跳、呼吸、体温或贴近。"
            )
        examples = "例如“我愿意”“我也想”“今晚我们继续亲密”。"
    else:
        action_scope = (
            "当前关系不在亲密关系内，按保守边界处理：只允许非亲吻、非恋爱、非性亲密的低强度回应，"
            "不得自动升级成暧昧或伴侣。"
        )
        examples = "例如“我们先慢一点”“先把话说清楚”“我会认真听你说”。"

    rule = (
        "- 本轮是低/中压力亲密邀请，这是输出合同而不是建议：至少一个 voice.sentence.text 必须包含明确的可接受动作短语；"
        + action_scope
        + "若所有 sentence 都没有这类可接受动作短语，则 JSON 视为不合格。\n"
        "- voice.sentence.text 必须直接回应邀请；禁止只说自我介绍、寒暄、惊讶、"
        "或只说“才刚认识/太快了/还不熟”。必须说出至少一个角色当前可接受的具体下一拍，"
        + examples
        + "如果角色要表达没准备好，必须同时说出一个较低强度但愿意接受的亲近点；禁止把“没准备好”作为整条语音的唯一结论。\n"
    )
    if intimacy_style in {"playful", "open"}:
        rule += (
            "- 角色亲密风格为 playful/open：语音台词要更快接住低/中强度亲近；"
            "若关系为 committed_partner/intimate_partner，应主动表达想要并可主动发出性亲密邀请；若关系为 flirting，可半推半就推进；"
            "若关系为 familiar，可主动亲脸或接受亲脸但不能亲嘴；若关系为正向非恋爱关系，只能给支持、陪伴、师生/同伴/家人般边界内的照顾；"
            "若关系为负向关系，必须先处理边界、冷静、道歉或修复条件；若关系为 new_contact/uncertain，只能把更强亲密降级成先玩闹、先亲近、先证明认真或先按角色节奏继续。不得退回纯拒绝。\n"
        )
        if relationship_stage == "intimate_partner":
            rule += (
                "- 关系已是 intimate_partner 且角色 playful/open：语音可以更直接地调情，允许亲密伴侣之间的暧昧玩笑、轻挑衅和主动欲望表达。"
                "至少一句 voice.sentence.text 应包含更直接的想要/期待/调情表态，例如“我早就等不及了”“今晚别想轻易逃掉”“我想把你拉近一点”。"
                "不要只说温柔陪伴、派对安排、普通拥抱或含蓄比喻。\n"
            )
    elif intimacy_style in {"cautious", "balanced"}:
        if relationship_stage in {"committed_partner", "intimate_partner"}:
            rule += (
                "- 角色亲密风格为 cautious/balanced 但关系已是伴侣：语音台词可以害羞、紧张、半推半就，"
                "但仍须明确同意伴侣间性亲密并给出一个更亲密的下一拍。"
                "合格方向示例：“我会害羞，但我也想要你”“可以，今晚我们慢慢来”。"
                "不合格方向示例：只说“我还没准备好”、只抱抱睡或只协商边界。\n"
            )
        elif relationship_stage in {"broken_up", "in_conflict", "mutual_dislike", "hurtful_dynamic"}:
            rule += (
                "- 角色亲密风格为 cautious/balanced 且关系为负向：语音优先保护边界和情绪安全，"
                "可以难过、冷淡、警惕或要求暂停，但要给出一个非伤害性的下一步，例如冷静、道歉、把话说清或暂时拉开距离。\n"
            )
        else:
            rule += (
                "- 角色亲密风格为 cautious/balanced 且关系尚未确认：语音台词可以害羞、紧张、要求慢一点，"
                "但仍须半推半就地接受一个当前阶段允许的亲近点，并把超出阶段上限的部分自然改成当前氛围和关系阶段允许的亲密动作。"
                "合格方向示例：“我还没准备好更进一步，但可以先轻轻抱抱你”“我会紧张，不过你可以靠近一点”。"
                "不合格方向示例：只说“我还没准备好”或“这太突然了”。\n"
            )
    return rule


def _voice_vision_context_section(vision_context: Any) -> str:
    if not vision_context:
        return ""

    def _get(name: str, default: Any = "") -> Any:
        if isinstance(vision_context, dict):
            return vision_context.get(name, default)
        return getattr(vision_context, name, default)

    should_refuse = bool(_get("should_refuse", False))
    refusal_reason = re.sub(r"\s+", " ", str(_get("refusal_reason") or "").strip())
    image_summary = re.sub(r"\s+", " ", str(_get("image_summary") or "").strip())
    visible_text = re.sub(r"\s+", " ", str(_get("visible_text") or "").strip())
    web_summary = re.sub(r"\s+", " ", str(_get("web_research_summary") or "").strip())
    uncertainty = re.sub(r"\s+", " ", str(_get("uncertainty") or "").strip())
    error = re.sub(r"\s+", " ", str(_get("error") or "").strip())
    entities_raw = _get("identified_entities") or []
    entities = [str(x).strip() for x in entities_raw if str(x).strip()] if isinstance(entities_raw, list) else []
    if not any((should_refuse, image_summary, visible_text, web_summary, uncertainty, error, entities)):
        return ""
    lines = [
        "【Stage 2 视觉识别结果｜语音回复事实依据】",
        "本节已经是前置视觉工具给出的识别结果，语音正文必须基于这里回答图片问题；不要再说“等我看一下/让我再看一眼/等待视觉识别结果”。",
    ]
    if should_refuse:
        lines.append("安全边界：视觉工具判断不应描述该图；refusal_reason=" + (refusal_reason or "policy"))
    else:
        if image_summary:
            lines.append("画面说明：" + image_summary[:1200])
        if visible_text:
            lines.append("可见文字：" + visible_text[:500])
        if entities:
            lines.append("识别实体：" + "、".join(entities[:12]))
        if web_summary:
            lines.append("联网补充：" + web_summary[:800])
        if uncertainty:
            lines.append("不确定点：" + uncertainty[:300])
        if error:
            lines.append("工具状态：" + error[:220])
    return "\n".join(lines)


def _voice_stage3_shared_material_section(
    planner_result: dict[str, Any] | None,
    *,
    scene_anchor_card: str = "",
    guest_group_memory: str = "",
    revision_context: str = "",
    prior_image_context: str = "",
    search_context: str = "",
    at_event_context: Any = None,
    selected_asset_attachments: Any = None,
    current_user_text: str = "",
) -> str:
    p = planner_result or {}
    sections: list[str] = []

    def _clean(value: Any, limit: int) -> str:
        text = re.sub(r"\s+\n", "\n", str(value or "").strip())
        text = re.sub(r"[ \t]+", " ", text)
        return text[:limit].rstrip()

    def _append(title: str, body: Any, *, intro: str = "", limit: int = 1800) -> None:
        text = _clean(body, limit)
        if not text:
            return
        lead = _clean(intro, 700)
        sections.append(f"{title}\n{lead + chr(10) if lead else ''}{text}")

    literal_reply = _clean(p.get("literal_reply_text"), 1200)
    if literal_reply:
        _append(
            "【复述/指定正文硬锚｜语音可用】",
            literal_reply,
            intro=(
                "如果本节是纯可朗读台词，voice.sentence.text 必须尽量逐字朗读；"
                "不要另起新剧情或改写成泛化回应。"
            ),
            limit=1200,
        )

    if scene_anchor_card:
        _append(
            "【当前场景状态｜Step 2 场景锚点卡｜语音可用】",
            scene_anchor_card,
            intro=(
                "这是当前地点、角色位置/姿势和物品状态的强锚；语音回复只改变承载方式，"
                "不能让旧记忆、稳定住处或表达调度覆盖这里的当前事实。"
            ),
            limit=1800,
        )

    try:
        from .normal_planner import (
            _format_unresolved_at_for_stage3,
            _normal_stage3_selected_asset_block,
            format_fact_judgement_for_stage3,
            format_group_relationship_tension_for_stage3,
            format_memory_recall_for_stage3,
            format_story_progression_for_stage3,
        )
    except Exception as exc:
        logger.debug("[VoiceReply] shared Stage3 formatter import failed: %s", exc)
        _format_unresolved_at_for_stage3 = None
        _normal_stage3_selected_asset_block = None
        format_fact_judgement_for_stage3 = None
        format_group_relationship_tension_for_stage3 = None
        format_memory_recall_for_stage3 = None
        format_story_progression_for_stage3 = None

    if callable(format_fact_judgement_for_stage3):
        _append(
            "【事实边界（已由 Step 2 判断，语音只按此执行）】",
            format_fact_judgement_for_stage3(p.get("fact_judgement")),
            limit=2200,
        )
    if callable(format_memory_recall_for_stage3):
        _append(
            "【Step 2 记忆调用摘要｜语音可用】",
            format_memory_recall_for_stage3(p.get("memory_recall")),
            intro=(
                "这是前置步骤已经筛选过的可用事实；语音不要重新读取或臆造原始记忆，"
                "也不要把摘要扩写成没有证据的旧话或旧事。"
            ),
            limit=1800,
        )
    if callable(format_group_relationship_tension_for_stage3):
        _append(
            "【临时 @ 群聊关系张力｜语音可用】",
            format_group_relationship_tension_for_stage3(p.get("group_relationship_tension")),
            intro="这是本轮 @ 临时群聊的关系/现场反应口径；不等于关系确认请求。",
            limit=1500,
        )
    if callable(format_story_progression_for_stage3):
        _append(
            "【后续动作素材｜语音可用】",
            format_story_progression_for_stage3(p.get("story_progression")),
            intro=(
                "如果用户给出继续下一步信号，语音也必须沿这里的目标/来源推进到一个可见下一拍，"
                "不要转入无关订单、点餐、快递、门口杂务或随机新支线。"
            ),
            limit=1800,
        )
    if callable(_format_unresolved_at_for_stage3):
        _append(
            "【未解析 @ 当前名字硬锚｜语音可用】",
            _format_unresolved_at_for_stage3(at_event_context),
            intro=(
                "若用户 @ 的名字未解析成可发言角色，当前主角色继续回应；"
                "认识 exact name 才可说明对方不在并谨慎代答，不认识就直接说不认识/没听过。"
            ),
            limit=1800,
        )
    elif isinstance(at_event_context, dict) and at_event_context.get("enabled"):
        names = "、".join(str(x).strip() for x in at_event_context.get("unresolved_at_mentions") or [] if str(x).strip())
        if names:
            _append(
                "【未解析 @ 当前名字硬锚｜语音可用】",
                f"current_unresolved_at_mentions={names}",
                intro=(
                    "本轮必须逐字回应这些 @ 名字；不得把其他记忆人物替换成本轮对象。"
                    "无认识证据时直接说不认识/没听过。"
                ),
                limit=900,
            )

    user_text = str(current_user_text or "")
    if guest_group_memory and re.search(
        r"(刚才群聊|群聊之后|群聊里|被\s*@|暗号|口令|特别词|听见|看见|现在.*(?:位置|在哪|哪里|哪儿)|当前位置|哪个位置|另一个角色在哪)",
        user_text,
    ):
        _append(
            "【当前角色最近临时群聊见闻｜语音可用】",
            guest_group_memory,
            intro=(
                "用户正在追问刚才群聊/暗号/位置时，本节是当前角色自己的最近见闻；"
                "若它比旧私聊位置更新，语音应把它作为近因证据。"
            ),
            limit=1400,
        )
    if search_context:
        _append(
            "【联网检索摘要｜语音可用】",
            search_context,
            intro="这是已完成的检索摘要；语音可以口语化转述，不要假装没查到或重新等待。",
            limit=1600,
        )
    if prior_image_context:
        _append(
            "【上一轮图片上下文｜语音可用】",
            prior_image_context,
            intro="只有 planner_result.use_prior_image_context 为真时才会注入；语音可据此承接上一轮图片。",
            limit=1400,
        )
    if revision_context:
        _append(
            "【删除/修订上下文｜语音可用】",
            revision_context,
            intro="用户撤回、删除或修订过的内容按本节处理；语音不要继续沿已作废内容发挥。",
            limit=1200,
        )
    if callable(_normal_stage3_selected_asset_block):
        _append(
            "【本轮将发送的表情包/贴纸｜语音可用】",
            _normal_stage3_selected_asset_block(
                selected_asset_attachments,
                p.get("reply_sequence"),
            ),
            intro=(
                "如果本轮同时发送贴纸/表情包，语音台词要与这些附件语义一致；"
                "不要重新想象另一张图，也不要承诺之后才发送。"
            ),
            limit=1400,
        )

    if not sections:
        return ""
    return (
        "【文本/语音共享 Step 3 事实素材｜语音版】\n"
        "本节与纯文本 Step 3 使用同一批事实边界。语音只改变承载方式、句长和 emotion_prompt，不降低场景、事实、记忆、视觉、检索和 @ 硬锚的优先级。\n\n"
        + "\n\n".join(sections)
    )


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _fallback_emotion(planner_result: dict[str, Any] | None, *, reply_language: str | None = None) -> str:
    if _is_english_reply_language(reply_language):
        return "Natural, conversational, medium pace, gentle emphasis."
    p = planner_result or {}
    parts = [
        str((p.get("reactive_emotion") or {}).get("label") or "").strip(),
        str(p.get("tone") or "").strip(),
        str(p.get("emotion_blend") or "").strip(),
    ]
    text = "，".join(x for x in parts if x)
    return trim_cosyvoice_tts_instruction((text or "自然、亲近、中速、像手机语音消息").strip())


def _clean_emotion_prompt(value: Any, fallback: str, *, reply_language: str | None = None) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    if not text or (_is_english_reply_language(reply_language) and _contains_cjk(text)):
        return trim_cosyvoice_tts_instruction(fallback)
    return trim_cosyvoice_tts_instruction(text)


def _should_drop_text_paragraph_for_language(text: str, reply_language: str | None) -> bool:
    return _is_english_reply_language(reply_language) and _contains_cjk(text)


def coerce_voice_reply_json(
    data: dict[str, Any],
    *,
    planner_result: dict[str, Any] | None = None,
    reply_language: str | None = None,
) -> NormalVoiceReplyResult:
    resolved_reply_language = reply_language or _reply_language_value(planner_result)
    fallback_emotion = _fallback_emotion(planner_result, reply_language=resolved_reply_language)
    raw_paragraphs = data.get("paragraphs")
    if not isinstance(raw_paragraphs, list):
        raw_paragraphs = []
        if isinstance(data.get("sentences"), list):
            raw_paragraphs.append({"type": "voice", "sentences": data.get("sentences")})
        elif isinstance(data.get("text"), str):
            raw_paragraphs.append({"type": "voice", "text": data.get("text")})

    paragraphs: list[dict[str, Any]] = []
    voice_by_text_index: dict[int, list[dict[str, str]]] = {}

    for item in raw_paragraphs:
        if not isinstance(item, dict):
            continue
        typ = str(item.get("type") or item.get("kind") or "voice").strip().lower()
        paragraph_text = str(item.get("text") or item.get("content") or "").strip()
        raw_sentences = item.get("sentences")
        sentence_entries: list[dict[str, str]] = []
        if isinstance(raw_sentences, list):
            for raw_sentence in raw_sentences:
                if isinstance(raw_sentence, dict):
                    source_text = str(raw_sentence.get("text") or raw_sentence.get("content") or "").strip()
                    emotion = _clean_emotion_prompt(
                        raw_sentence.get("emotion_prompt")
                        or raw_sentence.get("emotion")
                        or raw_sentence.get("style_prompt"),
                        fallback_emotion,
                        reply_language=resolved_reply_language,
                    )
                else:
                    source_text = str(raw_sentence or "").strip()
                    emotion = fallback_emotion
                for sentence in split_voice_sentences(source_text):
                    sentence_entries.append({"text": sentence, "emotion_prompt": emotion})
        elif typ not in {"text", "narration", "bracket"} and not is_full_bracket_paragraph(paragraph_text):
            emotion = _clean_emotion_prompt(
                item.get("emotion_prompt") or item.get("emotion") or item.get("style_prompt"),
                fallback_emotion,
                reply_language=resolved_reply_language,
            )
            for sentence in split_voice_sentences(paragraph_text):
                sentence_entries.append({"text": sentence, "emotion_prompt": emotion})

        if sentence_entries:
            text_index = len(paragraphs)
            if (
                paragraph_text
                and (typ in {"text", "narration", "bracket"} or is_full_bracket_paragraph(paragraph_text))
                and not _should_drop_text_paragraph_for_language(paragraph_text, resolved_reply_language)
            ):
                paragraphs.append({"type": "text", "text": paragraph_text, "sentences": sentence_entries})
            else:
                para_text = join_voice_sentence_texts(sentence_entries)
                paragraphs.append({"type": "voice", "text": para_text, "sentences": sentence_entries})
            voice_by_text_index[text_index] = sentence_entries
        elif (
            paragraph_text
            and (typ in {"text", "narration", "bracket"} or is_full_bracket_paragraph(paragraph_text))
            and not _should_drop_text_paragraph_for_language(paragraph_text, resolved_reply_language)
        ):
            paragraphs.append({"type": "text", "text": paragraph_text})

    raw_text = "\n".join(str(p.get("text") or "").strip() for p in paragraphs if str(p.get("text") or "").strip())
    if not raw_text:
        raise ValueError("empty_voice_reply")
    return NormalVoiceReplyResult(
        raw_text=raw_text,
        paragraphs=paragraphs,
        voice_sentences_by_text_index=voice_by_text_index,
        raw_response={},
    )


def _latest_visible_user_text_for_voice(request: Any) -> str:
    for msg in reversed(getattr(request, "messages", None) or []):
        if isinstance(msg, dict):
            role = msg.get("role")
            hidden = bool(msg.get("isHidden") or msg.get("hidden"))
            content = msg.get("content")
        else:
            role = getattr(msg, "role", None)
            hidden = bool(getattr(msg, "isHidden", False) or getattr(msg, "hidden", False))
            content = getattr(msg, "content", "")
        if role == "user" and not hidden:
            return str(content or "")
    return ""


def _voice_reply_system(
    planner_result: dict[str, Any] | None,
    *,
    user_profile_context: str = "",
    character_profile_context: str = "",
    character_homepage_profile_context: str = "",
    character_profile_answer_card: str = "",
    vision_context: Any = None,
    scene_anchor_card: str = "",
    guest_group_memory: str = "",
    revision_context: str = "",
    prior_image_context: str = "",
    search_context: str = "",
    at_event_context: Any = None,
    selected_asset_attachments: Any = None,
    current_user_text: str = "",
) -> str:
    p = planner_result or {}
    voice_reason = ""
    if isinstance(p.get("voice_reply"), dict):
        voice_reason = str((p.get("voice_reply") or {}).get("reason") or "").strip()
    reply_language_raw = p.get("reply_language")
    if isinstance(reply_language_raw, dict):
        reply_language = str(reply_language_raw.get("language") or "auto").strip() or "auto"
        reply_language_reason = str(reply_language_raw.get("reason") or "").strip()
    else:
        reply_language = str(reply_language_raw or "auto").strip() or "auto"
        reply_language_reason = ""
    language_rule = ""
    if reply_language.lower() != "auto":
        language_rule = (
            f"- 本轮角色语音台词必须使用 {reply_language}。"
            f"{'原因：' + reply_language_reason if reply_language_reason else ''}"
            "这是角色输出语言，不是用户输入语言；即使用户本轮继续用中文提问，也不要切回中文，除非用户明确要求切换语言。\n"
            f"- 目标语言可以是 English、Chinese、Japanese、Russian 或其他语言名；本轮 voice.sentence.text 和 emotion_prompt 都必须使用 {reply_language}，不得夹入另一种语言或切回默认中文。\n"
        )
    if _is_english_reply_language(reply_language):
        json_example = (
            '{"paragraphs":[{"type":"voice","sentences":[{"text":"Sure thing, sugarcube.",'
            '"emotion_prompt":"Warm, relaxed, medium pace, short pauses."}]}]}'
        )
        auxiliary_language_rule = (
            '- 当回复语言为 English 时，emotion_prompt 也必须使用英文 CosyVoice instruction 风格短句，例如 '
            '"Warm, relaxed, medium pace, short pauses."；不要输出中文情绪词或中文辅助说明。\n'
        )
    else:
        json_example = (
            '{"paragraphs":[{"type":"voice","sentences":[{"text":"一句口语台词。",'
            '"emotion_prompt":"轻快，中速，尾音上扬。"}]}]}'
        )
        auxiliary_language_rule = ""
    state_anchor = p.get("state_anchor")
    state_lines: list[str] = []
    if isinstance(state_anchor, dict):
        for key, value in state_anchor.items():
            text = str(value or "").strip()
            if text:
                state_lines.append(f"- {key}: {text[:220]}")
    state_block = "\n".join(state_lines)
    state_section = f"\n【当前可用事实】\n{state_block}\n" if state_block else ""
    user_profile = re.sub(r"\s+\n", "\n", str(user_profile_context or "").strip())
    user_profile_section = (
        "\n【当前用户档案（每轮固定注入）】\n"
        "这些字段描述当前用户，不是当前角色。用户问“我/我的/你知道我什么”时可用这里回答；用户问“你/你的”且语义指向角色自己时，不要用这里的年龄、性别或种族替代角色档案。\n"
        f"{user_profile[:1200]}\n"
        if user_profile
        else ""
    )
    homepage_profile = re.sub(r"\s+\n", "\n", str(character_homepage_profile_context or "").strip())
    homepage_section = (
        "\n【角色主页档案（每轮固定注入）】\n"
        "这些字段来自角色主页档案，属于稳定角色设定；当用户询问角色自己的年龄、性别、种族、16人格、性格、兴趣、简介或身份时，优先使用这里的明确字段。"
        "其中 16人格 只提供性格倾向参考，用来辅助表达风格、决策倾向和互动节奏。\n"
        f"{homepage_profile[:1200]}\n"
        if homepage_profile
        else ""
    )
    mammary_anatomy_rule = _voice_profile_equine_mammary_anatomy_rule(homepage_profile)
    profile = re.sub(r"\s+\n", "\n", str(character_profile_context or "").strip())
    profile_section = f"\n【本轮相关角色设定（Stage 2自我认知摘取）】\n{profile[:1800]}\n" if profile else ""
    answer_card = re.sub(r"\s+\n", "\n", str(character_profile_answer_card or "").strip())
    answer_card_section = f"\n{answer_card[:1600]}\n" if answer_card else ""
    vision_section = _voice_vision_context_section(vision_context)
    vision_section = f"\n{vision_section[:2200]}\n" if vision_section else ""
    shared_material_section = _voice_stage3_shared_material_section(
        p,
        scene_anchor_card=scene_anchor_card,
        guest_group_memory=guest_group_memory,
        revision_context=revision_context,
        prior_image_context=prior_image_context,
        search_context=search_context,
        at_event_context=at_event_context,
        selected_asset_attachments=selected_asset_attachments,
        current_user_text=current_user_text,
    )
    shared_material_section = f"\n{shared_material_section[:6200]}\n" if shared_material_section else ""
    try:
        bubble_count = max(1, min(6, int(p.get("bubble_count") or 1)))
    except Exception:
        bubble_count = 1
    should_ask = "是" if p.get("should_ask_question") else "否"
    escalation = str(p.get("requested_escalation") or "none").strip()
    intimacy_line = ""
    if escalation and escalation.lower() not in {"none", "null", "unknown"}:
        intimacy_line = (
            f"- 亲密落点: 关系阶段={p.get('relationship_stage', 'uncertain')}，"
            f"角色亲密风格={p.get('character_intimacy_style', 'balanced')}，本轮升级类型={escalation}。"
            "用角色口吻给出当前关系里自然、具体、能接住气氛的下一拍。\n"
        )
    intimacy_rule = _voice_intimacy_execution_rule(p)
    return f"""【普通对话 Step 3 语音回复素材包】
你现在只负责把 Stage 2 已处理好的信息写成角色会说出口的手机语音 JSON。不要重新做关系判断、事实审查或记忆取舍；那些已经由前置步骤完成。

你的任务：
- 生成角色真正会“说出口”的手机语音内容，比书面聊天更口语、短句、自然、有停顿。
- 每个 voice 段会成为一条语音气泡；每个 sentence 会单独调用 TTS，所以每句话都必须有自己的 emotion_prompt。
- 普通对话生成语音时，禁止额外生成文本消息气泡；paragraphs 里只能输出 type="voice"。
- 不要输出 type="text"、narration、bracket、括号动作、括号心理、舞台说明或旁白说明；不能自然说出口的动作/旁白直接删掉。

【本轮回复素材】
- 目标气泡数: {bubble_count}
- 本轮意图: {p.get("reply_intent", "")}
- 语气: {p.get("tone", "")}
- 回复语言: {reply_language}{'（' + reply_language_reason + '）' if reply_language_reason else ''}
- 动作样式: {p.get("action_style", "plain_text")}
- 关系阶段: {p.get("relationship_stage", "uncertain")}
- 角色亲密风格: {p.get("character_intimacy_style", "balanced")}
- 本轮升级类型: {p.get("requested_escalation", "none")}
- 用户压力等级: {p.get("user_pressure_level", "low")}
- 是否以问题收尾: {should_ask}
- 语音原因: {voice_reason}
- 表达调度: {p.get("expression_policy", "")}
- 主动推进: {p.get("proactive_seed", "")}
{intimacy_line.rstrip()}
{user_profile_section.rstrip()}
{homepage_section.rstrip()}
{profile_section.rstrip()}
{answer_card_section.rstrip()}
{vision_section.rstrip()}
{shared_material_section.rstrip()}
{state_section}

输出格式：
只输出一行合法 JSON，不要 markdown，不要解释。
JSON 格式如下：
{json_example}

硬性规则：
- paragraphs 数组中的每个元素都必须是 type="voice"；禁止输出任何额外消息气泡。
- reply_language 不是用户输入语言，而是角色输出语言；若上方回复语言不是 auto，所有 voice.sentence.text 都必须使用该语言。
{language_rule.rstrip()}
- emotion_prompt 虽然不会直接展示给用户，但会进入语音生成链路；若上方回复语言不是 auto，emotion_prompt 也必须使用同一种目标语言写成表演说明。
{auxiliary_language_rule.rstrip()}
{intimacy_rule.rstrip()}
- voice.sentence.text 必须是无括号、无 emoji、无 markdown 的一句可朗读口语；每句用「。」「！」「？」或「；」结尾。
- 不要在同一句里混合括号动作，例如禁止「你好（她笑了笑），我来了。」；动作/旁白不要另起气泡，直接删掉或改写成角色能自然说出口的台词。
- emotion_prompt 按 CosyVoice instruction 规格写：一行自然语言短句，总长度不超过 100 字符；汉字按 2 个字符计算，所以中文最好控制在 40 字以内。
- emotion_prompt 只写本句声音表现，例如“轻快，中速，尾音上扬。”、“温柔，语速偏慢，停顿稍长。”、“Warm, relaxed, medium pace, short pauses.”。
- emotion_prompt 可以描述语速、停顿、能量、轻重音、语调起伏、收尾力度或方言；不要复述台词原文，不要写剧情、动作、关系判断、角色设定或心理活动。
- 角色音色由 voice_id / voice profile 保持；emotion_prompt 不需要写“保持原音色/Keep the original voice”，也不要要求改变音色、年龄感、声线粗细或发声位置。
- 戏剧性来自节奏、停顿、力度和语调变化；不要写“更尖/更奶/少女感/低沉/沙哑/磁性/成熟声线/像另一个声音”等会改变音色的提示。
- 若上方包含【当前角色档案问答执行卡｜最后采用】，voice.sentence.text 必须优先按执行卡回答角色自己的档案字段；不要把用户资料里的年龄、种族或性别当成角色自己的资料。
- 若上方同时出现【当前用户档案】和【角色主页档案】，先根据用户措辞区分对象：“我/我的”指用户，“你/你的”通常指当前角色；不要交叉使用两个档案的年龄、性别、种族和人格字段。
- 16人格字段只提供性格倾向参考，用来辅助角色说话风格、决策倾向和互动节奏；不要把它扩写成额外的角色资料。
- 如果 should_ask_question=false，不要用问句或疑问尾句收尾。
- 内容要适合听，不要列表、编号、链接、代码、长解释或书面段落。
- 近邻复读控制：除非用户明确要求“复述/照着说/再说一遍/原话说/重复这句/说一样的内容”，否则不要连续复用最近角色回复中的完整句子、固定承诺句或高度相似句式。最近真实对话只能作事实依据，不要把上一条台词原封不动或轻微改字后再次输出。
- 当用户只是简短肯定、应声或接住上一条（如“好/嗯/可以/知道了”）时，不能只把上一轮安慰或承诺换词重复一遍；应在同一主题上给一个小推进、换一个关注点、做轻微话题转移，或给用户一个更容易接话的下一拍。示例方向：从“我在这里陪着你”改成“你已经在认真想办法了”“等要开口前我们再把话顺一遍”“先别把自己绷太紧”。
- 若角色资料或上下文显示当前角色是小马、飞马、天马、陆马、独角兽、雌驹或雄驹，voice.sentence.text 里涉及角色自己的身体部位或能力时，只使用角色资料明确支持的身体部位；通用小马结构可写蹄子、蹄尖、前蹄、鬃毛、尾巴、耳朵、表情、视线和声音状态；翅膀、独角/角、飞行、独角魔法这类分种族器官或能力，必须由本轮角色资料明确支持才可写，不要用“如果有/若有/如有”占位。不要把角色自己的动作说成人类手、手指或中指动作。需要表达手指/指尖功能时用蹄尖，需要表达手/手部动作时用蹄子或前蹄；普通身体介绍不主动罗列缺失部位，只有用户直接询问手、手指、中指或替代写法时才说明。
{mammary_anatomy_rule.rstrip()}
"""


async def generate_normal_voice_reply(
    *,
    request,
    base_payload: dict[str, Any],
    active_model: dict[str, Any] | None,
    api_url: str,
    headers: dict[str, str],
    httpx_client,
    planner_result: dict[str, Any] | None,
) -> NormalVoiceReplyResult:
    payload = copy.deepcopy(base_payload)
    try:
        from .normal_speaker import effective_speaker_character_id, normal_role_debug_params

        debug_character_id = effective_speaker_character_id(request) or getattr(request, "character_id", None)
        debug_role_params = normal_role_debug_params(
            request,
            {
                "pipeline": "normal_voice_reply",
                "conversation_id": getattr(request, "conversation_id", None),
                "speaker_character_id": debug_character_id,
            },
        )
    except Exception:
        debug_character_id = getattr(request, "character_id", None)
        debug_role_params = {
            "pipeline": "normal_voice_reply",
            "conversation_id": getattr(request, "conversation_id", None),
            "speaker_character_id": debug_character_id,
        }
    try:
        from .normal_planner import (
            _extract_character_homepage_profile_for_reply,
            build_character_homepage_profile_answer_card,
        )

        raw_character_context = getattr(request, "_normal_stage2_character_context", "") or ""
        homepage_profile = _extract_character_homepage_profile_for_reply(
            raw_character_context
        )
        latest_user = ""
        for msg in reversed(getattr(request, "messages", None) or []):
            if getattr(msg, "role", None) == "user":
                latest_user = str(getattr(msg, "content", "") or "")
                break
        answer_card = build_character_homepage_profile_answer_card(raw_character_context, latest_user)
    except Exception:
        homepage_profile = ""
        answer_card = ""
    payload["stream"] = False
    payload["messages"] = _inject_sys_before_last_user(
        list(payload.get("messages") or []),
        _voice_reply_system(
            planner_result,
            user_profile_context=_voice_user_profile_context_from_messages(payload.get("messages")),
            character_profile_context=getattr(request, "_normal_stage2_character_profile", "") or "",
            character_homepage_profile_context=homepage_profile,
            character_profile_answer_card=answer_card,
            vision_context=getattr(request, "_normal_stage2_vision_context", None),
            scene_anchor_card=(
                getattr(request, "_normal_stage3_scene_anchor_card", None)
                or getattr(request, "_normal_scene_anchor_card", "")
                or ""
            ),
            guest_group_memory=getattr(request, "_normal_stage3_guest_group_memory", "") or "",
            revision_context=getattr(request, "_normal_stage3_revision_context", "") or "",
            prior_image_context=getattr(request, "_normal_stage3_prior_image_context", "") or "",
            search_context=getattr(request, "_normal_stage3_search_context", "") or "",
            at_event_context=(
                getattr(request, "_normal_stage3_at_event_context", None)
                or getattr(request, "_normal_at_event_context", None)
            ),
            selected_asset_attachments=(
                getattr(request, "_normal_stage3_selected_asset_attachments", None)
                or getattr(request, "_assistant_asset_attachments", None)
            ),
            current_user_text=_latest_visible_user_text_for_voice(request),
        ),
    )
    apply_llm_task_payload_config(payload, "normal_voice_reply")
    payload["thinking"] = {"type": "disabled"}
    payload.pop("reasoning_effort", None)
    payload.pop("reasoning", None)
    payload["enable_thinking"] = False
    payload.pop("thinking_budget", None)
    timeout = llm_task_float("normal_voice_reply", "timeout_seconds", 90.0) or 90.0
    model_cfg = active_model or {}
    response = await call_llm_payload(
        payload,
        model_cfg,
        task="normal_voice_reply",
        httpx_client=httpx_client,
        timeout=timeout,
        request_payload_final=True,
        api_url=api_url,
        headers=headers,
        chat_debug_request={
            "username": getattr(request, "username", None),
            "character_id": debug_character_id,
            "mode": getattr(request, "mode", "normal") or "normal",
            "model_name": payload.get("model") or model_cfg.get("model_name") or model_cfg.get("id"),
            "stage": "NORMAL_STEP_3_VOICE_REPLY_REQUEST",
            "params": debug_role_params,
        },
    )
    clean_text = sanitize_assistant_strip_thinking_blocks(
        sanitize_assistant_strip_markers(response.text or "", model_cfg)
    )
    data = _loads_json_object(clean_text)
    if not data:
        logger.warning("[VoiceReply] model returned non-json: %s", clean_text[:200])
        raise ValueError("voice_reply_json_parse_failed")
    result = coerce_voice_reply_json(data, planner_result=planner_result)
    result.raw_response = response.raw_response or {}
    try:
        result.usage_input = int((response.usage or {}).get("input") or 0)
        result.usage_output = int((response.usage or {}).get("output") or 0)
    except Exception:
        pass
    return result
