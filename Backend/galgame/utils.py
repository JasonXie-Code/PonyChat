"""
utils.py
Galgame 通用工具：消息ID生成、JSON修复、文本提取、场景字段清洗。
"""

from __future__ import annotations

import copy
import json
import re
import time
import uuid

from json_repair import repair_json

from ..config import logger


# ---------------------------------------------------------------------------
# 消息 ID 生成
# ---------------------------------------------------------------------------

def generate_message_id() -> str:
    timestamp = int(time.time() * 1000)
    random_part = uuid.uuid4().hex[:8]
    return f"msg_{timestamp}_{random_part}"


# ---------------------------------------------------------------------------
# JSON 修复工具
# ---------------------------------------------------------------------------

def try_fix_json(s: str) -> str:
    """JSON 修复器：处理截断、非法控制字符和悬挂逗号"""
    s = s.strip()
    s = re.sub(r'```json\s*|\s*```', '', s)
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)
    s = re.sub(r':\s*\+([\d.]+)', r': \1', s)

    try:
        repaired = repair_json(s, skip_json_loads=True, ensure_ascii=False)
        if isinstance(repaired, str) and repaired.strip():
            s = repaired.strip()
        elif repaired is not None:
            s = json.dumps(repaired, ensure_ascii=False)
    except Exception as repair_err:
        logger.debug("json_repair 修复失败，使用本地兜底逻辑: %s", repair_err)

    brackets = {'{': '}', '[': ']'}
    stack = []
    for char in s:
        if char in brackets:
            stack.append(brackets[char])
        elif char in brackets.values():
            if stack and stack[-1] == char:
                stack.pop()
    s += ''.join(reversed(stack))

    s = re.sub(r',\s*([\]}])', r'\1', s)
    return s


# ---------------------------------------------------------------------------
# 场景文本提取辅助
# ---------------------------------------------------------------------------

def _compute_char_ngram_similarity(a: str, b: str, n: int = 3) -> float:
    """计算两段中文文本的字符 n-gram Jaccard 相似度，返回 [0, 1]。
    n=3（三元组）对中文散文有效：完全一致返回 1.0，完全不同接近 0.0。
    """
    if not a or not b or len(a) < n or len(b) < n:
        return 0.0
    a_ng = set(a[i:i + n] for i in range(len(a) - n + 1))
    b_ng = set(b[i:i + n] for i in range(len(b) - n + 1))
    union = len(a_ng | b_ng)
    return len(a_ng & b_ng) / union if union > 0 else 0.0


def _extract_scene_env_thoughts_from_raw(raw_content: str) -> str:
    """从 Galgame 助理消息的 rawContent 中解析出 scene.env + scene.thoughts，用于禁止重复与重试检测。"""
    if not raw_content or not raw_content.strip():
        return ""
    clean = re.sub(r'<(?:think|thinking)>.*?</(?:think|thinking)>', '', raw_content, flags=re.DOTALL).strip()
    json_match = re.search(r'\{(?:.*)\}', clean, re.DOTALL)
    json_str = json_match.group(0) if json_match else ""
    if not json_str:
        return ""
    try:
        fixed = try_fix_json(json_str)
        data = json.loads(fixed, strict=False)
        scene = data.get("scene") or {}
        env = (scene.get("env") or "").strip()
        thoughts = (scene.get("thoughts") or "").strip()
        return (env + "\n" + thoughts).strip()
    except Exception:
        return ""


def _extract_scene_response_from_raw(raw_content: str) -> str:
    """从 Galgame 助理消息的 rawContent 中解析 scene.response，用于重复检测。"""
    if not raw_content or not raw_content.strip():
        return ""
    clean = re.sub(r'<(?:think|thinking)>.*?</(?:think|thinking)>', '', raw_content, flags=re.DOTALL).strip()
    json_match = re.search(r'\{(?:.*)\}', clean, re.DOTALL)
    json_str = json_match.group(0) if json_match else ""
    if not json_str:
        return ""
    try:
        fixed = try_fix_json(json_str)
        data = json.loads(fixed, strict=False)
        scene = data.get("scene") or {}
        return str(scene.get("response") or "").strip()
    except Exception:
        return ""


def _extract_galgame_json_from_raw(raw_content: str) -> dict:
    """从 rawContent 中提取 Galgame JSON 对象，失败返回空 dict。"""
    if not raw_content or not str(raw_content).strip():
        return {}
    clean = re.sub(r'<(?:think|thinking)>.*?</(?:think|thinking)>', '', str(raw_content), flags=re.DOTALL).strip()
    json_match = re.search(r'\{(?:.*)\}', clean, re.DOTALL)
    json_str = json_match.group(0) if json_match else ""
    if not json_str:
        return {}
    try:
        fixed = try_fix_json(json_str)
        obj = json.loads(fixed, strict=False)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


_RE_MD_BOLD = re.compile(r'\*\*(.+?)\*\*')
_RE_MD_ITALIC = re.compile(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)')
_BRACKET_CONTENT_PATTERNS = (
    re.compile(r"\([^()]*\)"),
    re.compile(r"（[^（）]*）"),
    re.compile(r"\[[^\[\]]*\]"),
    re.compile(r"【[^【】]*】"),
    re.compile(r"<[^<>]*>"),
    re.compile(r"《[^《》]*》"),
)
_RE_LOOSE_BRACKETS = re.compile(r"[()\[\]{}<>（）【】《》]")


def _strip_any_bracket_content(text: str) -> str:
    """移除任意常见括号及其中内容（支持多轮剥离嵌套）。"""
    if not text:
        return text
    cleaned = text
    # 迭代剥离，处理浅层嵌套括号（如「（a（b）c）」）
    for _ in range(8):
        changed = False
        for pattern in _BRACKET_CONTENT_PATTERNS:
            next_text = pattern.sub("", cleaned)
            if next_text != cleaned:
                cleaned = next_text
                changed = True
        if not changed:
            break
    # 清除可能残留的孤立括号
    cleaned = _RE_LOOSE_BRACKETS.sub("", cleaned)
    # 清理多余空白与异常标点间距
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"[，、。！？；：]{2,}", lambda m: m.group(0)[0], cleaned)
    return cleaned.strip()


def _format_response_dialogue(text: str) -> str:
    """恢复统一台词格式：清除模型星号，仅给双引号内的台词加粗。

    重复处理不会累积 Markdown；兼容模型偶尔输出的英文双引号。
    """
    text = text.replace('*', '')
    text = re.sub(r'"([^"\n]*)"', lambda m: '“' + m.group(1) + '”', text)
    return re.sub(r'“([^“”]+)”', lambda m: '“**' + m.group(1) + '**”', text)


def _sanitize_scene_fields(scene: dict) -> None:
    """后处理清洗所有 scene 文本字段：
    - env/body_state/thoughts：移除 Markdown 格式（**加粗**、*斜体*）+ 移除任意括号及括号内容 + 合并换行为单段
    - response：合并换行，清除模型星号后统一给双引号内的台词加粗。

    在持久化及推送前统一处理，使即时回复、历史消息和 HTML 的台词格式一致。
    """
    for field in ("env", "body_state", "thoughts", "response"):
        text = scene.get(field)
        if not isinstance(text, str) or not text:
            continue
        original = text
        if field != "response":
            text = _RE_MD_BOLD.sub(r'\1', text)
            text = _RE_MD_ITALIC.sub(r'\1', text)
            text = _strip_any_bracket_content(text)
        text = re.sub(r'\s*\n\s*', '', text).strip()
        if field == "response":
            text = _format_response_dialogue(text)
        if text != original:
            scene[field] = text
            logger.debug("🔧 [场景清洗] %s 已清洗（Markdown/括号/换行）", field)


def _normalize_non_tag_payload(game_data: dict) -> dict:
    """
    用于"除标签外整体重复"检测的规范化对象。
    允许重复的标签：scene.time, scene.location, relationship_stage, mood, character_pose, player_pose,
    character_position, player_position
    """
    if not isinstance(game_data, dict):
        return {}
    data = copy.deepcopy(game_data)
    data.pop("relationship_stage", None)
    data.pop("mood", None)
    data.pop("character_pose", None)
    data.pop("player_pose", None)
    data.pop("character_position", None)
    data.pop("player_position", None)
    scene = data.get("scene")
    if isinstance(scene, dict):
        scene.pop("time", None)
        scene.pop("location", None)
    return data


def _preview_text(text: str, limit: int = 180) -> str:
    """日志预览：压缩空白并截断，避免超长原文污染日志。"""
    try:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        return normalized[:limit]
    except Exception:
        return ""


def _extract_json_object_text(raw_content: str, max_chars: int = 2200) -> str:
    """从 raw 内容中提取 JSON 对象文本，失败时返回空字符串。"""
    if not raw_content:
        return ""
    try:
        clean = re.sub(r'<(?:think|thinking)>.*?</(?:think|thinking)>', '', str(raw_content), flags=re.DOTALL).strip()
        json_match = re.search(r'\{(?:.*)\}', clean, re.DOTALL)
        if not json_match:
            return ""
        json_str = try_fix_json(json_match.group(0))
        obj = json.loads(json_str, strict=False)
        normalized = json.dumps(obj, ensure_ascii=False)
        return normalized[:max_chars]
    except Exception:
        return ""
