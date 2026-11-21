"""Explicit paragraph constraints without mistaking topic counts for replies."""
import importlib.util
from pathlib import Path

import pytest


path = Path(__file__).parents[1] / "chat_modules/normal_reply_count.py"
spec = importlib.util.spec_from_file_location("reply_count_under_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
count = module.requested_reply_count


@pytest.mark.parametrize("text,expected", [
    ("紫悦，请说一段话。", 1), ("请回复两段，别多说。", 2), ("分3段说说读书的乐趣", 3),
    ("用四个自然段描述夜空", 4), ("请正好回复５段", 5), ("两段话就好", 2), ("就两段", 2),
    ("回复5条消息", 5), ("Please reply in exactly three paragraphs.", 3),
    ("不要说两段，改成三段", 3), ("刚才让你说一段，这次请说四段", 4),
    ("请说两段，不，改成五段", 5), ("不限段数了，但这次只回复两段", 2),
])
def test_explicit_affirmative_requests(text, expected):
    assert count(text) == expected


@pytest.mark.parametrize("text", [
    "说说两个动作", "我有两段经历想告诉你", "帮我说三件事", "你刚才说了两段", "不要说两段",
    "请说1-5段", "请说一到五段", "请说12段", "请说至少两段", "最多说两段", "大约写三段",
    "请评价第一段和第二段", "我写了两段，你看看", "她说‘明天见’", "Please discuss two things.",
    "请说两段，算了，段数不限", "上次我让你说三段", "如果我让你说两段，你会怎么做？",
    '解释这句话：“请说两段”', '解释这句话："reply in two paragraphs"',
])
def test_non_requests_ranges_negation_and_history_are_not_hard_constraints(text):
    assert count(text) is None
