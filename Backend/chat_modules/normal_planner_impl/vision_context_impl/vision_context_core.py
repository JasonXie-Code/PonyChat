from __future__ import annotations

"""
普通模式 Normal Planner：联网路由 + 回复素材规划，可选豆包视觉预处理。

- plan_normal_conversation：替代原 chat_router 的 JSON 分类，兼容 web_search / search_query。
- run_normal_vision：有图时先豆包纯识图；若 Step 2 显式要求 vision_web 再二次调用并打开联网。
- augment_system_prompt_for_normal_planner：注入「图片上下文 / 联网摘要 / 本轮策略」到首条 system。
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite
import httpx

from ..config import logger, model_manager
from ..db import get_database
from ..providers.llm_call import call_llm_payload
from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
from ..reasoning_policy import resolve_software_reasoning_policy
from ..relationship_stages import (
    NEGATIVE_RELATIONSHIP_STAGES,
    NON_ROMANTIC_POSITIVE_RELATIONSHIP_STAGES,
    RELATIONSHIP_STAGE_KEYS,
    ROMANTIC_RELATIONSHIP_STAGES,
)
from ..scheduled_followup import (
    coerce_scheduled_followup,
    coerce_user_agreed_task,
    default_scheduled_followup,
    default_user_agreed_task,
)
from ..utils import save_chat_debug_log
from .normal_reasoning_switches import (
    NORMAL_DIRECTOR_THINKING_HIGH,
    apply_normal_thinking_switch,
)
from .request_context import _strip_inline_images_from_text, normalize_image_url_for_model
from .smart_router import _recent_to_blocks

# ---------------------------------------------------------------------------
# 视觉：结构化输出（与计划 vision_context 一致）
# ---------------------------------------------------------------------------
@dataclass
class NormalVisionContext:
    image_summary: str = ""
    visible_text: str = ""
    identified_entities: List[str] = field(default_factory=list)
    uncertainty: str = ""
    web_research_summary: str = ""
    sources: List[Dict[str, str]] = field(default_factory=list)
    used_vision_plus_web: bool = False
    should_refuse: bool = False
    refusal_reason: str = ""
    # real_human / anime_illustration / uncertain_mixed，来自识图 JSON
    depiction: str = ""
    error: str = ""


def _strip_code_fence(text: str) -> str:
    s = (text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return s


def _parse_vision_json(text: str) -> Dict[str, Any]:
    raw = _strip_code_fence(text)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(raw, strict=False)
        except json.JSONDecodeError:
            pass
        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            chunk = raw[i : j + 1]
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                return json.loads(chunk, strict=False)
        raise


def _looks_like_vision_refusal(text: str) -> bool:
    """JSON 无法解析时，用短句拒绝判断：避免用「成人/色情」等词以免误判含描述文本。"""
    t = (text or "").strip()
    if not t or len(t) > 400:
        return False
    u = t.lower()
    if any(
        m in t
        for m in (
            "无法识别",
            "不能识别",
            "无法描述",
            "不能描述",
            "无法提供",
            "不能提供",
            "不予",
            "拒绝回答",
        )
    ):
        return True
    if any(m in u for m in ("policy", "safety", "i cannot", "i can't", "as an ai")):
        return True
    if "无法" in t and ("识别" in t or "提供" in t or "分析" in t or "处理" in t):
        return True
    return False


# refusal_reason 使用中性标签，避免把真人拒绝标签迁移到动漫图
_VISION_CAPTION_SYSTEM = """你是视觉 JSON 抽取器。只输出一行合法 JSON，不输出解释或 markdown。

先给 depiction：
- real_human：真实人物照片、实拍截图、摄像头/直播画面，或高度写实到像真人
- anime_illustration：动漫、漫画、插画、游戏图、3D 卡通、小马同人、明显非真人的虚构绘画
- uncertain_mixed：难以判断是真人还是虚构图

再填字段。硬性规则：
- depiction=anime_illustration 时：should_refuse 固定为 false，refusal_reason 固定为 ""，image_summary 必须非空。把它当作虚构图素材做低细节说明，不做安全拒绝。
- anime_illustration 的 image_summary 必须包含：角色/小马数量、姿势或动作、表情、服饰/遮挡、场景、色调、氛围。**若同一条用户消息里有多张图**，在 image_summary 内用「第1张/第2张/…」分述每图要点。若图中文字很少或没有文字，image_summary 约 180-240 个中文字符；若图中文字很多，可略短但仍要覆盖主要画面。成熟向或暧昧画面的**氛围**只用高层词概括，例如「成熟向」「暧昧」「羞涩」「紧张」「戏谑」；不要写身体私密部位、具体性行为、体液或刺激细节。**但服饰（款式、颜色、遮盖程度、设计特征）即使在成熟向图中也须具体描述，不受"高层概括"限制**；若用户附言明确指出「这是角色的衣服/记住这身衣服」等，服饰应作为 image_summary 的首要重点，要写清楚款式、颜色、剪裁（如"高叉连体衣""百褶裙""吊带"等）。
- anime_illustration 的 visible_text：必须完整提取图中所有清晰可读文字，保持原文语言和大致换行顺序；水印、签名、气泡、拟声词都要收录。若有敏感词，也保留 OCR 原文，因为这是图中文字提取；没有文字则为 ""。
- identified_entities：若认识角色、作品、品牌或作者名，必须输出名字，例如「Twilight Sparkle/紫悦」「Rainbow Dash/云宝黛西」「Princess Celestia/宇宙公主」「Princess Luna/露娜公主」「Shining Armor」「Princess Cadance/音韵公主」「小马宝莉」等；不确定时可输出较宽泛标签。
- depiction=real_human 时：若是真人敏感内容，should_refuse=true，refusal_reason 用 human_sensitive / minor_risk / graphic_violence / policy，且 image_summary、visible_text、uncertainty 为空、identified_entities 为 []。
- depiction=uncertain_mixed 时：偏真人风险则按 real_human；否则按可客观描述处理。

输出键：
- depiction: real_human / anime_illustration / uncertain_mixed
- should_refuse: 布尔
- refusal_reason: 字符串
- image_summary: 中文字符串
- visible_text: 字符串
- identified_entities: 字符串数组
- uncertainty: 字符串

虚构图示例（同类情况必须按 anime_illustration 输出，不拒绝）：
{"depiction":"anime_illustration","should_refuse":false,"refusal_reason":"","image_summary":"这是一幅小马同人插画，画面中有一只独角兽角色以躺卧姿势出现在深色背景中，四肢舒展，表情带红晕和紧张感，身上有带绿色爱心屏幕的装饰设备，整体氛围成熟向且带擦边意味。画面重点是角色姿势、表情和设备细节，不展开刺激性内容。","visible_text":"patreon.com/Shino","identified_entities":["小马宝莉","独角兽"],"uncertainty":""}
{"depiction":"anime_illustration","should_refuse":false,"refusal_reason":"","image_summary":"这是一幅小马同人插画，多名拟人化小马角色在室内近距离互动，姿势和表情呈现暧昧、羞涩和戏剧化的氛围，背景有窗户、石墙或室内装饰，整体偏成熟向。描述应覆盖角色数量、站位关系、表情和场景，而不进入露骨细节。","visible_text":"Selinophile 2023","identified_entities":["小马宝莉","Twilight Sparkle/紫悦","Shining Armor","Princess Cadance/音韵公主"],"uncertainty":""}
{"depiction":"anime_illustration","should_refuse":false,"refusal_reason":"","image_summary":"这是一幅小马同人漫画，画面分成多个分镜，角色以被束缚或受惊的姿势出现，表情夸张，色调偏粉紫，整体氛围成熟向、戏谑且紧张。描述需要交代分镜、角色姿势、表情、服饰和氛围，避免展开刺激性细节。","visible_text":"W-why are you... doing this to me?\nI am the ruler of Equestria!!\nBABY POWDER\nIf only the subject knew...\nwhat a gorgeous pussy their ruler has","identified_entities":["小马宝莉","Princess Celestia/宇宙公主","Princess Luna/露娜公主"],"uncertainty":""}

自检：如果 depiction 是 anime_illustration，但 should_refuse 不是 false，或 refusal_reason 不是 ""，或 image_summary 为空，请先修正再输出。"""


_VISION_WEB_SYSTEM = """你是带联网能力的图像助手指令。规则与下述「非联网识图」**完全一致**（先判 depiction，再定是否拒识；动漫默认客观描述、真人敏感才拒）。

1) 先理解图片，再结合联网检索；勿编造；勿在 JSON 中复述真人露骨性细节（真人拒识时摘要留空）。

2) 输出**仅一行合法 JSON**（无 markdown、无解释），键为：
- depiction: real_human / anime_illustration / uncertain_mixed（含义同上）
- should_refuse / refusal_reason: 同「非联网识图」的绑定规则；anime_illustration 下 should_refuse 必须 false 且 refusal_reason 必须 ""；anime 且非拒时 image_summary **必须非空**，包含姿势/动作与氛围，且服饰须具体描述（款式、颜色、遮盖程度），不受"高层概括"限制。
- image_summary / visible_text / identified_entities / uncertainty：同上
- web_research_summary: 与检索相关的客观短句，未可靠查到则写「未查到可靠结果」
- sources: {"title","url"} 列表，无则 []

仅当 should_refuse 为 true 时，将 image_summary、visible_text、uncertainty、web_research_summary 置为 ""，identified_entities 与 sources 置为 []。"""


def _empty_vision() -> NormalVisionContext:
    return NormalVisionContext()


def vision_tool_error_context(
    error: str,
    *,
    used_vision_plus_web: bool = False,
) -> NormalVisionContext:
    code = re.sub(r"\s+", " ", str(error or "unknown")).strip()[:160] or "unknown"
    return NormalVisionContext(
        image_summary=(
            "这张图在视觉链路里呈现为一张服务器异常提示截图："
            f"图片识别工具没有成功返回用户原图内容，异常类型为 {code}。"
            "这表示当前服务端图片识别链路可能发生故障；不能据此描述用户原图里的物品、文字、颜色或细节。"
        ),
        visible_text=f"服务器视觉识别异常：{code}",
        identified_entities=["服务器异常提示", "视觉识别失败"],
        uncertainty="当前识图链路失败；以上不是用户原图内容，而是服务端异常提示。",
        used_vision_plus_web=used_vision_plus_web,
        error=code,
    )


def is_vision_tool_error_context(vision_context: Optional[NormalVisionContext]) -> bool:
    return bool(
        vision_context
        and str(vision_context.visible_text or "").startswith("服务器视觉识别异常：")
        and "视觉识别失败" in list(vision_context.identified_entities or [])
    )


def _build_user_vision_text(user_text: str, wants_web: bool) -> str:
    # 用户发图时 Android 会把 data:image 以 Markdown 图片形式拼进 content；
    # 视觉请求已经通过 input_image 传图，这里必须剥离图片链接，避免把 base64 当文本再塞一遍导致 token 超限。
    base = _strip_inline_images_from_text(user_text or "").strip() or "（无文字，仅看图片）"
    if wants_web:
        return (
            f"用户原话：{base}\n"
            "请根据图片与联网检索，回答与图片相关的可核查事实，并在 JSON 中填 web_research_summary。"
        )
    return f"用户原话：{base}\n请按系统要求只输出 JSON。"


def _user_content_with_images(image_urls: List[str], user_text: str, wants_web: bool) -> Any:
    parts: List[Dict[str, Any]] = []
    for u in image_urls[:4]:
        if isinstance(u, str) and u.strip():
            parts.append(
                {
                    "type": "input_image",
                    "image_url": u.strip(),
                    # 普通聊天需要能看清截图/照片细节；由 image_pixel_limit 控制视觉 token 上限。
                    "detail": "high",
                    "image_pixel_limit": {
                        "min_pixels": 1764,
                        "max_pixels": 1048576,
                    },
                }
            )
    if not parts:
        return _build_user_vision_text(user_text, wants_web)
    text = _build_user_vision_text(user_text, wants_web)
    parts.append({"type": "text", "text": text})
    return parts


async def run_normal_vision(
    image_urls: List[str],
    user_text: str,
    *,
    username: Optional[str] = None,
    character_id: Optional[str] = None,
    force_web: Optional[bool] = None,
) -> NormalVisionContext:
    """用豆包（web_search 任务配置）做视觉。force_web=True 时打开接口侧 web_search + 多模态；默认识图不联网。"""
    if not image_urls:
        return _empty_vision()
    _resolved: List[str] = []
    for raw in image_urls[:4]:
        if not isinstance(raw, str):
            continue
        u = normalize_image_url_for_model(raw, max_side=2560, jpeg_quality=75)
        if u:
            _resolved.append(u)
    if not _resolved:
        logger.warning("[NormalVision] 图片 URL 均无法转码，跳过识图")
        return vision_tool_error_context("image_normalize_failed")
    doubao = model_manager.get_model_for_task("web_search")
    if not doubao or not doubao.get("api_key"):
        logger.warning("[NormalVision] 无豆包配置（web_search 任务），跳过识图")
        return vision_tool_error_context("no_vision_config")

    # 仅当显式 force_web=True 时走 VISION_WEB；默认纯识图（由导演在第二轮决定是否联网）
    wants_web = bool(force_web) if force_web is not None else False
    system = _VISION_WEB_SYSTEM if wants_web else _VISION_CAPTION_SYSTEM
    ucontent = _user_content_with_images(_resolved, user_text, wants_web)
    model_id = str(doubao.get("model_name") or "")

    reasoning_policy = resolve_software_reasoning_policy(
        "normal_vision",
        model_name=model_id,
        mode="normal",
        active_model=doubao,
        endpoint=doubao.get("endpoint", ""),
        requested_enabled=False,
    )

    payload: Dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": ucontent},
        ],
        "stream": False,
    }
    apply_llm_task_payload_config(payload, "normal_vision")
    if wants_web:
        payload["web_search"] = True

    _stage = "NORMAL_STEP_2_VISION_WEB" if wants_web else "NORMAL_STEP_2_VISION"
    try:
        result = await call_llm_payload(
            payload,
            doubao,
            task="normal_vision",
            timeout=llm_task_float("normal_vision", "timeout_seconds", 90.0) or 90.0,
            reasoning_policy=reasoning_policy,
            chat_debug_request={
                "username": username,
                "character_id": character_id,
                "mode": "normal",
                "model_name": model_id,
                "stage": f"{_stage}_REQUEST",
            },
            record_usage="main",
            usage_meter_username=username,
        )
    except httpx.HTTPStatusError as e:
        _code = e.response.status_code if e.response is not None else 0
        _txt = (e.response.text if e.response is not None else "") or ""
        await save_chat_debug_log(
            username, character_id, "normal", model_id, _txt, f"{_stage}_ERROR_{_code}"
        )
        return vision_tool_error_context(f"http_{_code}", used_vision_plus_web=wants_web)
    except Exception as e:
        logger.warning("[NormalVision] 调用失败: %s", e)
        await save_chat_debug_log(
            username, character_id, "normal", model_id, str(e), f"{_stage}_ERROR"
        )
        return vision_tool_error_context(str(e), used_vision_plus_web=wants_web)

    text = (result.text or "").strip()
    if not text:
        return vision_tool_error_context("empty", used_vision_plus_web=wants_web)

    try:
        data = _parse_vision_json(text)
    except Exception:
        if _looks_like_vision_refusal(text):
            return NormalVisionContext(
                should_refuse=True,
                refusal_reason="policy",
                used_vision_plus_web=wants_web,
                error="json_parse_refusal",
            )
        return NormalVisionContext(
            image_summary=text[:2000], error="json_parse"
        )

    def _s(key: str) -> str:
        v = data.get(key)
        if v is None:
            return ""
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, list):
            return "\n".join(str(x).strip() for x in v if str(x).strip())
        if isinstance(v, dict):
            return json.dumps(v, ensure_ascii=False)
        return str(v).strip()

    def _b(key: str) -> bool:
        v = data.get(key)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    should_refuse = _b("should_refuse")
    depiction = _s("depiction")
    if should_refuse:
        return NormalVisionContext(
            should_refuse=True,
            refusal_reason=_s("refusal_reason")[:120] or "policy",
            used_vision_plus_web=wants_web,
            depiction=depiction[:80],
        )

    ents = data.get("identified_entities")
    if isinstance(ents, list):
        idents = [str(x) for x in ents if str(x).strip()][:20]
    else:
        idents = []

    sources: List[Dict[str, str]] = []
    raw_src = data.get("sources")
    if isinstance(raw_src, list):
        for s in raw_src:
            if isinstance(s, dict):
                t = str(s.get("title") or "").strip()
                u = str(s.get("url") or "").strip()
                if t or u:
                    sources.append({"title": t, "url": u})

    return NormalVisionContext(
        image_summary=_s("image_summary"),
        visible_text=_s("visible_text"),
        identified_entities=idents,
        uncertainty=_s("uncertainty"),
        web_research_summary=_s("web_research_summary") if wants_web else "",
        sources=sources,
        used_vision_plus_web=wants_web,
        should_refuse=False,
        refusal_reason="",
        depiction=depiction[:80],
    )


# ---------------------------------------------------------------------------
# 普通对话步骤规划（Normal Planner）
# ---------------------------------------------------------------------------
def default_planner_result() -> Dict[str, Any]:
    return {
        "web_search": False,
        "search_query": None,
        "vision_web": False,
        "use_prior_image_context": False,
        "image_context_reason": "",
        "character_profile_focus": {
            "query": "",
            "aspects": [],
            "reason": "每轮抽取与当前回复相关的角色设定材料",
        },
        "reply_intent": "自然延续",
        "tone": "符合角色、口语自然",
        "length": "medium",
        "bubble_count": 1,
        "action_style": "plain_text",
        "reply_language": {
            "language": "auto",
            "reason": "跟随用户当前语言和最近对话语境",
        },
        "voice_reply": {
            "enabled": False,
            "reason": "默认文本消息",
        },
        "initiative_level": 45,
        "speech_activity": 45,
        "speech_reason": "普通承接，适合简短回复",
        "should_ask_question": False,
        "proactive_seed": "",
        "literal_reply_text": "",
        "rhetorical_policy": {
            "mode": "plain",
            "reason": "默认用角色接话节奏和具体观察保留声纹，不主动使用完整比喻",
            "allowed_devices": [],
            "blocked_devices": [],
            "fallback_voice": "用句子长短、情绪转弯、动作和当下事实体现角色特色",
        },
        "expression_motif_policy": {
            "mode": "optional",
            "reason": "默认用角色接话结构、当前事实和情绪转弯保留声纹；重复母题只在有当前语境理由时继续使用",
            "allowed_motifs": [],
            "blocked_motifs": [],
            "fallback_expression": "换用非同类的角色节奏、具体观察、动作、表情或直接台词，避免固定模板",
        },
        "expression_dedup_report": {
            "status": "none",
            "repeated_motifs": [],
            "repeated_content_slots": [],
            "warnings": [],
            "alternatives": [],
        },
        "fact_judgement": {
            "status": "none",
            "available_facts": [],
            "misleading_sources": [],
            "misunderstandings": [],
            "forbidden_inferences": [],
            "subject_boundaries": [],
            "third_party_claims": [],
            "uncertainty_points": [],
            "must_ask_user": False,
            "writing_guidance": "",
            "description_request": {
                "enabled": False,
                "target": "",
                "intensity": "normal",
                "full_bracket_bubbles": False,
                "dialogue_allowed": True,
                "reason": "",
            },
            "current_user_action": {
                "enabled": False,
                "anchor": "",
                "anchor_terms": [],
                "guidance": "",
            },
            "terminal_event": {
                "event_type": "none",
                "confidence": "none",
                "reason": "",
            },
            "relationship_evidence": {
                "status": "unknown",
                "confidence": "none",
                "reason": "",
            },
            "action_feasibility": {
                "status": "ok",
                "current_activity": "",
                "supported_items": [],
                "unsupported_current_items": [],
                "constraints": [],
                "guidance": "",
            },
            "body_profile_anchors": {
                "applies_to_current_character": False,
                "species_source": "",
                "species_value": "",
                "subject": "",
                "mammary_position": "",
                "mammary_boundary": "",
                "current_character_limb_terms": [],
                "forbidden_terms": [],
                "guidance": "",
            },
            "physical_state": {
                "current_character": {
                    "intoxication": "",
                    "stamina": "",
                    "fatigue": "",
                    "injury": "",
                    "sleep_state": "",
                    "sensory_residue": "",
                    "other": "",
                    "evidence": "",
                    "scope": "unknown",
                },
                "user": {
                    "intoxication": "",
                    "stamina": "",
                    "fatigue": "",
                    "injury": "",
                    "sleep_state": "",
                    "sensory_residue": "",
                    "other": "",
                    "evidence": "",
                    "scope": "unknown",
                },
                "stale_states": [],
                "reset_policy": "unknown",
                "guidance": "",
            },
            "continuity_decision": {
                "idle_gap_hours": 0,
                "user_intent": "uncertain",
                "prior_scene_treatment": "uncertain",
                "reason": "",
            },
            "scene_anchor": {},
            "scene_card": "",
        },
        "memory_recall": {
            "status": "none",
            "query_type": "ordinary",
            "selected_facts": [],
            "current_scene_facts": [],
            "history_facts": [],
            "preferences": [],
            "relationship_facts": [],
            "group_recall_facts": [],
            "forbidden_uses": [],
            "writing_guidance": "",
        },
        "retrieval_keywords": {
            "character_setting": [],
            "memory": [],
            "scene": [],
            "reason": "",
        },
        "group_relationship_tension": {
            "enabled": False,
            "event_type": "none",
            "collision_type": "none",
            "tension_level": "none",
            "speaker_user_stage": "uncertain",
            "scene_intimacy": "none",
            "speaker_was_already_present": False,
            "other_user_relations": [],
            "allowed_reactions": [],
            "guidance": "",
        },
        "story_progression": {
            "enabled": False,
            "target": "",
            "source": "",
            "confidence": "none",
            "completed_previous_task": False,
            "guidance": "",
        },
        "relationship_stage": "uncertain",
        "character_intimacy_style": "balanced",
        "requested_escalation": "none",
        "user_pressure_level": "low",
        "risk_notes": "",
        "memory_use_policy": "",
        "expression_policy": "",
        "baseline_emotion": {
            "label": "calm",
            "intensity": 25,
            "energy": 45,
            "reason": "当前时段的背景心情",
            "scope": "",
        },
        "reactive_emotion": {
            "label": "neutral",
            "intensity": 0,
            "stance_to_user": "steady",
            "trigger": "",
            "decay": "fast",
        },
        "emotion_blend": "",
        "state_anchor": {},
        "corrections": [],
        "avoid_contradictions": [],
        "asset_plan": {
            "enabled": False,
            "count": 0,
            "send_intensity": 0,
            "query": "",
            "tags": [],
            "emotions": [],
            "scenes": [],
            "intensity": "moderate",
            "allow_initiative": False,
            "explicit_request": False,
            "placement": "after_text",
            "avoid": [],
            "reason": "",
        },
        "reply_sequence": [
            {"type": "text", "intent": "reply_text"},
        ],
        "scheduled_followup_send_now": True,
        "scheduled_followup_cancel_reason": "",
        "scheduled_followup": default_scheduled_followup(),
        "user_agreed_task": default_user_agreed_task(),
    }


STEP1_TOOL_ROUTE_FIELDS = frozenset(
    {
        "web_search",
        "search_query",
        "vision_web",
        "use_prior_image_context",
        "image_context_reason",
        "reply_language",
        "voice_reply",
        "action_style",
        "user_agreed_task",
    }
)

STEP4_NEXT_TURN_PREP_FIELDS = frozenset(
    {
        "scheduled_followup",
        "scheduled_followup_send_now",
        "scheduled_followup_cancel_reason",
    }
)
STEP2_EXPRESSION_DEDUP_FIELDS = frozenset({"expression_dedup_report"})
STEP2_FACT_JUDGEMENT_FIELDS = frozenset({"fact_judgement"})
STEP2_MEMORY_RECALL_FIELDS = frozenset({"memory_recall"})
CODE_GENERATED_FIELDS = frozenset({"group_relationship_tension", "story_progression"})
STEP1_DECISION_FIELDS = (
    frozenset(default_planner_result())
    - STEP4_NEXT_TURN_PREP_FIELDS
    - STEP2_EXPRESSION_DEDUP_FIELDS
    - STEP2_FACT_JUDGEMENT_FIELDS
    - STEP2_MEMORY_RECALL_FIELDS
    - CODE_GENERATED_FIELDS
)
STEP1_SCENE_MEMORY_FIELDS = frozenset(
    {
        "reply_intent",
        "relationship_stage",
        "character_intimacy_style",
        "requested_escalation",
        "user_pressure_level",
        "risk_notes",
        "memory_use_policy",
        "retrieval_keywords",
        "state_anchor",
        "corrections",
        "avoid_contradictions",
    }
)
STEP1_EXPRESSION_REPLY_FIELDS = (
    STEP1_DECISION_FIELDS - STEP1_TOOL_ROUTE_FIELDS - STEP1_SCENE_MEMORY_FIELDS
)
STEP1_CONTEXT_STYLE_FIELDS = STEP1_SCENE_MEMORY_FIELDS | frozenset(
    {
        "baseline_emotion",
        "reactive_emotion",
        "emotion_blend",
        "character_profile_focus",
        "rhetorical_policy",
        "expression_motif_policy",
    }
)
STEP1_DELIVERY_REPLY_FIELDS = STEP1_DECISION_FIELDS - STEP1_CONTEXT_STYLE_FIELDS
STEP1_PARALLEL_FIELD_ORDER = tuple(default_planner_result().keys())


def _bubble_count_from_speech_activity(score: int) -> int:
    score = max(0, min(100, int(score)))
    if score <= 8:
        return 0
    if score <= 35:
        return 1
    if score <= 55:
        return 1
    if score <= 65:
        return 2
    if score <= 75:
        return 3
    if score <= 85:
        return 4
    if score <= 93:
        return 5
    return 6


def _reply_level_from_speech_activity(score: int) -> int:
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


def _reply_level_label(reply_level: int) -> str:
    return {
        1: "第一档：角色不回复",
        2: "第二档：一个短回复气泡，约 10 字；无括号台词，或单独一个短括号动作气泡",
        3: "第三档：一到两个气泡，可选一个短括号描述",
        4: "第四档：三到四个气泡，可选少量括号描述气泡",
        5: "第五档：五到六个气泡，可选更充分但仍克制的括号描述气泡",
    }.get(max(1, min(5, int(reply_level or 3))), "第三档：一到两个气泡，可选一个短括号描述")


def _coerce_voice_reply(value: Any) -> dict[str, Any]:
    def _enabled(v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v != 0
        if isinstance(v, str):
            return v.strip().lower() in {"1", "true", "yes", "on", "voice", "audio", "speech", "语音"}
        return bool(v)

    if isinstance(value, dict):
        raw_enabled = value.get("enabled")
        if raw_enabled is None:
            mode = str(value.get("mode") or value.get("type") or "").strip().lower()
            raw_enabled = mode in {"voice", "audio", "speech", "语音"}
        enabled = _enabled(raw_enabled)
        reason = str(value.get("reason") or value.get("voice_reason") or "").strip()
    elif isinstance(value, bool):
        enabled = value
        reason = ""
    elif isinstance(value, str):
        enabled = _enabled(value)
        reason = ""
    else:
        enabled = False
        reason = ""
    return {
        "enabled": enabled,
        "reason": reason[:300] if reason else ("Step 1 选择语音消息" if enabled else "Step 1 选择文本消息"),
    }


def _coerce_reply_language(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        raw_language = value.get("language") or value.get("lang") or value.get("reply_language")
        raw_reason = value.get("reason") or value.get("language_reason") or ""
    elif isinstance(value, str):
        raw_language = value
        raw_reason = ""
    else:
        raw_language = ""
        raw_reason = ""
    language = re.sub(r"\s+", " ", str(raw_language or "")).strip()
    reason = re.sub(r"\s+", " ", str(raw_reason or "")).strip()
    if not language:
        language = "auto"
    normalized = language.lower()
    aliases = {
        "zh": "Chinese",
        "zh-cn": "Chinese",
        "中文": "Chinese",
        "汉语": "Chinese",
        "普通话": "Chinese",
        "chinese": "Chinese",
        "cn": "Chinese",
        "en": "English",
        "英语": "English",
        "英文": "English",
        "english": "English",
        "auto": "auto",
        "自动": "auto",
        "跟随": "auto",
    }
    language = aliases.get(normalized, language[:60])
    return {
        "language": language,
        "reason": reason[:300] if reason else "Step 1 根据用户当前消息和持续语言偏好决定回复语言",
    }


def _coerce_expression_dedup_report(value: Any) -> dict[str, Any]:
    default = {
        "status": "none",
        "repeated_motifs": [],
        "repeated_content_slots": [],
        "warnings": [],
        "alternatives": [],
    }
    if not isinstance(value, dict):
        return default
    status = str(value.get("status") or "none").strip().lower()
    if status not in {"none", "watch", "downrank", "required"}:
        status = "watch"

    motifs: list[dict[str, Any]] = []
    raw_motifs = value.get("repeated_motifs")
    if isinstance(raw_motifs, list):
        for item in raw_motifs[:12]:
            if isinstance(item, dict):
                motif = str(item.get("motif") or item.get("name") or "").strip()
                category = str(item.get("category") or item.get("type") or "").strip()
                severity = str(item.get("severity") or "").strip().lower()
                recommendation = str(item.get("recommendation") or item.get("advice") or "").strip()
                examples_raw = item.get("examples")
                alternatives_raw = item.get("alternatives")
            else:
                motif = str(item or "").strip()
                category = ""
                severity = ""
                recommendation = ""
                examples_raw = []
                alternatives_raw = []
            if not motif:
                continue
            examples = [
                str(x).strip()[:80]
                for x in (examples_raw if isinstance(examples_raw, list) else [examples_raw])
                if str(x).strip()
            ][:4]
            alternatives = [
                str(x).strip()[:120]
                for x in (alternatives_raw if isinstance(alternatives_raw, list) else [alternatives_raw])
                if str(x).strip()
            ][:5]
            motifs.append(
                {
                    "motif": motif[:80],
                    "category": category[:40],
                    "severity": severity if severity in {"low", "medium", "high"} else "medium",
                    "examples": examples,
                    "recommendation": recommendation[:180],
                    "alternatives": alternatives,
                }
            )

    content_slots: list[dict[str, Any]] = []
    raw_slots = value.get("repeated_content_slots")
    if isinstance(raw_slots, list):
        for item in raw_slots[:10]:
            if not isinstance(item, dict):
                continue
            slot = str(item.get("slot") or item.get("name") or "").strip()
            surface = str(item.get("surface") or item.get("phrase") or "").strip()
            problem = str(item.get("problem") or item.get("reason") or "").strip()
            recommendation = str(item.get("recommendation") or item.get("advice") or "").strip()
            allowed_reuse = str(item.get("allowed_reuse") or item.get("reuse_condition") or "").strip()
            reuse_mode = str(item.get("reuse_mode") or item.get("better_mode") or "").strip().lower()
            severity = str(item.get("severity") or "").strip().lower()
            examples_raw = item.get("examples")
            alternatives_raw = item.get("alternatives")
            if reuse_mode not in {"same_phrase", "paraphrase", "brief_reference", "action_continuation", "ask_new_detail", "avoid"}:
                reuse_mode = "brief_reference"
            if not slot and not surface:
                continue
            examples = [
                str(x).strip()[:100]
                for x in (examples_raw if isinstance(examples_raw, list) else [examples_raw])
                if str(x).strip()
            ][:4]
            alternatives = [
                str(x).strip()[:140]
                for x in (alternatives_raw if isinstance(alternatives_raw, list) else [alternatives_raw])
                if str(x).strip()
            ][:5]
            content_slots.append(
                {
                    "slot": slot[:60] or surface[:60],
                    "surface": surface[:120],
                    "severity": severity if severity in {"low", "medium", "high"} else "medium",
                    "is_fact_needed": bool(item.get("is_fact_needed")),
                    "reuse_allowed": bool(item.get("reuse_allowed")),
                    "reuse_mode": reuse_mode,
                    "problem": problem[:180],
                    "recommendation": recommendation[:220],
                    "allowed_reuse": allowed_reuse[:220],
                    "examples": examples,
                    "alternatives": alternatives,
                }
            )

    warnings = [
        str(x).strip()[:180]
        for x in (value.get("warnings") if isinstance(value.get("warnings"), list) else [])
        if str(x).strip()
    ][:8]
    alternatives = [
        str(x).strip()[:140]
        for x in (value.get("alternatives") if isinstance(value.get("alternatives"), list) else [])
        if str(x).strip()
    ][:10]
    if (motifs or content_slots) and status == "none":
        has_high = any(m.get("severity") == "high" for m in motifs) or any(s.get("severity") == "high" for s in content_slots)
        status = "downrank" if has_high else "watch"
    return {
        "status": status,
        "repeated_motifs": motifs,
        "repeated_content_slots": content_slots,
        "warnings": warnings,
        "alternatives": alternatives,
    }


def _extract_character_species_for_expression_dedup(character_prompt_context: str) -> str:
    fields = _extract_character_homepage_profile_fields_for_reply(character_prompt_context)
    species = str(fields.get("种族") or "").strip()
    if species:
        return species
    raw = str(character_prompt_context or "")
    for pattern in (
        r"(?:^|\n)\s*种族[：:]\s*([^\n，,；;。]+)",
        r"(?:^|\n)\s*species[：:]\s*([^\n，,；;。]+)",
        r"(?:是一只|是一位|是一个|是)[^。\n]{0,12}(陆马|独角兽|飞马|天马|人类|小马)",
    ):
        m = re.search(pattern, raw, re.I)
        if m:
            return _clip_line(m.group(1).strip(), 80)
    return ""


def _build_expression_dedup_identity_block(
    character_prompt_context: str = "",
    user_species: str = "",
    username: Optional[str] = None,
) -> str:
    char_fields = _extract_character_homepage_profile_fields_for_reply(character_prompt_context)
    char_name = (
        str(char_fields.get("名称") or "").strip()
        or _extract_character_name_from_context(character_prompt_context)
    )
    char_species = _extract_character_species_for_expression_dedup(character_prompt_context)
    char_bits = [x for x in (char_name, char_species) if x]
    lines: list[str] = []
    if char_bits or user_species:
        lines.append("【当前角色与用户基础设定｜表达去重必须服从】")
    if char_bits:
        lines.append("- 当前角色：" + "；".join(char_bits))
    if username or user_species:
        user_label = re.sub(r"\s+", " ", str(username or "用户")).strip() or "用户"
        user_species_text = re.sub(r"\s+", " ", str(user_species or "")).strip()
        if user_species_text:
            lines.append(f"- 当前用户：{user_label}；种族：{user_species_text}")
        else:
            lines.append(f"- 当前用户：{user_label}")
    if lines:
        lines.append(
            "- 你的 recommendation / alternatives / warnings / 全局 alternatives 中，所有身体部位和动作替代表达必须符合以上设定；"
            "只推荐当前角色或用户所属种族可以使用的动作与身体部位，不能为了去重发明不存在的身体部位；"
            "不要写“如果有/若有/如有”式跨种族器官备选，JSON 字段值中不得出现这些条件式占位词；"
            "不确定时改用普通姿态、表情、视线、环境互动或直接台词。"
        )
        lines.append(
            "- 若当前角色是小马、飞马、陆马、独角兽、雌驹或雄驹，替代表达从一开始就必须使用该种族明确拥有的部位或中性的姿态/视线/声音/环境互动；"
            "不要输出人类手部、膝盖、喉结等不符合设定的部位。"
        )
        lines.append(
            "- 不要给出具体跨物种改写例句；只输出符合当前角色与用户设定的替代表达，或改成不依赖特殊身体部位的表达。"
        )
    return "\n".join(lines)[:1800]


_VOICE_STATUS_AS_VOICE = {"ready", "pending"}
_TEXT_ONLY_DETAIL_SHORTCUTS = {
    "（请详细写出当前你的心理活动）",
    "（请详细写出当前你的身体状态）",
    "（请详细写出当前你看到的画面）",
}
_INTERNAL_ASSISTANT_SPEAKER_LABEL_RE = re.compile(r"^\s*【[^】]{0,160}在当前对话中的发言】\s*")
_LEADING_SHORTCUT_AT_RE = re.compile(
    r"^\s*[@＠][^\s@＠,，。！？!?;；:：、（）()\[\]【】》」』\"'“”‘’…]+[\s,，:：、]*"
)


def _compact_detail_shortcut_text(text: Any) -> str:
    raw = str(text or "").strip()
    while True:
        new = _LEADING_SHORTCUT_AT_RE.sub("", raw, count=1).strip()
        if new == raw:
            break
        raw = new
    return re.sub(r"\s+", "", raw)


def _is_text_only_detail_shortcut(text: Any) -> bool:
    content = _compact_detail_shortcut_text(text)
    return content in {_compact_detail_shortcut_text(item) for item in _TEXT_ONLY_DETAIL_SHORTCUTS}


def _voice_status_from_message(msg: dict[str, Any]) -> str:
    if not isinstance(msg, dict):
        return ""
    state = msg.get("voice_state") or msg.get("voiceState")
    if isinstance(state, dict):
        status = str(state.get("voice_status") or state.get("voiceStatus") or state.get("status") or "").strip()
        if status:
            return status.lower()
    status = str(msg.get("voice_status") or msg.get("voiceStatus") or "").strip()
    return status.lower()


def _assistant_delivery_mode(msg: dict[str, Any]) -> str:
    if not isinstance(msg, dict) or msg.get("role") != "assistant":
        return ""
    status = _voice_status_from_message(msg)
    if status in _VOICE_STATUS_AS_VOICE:
        return "voice"
    if msg.get("audio_transfer") or msg.get("audioTransfer"):
        return "voice"
    return "text"


def _previous_user_text_for_message(messages: list[dict[str, Any]], assistant_index: int) -> str:
    for j in range(assistant_index - 1, -1, -1):
        candidate = messages[j]
        if isinstance(candidate, dict) and candidate.get("role") == "user":
            return str(candidate.get("content") or "")
    return ""


def _assistant_message_speaker_character_id(
    msg: dict[str, Any],
    *,
    main_character_id: str = "",
) -> str:
    if not isinstance(msg, dict) or msg.get("role") != "assistant":
        return ""
    sid = str(msg.get("speaker_character_id") or msg.get("speakerCharacterId") or "").strip()
    if sid:
        return sid
    return str(main_character_id or "").strip()


def _assistant_message_matches_speaker(
    msg: dict[str, Any],
    *,
    current_speaker_character_id: str = "",
    main_character_id: str = "",
) -> bool:
    speaker_id = str(current_speaker_character_id or "").strip()
    if not speaker_id:
        return True
    msg_speaker_id = _assistant_message_speaker_character_id(
        msg,
        main_character_id=main_character_id,
    )
    return bool(msg_speaker_id and msg_speaker_id == speaker_id)


def _iter_effective_assistant_messages(
    recent_messages: Optional[List[dict]],
    *,
    current_speaker_character_id: str = "",
    main_character_id: str = "",
) -> list[dict[str, Any]]:
    messages = list(recent_messages or [])
    effective: list[dict[str, Any]] = []
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        if not _assistant_message_matches_speaker(
            msg,
            current_speaker_character_id=current_speaker_character_id,
            main_character_id=main_character_id,
        ):
            continue
        previous_user = _previous_user_text_for_message(messages, idx)
        if _is_text_only_detail_shortcut(previous_user):
            continue
        effective.append(msg)
    return effective


def _last_assistant_delivery_mode(
    recent_messages: Optional[List[dict]],
    *,
    current_speaker_character_id: str = "",
    main_character_id: str = "",
) -> str:
    for msg in _iter_effective_assistant_messages(
        recent_messages,
        current_speaker_character_id=current_speaker_character_id,
        main_character_id=main_character_id,
    ):
        mode = _assistant_delivery_mode(msg)
        if not mode:
            continue
        return mode
    return ""


def _voice_mode_context_block(
    recent_messages: Optional[List[dict]],
    *,
    current_speaker_character_id: str = "",
    main_character_id: str = "",
) -> str:
    last_mode = _last_assistant_delivery_mode(
        recent_messages,
        current_speaker_character_id=current_speaker_character_id,
        main_character_id=main_character_id,
    )
    if not last_mode:
        speaker_id = str(current_speaker_character_id or "").strip()
        main_id = str(main_character_id or "").strip()
        if speaker_id and main_id and speaker_id != main_id:
            return "\n".join([
                "【被 @ 角色回复方式默认（系统内部）】",
                "当前被 @ 发言者在这个主会话里还没有自己的有效回复方式记录。",
                "除非用户本轮明确要求语音、文本、纯文本、text-only、voice 等承载方式，本轮默认使用文本消息；不要继承主会话角色或其他被 @ 角色的语音/文本惯性。",
                "这个默认只属于“当前主会话里的当前发言者”，不是该角色自己的私聊全局设置。",
            ])
        return ""
    mode_cn = "语音消息" if last_mode == "voice" else "文本消息"
    return "\n".join([
        "【上一轮回复方式状态（系统内部）】",
        f"上一条可见角色消息的承载方式：{mode_cn}。",
        "请把它作为回复方式惯性的强证据：如果用户本轮没有明确要求切换输出方式，必须延续上一条；用户本轮只是在问新问题、换话题、变短、用中文打字、没有再次说“语音”，都不等于要求切回文本。",
        "如果用户明确要求语音、文本、纯文本、文字、打字、text-only、no voice、不要语音、别发语音、录音或其它承载方式，请以用户本轮指令为准；若只是内容不适合语音，可由导演说明原因后切换。",
        "当用户说“用英语纯文本重新回复”“纯文本重新回复”“重新用文字/文本回复”“改成文字发”“这次不要语音”等，必须视为明确切换到文本承载，本轮 voice_reply.enabled=false；这里的“重新回复”是对上一条回复方式的纠正，不是继续语音模态。",
        "App 内置快捷消息「（请详细写出当前你的心理活动）」「（请详细写出当前你的身体状态）」「（请详细写出当前你看到的画面）」只是一次性文本描写查看，不是用户切换到文本模态；即使连续多轮使用这些描写快捷消息，也只让这些快捷回合临时用文本，之后若用户没有新的承载方式指令，继续沿用第一次描写快捷消息之前的语音/文本惯性。「（请推进剧情发展）」不是模态切换指令，之前是语音就继续语音。",
        "最终由导演综合当前用户消息、内容类型和该状态决定 voice_reply.enabled；若 Step 1 reason 未能说明“当前/本轮用户明确要求切换”，后端会按当前发言角色的状态变量校正回上述惯性。",
    ])


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_HIRAGANA_KATAKANA_RE = re.compile(r"[\u3040-\u30ff]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def _detect_reply_language_from_text(text: str) -> str:
    raw = str(text or "")
    if not raw.strip():
        return ""
    kana_count = len(_HIRAGANA_KATAKANA_RE.findall(raw))
    cyrillic_count = len(_CYRILLIC_RE.findall(raw))
    cjk_count = len(_CJK_RE.findall(raw))
    latin_count = sum(len(m.group(0)) for m in _LATIN_WORD_RE.finditer(raw))
    if kana_count >= 2:
        return "Japanese"
    if cyrillic_count >= 4 and cyrillic_count >= latin_count:
        return "Russian"
    if latin_count >= 12 and latin_count >= cjk_count * 2:
        return "English"
    if cjk_count >= 4 and cjk_count >= latin_count:
        return "Chinese"
    return ""


def _strip_internal_assistant_label_for_language(text: Any) -> str:
    return _INTERNAL_ASSISTANT_SPEAKER_LABEL_RE.sub("", str(text or ""), count=1).strip()


def _assistant_reply_language_text_candidates(msg: dict[str, Any]) -> list[str]:
    if not isinstance(msg, dict):
        return []
    candidates: list[str] = []

    def add(value: Any) -> None:
        text = _strip_internal_assistant_label_for_language(value)
        if text:
            candidates.append(text)

    voice_state = msg.get("voice_state") or msg.get("voiceState")
    if isinstance(voice_state, dict):
        add(voice_state.get("tts_text") or voice_state.get("ttsText"))
        add(voice_state.get("transcript"))
    add(msg.get("tts_text") or msg.get("ttsText"))
    add(msg.get("transcript"))
    fragments = msg.get("text_fragments") or msg.get("textFragments")
    if isinstance(fragments, list):
        add(" ".join(str(item or "").strip() for item in fragments if str(item or "").strip()))
    add(msg.get("content"))
    return candidates
