# 阶段预算分离、技能上下文单份化与受控降级恢复

## 背景：一次 125 秒超时

生产日志证据（`var/.chatlogs/2026-09-14/21`，紫悦 `manual_speaker_attr_ziyue_b02669a76c`）：

- `chatjob_1789393954870_7a580687`：`status=timeout`、`latency_ms=124875`、`harness_runs=2`、`error=Autonomous Harness exceeded its total time budget`。
- 探索阶段 18 次工具调用（其中 15 次是读技能：`load_chat_skill`×8 + `read_next_reply_skill`×7），第 9 步单次 LLM 调用 27.5 秒，累计 43 秒超过 40 秒工具上限 → `tool_time_budget_exhausted`。
- 交付 run 在 80 秒窗口里只产出 reasoning（3,855 个 `reasoning-delta`、21,842 字），**`text-delta` 为 0**，无任何正文输出。
- 用户在 6 秒后用同一句话重发（seq 244 → 245）：探索阶段同样超限，但交付 run 28 秒完成，总耗时 72.2 秒成功。配置与技能数几乎一致，差别只是那一次有没有从"想"转到"写"。
- 同期分布：当天紫悦 36 个 job 中位耗时 **67.9 秒**、19 个超过 60 秒、2 个超时，整条链路本来就贴着预算运行。

根因不是工具或网络，而是三处结构问题：探索阶段拿到的是**整个用户可见总时长**；交付重试**原样重发**更大的 prompt；推理档位被运行层**统一覆盖**，调用处改参数不生效。

## 本次修改

### 1. 分离总截止时间、探索截止时间、交付截止时间与错误类型

`Backend/chat_modules/autonomous_normal.py`：

- 新增常量 `NORMAL_TOTAL_BUDGET_SECONDS=180`、`NORMAL_EXPLORATION_LIMIT_SECONDS=40`、`NORMAL_DELIVERY_LIMIT_SECONDS=80`、`NORMAL_RECOVERY_RESERVE_SECONDS=60`；历史名 `NORMAL_TOOL_TIME_LIMIT_SECONDS`/`NORMAL_FINALIZE_TIMEOUT_SECONDS` 保留为别名。
- 新增 `_split_deadlines(now, deadline)`：从**一个**总时限推导四个截止点，恢复片先预留，探索与交付都被夹在 `总时限 − 恢复片` 之内。**总时限从不延长**，因此预留恢复时间不会让用户等更久；总时限本身偏短时，各窗口按比例收缩而不是外扩。
- 探索窗口以 `tool_timeout_seconds` 交给运行层，使"工具到期"与"阶段到期"变成同一时刻，不再是两个会互相打架的计时器。
- 新增 `NormalAgentBudgetExceeded(phase, message)`，`phase ∈ {exploration, delivery, total}`，`code` 形如 `delivery_budget_exceeded`；只有 `total` 的 `retryable` 为 False。
- 新增 `enter_delivery(reason, reply)`：运行层报 `tool_*_budget_exhausted` 与本地计时器到点两条路径，现在走同一个入口，产出同一份交付上下文（已暂存事实、已提交关系合同、已执行操作、带阶段的 reason）。**探索到点不再直接失败，而是转入交付**，不会动到恢复片。

### 2. 减少固定技能的模型往返，并消除上下文重复装载

`Backend/chat_modules/autonomous_prompt_skills.py`、`Prompts.py`：

- `load_chat_skill` 新增 `names` 数组参数，可一次读完 `required_skills_before_reply` 里的整组固定技能；单名调用与 `{"skill", "instructions"}` 返回结构保持不变。固定技能此前是"一项一次往返"。
- 新增不变式：**每个技能正文每份 prompt 只出现一次**。已由 `finalization_skills` 交付的正文不再进入 `verified_observations`；同一技能被读两次也只注入一次。
- 按既定顺序执行：本轮只做"每条必要规则只出现一次"，**未做摘要化**，避免摘要漏掉现有约束。

### 3. 交付阶段独立配置生成预算，并实测落到最终请求

`Backend/chat_modules/harness_runtime.py`、`autonomous_normal.py`：

- 运行层原本无条件 `reasoning_effort = REASONING_EFFORT`，调用处改参数不可能生效。现在改为：探索阶段仍强制 `low`（含仍请求 high 的历史调用方），**交付阶段（`delivery_only` 或 `force_no_tools`）改由独立参数 `delivery_reasoning_effort` 决定**，默认 `DELIVERY_REASONING_EFFORT = None`。调用方无法用 `reasoning_effort` 私自加深检索阶段的推理。
- Agent 层在交付尝试上设置 `delivery_reasoning_effort`，并把 `max_tokens` 夹到 `NORMAL_DELIVERY_MAX_TOKENS = 16384`（原先直接沿用 `model_config` 的 393216）。
- 校验放宽为 `{low, high, None}`，非法值仍然报错。

### 4. 一次受控降级恢复

`Backend/chat_modules/autonomous_normal.py`：

- 新增 `_degraded_prompt_data(prompt_data, rounds=6)`，白名单式构造降级输入。**保留**：当前用户消息与批次、角色档案、环境、当前场景、关系状态与执行合同、`verified_observations`（必要事实）、`previous_attempt.tool_attempts`（已执行操作，逐字保留，重试不可能重复暂存或重复发送）、来源时间、已保存偏好（经 system prompt）。
- **只压缩两处**：对话历史裁成完整的最近若干**轮**（不是最近三条机械截断，承接关系不会断），以及去除本轮不再需要的字段。降级输入带 `degraded_recovery` 说明与 `completion_feedback`，并清空 `required_tools_before_reply`。
- 恢复重试只在**预先预留的恢复片**内运行（`time.monotonic() < recovery_start`），因此重试永远无法延长总时限。

## 测试

- 新增 `Backend/tests/test_normal_stage_budgets.py`（13 项）：四窗口分离与恢复片预留、总时限偏短时收缩而非外扩、三类错误码与 `retryable`、探索到点转入交付、批量读技能一次往返、单份技能不变式（含同一技能读两次）、交付推理预算落到构造参数与 SDK `initialize` payload、调用方不能提高探索档位、非法档位报错、降级恢复保留任务/事实/偏好/已执行操作且只按整轮裁剪。
- 按新契约更新 3 处旧断言（都在断言"探索阶段拿到整个 180 秒"这一旧行为）：
  - `test_image_delivery_budget.py::test_delivery_json_retry_shares_the_original_eighty_second_deadline` → 更名 `test_exploration_and_delivery_windows_are_separate`，期望 `[40, 80, 50]`。
  - `test_autonomous_normal.py::test_format_repairs_and_automatic_retry_share_three_minute_deadline` → 更名 `test_a_spent_total_budget_ends_the_turn_without_recovery`，改用可变时钟并断言 `phase == "total"`；新增两个纯函数窗口测试。
  - `test_normal_automatic_retry.py::test_retry_uses_only_remaining_time` → 期望 `[40, 58]`，并断言两段之和不超过总时限。
- 全量 `Backend/tests`：**1744 passed / 0 failed**。

## 实测：最终请求的真实 payload

`scripts/ops/probe_stage_budget.py`（真实 DSH runtime + 真实模型，抓取 SDK `initialize` 实际 payload）：

| 阶段 | initialize payload | finish_reason |
| --- | --- | --- |
| 探索（默认策略） | `{"provider":"deepseek-official","model":"deepseek-v4-flash","reasoningEffort":"low","maxTokens":8192}` | completed |
| 交付（独立预算） | `{"provider":"deepseek-official","model":"deepseek-v4-flash","maxTokens":16384}` | completed |

交付请求里**不再出现 `reasoningEffort` 键**（SDK 对 `None` 的做法是省略该字段，而不是回落到默认值），证明档位确实不再被运行层统一覆盖，而不只是我们自己的函数签名变了。

## 边界说明

- 省略推理字段不证明关闭推理；最终上线配置保留 low：`NORMAL_DELIVERY_REASONING_EFFORT` 改回 `'low'` 即可，无需改结构。简单 JSON 探针能通过不代表复杂交付一定通过，需要按真实角色场景复核 JSON 完整率与约束命中率。
- 本次未做技能正文摘要化，交付 prompt 里的技能正文体积不变（实测该会话为 18.9k 字符，16 份各出现一次、无重复）。摘要化必须在单份化验证稳定之后再评估。
- `NORMAL_RECOVERY_RESERVE_SECONDS=60` 与总时限 180 秒是配比关系：若总时限改成别的值，恢复片需要一起复核。
- 探索阶段固定 40 秒未调整；本次只保证它不再侵占交付与恢复，不主张 40 秒对"7 项必需技能 + 串行表达子技能链"一定够用。批量读技能可显著减少往返，但真实效果需要按生产会话复测。


## 边界修复与部署验收

- 修复恢复入口：达到 recovery_start 后仍允许一次恢复，仅总截止时间或已恢复才禁止。
- asyncio.wait_for 的实际超时按阶段分流；探索转交付不消耗恢复次数，提前的供应商超时仍普通恢复。
- 短总预算按 40:80:60 等比收缩；去除调用超时的 1 秒外扩。
- 生产串行技能类支持 names 批量调用，逐项经过顺序门禁，不能绕过 reply_review 前置依赖。
- 交付保留 low 推理，独立输出上限 16384；未将省略 SDK 字段当作关闭模型推理的证据。
- 新增 40/80/60 秒边界、恢复再次超时、短预算比例、串行批量门禁、图片恢复传输幂等测试。
- 最终全量：1750 passed，648 warnings，107.80 秒；警告包含既有弃用和异步 SQLite 线程清理警告。
- 真实模型隔离 ASGI /api/chat SSE 验收成功，32.297 秒，记忆记录 1 条；不是生产用户会话性能证明。
- 回滚限制：autonomous_normal.py、autonomous_expression_paths.py 未找到旧发布标记原始哈希副本，使用旧发布提交源码作备用回滚，其余三个文件匹配旧哈希。部署工具会明确记录此例外。
