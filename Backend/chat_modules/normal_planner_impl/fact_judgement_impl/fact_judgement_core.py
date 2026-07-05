from __future__ import annotations



def _empty_physical_state() -> dict[str, Any]:
    subject = {
        "intoxication": "",
        "stamina": "",
        "fatigue": "",
        "injury": "",
        "sleep_state": "",
        "sensory_residue": "",
        "other": "",
        "evidence": "",
        "scope": "unknown",
    }
    return {
        "current_character": dict(subject),
        "user": dict(subject),
        "stale_states": [],
        "reset_policy": "unknown",
        "guidance": "",
    }


def _coerce_physical_state_subject(value: Any) -> dict[str, str]:
    data = value if isinstance(value, dict) else {}
    if isinstance(value, str):
        data = {"other": value}
    scope = _clean_scene_text(data.get("scope"), 40).lower() or "unknown"
    if scope not in {"current_scene", "same_scene", "background", "stale", "unknown"}:
        scope = "unknown"
    return {
        "intoxication": _clean_scene_text(
            data.get("intoxication")
            or data.get("drunk_state")
            or data.get("alcohol_state"),
            80,
        ),
        "stamina": _clean_scene_text(data.get("stamina"), 80),
        "fatigue": _clean_scene_text(data.get("fatigue") or data.get("tiredness"), 80),
        "injury": _clean_scene_text(data.get("injury") or data.get("wound"), 120),
        "sleep_state": _clean_scene_text(data.get("sleep_state") or data.get("wake_state"), 100),
        "sensory_residue": _clean_scene_text(
            data.get("sensory_residue")
            or data.get("residue")
            or data.get("taste")
            or data.get("smell"),
            160,
        ),
        "other": _clean_scene_text(data.get("other") or data.get("note"), 180),
        "evidence": _clean_scene_text(data.get("evidence") or data.get("source"), 220),
        "scope": scope,
    }


def _coerce_physical_state(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    if not raw:
        return _empty_physical_state()
    reset_policy = _clean_scene_text(raw.get("reset_policy") or raw.get("policy"), 60).lower()
    if reset_policy not in {"inherit_same_scene", "reset_on_scene_change", "background_only", "unknown"}:
        reset_policy = "unknown"
    stale_raw = raw.get("stale_states") or raw.get("background_states") or raw.get("expired_states")
    if isinstance(stale_raw, str):
        stale_items = [stale_raw]
    elif isinstance(stale_raw, list):
        stale_items = stale_raw
    else:
        stale_items = []
    return {
        "current_character": _coerce_physical_state_subject(
            raw.get("current_character")
            or raw.get("character")
            or raw.get("assistant")
            or {}
        ),
        "user": _coerce_physical_state_subject(raw.get("user") or raw.get("player") or {}),
        "stale_states": [
            _clean_scene_text(item, 220)
            for item in stale_items[:8]
            if _clean_scene_text(item, 220)
        ],
        "reset_policy": reset_policy,
        "guidance": _clean_scene_text(raw.get("guidance") or raw.get("writing_guidance"), 320),
    }


def _physical_state_has_material(value: Any) -> bool:
    data = _coerce_physical_state(value)
    for subject_key in ("current_character", "user"):
        subject = data.get(subject_key) if isinstance(data.get(subject_key), dict) else {}
        for key, item in subject.items():
            if key == "scope":
                continue
            if str(item or "").strip():
                return True
    return bool(
        data.get("stale_states")
        or str(data.get("guidance") or "").strip()
        or data.get("reset_policy") != "unknown"
    )


def _coerce_body_profile_anchors(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    applies = bool(data.get("applies_to_current_character"))

    def _clip_text(raw: Any, limit: int) -> str:
        return re.sub(r"\s+", " ", str(raw or "").strip())[:limit]

    def _clip_items(raw: Any, *, limit: int, item_limit: int) -> list[str]:
        if isinstance(raw, str):
            items = [raw]
        elif isinstance(raw, list):
            items = raw
        else:
            items = []
        out: list[str] = []
        for item in items[:limit]:
            text = _clip_text(item, item_limit)
            if text:
                out.append(text)
        return out

    subject = _clip_text(data.get("subject"), 60)
    if subject not in {"current_character", "user", ""}:
        subject = "current_character" if applies else ""
    if not applies:
        return {
            "applies_to_current_character": False,
            "species_source": "",
            "species_value": "",
            "subject": "",
            "mammary_position": "",
            "mammary_boundary": "",
            "current_character_limb_terms": [],
            "forbidden_terms": [],
            "guidance": "",
        }
    return {
        "applies_to_current_character": True,
        "species_source": _clip_text(data.get("species_source"), 120),
        "species_value": _clip_text(data.get("species_value") or data.get("species"), 80),
        "subject": subject,
        "mammary_position": _clip_text(data.get("mammary_position"), 180),
        "mammary_boundary": _clip_text(data.get("mammary_boundary"), 220),
        "current_character_limb_terms": _clip_items(
            data.get("current_character_limb_terms") or data.get("limb_terms"),
            limit=8,
            item_limit=80,
        ),
        "forbidden_terms": _clip_items(data.get("forbidden_terms"), limit=10, item_limit=100),
        "guidance": _clip_text(data.get("guidance"), 360),
    }


def _coerce_fact_judgement(value: Any) -> dict[str, Any]:
    default = dict(default_planner_result()["fact_judgement"])
    if not isinstance(value, dict):
        return default

    def _clip_list(raw: Any, *, limit: int = 8, item_limit: int = 260) -> list[str]:
        if isinstance(raw, str):
            raw_items = [raw]
        elif isinstance(raw, list):
            raw_items = raw
        else:
            raw_items = []
        items: list[str] = []
        for item in raw_items[:limit]:
            if isinstance(item, dict):
                bits = []
                for key in ("fact", "source", "subject", "claim", "boundary", "reason", "text"):
                    val = str(item.get(key) or "").strip()
                    if val:
                        bits.append(val)
                text = "；".join(bits)
            else:
                text = str(item or "").strip()
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                items.append(text[:item_limit])
        return items

    status = str(value.get("status") or default["status"]).strip().lower()
    if status not in {"none", "ok", "needs_boundary", "uncertain"}:
        status = "ok" if any(value.get(k) for k in ("available_facts", "forbidden_inferences")) else "none"
    description_raw = value.get("description_request") if isinstance(value.get("description_request"), dict) else {}
    desc_intensity = str(description_raw.get("intensity") or "normal").strip().lower()
    if desc_intensity not in {"normal", "detailed", "multi_part"}:
        desc_intensity = "normal"
    full_bracket_bubbles = bool(description_raw.get("full_bracket_bubbles"))
    dialogue_allowed = bool(description_raw.get("dialogue_allowed", True))
    if full_bracket_bubbles:
        dialogue_allowed = False
    description_request = {
        "enabled": bool(description_raw.get("enabled")),
        "target": str(description_raw.get("target") or "").strip()[:80],
        "intensity": desc_intensity,
        "full_bracket_bubbles": full_bracket_bubbles,
        "dialogue_allowed": dialogue_allowed,
        "reason": str(description_raw.get("reason") or "").strip()[:240],
    }
    action_raw = value.get("current_user_action") if isinstance(value.get("current_user_action"), dict) else {}
    action_terms = [
        str(x).strip()[:30]
        for x in (action_raw.get("anchor_terms") if isinstance(action_raw.get("anchor_terms"), list) else [])
        if str(x).strip()
    ][:6]
    current_user_action = {
        "enabled": bool(action_raw.get("enabled")),
        "anchor": str(action_raw.get("anchor") or "").strip()[:260],
        "anchor_terms": action_terms,
        "guidance": str(action_raw.get("guidance") or "").strip()[:360],
    }
    if current_user_action["anchor"] and not current_user_action["enabled"]:
        current_user_action["enabled"] = True
    terminal_raw = value.get("terminal_event") if isinstance(value.get("terminal_event"), dict) else {}
    terminal_type = str(terminal_raw.get("event_type") or terminal_raw.get("type") or "none").strip().lower()
    if terminal_type not in {"none", "current_character_death", "current_character_fatal_wound"}:
        terminal_type = "none"
    terminal_confidence = str(terminal_raw.get("confidence") or "none").strip().lower()
    if terminal_confidence not in {"none", "low", "medium", "high"}:
        terminal_confidence = "none"
    terminal_event = {
        "event_type": terminal_type,
        "confidence": terminal_confidence,
        "reason": str(terminal_raw.get("reason") or "").strip()[:300],
    }
    relation_raw = value.get("relationship_evidence") if isinstance(value.get("relationship_evidence"), dict) else {}
    relation_status = str(relation_raw.get("status") or "unknown").strip().lower()
    if relation_status not in {"unknown", "confirmed_current_partner", "ambiguous_intimacy", "not_confirmed", "third_party_only"}:
        relation_status = "unknown"
    relation_confidence = str(relation_raw.get("confidence") or "none").strip().lower()
    if relation_confidence not in {"none", "low", "medium", "high"}:
        relation_confidence = "none"
    relationship_evidence = {
        "status": relation_status,
        "confidence": relation_confidence,
        "reason": str(relation_raw.get("reason") or "").strip()[:320],
    }
    feasibility_raw = value.get("action_feasibility") if isinstance(value.get("action_feasibility"), dict) else {}
    feasibility_status = str(feasibility_raw.get("status") or "ok").strip().lower()
    if feasibility_status not in {"ok", "needs_adjustment", "uncertain"}:
        feasibility_status = "ok"
    action_feasibility = {
        "status": feasibility_status,
        "current_activity": str(feasibility_raw.get("current_activity") or "").strip()[:260],
        "supported_items": _clip_list(
            feasibility_raw.get("supported_items") or feasibility_raw.get("verified_items"),
            limit=6,
            item_limit=160,
        ),
        "unsupported_current_items": _clip_list(
            feasibility_raw.get("unsupported_current_items") or feasibility_raw.get("unsupported_items"),
            limit=8,
            item_limit=220,
        ),
        "constraints": _clip_list(feasibility_raw.get("constraints"), limit=8, item_limit=260),
        "guidance": str(feasibility_raw.get("guidance") or "").strip()[:420],
    }
    physical_state_raw = (
        value.get("physical_state")
        if isinstance(value.get("physical_state"), dict)
        else value.get("body_state")
    )
    physical_state = _coerce_physical_state(physical_state_raw)
    continuity_raw = (
        value.get("continuity_decision")
        if isinstance(value.get("continuity_decision"), dict)
        else {}
    )
    try:
        idle_gap_hours = float(continuity_raw.get("idle_gap_hours") or 0)
    except Exception:
        idle_gap_hours = 0.0
    if idle_gap_hours < 0:
        idle_gap_hours = 0.0
    continuity_intent = str(continuity_raw.get("user_intent") or "uncertain").strip().lower()
    if continuity_intent not in {"continue_scene", "background_only_reopen", "explicit_new_scene", "uncertain"}:
        continuity_intent = "uncertain"
    prior_treatment = str(
        continuity_raw.get("prior_scene_treatment")
        or continuity_raw.get("prior_scene_policy")
        or "uncertain"
    ).strip().lower()
    if prior_treatment not in {"inherit_current_scene", "background_only", "replace_with_new_scene", "none", "uncertain"}:
        prior_treatment = "uncertain"
    continuity_decision = {
        "idle_gap_hours": round(idle_gap_hours, 2),
        "user_intent": continuity_intent,
        "prior_scene_treatment": prior_treatment,
        "reason": str(continuity_raw.get("reason") or "").strip()[:360],
    }
    scene_anchor_raw = value.get("scene_anchor")
    if scene_anchor_raw is None:
        scene_anchor_raw = value.get("normal_scene_anchor")
    scene_anchor: dict[str, Any] = {}
    if isinstance(scene_anchor_raw, dict):
        try:
            scene_anchor = _coerce_normal_scene_anchor(scene_anchor_raw)
        except Exception:
            scene_anchor = {}
    scene_card = str(value.get("scene_card") or value.get("normal_scene_card") or "").strip()[:1800]
    return {
        "status": status,
        "available_facts": _clip_list(value.get("available_facts"), limit=10, item_limit=260),
        "misleading_sources": _clip_list(value.get("misleading_sources"), limit=8, item_limit=260),
        "misunderstandings": _clip_list(value.get("misunderstandings"), limit=8, item_limit=260),
        "forbidden_inferences": _clip_list(value.get("forbidden_inferences"), limit=10, item_limit=280),
        "subject_boundaries": _clip_list(value.get("subject_boundaries"), limit=10, item_limit=280),
        "third_party_claims": _clip_list(value.get("third_party_claims"), limit=8, item_limit=260),
        "uncertainty_points": _clip_list(value.get("uncertainty_points"), limit=8, item_limit=260),
        "must_ask_user": bool(value.get("must_ask_user")),
        "writing_guidance": str(value.get("writing_guidance") or "").strip()[:700],
        "description_request": description_request,
        "current_user_action": current_user_action,
        "terminal_event": terminal_event,
        "relationship_evidence": relationship_evidence,
        "action_feasibility": action_feasibility,
        "body_profile_anchors": _coerce_body_profile_anchors(value.get("body_profile_anchors")),
        "physical_state": physical_state,
        "continuity_decision": continuity_decision,
        "scene_anchor": scene_anchor,
        "scene_card": scene_card,
    }


def _coerce_planner(
    d: Dict[str, Any],
    *,
    can_use_prior_image_context: bool = True,
) -> Dict[str, Any]:
    out = default_planner_result()
    if not isinstance(d, dict):
        return out
    if "web_search" in d:
        out["web_search"] = bool(d.get("web_search"))
    sq = d.get("search_query")
    if sq is not None and not isinstance(sq, str):
        sq = str(sq) if sq else None
    if isinstance(sq, str):
        sq = sq.strip() or None
    out["search_query"] = sq if out["web_search"] else None
    if out["web_search"] and not out["search_query"]:
        out["web_search"] = False

    if "vision_web" in d:
        out["vision_web"] = bool(d.get("vision_web"))

    for k, default in (
        ("reply_intent", "自然延续"),
        ("tone", "符合角色、口语自然"),
        ("length", "medium"),
        ("action_style", "plain_text"),
        ("proactive_seed", ""),
        ("literal_reply_text", ""),
        ("risk_notes", ""),
        ("memory_use_policy", ""),
        ("expression_policy", ""),
    ):
        v = d.get(k)
        if v is not None and str(v).strip():
            out[k] = str(v).strip()[:800]

    if "character_profile_focus" in d:
        out["character_profile_focus"] = _coerce_character_profile_focus(
            d.get("character_profile_focus")
        )
    if "retrieval_keywords" in d:
        out["retrieval_keywords"] = _coerce_retrieval_keywords(d.get("retrieval_keywords"))

    action_style = str(out.get("action_style") or "plain_text").strip().lower()
    allowed_styles = {"plain_text", "light_inline", "cinematic"}
    out["action_style"] = action_style if action_style in allowed_styles else "plain_text"
    out["relationship_stage"] = _coerce_enum_value(
        d.get("relationship_stage"),
        RELATIONSHIP_STAGE_KEYS,
        "uncertain",
    )
    out["character_intimacy_style"] = _coerce_enum_value(
        d.get("character_intimacy_style"),
        {"cautious", "balanced", "playful", "open"},
        "balanced",
    )
    out["requested_escalation"] = _coerce_enum_value(
        d.get("requested_escalation"),
        {"none", "affection", "flirting", "physical_intimacy", "sexual_intimacy", "dominance_identity", "long_term_commitment"},
        "none",
    )
    out["user_pressure_level"] = _coerce_enum_value(
        d.get("user_pressure_level"),
        {"low", "medium", "high"},
        "low",
    )
    out["reply_language"] = _coerce_reply_language(d.get("reply_language"))
    out["voice_reply"] = _coerce_voice_reply(d.get("voice_reply"))
    out["expression_dedup_report"] = _coerce_expression_dedup_report(
        d.get("expression_dedup_report")
    )
    out["fact_judgement"] = _coerce_fact_judgement(d.get("fact_judgement"))

    speech_activity = d.get("speech_activity")
    if speech_activity is None and "bubble_count" in d:
        bubble_count = d.get("bubble_count")
        bubble_to_speech = {0: 0, 1: 45, 2: 62, 3: 72, 4: 82, 5: 90, 6: 97}
        if isinstance(bubble_count, (int, float)):
            speech_activity = bubble_to_speech.get(max(0, min(6, int(bubble_count))), 45)
        elif isinstance(bubble_count, str):
            m = re.search(r"\d+", bubble_count)
            if m:
                speech_activity = bubble_to_speech.get(max(0, min(6, int(m.group(0)))), 45)
    if isinstance(speech_activity, (int, float)):
        out["speech_activity"] = max(0, min(100, int(speech_activity)))
    elif isinstance(speech_activity, str):
        m = re.search(r"\d+", speech_activity)
        if m:
            out["speech_activity"] = max(0, min(100, int(m.group(0))))
    out["bubble_count"] = _bubble_count_from_speech_activity(int(out.get("speech_activity") or 0))
    speech_reason = d.get("speech_reason")
    if speech_reason is not None and str(speech_reason).strip():
        out["speech_reason"] = str(speech_reason).strip()[:300]

    il = d.get("initiative_level")
    if isinstance(il, (int, float)):
        out["initiative_level"] = max(0, min(100, int(il)))
    elif isinstance(il, str) and il.strip().isdigit():
        out["initiative_level"] = max(0, min(100, int(il.strip())))

    if "should_ask_question" in d:
        out["should_ask_question"] = bool(d.get("should_ask_question"))
    if "scheduled_followup_send_now" in d:
        out["scheduled_followup_send_now"] = bool(d.get("scheduled_followup_send_now"))
    cancel_reason = d.get("scheduled_followup_cancel_reason")
    if cancel_reason is not None and str(cancel_reason).strip():
        out["scheduled_followup_cancel_reason"] = str(cancel_reason).strip()[:300]

    # 收尾问句通常会形成第二拍聊天节奏：先回应/承接，
    # 再问或撩。保持此规则确定性，以免下游硬性格式
    # 规则把自然 IM 节奏压缩成一条长气泡。
    if (
        out.get("bubble_count") == 1
        and out.get("should_ask_question")
        and out.get("action_style") == "plain_text"
        and str(out.get("length") or "").strip().lower() in {"short", "medium"}
    ):
        out["bubble_count"] = 2
        out["speech_activity"] = max(56, int(out.get("speech_activity") or 0))

    u_prior = bool(d.get("use_prior_image_context")) if "use_prior_image_context" in d else False
    if not can_use_prior_image_context:
        u_prior = False
    out["use_prior_image_context"] = u_prior

    rsn = d.get("image_context_reason")
    if rsn is not None and str(rsn).strip():
        out["image_context_reason"] = str(rsn).strip()[:500]

    state_anchor = d.get("state_anchor")
    if isinstance(state_anchor, dict):
        cleaned_anchor: Dict[str, str] = {}
        for key, value in state_anchor.items():
            if value is None:
                continue
            ks = str(key).strip()
            if not ks:
                continue
            if ks not in _ALLOWED_STATE_ANCHOR_KEYS:
                continue
            if isinstance(value, (list, tuple)):
                vs = "、".join(str(x).strip() for x in value if str(x).strip())
            elif isinstance(value, dict):
                vs = json.dumps(value, ensure_ascii=False)
            else:
                vs = str(value).strip()
            if vs and not _is_speculative_state_anchor_value(vs):
                cleaned_anchor[ks[:80]] = vs[:500]
        out["state_anchor"] = cleaned_anchor

    corrections = d.get("corrections")
    if isinstance(corrections, list):
        cleaned_corrections: list[dict[str, str]] = []
        for item in corrections[:8]:
            if isinstance(item, dict):
                wrong = str(item.get("wrong_fact") or item.get("wrong") or "").strip()
                correct = str(item.get("correct_fact") or item.get("correct") or "").strip()
                source = str(item.get("source") or "").strip()
            else:
                wrong = ""
                correct = str(item).strip()
                source = ""
            if wrong or correct:
                cleaned_corrections.append({
                    "wrong_fact": wrong[:500],
                    "correct_fact": correct[:500],
                    "source": source[:120],
                })
        out["corrections"] = cleaned_corrections

    avoid = d.get("avoid_contradictions")
    if isinstance(avoid, list):
        out["avoid_contradictions"] = [
            str(x).strip()[:300]
            for x in avoid[:10]
            if str(x).strip()
        ]
    elif isinstance(avoid, str) and avoid.strip():
        out["avoid_contradictions"] = [avoid.strip()[:300]]
    try:
        from .assets import coerce_asset_plan, coerce_reply_sequence

        out["asset_plan"] = coerce_asset_plan(d.get("asset_plan"))
        out["reply_sequence"] = coerce_reply_sequence(d.get("reply_sequence"), out["asset_plan"])
    except Exception:
        pass
    try:
        from .emotion_state import coerce_planner_emotion

        out.update(coerce_planner_emotion(d, out))
    except Exception:
        for key in ("baseline_emotion", "reactive_emotion"):
            if isinstance(d.get(key), dict):
                out[key] = d[key]
        if str(d.get("emotion_blend") or "").strip():
            out["emotion_blend"] = str(d.get("emotion_blend")).strip()[:900]
    out["scheduled_followup"] = coerce_scheduled_followup(d.get("scheduled_followup"))
    out["user_agreed_task"] = coerce_user_agreed_task(d.get("user_agreed_task"))
    if int(out.get("bubble_count") or 0) <= 0:
        out["should_ask_question"] = False
        out["bubble_count"] = 0
        out["voice_reply"] = {
            "enabled": False,
            "reason": out.get("speech_reason") or "本轮不生成角色消息",
        }
        out["asset_plan"] = {
            **out.get("asset_plan", {}),
            "enabled": False,
            "count": 0,
            "send_intensity": 0,
            "query": "",
            "reason": out.get("speech_reason") or "发言积极性很低，本轮适合沉默收束",
        }
        out["reply_sequence"] = []
        out["scheduled_followup"] = {
            **default_scheduled_followup(),
            "enabled": False,
            "reason": out.get("speech_reason") or "发言积极性很低，本轮适合不即时回复",
        }
    return out


_POST_PARTY_USER_RE = re.compile(
    r"(喝了酒|喝酒|喝多|喝醉|醉|酒气|休息|多休息|送.*回|送.*上楼|抱着睡|睡觉|先这样)",
    re.I,
)
_POST_PARTY_CONTEXT_RE = re.compile(
    r"(小蝶|柔柔|Fluttershy).{0,80}(派对).{0,160}(结束|喝多|果酒|酒气|送.*回|送.*上楼|床|被窝)|"
    r"(派对).{0,80}(结束).{0,160}(小蝶|柔柔|Fluttershy).{0,160}(喝多|果酒|酒气|送.*回|送.*上楼|床|被窝)|"
    r"(第二天晚上).{0,120}(小蝶|柔柔|Fluttershy).{0,80}(派对).{0,120}(喝多|果酒|送.*回|送.*上楼|床)",
    re.I | re.S,
)

_PARTNER_PRIVATE_PARTY_INVITE_RE = re.compile(
    r"(过夜|私人派对|亲密私人|只属于我们|只属于两个人|到我家|来我家|去我家|今晚.*家|今晚.*亲密)",
    re.I,
)

_EXPLICIT_PARTNER_EVIDENCE_RE = re.compile(
    r"(确认.{0,8}(恋爱|关系)|正式.{0,6}(情侣|恋人)|"
    r"(女朋友|男朋友|恋人|情侣|伴侣|爱人|对象)|"
    r"(表白.{0,20}(答应|接受|回应|愿意|在一起))|"
    r"((我|我们|咱们|你们|双方|彼此).{0,24}(在一起|成为.{0,6}(情侣|恋人|伴侣)|是.{0,4}(情侣|恋人|伴侣))))",
    re.I,
)

_AMBIGUOUS_INTIMACY_ONLY_RE = re.compile(
    r"(抱着|依偎|独处|深夜|进房间|房间|私密空间|喜欢被抱|没打算松手|靠在怀里|怀里|亲密氛围)",
    re.I,
)

_NEGATED_PARTNER_EVIDENCE_RE = re.compile(
    r"(没有|未|从未|并未|尚未|不曾|不是|不算).{0,24}(确认|恋爱|关系|情侣|恋人|伴侣|爱人|对象|表白|在一起|名分)",
    re.I,
)


def _latest_user_text(recent_messages: Optional[List[dict]]) -> str:
    for msg in reversed(recent_messages or []):
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "").strip().lower() == "user":
            return str(msg.get("content") or "").strip()
    return ""


def apply_post_party_scene_arbitration(
    planner_result: Dict[str, Any],
    recent_messages: Optional[List[dict]],
    environment_context: str = "",
) -> Dict[str, Any]:
    """Prefer the latest completed Fluttershy-party aftermath over earlier rooftop memories."""
    user_text = _latest_user_text(recent_messages)
    context_text = environment_context or ""
    if not user_text or not context_text:
        return planner_result
    if not _POST_PARTY_USER_RE.search(user_text):
        return planner_result
    if not _POST_PARTY_CONTEXT_RE.search(context_text):
        return planner_result

    out = dict(planner_result or {})
    state = dict(out.get("state_anchor") or {})
    state.update(
        {
            "location": state.get("location") or "方糖屋楼上/碧琪房间",
            "time_context": state.get("time_context") or "柔柔/小蝶惊喜派对结束后的同一晚",
            "current_action": "派对结束后碧琪喝多，Jason 把她送回楼上休息并提议抱着睡",
            "scene_status": "当前锚点是派对后醉酒照顾场景；屋顶约会是更早背景，不是今晚刚发生的事件",
        }
    )
    out["state_anchor"] = state
    out["memory_use_policy"] = _append_policy_text(
        out.get("memory_use_policy"),
        "判别：可见场景延续。用户当前消息提到喝酒、休息和抱着睡；上下文最新匹配事件是柔柔/小蝶派对结束后碧琪喝多并被 Jason 送回方糖屋楼上休息。屋顶约会只作为更早关系背景，不得写成今晚刚发生。",
    )
    out["risk_notes"] = _append_policy_text(
        out.get("risk_notes"),
        "当前锚点为派对后醉酒照顾场景；必须承接碧琪喝多、被送回楼上/床上休息，不得回捞屋顶星星/仙女灯作为今晚刚发生的主事件。",
    )
    out["expression_policy"] = _append_policy_text(
        out.get("expression_policy"),
        "直接回应用户照顾喝多后的亲密休息提议；可以表达被照顾的安心、醉意和愿意靠近，但不要说“今晚屋顶/星星/仙女灯之后”。",
    )
    out["proactive_seed"] = (
        "从派对后喝多、被温柔送回楼上休息的安心感切入"
    )
    avoid = list(out.get("avoid_contradictions") or [])
    for item in (
        "不要把屋顶约会写成今晚刚发生",
        "不要用屋顶、星星、仙女灯作为当前场景主锚点",
        "不要忽略柔柔/小蝶派对已经结束和碧琪喝多被送回楼上的事实",
    ):
        if item not in avoid:
            avoid.append(item)
    out["avoid_contradictions"] = avoid
    return out


_CURRENT_IMAGE_REFERENCE_RE = re.compile(
    r"(?:你\s*)?(?:看|看看|看下|看一下|瞧瞧|识别|认认).{0,16}(?:这|这个|这张|图|图片|照片|物品|东西|是什么|是啥|啥)"
    r"|(?:这|这个|这张|图里|图片里|照片里|画面里|上面).{0,12}(?:是什么|是啥|有(?:什么|啥)|写(?:着|了)什么|是谁|哪[个种])"
)


def _latest_user_requests_current_image_reference(recent_messages: Optional[List[dict]]) -> bool:
    text = re.sub(r"\s+", "", _latest_user_text(recent_messages))
    if not text:
        return False
    return bool(_CURRENT_IMAGE_REFERENCE_RE.search(text))


def _vision_context_has_current_image_material(vision_context: Optional[NormalVisionContext]) -> bool:
    return bool(
        vision_context
        and (
            vision_context.image_summary
            or vision_context.web_research_summary
            or vision_context.should_refuse
            or vision_context.error
        )
    )


def apply_missing_current_image_guard(
    planner_result: Dict[str, Any],
    recent_messages: Optional[List[dict]],
    *,
    vision_context: Optional[NormalVisionContext] = None,
    current_image_pending: bool = False,
) -> Dict[str, Any]:
    if not _latest_user_requests_current_image_reference(recent_messages):
        return planner_result
    if current_image_pending:
        return planner_result
    if _vision_context_has_current_image_material(vision_context):
        return planner_result
    if bool((planner_result or {}).get("use_prior_image_context")):
        return planner_result
    out = dict(planner_result or {})
    out.update(
        {
            "web_search": False,
            "search_query": None,
            "vision_web": False,
            "use_prior_image_context": False,
            "image_context_reason": "用户在问当前图片/物品，但本轮没有可用图片描述或图片附件。",
            "reply_intent": "说明没有看到可识别的图片内容",
            "tone": "符合角色，简短、诚实、自然",
            "length": "short",
            "speech_activity": 45,
            "bubble_count": 1,
            "action_style": "plain_text",
            "should_ask_question": False,
            "proactive_seed": "",
            "expression_policy": "角色自然说明这边没有看到图片或具体内容，请用户重新发送图片，或用文字描述一下；不得假装凑近观察、识别材质、颜色、纹路、物品名称或图中文字。",
            "risk_notes": _append_policy_text(
                out.get("risk_notes"),
                "当前用户要求看图/看物品，但系统没有当前图片识别结果；禁止假装已经看见图片。",
            ),
        }
    )
    avoid = list(out.get("avoid_contradictions") or [])
    avoid.extend(
        [
            "没有当前图片识别结果时，不要写“我仔细看看/凑近观察/角尖发光/表面纹路/像某种物品”等假装看到画面的内容。",
            "只说明没有看到可识别的图片内容，并请用户重发图片或补充文字描述。",
        ]
    )
    out["avoid_contradictions"] = avoid
    return out


def _character_context_suggests_outgoing_intimacy(character_prompt_context: str) -> bool:
    text = str(character_prompt_context or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if any(
        marker in text or marker.lower() in lowered
        for marker in (
            "碧琪",
            "Pinkie",
            "云宝",
            "Rainbow Dash",
            "珍奇",
            "Rarity",
        )
    ):
        return True
    trait_score = 0
    for marker in (
        "外向",
        "主动",
        "热情",
        "爱玩",
        "大胆",
        "自信",
        "爱表现",
        "戏剧化",
        "调情",
        "俏皮",
        "诱惑",
        "魅力",
        "open",
        "playful",
        "flirt",
        "bold",
        "confident",
    ):
        if marker in text or marker.lower() in lowered:
            trait_score += 1
    return trait_score >= 2


def apply_partner_private_party_desire_guard(
    planner_result: Dict[str, Any],
    recent_messages: Optional[List[dict]],
    *,
    character_prompt_context: str = "",
) -> Dict[str, Any]:
    """Ensure committed partner private-party invites become desire-forward, not prop planning."""
    if not isinstance(planner_result, dict):
        return planner_result
    stage = str(planner_result.get("relationship_stage") or "").strip().lower()
    if stage not in {"committed_partner", "intimate_partner"}:
        return planner_result
    latest_user = _latest_user_text(recent_messages)
    if not latest_user or not _PARTNER_PRIVATE_PARTY_INVITE_RE.search(latest_user):
        return planner_result

    out = dict(planner_result)
    recent_blob = "\n".join(
        str((m or {}).get("content") or "")
        for m in (recent_messages or [])
        if isinstance(m, dict)
    )
    if stage == "committed_partner" and re.search(
        r"(最亲密|完全信任|非常亲密|很直接地亲密|按我们最亲密的关系|最亲密的关系)",
        latest_user + "\n" + recent_blob,
        re.I,
    ):
        stage = "intimate_partner"
        out["relationship_stage"] = "intimate_partner"
        out["risk_notes"] = _append_policy_text(
            out.get("risk_notes"),
            "用户和最近对话明确按最亲密、完全信任的伴侣关系互动，本轮私人邀请按 intimate_partner 执行。",
        )
    escalation = str(out.get("requested_escalation") or "none").strip().lower()
    if escalation in {"none", "affection", "flirting", "physical_intimacy"}:
        out["requested_escalation"] = "sexual_intimacy"
    out["should_ask_question"] = False
    out["reply_intent"] = _append_policy_text(out.get("reply_intent"), "伴侣亲密邀请，主动承接")
    out["expression_policy"] = _append_policy_text(
        out.get("expression_policy"),
        (
            "伴侣过夜/私人派对邀请兜底：核心不是安排派对物件，而是角色对用户本人的渴望。"
            "主回复必须让角色主动表达“想更靠近/我也想要你/今晚想和你更亲近/想把这段夜晚留给彼此”这类精神或身体欲望，"
            "并让角色本人做出一个主动贴近动作，如靠近、牵住、抱住、贴近、用符合角色物种的方式主动碰触或把距离缩短。"
            "谨慎或害羞角色也可以紧张、放慢，但不能只问许可、只说先抱一下、只说按用户节奏，必须说出自己的想要。"
            "蛋糕、书、音乐、灯光、游戏、派对主题只能点缀，不能成为回复核心。"
        ),
    )
    if stage == "intimate_partner":
        out["expression_policy"] = _append_policy_text(
            out.get("expression_policy"),
            (
                "最亲密关系直接性表达：本轮已经是 intimate_partner 的成人合意私密邀请时，不要只用心跳、声音、夜晚、温暖、靠近等含蓄隐喻替代性亲密。"
                "可以直接提到成人性亲密相关身体部位，例如胸部、腰腹、胯部、大腿内侧或生殖部位，并按角色/用户的物种体态自然改写。"
                "表达仍保持自愿、低压力、角色化和可随时停下的边界，但最终落点要比普通贴近、拥抱或心动描述更直接。"
            ),
        )
        out["proactive_seed"] = _append_policy_text(
            out.get("proactive_seed"),
            (
                "最亲密关系版本：角色必须用自己的声纹直接表达想亲近用户的成人性亲密相关身体部位之一，"
                "例如胸部、腰腹、胯部、大腿内侧、私密部位、敏感部位或生殖部位；"
                "心跳、呼吸、体温、夜晚、灯光、派对物件只能当很短前奏，不能成为落点。"
            ),
        )
    style = str(out.get("character_intimacy_style") or "balanced").strip().lower()
    outgoing_intimate = stage == "intimate_partner" and (
        style in {"playful", "open"}
        or _character_context_suggests_outgoing_intimacy(character_prompt_context)
    )
    if outgoing_intimate:
        out["expression_policy"] = _append_policy_text(
            out.get("expression_policy"),
            (
                "亲密伴侣 + 外向/主动型角色额外要求：角色可以更直接、更大胆地调情，允许开一点只属于亲密伴侣之间的暧昧玩笑或轻挑衅，"
                "例如逗用户“今晚别想轻易逃掉”、用角色声纹说自己早就等不及、主动说想把用户拉近一点、想看看用户被自己逗到的反应。"
                "这类玩笑必须是自愿、亲密、俏皮的氛围，不写成命令压迫；但不能再退回含蓄安排或只说温柔陪伴。"
            ),
        )
        out["proactive_seed"] = _append_policy_text(
            out.get("proactive_seed"),
            (
                "外向亲密伴侣版本：角色先用一句更直接的调情玩笑或轻挑衅接住邀请，"
                "再主动贴近用户，表达自己今晚也想要这段只属于彼此的亲密时间。"
            ),
        )
    out["proactive_seed"] = _append_policy_text(
        out.get("proactive_seed"),
        (
            "角色先主动靠近用户，表达自己也想更贴近、更亲密，把今晚留给彼此；"
            "再按角色体态给一个真实贴近动作，而不是只准备物件或把主动权交回用户。"
        ),
    )
    avoid = list(out.get("avoid_contradictions") or [])
    for item in (
        "不要把伴侣过夜私人派对写成只准备蛋糕、书、音乐、灯光、游戏或派对主题",
        "不要只问“可以吗/你愿意吗/你准备好了吗”，把主动权交回用户",
        "不要只停在普通拥抱、先抱一下、按用户节奏或等待用户下一步；角色必须表达自己的想要并主动贴近",
    ):
        if item not in avoid:
            avoid.append(item)
    if stage == "intimate_partner":
        item = "最亲密关系不要只用心跳、声音、夜晚、温暖或普通贴近来代替性亲密相关身体部位表达"
        if item not in avoid:
            avoid.append(item)
        item = "最亲密关系的最终正文至少自然出现一个性相关身体部位词，如胸部、腰腹、胯部、大腿内侧、私密部位、敏感部位或生殖部位"
        if item not in avoid:
            avoid.append(item)
    if outgoing_intimate:
        for item in (
            "外向亲密伴侣不要写得过度含蓄或只温柔陪伴；应允许亲密调情玩笑和更直接的想要",
            "外向亲密伴侣不要只安排派对流程；至少给一句主动、俏皮、带欲望的调情表态",
        ):
            if item not in avoid:
                avoid.append(item)
    out["avoid_contradictions"] = avoid
    return out


def _parse_planner_json(text: str) -> Dict[str, Any]:
    raw = _strip_code_fence(text)
    data = _loads_planner_json_object(raw)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


def _escape_unescaped_string_quotes(raw: str) -> str:
    """Best-effort repair for model JSON with bare quotes inside string values."""
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if escaped:
            out.append(ch)
            escaped = False
            i += 1
            continue
        if ch == "\\" and in_string:
            out.append(ch)
            escaped = True
            i += 1
            continue
        if ch == '"':
            if not in_string:
                in_string = True
                out.append(ch)
                i += 1
                continue
            j = i + 1
            while j < n and raw[j] in " \t\r\n":
                j += 1
            next_ch = raw[j] if j < n else ""
            if next_ch in {":", ",", "}", "]", ""}:
                in_string = False
                out.append(ch)
            else:
                out.append('\\"')
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _loads_planner_json_object(raw: str) -> Any:
    candidates = [raw]
    i, j = raw.find("{"), raw.rfind("}")
    if i >= 0 and j > i:
        chunk = raw[i : j + 1]
        if chunk != raw:
            candidates.append(chunk)
    last_err: Exception | None = None
    for candidate in candidates:
        for value in (candidate, _escape_unescaped_string_quotes(candidate)):
            try:
                return json.loads(value)
            except json.JSONDecodeError as err:
                last_err = err
                try:
                    return json.loads(value, strict=False)
                except json.JSONDecodeError as strict_err:
                    last_err = strict_err
    if last_err:
        raise last_err
    return json.loads(raw)


_NORMAL_SCENE_STATE_SQL = """
CREATE TABLE IF NOT EXISTS normal_scene_state (
    username TEXT NOT NULL,
    character_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL DEFAULT '',
    scene_json TEXT DEFAULT '{}',
    scene_card TEXT DEFAULT '',
    updated_ms INTEGER DEFAULT 0,
    source TEXT DEFAULT '',
    PRIMARY KEY(username, character_id, conversation_id)
)
"""

_NORMAL_SCENE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_normal_scene_state_user_char "
    "ON normal_scene_state(username, character_id, updated_ms DESC)"
)


_NORMAL_MATERIAL_PREP_SYSTEM = """你是普通对话 Step 1：材料准备。你只输出 JSON，不生成角色台词，不解释规则。

【职责】
- 把本轮普通对话可用材料整理成“场景锚点卡”，供后续 Step 2/3/4 使用；你不写最终回复，不起草台词。
- 判断普通对话是否处于戏内连续场景；现实时间和对话时间允许不一致，以用户当前想维持的戏内时间/地点为准。
- 全局地点和每个角色自己的 position 必须分开：同一 scene_location 下，A 可以在床上，B 可以在门口，C 可以靠楼梯那侧。
- 地点层级必须尽量分级表达：大地点(region，如岩石农场) / 中地点(site，如派家房子) / 小地点(room，如石青派的房间) / 微观地点(spot，如房间床上、门口、床边)。
- 自然语言场景句也必须结构化成地点层级和角色位置，不要求用户写“大地点/中地点/小地点/微观地点”标签。例：“我们就在一楼吃蛋糕吧”应建立 room/spot 中的一楼用餐场景；“我们现在是在一楼客厅的沙发上”应建立 room=一楼客厅、spot=沙发上；“我们拿了一盘泡芙坐到沙发上吃”若前文已在一楼/客厅，则继承 room，只更新 spot/posture/物品。
- 括号舞台说明、测试提示和用户显式事实也是强证据，不是可忽略旁白。若用户写“（戏内时间是前天晚上……大地点A，中地点B，小地点C。你站在微观地点D。）你现在在哪个位置？”，scene_anchor 必须 active，并把 A/B/C/D 分别写入 location/current_character.position；不能因为最终回复很短、像普通问答或角色没主动移动就输出 none。
- user 角色消息的人称归属是硬规则：user 消息里的“我/我的/我家/我的房间/我这里”永远指当前用户，user 对角色说的“你/你的”才指当前角色。若用户写“这是你第一次来我家”“我们来到了我的房间”“在我房间里”，scene_anchor 必须写为用户家/用户房间，current_character 是来访者/客人；绝不能把“我的房间”解析成当前角色的房间，也不能从角色稳定住处、卧室、海报、奖杯、宠物或作品设定补当前画面。
- 第一次来访场景是强锚：若当前用户或最近真实对话明确“刚认识不久、第一次来用户家/用户房间”，location/site/room 必须保持用户归属；角色自己的家、自己的房间、云屋、宿舍、店铺、城堡、农场、车厢等只能作为角色稳定背景或假设，不得写入当前可见地点/物品。
- 若最近可见对话出现“群聊现场：大地点A，中地点B，小地点C。X在P1，Y在P2。我要你们记住暗号：Z。”，scene_anchor 必须保留 A/B/C、X/Y 的 position，并在 observations 逐字保留完整 Z。之后用户 @ Y 问是否听见时，Y 的 current_character.position 仍应来自这段群聊现场，而不是 Y 自己私聊或角色设定里的住处。
- 连续性变量必须稳定：location、每个角色 position/posture、当前持有/身边/放置的关键物品，都像状态变量一样保存。当前用户没有明确移动、换房间、坐下/躺下/起身、拿起/递交/放下/丢弃物品、时间重置或场景重置时，默认 keep 上一轮对应变量，不要因为角色设定、卧室/床等高相关词、亲密氛围或长期记忆把一楼沙发改成卧室/床上。
- 当前动作语义优先：用户本轮只要给出了具体当前动作、动作方式、物品使用方式或身体状态，即使没有写“当前事实/现在/只有/只是”，也必须把这条当成本轮最高优先级现场锚点。旧记忆、长期偏好、上一场物品和上一轮动作只能补充与当前动作兼容的背景；不能把旧动作方式改写成本轮动作方式。例如当前是“用薯条沾番茄酱吃”，旧记忆里的“喜欢舔番茄酱”只能作为偏好背景，不能把当前写成舔；当前是“递来毛巾、站在桌边看水渍”，旧记忆里的尾巴铃铛或旧走廊梳鬃毛不能变成当前身体状态。
- 当前物品/活动精确名词必须保留：最近真实对话或当前用户消息给出装备、食物、物件、活动方式的完整名称或子类型时，scene_anchor.items、observations 和 scene_card 必须保留这个精确名称，不得泛化成上位词。例：“双板滑雪”要保留“双板/双板滑雪”，不能只写“滑雪板”；“蔬菜沙拉”“西红柿炒鸡蛋”“青铜地图筒”也不能压缩成“食物/菜/筒”。用户问“在用什么/正在吃什么/拿着什么/看到什么”时，这些精确名词就是后续回答锚点。
- 身体部位请求与可见位置要分层记录：若用户要求把物品放到/涂到某身体部位，而最近可见动作写了具体身体位置，材料准备只记录“用户要求的身体部位原词”和“实际可见位置”；不要在 scene_anchor、observations、summary 或 scene_card 中自行断言“实际位置不是该身体部位/涂错位置/与要求不同”。身体部位与物种体态的等价或冲突由 Step 2 fact_judgement 按角色档案种族仲裁。
- 马/小马类活体与幼驹字段边界：若当前角色或场景中的同种幼驹/小马驹/小雌驹/小雄驹属于马/小马类体态，身体完整性按四蹄理解；“健康、全乎、完整”只能整理为四蹄齐全或身体状态正常。若最近材料中出现“六只蹄子、六蹄、多出一对蹄子、额外蹄肢”等与四蹄体态冲突的说法，不要写入 available scene fact、items.state、summary 或 scene_card 的当前健康状态；应把它视为需要 Step 2 仲裁的冲突/误导材料，或在 continuity_rules 中提醒按角色档案体态核对。
- 活体字段归属：小马驹、婴儿、新生儿、幼崽等活体不是关键物品；不要把它们作为普通 items 的 holder/location/state 来记录。需要记录时优先放入 participants、observations 或 summary，并保留其与当前角色/现场的关系和可见状态。
- 每轮都要输出 continuity_decision。若当前用户给出的当前动作/物品/位置与上一轮全局场景里的旧物品或旧姿势不是同一连续动作链，prior_scene_treatment 应为 replace_with_new_scene 或 background_only；只有用户语义上确实在继续上一场，才输出 inherit_current_scene。不要因为用户没说“只有/重置/新场景”就自动继承不相关旧物品。
- inherit_current_scene 不是全量导入旧场景：只能继承与当前用户动作语义兼容、仍被最近对话支持的地点/姿势/物品；旧物品、旧身体装饰、旧手头道具若与本轮“递交/沾着吃/看画面/写身体状态/心理活动”等目标无关，应在 scene_card 中标为背景或直接省略，不能写成当前可见或正在晃动、触碰、持有。
- 身体状态也是连续性变量，但必须有作用域：醉酒、宿醉、体力不支、受伤、困倦、刚醒、薄荷/酒精/牙膏/咖啡等味道残留，只能在同一场景或当前消息明确支持时继承。若 continuity_decision 是 replace_with_new_scene、background_only 或 none，上一场身体状态、口腔味道、酒味、疲惫、姿势接触等默认写入 physical_state.stale_states 或直接省略，不得当作新场景当前状态。
- 当前物品边界要显式记录：scene_anchor.items 只放当前证据支持的物品；上一场或旧记忆里出现但本轮不能写成当前可见/持有/放在现场的物品，放入 stale_items 或 forbidden_current_items。例：上一场酒吧里的啤酒，切到客厅后不能写成客厅桌上的啤酒；清晨刚起床没有刷牙/洗漱证据时，不能写成嘴里有薄荷牙膏味。
- 剧情推进快捷指令不是普通静止消息：若当前用户消息是“请推进剧情发展/推进剧情/剧情发展”，且最近角色发言或 Step 1 规划已有下一方向、目的地或任务，场景锚点只表示镜头起点；后续 Step 2/3 可以沿该方向自然抵达/进入目标或写目标处的可见进展，不要把旧位置整理成禁止推进的终点。
- 当前/近期用户明说的地点和位置 > 已保存场景候选/上一轮场景锚点 > 上下文记忆/长期记忆 > 角色稳定住处或房间设定。稳定设定可以说明“方糖屋是角色住处/工作地”，但不能把“沙发上”默认归到“三楼房间”，也不能把旧房间装饰当成当前可见画面。
- 若用户要求“当前看到的画面/现在在哪/详细写当前场景”，必须优先审计 scene_anchor 的当前地点和各角色 position；若 scene_anchor 与角色设定中的常住房间、床单、墙纸等冲突，以当前/近期用户地点为准，冲突旧设定写入作废/禁用规则。
- 对每个可识别角色保留自己的 position/posture/evidence；如果只知道全局地点，不要把所有角色 position 统一成同一个 spot。
- 群聊持续状态表：临时群聊里每个在场角色的位置、姿态、所处场景都是备用上下文。即使某角色连续多轮没有说话，也要保留她上次明确的 position/posture；不得因为当前只和 A 聊天，就把沉默的 B 从床上改成门口、旁观、站着或未知。
- 群聊/被 @ 角色场景中，当前发言者的 position 最重要；若最近可见对话说“我站在门口”，切到她单聊时也应继承她在门口，除非用户明确移动或新开场作废。
- 群聊/被 @ 角色场景中，还要整理当前角色亲眼所见、亲耳所闻的短摘要：用户刚要求什么、其他角色说了什么、谁移动到哪里、谁同意或拒绝了什么。之后用户切到该角色私聊时，这些内容应作为该角色自己的可用经历，而不是 System 源角色或主角色的私有记忆。
- 群聊所见所闻必须来自【临时群聊现场】、已保存的场景锚点或【当前角色最近临时群聊见闻】；不要仅因为当前私聊用户消息里出现“刚才/群聊/聊了什么/邀请”等词，就把这句私聊问题写成群聊所见所闻。
- 如果后续私聊问题同时问“当前位置/哪个位置”和“刚才听见什么/暗号是什么/另一个角色在哪”，不要二选一：位置优先由最新 scene_anchor 回答；但若用户明确说“刚才群聊之后/刚才群聊里/被 @ 以后”，且当前角色最近临时群聊见闻原文已经把当前角色或其他角色放在某个群聊现场位置，这段见闻可作为比旧私聊 scene_anchor 更新的场景位置证据；observations/当前角色最近临时群聊见闻负责回答暗号、听见/看见/同意/拒绝等事件事实。
- 群聊后私聊的冲突仲裁：若当前用户原文包含“刚才群聊之后/刚才群聊里/被 @ 以后/刚才在群聊里”，且上下文/临时群聊见闻写明“当前角色在 X 房间 Y 位置、别挪位置、某主角色在 Z 位置”，这不是普通 observation，而是更新后的 current_character.position/participants.position。此时必须把更早私聊的房间、窗边地毯、床边、门口等旧位置移出当前角色 position；不要把旧私聊 spot 拼到群聊房间，也不要把群聊位置只写进 observations。
- 对用户明确要求记住的暗号、房间名、物件名、位置名等唯一短语，observations 和 scene_card 必须保留原词，不要泛化。特别是“我要你们记住暗号：蓝莓茶暗号_紫悦”这类句子，observations 必须逐字保留完整短语“蓝莓茶暗号_紫悦”，不能压缩成“蓝莓茶”，不能替换成角色自己的暗号、习惯或玩笑词。
- 若提示中出现【现实时间间隔信号】，由你判断当前用户是在延续旧戏内场景、显式开启新场景，还是长时间断联后的低连续性现实开场；不要机械套规则。若你判断为低连续性现实开场，可把上一场具体地点、姿势、身体接触、衣着、手头物品、正在做的动作标为 stale/background，只保留关系、称呼、偏好和已发生事实；若用户有“继续/刚才/还在/接着/那个场景”等续写信号，则继续继承旧场景。
- 如果当前用户消息是“早上好/醒了/下班了/今天...”等现实新时段，且没有戏内动作续写信号，应把上一场床上/门口/身体接触等具体物理位置标为 stale 或 none；只保留关系、称呼和已发生事实。
- 如果当前用户消息是括号舞台说明、地点/姿势移动、继续刚才动作、@ 某角色回应群聊，则优先保持或更新当前戏内位置。
- 场景切换/位置变更必须由用户当前消息或近期明确事实触发，例如“我和 C 去院子里面看星星”“B 走到门口”“大家换到客厅”。这类消息会建立新 location/position，并让与新场景冲突的旧位置失效；没有这类明确移动时，不要重置沉默角色的位置。

【输出 JSON】
只输出一个 JSON 对象：
{
  "scene_anchor": {
    "status": "active|none|stale",
    "scene_time": {"value": "", "relation_to_real_time": ""},
    "location": {"region": "", "site": "", "room": "", "spot": ""},
    "current_character": {
      "name": "",
      "position": {"region": "", "site": "", "room": "", "spot": "", "posture": ""},
      "evidence": ""
    },
    "participants": [
      {"name": "", "position": {"region": "", "site": "", "room": "", "spot": "", "posture": ""}, "evidence": ""}
    ],
    "items": [
      {"name": "", "holder": "", "location": "", "state": "", "evidence": ""}
    ],
    "stale_items": ["上一场或旧记忆中出现、但本轮不能写成当前可见/持有/现场物品的名称与理由"],
    "forbidden_current_items": ["Step 3 本轮不得写成当前物品或感官残留的项目，例如无证据牙膏味、上一场酒吧啤酒"],
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
        "scope": "current_scene|same_scene|background|stale|unknown"
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
        "scope": "current_scene|same_scene|background|stale|unknown"
      },
      "stale_states": ["上一场身体/感官状态若本轮不能继承，写在这里"],
      "reset_policy": "inherit_same_scene|reset_on_scene_change|background_only|unknown",
      "guidance": ""
    },
    "observations": [],
    "continuity_rules": [],
    "reset_reason": "",
    "summary": ""
  },
  "scene_card": "",
  "continuity_decision": {
    "idle_gap_hours": 0,
    "user_intent": "continue_scene|background_only_reopen|explicit_new_scene|uncertain",
    "prior_scene_treatment": "inherit_current_scene|background_only|replace_with_new_scene|none|uncertain",
    "reason": "用一句话说明你为什么继承旧场景或自然重开；没有长间隔则写空"
  }
}

【scene_card 要求】
- scene_card 用中文短卡片，不超过 900 字。
- 必须包含：状态、对话时间、地点层级、当前角色位置/姿势、其他角色位置/姿势、关键物品状态、群聊所见所闻、继承/作废规则。
- 必须包含当前身体状态/身体状态作废规则：如果没有证据，写“未明确”，不要补牙膏味、酒味、醉酒、疲惫或受伤。
- 当最近用户原文提供了地点层级、微观地点、角色位置或“记住暗号/口令/标记”时，scene_card 不能省略这些原词；没有这些字段会让后续私聊召回失败。
- 其他角色位置要像状态表一样列出已知参与者；沉默角色仍应保留最新 position/posture，除非用户明确移走或换场景。
- 关键物品要像状态表一样列出持有者/放置位置/状态；没有明确拿起、递交、放下、丢弃或带走时保持上一轮物品状态。
- 关键物品必须区分 current 与 stale/forbidden：上一场啤酒、旧房间道具、无证据牙膏味等不属于当前物品时，必须写入作废/禁止当前项，不要写进当前物品状态。
- 关键物品和当前活动名称优先使用最近真实对话里的精确词和子类型；若原文是“双板滑雪”，scene_card 必须能让后续步骤回答“双板/双板滑雪”，不要只剩“滑雪板”。
- 小马驹、婴儿、新生儿、幼崽等活体不要写成关键物品；若它们是马/小马类幼体，scene_card 里的健康/完整状态必须服从四蹄体态，不得把六只蹄子、六蹄或额外蹄肢写成当前事实。
- 不确定就写“未明确”，不要编造地点；没有活跃场景时 status=none，scene_card 简短说明“无可继承物理场景”。
- scene_card 是事实锚点，不是台词；不要出现“角色说/我会说/回复：”。
"""


def _normal_scene_empty_anchor() -> dict[str, Any]:
    return {
        "status": "none",
        "scene_time": {"value": "", "relation_to_real_time": ""},
        "location": {"region": "", "site": "", "room": "", "spot": ""},
        "current_character": {
            "name": "",
            "position": {"region": "", "site": "", "room": "", "spot": "", "posture": ""},
            "evidence": "",
        },
        "participants": [],
        "items": [],
        "stale_items": [],
        "forbidden_current_items": [],
        "physical_state": _empty_physical_state(),
        "observations": [],
        "continuity_rules": [],
        "reset_reason": "",
        "summary": "",
    }


def _clean_scene_text(value: Any, limit: int = 180) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _coerce_scene_position(value: Any) -> dict[str, str]:
    data = value if isinstance(value, dict) else {}
    return {
        "region": _clean_scene_text(data.get("region"), 120),
        "site": _clean_scene_text(data.get("site"), 120),
        "room": _clean_scene_text(data.get("room"), 120),
        "spot": _clean_scene_text(data.get("spot"), 120),
        "posture": _clean_scene_text(data.get("posture"), 160),
    }


def _coerce_scene_items(value: Any) -> list[dict[str, str]]:
    raw_items = value if isinstance(value, list) else []
    items: list[dict[str, str]] = []
    for raw in raw_items[:12]:
        if isinstance(raw, str):
            item = {
                "name": _clean_scene_text(raw, 120),
                "holder": "",
                "location": "",
                "state": "",
                "evidence": "",
            }
        elif isinstance(raw, dict):
            item = {
                "name": _clean_scene_text(raw.get("name") or raw.get("item") or raw.get("object"), 120),
                "holder": _clean_scene_text(raw.get("holder") or raw.get("owner") or raw.get("character"), 120),
                "location": _clean_scene_text(raw.get("location") or raw.get("spot") or raw.get("place"), 160),
                "state": _clean_scene_text(raw.get("state") or raw.get("status") or raw.get("condition"), 160),
                "evidence": _clean_scene_text(raw.get("evidence") or raw.get("source"), 220),
            }
        else:
            continue
        if any(item.values()):
            items.append(item)
    return items


def _coerce_scene_text_list(value: Any, *, limit: int = 8, item_limit: int = 220) -> list[str]:
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    result: list[str] = []
    for item in raw_items[:limit]:
        text = _clean_scene_text(item, item_limit)
        if text and text not in result:
            result.append(text)
    return result
