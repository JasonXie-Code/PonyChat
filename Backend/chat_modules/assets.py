from __future__ import annotations

from .Prompts import ASSET_SELECTOR_SYSTEM

import json
import re
from typing import Any

import aiosqlite

from ..config import logger
from ..db import get_database
from ..providers.llm_call import call_llm_payload
from ..reasoning_config import apply_llm_task_payload_config, llm_task_float
from ..reasoning_policy import resolve_software_reasoning_policy


_STAGE_RANK = {
    "stranger": 0,
    "familiar": 1,
    "close": 2,
    "ambiguous": 3,
    "lover": 4,
}

ASSET_SEND_INTENSITY_THRESHOLD = 70
ASSET_RECENT_COOLDOWN_LIMIT = 3

_EXPLICIT_ASSET_REQUEST_RE = re.compile(
    r"(?:用户|对方|user).{0,12}(?:明确|直接|显式).{0,12}(?:要求|请求|想要|要|让).{0,12}(?:发|发送|来|给).{0,8}(?:表情包|贴纸|sticker|emoji)"
    r"|(?:用户|对方|user).{0,12}(?:要求|请求|想要|要|让).{0,12}(?:发|发送|来|给).{0,8}(?:表情包|贴纸|sticker|emoji)"
    r"|(?:发|发送|来一个|来个|来张|给我|给用户|给对方).{0,8}(?:表情包|贴纸|sticker|emoji)",
    re.IGNORECASE,
)



def _coerce_str_list(value: Any, *, limit: int = 16) -> list[str]:
    if isinstance(value, list):
        out = [str(v).strip() for v in value if str(v).strip()]
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                out = [str(v).strip() for v in parsed if str(v).strip()]
            else:
                out = [value.strip()]
        except Exception:
            out = [x.strip() for x in re.split(r"[,，、\s]+", value) if x.strip()]
    else:
        out = []
    deduped: list[str] = []
    seen: set[str] = set()
    for item in out:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item[:80])
        if len(deduped) >= limit:
            break
    return deduped


def _coerce_int_0_100(value: Any) -> int:
    try:
        n = int(float(value))
    except Exception:
        return 0
    return max(0, min(n, 100))


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on", "required", "explicit", "must", "必须", "明确"}


def _asset_plan_has_explicit_request(value: dict[str, Any]) -> bool:
    for key in ("explicit_request", "user_requested", "required", "must_send", "force_send"):
        if _coerce_bool(value.get(key)):
            return True
    necessity_text = str(value.get("necessity") or value.get("priority") or "").strip().lower()
    if necessity_text in {"required", "explicit", "must", "must_send", "必须", "明确要求"}:
        return True
    text_parts: list[str] = []
    for key in ("query", "intent", "reason", "speech_reason", "reply_intent"):
        raw = value.get(key)
        if raw is not None:
            text_parts.append(str(raw))
    for key in ("tags", "emotions", "scenes", "custom_tags"):
        text_parts.extend(_coerce_str_list(value.get(key), limit=24))
    joined = " ".join(text_parts)
    return bool(_EXPLICIT_ASSET_REQUEST_RE.search(joined))


def _extract_character_name_from_context(character_prompt_context: str) -> str:
    for line in str(character_prompt_context or "").splitlines():
        text = line.strip()
        if not text:
            continue
        for prefix in ("角色名称：", "角色名称:", "名称：", "名称:"):
            if text.startswith(prefix):
                return text[len(prefix):].strip()[:80]
    return ""


def _preferred_character_name_terms(
    character_prompt_context: str = "",
    character_id: str | None = None,
) -> list[str]:
    raw_terms: list[str] = []
    name = _extract_character_name_from_context(character_prompt_context)
    if name:
        raw_terms.append(name)
        compact = re.sub(r"\s+", "", name)
        if compact and compact != name:
            raw_terms.append(compact)
        for sep in (" / ", "/", "、", "，", ",", "|"):
            if sep in name:
                raw_terms.extend(part.strip() for part in name.split(sep))
        if len(compact) >= 4 and compact.endswith("黛西"):
            raw_terms.append(compact[:-2])
        if len(compact) >= 3 and compact.endswith("派"):
            raw_terms.append(compact[:-1])
        if re.search(r"[A-Za-z]", name):
            raw_terms.extend(part for part in re.split(r"[\s_-]+", name) if len(part) >= 2)

    cid = str(character_id or "").strip()
    if cid:
        raw_terms.append(cid)
        raw_terms.extend(part for part in re.split(r"[_\-\s]+", cid) if len(part) >= 2)

    out: list[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        item = str(term or "").strip()
        if not item or len(item) < 2:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item[:80])
        if len(out) >= 8:
            break
    return out


def coerce_asset_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"enabled": False, "count": 0, "send_intensity": 0}
    enabled = bool(value.get("enabled"))
    count = max(0, min(int(value.get("count") or 0), 4))
    raw_send_intensity = None
    for key in ("send_intensity", "necessity", "asset_intensity", "emotional_intensity"):
        if value.get(key) is not None:
            raw_send_intensity = value.get(key)
            break
    send_intensity = _coerce_int_0_100(raw_send_intensity)
    explicit_request = _asset_plan_has_explicit_request(value)
    if explicit_request and enabled and count > 0 and send_intensity < ASSET_SEND_INTENSITY_THRESHOLD:
        send_intensity = ASSET_SEND_INTENSITY_THRESHOLD
    if not enabled or count <= 0:
        return {
            "enabled": False,
            "count": 0,
            "send_intensity": send_intensity,
            "explicit_request": explicit_request,
        }
    if send_intensity < ASSET_SEND_INTENSITY_THRESHOLD:
        return {
            "enabled": False,
            "count": 0,
            "send_intensity": send_intensity,
            "explicit_request": explicit_request,
            "reason": (
                str(value.get("reason") or "").strip()[:220]
                or f"表情包必要强度 {send_intensity} 低于阈值 {ASSET_SEND_INTENSITY_THRESHOLD}"
            ),
        }
    emotions = _coerce_str_list(value.get("emotions"))
    scenes = _coerce_str_list(value.get("scenes"))
    tags = _coerce_str_list(value.get("tags") or value.get("custom_tags"))
    query = str(value.get("query") or value.get("intent") or value.get("reason") or "").strip()
    avoid = _coerce_str_list(value.get("avoid") or value.get("avoid_semantics"))
    placement = str(value.get("placement") or "after_text").strip().lower()
    if placement not in {"before_text", "after_text", "between_text", "asset_only"}:
        placement = "after_text"
    return {
        "enabled": True,
        "count": count,
        "send_intensity": send_intensity,
        "explicit_request": explicit_request,
        "query": query[:500],
        "tags": [*tags, *emotions, *scenes][:24],
        "emotions": emotions,
        "scenes": scenes,
        "avoid": avoid,
        "intensity": str(value.get("intensity") or "").strip(),
        "allow_initiative": bool(value.get("allow_initiative")),
        "placement": placement,
        "reason": str(value.get("reason") or "").strip()[:300],
    }


def coerce_reply_sequence(value: Any, asset_plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(value, list):
        asset_idx = 0
        text_idx = 0
        for item in value[:8]:
            if not isinstance(item, dict):
                continue
            typ = str(item.get("type") or "").strip().lower()
            if typ == "asset":
                asset_idx += 1
                rid = str(item.get("request_id") or item.get("id") or f"asset_{asset_idx}").strip()
                query = str(item.get("query") or item.get("intent") or item.get("reason") or "").strip()
                tags = _coerce_str_list(item.get("tags") or item.get("emotions") or item.get("custom_tags"))
                avoid = _coerce_str_list(item.get("avoid") or item.get("avoid_semantics"))
                out.append({
                    "type": "asset",
                    "request_id": rid[:80],
                    "query": query[:500],
                    "tags": tags[:16],
                    "avoid": avoid[:16],
                    "reason": str(item.get("reason") or "").strip()[:300],
                })
            elif typ == "text":
                text_idx += 1
                out.append({
                    "type": "text",
                    "intent": str(item.get("intent") or item.get("reply_intent") or f"text_{text_idx}").strip()[:500],
                })

    plan = coerce_asset_plan(asset_plan) if asset_plan else {"enabled": False, "count": 0}
    if not plan.get("enabled"):
        out = [item for item in out if item.get("type") != "asset"]
    if not out and plan.get("enabled"):
        asset_units = [
            {
                "type": "asset",
                "request_id": f"asset_{i + 1}",
                "query": plan.get("query") or plan.get("reason") or "",
                "tags": plan.get("tags") or plan.get("emotions") or [],
                "avoid": plan.get("avoid") or [],
                "reason": plan.get("reason") or "",
            }
            for i in range(int(plan.get("count") or 0))
        ]
        placement = plan.get("placement") or "after_text"
        if placement == "before_text":
            out = [*asset_units, {"type": "text", "intent": "reply_text"}]
        elif placement == "asset_only":
            out = asset_units
        elif placement == "between_text" and asset_units:
            out = [{"type": "text", "intent": "reply_opening"}, asset_units[0], {"type": "text", "intent": "reply_followup"}, *asset_units[1:]]
        else:
            out = [{"type": "text", "intent": "reply_text"}, *asset_units]

    if not out:
        out = [{"type": "text", "intent": "reply_text"}]
    if not any(item.get("type") == "text" for item in out):
        return out[:4]
    return out[:6]


def _asset_requests_from_sequence(sequence: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for item in sequence:
        if item.get("type") != "asset":
            continue
        rid = str(item.get("request_id") or f"asset_{len(requests) + 1}").strip()
        query = str(item.get("query") or plan.get("query") or plan.get("reason") or "").strip()
        tags = _coerce_str_list(item.get("tags")) or list(plan.get("tags") or plan.get("emotions") or [])
        avoid = _coerce_str_list(item.get("avoid")) or list(plan.get("avoid") or [])
        preferred_character_names = (
            _coerce_str_list(item.get("preferred_character_names"), limit=8)
            or _coerce_str_list(plan.get("preferred_character_names"), limit=8)
        )
        requests.append({
            "request_id": rid,
            "query": query,
            "tags": tags,
            "avoid": avoid,
            "intensity": plan.get("intensity") or "",
            "preferred_character_names": preferred_character_names,
        })
    return requests[:4]


def _tokens_for_request(req: dict[str, Any]) -> tuple[list[str], list[str]]:
    raw_terms: list[str] = []
    raw_terms.extend(_coerce_str_list(req.get("tags"), limit=24))
    query = str(req.get("query") or "").strip()
    raw_terms.extend(x.strip() for x in re.split(r"[,，、;；。！？\s]+", query) if len(x.strip()) >= 2)
    terms: list[str] = []
    for term in raw_terms:
        if term and term not in terms:
            terms.append(term)
    avoid = _coerce_str_list(req.get("avoid"), limit=16)
    return terms[:32], avoid


_NON_FLIRT_BLOCK_TERMS = (
    "性暗示",
    "暧昧",
    "撩人",
    "撩拨",
    "调情",
    "挑逗",
    "色气",
    "擦边",
    "成人",
    "nsfw",
    "suggestive",
    "flirty",
    "seductive",
)


def _looks_flirty_asset_text(*parts: Any) -> bool:
    text = " ".join(
        " ".join(str(x) for x in part) if isinstance(part, (list, tuple, set)) else str(part or "")
        for part in parts
    ).lower()
    return any(term in text for term in _NON_FLIRT_BLOCK_TERMS)


def _character_name_preference_bonus(
    preferred_names: list[str],
    *,
    name: str = "",
    intro: str = "",
    detail: str = "",
    image_text: str = "",
    emotions: list[str] | None = None,
    custom_tags: list[str] | None = None,
) -> tuple[int, list[str]]:
    if not preferred_names:
        return 0, []
    bonus = 0
    matches: list[str] = []
    strong_fields = [name, *(emotions or []), *(custom_tags or [])]
    weak_text = "\n".join([intro, detail, image_text]).lower()
    for raw_term in preferred_names:
        term = str(raw_term or "").strip()
        if not term:
            continue
        lower = term.lower()
        strong_hit = any(lower in str(field or "").lower() for field in strong_fields)
        weak_hit = bool(lower and lower in weak_text)
        if strong_hit:
            bonus += 4
        elif weak_hit:
            bonus += 2
        else:
            continue
        if term not in matches:
            matches.append(term)
    return min(bonus, 8), matches[:4]


def _asset_id_from_attachment(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    return str(raw.get("asset_id") or raw.get("assetId") or "").strip()


def _recent_asset_ids_from_messages(recent_messages: list[dict[str, Any]] | None, *, limit: int = ASSET_RECENT_COOLDOWN_LIMIT) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for msg in reversed(recent_messages or []):
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "") != "assistant":
            continue
        for att in reversed(msg.get("attachments") or []):
            asset_id = _asset_id_from_attachment(att)
            if asset_id and asset_id not in seen:
                seen.add(asset_id)
                out.append(asset_id)
                if len(out) >= limit:
                    return out
    return out


async def _recent_asset_ids_from_db(
    *,
    username: str | None,
    character_id: str | None,
    limit: int = ASSET_RECENT_COOLDOWN_LIMIT,
) -> list[str]:
    if not username or not character_id:
        return []
    try:
        db = get_database()
        await db.init()
        async with aiosqlite.connect(db.db_path) as conn:
            async with conn.execute(
                """SELECT ma.asset_id
                     FROM message_attachments ma
                     JOIN messages m ON m.conversation_id = ma.conversation_id
                                    AND m.message_id = ma.message_id
                     JOIN conversations c ON c.id = ma.conversation_id
                     JOIN users u ON u.id = c.user_id
                    WHERE u.username = ?
                      AND c.character_id = ?
                      AND m.role = 'assistant'
                      AND ma.asset_id IS NOT NULL
                      AND ma.asset_id <> ''
                      AND m.deleted_at IS NULL
                      AND COALESCE(m.is_hidden, 0) = 0
                      AND COALESCE(c.is_hidden, 0) = 0
                    ORDER BY m.timestamp DESC, ma.rowid DESC
                    LIMIT ?""",
                (username, character_id, limit * 3),
            ) as cur:
                out: list[str] = []
                seen: set[str] = set()
                async for row in cur:
                    asset_id = str(row[0] or "").strip()
                    if asset_id and asset_id not in seen:
                        seen.add(asset_id)
                        out.append(asset_id)
                        if len(out) >= limit:
                            break
                return out
    except Exception as exc:
        logger.debug("[Assets] load recent asset cooldown ids failed: %s", exc)
        return []


async def _recall_platform_candidates(
    req: dict[str, Any],
    *,
    age_rating: str = "all",
    max_flirt_level: int = 0,
    cooldown_asset_ids: set[str] | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    terms, avoid_terms = _tokens_for_request(req)
    preferred_names = _coerce_str_list(req.get("preferred_character_names"), limit=8)
    db = get_database()
    await db.init()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """SELECT id, name, category, emotions, intensity, custom_tags, intro, detail, image_text, flirt_level
               FROM media_assets
               WHERE category IN ('emoji', 'sticker')
                 AND COALESCE(is_active, 1) = 1
                 AND COALESCE(review_status, 'ready') = 'ready'
                 AND COALESCE(age_rating, 'all') = ?
                 AND COALESCE(flirt_level, 0) <= ?
               LIMIT 500""",
            (age_rating, max_flirt_level),
        ) as cur:
            rows = await cur.fetchall()

    candidates: list[dict[str, Any]] = []
    requested_intensity = str(req.get("intensity") or "").strip()
    cooldown_ids = cooldown_asset_ids or set()
    for row in rows:
        asset_id = str(row["id"] or "")
        if asset_id in cooldown_ids:
            continue
        emotions = _coerce_str_list(row["emotions"])
        custom_tags = _coerce_str_list(row["custom_tags"])
        intro = str(row["intro"] or "")
        detail = str(row["detail"] or "")
        image_text = str(row["image_text"] or "")
        name = str(row["name"] or "")
        if max_flirt_level <= 0 and _looks_flirty_asset_text(name, intro, detail, image_text, custom_tags):
            continue
        searchable = "\n".join([name, intro, detail, image_text, " ".join(emotions), " ".join(custom_tags)]).lower()
        score = 0
        matched: list[str] = []
        for term in terms:
            t = term.lower()
            if not t:
                continue
            hit = False
            if term in emotions or term in custom_tags:
                score += 5
                hit = True
            if t in intro.lower() or t in name.lower():
                score += 3
                hit = True
            if t in detail.lower():
                score += 2
                hit = True
            if t in image_text.lower():
                score += 2
                hit = True
            if hit:
                matched.append(term)
        for term in avoid_terms:
            if term.lower() in searchable:
                score -= 4
        character_name_bonus, character_name_matches = _character_name_preference_bonus(
            preferred_names,
            name=name,
            intro=intro,
            detail=detail,
            image_text=image_text,
            emotions=emotions,
            custom_tags=custom_tags,
        )
        if character_name_bonus:
            score += character_name_bonus
            matched.extend(f"角色:{item}" for item in character_name_matches)
        if requested_intensity and requested_intensity == str(row["intensity"] or ""):
            score += 1
        if score <= 0 and terms:
            continue
        if score <= -3:
            continue
        candidates.append({
            "ref": f"platform:{row['id']}",
            "asset_id": asset_id,
            "source": "platform",
            "name": name,
            "category": row["category"] or "emoji",
            "emotions": emotions,
            "intensity": row["intensity"] or "moderate",
            "custom_tags": custom_tags,
            "intro": intro,
            "detail": detail,
            "image_text": image_text,
            "score": score,
            "matched": matched[:8],
            "preferred_character_name_matches": character_name_matches,
        })
    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    return candidates[:limit]


def _selector_context_text(
    *,
    request: dict[str, Any],
    candidates: list[dict[str, Any]],
    recent_messages: list[dict[str, Any]] | None,
    character_prompt_context: str,
    environment_context: str,
    recent_asset_ids: list[str] | None = None,
) -> str:
    recent_lines: list[str] = []
    for msg in recent_messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "")
        content = str(msg.get("content") or "")
        if content.strip():
            recent_lines.append(f"{role}: {content[:800]}")
    cand_lines: list[str] = []
    for idx, c in enumerate(candidates, 1):
        cand_lines.append(
            "\n".join([
                f"{idx}. ref={c['ref']}",
                f"name={c.get('name','')}",
                f"emotions={','.join(c.get('emotions') or [])}; intensity={c.get('intensity','')}; tags={','.join(c.get('custom_tags') or [])}",
                f"intro={c.get('intro','')}",
                f"detail={c.get('detail','')}",
                f"image_text={c.get('image_text','')}",
                f"preferred_character_name_matches={','.join(c.get('preferred_character_name_matches') or [])}",
                f"matched={','.join(c.get('matched') or [])}; recall_score={c.get('score', 0)}",
            ])
        )
    return (
        "【角色短设定摘要/基础字段】\n"
        + (character_prompt_context or "（无）")[:6000]
        + "\n\n【当前会话记忆/环境】\n"
        + (environment_context or "（无）")[:6000]
        + "\n\n【最近对话】\n"
        + ("\n".join(recent_lines) or "（无）")
        + "\n\n【导演表情包请求】\n"
        + json.dumps(request, ensure_ascii=False)
        + "\n\n【最近已发送表情包素材（避免重复）】\n"
        + ("、".join(recent_asset_ids or []) or "（无）")
        + "\n\n【候选表情包池】\n"
        + ("\n\n".join(cand_lines) or "（空）")
        + "\n\n请从候选池选择一个 ref，或返回 null。"
    )


def _parse_selector_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except Exception:
        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            data = json.loads(raw[i : j + 1])
        else:
            raise
    return data if isinstance(data, dict) else {}


async def _select_candidate_with_llm(
    req: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    selector_model: dict[str, Any],
    username: str | None,
    character_id: str | None,
    recent_messages: list[dict[str, Any]] | None,
    character_prompt_context: str,
    environment_context: str,
    recent_asset_ids: list[str] | None = None,
    debug_role_params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not candidates or not selector_model or not selector_model.get("api_key"):
        return candidates[0] if candidates else None
    model_name = selector_model.get("model_name") or selector_model.get("id") or ""
    reasoning_policy = resolve_software_reasoning_policy(
        "asset_selector",
        model_name=str(model_name),
        mode="normal",
        active_model=selector_model,
        endpoint=selector_model.get("endpoint", ""),
        requested_enabled=False,
        requested_effort="minimal",
    )
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": ASSET_SELECTOR_SYSTEM},
            {
                "role": "user",
                "content": _selector_context_text(
                    request=req,
                    candidates=candidates,
                    recent_messages=recent_messages,
                    character_prompt_context=character_prompt_context,
                    environment_context=environment_context,
                    recent_asset_ids=recent_asset_ids,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    apply_llm_task_payload_config(payload, "asset_selector")
    try:
        res = await call_llm_payload(
            payload,
            selector_model,
            task="classify",
            timeout=llm_task_float("asset_selector", "timeout_seconds", 45.0) or 45.0,
            reasoning_policy=reasoning_policy,
            chat_debug_request={
                "username": username,
                "character_id": character_id,
                "mode": "normal",
                "model_name": str(model_name),
                "stage": "NORMAL_STEP_2_ASSET_SELECTOR_REQUEST",
                "params": {
                    **(debug_role_params or {}),
                    "tool": "asset_selector",
                    "request_id": req.get("request_id"),
                },
            },
            record_usage="main",
            usage_meter_username=username,
            charge_membership_chat_quota=True,
        )
        data = _parse_selector_json(res.text or "")
        selected_ref = data.get("selected_ref")
        if selected_ref is None or str(selected_ref).strip().lower() in {"", "null", "none"}:
            logger.info("[Assets] selector chose none: request=%s reason=%s", req.get("request_id"), data.get("reason"))
            return None
        selected_ref = str(selected_ref).strip()
        chosen = next((c for c in candidates if c.get("ref") == selected_ref), None)
        if chosen:
            chosen = dict(chosen)
            chosen["selection_reason"] = str(data.get("reason") or "").strip()[:500]
            chosen["selection_confidence"] = data.get("confidence")
            return chosen
    except Exception as exc:
        logger.debug("[Assets] selector failed, fallback to top candidate: %s", exc)
    return candidates[0] if candidates else None


def _candidate_to_attachment(candidate: dict[str, Any], req: dict[str, Any]) -> dict[str, Any]:
    asset_id = str(candidate.get("asset_id") or "")
    return {
        "id": f"att_{asset_id}",
        "type": "sticker",
        "asset_id": asset_id,
        "url": f"/api/admin/assets/{asset_id}/file",
        "name": candidate.get("name") or "",
        "metadata": {
            "source": candidate.get("source") or "platform",
            "request_id": req.get("request_id") or "",
            "query": req.get("query") or "",
            "tags": req.get("tags") or [],
            "category": candidate.get("category") or "sticker",
            "emotions": candidate.get("emotions") or [],
            "intensity": candidate.get("intensity") or "",
            "custom_tags": candidate.get("custom_tags") or [],
            "intro": candidate.get("intro") or "",
            "detail": candidate.get("detail") or "",
            "image_text": candidate.get("image_text") or "",
            "selection_reason": candidate.get("selection_reason") or "",
            "selection_confidence": candidate.get("selection_confidence"),
            "recall_score": candidate.get("score"),
            "matched": candidate.get("matched") or [],
            "preferred_character_name_matches": candidate.get("preferred_character_name_matches") or [],
        },
    }


async def plan_assets_for_reply(
    planner_result: dict[str, Any],
    *,
    selector_model: dict[str, Any] | None = None,
    username: str | None = None,
    character_id: str | None = None,
    recent_messages: list[dict[str, Any]] | None = None,
    character_prompt_context: str = "",
    environment_context: str = "",
    age_rating: str = "all",
    debug_role_params: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    if not isinstance(planner_result, dict):
        return [{"type": "text", "intent": "reply_text"}], {}, {}
    asset_plan = coerce_asset_plan(planner_result.get("asset_plan"))
    sequence = coerce_reply_sequence(planner_result.get("reply_sequence"), asset_plan)
    requests = _asset_requests_from_sequence(sequence, asset_plan)
    preferred_character_names = _preferred_character_name_terms(
        character_prompt_context,
        character_id=character_id,
    )
    if preferred_character_names:
        for req in requests:
            existing = _coerce_str_list(req.get("preferred_character_names"), limit=8)
            merged = []
            for item in [*existing, *preferred_character_names]:
                if item not in merged:
                    merged.append(item)
            req["preferred_character_names"] = merged[:8]
    cooldown_ids = _recent_asset_ids_from_messages(recent_messages)
    db_cooldown_ids = await _recent_asset_ids_from_db(username=username, character_id=character_id)
    for asset_id in db_cooldown_ids:
        if asset_id not in cooldown_ids:
            cooldown_ids.append(asset_id)
        if len(cooldown_ids) >= ASSET_RECENT_COOLDOWN_LIMIT:
            break
    if not requests:
        return sequence, {}, {
            "asset_plan": asset_plan,
            "threshold": ASSET_SEND_INTENSITY_THRESHOLD,
            "preferred_character_names": preferred_character_names,
            "cooldown_asset_ids": list(cooldown_ids),
            "requests": [],
            "selected": [],
        }
    selected: dict[str, dict[str, Any]] = {}
    debug: dict[str, Any] = {
        "asset_plan": asset_plan,
        "threshold": ASSET_SEND_INTENSITY_THRESHOLD,
        "preferred_character_names": preferred_character_names,
        "cooldown_asset_ids": list(cooldown_ids),
        "requests": [],
        "selected": [],
    }
    for req in requests:
        request_cooldown_ids = list(cooldown_ids)
        candidates = await _recall_platform_candidates(
            req,
            age_rating=age_rating,
            max_flirt_level=0,
            cooldown_asset_ids=set(request_cooldown_ids),
            limit=30,
        )
        debug["requests"].append({
            "request_id": req.get("request_id"),
            "candidate_count": len(candidates),
            "query": req.get("query"),
            "tags": req.get("tags"),
            "preferred_character_names": req.get("preferred_character_names"),
            "cooldown_asset_ids": request_cooldown_ids,
        })
        chosen = await _select_candidate_with_llm(
            req,
            candidates,
            selector_model=selector_model or {},
            username=username,
            character_id=character_id,
            recent_messages=recent_messages,
            character_prompt_context=character_prompt_context,
            environment_context=environment_context,
            recent_asset_ids=request_cooldown_ids,
            debug_role_params=debug_role_params,
        )
        if chosen:
            rid = str(req.get("request_id") or "")
            selected[rid] = _candidate_to_attachment(chosen, req)
            chosen_asset_id = str(chosen.get("asset_id") or "")
            if chosen_asset_id:
                cooldown_ids.insert(0, chosen_asset_id)
                cooldown_ids = list(dict.fromkeys(cooldown_ids))[:ASSET_RECENT_COOLDOWN_LIMIT]
            debug["selected"].append({
                "request_id": rid,
                "ref": chosen.get("ref"),
                "name": chosen.get("name"),
                "reason": chosen.get("selection_reason") or "",
            })
    debug["cooldown_asset_ids_final"] = cooldown_ids
    return sequence, selected, debug


async def pick_assets_for_plan(
    plan: dict[str, Any],
    *,
    relationship_stage: str = "stranger",
    sender_archetype: str | None = None,
    max_flirt_level: int = 0,
    age_rating: str = "all",
) -> list[dict[str, Any]]:
    """Legacy compatibility: return random-ish top recalled assets for an asset_plan."""
    p = coerce_asset_plan(plan)
    if not p.get("enabled"):
        return []
    sequence = coerce_reply_sequence(None, p)
    requests = _asset_requests_from_sequence(sequence, p)
    out: list[dict[str, Any]] = []
    for req in requests:
        candidates = await _recall_platform_candidates(req, age_rating=age_rating, max_flirt_level=max_flirt_level, limit=1)
        if candidates:
            out.append(_candidate_to_attachment(candidates[0], req))
    return out
