# Galgame / 锁分：分层记忆 — 前后端契约说明

本文说明「长期 / 短期 / 对话历史」分层记忆在 **存档结构**、**摘要接口** 与 **对话详情** 上的约定，便于客户端与 Web 对齐。

## 1. 存档中的字段（`load_galgame_state` / 同步 payload）

游戏与锁分共用同一套键名（与数据库列对应，API 层为 camelCase）：

| 键名 | 类型 | 含义 |
|------|------|------|
| `charMemory` / `char_memory` | 对象 | `entries`：当前保留的逐轮「客观转写」列表（裁剪后通常最多 8 条） |
| `shortTermMemory` | 字符串 | 短期摘要正文 |
| `shortTermMemoryStartTurn` | 整数，可空 | 短期摘要覆盖的起始轮次 |
| `shortTermMemoryCutoffTurn` | 整数，可空 | 短期摘要覆盖的结束轮次 |
| `longTermMemory` | 字符串 | 长期摘要正文 |
| `longTermMemoryCutoffTurn` | 整数，可空 | 长期摘要覆盖的最高轮次（展示为「第0–X轮」） |

说明：

- 旧的 `contextSummary` / `contextSummaryCutoff*` 列仍可能存在于数据库中，**游戏链路不再依赖**；消息列表不再按该摘要做截断或插入占位。
- 重置进度（`POST /api/galgame/reset`）后，上述分层字段与 `char_memory` 一并回到空/默认。

## 2. 自动折叠（服务端）

每局结束后，在角色记忆更新步骤（**第 10 步**，与 `galgame/memory.py` 中 `SEQ_STEP_10_*`、提示词 `seq_prompts/step_10_char_memory_update.py` 一致；主剧情分步为第 1～9 步）中：当 `char_memory.entries` 条数 **大于 15** 时，会尝试生成分层摘要并将 `entries` 裁剪为最近 **8** 条。若 LLM 失败，**不裁剪**，下轮可重试。

常量（与后端 `galgame/memory.py` 一致）：

- 触发上限：16 条（`KEEP_VERBATIM_MAX + 1`）
- 裁剪后保留：8 条（`KEEP_VERBATIM_AFTER_TRIM`）
- 短期窗口上限：16 轮（`SHORT_TERM_MAX_TURNS`）

## 3. `POST /conversation/summarize_context`

请求体仍为 `SummarizeContextRequest`：`mode` 为 `galgame` 或 `galgame_lock` 时走分层折叠逻辑。

### 3.1 成功响应（`status: success`）

与普通对话不同，游戏/锁分 **不再返回** `total_tokens` / `limit_tokens` / `summary_length`，改为：

```json
{
  "status": "success",
  "short_term_length": 123,
  "long_term_length": 456,
  "verbatim_turns": 8
}
```

- `short_term_length` / `long_term_length`：当前落库后的短期、长期摘要**字符长度**（便于 UI 展示或日志）。
- `verbatim_turns`：折叠后 `char_memory.entries` 的**条数**（不是游戏内「第 N 轮」的 N）。

### 3.2 跳过或失败（HTTP 200 + JSON）

| `reason` | 含义 |
|----------|------|
| `not_enough_turns` | `entries` 条数 **小于 9**（`KEEP_VERBATIM_AFTER_TRIM + 1`），无法折叠 |
| `tiered_fold_failed` | 折叠逻辑执行失败（常见：LLM 无返回、超时等），库表未更新 |

示例：

```json
{ "skipped": true, "reason": "not_enough_turns" }
```

### 3.3 错误（HTTP 非 200）

例如用户不存在、写库失败等，仍为 `HTTPException`，与普通接口一致。

## 4. 对话详情与 `usage`（Galgame）

拉取 Galgame/锁分对话详情时，`usage` 仍由 `estimate_galgame_context_usage` 估算；其中 **摘要占位部分** 使用 `longTermMemory` 与 `shortTermMemory` 拼接后的文本近似，**不再使用** `contextSummary` 与 cutoff 字段。客户端若仅展示百分比，无需区分来源。

## 5. 后台自动摘要调度

`memory/auto_summarizer.py` **不再**对 Galgame/锁分按 token 阈值写 `contextSummary`。长对话压缩完全由 **第 10 步**（角色记忆更新链路中的分层折叠）与手动 `summarize_context` 负责。

---

若后续接口增加「只读返回分层字段」的独立字段列表，建议与本文 1 节键名保持一致，避免再引入一套命名。
