"""语音验收报告的复核必须能识破“报告与最终代码不一致”和“尾词被截断”。

回归背景：上一份 8/8 报告里一条交付提示结束于 `...on the last`，而最终实现给同一份决策
提示的结果是 `...on the last word`；报告也没有记录裁剪实现本身的哈希，无法证明它对应的
是哪一版代码。
"""
import hashlib
import unittest
from pathlib import Path

from scripts.ops import verify_emotion_prompt_acceptance as acceptance

ROOT = Path(__file__).resolve().parents[2]
TEXT_LIMITS = acceptance.load_text_limits(ROOT)
MAX_CHARS = 100
DECISION_PROMPT = (
    "Bright, bouncy and fast-paced, with a warm cheerful lilt and an excited little rise on the last word."
)


def _case(delivered, *, expected_voice=True, source=DECISION_PROMPT, name="english_voice"):
    paragraphs = []
    if delivered is not None:
        paragraphs.append({"type": "assistant_paragraph", "content": "hi",
                           "voice_state": {"voice_sentences": [{"text": "hi", "emotion_prompt": delivered}]}})
    return {
        "case": name,
        "expected_voice": expected_voice,
        "paragraphs": paragraphs,
        "decision": {"voice_reply": {"enabled": expected_voice, "emotion_prompt": source}},
    }


def _report(cases, *, source_hashes=None):
    return {"passed": True, "cases": cases, "source_hashes": source_hashes if source_hashes is not None else {}}


def _current_hashes():
    return acceptance.source_hash_check(_report([]), ROOT)["current"]


class PromptCheckTests(unittest.TestCase):
    def test_current_implementation_result_passes(self):
        delivered = TEXT_LIMITS.truncate_prompt_text(DECISION_PROMPT, MAX_CHARS)

        check = acceptance.check_case(_case(delivered), TEXT_LIMITS, MAX_CHARS)

        self.assertTrue(check["prompt_passed"])
        self.assertEqual(delivered, "Bright, bouncy and fast-paced, with a warm cheerful lilt"
                                    " and an excited little rise on the last word")

    def test_report_value_that_no_longer_matches_the_implementation_is_flagged(self):
        # 旧实现的产物：丢掉完整末词 `word`，报告里就是这条值。
        stale = "Bright, bouncy and fast-paced, with a warm cheerful lilt and an excited little rise on the last"

        check = acceptance.check_case(_case(stale), TEXT_LIMITS, MAX_CHARS)

        self.assertFalse(check["prompt_passed"])
        self.assertFalse(check["prompt_checks"][0]["matches_current_code"])
        self.assertTrue(check["prompt_checks"][0]["from_decision_prompt"])

    def test_half_a_word_at_the_tail_is_flagged(self):
        truncated = DECISION_PROMPT[:MAX_CHARS - 1]  # `...on the last wor`
        self.assertTrue(truncated.endswith("wor"))

        check = acceptance.check_case(_case(truncated), TEXT_LIMITS, MAX_CHARS)

        self.assertFalse(check["prompt_passed"])
        self.assertTrue(check["prompt_checks"][0]["ends_inside_word"])

    def test_delivered_prompt_must_come_from_the_decision_prompt(self):
        # 是决策提示的前缀、但短于当前实现的结果：可能来自旧实现，必须标成与当前实现不一致。
        shorter = "Bright, bouncy and fast-paced, with a warm cheerful lilt"
        check = acceptance.check_case(_case(shorter), TEXT_LIMITS, MAX_CHARS)

        self.assertTrue(check["prompt_checks"][0]["from_decision_prompt"])
        self.assertFalse(check["prompt_checks"][0]["matches_current_code"])
        self.assertFalse(check["prompt_passed"])

        # 决策提示里根本没有的值同样不合格。
        check = acceptance.check_case(_case("Warm and cheerful, but this was never in the decision."),
                                      TEXT_LIMITS, MAX_CHARS)
        self.assertFalse(check["prompt_checks"][0]["from_decision_prompt"])
        self.assertFalse(check["prompt_passed"])

    def test_case_without_voice_delivery_needs_no_instruct(self):
        check = acceptance.check_case(_case(None, expected_voice=False), TEXT_LIMITS, MAX_CHARS)

        self.assertTrue(check["prompt_passed"])

    def test_default_prompt_is_not_treated_as_a_lost_prompt(self):
        default = "Warm, relaxed, conversational."

        check = acceptance.check_case(_case(default, source=""), TEXT_LIMITS, MAX_CHARS, default)

        self.assertTrue(check["prompt_passed"])
        self.assertTrue(check["prompt_checks"][0]["uses_default_prompt"])

    def test_other_prompt_without_a_decision_source_fails(self):
        check = acceptance.check_case(_case("Something nobody asked for.", source=""), TEXT_LIMITS, MAX_CHARS,
                                      "Warm, relaxed, conversational.")

        self.assertFalse(check["prompt_passed"])

    def test_voice_expected_without_any_instruct_fails(self):
        check = acceptance.check_case(_case(None, expected_voice=True), TEXT_LIMITS, MAX_CHARS)

        self.assertFalse(check["prompt_passed"])


class ReportCheckTests(unittest.TestCase):
    def test_report_without_the_truncation_source_hash_cannot_pass(self):
        delivered = TEXT_LIMITS.truncate_prompt_text(DECISION_PROMPT, MAX_CHARS)
        hashes = {name: value for name, value in _current_hashes().items() if name != "text_limits.py"}

        result = acceptance.verify_report(_report([_case(delivered)], source_hashes=hashes), TEXT_LIMITS, MAX_CHARS, ROOT)

        self.assertTrue(result["prompt_passed"])
        self.assertFalse(result["source_hashes"]["passed"])
        self.assertIn("text_limits.py", result["source_hashes"]["missing"])
        self.assertFalse(result["passed"])

    def test_report_pinned_to_the_current_code_passes(self):
        delivered = TEXT_LIMITS.truncate_prompt_text(DECISION_PROMPT, MAX_CHARS)

        result = acceptance.verify_report(_report([_case(delivered)], source_hashes=_current_hashes()),
                                          TEXT_LIMITS, MAX_CHARS, ROOT)

        self.assertTrue(result["passed"])

    def test_report_with_a_mismatched_truncation_hash_fails(self):
        delivered = TEXT_LIMITS.truncate_prompt_text(DECISION_PROMPT, MAX_CHARS)
        hashes = dict(_current_hashes(), **{"text_limits.py": "0" * 64})

        result = acceptance.verify_report(_report([_case(delivered)], source_hashes=hashes), TEXT_LIMITS, MAX_CHARS, ROOT)

        self.assertFalse(result["passed"])
        self.assertEqual(result["source_hashes"]["mismatched"], ["text_limits.py"])

    def test_line_ending_differences_do_not_invalidate_the_pin(self):
        delivered = TEXT_LIMITS.truncate_prompt_text(DECISION_PROMPT, MAX_CHARS)
        # checkout 造成的 CRLF 变化不该让报告失效：记的是内容，不是换行。
        hashes = dict(_current_hashes())
        hashes["text_limits.py"] = acceptance.normalized_hash(
            (ROOT / "Backend/chat_modules/text_limits.py").read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        )

        result = acceptance.verify_report(_report([_case(delivered)], source_hashes=hashes), TEXT_LIMITS, MAX_CHARS, ROOT)

        self.assertTrue(result["source_hashes"]["passed"])
        self.assertTrue(result["passed"])

    def test_raw_byte_pins_are_accepted_too(self):
        # 早期报告记的是原样字节哈希，仍然要能复核。
        delivered = TEXT_LIMITS.truncate_prompt_text(DECISION_PROMPT, MAX_CHARS)
        hashes = {name: hashlib.sha256((ROOT / "Backend/chat_modules" / name).read_bytes()).hexdigest()
                  for name in acceptance.PINNED_SOURCES}

        result = acceptance.verify_report(_report([_case(delivered)], source_hashes=hashes), TEXT_LIMITS, MAX_CHARS, ROOT)

        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
