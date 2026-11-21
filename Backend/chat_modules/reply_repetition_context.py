"""Small observed text patterns (2+ characters), derived from completed visible role turns."""
from __future__ import annotations

import re
from collections import Counter

# 展示上限，以及短片段（1~2 字，含单字语气词）在展示位里的配额。短片段容易是
# 跨词碎片，给它们固定的小配额并预留名额，其余展示位留给更长的片段。
DISPLAY_LIMIT = 24
MAX_SHORT_SPANS = 6


def _is_observable_span(text: str, edge_evidence: Counter) -> bool:
    """二字片段只有在分句首尾出现过才算候选。

    分句边界由标点切分出的 token 边界表示。跨词碎片（“才那”出自“刚才那张”、
    “么样”出自“怎么样”）永远落在词中间，而习惯用词、副词和连接语通常会落在
    分句开头或结尾，因此该判据不需要词典即可把两类分开。
    """
    if len(text) != 2:
        return True
    return edge_evidence[text] >= 1


def build_reply_repetition_context(messages, *, speaker_character_id=None):
    turns, current = [], None
    for message in messages or []:
        if message.get('is_hidden') or message.get('isHidden') or message.get('deleted_at'):
            continue
        if message.get('role') == 'user':
            current = None
            continue
        if message.get('role') != 'assistant':
            continue
        speaker = message.get('speaker_character_id')
        if speaker_character_id and speaker and speaker != speaker_character_id:
            continue
        if current is None:
            current = []
            turns.append(current)
        current.append(str(message.get('content') or ''))
    turns = ['\n'.join(t) for t in turns[-10:]]
    openings, index = {}, {}
    edge_evidence: Counter = Counter()
    for ago, text in enumerate(reversed(turns), 1):
        spoken = re.sub(r'（[^）]*）|\([^)]*\)', '', text).strip()
        # Observe the first speech clause, including interjections before ellipses.
        opening = re.split(r'[，。！？?!…\n]|\.{2,}', spoken, maxsplit=1)[0].strip()[:12]
        if opening:
            openings.setdefault(opening, []).append(ago)
        # Scan every bubble in full, including short clauses and non-CJK names.
        # Limit the displayed evidence, never the source text being counted.
        # 2字词也要统计：二字习惯用词（如"方才"）在更长的分词片段里永远不会
        # 成为候选，只统计4字以上会漏掉这类跨轮反复出现的用词。
        counts = Counter()
        for span in re.findall(r'\w+', text):
            if len(span) < 2:
                counts[span] += 1
            for size in range(2, min(20, len(span)) + 1):
                for start in range(len(span) - size + 1):
                    piece = span[start:start + size]
                    counts[piece] += 1
                    if size == 2 and (start == 0 or start + size == len(span)):
                        edge_evidence[piece] += 1
        for span, count in counts.items():
            index.setdefault(span, {})[ago] = count
    phrases = []
    candidates = [(text, ages) for text, ages in index.items()
                  if sum(ages.values()) >= 2 and _is_observable_span(text, edge_evidence)]
    ranked = sorted(candidates, key=lambda item: (-len(item[1]), -len(item[0]), min(item[1])))
    # 配额：1~2 字片段最多占 MAX_SHORT_SPANS 位；先为它们留出名额，再用长片段
    # 填满剩余展示位，避免任一类把另一类整体挤出展示。
    short_pool = [item for item in ranked if len(item[0]) <= 2]
    long_pool = [item for item in ranked if len(item[0]) > 2]
    chosen = short_pool[:MAX_SHORT_SPANS]
    chosen.extend(long_pool[:max(0, DISPLAY_LIMIT - len(chosen))])
    chosen_texts = {text for text, _ages in chosen}
    for text, ages in ranked:
        if text not in chosen_texts:
            continue
        if any(text in row['text'] and sorted(ages) == row['turns_ago']
               and sum(ages.values()) == row['occurrences'] for row in phrases):
            continue
        phrases.append({'text': text, 'turns_ago': sorted(ages), 'occurrences': sum(ages.values())})
    return {'history_may_be_incomplete': True, 'observed_turns': len(turns),
            'window_turns': 10, 'scanned_characters': sum(map(len, turns)),
            'candidate_span_count': len(candidates), 'displayed_span_count': len(phrases),
            'speech_openings': [{'text': text, 'turns_ago': ages} for text, ages in list(openings.items())[:4]],
            'repeated_spans': phrases}
