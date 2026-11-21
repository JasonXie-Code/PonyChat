"""Structural delivery contract for an explicitly summoned dead character."""
from __future__ import annotations

import re

SPIRIT_TEXT_LIMIT = 240


def validate_spirit_reply(data: dict) -> None:
    bubbles = data.get('bubbles') or []
    if data.get('bubble_count') != 1 or len(bubbles) != 1:
        raise ValueError('灵魂回应只允许1个短文本气泡，不能恢复普通多气泡聊天')
    parts = bubbles[0].get('parts') or []
    if len(parts) < 2 or any(p.get('kind') == 'speech' for p in parts[:-1]) or parts[-1].get('kind') != 'speech':
        raise ValueError('灵魂回应须先用非speech片段描述灵魂或残响显形，再用一个speech片段写短台词')
    description = ' '.join(str(p.get('text') or '') for p in parts[:-1])
    text = description + ' ' + str(parts[-1].get('text') or '')
    if sum(len(str(p.get('text') or '')) for p in parts) > SPIRIT_TEXT_LIMIT:
        raise ValueError(f'灵魂回应必须简短，显形描写和台词的片段文字合计不超过{SPIRIT_TEXT_LIMIT}个字符；详细描述请求不改变此限制')
    if not re.search(r'灵魂|残响|幽魂|幽灵|\b(?:spirit|ghost|soul|echo)\b', description, re.I):
        raise ValueError('显形描写必须明确发言主体是已死亡角色的灵魂或残响')
    if re.search(r'我|咱|\b(?:I|me|my|mine|we|our|ours)\b', text, re.I):
        raise ValueError('灵魂回应使用第三者显形描写和短台词，不使用我、我的、我们、咱等生者第一人称')
    voice = data.get('voice_reply') or {}
    if isinstance(voice, dict) and voice.get('enabled'):
        raise ValueError('灵魂回应只允许文本，不启用语音')
