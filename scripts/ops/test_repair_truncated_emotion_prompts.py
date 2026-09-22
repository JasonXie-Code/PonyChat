"""历史提示词修复脚本：候选不等于证据，只有确认记录能触发写入。

回归背景：旧条件“长度正好落在 100/220 且以字母数字结尾”会把本来完整的提示也选中，
对完整提示调用裁剪逻辑会删掉完整的末词。现在只读扫描只输出候选，写入必须有原始生成
记录或已确认记录。
"""
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from scripts.ops import repair_truncated_emotion_prompts as repair

# 生产现场真实被硬切的值：完整提示 117 字符，存库只有前 100 字符 `...trailin`。
ORIGINAL_PROMPT = (
    "Speak slowly and gently in a soft, shy, almost whispering voice, "
    "warm and a little hesitant, trailing off at the end."
)
TRUNCATED_PROMPT = ORIGINAL_PROMPT[:100]
# 同一份报告里的真实反例：100 字符、以字母结尾，但末词 `word` 是完整的。
COMPLETE_PROMPT = (
    "Bright, bouncy and fast-paced, with a warm cheerful lilt and an excited little rise on the last word."
)[:100]


def _database(path: Path, prompts) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE message_voice_states (conversation_id TEXT, message_id TEXT,"
        " voice_sentences_json TEXT, updated_at INTEGER)"
    )
    for index, prompt in enumerate(prompts):
        conn.execute(
            "INSERT INTO message_voice_states VALUES (?,?,?,?)",
            ("conv_1", f"msg_{index}", json.dumps([{"text": "hi", "emotion_prompt": prompt}]), 1),
        )
    conn.commit()
    conn.close()


def _stored_prompts(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [
            item["emotion_prompt"]
            for (raw,) in conn.execute("SELECT voice_sentences_json FROM message_voice_states ORDER BY message_id")
            for item in json.loads(raw)
        ]
    finally:
        conn.close()


def _run(argv) -> dict:
    stream = io.StringIO()
    with mock.patch.object(sys, "argv", ["repair"] + [str(item) for item in argv]):
        with redirect_stdout(stream):
            repair.main()
    return json.loads(stream.getvalue())


class CandidateScanTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "ponychat.db"
        _database(self.database, [TRUNCATED_PROMPT, COMPLETE_PROMPT])

    def test_fixtures_match_the_reported_shape(self):
        self.assertEqual(len(TRUNCATED_PROMPT), 100)
        self.assertTrue(TRUNCATED_PROMPT.endswith("trailin"))
        self.assertEqual(len(COMPLETE_PROMPT), 100)
        self.assertTrue(COMPLETE_PROMPT.endswith("word"))
        self.assertTrue(repair.cut_inside_word(ORIGINAL_PROMPT, len(TRUNCATED_PROMPT)))

    def test_scan_reports_candidates_without_writing(self):
        before = _stored_prompts(self.database)

        result = _run(["--database", self.database])

        self.assertEqual(result["mode"], "scan")
        self.assertFalse(result["applied"])
        self.assertEqual(result["rows"], 0)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(
            [item["confirmed"] for item in result["candidates"]], [False, False]
        )
        self.assertEqual(_stored_prompts(self.database), before)

    def test_scan_does_not_claim_the_complete_prompt_was_truncated(self):
        result = _run(["--database", self.database])

        complete = [item for item in result["candidates"] if item["prompt"] == COMPLETE_PROMPT]
        self.assertEqual(len(complete), 1)
        # 候选条件只是“长度正好落在旧上限且以字母结尾”，不能据此判断末词残缺。
        self.assertFalse(repair.cut_inside_word(COMPLETE_PROMPT + ".", len(COMPLETE_PROMPT)))

    def test_apply_without_confirmation_refuses_before_writing(self):
        before = _stored_prompts(self.database)

        with self.assertRaises(SystemExit) as raised:
            _run(["--database", self.database, "--apply", "--backup", Path(self.directory.name) / "backup"])

        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(_stored_prompts(self.database), before)
        self.assertFalse((Path(self.directory.name) / "backup").exists())


class ConfirmedApplyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "ponychat.db"
        self.confirm = Path(self.directory.name) / "confirm.json"
        self.backup = Path(self.directory.name) / "backup"
        _database(self.database, [TRUNCATED_PROMPT, COMPLETE_PROMPT])

    def _confirm(self, entries) -> None:
        self.confirm.write_text(json.dumps({"confirmed": entries}, ensure_ascii=False), encoding="utf-8")

    def test_only_the_confirmed_candidate_is_repaired(self):
        self._confirm([{"prompt": TRUNCATED_PROMPT, "original_prompt": ORIGINAL_PROMPT,
                        "source": "agent run response record"}])

        result = _run(["--database", self.database, "--apply", "--backup", self.backup,
                       "--confirm", self.confirm])

        self.assertTrue(result["applied"])
        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["prompt_changes"][0]["evidence"], "original_generation_record")
        self.assertEqual(result["skipped_candidate_count"], 1)
        self.assertEqual(
            _stored_prompts(self.database),
            ["Speak slowly and gently in a soft, shy, almost whispering voice, warm and a little hesitant",
             COMPLETE_PROMPT],
        )
        self.assertTrue((self.backup / "ponychat.before-repair.db").exists())
        before = json.loads((self.backup / "emotion-prompts.before.json").read_text(encoding="utf-8"))
        self.assertEqual(before[0]["prompts"][0]["before"], TRUNCATED_PROMPT)

    def test_operator_confirmation_is_accepted_with_a_verifier(self):
        self._confirm([{"prompt": TRUNCATED_PROMPT, "confirmed_truncated": True,
                        "verified_by": "20260913 语音验收回执", "source": "receipt"}])

        result = _run(["--database", self.database, "--apply", "--backup", self.backup,
                       "--confirm", self.confirm])

        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["prompt_changes"][0]["evidence"], "confirmed_record")
        # 未确认的完整提示原样保留。
        self.assertIn(COMPLETE_PROMPT, _stored_prompts(self.database))

    def test_confirmation_without_mid_word_evidence_is_rejected(self):
        # 完整提示 + 一个只多出句号的“原始记录”：没有半个词被切掉，不得修复。
        self._confirm([{"prompt": COMPLETE_PROMPT, "original_prompt": COMPLETE_PROMPT + "."}])
        before = _stored_prompts(self.database)

        with self.assertRaises(ValueError):
            _run(["--database", self.database, "--apply", "--backup", self.backup,
                  "--confirm", self.confirm])

        self.assertEqual(_stored_prompts(self.database), before)
        self.assertFalse(self.backup.exists())

    def test_confirmation_without_any_record_is_rejected(self):
        self._confirm([{"prompt": TRUNCATED_PROMPT}])
        before = _stored_prompts(self.database)

        with self.assertRaises(ValueError):
            _run(["--database", self.database, "--apply", "--backup", self.backup,
                  "--confirm", self.confirm])

        self.assertEqual(_stored_prompts(self.database), before)
        self.assertFalse(self.backup.exists())

    def test_confirmation_for_a_prompt_outside_the_candidates_is_rejected(self):
        self._confirm([{"prompt": "a short complete prompt", "confirmed_truncated": True,
                        "verified_by": "guess"}])
        before = _stored_prompts(self.database)

        with self.assertRaises(ValueError):
            _run(["--database", self.database, "--apply", "--backup", self.backup,
                  "--confirm", self.confirm])

        self.assertEqual(_stored_prompts(self.database), before)
        self.assertFalse(self.backup.exists())


if __name__ == "__main__":
    unittest.main()
