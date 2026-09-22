import importlib
import json
from test_autonomous_prompt_skills import skills

build = importlib.import_module(skills.__package__ + '.reply_repetition_context').build_reply_repetition_context


def test_bubbles_form_one_turn_and_punctuation_does_not_hide_the_opening():
    history = [{'role': 'user', 'content': '你好'},
               {'role': 'assistant', 'content': '（我坐着）唔……你好'},
               {'role': 'assistant', 'content': '后面的气泡'},
               {'role': 'user', 'content': '再说'},
               {'role': 'assistant', 'content': '唔......今天很好'}]
    result = build(history)
    assert result['observed_turns'] == 2
    assert result['speech_openings'] == [{'text': '唔', 'turns_ago': [1, 2]}]


def test_speakers_hidden_messages_and_within_turn_repetition_are_not_extra_turns():
    history = [{'role': 'assistant', 'content': '重复片段只算一轮重复片段只算一轮', 'speaker_character_id': 'a'},
               {'role': 'assistant', 'content': '唔……', 'speaker_character_id': 'b'},
               {'role': 'assistant', 'content': '唔……', 'is_hidden': True},
               {'role': 'assistant', 'content': '唔……', 'deleted_at': 'now'}]
    result = build(history, speaker_character_id='a')
    assert result['observed_turns'] == 1
    assert all(row['turns_ago'] == [1] for row in result['repeated_spans'])
    assert result['repeated_spans'][0]['occurrences'] >= 2


def test_recent_literal_spans_and_context_size_are_bounded():
    history = []
    for i in range(20):
        history += [{'role': 'user', 'content': str(i)},
                    {'role': 'assistant', 'content': '翅膀不自觉掀了半寸又慢慢落回背上。' * 30}]
    result = build(history)
    assert result['observed_turns'] == 10 and result['history_may_be_incomplete']
    assert result['repeated_spans'][0]['turns_ago'] == list(range(1, 11))
    assert len(json.dumps(result, ensure_ascii=False)) < 4000
    assert build([])['observed_turns'] == 0


def test_full_text_after_3000_and_short_interjections_inside_later_bubbles():
    history = []
    for filler in ('a', 'b'):
        history += [{'role': 'user', 'content': '问'},
                    {'role': 'assistant', 'content': filler * 3500 + '。共同测试末尾短语甲乙。'},
                    {'role': 'assistant', 'content': '中间一句。唔……后续一句。唔……'}]
    result = build(history)
    spans = {row['text']: row for row in result['repeated_spans']}
    assert spans['共同测试末尾短语甲乙']['turns_ago'] == [1, 2]
    assert spans['唔']['occurrences'] == 4
    assert spans['唔']['turns_ago'] == [1, 2]
    assert result['scanned_characters'] > 7000


def test_tenth_turn_is_included_and_eleventh_is_excluded():
    history = []
    for i in range(11):
        text = '共同十轮目标短语' if i in (1, 10) else str(i)
        if i in (0, 10):
            text += '。排除十一轮旧短语'
        history += [{'role': 'user', 'content': '问'}, {'role': 'assistant', 'content': text}]
    spans = {row['text']: row for row in build(history)['repeated_spans']}
    assert spans['共同十轮目标短语']['turns_ago'] == [1, 10]
    assert '排除十一轮旧短语' not in spans


def test_names_remain_observations_and_skill_explicitly_allows_repetition():
    history = [{'role': 'user', 'content': '问'}, {'role': 'assistant', 'content': '云中城。Twilight。'},
               {'role': 'user', 'content': '问'}, {'role': 'assistant', 'content': '云中城。Twilight。'}]
    assert {'云中城', 'Twilight'} <= {row['text'] for row in build(history)['repeated_spans']}
    prompts = importlib.import_module(skills.__package__ + '.Prompts')
    assert '专有名称可以正常重复' in prompts.reply_deduplication


def test_two_character_habit_words_are_counted_across_turns():
    """二字习惯用词（如“方才”）过去因为只统计4字以上片段而永远不被列出。"""
    turns = [
        '（我把脸侧过去）方才你舌尖退开的那一点空隙，让我合了合唇。',
        '（我抬起蹄子）这样躺着就好，我什么都不用做。',
        '（我往你怀里挪）方才我还想着先下床去洗一洗，腿刚放到地上就知道走不了。',
        '（我收拢翅膀）你别急着动呀，我趴在你胸口听着就行。',
        '（我把脸埋起来）方才被你弄过的地方还有一点酸，可你一停下手又难受。',
        '（我抓着床单）我腿软着，你等我缓一缓。',
        '（我把鬃毛拨开）方才是我自己把话说满了，这会儿摇摇晃晃也只能怨我。',
        '（我垂下耳朵）我数着你呢，你别一下子推到底。',
        '（我贴着你）方才那些热留在里面还没散，我稍微一动就往外淌一点。',
        '（我闭上眼）哪也别去，让我多听一会儿你的心跳。',
    ]
    history = []
    for text in turns:
        history += [{'role': 'user', 'content': '嗯'}, {'role': 'assistant', 'content': text}]
    spans = {row['text']: row for row in build(history)['repeated_spans']}
    assert spans['方才']['turns_ago'] == [2, 4, 6, 8, 10]
    assert spans['方才']['occurrences'] == 5


def test_two_character_spans_appear_beside_longer_phrases():
    """不同上下文里的同一个二字词不被更长的片段吞掉。"""
    history = [{'role': 'user', 'content': '问'},
               {'role': 'assistant', 'content': '翅膀不自觉掀了半寸。方才好冷。'},
               {'role': 'user', 'content': '问'},
               {'role': 'assistant', 'content': '腿根还软着。方才你按过的地方有点酸。'},
               {'role': 'user', 'content': '问'},
               {'role': 'assistant', 'content': '翅膀不自觉掀了半寸。方才我数着你呢。'}]
    spans = {row['text']: row for row in build(history)['repeated_spans']}
    assert spans['方才']['turns_ago'] == [1, 2, 3]
    assert '翅膀不自觉掀了半寸' in spans


def test_cross_word_fragments_never_reach_the_display():
    """只在词中间出现的二字碎片（“才那”出自“刚才那张”）不算候选。"""
    history = []
    for text in ('我翻过了，刚才那张就是边界。',
                 '这些是刚才那间屋子里的东西。',
                 '我说的就是刚才那些话。'):
        history += [{'role': 'user', 'content': '嗯'}, {'role': 'assistant', 'content': text}]
    texts = {row['text'] for row in build(history)['repeated_spans']}
    assert '才那' not in texts
    assert '刚才那' in texts  # 更长的片段仍然保留


def test_two_character_habit_words_survive_on_clause_edges():
    history = []
    for text in ('方才你说过的话我记着。', '方才我数着你呢。',
                 '方才那些热还没有散。', '腿是软的。方才被你碰过。'):
        history += [{'role': 'user', 'content': '嗯'}, {'role': 'assistant', 'content': text}]
    spans = {row['text']: row for row in build(history)['repeated_spans']}
    assert spans['方才']['turns_ago'] == [1, 2, 3, 4]


def test_two_character_spans_are_capped_but_long_spans_still_show():
    """短片段最多占 MAX_SHORT_SPANS 个展示位，长片段不被挤掉。"""
    fillers = ['方才', '随后', '忽然', '只是', '果然', '仍旧', '偏又', '竟还', '早就', '刚好']
    follow = ['又', '还', '已', '刚', '只', '偏', '竟', '就']
    history = []
    for turn in range(8):
        # 习惯词后面每轮换字，避免被更长的固定片段整段覆盖
        body = '，'.join(f'{word}{follow[turn]}看了你一眼' for word in fillers) + '。'
        history += [{'role': 'user', 'content': '嗯'}, {'role': 'assistant', 'content': body}]
    result = build(history)
    short = [row['text'] for row in result['repeated_spans'] if len(row['text']) <= 2]
    assert 0 < len(short) <= 6
    assert '方才' in short
    assert len(result['repeated_spans']) <= 24
    assert any(len(row['text']) >= 4 for row in result['repeated_spans'])


def test_short_habit_word_survives_when_long_spans_abound():
    """长片段很多时，二字习惯用词仍然保留展示位（配额是预留，不是只做上限）。"""
    follow = ['又', '还', '已', '刚', '只', '偏', '竟', '就']
    history = []
    for turn in range(8):
        body = f'方才{follow[turn]}看了你一眼，' + '翅膀收着没有动。' * 30
        history += [{'role': 'user', 'content': '嗯'}, {'role': 'assistant', 'content': body}]
    result = build(history)
    short = [row['text'] for row in result['repeated_spans'] if len(row['text']) <= 2]
    assert '方才' in short
    assert any(len(row['text']) >= 4 for row in result['repeated_spans'])


def test_display_limit_and_short_span_quota_are_declared():
    context = importlib.import_module(skills.__package__ + '.reply_repetition_context')
    assert context.DISPLAY_LIMIT == 24
    assert context.MAX_SHORT_SPANS == 6
