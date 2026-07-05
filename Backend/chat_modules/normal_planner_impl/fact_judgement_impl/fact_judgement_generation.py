

def _coerce_normal_scene_anchor(value: Any) -> dict[str, Any]:
    src = value if isinstance(value, dict) else {}
    if "material_preparation" in src and isinstance(src.get("material_preparation"), dict):
        src = src["material_preparation"]
    if "scene_anchor" in src and isinstance(src.get("scene_anchor"), dict):
        src = src["scene_anchor"]
    anchor = _normal_scene_empty_anchor()
    status = _clean_scene_text(src.get("status"), 24).lower()
    if status not in {"active", "none", "stale"}:
        status = "active" if any(str(src.get(k) or "").strip() for k in ("summary", "reset_reason")) else "none"
    anchor["status"] = status
    raw_scene_time = src.get("scene_time")
    st = raw_scene_time if isinstance(raw_scene_time, dict) else {}
    anchor["scene_time"] = {
        "value": _clean_scene_text(
            st.get("value")
            or src.get("time")
            or (raw_scene_time if not isinstance(raw_scene_time, dict) else ""),
            160,
        ),
        "relation_to_real_time": _clean_scene_text(st.get("relation_to_real_time"), 180),
    }
    loc = src.get("location") if isinstance(src.get("location"), dict) else {}
    anchor["location"] = {
        "region": _clean_scene_text(loc.get("region") or src.get("region"), 120),
        "site": _clean_scene_text(loc.get("site") or src.get("site"), 120),
        "room": _clean_scene_text(loc.get("room") or src.get("room"), 120),
        "spot": _clean_scene_text(loc.get("spot") or src.get("spot"), 120),
    }
    cur = src.get("current_character") if isinstance(src.get("current_character"), dict) else {}
    anchor["current_character"] = {
        "name": _clean_scene_text(cur.get("name") or src.get("current_character_name"), 120),
        "position": _coerce_scene_position(cur.get("position") or src.get("current_character_position")),
        "evidence": _clean_scene_text(cur.get("evidence"), 220),
    }
    participants: list[dict[str, Any]] = []
    raw_participants = src.get("participants")
    if isinstance(raw_participants, list):
        for item in raw_participants[:12]:
            if not isinstance(item, dict):
                continue
            name = _clean_scene_text(item.get("name"), 120)
            pos = _coerce_scene_position(item.get("position"))
            evidence = _clean_scene_text(item.get("evidence"), 220)
            if name or any(pos.values()) or evidence:
                participants.append({"name": name, "position": pos, "evidence": evidence})
    anchor["participants"] = participants
    anchor["items"] = _coerce_scene_items(src.get("items") or src.get("held_items") or src.get("visible_items"))
    anchor["stale_items"] = _coerce_scene_text_list(
        src.get("stale_items") or src.get("background_items") or src.get("expired_items"),
        limit=8,
        item_limit=220,
    )
    anchor["forbidden_current_items"] = _coerce_scene_text_list(
        src.get("forbidden_current_items") or src.get("unsupported_current_items"),
        limit=8,
        item_limit=220,
    )
    anchor["physical_state"] = _coerce_physical_state(src.get("physical_state") or src.get("body_state"))
    observations: list[str] = []
    for key in ("observations", "seen_heard", "witnessed_events", "heard_messages"):
        raw_observations = src.get(key)
        if isinstance(raw_observations, list):
            observations.extend(_clean_scene_text(x, 260) for x in raw_observations if _clean_scene_text(x, 260))
        elif isinstance(raw_observations, str) and _clean_scene_text(raw_observations, 320):
            observations.append(_clean_scene_text(raw_observations, 320))
    anchor["observations"] = list(dict.fromkeys(x for x in observations if x))[:8]
    rules = src.get("continuity_rules")
    if isinstance(rules, list):
        anchor["continuity_rules"] = [_clean_scene_text(x, 220) for x in rules[:8] if _clean_scene_text(x, 220)]
    elif isinstance(rules, str):
        anchor["continuity_rules"] = [_clean_scene_text(rules, 260)]
    anchor["reset_reason"] = _clean_scene_text(src.get("reset_reason"), 260)
    anchor["summary"] = _clean_scene_text(src.get("summary"), 320)
    return anchor


def _recent_user_texts_for_scene(recent_messages: Optional[List[dict]], limit: int = 4) -> list[str]:
    texts: list[str] = []
    for msg in recent_messages or []:
        try:
            role = str(msg.get("role") or "").lower()
            content = str(msg.get("content") or "")
        except Exception:
            continue
        if role == "user" and content.strip():
            texts.append(content.strip())
    return texts[-limit:]

def _extract_explicit_normal_scene_anchor(
    recent_messages: Optional[List[dict]],
    *,
    character_name: str = "",
) -> dict[str, Any]:
    """Compatibility hook only.

    Scene acquisition is model-owned: Step 1 material prep and Step 2 fact
    judgement read the recent messages and emit scene_anchor JSON. Backend code
    must not parse user text for location/position labels or natural-language
    scene moves here.
    """
    return {}


def _merge_explicit_normal_scene_anchor(base: Any, explicit: Any) -> dict[str, Any]:
    anchor = _coerce_normal_scene_anchor(base)
    extra = _coerce_normal_scene_anchor(explicit)
    if (
        extra.get("status") == "none"
        and not extra.get("summary")
        and not extra.get("stale_items")
        and not extra.get("forbidden_current_items")
        and not _physical_state_has_material(extra.get("physical_state"))
    ):
        return anchor
    if extra.get("status") and extra.get("status") != "none":
        anchor["status"] = extra["status"]
    for key, value in (extra.get("scene_time") or {}).items():
        if _clean_scene_text(value, 180):
            anchor["scene_time"][key] = value
    for key, value in (extra.get("location") or {}).items():
        if _clean_scene_text(value, 180):
            anchor["location"][key] = value
    extra_cur = extra.get("current_character") if isinstance(extra.get("current_character"), dict) else {}
    if extra_cur:
        cur = anchor["current_character"]
        if _clean_scene_text(extra_cur.get("name"), 120):
            cur["name"] = extra_cur.get("name")
        cur_pos = cur.get("position") if isinstance(cur.get("position"), dict) else {}
        extra_pos = extra_cur.get("position") if isinstance(extra_cur.get("position"), dict) else {}
        for key, value in extra_pos.items():
            if _clean_scene_text(value, 180):
                cur_pos[key] = value
        cur["position"] = cur_pos
        if _clean_scene_text(extra_cur.get("evidence"), 220):
            cur["evidence"] = extra_cur.get("evidence")

    participants: dict[str, dict[str, Any]] = {}
    for item in anchor.get("participants") if isinstance(anchor.get("participants"), list) else []:
        if not isinstance(item, dict):
            continue
        name = _clean_scene_text(item.get("name"), 120)
        if name:
            participants[name] = item
    for item in extra.get("participants") if isinstance(extra.get("participants"), list) else []:
        if not isinstance(item, dict):
            continue
        name = _clean_scene_text(item.get("name"), 120)
        if not name:
            continue
        old = participants.get(name, {"name": name, "position": {}, "evidence": ""})
        old_pos = old.get("position") if isinstance(old.get("position"), dict) else {}
        new_pos = item.get("position") if isinstance(item.get("position"), dict) else {}
        for key, value in new_pos.items():
            if _clean_scene_text(value, 180):
                old_pos[key] = value
        old["position"] = old_pos
        if _clean_scene_text(item.get("evidence"), 220):
            old["evidence"] = item.get("evidence")
        participants[name] = old
    anchor["participants"] = list(participants.values())[:8]

    item_map: dict[str, dict[str, str]] = {}
    for item in anchor.get("items") if isinstance(anchor.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        name = _clean_scene_text(item.get("name"), 120)
        holder = _clean_scene_text(item.get("holder"), 120)
        location = _clean_scene_text(item.get("location"), 160)
        if not (name or holder or location):
            continue
        item_map[f"{holder}|{name}|{location}"] = {
            "name": name,
            "holder": holder,
            "location": location,
            "state": _clean_scene_text(item.get("state"), 160),
            "evidence": _clean_scene_text(item.get("evidence"), 220),
        }
    for item in extra.get("items") if isinstance(extra.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        name = _clean_scene_text(item.get("name"), 120)
        holder = _clean_scene_text(item.get("holder"), 120)
        location = _clean_scene_text(item.get("location"), 160)
        if not (name or holder or location):
            continue
        key = f"{holder}|{name}|{location}"
        old = item_map.get(key, {"name": name, "holder": holder, "location": location, "state": "", "evidence": ""})
        for field in ("name", "holder", "location", "state", "evidence"):
            value = _clean_scene_text(item.get(field), 220 if field == "evidence" else 160)
            if value:
                old[field] = value
        item_map[key] = old
    anchor["items"] = list(item_map.values())[:10]

    stale_items: list[str] = []
    for item in (extra.get("stale_items") or []) + (anchor.get("stale_items") or []):
        text = _clean_scene_text(item, 220)
        if text and text not in stale_items:
            stale_items.append(text)
    anchor["stale_items"] = stale_items[:8]
    forbidden_items: list[str] = []
    for item in (extra.get("forbidden_current_items") or []) + (anchor.get("forbidden_current_items") or []):
        text = _clean_scene_text(item, 220)
        if text and text not in forbidden_items:
            forbidden_items.append(text)
    anchor["forbidden_current_items"] = forbidden_items[:8]
    if _physical_state_has_material(extra.get("physical_state")):
        anchor["physical_state"] = _coerce_physical_state(extra.get("physical_state"))

    observations = []
    for item in (extra.get("observations") or []) + (anchor.get("observations") or []):
        text = _clean_scene_text(item, 260)
        if text and text not in observations:
            observations.append(text)
    anchor["observations"] = observations[:8]
    rules = []
    for item in (extra.get("continuity_rules") or []) + (anchor.get("continuity_rules") or []):
        text = _clean_scene_text(item, 240)
        if text and text not in rules:
            rules.append(text)
    anchor["continuity_rules"] = rules[:8]
    if _clean_scene_text(extra.get("summary"), 320):
        anchor["summary"] = extra.get("summary")
    return anchor


def _filter_normal_scene_anchor_to_explicit_participants(anchor: Any, explicit: Any) -> dict[str, Any]:
    """Keep group participants as a persistent spatial state table."""
    data = _coerce_normal_scene_anchor(anchor)
    return data


def _calibrate_normal_scene_current_character(anchor: Any, character_name: str = "") -> dict[str, Any]:
    data = _coerce_normal_scene_anchor(anchor)
    name = _clean_scene_text(character_name, 120)
    if not name:
        return data
    cur = data["current_character"]
    cur["name"] = name
    for item in data.get("participants") if isinstance(data.get("participants"), list) else []:
        if not isinstance(item, dict) or _clean_scene_text(item.get("name"), 120) != name:
            continue
        item_pos = item.get("position") if isinstance(item.get("position"), dict) else {}
        cur_pos = cur.get("position") if isinstance(cur.get("position"), dict) else {}
        for key, value in item_pos.items():
            if _clean_scene_text(value, 180):
                cur_pos[key] = value
        cur["position"] = cur_pos
        if _clean_scene_text(item.get("evidence"), 220):
            cur["evidence"] = item.get("evidence")
        break
    return data


def _normal_scene_current_spot(anchor: Any) -> str:
    data = _coerce_normal_scene_anchor(anchor)
    cur = data.get("current_character") if isinstance(data.get("current_character"), dict) else {}
    pos = cur.get("position") if isinstance(cur.get("position"), dict) else {}
    return _clean_scene_text(pos.get("spot"), 180)


def _normal_scene_latest_user_text(recent_messages: Optional[List[dict]]) -> str:
    texts = _recent_user_texts_for_scene(recent_messages, limit=1)
    return texts[-1] if texts else ""


def _normal_scene_turn_has_reset_signal(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False
    if re.search(r"(刚才|刚刚|继续|还在|没挪|群聊|私聊|现在在哪|哪个位置|位置在哪里|暗号|听见|看见)", compact):
        return False
    return bool(
        re.search(r"(新场景|换个场景|重置场景|另一天|第二天|今天早上|早上好|醒了|下班了|回到现实|现实时间)", compact)
    )


_NORMAL_SCENE_IDLE_STALE_GAP_MS = 6 * 60 * 60 * 1000


def _normal_scene_timestamp_ms(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        ts = int(float(value))
    except Exception:
        return 0
    if ts <= 0:
        return 0
    if 1_000_000_000 <= ts < 100_000_000_000:
        return ts * 1000
    return ts


def _normal_scene_visible_messages(recent_messages: Optional[List[dict]]) -> list[Any]:
    result: list[Any] = []
    for msg in recent_messages or []:
        hidden = False
        if isinstance(msg, dict):
            hidden = bool(msg.get("isHidden") or msg.get("is_hidden"))
        else:
            hidden = bool(getattr(msg, "isHidden", False) or getattr(msg, "is_hidden", False))
        if not hidden:
            result.append(msg)
    return result


def _normal_scene_msg_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role") or "")
    return str(getattr(msg, "role", "") or "")


def _normal_scene_msg_timestamp_ms(msg: Any) -> int:
    if isinstance(msg, dict):
        return _normal_scene_timestamp_ms(msg.get("timestamp") or msg.get("client_timestamp"))
    return _normal_scene_timestamp_ms(
        getattr(msg, "timestamp", None) or getattr(msg, "client_timestamp", None)
    )


def _normal_scene_idle_gap_ms(
    recent_messages: Optional[List[dict]],
    prior_scene_state: Optional[dict[str, Any]] = None,
) -> int:
    visible = _normal_scene_visible_messages(recent_messages)
    latest_user_idx = -1
    for idx in range(len(visible) - 1, -1, -1):
        if _normal_scene_msg_role(visible[idx]) == "user":
            latest_user_idx = idx
            break
    latest_user_ts = _normal_scene_msg_timestamp_ms(visible[latest_user_idx]) if latest_user_idx >= 0 else 0
    prev_ts = 0
    if latest_user_idx > 0:
        for msg in reversed(visible[:latest_user_idx]):
            prev_ts = _normal_scene_msg_timestamp_ms(msg)
            if prev_ts:
                break
    prior_ts = 0
    if isinstance(prior_scene_state, dict):
        prior_ts = _normal_scene_timestamp_ms(prior_scene_state.get("updated_ms"))
    if latest_user_ts and prev_ts and latest_user_ts >= prev_ts:
        return latest_user_ts - prev_ts
    if latest_user_ts and prior_ts and latest_user_ts >= prior_ts:
        return latest_user_ts - prior_ts
    if prior_ts:
        return max(0, int(time.time() * 1000) - prior_ts)
    return 0


_NORMAL_SCENE_CONTINUITY_CHANGE_RE = re.compile(
    r"(进入|进去|走到|来到|回到|前往|离开|出门|上楼|下楼|换到|移到|挪到|搬到|带到|"
    r"去(?:了|到|往|院子|客厅|厨房|卧室|房间|楼上|楼下|外面|里面|那里|这里|看|拿|找|见)|"
    r"到(?:了)?[^，。！？!?；;]{0,12}(?:院子|客厅|厨房|卧室|房间|沙发|床上|门口|楼上|楼下|外面|里面|那里|这里)|"
    r"坐到|坐下|躺到|躺下|站到|站起来|起身|靠到|爬上|跳到|"
    r"拿起|拿了|拿着|递给|交给|放下|放到|放在|丢下|丢掉|收起|带走|"
    r"开门|关门|上床|下床)"
)


def _normal_scene_turn_has_continuity_change_signal(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False
    if _normal_scene_turn_has_reset_signal(compact):
        return True
    return bool(_NORMAL_SCENE_CONTINUITY_CHANGE_RE.search(compact))


def _should_preserve_prior_normal_scene(
    recent_messages: Optional[List[dict]],
    *,
    prior_scene_anchor: Any,
    explicit_scene_anchor: Any,
) -> bool:
    if not _normal_scene_current_spot(prior_scene_anchor):
        return False
    if _normal_scene_current_spot(explicit_scene_anchor):
        return False
    latest = _normal_scene_latest_user_text(recent_messages)
    if _normal_scene_turn_has_reset_signal(latest):
        return False
    compact = re.sub(r"\s+", "", str(latest or ""))
    if _normal_scene_turn_has_continuity_change_signal(compact):
        return False
    return True


def format_normal_scene_anchor_card(scene_anchor: Any, *, scene_card: str = "") -> str:
    existing = (scene_card or "").strip()
    if existing:
        return existing[:1800]
    anchor = _coerce_normal_scene_anchor(scene_anchor)
    status = anchor.get("status") or "none"
    time_obj = anchor.get("scene_time") if isinstance(anchor.get("scene_time"), dict) else {}
    loc = anchor.get("location") if isinstance(anchor.get("location"), dict) else {}
    cur = anchor.get("current_character") if isinstance(anchor.get("current_character"), dict) else {}
    cur_pos = cur.get("position") if isinstance(cur.get("position"), dict) else {}

    def _join_location(pos: dict[str, Any]) -> str:
        bits = [
            ("大地点", pos.get("region")),
            ("中地点", pos.get("site")),
            ("小地点", pos.get("room")),
            ("微观地点", pos.get("spot")),
        ]
        text = " > ".join(f"{label}={value}" for label, value in bits if _clean_scene_text(value, 120))
        return text or "未明确"

    def _merge_location_with_position(position: dict[str, Any]) -> dict[str, Any]:
        merged = dict(loc)
        for key, value in (position or {}).items():
            if _clean_scene_text(value, 160):
                merged[key] = value
        return merged

    lines = ["【普通对话 Step 1 材料准备｜场景锚点】"]
    lines.append(f"- 状态: {status}")
    scene_time = _clean_scene_text(time_obj.get("value"), 160) or "未明确"
    relation = _clean_scene_text(time_obj.get("relation_to_real_time"), 160)
    lines.append(f"- 对话时间: {scene_time}" + (f"（{relation}）" if relation else ""))
    lines.append(f"- 地点层级: {_join_location(loc)}")
    cur_name = _clean_scene_text(cur.get("name"), 120) or "当前角色"
    cur_position = _join_location(_merge_location_with_position(cur_pos))
    posture = _clean_scene_text(cur_pos.get("posture"), 160)
    evidence = _clean_scene_text(cur.get("evidence"), 200)
    lines.append(
        f"- {cur_name}.position: {cur_position}"
        + (f"；姿态={posture}" if posture else "")
        + (f"；证据={evidence}" if evidence else "")
    )
    participants = anchor.get("participants") if isinstance(anchor.get("participants"), list) else []
    if participants:
        lines.append("- 其他角色位置:")
        for item in participants[:8]:
            if not isinstance(item, dict):
                continue
            name = _clean_scene_text(item.get("name"), 120) or "未命名角色"
            pos = item.get("position") if isinstance(item.get("position"), dict) else {}
            merged_pos = _merge_location_with_position(pos)
            posture = _clean_scene_text(pos.get("posture"), 160)
            evidence = _clean_scene_text(item.get("evidence"), 180)
            lines.append(
                f"  - {name}: {_join_location(merged_pos)}"
                + (f"；姿态={posture}" if posture else "")
                + (f"；证据={evidence}" if evidence else "")
            )
    exact_positions: list[str] = []

    def _add_exact_position(name: str, position: dict[str, Any]) -> None:
        spot = _clean_scene_text((position or {}).get("spot"), 120)
        label = _clean_scene_text(name, 120)
        if not (label and spot):
            return
        value = f"{label}.position.spot={spot}"
        if value not in exact_positions:
            exact_positions.append(value)

    _add_exact_position(cur_name, cur_pos)
    for item in participants[:8]:
        if not isinstance(item, dict):
            continue
        _add_exact_position(
            _clean_scene_text(item.get("name"), 120) or "未命名角色",
            item.get("position") if isinstance(item.get("position"), dict) else {},
        )
    if exact_positions:
        lines.append("- 位置锚点（供核对，不要求逐字复述）: " + "；".join(exact_positions[:10]))
    items = anchor.get("items") if isinstance(anchor.get("items"), list) else []
    if items:
        lines.append("- 物品状态:")
        exact_items: list[str] = []
        for item in items[:8]:
            if not isinstance(item, dict):
                continue
            name = _clean_scene_text(item.get("name"), 120) or "未命名物品"
            holder = _clean_scene_text(item.get("holder"), 120)
            item_location = _clean_scene_text(item.get("location"), 160)
            state = _clean_scene_text(item.get("state"), 160)
            evidence = _clean_scene_text(item.get("evidence"), 180)
            pieces = [name]
            if holder:
                pieces.append(f"持有者={holder}")
            if item_location:
                pieces.append(f"位置={item_location}")
            if state:
                pieces.append(f"状态={state}")
            if evidence:
                pieces.append(f"证据={evidence}")
            lines.append("  - " + "；".join(pieces))
            exact = f"{name}.item"
            if holder:
                exact += f".holder={holder}"
            if item_location:
                exact += f".location={item_location}"
            if exact not in exact_items:
                exact_items.append(exact)
        if exact_items:
            lines.append("- 物品锚点（供核对，不要求逐字复述）: " + "；".join(exact_items[:10]))
    stale_items = anchor.get("stale_items") if isinstance(anchor.get("stale_items"), list) else []
    forbidden_items = anchor.get("forbidden_current_items") if isinstance(anchor.get("forbidden_current_items"), list) else []
    if stale_items or forbidden_items:
        boundary_bits: list[str] = []
        if stale_items:
            boundary_bits.append(
                "历史/作废物品=" + "；".join(_clean_scene_text(x, 120) for x in stale_items[:5] if _clean_scene_text(x, 120))
            )
        if forbidden_items:
            boundary_bits.append(
                "本轮禁止写成当前物品/感官残留=" + "；".join(_clean_scene_text(x, 120) for x in forbidden_items[:5] if _clean_scene_text(x, 120))
            )
        lines.append("- 物品边界: " + "；".join(x for x in boundary_bits if x))
    physical_state = anchor.get("physical_state") if isinstance(anchor.get("physical_state"), dict) else {}

    def _format_physical_subject(label: str, subject: Any) -> str:
        data = subject if isinstance(subject, dict) else {}
        bits: list[str] = []
        for field, title in (
            ("intoxication", "醉酒"),
            ("stamina", "体力"),
            ("fatigue", "疲惫"),
            ("injury", "伤势"),
            ("sleep_state", "睡眠/清醒"),
            ("sensory_residue", "感官残留"),
            ("other", "其他"),
        ):
            value = _clean_scene_text(data.get(field), 80)
            if value:
                bits.append(f"{title}={value}")
        scope = _clean_scene_text(data.get("scope"), 40)
        evidence = _clean_scene_text(data.get("evidence"), 120)
        if scope and scope != "unknown":
            bits.append(f"scope={scope}")
        if evidence:
            bits.append(f"证据={evidence}")
        return f"{label}: " + ("；".join(bits) if bits else "未明确")

    if _physical_state_has_material(physical_state):
        lines.append("- 身体状态:")
        lines.append("  - " + _format_physical_subject(cur_name, physical_state.get("current_character")))
        lines.append("  - " + _format_physical_subject("用户", physical_state.get("user")))
        stale_states = physical_state.get("stale_states") if isinstance(physical_state.get("stale_states"), list) else []
        if stale_states:
            lines.append(
                "  - 作废/背景身体状态: "
                + "；".join(_clean_scene_text(x, 120) for x in stale_states[:5] if _clean_scene_text(x, 120))
            )
        reset_policy = _clean_scene_text(physical_state.get("reset_policy"), 60)
        guidance = _clean_scene_text(physical_state.get("guidance"), 180)
        if reset_policy and reset_policy != "unknown":
            lines.append("  - 身体状态继承策略: " + reset_policy + (f"；{guidance}" if guidance else ""))
    observations = anchor.get("observations") if isinstance(anchor.get("observations"), list) else []
    if observations:
        lines.append("- 历史观察/群聊见闻（用于回忆核对；不是当前正在发生的动作，除非用户明确追问刚才群聊/暗号/见闻）:")
        for item in observations[:6]:
            obs = _clean_scene_text(item, 240)
            if obs:
                lines.append(f"  - {obs}")
    rules = anchor.get("continuity_rules") if isinstance(anchor.get("continuity_rules"), list) else []
    reset = _clean_scene_text(anchor.get("reset_reason"), 260)
    summary = _clean_scene_text(anchor.get("summary"), 320)
    if summary:
        lines.append(f"- 摘要: {summary}")
    if rules:
        lines.append("- 继承/作废规则: " + "；".join(_clean_scene_text(x, 180) for x in rules if _clean_scene_text(x, 180)))
    elif reset:
        lines.append(f"- 继承/作废规则: {reset}")
    else:
        lines.append("- 继承/作废规则: 只继承最近可见对话、上下文记忆或用户当前消息明确支持的物理场景；现实时间不能自动打断戏内时间。")
    card_text_so_far = "\n".join(lines)
    if (
        status in {"stale", "none"}
        or "background_only" in card_text_so_far
        or "历史/作废物品" in card_text_so_far
        or "本轮禁止写成当前物品" in card_text_so_far
    ):
        lines.append(
            "- 连续性硬规则: 本卡为 stale/background_only 或列出作废物品时，通用“无变化保持”只在用户明确说继续/刚才/还在/接着/那个场景时生效；"
            "否则旧地点、旧姿势、旧茶几和旧物品只作历史背景，不得写成当前正在看见、正在拿着、仍在现场或当前所在。"
        )
    else:
        lines.append("- 连续性硬规则: 用户未明确移动/换房间/改变姿势/拿放物品/重置场景时，地点、各角色 position/posture、物品状态默认保持；角色设定、卧室/床等高相关词和旧记忆不能覆盖当前锚点。")
    return "\n".join(lines).strip()[:1800]


async def _ensure_normal_scene_state_table(conn: aiosqlite.Connection) -> None:
    await conn.execute(_NORMAL_SCENE_STATE_SQL)
    await conn.execute(_NORMAL_SCENE_INDEX_SQL)


async def load_normal_scene_state(
    username: Optional[str],
    character_id: Optional[str],
    conversation_id: Optional[str] = None,
) -> dict[str, Any]:
    if not (username and character_id):
        return {}
    db = get_database()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await _ensure_normal_scene_state_table(conn)
            conv = str(conversation_id or "")
            if conv:
                query = """SELECT scene_json, scene_card, updated_ms, conversation_id
                           FROM normal_scene_state
                           WHERE username = ? AND character_id = ? AND conversation_id = ?
                           ORDER BY updated_ms DESC
                           LIMIT 1"""
                params = (username, character_id, conv)
            else:
                query = """SELECT scene_json, scene_card, updated_ms, conversation_id
                           FROM normal_scene_state
                           WHERE username = ? AND character_id = ? AND conversation_id = ''
                           ORDER BY updated_ms DESC
                           LIMIT 1"""
                params = (username, character_id)
            async with conn.execute(query, params) as cur:
                row = await cur.fetchone()
            if row:
                try:
                    scene_json = json.loads(row["scene_json"] or "{}")
                except Exception:
                    scene_json = {}
                return {
                    "scene_anchor": _coerce_normal_scene_anchor(scene_json),
                    "scene_card": str(row["scene_card"] or ""),
                    "updated_ms": int(row["updated_ms"] or 0),
                    "conversation_id": str(row["conversation_id"] or ""),
                }
    except Exception as exc:
        logger.debug("[NormalMaterialPrep] load scene state failed: %s", exc)
    return {}
