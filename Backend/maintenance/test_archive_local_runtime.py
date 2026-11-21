"""Protect knowledge data while recognizing actual runtime log files."""
import unittest

from archive_local_runtime import log_file


class LogClassificationTests(unittest.TestCase):
    def test_knowledge_pages_and_jsonl_datasets_are_not_logs(self):
        for path in [
            "Backend/data/mlp/pages/Dishwater Slog.txt",
            "Backend/data/mlp/pages/Fictional chronology.txt",
            "Backend/data/mlp/pages/Log cabin.txt",
            "Backend/data/mlp/tags.jsonl",
            "Backend/data/mlp/tags_test.jsonl",
            "var/codex/dataset.jsonl",
        ]:
            with self.subTest(path=path):
                self.assertFalse(log_file(path))

    def test_actual_log_files_remain_classified(self):
        for path in [
            "var/.chatlogs/2026-09-09/request.json",
            "var/ChatMonitor/cache/response.json",
            "var/local-stack/supervisor.log",
            "var/bottom_obstruction_log2.txt",
            "var/codex-current-reply-notify-log.txt",
            "Backend/data/mlp/fetch_portrait_candidates_log.jsonl",
            "Backend/data/mlp/fetch_portraits_log.jsonl",
            "Backend/database/daily_summary_clean_changes_20260524_094604.jsonl",
            "Backend/database/admin_uptime_samples.json",
        ]:
            with self.subTest(path=path):
                self.assertTrue(log_file(path))


if __name__ == "__main__":
    unittest.main()
