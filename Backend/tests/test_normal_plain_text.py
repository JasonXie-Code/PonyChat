"""Plain chat formatting without booting Backend or calling a model."""
import importlib.util
from pathlib import Path

path = Path(__file__).parents[1] / "chat_modules/normal_plain_text.py"
spec = importlib.util.spec_from_file_location("normal_plain_text_under_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
plain = module.normal_plain_text


def test_pinkie_memory_reply_has_no_markdown_or_numbered_list():
    raw = "我记住了两件事——\n1. 你更喜欢**无糖茉莉花茶**（这是你的偏好）\n2. 我们约好**周六下午三点在方糖甜品屋门口见**！"
    result = plain(raw)
    assert "**" not in result and "1." not in result and "2." not in result
    assert "无糖茉莉花茶" in result and "周六下午三点" in result
    assert plain(raw.replace("\n", " ")) == result


def test_structured_markdown_becomes_readable_plain_text():
    result = plain("# 喝茶\n> 欢迎\n- **无糖**\n- [方糖屋](https://example.com)\n```text\n三点见\n```\n---")
    assert result == "喝茶\n欢迎\n无糖。\n方糖屋（https://example.com）。\n\n三点见"


def test_literal_numbers_arithmetic_and_urls_remain_intact():
    text = "版本 5.6.17，周六 15:00。2 * 3 = 6，2 ** 3 = 8，user_name。https://example.com/a_b"
    assert plain(text) == text


def test_table_preserves_header_value_relationships():
    assert plain("| 茶 | 口味 |\n| --- | --- |\n| 茉莉花茶 | 无糖 |") == "茶：茉莉花茶，口味：无糖。"


def test_inline_code_and_emphasis_are_removed():
    assert plain("**记住了**，`15:00`见，*好的*。") == "记住了，15:00见，好的。"
