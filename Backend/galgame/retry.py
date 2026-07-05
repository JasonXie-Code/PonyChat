"""
retry.py
Galgame 重试指令构造器：去重提示、字段补全提示、Payload 注入。
"""

from __future__ import annotations

import copy
import json
from typing import Any

from .constants import EVENT_FLAG_KEYS, LOCK_EVENT_FLAG_KEYS


def _build_anti_duplicate_instruction(
    retry_code: str,
    previous_json_hint: str = "",
    strict_lock: bool = False,
) -> str:
    """构造去重重试提示：避免与上一条回复的关键场景文本完全一致。"""
    reason_text = {
        "duplicate_response": "上一版与上一条消息的 scene.response 完全一致",
        "duplicate_non_tag_payload": "上一版除八个标签（time/location/relationship_stage/mood/character_pose/player_pose/character_position/player_position）外与上一条消息完全一致",
        "duplicate_env": "上一版的 scene.env 与上一条消息的 scene.env 相似度过高（疑似照抄）",
        "duplicate_body_state": "上一版的 scene.body_state 与上一条消息相同或相似度过高（疑似照抄）",
        "duplicate_thoughts": "上一版的 scene.thoughts 与上一条消息的 scene.thoughts 相似度过高（疑似照抄）",
        "duplicate_options": "上一版的 suggested_options 与历史消息的选项完全一致",
    }.get(retry_code, "上一版与上一条消息关键文本重复")
    base = (
        f"【重试去重修复】{reason_text}，本次判定失败。\n"
        "请保留同一场景的事实连续性（地点、时间、事件因果可延续），但必须改写重复字段。\n"
        "禁止复用相同句式、比喻、节奏与关键短语；读者应能明显看出是新一轮推进。\n"
    )
    if retry_code == "duplicate_response":
        base += (
            "至少重写 scene.response，保证核心台词与动作表达都不同；"
            "必要时可小幅联动改写 scene.thoughts 以保持一致。\n"
        )
        if previous_json_hint:
            try:
                prev_obj = json.loads(previous_json_hint)
                prev_resp = str(prev_obj.get("scene", {}).get("response") or "").strip()
                if prev_resp:
                    base += (
                        f"【禁止照抄以下台词】上一版 scene.response 为：\n「{prev_resp}」\n"
                        "本次必须完全避开其中的句式、动作描写和关键短语，重新创作。\n"
                    )
            except Exception:
                pass
    elif retry_code == "duplicate_non_tag_payload":
        base += (
            "除 scene.time、scene.location、relationship_stage、mood、character_pose、player_pose、"
            "character_position、player_position 外，"
            "其余字段至少有一个实质变化（如 env/thoughts/response/body_state/score_delta_reason/suggested_options 等）。\n"
        )
    elif retry_code == "duplicate_env":
        base += (
            "【env 重写强制要求】scene.env 必须从零重新构建，禁止复用上一条 env 的任何意象、比喻或句式。\n"
            "具体方法：换一个主导感官（如上一条写视觉光线 → 本条改写嗅觉/触觉/声响），"
            "或聚焦完全不同的空间细节（如上一条写水面/墙面 → 本条改写角色皮肤触感/空气温度/远处声音）。\n"
            "写完后自检：如果把本条 env 和上一条 env 对比，读者应该无法找到相同的句子结构或词组。\n"
        )
    elif retry_code == "duplicate_body_state":
        base += (
            "【body_state 重写强制要求】scene.body_state 必须反映当前时刻角色身体状态的新变化，"
            "禁止复用上一条的任何描述句式或身体细节。\n"
            "具体方法：聚焦新发生的生理反应（如心跳加速/皮肤温度变化/肌肉紧张或放松/呼吸节律），"
            "或描写与上一条完全不同的身体部位或感官体验。\n"
        )
        if previous_json_hint:
            try:
                prev_obj = json.loads(previous_json_hint)
                prev_body = str(prev_obj.get("scene", {}).get("body_state") or "").strip()
                if prev_body:
                    base += (
                        f"【禁止照抄以下身体描写】上一版 scene.body_state 为：\n「{prev_body}」\n"
                        "本次必须完全避开其中的描述角度和关键词组。\n"
                    )
            except Exception:
                pass
    elif retry_code == "duplicate_thoughts":
        base += (
            "【thoughts 重写强制要求】scene.thoughts 必须体现角色在本回合的新心理活动，"
            "禁止复用上一条的情绪走向、内心独白句式或思维结构。\n"
            "具体方法：呈现角色因当前事件产生的新困惑、新期待或新决定，"
            "而非重复上一条已表达过的心情。\n"
        )
        if previous_json_hint:
            try:
                prev_obj = json.loads(previous_json_hint)
                prev_thoughts = str(prev_obj.get("scene", {}).get("thoughts") or "").strip()
                if prev_thoughts:
                    base += (
                        f"【禁止照抄以下心理描写】上一版 scene.thoughts 为：\n「{prev_thoughts}」\n"
                        "本次必须采用完全不同的情绪角度和句式。\n"
                    )
            except Exception:
                pass
    elif retry_code == "duplicate_options":
        base += (
            "【选项重写强制要求】suggested_options 的所有 label 都与历史消息相同，"
            "必须基于当前场景的新发展生成完全不同的选项文案。\n"
            "具体方法：根据本轮角色的新情绪和新动作，设计新的互动方向。\n"
        )
    else:
        base += "至少重写 scene.env 与 scene.thoughts，必要时联动调整 scene.response。\n"
    if strict_lock and previous_json_hint:
        field_name_map = {
            "duplicate_response": "scene.response",
            "duplicate_non_tag_payload": "scene.response",
            "duplicate_env": "scene.env",
            "duplicate_body_state": "scene.body_state",
            "duplicate_thoughts": "scene.thoughts",
            "duplicate_options": "suggested_options",
        }
        target_field = field_name_map.get(retry_code, "")
        if target_field:
            return (
                f"【单字段手术模式】你只需要修改 {target_field} 这一个字段。\n"
                f"下面是你上一次的完整 JSON 输出，除了 {target_field} 之外全部照抄，"
                f"只把 {target_field} 的内容完全重写（禁止与上一条消息的同名字段雷同）。\n\n"
                f"上一次的完整输出：\n{previous_json_hint}\n\n"
                f"请输出完整 JSON，仅 {target_field} 不同。不要输出额外说明。"
            )
        lock_part = (
            "【严格修复模式】除必要去重字段外，尽量保持以下字段不变："
            "score.current、score.change、score.status、scene.time、scene.location、suggested_options。\n"
        )
        lock_part += f"上一版 JSON（仅供字段锁定参考）：\n{previous_json_hint}\n"
        return base + lock_part + "只输出合法 JSON，不要输出额外说明。"
    elif strict_lock:
        lock_part = (
            "【严格修复模式】除必要去重字段外，尽量保持以下字段不变："
            "score.current、score.change、score.status、scene.time、scene.location、suggested_options。\n"
        )
        return base + lock_part + "只输出合法 JSON，不要输出额外说明。"
    return base + "其余字段按原逻辑正常输出。只输出合法 JSON，不要输出额外说明。"


def _build_schema_instruction(
    strict_lock: bool = False,
    previous_json_hint: str = "",
    schema_error: str = "",
) -> str:
    base = (
        "【重试字段补全修复】上一版输出字段不完整或字段值为空，判定失败。\n"
        "必须输出完整且可解析的 JSON，且所有字段都要存在。\n"
        "必填顶层字段：score, scene, relationship_stage, mood, character_pose, player_pose, character_position, player_position, "
        "character_gender, player_gender, character_race, player_race, character_outfit, player_outfit, "
        "memory_tags, event_flags, score_delta_reason, suggested_options。\n"
        "score 必填：current, change, status。\n"
        "scene 必填：time, location, env, thoughts, body_state, third_party_dialogue, response。\n"
        f"event_flags 基础必填：{', '.join(EVENT_FLAG_KEYS)}。\n"
        f"若为锁分模式（galgame_lock），event_flags 还需额外包含：{', '.join(LOCK_EVENT_FLAG_KEYS)}。\n"
        "suggested_options 必须为数组，首元素为 _options_perspective 视角提醒（无需 label/type/tone），之后每项都要有：label, type, tone。\n"
        "third_party_dialogue 可以为空字符串，但字段必须存在；其余必填文本字段不能为空。\n"
        "禁止省略字段、禁止改名、禁止额外解释文字、禁止 Markdown 包裹。\n"
    )
    if schema_error:
        base += f"上一次失败原因（必须优先修复）：{schema_error}\n"
    if strict_lock:
        lock_part = "【严格修复模式】优先补齐缺失字段，尽量保持剧情连续和分数逻辑稳定，不要重写整包剧情。\n"
        if previous_json_hint:
            lock_part += f"上一版 JSON（仅供字段锁定参考）：\n{previous_json_hint}\n"
        return base + lock_part + "只输出合法 JSON，不要输出额外说明。"
    return base + "请按字段清单逐项自检后再输出。只输出合法 JSON，不要输出额外说明。"


def _build_retry_payload_with_instruction(base_payload: dict, instruction: str) -> dict:
    """
    复制 payload 并将"扩写修复提示"注入到最后一条 user 消息。
    同时兼容 chat/completions(messages) 与 responses(input) 两种格式。
    """
    if not instruction:
        return base_payload

    payload = copy.deepcopy(base_payload)

    def _append_to_content_item(content: Any) -> tuple:
        if isinstance(content, str):
            merged = f"{content}\n\n{instruction}" if content.strip() else instruction
            return merged, True
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = (item.get("type") or "").lower()
                if item_type in ("text", "input_text"):
                    text_val = item.get("text", "")
                    item["text"] = f"{text_val}\n\n{instruction}" if str(text_val).strip() else instruction
                    return content, True
            content.append({"type": "input_text", "text": instruction})
            return content, True
        return content, False

    def _inject_into_messages(message_list: Any) -> bool:
        if not isinstance(message_list, list):
            return False
        for msg in reversed(message_list):
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "user":
                continue
            new_content, ok = _append_to_content_item(msg.get("content"))
            if ok:
                msg["content"] = new_content
                return True
        message_list.append({"role": "user", "content": instruction})
        return True

    if _inject_into_messages(payload.get("messages")):
        return payload
    if _inject_into_messages(payload.get("input")):
        return payload
    return payload
