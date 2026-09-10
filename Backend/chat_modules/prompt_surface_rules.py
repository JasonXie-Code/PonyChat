"""Resolve requested punctuation style for prompt construction."""
import re

DASH = re.compile(r"[—–―]")


def dash_preference(text):
    decision = None
    for clause in re.split(r"[。！？!?；;，,\n]", str(text).lower()):
        target = r"(?:破折号|长横线|em[ -]?dash|[—–―])"
        if re.search(r"(?:不要|别|不用|禁止|避免|不使用|不加|禁用|不允许|不能|没有要求|do not|don't|avoid)[^。！？\n]{0,12}" + target, clause) and not re.search(r"不要改动|不要修改|别改|不改变", clause):
            decision = False
        elif re.search(r"(?:请|本轮|这次|以后|今后|继续|允许|可以|需要|要|务必|必须)[^。！？\n]{0,10}(?:用|使用|保留|加入|加上|写上|输出)[^。！？\n]{0,12}" + target, clause) or re.search(r"^\s*(?:用|使用|保留|允许|加入|加上|写上|输出|解释|演示|use|keep)(?!了|过)[^。！？\n]{0,12}" + target, clause):
            decision = True
        elif re.search(target + r"\s*[:：]\s*(?:允许|使用|保留)", clause):
            decision = True
    if decision is None and DASH.search(str(text)) and re.search(r"原样|逐字|一字不改|照抄|verbatim", str(text), re.I):
        decision = True
    return decision


def dash_allowed(data, preferences):
    batch = data.get("current_user_batch") or [data.get("latest_user_message") or {}]
    if not isinstance(batch, list):
        batch = [batch]
    text = "\n".join(str(m.get("content", "")) if isinstance(m, dict) else str(m) for m in batch)
    current = dash_preference(text)
    if current is not None:
        return current
    return dash_preference(preferences) is True
