from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


_FIELD_ORDER = ("env", "body_state", "thoughts", "third_party", "response")

_BODY_PARTS = (
    "翅根", "翅膀", "翅尖", "羽翼",
    "耳尖", "耳朵", "耳根",
    "尾巴", "尾尖", "尾端",
    "眼睛", "眼眶", "眼神", "视线", "目光", "睫毛",
    "脸颊", "脸", "面颊", "嘴角", "嘴唇", "唇", "喉咙",
    "肩膀", "肩头", "后背", "脊背", "胸口", "腹部",
    "手指", "指尖", "手", "拳头", "手腕",
    "前蹄", "后蹄", "蹄子", "爪子",
    "衣角", "袖口", "裙摆", "被角", "枕头",
)

_ACTION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("抖", ("抖", "抖动", "发抖", "颤", "颤抖", "轻颤", "猛颤", "震颤", "哆嗦", "发颤")),
    ("红", ("红", "泛红", "发红", "通红", "涨红", "红透", "发烫", "烧起来")),
    ("垂", ("垂", "垂下", "垂落", "耷拉", "无力地垂")),
    ("扫", ("扫", "扫动", "摇", "摇晃", "晃动", "甩", "摆动")),
    ("躲", ("躲", "躲开", "避开", "错开", "移开", "垂下", "压低")),
    ("攥", ("攥", "攥紧", "握", "握紧", "抓", "抓紧", "揪", "捏")),
    ("埋", ("埋", "埋进", "藏", "缩进", "缩回", "遮住")),
    ("咬", ("咬", "咬住", "咬紧", "抿", "抿紧")),
    ("哽", ("哽", "哽咽", "发紧", "吞咽", "堵住", "卡住")),
)

_ACTION_ALIASES: dict[str, str] = {
    alias: group for group, aliases in _ACTION_GROUPS for alias in aliases
}

_BODY_RE = "|".join(sorted((re.escape(x) for x in _BODY_PARTS), key=len, reverse=True))
_ACTION_RE = "|".join(sorted((re.escape(x) for x in _ACTION_ALIASES), key=len, reverse=True))
_BODY_ACTION_RE = re.compile(
    rf"(?P<body>{_BODY_RE})[^，。！？；、\n]{{0,8}}(?P<action>{_ACTION_RE})"
)
_ACTION_BODY_RE = re.compile(
    rf"(?P<action>{_ACTION_RE})[^，。！？；、\n]{{0,4}}(?P<body>{_BODY_RE})"
)

_QUOTE_RE = re.compile(r"[“\"「](.*?)[”\"」]")
_PUNCT_RE = re.compile(r"[，。！？、；：…—\s（）()【】\[\]《》<>]+")


def _normalize_action(action: str) -> str:
    return _ACTION_ALIASES.get(action, action)


def _iter_texts_from_turn(turn: dict[str, str]) -> Iterable[str]:
    for field in _FIELD_ORDER:
        value = (turn.get(field) or "").strip()
        if value:
            yield value


def extract_repetition_signatures(text: str) -> set[str]:
    """从中文角色扮演文本中提取通用表达指纹。

    指纹刻意只描述表层模式，而非角色语义，因此可跨角色复用：
    例如「手指+攥」与「翅根+抖」均视为同类可重复的微动作。
    """
    text = (text or "").strip()
    if not text:
        return set()

    out: set[str] = set()
    for match in _BODY_ACTION_RE.finditer(text):
        body = match.group("body")
        action = _normalize_action(match.group("action"))
        out.add(f"动作:{body}+{action}")
    for match in _ACTION_BODY_RE.finditer(text):
        body = match.group("body")
        action = _normalize_action(match.group("action"))
        out.add(f"动作:{body}+{action}")

    for quote in _QUOTE_RE.findall(text):
        q = quote.strip()
        if len(q) >= 2:
            opener = q[:4]
            closer = q[-4:]
            out.add(f"台词开头:{opener}")
            if closer != opener:
                out.add(f"台词收尾:{closer}")

    # 紧凑意象经改写仍易残留并引发循环：提取中等长度片段，如「胸口那块石头」或「窗帘缝隙」。
    for chunk in _PUNCT_RE.split(text):
        chunk = chunk.strip("*_`'\"")
        if 5 <= len(chunk) <= 12 and not _BODY_ACTION_RE.search(chunk):
            out.add(f"短语:{chunk}")
    return out


def collect_recent_signature_counts(prev_turns: list[dict[str, str]], *, lookback: int = 5) -> Counter[str]:
    counts: Counter[str] = Counter()
    for turn in prev_turns[:lookback]:
        turn_sigs: set[str] = set()
        for text in _iter_texts_from_turn(turn):
            turn_sigs |= extract_repetition_signatures(text)
        counts.update(turn_sigs)
    return counts


def build_repetition_avoidance_hint(
    prev_turns: list[dict[str, str]],
    *,
    step_name: str,
    lookback: int = 5,
    min_count: int = 2,
    max_items: int = 8,
) -> str:
    counts = collect_recent_signature_counts(prev_turns, lookback=lookback)
    hot = [(sig, n) for sig, n in counts.most_common() if n >= min_count]
    if not hot:
        return ""
    hot = hot[:max_items]
    sig_text = "、".join(f"{sig}（{n}次）" for sig, n in hot)
    scope = {
        "env": "环境描写应换用新的空间细节、声响或物件，不要复用这些高频意象。",
        "body_state": "身体描写应换用新的可观察状态或保持简洁，不要继续播放同一微动作。",
        "thoughts": "心理描写应抽象承接状态，不要继续使用同一比喻、同一动作意象或同一句式。",
        "response": "角色回复应以台词或全新动作推进，不要复述这些高频微动作/意象。",
        "third_party": "第三者发言须提供新信息或新动作，不要借这些高频节拍凑场。",
    }.get(step_name, "本轮须避免继续使用这些高频表达。")
    return (
        "【近期高频表达指纹｜本轮降权】\n"
        f"以下表达模式已在最近剧情中反复出现：{sig_text}。\n"
        f"{scope}除非玩家本轮直接触发对应部位、物件或意象，否则须改用新的动作、对象、句式或推进事件。"
    )


def check_signature_repetition(
    candidate: str,
    blocked_signatures: Iterable[str],
    *,
    allow_phrase: bool = False,
) -> str:
    blocked = set(blocked_signatures)
    if not blocked:
        return ""
    cand = extract_repetition_signatures(candidate)
    if not allow_phrase:
        cand = {s for s in cand if not s.startswith("短语:")}
        blocked = {s for s in blocked if not s.startswith("短语:")}
    overlap = cand & blocked
    if not overlap:
        return ""
    return sorted(overlap)[0]


def repeated_signature_retry_hint(signature: str, step_label: str) -> str:
    extra = ""
    if signature.startswith("动作:") and "+" in signature:
        body = signature.split(":", 1)[1].split("+", 1)[0]
        extra = f"本次重写中尽量完全避开「{body}」这个部位，改用台词、停顿、物件互动、姿态变化或其他未出现过的对象承接情绪。"
    return (
        f"\n\n⚠️ 检测到{step_label}复用了近期或本轮已使用的表达指纹「{signature}」。"
        "请整段重写，禁止继续使用该身体部位+动作、同类微表情、同一台词开头/收尾或近义表达；"
        f"{extra}"
        "改用新的可观察动作、对象、句式，或直接用台词推进。"
    )
