from __future__ import annotations



def augment_system_prompt_for_normal_mode(
    messages: List[dict],
    *,
    vision_context: Optional[NormalVisionContext] = None,
    search_context: str = "",
    planner_result: Optional[Dict[str, Any]] = None,
    prior_image_injection_text: str = "",
    recent_messages: Optional[List[dict]] = None,
    revision_context: str = "",
    user_species: str = "",
    is_new_contact_opening: bool = False,
    character_prompt_context: str = "",
) -> None:
    """已由 build_normal_mode_augment_block + 延迟注入替代；保留供其他调用方兼容。"""
    combined = build_normal_mode_augment_block(
        vision_context=vision_context,
        search_context=search_context,
        planner_result=planner_result,
        prior_image_injection_text=prior_image_injection_text,
        recent_messages=recent_messages,
        revision_context=revision_context,
        user_species=user_species,
        is_new_contact_opening=is_new_contact_opening,
        character_prompt_context=character_prompt_context,
        raw_character_prompt_context=character_prompt_context,
        scene_anchor_card="",
    )
    if not combined:
        return
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "system":
            continue
        c = m.get("content")
        if isinstance(c, str):
            m["content"] = c.rstrip() + "\n\n" + combined
        return
    messages.insert(0, {"role": "system", "content": combined})


# 从外部读取「有图时用户文字」，用于识图/搜图
def get_last_user_text_for_vision(request) -> str:
    """参数 request 为 ChatRequest。"""
    msgs = getattr(request, "messages", None) or []
    for m in reversed(msgs):
        if getattr(m, "role", None) == "user" and not getattr(m, "isHidden", False):
            c = getattr(m, "content", None)
            if isinstance(c, str):
                return _strip_inline_images_from_text(c)
            return ""
    return ""
