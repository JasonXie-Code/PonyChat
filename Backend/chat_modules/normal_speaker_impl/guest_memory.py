

def _set_unresolved_at_mentions(request: ChatRequest, values: list[str]) -> None:
    mentions = [str(value or "").strip() for value in values if str(value or "").strip()]
    if mentions:
        setattr(request, "_normal_unresolved_at_mentions", mentions)
        return
    if hasattr(request, "_normal_unresolved_at_mentions"):
        try:
            delattr(request, "_normal_unresolved_at_mentions")
        except Exception:
            setattr(request, "_normal_unresolved_at_mentions", [])


async def resolve_explicit_at_reply_character_ids(request: ChatRequest) -> list[str]:
    """Resolve visible @names to owned character ids before falling back to LLM routing."""
    if (getattr(request, "mode", None) or "normal") != "normal" or getattr(request, "is_summary_request", False):
        _set_unresolved_at_mentions(request, [])
        return []
    if requested_reply_character_ids(request):
        _set_unresolved_at_mentions(request, [])
        return []
    mention_names = extract_at_mention_names(_latest_visible_user_text(request))
    if not mention_names:
        _set_unresolved_at_mentions(request, [])
        return []

    characters = await load_owned_visible_characters_for_mentions(getattr(request, "username", None))
    resolved: list[str] = []
    unresolved: list[str] = []
    for mention_name in mention_names:
        cid = _resolve_mention_name_to_character_id(mention_name, characters)
        if cid:
            resolved.append(cid)
        else:
            unresolved.append(mention_name)
    if unresolved:
        _set_unresolved_at_mentions(request, unresolved)
        logger.info(
            "[NormalSpeaker] 未解析 @ 角色 user=%s mentions=%s",
            getattr(request, "username", ""),
            unresolved,
        )
        return []
    _set_unresolved_at_mentions(request, [])
    return _dedupe_character_ids(resolved)


def character_name_appears_in_recent_context(character: dict[str, Any], recent_text: str) -> bool:
    text = _compact_for_name_match(recent_text)
    if not text:
        return False
    raw_names = [
        character.get("name"),
        character.get("displayName"),
        character.get("profileName"),
    ]
    names: list[str] = []
    for raw in raw_names:
        name = str(raw or "").strip()
        if name and name not in names:
            names.append(name)
    for name in names:
        compact = _compact_for_name_match(name)
        if compact and compact in text:
            return True
    return False


def speaker_context_prompt(request: ChatRequest) -> str:
    if not is_guest_speaker(request):
        return ""
    speaker_name = speaker_display_name(request)
    main_name = main_display_name(request)
    return (
        "【本轮临时发言者】\n"
        f"当前主会话角色是「{main_name}」，但用户本轮通过 @ 点名「{speaker_name}」临时加入这段对话。\n"
        f"本轮生成以「{speaker_name}」为当前发言主体：使用「{speaker_name}」自己的角色设定、长期记忆、普通对话上下文、情绪与关系状态；"
        f"「{main_name}」的私有长期记忆不自动等于「{speaker_name}」知道的事。\n"
        f"最终回复必须只以「{speaker_name}」身份写一次；不要替「{main_name}」发言，不要把自己写成「{main_name}」，"
        "也不要让其他角色插话。\n"
        f"「{speaker_name}」能看到最近对话上下文，需要接住用户当前话题并推进情境，像被叫进临时群聊/现场的人一样自然回应。\n"
        f"如果提到「{main_name}」或本主会话，请保持第三方关系清楚；不要假装这就是「{speaker_name}」自己的主聊天窗口。\n"
        f"当前正文只写「{speaker_name}」这一位角色的本轮发言；如果需要让「{main_name}」或其他在场角色接下一句，"
        "正文里只能自然把话递出去，不能代替对方说话；是否真的让对方接话由后端独立 router 判断。"
    )


def guest_memory_user_message(request: ChatRequest, latest_user_text: str) -> str:
    if not is_guest_speaker(request):
        return latest_user_text
    speaker_name = speaker_display_name(request)
    main_name = main_display_name(request)
    recent_context = str(getattr(request, "_normal_speaker_recent_context", "") or "").strip()
    context_part = f"\n\n当时可见的部分上下文：\n{recent_context[:1800]}" if recent_context else ""
    return (
        f"在「{main_name}」的主聊天里，用户 @ 了「{speaker_name}」临时发言。\n"
        f"用户本轮消息：{latest_user_text.strip() or '（无文字）'}"
        f"{context_part}\n\n"
        f"请把这件事记成「{speaker_name}」自己曾被叫到「{main_name}」的对话中，并说过/做过后续回复。"
    )


def guest_main_memory_assistant_message(request: ChatRequest, assistant_text: str) -> str:
    if not is_guest_speaker(request):
        return assistant_text
    speaker_name = speaker_display_name(request)
    main_name = main_display_name(request)
    return (
        f"【临时群聊发言｜实际发言者={speaker_name}｜主聊天角色={main_name}】\n"
        f"注意：以下内容是「{speaker_name}」的临时发言/动作，不是「{main_name}」的发言或动作；"
        f"「{main_name}」只能记为在自己的主聊天现场听见/看见了这次发言。\n"
        f"{assistant_text.strip()}"
    ).strip()


def guest_direct_memory_content(request: ChatRequest, latest_user_text: str, assistant_text: str) -> str:
    speaker_name = speaker_display_name(request)
    main_name = main_display_name(request)
    recent_context = str(getattr(request, "_normal_speaker_recent_context", "") or "").strip()
    context_hint = "；当时处在临时群聊现场，完整原文保留在主会话记录中。" if recent_context else ""
    context_summary = ""
    if recent_context:
        context_summary = (
            "当时可见现场原文摘要："
            + _clip_guest_group_memory_text(recent_context, 760)
            + "。"
        )
    return (
        f"我曾在「{main_name}」的主聊天里被用户 @ 临时加入发言。"
        f"高优先级事实：若当时可见现场或用户原文里有暗号、口令、测试标记、房间名或位置名，之后被问到时应按原文完整复述；不要只记关键词。"
        f"用户当时说：{_clip_guest_group_memory_text(latest_user_text, 180) or '（无文字）'}。"
        f"我作为「{speaker_name}」回复：{_clip_guest_group_memory_text(assistant_text, 260)}。"
        f"{context_summary}"
        f"{context_hint}"
    )


async def write_guest_direct_memory_once(
    request: ChatRequest,
    assistant_text: str = "",
    *,
    wait: bool = True,
) -> bool:
    """Persist raw temporary-group evidence as soon as a guest speaker is resolved."""
    if not is_guest_speaker(request):
        return False
    if getattr(request, "_normal_guest_direct_memory_written", False):
        return False
    if getattr(request, "memory_enabled", True) is False:
        return False
    username = str(getattr(request, "username", "") or "").strip()
    speaker_id = effective_speaker_character_id(request)
    if not username or not speaker_id:
        return False
    latest_user_text = _latest_visible_user_text(request)
    content = guest_direct_memory_content(request, latest_user_text, assistant_text or "")
    if not content.strip():
        return False
    async def _persist() -> bool:
        from ..db.memory_dao import add_memory

        memory_id = await add_memory(
            username,
            speaker_id,
            "episode",
            content,
            source="normal_guest_group",
            importance=8,
        )
        if memory_id:
            setattr(request, "_normal_guest_direct_memory_written", True)
            return True
        return False

    if not wait:
        if not bool(getattr(request, "_normal_enable_guest_direct_prewrite", False)):
            return False
        try:
            asyncio.create_task(_persist())
            return False
        except RuntimeError:
            return False

    try:
        return await asyncio.wait_for(_persist(), timeout=0.8)
    except asyncio.TimeoutError:
        logger.debug("[NormalSpeaker] 写入临时群聊原文摘要记忆超时，跳过本次预写入")
    except Exception as exc:
        logger.debug("[NormalSpeaker] 写入临时群聊原文摘要记忆失败: %s", exc)
    return False


def guest_group_participant_character_ids(request: ChatRequest) -> list[str]:
    """Participants whose memory should receive the temporary group event."""
    main_id = main_character_id(request)
    speaker_id = effective_speaker_character_id(request)
    ids: list[str] = []

    def add(cid: str) -> None:
        cid = str(cid or "").strip()
        if cid and cid not in ids:
            ids.append(cid)

    add(main_id)
    recent = _visible_recent_scene_messages(request, include_latest_user=True)
    for msg in recent:
        if getattr(msg, "role", None) != "assistant":
            continue
        add(str(getattr(msg, "speaker_character_id", "") or "").strip() or main_id)
        if len(ids) >= _GUEST_GROUP_MEMORY_MAX_PARTICIPANTS:
            break
    add(speaker_id)
    return ids[:_GUEST_GROUP_MEMORY_MAX_PARTICIPANTS]


def guest_group_memory_content(
    request: ChatRequest,
    *,
    participant_name: str,
    participant_is_speaker: bool,
    latest_user_text: str,
    assistant_text: str,
) -> str:
    speaker_name = speaker_display_name(request)
    main_name = main_display_name(request)
    scene = str(getattr(request, "_normal_speaker_recent_context", "") or "").strip()
    scene_hint = "；此前现场属于临时群聊，完整原文保留在主会话记录中。" if scene else ""
    if participant_is_speaker:
        return guest_direct_memory_content(request, latest_user_text, assistant_text)
    return (
        f"我作为「{participant_name}」参与或可见一次由「{main_name}」主聊天形成的临时群聊。"
        f"用户本轮让「{speaker_name}」发言，用户说：{_clip_guest_group_memory_text(latest_user_text, 180) or '（无文字）'}。"
        f"「{speaker_name}」回复：{_clip_guest_group_memory_text(assistant_text, 260)}。"
        f"{scene_hint}"
    )


def _guest_group_utterance_speaker_id(msg: ChatMessage, *, main_id: str) -> str:
    if getattr(msg, "role", None) != "assistant":
        return ""
    return str(getattr(msg, "speaker_character_id", "") or "").strip() or main_id


def _guest_group_utterance_speaker_name(msg: ChatMessage, *, main_name: str, main_id: str) -> str:
    if getattr(msg, "role", None) == "user":
        return "用户"
    name = str(getattr(msg, "speaker_name", "") or "").strip()
    sid = _guest_group_utterance_speaker_id(msg, main_id=main_id)
    if name:
        return name
    if sid == main_id:
        return main_name or "主角色"
    return sid or "角色"


def _guest_group_recent_utterances(
    request: ChatRequest,
    *,
    latest_user_text: str,
    assistant_text: str,
) -> list[dict[str, Any]]:
    """Return recent group utterances, merging adjacent assistant bubbles.

    Multiple text bubbles produced by one assistant reply are stored as separate
    message rows, but for group memory they count as one utterance.
    """
    main_id = main_character_id(request)
    main_name = main_display_name(request)
    speaker_id = effective_speaker_character_id(request)
    speaker_name = speaker_display_name(request)
    rows: list[dict[str, Any]] = []

    def add_row(
        *,
        role: str,
        content: str,
        speaker_id_value: str = "",
        speaker_name_value: str = "",
    ) -> None:
        text = _clip_guest_group_memory_text(content, 700)
        if not text:
            return
        role = str(role or "").strip().lower()
        if role not in {"user", "assistant"}:
            return
        sid = str(speaker_id_value or "").strip()
        sname = str(speaker_name_value or "").strip()
        if role == "assistant":
            sid = sid or main_id
            sname = sname or (main_name if sid == main_id else sid)
            if rows and rows[-1].get("role") == "assistant" and rows[-1].get("speaker_id") == sid:
                rows[-1]["content"] = _clip_guest_group_memory_text(
                    str(rows[-1].get("content") or "") + "\n" + text,
                    1200,
                )
                return
        else:
            sname = "用户"
        rows.append(
            {
                "role": role,
                "speaker_id": sid,
                "speaker_name": sname,
                "content": text,
            }
        )

    for msg in _visible_recent_scene_messages(request, include_latest_user=True):
        role = str(getattr(msg, "role", "") or "").strip().lower()
        content = str(getattr(msg, "content", "") or "").strip()
        if role == "user":
            add_row(role="user", content=content)
        elif role == "assistant":
            add_row(
                role="assistant",
                content=content,
                speaker_id_value=_guest_group_utterance_speaker_id(msg, main_id=main_id),
                speaker_name_value=_guest_group_utterance_speaker_name(msg, main_name=main_name, main_id=main_id),
            )

    latest_user_clean = _clip_guest_group_memory_text(latest_user_text, 700)
    if latest_user_clean and not (
        rows
        and rows[-1].get("role") == "user"
        and str(rows[-1].get("content") or "").strip() == latest_user_clean
    ):
        add_row(role="user", content=latest_user_clean)

    add_row(
        role="assistant",
        content=assistant_text,
        speaker_id_value=speaker_id,
        speaker_name_value=speaker_name,
    )
    return rows[-40:]


def _guest_group_window_extract_messages(
    utterances: list[dict[str, Any]],
    *,
    target_character_id: str,
) -> list[dict[str, Any]]:
    target_character_id = str(target_character_id or "").strip()
    if not target_character_id or not utterances:
        return []
    latest_idx = len(utterances) - 1
    anchor_indices: list[int] = []
    for idx, item in enumerate(utterances):
        if item.get("role") != "assistant" or str(item.get("speaker_id") or "") != target_character_id:
            continue
        # Process the current utterance immediately, and revisit a prior
        # utterance only while the newest utterance is still inside its
        # "two following utterances" window.
        distance_to_latest = latest_idx - idx
        if distance_to_latest == 0 or 0 < distance_to_latest <= 2:
            anchor_indices.append(idx)
    if not anchor_indices:
        return []

    keep_indices: set[int] = set()
    for anchor_idx in anchor_indices:
        start = max(0, anchor_idx - 8)
        end = min(len(utterances), anchor_idx + 3)
        keep_indices.update(range(start, end))

    messages: list[dict[str, Any]] = []
    for idx in sorted(keep_indices):
        item = utterances[idx]
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if not role or not content:
            continue
        msg = {"role": role, "content": content}
        if role == "assistant":
            msg["speaker_name"] = str(item.get("speaker_name") or "").strip()
        messages.append(msg)
    return messages


async def guest_group_memory_extract_specs(
    request: ChatRequest,
    *,
    username: str,
    participant_ids: list[str],
    latest_user_text: str,
    assistant_text: str,
) -> list[dict[str, Any]]:
    """Build model-extractor jobs for temporary group known windows.

    For every role who has spoken in the temporary group, the role knows the
    eight utterances before its own utterance and the two utterances after it
    when those following utterances already exist.  Adjacent assistant bubbles
    from the same speaker count as one utterance.
    """
    username = str(username or "").strip()
    utterances = _guest_group_recent_utterances(
        request,
        latest_user_text=latest_user_text,
        assistant_text=assistant_text,
    )
    specs: list[dict[str, Any]] = []

    for raw_pid in participant_ids or []:
        pid = str(raw_pid or "").strip()
        if not pid:
            continue
        window_messages = _guest_group_window_extract_messages(
            utterances,
            target_character_id=pid,
        )
        if not window_messages:
            continue
        specs.append(
            {
                "character_id": pid,
                "messages": window_messages,
                "types": ["episode", "activity", "relationship"],
                "source": "normal_guest_group",
                "debug_stage": "NORMAL_STEP_4_GUEST_GROUP_MEMORY_EXTRACT_REQUEST",
            }
        )
    return specs


async def prepare_normal_reply_speaker(request: ChatRequest) -> None:
    if (getattr(request, "mode", None) or "normal") != "normal" or getattr(request, "is_summary_request", False):
        return
    username = str(getattr(request, "username", "") or "").strip()
    main_id = main_character_id(request)
    reply_id = requested_reply_character_id(request)

    main_char = None
    if username and main_id:
        main_char = await load_owned_visible_character(username, main_id)
    if main_char:
        setattr(request, "_normal_main_character_name", str(main_char.get("name") or main_id).strip())
        setattr(request, "_normal_main_character_avatar", str(main_char.get("avatar") or "").strip())

    if not reply_id or reply_id == main_id:
        setattr(request, "_normal_speaker_character_id", main_id)
        setattr(request, "_normal_speaker_character_name", str((main_char or {}).get("name") or main_id).strip())
        setattr(request, "_normal_speaker_character_avatar", str((main_char or {}).get("avatar") or "").strip())
        setattr(request, "_normal_speaker_is_guest", False)
        return

    if not username or not main_id:
        raise HTTPException(status_code=400, detail={"status": "invalid_reply_character", "reason": "missing_main_character"})
    if not main_char:
        raise HTTPException(status_code=403, detail={"status": "invalid_reply_character", "reason": "main_character_not_owned"})

    reply_char = await load_owned_visible_character(username, reply_id)
    if not reply_char:
        raise HTTPException(status_code=403, detail={"status": "invalid_reply_character", "reason": "reply_character_not_owned"})

    recent_text = recent_at_eligibility_text(
        request,
        main_name=str(main_char.get("name") or main_id).strip(),
    )
    quoted_reply_id = quoted_reply_character_id(request)
    if reply_id != quoted_reply_id and not character_name_appears_in_recent_context(reply_char, recent_text):
        raise HTTPException(
            status_code=400,
            detail={
                "status": "invalid_reply_character",
                "reason": "reply_character_not_recently_mentioned",
                "message": "被 @ 的角色必须出现在当前对话最近 8 轮上下文中。",
            },
        )

    setattr(request, "_normal_speaker_character_id", reply_id)
    setattr(request, "_normal_speaker_character_name", str(reply_char.get("name") or reply_id).strip())
    setattr(request, "_normal_speaker_character_avatar", str(reply_char.get("avatar") or "").strip())
    setattr(request, "_normal_speaker_is_guest", True)
    setattr(request, "_normal_speaker_recent_context", recent_text)
    await write_guest_direct_memory_once(request, "", wait=False)
    logger.info(
        "[NormalSpeaker] 本轮使用临时发言者 user=%s main=%s guest=%s guest_name=%s",
        username,
        main_id[:12],
        reply_id[:12],
        str(reply_char.get("name") or reply_id),
    )
