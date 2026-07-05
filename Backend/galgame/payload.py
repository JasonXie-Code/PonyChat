from __future__ import annotations

import json
import re as _re_global

import httpx

from ..config import logger
from .utils import (
    _compute_char_ngram_similarity,
    _extract_galgame_json_from_raw,
    _extract_scene_response_from_raw,
)
from .hints import _build_mood_desc_lines


def _char_gender_is_male(s: str) -> bool:
    x = (s or "").strip().lower()
    return x in ("male", "m", "男", "男性", "雄", "雄性")


def _char_gender_is_female(s: str) -> bool:
    x = (s or "").strip().lower()
    return x in ("female", "f", "女", "女性", "雌", "雌性")


def _galgame_httpx_timeout(api_url: str) -> httpx.Timeout:
    """分步生成单次 HTTP 超时（云端 Chat Completions）。"""
    return httpx.Timeout(60.0)


def _strip_think_tag_blocks(text: str) -> str:
    """移除 think / thinking 标签包裹块（厂商常用 XML 片段）。

    游戏/锁分分步里仅对这类结构性包装做后端剥离：残留会严重破坏展示与 JSON 解析；
    不对正文做语义级删改，由提示词约束其它格式问题。
    """
    if not text:
        return ""
    return _re_global.sub(
        r"<(?:think|thinking)>.*?</(?:think|thinking)>", "", text, flags=_re_global.DOTALL
    ).strip()


def _inject_instruction_to_last_user(payload: dict, instruction: str) -> None:
    """用 instruction 的整段作为最后一条 user 消息的正文（覆盖原内容）。

    分步里 instruction 已含【玩家本轮行为】等，不再在上方重复拼接用户原话，避免
   「第一行只有玩家话 + 大段空行 + 【当前任务】」与下方【玩家本轮行为】重复。

    若不存在 user 消息（例如重开一局首轮、slim 后仅余 system），则新增一条 user。
    """
    key = "messages" if "messages" in payload else "input"
    msgs = payload.get(key)
    if not isinstance(msgs, list):
        msgs = []
        payload[key] = msgs
    for msg in reversed(msgs):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        # 统一为纯文本，避免在文本段后追加导致与【玩家本轮行为】双写
        msg["content"] = instruction
        return
    msgs.append({"role": "user", "content": instruction})


def _build_galgame_prompt_packet(
    *,
    reference_blocks: list[str] | None = None,
    instruction_blocks: list[str] | None = None,
    reference_title: str = "【参考资料｜只读上下文】",
    instruction_title: str = "【执行指令｜本次必须遵守】",
) -> str:
    """构建 Galgame 双区提示词，将上下文与任务分离。

    参考资料块置前并标注为只读；任务、输出格式、重试与校验要求置后。
    """
    refs = [str(x).strip() for x in (reference_blocks or []) if str(x or "").strip()]
    instrs = [str(x).strip() for x in (instruction_blocks or []) if str(x or "").strip()]

    parts: list[str] = []
    if refs:
        parts.append(
            reference_title
            + "\n以下内容只用于理解背景、状态和连续性；不要把本区标题当成输出内容，不要复述本区。"
            + "\n\n"
            + "\n\n---\n\n".join(refs)
        )
    if instrs:
        parts.append(
            instruction_title
            + "\n以下内容是当前步骤的任务、格式和校验要求；优先级高于参考资料。"
            + "\n\n"
            + "\n\n---\n\n".join(instrs)
        )
    return "\n\n====================\n\n".join(parts)


def _inject_instruction_as_final_system(payload: dict, instruction: str) -> None:
    """将指令文本作为最后一条 system 消息插入，紧挨最后一条 user 消息之前。

    结构：[system(角色卡), system(玩家背景), ..., system(任务指令), user(玩家原话)]
    规则放 system 优先级更高；user 消息保持纯净，只含玩家动作。
    """
    key = "messages" if "messages" in payload else "input"
    msgs = payload.get(key)
    if not isinstance(msgs, list):
        return
    last_user_idx = -1
    for i in range(len(msgs) - 1, -1, -1):
        if isinstance(msgs[i], dict) and msgs[i].get("role") == "user":
            last_user_idx = i
            break
    new_msg = {"role": "system", "content": instruction}
    if last_user_idx < 0:
        msgs.append(new_msg)
    else:
        msgs.insert(last_user_idx, new_msg)


def _remove_galgame_seq_chat_user_context_systems(payload: dict) -> None:
    """第3～7步分步：移除 request_context 注入的「对话背景 / 自然互动」system 段。

    与字段任务中禁止台词、禁止回复的指令相冲突，且 `instruction` 中已有【玩家信息】行。
    """
    key = "messages" if "messages" in payload else "input"
    msgs = payload.get(key)
    if not isinstance(msgs, list):
        return

    def _is_chat_user_context_system(m: object) -> bool:
        if not isinstance(m, dict) or m.get("role") != "system":
            return False
        c = m.get("content", "")
        if not isinstance(c, str):
            return False
        return "【对话背景】" in c or "请以角色身份自然互动" in c

    filtered = [m for m in msgs if not _is_chat_user_context_system(m)]
    if len(filtered) != len(msgs):
        payload[key] = filtered


# 各字段与可见历史比较，相似度超阈值即重试（third_party 文本短，略严）
_SEQ_DEDUP_THRESHOLDS: dict[str, float] = {
    "env": 0.8,
    "body_state": 0.8,
    "thoughts": 0.8,
    "response": 0.8,
    "third_party": 0.64,  # 整行与历史；third_party 另有去前缀/同轮去重，见 _check_third_party_line_dedup
}

# 第 5 步：向模型注入的「非空第三者台词」自可见历史起最多回溯条数（按 assistant 轮计）
THIRD_PARTY_INJECT_LOOKBACK = 5

_SEQ_DEDUP_MAX_RETRIES = 4  # 查重/拒绝: 加上首次共5次；查字数: 独立5次


def _extract_prev_status_snapshot(payload: dict) -> dict[str, str]:
    """从最近一条 assistant 消息的 JSON 中提取角色/玩家状态元数据快照。

    返回 dict，键为字段名（如 'character_outfit', 'mood' 等），值为对应文本。
    若无可用数据则返回空 dict。
    """
    _STATUS_KEYS = (
        "relationship_stage", "mood",
        "character_pose", "player_pose",
        "character_position", "player_position",
        "character_action", "player_action",
        "character_outfit", "player_outfit",
    )
    msgs = payload.get("messages") or payload.get("input") or []
    for m in reversed(msgs):
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        content = m.get("content", "")
        if not isinstance(content, str):
            continue
        data = _extract_galgame_json_from_raw(content)
        if not data:
            continue
        snapshot: dict[str, str] = {}
        scene = data.get("scene") or {}
        for k in _STATUS_KEYS:
            v = data.get(k, "") or scene.get(k, "")
            if v:
                snapshot[k] = str(v).strip()
        # 读取 Director 持久化决策（上轮注入的 _director_meta）
        _dmeta = data.get("_director_meta")
        if isinstance(_dmeta, dict):
            for _dk in ("response_type", "response_type_prev", "response_type_prev2", "player_action_type"):
                _dv = (_dmeta.get(_dk) or "").strip()
                if _dv:
                    snapshot[f"_director_{_dk}"] = _dv
        if snapshot:
            return snapshot
    return {}


def _build_status_reminder(snapshot: dict[str, str]) -> str:
    """将元数据快照构建为步骤 3-7 可注入的状态提醒文本块。"""
    if not snapshot:
        return ""

    _LABELS = {
        "relationship_stage": "关系阶段",
        "mood": "角色心情",
        "character_pose": "角色姿态",
        "player_pose": "玩家姿态",
        "character_position": "角色位置",
        "player_position": "玩家位置",
        "character_action": "角色动作",
        "player_action": "玩家动作",
        "character_outfit": "角色服装",
        "player_outfit": "玩家服装",
    }
    lines: list[str] = []
    for k, label in _LABELS.items():
        v = snapshot.get(k, "")
        if v:
            lines.append(f"- {label}: {v}")
    if not lines:
        return ""

    block = "【角色与玩家当前状态】（上一轮结束时的状态快照，本轮叙事必须与以下状态保持严格一致）\n"
    block += "\n".join(lines)
    block += "\n⚠️ 禁止出现与上述状态矛盾的描写。"
    outfit = snapshot.get("character_outfit", "")
    if outfit == "赤裸":
        block += "角色当前为赤裸状态，严禁描写角色穿戴任何衣物/裙子/裤子/鞋子/外套等。"
    elif outfit:
        block += f"角色当前穿着「{outfit}」，描写中的着装细节必须与此一致。"
    return block


def _extract_prev_scene_texts(payload: dict) -> list[dict[str, str]]:
    """从 payload 的 messages 中提取全部 assistant 消息的 scene 文本字段（即可见历史）。
    返回列表，按时间从近到远排列，每个元素是
    {"env", "body_state", "thoughts", "third_party", "response"}。
    third_party 对应 JSON 的 scene.third_party_dialogue。
    """
    msgs = payload.get("messages") or payload.get("input") or []
    result: list[dict[str, str]] = []
    for m in reversed(msgs):
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        content = m.get("content", "")
        if not isinstance(content, str):
            continue
        data = _extract_galgame_json_from_raw(content)
        if not data:
            resp_text = _extract_scene_response_from_raw(content)
            if resp_text:
                result.append({
                    "env": "",
                    "body_state": "",
                    "thoughts": "",
                    "third_party": "",
                    "response": resp_text,
                })
            continue
        scene = data.get("scene") or {}
        result.append({
            "env": (scene.get("env") or "").strip(),
            "body_state": (scene.get("body_state") or "").strip(),
            "thoughts": (scene.get("thoughts") or "").strip(),
            "third_party": (scene.get("third_party_dialogue") or "").strip(),
            "response": str(scene.get("response") or "").strip(),
        })
    return result


def _check_inline_dedup(field_name: str, new_text: str, prev_turns: list[dict[str, str]]) -> float:
    """检查 new_text 与历史的最高相似度，返回最高相似度值。0.0 表示无重复。"""
    threshold = _SEQ_DEDUP_THRESHOLDS.get(field_name, 0.8)
    for turn_idx, prev in enumerate(prev_turns):
        prev_text = prev.get(field_name, "")
        if not prev_text:
            continue
        if field_name == "response" and new_text == prev_text:
            return 1.0
        turn_threshold = threshold if turn_idx == 0 else min(threshold + 0.15, 0.85)
        sim = _compute_char_ngram_similarity(new_text, prev_text)
        if sim > turn_threshold:
            return sim
    return 0.0


def _split_third_party_speaker_body(line: str) -> tuple[str, str]:
    """解析「角色名：台词」格式，返回 (说话者前缀, 去前缀后正文)。无冒号时正文为整行。"""
    s = (line or "").strip()
    if not s:
        return "", ""
    m = _re_global.match(r"^([^：:]{1,32})([：:])\s*(.*)$", s, flags=_re_global.DOTALL)
    if m:
        return m.group(1).strip(), (m.group(3) or "").strip()
    return "", s


def _check_third_party_line_dedup(
    new_text: str,
    prev_turns: list[dict[str, str]],
    same_round_focal_text: str,
) -> float:
    """第三者台词专用查重。返回 0.0 表示通过；>0 表示触发的 n-gram 相似度（供日志）。

    在整行 n-gram 外增加：去「名：」前缀后正文对历史的更严比较、
    与本轮已写 env+body+thoughts 的交叉相似（只挡「复读主角/场景已说命题」，阈值偏保守以免误伤 NPC 自线）。

    不宜与对「third_party」调用的 _check_inline_dedup 叠加，只应二选一，避免重复判定。
    """
    threshold = _SEQ_DEDUP_THRESHOLDS.get("third_party", 0.64)
    # 1) 整行与历史
    for turn_idx, prev in enumerate(prev_turns):
        prev_tp = (prev.get("third_party") or "").strip()
        if not prev_tp:
            continue
        turn_th = threshold if turn_idx == 0 else min(threshold + 0.12, 0.80)
        sim = _compute_char_ngram_similarity(new_text, prev_tp)
        if sim > turn_th:
            return sim
    n_sp, n_body = _split_third_party_speaker_body(new_text)
    if not n_body or len(n_body) < 2:
        return 0.0
    # 2) 去前缀后正文 vs 历史同字段
    for turn_idx, prev in enumerate(prev_turns):
        prev_tp = (prev.get("third_party") or "").strip()
        if not prev_tp:
            continue
        p_sp, p_body = _split_third_party_speaker_body(prev_tp)
        if not p_body:
            continue
        sim_b = _compute_char_ngram_similarity(n_body, p_body)
        # 越近的轮次，对「换皮同拍」越敏感
        th_body = 0.52 if turn_idx == 0 else 0.56
        if sim_b > th_body:
            return sim_b
        # 同说话者、最近一条：略收紧，抑制连续无增量社交句（仍不挡「新话题、新自线信息」在模型侧）
        if (
            turn_idx == 0
            and n_sp
            and p_sp
            and n_sp == p_sp
            and len(n_body) >= 4
            and len(p_body) >= 4
        ):
            if sim_b > 0.48:
                return sim_b
    # 3) 与本轮主角侧已锁定文本的交叉：复读 env/thoughts/body 已展开命题时触发
    pool = (same_round_focal_text or "").strip()
    if len(pool) >= 12 and len(n_body) >= 6:
        sim_x = _compute_char_ngram_similarity(n_body, pool)
        if sim_x > 0.44:
            return sim_x
    return 0.0


_RE_CHAR_PROFILE_BLOCK = _re_global.compile(r'# \[角色设定\].*?(?=\n# )', _re_global.DOTALL)


def _strip_char_profile_from_system_msgs(payload: dict) -> None:
    """从 payload 的 system 消息中原地移除「# [角色设定]」块。
    用于第2步（环境描写）：环境描写是纯旁白客观描述，与角色人设无关，省去大量 token。
    """
    msgs = payload.get("messages") or payload.get("input") or []
    for msg in msgs:
        if not isinstance(msg, dict) or msg.get("role") != "system":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str) or "# [角色设定]" not in content:
            continue
        new_content = _RE_CHAR_PROFILE_BLOCK.sub("", content).strip()
        msg["content"] = new_content


def build_galgame_step_system_prompt(char_profile: str) -> str:
    """第2～6步文本生成用的精简 system：仅含「# [角色设定]」块。

    第1步导演（JSON）不用本内容。第5步 third_party 会去掉整条 system；
    第2步 env 首轮可对 system 剥除角色块（见本模块 `_strip_char_profile_from_system_msgs`）。
    分步规则在 seq_prompts 各步 instruction 中。
    """
    return f"""# [角色设定]
{char_profile}
"""


def _build_slim_payload_for_text_steps(base_payload: dict, full_recent_turns: int = 3) -> dict:
    """构建第2～6步的精简 payload。

    full_recent_turns=0（当前默认）：历史 assistant/user 消息对整轮物理删除，
    语义上下文完全由 char_memory 语义摘要块承担，消息数组只保留 system 消息
    和当前轮的 user 指令消息。

    full_recent_turns>0：最近 N 轮保留完整四字段（身体状态/内心独白/角色回复/元数据），
    更早的轮次保留骨架（时间/地点/关系/心情 + 角色回复），旧 user 消息合并进骨架后删除。
    """
    import copy
    slim = copy.deepcopy(base_payload)
    key = "messages" if "messages" in slim else "input"
    msgs = slim.get(key) or []
    if not isinstance(msgs, list):
        return slim

    # 收集所有 assistant 消息的下标（按出现顺序）
    assistant_indices: list[int] = [
        i for i, m in enumerate(msgs)
        if isinstance(m, dict) and m.get("role") == "assistant"
    ]
    if not assistant_indices:
        return slim

    last_assistant_idx = assistant_indices[-1]
    # 最近 full_recent_turns 轮（不含最后一条）保留完整四字段
    # assistant_indices[-1] = 最后一条（当前轮，完整保留）
    # assistant_indices[-(full_recent_turns+1):-1] = 近期轮（保留四字段）
    # 更早的 = 仅骨架
    recent_full_set: set[int] = set(assistant_indices[-(full_recent_turns + 1):-1])

    indices_to_remove: set[int] = set()

    for i, msg in enumerate(msgs):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if i == last_assistant_idx and full_recent_turns > 0:
            # full_recent_turns > 0：保留最后一条完整内容，供近期轮感知具体台词
            # full_recent_turns = 0：一视同仁处理，由 char_memory 承担语义
            continue
        data = _extract_galgame_json_from_raw(content)
        if not data:
            continue
        scene = data.get("scene") or {}
        resp_text = str(scene.get("response") or "").strip()
        time_val = str(scene.get("time") or "").strip()
        loc_val = str(scene.get("location") or "").strip()
        rel_val = str(data.get("relationship_stage") or "").strip()
        mood_val = str(data.get("mood") or "").strip()
        char_pos_val = str(data.get("character_position") or "").strip()
        play_pos_val = str(data.get("player_position") or "").strip()

        # 找到紧邻此 assistant 消息之前的 user 消息，合并进骨架后删除。
        # 例外：摘要占位消息（以"[以下是本对话之前内容的摘要"开头）不参与合并，
        # 必须保留在消息列表中，让模型可以读到完整历史摘要。
        user_text = ""
        user_idx = -1
        for j in range(i - 1, -1, -1):
            if not isinstance(msgs[j], dict):
                continue
            if msgs[j].get("role") == "user":
                uc = msgs[j].get("content", "")
                # 摘要消息保留原位，不合并进骨架
                if isinstance(uc, str) and uc.startswith("[以下是本对话之前内容的摘要"):
                    break
                user_idx = j
                if isinstance(uc, str):
                    user_text = uc
                elif isinstance(uc, list):
                    user_text = " ".join(
                        p.get("text", "") for p in uc
                        if isinstance(p, dict) and p.get("type") in ("text", "input_text")
                    )
                break
            if msgs[j].get("role") == "assistant":
                break  # 遇到更早的 assistant 就停止，不跨轮查找

        if full_recent_turns == 0:
            # full_recent_turns=0：整轮物理删除，语义由 char_memory 承担，消息数组不留任何历史占位
            indices_to_remove.add(i)
            if user_idx >= 0:
                indices_to_remove.add(user_idx)
            continue

        prefix = f"玩家: {user_text}\n" if user_text else ""
        meta = (
            f"时间: {time_val} | 地点: {loc_val} | 关系: {rel_val} | 心情: {mood_val}"
            f" | 角色位置: {char_pos_val} | 玩家位置: {play_pos_val}"
        )

        if i in recent_full_set:
            # 近期轮：保留完整四字段，让模型感知具体的身体状态/内心独白/角色回复
            body_text = str(scene.get("body_state") or "").strip()
            thoughts_text = str(scene.get("thoughts") or "").strip()
            parts = [prefix + meta]
            if body_text:
                parts.append(f"身体状态: {body_text}")
            if thoughts_text:
                parts.append(f"内心独白: {thoughts_text}")
            parts.append(f"角色回复: {resp_text}")
            msg["content"] = "\n".join(parts)
        else:
            # 较早轮：保留骨架（时间/地点/关系/心情 + 角色回复），节省 token
            msg["content"] = f"{prefix}{meta}\n角色回复: {resp_text}"

        if user_idx >= 0:
            indices_to_remove.add(user_idx)

    if indices_to_remove:
        slim[key] = [m for idx, m in enumerate(msgs) if idx not in indices_to_remove]
    return slim


def _build_minimal_payload_for_json_step(
    base_payload: dict,
    user_last_msg: str,
    character_profile_str: str = "",
) -> tuple[dict, str]:
    """构建第8步的最小 payload：角色设定（system）+ 一条 user 消息。

    user 消息仅含玩家本轮行为（清理 /no_think，与第2～6步前缀统一）。
    上一轮状态 / 玩家信息 / 当前分数 / 场景文本 / 评分规则
    均由 _SEQ_JSON_STEP_INSTRUCTION 模板在 inject 时统一提供，不在此处拼入。

    返回 (payload, prev_state_text)。
    """
    import copy
    minimal = copy.deepcopy(base_payload)
    msgs = minimal.get("messages") or minimal.get("input") or []
    if not isinstance(msgs, list):
        return minimal, ""

    system_msgs = []
    if (character_profile_str or "").strip():
        system_msgs.append({"role": "system", "content": character_profile_str.strip()})

    # 从最后一条 assistant 消息中提取上一轮关键状态
    prev_state_text = ""
    for m in reversed(msgs):
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        content = m.get("content", "")
        if not isinstance(content, str):
            continue
        prev_data = _extract_galgame_json_from_raw(content)
        if not prev_data:
            continue
        prev_scene = prev_data.get("scene") or {}
        prev_flags = prev_data.get("event_flags") or {}
        prev_mood = prev_data.get("char_mood") or {}
        prev_vitals = prev_data.get("char_vitals") or {}
        lines = [
            f"时间: {prev_scene.get('time', '')}",
            f"地点: {prev_scene.get('location', '')}",
            f"关系阶段: {prev_data.get('relationship_stage', '')}",
            f"心情: {prev_data.get('mood', '')}",
            f"角色姿态: {prev_data.get('character_pose', '')}",
            f"玩家姿态: {prev_data.get('player_pose', '')}",
            f"角色位置: {prev_data.get('character_position', '')}",
            f"玩家位置: {prev_data.get('player_position', '')}",
            f"角色种族: {prev_data.get('character_race', '')}",
            f"玩家种族: {prev_data.get('player_race', '')}",
            f"角色服装: {prev_data.get('character_outfit', '')}",
            f"玩家服装: {prev_data.get('player_outfit', '')}",
            f"上一轮分数: {(prev_data.get('score') or {}).get('current', '')}",
        ]
        # 注入全部情绪数值+描述，供第8步元数据 JSON 评分规则参考（非零才输出）
        _mood_map = [
            ("arousal",    "兴奋"),
            ("pleasure",   "愉悦"),
            ("shyness",    "害羞"),
            ("fear",       "恐惧"),
            ("anger",      "愤怒"),
            ("sadness",    "悲伤"),
            ("submission", "顺从"),
            ("despair",    "绝望"),
            ("courage",    "勇气"),
            ("curiosity",  "好奇"),
            ("nervousness", "紧张"),
        ]
        _mood_defaults = {"curiosity": 50, "courage": 50, "nervousness": 20, "shyness": 35}
        _mood_parts = [
            f"{label}={prev_mood.get(key, _mood_defaults.get(key, 0)) or 0}"
            for key, label in _mood_map
            if (prev_mood.get(key, _mood_defaults.get(key, 0)) or 0) != 0
        ]
        if _mood_parts:
            lines.append(f"角色情绪(上一轮): {' '.join(_mood_parts)}")
            _mood_descs = _build_mood_desc_lines(prev_mood, cv=prev_vitals)
            if _mood_descs:
                lines.append("角色情绪描述: " + "；".join(_mood_descs))
        if prev_flags:
            import json as _json
            lines.append(f"事件标记(上一轮): {_json.dumps(prev_flags, ensure_ascii=False)}")
        prev_state_text = "\n".join(lines)
        break

    clean_msg = user_last_msg.replace("/no_think", "").strip() if user_last_msg else ""
    user_content = f"【玩家本轮行为】：{clean_msg}\n" if clean_msg else ""

    key = "messages" if "messages" in minimal else "input"
    minimal[key] = system_msgs + [{"role": "user", "content": user_content}]
    return minimal, prev_state_text


def _set_max_tokens(p: dict, n: int) -> None:
    """根据 payload 格式设置正确的 token 上限字段（Responses API 用 max_output_tokens）。
    同时移除其他命名（max_completion_tokens / max_tokens），保证 payload 中只保留一个最大输出参数。"""
    n = 16384
    if "input" in p:
        p.pop("max_tokens", None)
        p.pop("max_completion_tokens", None)
        p["max_output_tokens"] = n
    else:
        p.pop("max_output_tokens", None)
        p.pop("max_completion_tokens", None)
        p["max_tokens"] = n


# ---------------------------------------------------------------------------
# 剧情导演辅助：构建注入块 & 体征 delta 转绝对值
# ---------------------------------------------------------------------------

_GALGAME_TEXT_STEP_ORDER = ("env", "body_state", "thoughts", "third_party", "response")
_SCENE_FIELD_TEXT = frozenset({"env", "body_state", "thoughts", "third_party", "response"})
_SCENE_FIELD_ALL = _SCENE_FIELD_TEXT | {"options"}
# 提示词告知导演「0～29 = 跳过」，但实测导演对轻量字段习惯给 30～39 的保底分。
# 将激活阈值设为 40，使 30～39 的分数在后端静默跳过，
# 实现比提示词承诺更激进的动态裁剪，无需改变导演的打分行为。
_FIELD_SCORE_ACTIVE_MIN = 40

_RT_VALID = frozenset({
    "statement",
    "silence",
    "question",
    "exclamation",
    "initiative",
    "plead",
    "deflect",
    "consent",
    "tender",
    "refuse",
})


def select_response_type(
    scores: dict | None,
    recent: list[str],
    *,
    legacy_response_type: str = "",
) -> str:
    """从 Director 输出的 response_type_scores 中选出最终类型；排除近 2 轮已用类型（fallback 不排除）。

    recent：按时间从旧到新，通常为上上轮、上轮已选类型字符串列表。
    legacy_response_type：旧版 Director 仅输出 response_type 字符串时的兼容回退。
    """
    candidates: dict[str, int] = {}
    if isinstance(scores, dict) and scores:
        for k, v in scores.items():
            kn = str(k).strip().lower()
            if kn not in _RT_VALID:
                continue
            try:
                candidates[kn] = int(float(v))
            except (TypeError, ValueError):
                continue
    if not candidates:
        leg = (legacy_response_type or "").strip().lower()
        if leg in _RT_VALID:
            return leg
        return "statement"
    exclude = set(recent[-3:]) if recent else set()
    filtered = {k: sc for k, sc in candidates.items() if k not in exclude}
    pool = filtered if filtered else candidates
    return max(pool, key=lambda x: pool[x])


def _director_field_score_int(raw: object) -> int:
    """解析导演 field_scores 单项；非法时返回 -1（视为未激活）。"""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


def _derive_active_text_steps_fallback(director: dict) -> set[str]:
    """导演未给出 field_scores / scene_fields 或解析失败时，用启发式推断本轮应跑哪些文本步。"""
    active: set[str] = {"response"}
    env_facts = (director.get("environment_facts") or "").strip()
    if director.get("decided_events") or len(env_facts) > 10:
        active.add("env")
    action_type = (director.get("player_action_parse") or {}).get("action_type") or ""
    if action_type in ("physical_intimacy", "restraint", "physical_violence", "care_provision"):
        active.add("body_state")
    inner_arc = director.get("character_inner_arc") or ""
    if len(inner_arc) > 20:
        active.add("thoughts")
    # 兼容旧版导演 JSON 的 need_third_party
    raw_ntp = director.get("need_third_party")
    if raw_ntp is True or (isinstance(raw_ntp, str) and raw_ntp.strip().lower() in ("true", "1", "yes", "需要", "是")):
        active.add("third_party")
    return active


def get_active_text_step_set(director: dict | None) -> set[str]:
    """返回本轮要调用模型生成的文本步骤名集合（不含 options；options 由第 9 步单独生成）。"""
    if not director:
        return set(_GALGAME_TEXT_STEP_ORDER)
    raw_fs = director.get("field_scores")
    if isinstance(raw_fs, dict) and raw_fs:
        out: set[str] = set()
        for k, v in raw_fs.items():
            kn = str(k).strip().lower()
            if kn in _SCENE_FIELD_TEXT and _director_field_score_int(v) >= _FIELD_SCORE_ACTIVE_MIN:
                out.add(kn)
        if out:
            return out
    raw = director.get("scene_fields")
    if isinstance(raw, list) and len(raw) > 0:
        seen: list[str] = []
        for x in raw:
            s = str(x).strip().lower()
            if s in _SCENE_FIELD_TEXT:
                if s not in seen:
                    seen.append(s)
        if not seen:
            return _derive_active_text_steps_fallback(director)
        out2 = set(seen)
        if "response" not in out2:
            out2.add("response")
        return out2
    return _derive_active_text_steps_fallback(director)


def scene_fields_for_sse_plan(director: dict | None) -> list[str]:
    """供 SSE plan 事件：按叙事流水线顺序排列的字段列表，末尾固定含 options。"""
    s = get_active_text_step_set(director)
    ordered = [x for x in _GALGAME_TEXT_STEP_ORDER if x in s]
    if "options" not in ordered:
        ordered.append("options")
    return ordered


def normalize_director_json(director: dict) -> None:
    """就地修正导演 JSON 常见不一致（模型未严格遵守 schema 时）。

    - third_party 未激活（field_scores < 30 或未在 scene_fields）时清空 third_party_hint。
    """
    if not isinstance(director, dict):
        return
    active = get_active_text_step_set(director)
    if "third_party" not in active:
        _h = (director.get("third_party_hint") or "").strip()
        if _h:
            logger.info(
                "🎬 [导演规范化] third_party 未激活，已清空 third_party_hint（原长度=%s 字）",
                len(_h),
            )
        director["third_party_hint"] = ""


def _normalize_need_third_party(director: dict | None) -> tuple[str, bool | None]:
    """
    兼容旧代码：等价于判断「本轮是否生成 third_party 文本」。
    返回 (hint, tri_state)；tri_state None 表示无法从 scene_fields 推断时交由步骤内模型自判（当前实现下不会返回 None）。
    """
    if not director:
        return ("", None)
    hint = (director.get("third_party_hint") or "").strip()
    if "third_party" in get_active_text_step_set(director):
        return (hint, True)
    return (hint, False)


def _build_director_block(
    director: dict,
    step_name: str = "",
    merged_organ_fill: dict | None = None,
    character_gender: str = "",
) -> str:
    """将导演决策 JSON 转为注入到各步骤的简短上下文块。
    step_name 用于按步骤过滤：只给该步骤需要的字段，减少干扰。
    merged_organ_fill：导演预算后的 organ_fill 绝对值（含器具四键），防后续步骤遗忘。
    """
    if not director:
        return ""
    lines = ["【本轮导演决策】"]

    _fs = director.get("field_scores")
    if isinstance(_fs, dict) and _fs:
        lines.append(f"field_scores（本轮）：{json.dumps(_fs, ensure_ascii=False)}")
    else:
        _sf = director.get("scene_fields")
        if isinstance(_sf, list) and _sf:
            lines.append(f"scene_fields（兼容，本轮生成字段）：{json.dumps(_sf, ensure_ascii=False)}")

    if step_name == "third_party":
        if "third_party" in get_active_text_step_set(director):
            _h = (director.get("third_party_hint") or "").strip()
            lines.append(
                "⚠️ **第三者发言：导演裁定需要**——必须写出一句第三方 NPC 台词（格式「NPC名：台词」），"
                "禁止输出（无）。"
                + (_h and f" 导演意图：{_h}" or " 请依据下方环境事实与剧情补全 NPC 台词。")
            )

    action_parse = director.get("player_action_parse") or {}
    if action_parse.get("note"):
        lines.append(f"行动解析：{action_parse['note']}")

    if step_name in ("", "env", "body_state", "third_party", "response"):
        if director.get("environment_facts"):
            _ef = director["environment_facts"]
            if step_name == "env":
                lines.append(
                    f"环境事实：{_ef}\n"
                    "（注意：其中可能混入角色动作/位移；本步 env **仅**写空间、光线、气味、温度、声响等客观环境，"
                    "勿把角色动作写入环境描写。）"
                )
            else:
                lines.append(f"环境事实：{_ef}")

    if step_name in ("", "thoughts", "response"):
        if director.get("character_inner_arc"):
            lines.append(f"内心走向：{director['character_inner_arc']}")

    if step_name in ("", "response", "thoughts"):
        if director.get("character_core_reaction"):
            lines.append(f"核心反应：{director['character_core_reaction']}")

    # decided_events 注入按步骤分流，避免与各步硬性禁令冲突：
    # - body_state：强制体现（主要承接物理事件）
    # - env：仅允许提取客观环境后果，不得写动作
    # - thoughts：仅作情绪触发背景，不得写动作/台词
    # - response：若 body_state 已生成则仅作背景参考，避免重复重述
    decided = director.get("decided_events")
    if isinstance(decided, list) and decided:
        events_str = "、".join(f"「{e}」" for e in decided if str(e).strip())
        if events_str:
            _body_state_active = "body_state" in get_active_text_step_set(director)
            if step_name == "body_state":
                lines.append(
                    f"⚠️ 本轮已决定发生的物理事件（必须体现，禁止删减，禁止添加未列出的进食/饮水/受伤等事件）：{events_str}"
                )
            elif step_name == "env":
                lines.append(
                    f"（本轮物理事件参考：{events_str}。env 只能提取其中可观测的客观环境变化，如声响/气味/温度/空间状态；禁止写角色动作与台词。）"
                )
            elif step_name == "thoughts":
                lines.append(
                    f"（本轮物理事件背景：{events_str}。thoughts 仅可把它们作为情绪触发来源，禁止复述动作过程，禁止写对外台词。）"
                )
            elif step_name == "response" and _body_state_active:
                lines.append(
                    f"（以下物理事件已由身体描写完成，response 无需重述，仅作背景参考：{events_str}）"
                )
            else:
                lines.append(
                    f"⚠️ 本轮已决定发生的物理事件（必须体现，禁止删减，禁止添加未列出的进食/饮水/受伤等事件）：{events_str}"
                )

    # response_type：由后端从 response_type_scores 选出 _selected_response_type；兼容旧版 response_type 字符串
    if step_name == "response":
        _resp_type = (
            (director.get("_selected_response_type") or director.get("response_type") or "statement")
        ).strip().lower()
        _type_map = {
            "statement":   "陈述收束——末句以**句号或省略号**收尾，语气平稳内敛；**禁止感叹号收尾**、**禁止呼喊爆发式表达**；**禁止**征询许可（「好不好」「可以吗」「你愿意吗」）——征询须用 **consent**",
            "silence":     "沉默/极简——台词**不得超过10字**，只允许语气词、呢喃或单字短语；以动作/神态为主体；**禁止完整句子台词**、**禁止任何感叹爆发**",
            "question":    "真实疑问——末句**必须以「？」收尾**，是角色真正想了解的**信息性问题**；**禁止**写成征求许可（那是 **consent**）；**禁止**陈述句/感叹句/行动宣告收束",
            "exclamation": "情绪感叹——末句**必须以「！」收尾**，体现突然强烈的**非拒绝向**情绪爆发（惊喜/震惊/感动/狂喜等）；**禁止以句号或省略号平静收尾**；**强烈抗议、拒绝、要求停止归 refuse**，勿用本类型",
            "initiative":  "角色主动——收束为角色自发的**行动宣告或邀请**（「我来……」「跟我走」「我们去……」等主动句式）；**禁止征询许可**；**禁止感叹爆发收尾**；**禁止问号收尾**",
            "plead":       "哀求/恳求——以**恳求、哭诉或无意识呻吟**收束，语气柔弱无力，角色处于弱势；**禁止坚定主动或感叹爆发语气**；诉求须有明确对象",
            "deflect":     "玩笑/偏转——以**调皮、自嘲或刻意转移话题**收束，主动回避正面回应；**禁止认真表态或情感宣泄**；语气轻快或带抗拒质感",
            "consent":     "征询许可——末句须为**征求玩家同意或许可**的问句（「可以吗？」「好不好？」「你愿意……吗？」「让我……好吗？」等）；**禁止**写成纯信息追问（那是 **question**）；**禁止**陈述句收束",
            "tender":      "温柔倾诉——末句以**句号或省略号**收尾，语气柔软、亲密、沉溺，以信任与感受为主；**禁止感叹号收尾**、**禁止征询许可**、**禁止信息性追问**；**非**情绪爆发（爆发→exclamation）",
            "refuse":      "抗拒拒绝——末句表达明确**拒绝、反对、划界或要求停止**；可用**句号**（冷淡坚决）或**感叹号**（强烈抗议）；**语义须为否定立场**；**禁止**恳求弱势语气（plead）、**禁止**惊喜式欢呼（exclamation）、**禁止**征询许可（consent）",
        }
        _type_label = _type_map.get(_resp_type, _type_map["statement"])
        lines.append(f"⚠️ **导演指定发言模式（必须遵守）**：{_type_label}")

    if merged_organ_fill and isinstance(merged_organ_fill, dict):
        _plug_keys = ["urethral_plug", "anal_plug", "mouth_plug"]
        if _char_gender_is_female(character_gender):
            _plug_keys.append("vaginal_plug")
        _parts: list[str] = []
        for _pk in _plug_keys:
            if _pk not in merged_organ_fill:
                continue
            try:
                _pv = int(merged_organ_fill.get(_pk, 0) or 0)
            except (TypeError, ValueError):
                continue
            if _pv <= 0:
                continue
            _lab = {"urethral_plug": "尿道塞", "anal_plug": "肛塞", "mouth_plug": "口塞", "vaginal_plug": "阴道塞"}.get(_pk, _pk)
            _parts.append(f"{_lab}={_pv}")
        if _parts:
            lines.append(
                "⚠️ **体内器具（本轮预算后仍佩戴）**："
                + "，".join(_parts)
                + "——叙事须体现限制（口塞限说话/进食；尿道塞限排尿；肛塞限排便/肛行为；阴道塞限阴道插入等），禁止无故遗忘。"
            )

    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


def _repair_drinking_bladder_consistency(director: dict) -> None:
    """经口饮水：导演已因饮水降低 thirst，但未给出 bladder 正向 delta 时补全。

    不经口膀胱灌注（仅 bladder+、无 thirst−）不经过本函数。仅依据 vital_events + decided_events。
    """
    if not isinstance(director, dict):
        return
    ve = director.get("vital_events")
    if not isinstance(ve, dict):
        return
    cv = ve.get("char_vitals")
    if not isinstance(cv, dict):
        return
    try:
        thirst_d = int(cv.get("thirst", 0))
    except (TypeError, ValueError):
        return
    if thirst_d >= 0:
        return
    decided = director.get("decided_events")
    if not isinstance(decided, list):
        return
    blob = " ".join(str(x) for x in decided)
    drink_markers = ("喝", "饮", "咽", "抿", "润", "啜", "吞", "灌")
    if not any(m in blob for m in drink_markers):
        return
    of = ve.get("organ_fill")
    if not isinstance(of, dict):
        of = {}
        ve["organ_fill"] = of
    bd_raw = of.get("bladder")
    if bd_raw is not None:
        try:
            if int(bd_raw) > 0:
                return
        except (TypeError, ValueError):
            pass
    # thirst 负向幅度与膀胱增量大致对应：一口约 -20 → +3~+5
    add = max(2, min(12, (abs(thirst_d) * 2 + 9) // 10))
    of["bladder"] = add
    vr = director.get("vital_reasons")
    if not isinstance(vr, dict):
        vr = {}
        director["vital_reasons"] = vr
    vr.setdefault("bladder", "饮水入体")


def _apply_director_vitals(
    director: dict,
    current_cv: dict,
    current_cm: dict,
    current_of: dict,
    character_gender: str = "",
) -> dict | None:
    """将导演决策中的 vital_events delta 应用到当前体征，
    返回包含 char_vitals/char_mood/organ_fill 三个绝对值对象的 dict；
    若导演未提供 vital_events 则返回 None。
    """
    vital_events = director.get("vital_events")
    if not isinstance(vital_events, dict):
        return None

    from .constants import (
        _DEFAULT_CHAR_VITALS as _DCV,
        _DEFAULT_CHAR_MOOD as _DCM,
        _DEFAULT_ORGAN_FILL as _DOF,
    )

    cv = dict(current_cv)
    cm = dict(current_cm)
    of = dict(current_of)

    cv_delta = vital_events.get("char_vitals") or {}
    cm_delta = vital_events.get("char_mood") or {}
    of_delta: dict = dict(vital_events.get("organ_fill") or {})
    if _char_gender_is_male(character_gender):
        of_delta.pop("vaginal_plug", None)
        of_delta.pop("womb", None)
    elif _char_gender_is_female(character_gender):
        of_delta.pop("testicles", None)
    else:
        # 性别未判明：与 UI 一致不生效阴道塞 delta（仅雌性可改 vaginal_plug）
        of_delta.pop("vaginal_plug", None)

    if isinstance(cv_delta, dict):
        for k, v in cv_delta.items():
            if k in _DCV:
                try:
                    cv[k] = max(0, min(100, cv.get(k, _DCV[k]) + int(v)))
                except (TypeError, ValueError):
                    pass

    if isinstance(cm_delta, dict):
        for k, v in cm_delta.items():
            if k in _DCM:
                try:
                    cm[k] = max(0, min(100, cm.get(k, _DCM[k]) + int(v)))
                except (TypeError, ValueError):
                    pass

    if isinstance(of_delta, dict):
        for k, v in of_delta.items():
            if k in _DOF:
                try:
                    of[k] = max(0, min(100, of.get(k, _DOF[k]) + int(v)))
                except (TypeError, ValueError):
                    pass

    if _char_gender_is_male(character_gender):
        of["vaginal_plug"] = 0
        of["womb"] = 0
    elif _char_gender_is_female(character_gender):
        of["testicles"] = 0
    else:
        of["vaginal_plug"] = 0

    return {"char_vitals": cv, "char_mood": cm, "organ_fill": of}


def _strip_no_think_from_payload(payload: dict) -> None:
    """移除 payload 中所有 user 消息末尾的 /no_think，让模型在重试时可以使用思考链来理解去重指令。"""
    msgs = payload.get("messages") or payload.get("input")
    if not isinstance(msgs, list):
        return
    for msg in msgs:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str) and "/no_think" in content:
            msg["content"] = content.replace(" /no_think", "").replace("/no_think", "")
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    txt = part.get("text", "")
                    if "/no_think" in txt:
                        part["text"] = txt.replace(" /no_think", "").replace("/no_think", "")
