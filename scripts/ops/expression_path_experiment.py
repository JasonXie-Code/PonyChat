"""Isolated lossless expression-skill split; never imported by production."""
from __future__ import annotations

import re

CORE = (1, 2, 4, 6, 8, 12, 13, 14, 16, 17, 18)
PATHS = {
    'conversation_reply': (5, 7, 9),
    'interaction_reply': (3, 7, 10, 11, 15),
    'description_reply': (3, 7),
}
WHEN = {
    'conversation_reply': '普通问答、闲聊、分享、回忆、暂别等接话；当前消息同时有动作时可与动作路径一起读取。',
    'interaction_reply': '本轮发起实际动作或确有未结束的持续动作需要承接；历史上发生过动作本身不触发。',
    'description_reply': '本轮明确要求心理、身体、画面等描写；同时要求实际动作时可与动作路径一起读取。',
}
ROUTING = ('【读取路径】本技能保留共同表达规则。依据当前用户消息与已确认的持续状态，'
           '在生成前调用load_chat_skill读取适用路径：conversation_reply为日常接话，'
           'interaction_reply为动作互动，description_reply为明确描写。混合请求可读取多项；'
           '不为旧历史动作或预防性覆盖读取无关路径。路径只拆分现有表达规则，'
           '不改变互动模式、事实来源、身体和关系边界、快捷消息或交付数量。')


def partition(text):
    matches = list(re.finditer(r'(?m)^(\d+)\. ', text))
    rules = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        rules[int(match.group(1))] = text[match.start():end].replace('【内容组织】', '').strip()
    assert set(rules) == set(range(1, 19))
    assert set(CORE).union(*map(set, PATHS.values())) == set(rules)
    return rules


def split_session_class(base, full_text):
    rules = partition(full_text)

    def body(indices):
        return '\n'.join(rules[i] for i in indices)

    class SplitSession(base):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.catalog['reply_expression'] = ('每轮读取共同表达规则并选择适用路径。',
                                                body(CORE) + '\n' + ROUTING)
            for name, indices in PATHS.items():
                self.catalog[name] = (WHEN[name], body(indices))

        def skill_instructions(self, name):
            if name in PATHS or name == 'reply_expression':
                return '【' + name + '】\n' + self.catalog[name][1]
            return super().skill_instructions(name)

    return SplitSession
