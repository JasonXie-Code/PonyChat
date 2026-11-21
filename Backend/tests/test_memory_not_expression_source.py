"""记忆正文只作事实依据，不作表达方式依据。"""
from __future__ import annotations

import importlib
from pathlib import Path

from test_autonomous_prompt_skills import skills

Prompts = importlib.import_module(skills.__package__ + '.Prompts')
ROOT = Path(__file__).resolve().parents[2]

STYLE_RULE = '不作为表达方式依据'


def test_memory_skill_forbids_borrowing_memory_wording():
    assert STYLE_RULE in Prompts.memory
    assert '不得复用记忆里的用词、句式、比喻、语气或口癖' in Prompts.memory


def test_deduplication_skill_covers_memory_text_not_only_history():
    assert '记忆正文同理' in Prompts.reply_deduplication
    assert STYLE_RULE in Prompts.reply_deduplication


def test_normal_chat_memory_block_states_the_rule_before_the_entries():
    source = (ROOT / 'Backend/chat_modules/request_context.py').read_text(encoding='utf-8')
    assert '【记忆只作事实依据，不作为表达方式依据】' in source
    # 说明必须排在记忆正文之前，不能只挂在别处
    header = source.index('【记忆只作事实依据，不作为表达方式依据】')
    assert source.index('memory_block = (') < header < source.index('+ memory_block')


def test_proactive_memory_block_states_the_rule():
    source = (ROOT / 'Backend/scheduled_followup_impl/followup_delivery.py').read_text(encoding='utf-8')
    assert STYLE_RULE in source
    assert '不得复用其中的用词、句式、比喻、语气或口癖' in source
