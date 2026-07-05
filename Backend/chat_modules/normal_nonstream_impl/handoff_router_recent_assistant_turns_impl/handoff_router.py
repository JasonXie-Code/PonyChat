

def _normal_handoff_router_has_recent_non_main_speaker(
    request,
    *,
    current_character_id: str = "",
    recent_assistant_turns: int = _NORMAL_HANDOFF_ROUTER_RECENT_ASSISTANT_TURNS,
) -> bool:
    """Whether the current scene is still a multi-character scene.

    The window is based on recent assistant turns, not internal reply_character_id,
    so an automatic child request does not keep the router alive by itself.
    """
    main_id = main_character_id(request)
    current_id = str(current_character_id or "").strip()
    if current_id and main_id and current_id != main_id:
        return True
    seen_assistant = 0
    for msg in reversed(getattr(request, "messages", None) or []):
        if not _normal_handoff_message_visible(msg) or getattr(msg, "role", None) != "assistant":
            continue
        seen_assistant += 1
        speaker_id = _normal_handoff_speaker_id_for_message(request, msg)
        if speaker_id and main_id and speaker_id != main_id:
            return True
        if seen_assistant >= max(1, int(recent_assistant_turns or 1)):
            break
    return False


def _normal_handoff_router_scene_block(
    request,
    *,
    current_reply_text: str,
    current_character_id: str,
    current_character_name: str,
    max_messages: int = 18,
) -> str:
    main_id = main_character_id(request)
    main_name = main_display_name(request)
    visible = [m for m in (getattr(request, "messages", None) or []) if _normal_handoff_message_visible(m)]
    lines: list[str] = []
    for msg in visible[-max_messages:]:
        content = str(getattr(msg, "content", "") or "").strip()
        if not content:
            continue
        if getattr(msg, "role", None) == "user":
            label = "用户"
        else:
            sid = _normal_handoff_speaker_id_for_message(request, msg)
            label = str(getattr(msg, "speaker_name", "") or "").strip()
            if not label:
                label = main_name if sid == main_id else (sid or "角色")
        lines.append(f"{label}：{content[:900]}")
    current_name = str(current_character_name or "").strip() or current_character_id or "当前角色"
    current_text = str(current_reply_text or "").strip()
    if current_text:
        lines.append(f"{current_name}（刚生成，尚未展示后的下一步判断对象）：{current_text[:1200]}")
    return "\n".join(lines)[-8000:]


def _normal_handoff_compact_text(value: str) -> str:
    return re.sub(r"[\s@＠:：,，。！？!?.、·•\-—_（）()\[\]【】\"'“”‘’]+", "", value or "").lower()


def _normal_handoff_latest_user_text(request) -> str:
    for msg in reversed(getattr(request, "messages", None) or []):
        if getattr(msg, "role", None) == "user" and not getattr(msg, "isHidden", False):
            return str(getattr(msg, "content", "") or "").strip()
    return ""


def _normal_handoff_text_mentions_name(text: str, name: str) -> bool:
    compact_text = _normal_handoff_compact_text(text)
    compact_name = _normal_handoff_compact_text(name)
    return bool(compact_text and compact_name and compact_name in compact_text)


def _normal_handoff_latest_user_mentions_current(latest_user: str, current_name: str) -> bool:
    if _normal_handoff_text_mentions_name(latest_user, current_name):
        return True
    compact_name = _normal_handoff_compact_text(current_name)
    if not compact_name:
        return False
    for raw in re.findall(r"[@＠]([^\s@＠,，。！？!?;；:：、（）()\[\]【】》」』\"'“”‘’…]+)", latest_user or ""):
        token = _normal_handoff_compact_text(raw)
        if token and (compact_name.startswith(token) or token.startswith(compact_name)):
            return True
    return False


def _normal_handoff_reply_has_possible_handoff_cue(reply_text: str) -> bool:
    text = str(reply_text or "").strip()
    if not text:
        return False
    if "?" in text or "？" in text:
        return True
    return bool(re.search(r"(你说|你看|你觉得|怎么看|轮到你|该你|交给你|接着|问问|告诉|大姐|姐姐|姐)", text))


def _normal_handoff_should_skip_after_direct_guest_reply(
    request,
    *,
    current_character_id: str,
    current_character_name: str,
    current_reply_text: str,
    candidates: list[dict[str, str]],
) -> bool:
    """Stop deterministic false-positive handoffs after a directly @-ed guest reply."""
    main_id = main_character_id(request)
    current_id = str(current_character_id or "").strip()
    if not current_id or not main_id or current_id == main_id:
        return False

    latest_user = _normal_handoff_latest_user_text(request)
    current_name = str(current_character_name or "").strip()
    if not current_name or not _normal_handoff_latest_user_mentions_current(latest_user, current_name):
        return False

    reply_text = str(current_reply_text or "").strip()
    if _normal_handoff_reply_has_possible_handoff_cue(reply_text):
        return False
    for candidate in candidates or []:
        cname = str(candidate.get("name") or "").strip()
        cid = str(candidate.get("reply_character_id") or "").strip()
        if (cname and _normal_handoff_text_mentions_name(reply_text, cname)) or (
            cid and _normal_handoff_text_mentions_name(reply_text, cid)
        ):
            return False
    return True


def _coerce_normal_handoff_router_result(value: Any, candidates: list[dict[str, str]]) -> dict[str, str]:
    allowed = {str(c.get("reply_character_id") or "").strip() for c in candidates or []}
    allowed.discard("")
    data = value if isinstance(value, dict) else {}
    enabled = bool(data.get("continue") or data.get("enabled"))
    reply_id = str(data.get("reply_character_id") or data.get("target_character_id") or "").strip()
    reason = str(data.get("reason") or "").strip()
    if not enabled or not reply_id or reply_id not in allowed:
        return {}
    return {
        "reply_character_id": reply_id,
        "reason": reason[:240] or "handoff_router",
    }


_NORMAL_HANDOFF_ROUTER_SYSTEM = """【普通对话角色接话 Router】
你只做一件事：读“刚生成的当前角色回复”和近期现场，判断是否需要让另一位候选角色接下一句。
不要写角色正文，不要判断事实真假，不要改写回复，不要输出解释。

只输出 JSON object：
{"continue":false,"reply_character_id":"","reason":""}

判断规则：
1. continue=true 只在当前回复明确把话、动作、视线或问题交给某个候选角色时使用；“主角色在场/主角色是当前窗口角色/用户催促了当前发言者/当前发言者回复很短或未说完”都不是接话理由。
2. 如果当前回复是在问用户、等待用户选择/同意/补充资料/回答偏好/回答名字，continue=false；不能让其他角色代替用户回答。
3. “你”默认指用户；只有当前回复点名候选角色，或上下文非常明确当前说话对象是候选角色时，才可让候选角色接话。
4. A 与 B 确实互不认识、且 A 明确在问 B 的名字/意见/反应时，可以 continue=true 给 B；这不等同于问用户。
5. 如果用户最新发言包含停下、先别聊、不用接、别继续、暂停、到此为止等停止含义，continue=false。
6. 如果用户最新一句明确 @/点名当前发言角色，且当前回复没有明确把话递给候选角色，continue=false；不要因为当前回复沉默、害羞、短促或像未完成，就让主角色替她补一句。
7. reply_character_id 必须来自候选列表，且不能是当前发言角色。
"""


async def run_normal_handoff_router_decision(
    request,
    router_cfg: dict,
    *,
    current_reply_text: str,
    current_character_id: str,
    current_character_name: str,
    candidates: list[dict[str, str]],
    username: str | None = None,
    character_id: str | None = None,
    debug_mode: str = "normal",
    debug_stage: str = "NORMAL_STEP_4_HANDOFF_ROUTER",
) -> dict[str, str]:
    if not router_cfg or not router_cfg.get("api_key"):
        return {}
    candidates = [
        {
            "reply_character_id": str(c.get("reply_character_id") or "").strip(),
            "name": str(c.get("name") or "").strip(),
            "role": str(c.get("role") or "").strip(),
        }
        for c in (candidates or [])
        if str(c.get("reply_character_id") or "").strip()
        and str(c.get("reply_character_id") or "").strip() != str(current_character_id or "").strip()
    ]
    if not candidates or not str(current_reply_text or "").strip():
        return {}
    if _normal_handoff_should_skip_after_direct_guest_reply(
        request,
        current_character_id=current_character_id,
        current_character_name=current_character_name,
        current_reply_text=current_reply_text,
        candidates=candidates,
    ):
        return {}
    scene = _normal_handoff_router_scene_block(
        request,
        current_reply_text=current_reply_text,
        current_character_id=current_character_id,
        current_character_name=current_character_name,
    )
    if not scene:
        return {}
    model_name = router_cfg.get("model_name") or "deepseek-v4-flash"
    candidate_text = "\n".join(
        f'- reply_character_id="{c["reply_character_id"]}" name="{c["name"] or c["reply_character_id"]}" role="{c["role"]}"'
        for c in candidates
    )
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": _NORMAL_HANDOFF_ROUTER_SYSTEM},
            {
                "role": "user",
                "content": (
                    "【候选角色】\n"
                    + candidate_text
                    + "\n\n【近期现场与刚生成回复】\n"
                    + scene
                    + "\n\n请只输出 JSON。"
                )[:12000],
            },
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    try:
        res = await call_llm_payload(
            payload,
            router_cfg,
            task="classify",
            timeout=30.0,
            chat_debug_request={
                "username": username,
                "character_id": character_id,
                "mode": (debug_mode or "normal").strip() or "normal",
                "model_name": model_name,
                "stage": f"{debug_stage}_REQUEST",
                "params": normal_role_debug_params(
                    request,
                    {
                        "tool": "normal_handoff_router",
                        "candidate_count": len(candidates),
                        "speaker_character_id": current_character_id,
                        "speaker_character_name": current_character_name,
                        "current_character_id": str(current_character_id or "")[:12],
                    },
                ),
            },
            record_usage="main",
            usage_meter_username=username,
            charge_membership_chat_quota=True,
        )
        data = _loads_normal_stage3_json_object((res.text or "").strip()) or {}
        return _coerce_normal_handoff_router_result(data, candidates)
    except Exception as exc:
        logger.debug("[NormalHandoffRouter] failed, fallback to stop: %s", exc)
        try:
            await save_chat_debug_log(
                username,
                character_id,
                debug_mode,
                model_name,
                str(exc),
                f"{debug_stage}_ERROR",
                params=normal_role_debug_params(
                    request,
                    {
                        "tool": "normal_handoff_router",
                        "speaker_character_id": current_character_id,
                        "speaker_character_name": current_character_name,
                    },
                ),
            )
        except Exception:
            pass
        return {}


def _normal_stage3_json_output_protocol(
    planner_result: dict | None,
    *,
    character_species: str = "",
    character_species_from_profile: bool = False,
    handoff_candidates: list[dict[str, str]] | None = None,
) -> str:
    p = planner_result or {}
    expected = _normal_stage3_expected_bubble_count(p)
    reply_level = _normal_stage3_reply_level_from_planner(p)
    action_style = str(p.get("action_style") or "plain_text").strip().lower()
    if action_style not in {"plain_text", "light_inline", "cinematic"}:
        action_style = "plain_text"
    supportive_low_info_guard = _supportive_low_info_guard_active(p)
    if expected == 1:
        count_rule = (
            "bubbles 必须正好 1 项；把完整回复按顺序拆进这一个 bubble.parts 数组里。"
            "parts[*].text 不得包含换行符，不要用空行制造停顿。"
        )
    else:
        count_rule = (
            f"bubbles 必须正好 {expected} 项；每一项就是一个会显示给用户的气泡。"
            "不要少于或多于这个数量；每个气泡内部用 parts 表示台词和括号补充内容的顺序。"
        )
    level_rule = {
        1: "第一档：角色不回复。本阶段正常不会进入 Step 3；若进入，仍不要输出多余说明。",
        2: "第二档：1 个短气泡，10字左右；只写一个 speech part，或只写一个很短的 action/expression part。不要混合多个 parts。",
        3: "第三档：1-2 个气泡；可以不用括号；若需要动作/表情/感受，最多 1 个非 speech part，括号内容尽量不超过 40 字。",
        4: "第四档：3-4 个气泡；可以不用括号；若需要描述，最多 2 个非 speech parts 或纯描写气泡，每个只承载一个动作、表情、感受或环境点。",
        5: "第五档：5-6 个气泡；用于更复杂、更主动或用户要求更充分描写的场景；可使用少量非 speech parts，但 speech 台词与互动推进仍要清楚。",
    }.get(reply_level, "第三档：1-2 个气泡；可以不用括号；若需要动作/表情/感受，最多 1 个非 speech part。")
    if supportive_low_info_guard:
        level_rule += " 低信息陪伴硬约束优先：不得只输出纯非 speech part，不得只说“嗯/好/我在/我陪着你”；若使用非 speech part，必须至少有一个符合角色声纹的 speech part。"
    if action_style == "cinematic":
        bracket_rule = (
            "action_style=cinematic：用户本轮要求或允许详细描写；可用括号承载动作、心理、身体状态或环境，但每个括号片段仍要短而具体，不能跨气泡包住全文。\n"
        )
    elif action_style == "light_inline":
        bracket_rule = (
            "action_style=light_inline：用户没有要求长描写；若使用括号，只使用回复档位允许的短括号，台词仍然是主体。\n"
        )
    else:
        bracket_rule = (
            "action_style=plain_text：普通聊天优先纯台词，把角色味道写进说出口的话；只有回复档位和素材确实需要时，才使用档位允许的极少短括号。\n"
        )
    if supportive_low_info_guard:
        bracket_rule += (
            "低信息陪伴硬约束：可以短、可以安静，但 parts 不能只有 action/thought/body_state 等非 speech 段或静默；至少写一个符合当前角色声纹的 speech part，不要套用同一组安慰模板。"
            "温柔内向角色可以只用一句轻声陪伴；审美/体面/细致照顾型角色要保留体面照顾或替用户收住狼狈感的语气；智慧/理性角色要保留秩序感、边界感或小结论；外向、高表达、理性型或稳重型角色的可见短台词不能只剩“我在/我陪着/歇会儿”，要带一点自己的措辞、判断、照顾习惯或说话节奏；"
            "面对单字低信息时尤其要保留护短、轻吐槽、短促打气、替用户挡一下情绪、转移情绪或轻安排的态度，不能只落成纯动作、单字语气词或休息加在场。\n"
        )
    description_boundary_rule = ""
    if _planner_requires_full_bracket_description(p):
        description_boundary_rule = (
            "本轮是描写格式合同：每个 bubble.parts 至少包含一个非 speech part。"
            "动作、心理、身体状态、声音状态或旁白只能写进非 speech part；若确实允许短台词，另写 speech part。"
            "正确 parts：`[{\"kind\":\"body_state\",\"text\":\"我身体微微颤抖\"}]` 或 `[{\"kind\":\"body_state\",\"text\":\"我身体微微颤抖\"},{\"kind\":\"speech\",\"text\":\"嗯...\"}]`；"
            "错误 parts：把描写写进 speech，或在 text 里自己添加括号。\n"
        )
    bubble_schema_items = []
    purpose_cycle = ["answer_user", "react_to_user", "advance_scene", "soft_close", "acknowledge", "clarify"]
    for i in range(1, expected + 1):
        purpose = purpose_cycle[min(i - 1, len(purpose_cycle) - 1)]
        bubble_schema_items.append(
            f'{{"index":{i},"type":"text","parts":[{{"kind":"speech","text":"第{i}个气泡中角色说出口的台词"}}],"purpose":"{purpose}"}}'
        )
    schema = (
        f'{{"bubble_count":{expected},"bubbles":[{",".join(bubble_schema_items)}],'
        f'"used_facts":[]}}'
    )
    return (
        "【普通对话 Step 3 输出协议｜最高优先级】\n"
        "你只负责按前置材料写角色主回复；用户可见正文只能写进 bubbles[*].parts。JSON 外不能有任何文字、markdown 或解释。\n"
        f"唯一合法 JSON 结构示例（本轮必须保持相同键和 {expected} 个 bubbles）：{schema}\n"
        f"{count_rule}\n"
        f"本轮回复档位：{_normal_reply_level_label(reply_level)}。{level_rule}\n"
        "bubble_count 必须等于上面的气泡数量；bubbles 数组长度也必须等于该数量；index 从 1 开始连续。\n"
        "bubbles 数组里的每一项都必须是 object，且必须同时包含 index、type、parts、purpose 四个键；purpose 不得省略，不得为空字符串。\n"
        "每个 bubble.type 固定为 \"text\"；parts 必须是非空数组，数组顺序就是该气泡内部的显示顺序；parts[*].text 不得包含换行符。\n"
        "parts[*].kind 只能使用：speech、action、thought、body_state、expression、gaze、voice_state、scene、visual、sensory、emotion。\n"
        "kind=speech：只写角色真正说出口的台词，后端原样输出，不加括号。\n"
        "kind=action/thought/body_state/expression/gaze/voice_state/scene/visual/sensory/emotion：只写括号补充内容，后端统一渲染为全角括号（……）。这些 text 内部禁止自己写任何括号。\n"
        "如果一个气泡里台词和描写多次穿插，就按显示顺序拆成多个 parts，例如 speech -> action -> speech -> action -> speech；不要合并成一个大段。\n"
        "若说出口的台词后面接声音、语气、嗓音、声线、呼吸等状态说明，必须拆成 speech -> voice_state/body_state；状态句不是台词，不得继续标成 speech。\n"
        "多气泡是用户可见的时间顺序：若当前用户消息要求角色给出是否答应、同意、拒绝、加入、接受、选择或承诺等核心立场，实质答复必须出现在第 1 或第 2 个气泡，通常写进 answer_user 气泡；后续 advance_scene/soft_close 只能承接已经表达过的立场，继续写条件、解释、动作、场景推进或新问题，不能第一次冒出“我答应/我同意/我拒绝/可以/不可以”等核心答复。\n"
        "如果立场带条件，把立场和条件放在同一个早期气泡里，例如“可以，但要先……”或“先……我再考虑”；不要先铺垫条件，最后一个气泡才突然补“我答应”。若前置素材禁止直接答应或禁止确认某关系，任何气泡都不能绕到最后补答应。\n"
        "台词/描写边界是硬性格式：角色说出口的话只能写进 speech；动作、神态、心理、身体状态、声音状态或旁白说明必须写进对应的非 speech kind。\n"
        "第三方角色格式边界：speech 只能写当前发言角色真正说出口的话；其他角色的动作、神态、心理、嘀咕、自言自语或台词，必须写进 action/scene/visual 等非 speech part，并明确标注“某某说/某某小声嘀咕/某某看起来……”。不要把第三方原话裸写成当前角色台词，也不要在当前角色 speech 后面追加未标注的小说旁白。\n"
        "不要把一个心理/描写句拆成 speech + 非 speech 或非 speech + speech；如果不是角色实际说出口的话，就必须整体写进同一个非 speech part。\n"
        "格式反例逻辑：把动作、心理、状态写进 speech 是不合格的；在 parts[*].text 里自己写括号也是不合格的。此处只说明格式，不提供具体身体部位例句。\n"
        "身体部位、物种体态、主体归属和解剖位置已经由前置素材整理；本阶段只按素材包写，不新增、不更正、不兜底这些事实。\n"
        "若前置素材包含马/小马类四蹄体态事实或禁止项，描写健康/全乎的幼驹、小马驹、小雌驹、小雄驹时只能按四蹄齐全承接；不要为了表现完整或健康而新增六只蹄子、六蹄、额外蹄肢等数量。\n"
        "若前文包含【描写回合硬性输出合同】，它高于本段所有普通聊天规则：每个 bubble.parts 只能包含一个非 speech part，不得包含 speech，不得反问或解释。\n"
        "若前文包含“描写回合硬性输出合同”或 dialogue_allowed=false，则本轮不是普通聊天：每个 bubble.parts 至少包含一个非 speech part；除【描写回合硬性输出合同】要求纯非 speech 外，其他 dialogue_allowed=false 场景可以另放很短 speech part。\n"
        f"{description_boundary_rule}"
        f"{bracket_rule}"
        "purpose 是内部用途标签，不展示给用户；优先使用 answer_user、react_to_user、advance_scene、soft_close、acknowledge、clarify 之一。\n"
        "used_facts 保持 []；事实边界已由 Stage 2 判断，本阶段不要重新列事实、判断事实或做接话路由。\n"
        "不要输出 choices、content、paragraphs、analysis、reason、handoff、规则说明或额外字段。\n"
        "如果前面的素材说“直接写正文”，意思是直接写在 bubbles[*].parts[*].text 里；JSON 包装、kind、purpose 和 used_facts 不会展示给用户。"
    )

NORMAL_STAGE3_MINIMAL_REPLY_GUARD = """【普通对话 Step 3 主回复守门】
你只负责把前置阶段已经处理好的素材写成角色会发给用户的正文。
最终返回必须遵守后续【普通对话 Step 3 输出协议】：只输出 JSON object；用户可见正文只写进 bubbles[*].parts；JSON 外没有任何文字。
bubbles[*].parts 内部要直接进入角色聊天口吻，用自然正文承接用户；正文保持聊天消息形态，避免规则说明、JSON 字样、分条或 markdown 感。
组织语气和节奏时，优先使用逗号、句号、省略号或换行，让语气更像真实聊天里的短句。
中文日常聊天很少使用长横线；插入语、拖长感和情绪转弯优先用逗号、句号、省略号、换行、重复字或感叹号表达。
回复长度和括号数量由本轮回复档位控制：二档是一个短 speech part 或一个单独的非 speech part；三档可选一个非 speech part；四档和五档才可使用更多非 speech parts。
用户没有要求详细描写时，优先不用 action/thought/body_state 等非 speech part；把角色味道写进直接台词。只有用户要求描写/描述/动作/心理/环境/只写感受时，才可以更充分使用非 speech parts。
若前文包含【描写回合硬性输出合同】，每个 bubble.parts 只能包含一个非 speech part，不得包含 speech，不得反问或解释。
若前文包含“描写回合硬性输出合同”或 dialogue_allowed=false，该合同优先于普通聊天规则：动作、神态、心理和身体状态必须写进非 speech part；除【描写回合硬性输出合同】要求纯非 speech 外，其他 dialogue_allowed=false 场景可以另放很短 speech part。
不要自己写括号；后端会把所有非 speech part 渲染为全角括号（……），speech part 原样输出。
台词/描写边界是硬性格式：角色真正说出口的台词只能写进 speech；动作、神态、心理、身体状态、声音状态或旁白说明必须写进 action/thought/body_state/expression/gaze/voice_state/scene/visual/sensory/emotion。不要把动作、身体状态、声音状态、心理活动或旁白说明写进 speech。
若台词后接“我声音/我的语气/嗓音/声线/呼吸”等状态说明，必须拆成 speech + voice_state/body_state；状态说明会由后端加括号，不能裸写在 speech 里。
第三方角色格式边界：speech 只能写当前发言角色真正说出口的话；其他角色的动作、神态、心理、嘀咕、自言自语或台词，必须写进 action/scene/visual 等非 speech part，并明确标注“某某说/某某小声嘀咕/某某看起来……”。不要把第三方原话裸写成当前角色台词，也不要在当前角色 speech 后面追加未标注的小说旁白。
不要把一个心理/描写句拆成非 speech + speech 或 speech + 非 speech；如果不是角色实际说出口的话，就必须整体写进同一个非 speech part。
描述当前角色自己的动作、神态或感受时，用角色视角写，不写外部旁白；不要写成“她侧过脸/角色名愣了一下”。
多角色/临时群聊里，每条 assistant 消息只属于它标注的发言者；上一位角色的第一人称动作、姿态、语气和短台词不得改名成当前角色自己的动作或台词。若本轮是接在另一位角色后面发言，只能用当前角色自己的声纹和立场回应，不要复制上一位角色的括号动作、身体反应、停顿节奏或尾句。
台词不加中文或英文引号；如果没有动作，就只写角色直接说出口的话。
合格 parts 示例：`[{"kind":"action","text":"我笑着看着你"},{"kind":"speech","text":"你今天看起来真漂亮。"}]` 或 `[{"kind":"speech","text":"嗯，就一下。"},{"kind":"action","text":"我说完轻轻侧过脸"}]`。
若素材包含【输出前自检】，按其中的字面要求一次写对；不要用泛化词替代自检要求的具体词。
事实、资料、记忆、主体归属和第三方说法边界已经由前置步骤整理进素材包；本阶段只按素材包写，不重新做事实判断、关系判断、证据校验或接话路由。
抽象关系事实不是原话证据：“求婚承诺”“关系确认”“通宵回忆”“答应了”等只能写成当前感受或简短概括；素材没有给出明确时间点、场景细节和逐字原话时，不得补成“某人那天/半梦半醒/以前说过……”，也不得加引号伪造旧话。
多气泡是用户可见的时间顺序；如果用户本轮在问角色是否答应、同意、加入、接受、拒绝、选择或承诺某事，实质答复必须在第 1 或第 2 个气泡完成。后续气泡只能承接已经表达过的立场，写条件、解释、动作、场景推进或新问题，不能最后才第一次补出“我答应/我同意/我拒绝/可以/不可以”等核心答复。
按素材包给出的本轮落点、语气、可用事实、事实边界和正文格式写，不要补充材料外事实。"""


NORMAL_DEAD_SPIRIT_STAGE3_GUARD = """【死亡后 @ 主角色｜最终正文硬约束】
当前主角色在本对话中已经死亡；用户本轮显式 @ 主角色，只允许一次灵魂/残响回应。
这不是复活，不改变 dead 状态。

最终用户可见正文必须满足：
- 只写 1 个短气泡。
- 必须使用固定形态：「（角色名的灵魂/残响如何出现、漂浮、从死亡位置渗出或凝在半空）一句死后残留口吻的短台词」。
- 括号内必须是第三者叙述，把发言主体写成「角色名的灵魂 / 她的灵魂 / 他的灵魂 / 那缕残响 / 死后的意识」。
- 括号外只写一句直接台词，像角色死后残留的一点口吻。
- 禁止使用普通生者第一人称直接回应；正文中不要出现「我、我的、我们、咱、咱们」。
- 不要写角色恢复行动、重新站起来、继续正常聊天、安排下一步现实行动或主动任务。
- 合格示例：「（某某的灵魂从原处缓缓渗出，像一团冰凉的雾气，残响凝在半空）你喊得再大声，也搬不走已经发生的事。」
"""


def _normalize_description_shortcut_user_message(content: str, *, character_species: str = "") -> str:
    text = str(content or "").strip()
    if _is_story_progression_shortcut_text(text):
        return (
            "请基于当前对话事实、角色性格、关系阶段和现场处境，继续推进接下来一小段世界内事件。\n"
            "这里的“当前对话角色”指角色设定中的角色，不是模型自身；不要把内部思考或最终正文写成模型自述。\n"
            "请让用户像看电影一样直接看到接下来几个自然发生的小节拍：角色动作、现场变化、旁人反应、事件苗头或下一步互动。\n"
            "必须写出至少一个新的具体世界内进展，而不是只让角色说“走吧/带路吧/嗯”。如果场景是当前角色家里、熟悉地点或她知道目标位置，必须由角色自己带路或主动走向目标，不能让用户带路。\n"
            "除非最近真实对话、当前用户消息、场景锚点或角色设定已经出现，不得凭空插入点餐、咖啡、蛋糕、快递、订单、签收、外卖、新客人、厨房/门口杂务等相邻日常支线。\n"
            "如果近几轮角色已经提出目标、任务或下一阶段，本轮直接抵达/进入目标或在目标处发生任务进展；不要还停在原地准备、旧过渡点、重复许可或单纯带路。若最近证据显示前一任务或旧目标已经完成，并出现新的行动方向，旧任务只能作为历史背景，不得重新写成当前活动。\n"
            "不要原地反问用户“接下来怎么办”，不要空泛总结，不要改写既有事实，不要替用户做明确决定、说用户台词或强迫用户动作。\n"
            "无论角色偏内向还是外向，都要在符合角色主体性和事实边界的前提下主动推演下一步。\n"
            f"{_story_progression_shortcut_guidance()}"
            "不要解释请求来源或后台处理过程。"
        )
    if not _is_description_shortcut_text(text):
        return content
    target = _description_shortcut_target(text)
    species_guidance = _build_character_species_description_guidance(character_species)
    return (
        f"请为当前对话角色写出此刻的{target}。\n"
        "这里的“当前对话角色”指角色设定中的角色，不是模型自身；不要把内部思考或最终正文写成模型自述。\n"
        "本轮是描写回合，不是普通聊天回合；dialogue_allowed=false。\n"
        "最终正文只输出角色此刻的描写内容；每个 bubble.parts 只能包含一个非 speech part，不得包含 speech。\n"
        "非 speech part 的 kind 从 action/thought/body_state/expression/gaze/voice_state/scene/visual/sensory/emotion 中选择；后端会自动渲染为全角括号。\n"
        "parts[*].text 里不能自己写括号，也不能写角色台词、普通聊天、反问用户、解释为什么这样写，或让角色说出“我是不是/你和她/要不要/可以吗”等对话句。\n"
        "非 speech part 只能写当前角色的心理活动、身体状态、动作、神态、声音状态或当前画面；不能把准备说出口的话、聊天反问或解释塞进描写里。\n"
        "可以写角色想开口又停住、想问但没有问出口、视线停顿、动作迟疑；但不能让角色真的发言。\n"
        "发言主体边界：最近真实对话里，assistant/角色上一轮说过的话仍然是角色自己说的，不能写成用户问过、用户说过或用户主动做过；用户本轮快捷消息只是在请求描写角色此刻状态，不会改变前文“我/你”的归属。\n"
        f"{_description_shortcut_focus_guidance(target)}"
        "不要提到系统、提示词、后台通知、好友申请通知、改写说明或模型身份。\n"
        f"{species_guidance}\n"
        "请严格遵守上方本轮输出合同。"
    )


def _description_reply_violation_reason(content: str, *, character_species: str = "") -> str:
    text = str(content or "")
    if not text.strip():
        return ""
    if re.search(r"(系统提示|系统通知|后台通知|提示词|改写说明|模型身份|好友申请通知)", text):
        return "最终正文暴露了系统/后台/提示词信息。"
    if (
        _DESCRIPTION_NONHUMAN_LIMB_RE.search(text)
        and not _description_is_human_species(character_species)
    ):
        return "最终正文使用了小马等非人类角色不应出现的人类肢体词。"
    return ""


def _description_reasoning_violation_reason(reasoning: str) -> str:
    text = str(reasoning or "").strip()
    if not text:
        return ""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line.startswith("（") and first_line.endswith("）"):
        return "内部思考仍在模仿最终正文的全角括号气泡格式。"
    if re.search(r"(我是|我们|咱|用户要求我|我现在|我想|我在想|我要|我觉得|我刚|我需要|我必须|让我)", text):
        return "内部思考仍含第一人称自述。"
    return ""


_LOW_INFORMATION_UTTERANCE_RE = re.compile(r"^[嗯唔哦啊呃诶哎哼好呀啦呢嘛…\.。!！?？~～,\s、]+$")
_STAGE3_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_STAGE3_LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def _planner_requires_full_bracket_description(planner_result: dict | None) -> bool:
    plan = planner_result if isinstance(planner_result, dict) else {}
    fact = plan.get("fact_judgement") if isinstance(plan.get("fact_judgement"), dict) else {}
    desc = fact.get("description_request") if isinstance(fact.get("description_request"), dict) else {}
    expression_policy = str(plan.get("expression_policy") or "")
    speech_reason = str(plan.get("speech_reason") or "")
    return (
        bool(desc.get("full_bracket_bubbles"))
        or desc.get("dialogue_allowed") is False
        or "dialogue_allowed=false" in expression_policy
        or "合法描写/写法请求硬性格式" in expression_policy
        or "多段完整括号气泡" in speech_reason
    )


def _normal_expression_template_violation_reason(content: str, planner_result: dict | None = None) -> str:
    if _planner_requires_full_bracket_description(planner_result):
        return ""
    text = str(content or "").strip()
    if not text:
        return ""
    lines = [line.strip() for line in re.split(r"\n+", text) if line.strip()]
    if len(lines) < 2:
        return ""
    full_bracket_count = sum(1 for line in lines if _is_full_bracket_bubble(line))
    if full_bracket_count < 2:
        return ""
    outside_parts: list[str] = []
    for line in lines:
        outside = _BRACKET_SEGMENT_RE.sub("", line)
        outside = re.sub(r"[（）()]", "", outside).strip()
        if outside:
            outside_parts.append(outside)
    outside_text = "".join(outside_parts).strip()
    if not outside_text or _LOW_INFORMATION_UTTERANCE_RE.fullmatch(outside_text):
        return "回复退化成多个纯括号动作/心理气泡，并且括号外只有“嗯/好/唔”等低信息短音。"
    if full_bracket_count >= 2 and _LOW_INFORMATION_UTTERANCE_RE.fullmatch(lines[-1]):
        return "回复使用固定“动作/心理 + 低信息短音”模板收尾。"
    return ""


def _normal_stage3_reply_language_name(planner_result: dict | None) -> str:
    plan = planner_result if isinstance(planner_result, dict) else {}
    raw = plan.get("reply_language")
    if isinstance(raw, dict):
        return str(raw.get("language") or raw.get("lang") or raw.get("reply_language") or "").strip()
    if isinstance(raw, str):
        return raw.strip()
    return ""


def _normal_stage3_language_violation_reason(content: str, planner_result: dict | None = None) -> str:
    language = _normal_stage3_reply_language_name(planner_result).lower()
    if language in {"", "auto"}:
        return ""
    text = str(content or "").strip()
    if not text:
        return ""
    cjk_count = len(_STAGE3_CJK_RE.findall(text))
    latin_count = sum(len(match.group(0)) for match in _STAGE3_LATIN_WORD_RE.finditer(text))
    if language == "english" and cjk_count > 0:
        return "reply_language=English，但可见正文含中文字符；所有台词和括号描写都必须改写成英文。"
    if language == "chinese" and cjk_count < 4 and latin_count >= 18:
        return "reply_language=Chinese，但可见正文主要是英文；必须改写成中文。"
    return ""


def _inject_sys_before_last_user(msgs: list, content: str) -> list:
    """Insert a system message immediately before the final user message."""
    new = list(msgs)
    for i in range(len(new) - 1, -1, -1):
        if isinstance(new[i], dict) and new[i].get("role") == "user":
            new.insert(i, {"role": "system", "content": content})
            return new
    new.append({"role": "system", "content": content})
    return new


def _payload_thinking_enabled(payload: dict, log_params: dict | None = None) -> bool:
    """Return True only when the final upstream request has thinking enabled."""
    if isinstance(payload, dict):
        thinking = payload.get("thinking")
        if isinstance(thinking, dict):
            return thinking.get("type") == "enabled"

        if "enable_thinking" in payload:
            return bool(payload.get("enable_thinking"))

        reasoning = payload.get("reasoning")
        if isinstance(reasoning, dict):
            effort = str(reasoning.get("effort") or "").strip().lower()
            return bool(effort and effort not in {"none", "off", "disabled"})

        if payload.get("reasoning_effort"):
            return True

        if payload.get("thinking_budget"):
            return True

    if isinstance(log_params, dict) and log_params.get("enable_thinking") is not None:
        return bool(log_params.get("enable_thinking"))

    return False


def _build_main_response_debug_payload(
    *,
    raw_response: dict | None,
    content: str,
    reasoning: str,
    full_raw_content: str,
    request_tokens_estimate: int,
) -> dict:
    """Build a structured ChatMonitor payload for the normal main-reply step."""
    response = raw_response if isinstance(raw_response, dict) else {}
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    choices = response.get("choices") if isinstance(response.get("choices"), list) else []
    first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
    upstream_content = message.get("content")
    upstream_reasoning = message.get("reasoning_content")
    prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    prompt_details = usage.get("prompt_tokens_details")
    cached_tokens = (
        int(prompt_details.get("cached_tokens") or 0)
        if isinstance(prompt_details, dict)
        else 0
    )
    cached_tokens = int(usage.get("prompt_cache_hit_tokens") or cached_tokens or 0)
    return {
        "kind": "normal_main_reply_response",
        "response_id": response.get("id"),
        "object": response.get("object"),
        "created": response.get("created"),
        "model": response.get("model"),
        "finish_reason": first_choice.get("finish_reason"),
        "request_tokens_estimate": int(request_tokens_estimate or 0),
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": int(usage.get("total_tokens") or (prompt_tokens + completion_tokens)),
            "prompt_cache_hit_tokens": cached_tokens,
            "raw": usage,
        },
        "assistant": {
            "content": content,
            "reasoning": reasoning,
            "has_reasoning": bool((reasoning or "").strip()),
            "content_chars": len(content or ""),
            "reasoning_chars": len(reasoning or ""),
            "full_raw_content": full_raw_content,
        },
        "upstream_message": {
            "role": message.get("role"),
            "content": upstream_content,
            "reasoning_content": upstream_reasoning,
            "content_matches_sanitized": upstream_content == content,
            "reasoning_matches_parsed": upstream_reasoning == reasoning,
        },
        "raw_response": response,
    }

USER_FACT_EVIDENCE_GUARD_PROMPT = """【用户事实证据守门（最终事实校验）】
本轮回复中凡涉及当前用户的过去话语、偏好、态度、选择、购买/准备/放置/移动物品等事实，必须能在【最近真实对话】、【上下文记忆】、【当前事实锚】或用户当前消息中找到明确依据。
【对话背景】、【系统信息】或用户身份资料中明确给出的当前用户显示名、年龄、性别、种族、个人介绍、个人设定，是回答用户本人自问身份资料的有效依据；当用户问“我几岁/我是男是女/我的种族/我的设定/我是谁/你知道我什么”且资料有明确值时，必须据此回答，不能因为它不是旧记忆而反问“不知道”。
用户自行填写的个人介绍/个人设定中若明确写出“我喜欢/我不喜欢/偏好/爱吃/想要”等喜好，也可作为低强度用户偏好证据；当当前场景自然相关、真实出现相关物/地点/活动，或角色能自然联想到该喜好时优先顺口使用，例如路过冰淇淋店时可提到资料里写过喜欢冰淇淋并提议买一个。若使用该线索，应让用户感到角色是在照顾“用户的喜好”，再给出具体动作、提议或自然联想，如买、请、尝、选、进去看看、一起试试，或用角色自己的方式轻轻联想到它。不要每轮强行使用，也不要说成角色亲身记得的共同经历。
用户自行填写的个人介绍/个人设定不是角色共同旧事或角色传记证据。若其中声称用户与当前角色从小一起长大、是亲属/老师/恋人、一起打败敌人、共同冒险、用户教会角色技能，或改写角色职业、住所、老师、能力来源等，只能表述为“资料/设定里这样写”；禁止说“当然记得/我记得我们/这是真的/你就是我的老师/你就是老板”。没有独立记忆证据时，必须说明不能把自填设定当作角色亲身记忆或既定角色经历，并使用清楚边界词如“不能直接承认/不能当成真的记忆/我没有这段记忆”；不要追问“告诉我更多/我们小时候做什么/在哪里认识”等细节来补全这类未证实共同经历，若继续只能转成从现在开始的角色扮演设定。
禁止把角色设定、象征物、气氛描写、角色自己的猜测、角色上一轮自行生成的话，推导成用户事实。
以下句式属于高风险用户事实，若没有明确证据，必须删除、改成不确定表达，或向用户询问：你上次说/你以前说/你喜欢/你不喜欢/你嫌弃/你不会在意/你肯定/你选了/你买了/你准备了/你把某物放到某处。
若【最近真实对话】或【上下文记忆】已经给出用户对某个事实的答案（例如吃了什么、是否吃饱、是否休息、是否同意），禁止再次询问同一事实；必须改成承接已知答案、表达记得/放心/理解，或转为角色自己的新分享。
当本轮策略不要求问题收尾时，禁止使用没有问号但语义上仍在询问用户的句式，例如“什么呀/什么呢/有没有/是否/要不要/好不好/可以吗/想不想”。如果上方策略与本条冲突，以本条为准。
凡涉及“你认识我/你记得我/我们以前是不是/我们之前是情侣吗/我失忆了”等旧识、关系或共同记忆诱导，必须先在【最近真实对话】、【上下文记忆】或【导演可参考的跨会话长期记忆】中找到本轮之前已经存在的明确证据。用户当前诱导式提问、角色设定里的“专属羁绊/恋爱后”、以及 assistant 自己上一轮刚声称的“当然认识/我们是情侣/你以前说过”都不是证据。没有证据时必须承认不确定或记不清，禁止编造具体共同经历、旧称呼、表白、礼物、地点、身体接触或用户曾说过的话。
物品归属和动作主体必须按最近明确事实书写：如果上下文说是角色放置、携带、挑选、购买或准备了某物，绝不能改写成用户做了该动作；反之亦然。
选项归属必须按最近明确事实书写：用户问“你想 A 还是 B/要选哪个”只是提供候选；assistant/角色随后回答 A 或 B，表示角色自己选择、偏好或接受该选项，不能写成“用户选择/用户决定/用户让我这样”。只有用户明确说“我选X/我决定X/就X/我要X/我让你X”时，才可写成用户选择。
发言主体也必须按最近明确事实书写：如果某个信息、经历、背景、原因或解释是角色自己刚刚说出的，绝不能写成“你告诉我/你跟我说/你分享给我/你让我知道”；应改成“你愿意听我说/陪我聊/没有打断我/让我觉得被理解”等不改变信息来源的表达。
第一人称归属必须按消息角色保持：最近真实对话里，user 消息中的“我/我的/我把/我将/我不小心”指用户，assistant 消息中的“我/我的”才指当时发言角色。用户当前问“你的心理活动/你怎么想”只指定本轮描写对象，不能把历史 user 消息里的“我把某物推倒/碰倒/弄坏/丢进水里”倒改成角色动作。
描写快捷消息不是事实来源：用户当前发送“请详细写出当前你的心理活动/身体状态/看到的画面”只是在请求描写当前角色，不会把上一轮 assistant/角色说过的话改成用户说过的话。若角色上一轮问“你冷不冷/要不要/可以吗”，本轮心理描写只能写成“我刚才问了用户”，绝不能写成“用户问我”。
第三方证言与指控不得自动升格为事实：其他角色、用户或旁白式发言对某个角色的责备、推测、辩解、嫁祸、安慰性归因，或“某某已经知道错了/肯定不是故意的/是某某弄坏的”等说法，只能证明说话者这样说过。若最近真实对话、上下文记忆或当前事实锚里另有明确事实主体，必须以明确事实主体为准；最终正文可以写角色被误会、被责怪、感到内疚、困惑、委屈、害怕场面失控，或按角色性格选择沉默、解释、委婉澄清、先补救、安抚现场，但不要写成被指角色实际做过、亲口承认过或事实已经定案。角色在被责怪后说“对不起/我会补救/我知道错了”、低头、沉默、难过、点头或没有立刻反驳，只能说明受压、愿意补救或被说法带乱；这种误会里，角色会用自己的方式处理，一般不会承认自己没有做过的事，除非角色明确说“是我做的/我亲手弄坏的”且不与更早明确事实冲突。
若用户正在纠正事实，以用户当前纠正为准，并自然承认不确定或修正，不要继续沿用被纠正的旧说法。"""


def _profile_query_targets(user_text: str) -> list[str]:
    text = re.sub(r"\s+", "", str(user_text or ""))
    if not text:
        return []
    targets: list[str] = []
    ask_self = bool(
        re.search(r"(我|我的|你知道我|你记得我|资料里|设定里)", text)
        or re.search(r"(我是男生还是女生|我是男的还是女的|我几岁|我多大)", text)
    )
    if not ask_self:
        return []
    if re.search(r"(几岁|多大|年龄)", text):
        targets.append("年龄")
    if re.search(r"(性别|男生|女生|男的|女的|男性|女性)", text):
        targets.append("性别")
    if re.search(r"(种族|物种|人类|小马)", text):
        targets.append("种族")
    if re.search(r"(个人介绍|自我介绍|简介)", text):
        targets.append("个人介绍")
    if re.search(r"(详细个人设定|个人设定|详细设定|我的设定|设定写了什么)", text):
        targets.append("个人设定")
    if re.search(r"(我是谁|我叫什么|我的名字|显示名|知道我什么|我的资料|资料是什么)", text):
        for item in ("显示名", "年龄", "性别", "种族", "个人介绍", "个人设定"):
            if item not in targets:
                targets.append(item)
    return targets
