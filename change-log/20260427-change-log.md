# 2026-04-27 Change Log

## Galgame 分步文档对齐

- `Backend/galgame/seq_prompts/` 为 `step_00`～`step_10`。
- `step_00` 为共用提示词。
- 第 1～9 步主流程为：导演 → 锁分体征 → 环境 / 身体 / 心理 / 第三者 / 角色回复 → 元数据 JSON → 选项。
- 第 10 步为 Galgame 角色短期记忆中性改写，提示词在 `step_10_char_memory_update.py`，调度与注入见 `galgame/memory.py`。
- 调试阶段名使用 `SEQ_STEP_10_*`。

## 普通聊天识图上下文

- 近期用户发图识图结果可经 SQLite 持久化，表为 `normal_image_contexts` / `normal_image_context_state`。
- `normal_planner` 决定是否把识图摘要注入主回复。
- 实现落点包括 `chat_modules/image_context_store.py` 与 `chat_modules/service.py`。

## 历史摘要修正

- 历史摘要中「第 6 / 8 步生成为准」已随流水线扩展更正为第 7 / 9 步，即 `response` / `suggested_options`。
- 分层记忆 API 说明见 `Backend/docs/galgame_tiered_memory_api.md`，步号已与第 10 步记忆更新对齐。
