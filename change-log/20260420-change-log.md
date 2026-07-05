# 2026-04-20 Change Log

## Backend 目录整理

- Galgame 逻辑迁入 `Backend/galgame/`。
- 迁移模块包括 `handler`、`constants`、`vitals`、`utils`、`retry`、`history`、`seq_prompts` 等。
- 调用方统一使用 `from ..galgame import ...`。
- 记忆与 RAG 迁入 `Backend/memory/`，包括 `auto_summarizer`、`consolidator`、`extractor`、`scheduler`、`mlp_rag`。
- `migrate_b64_to_cdn.py` 移至 `Backend/scripts/`。
