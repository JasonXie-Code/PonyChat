# 2026-04-28 Change Log

## Galgame / 锁分模式去重

- 将第 7 步 `response` 的防复读逻辑改为通用机制，不再针对固定角色、动作或话题写死规则。
- 在最终执行指令末尾追加自动抽取的防复读硬约束，来源包括：
  - 本轮已生成的 `body_state`
  - 最近两轮 `response`
  - 最近 5 轮中重复出现的表达指纹
- 防复读项统一使用通用指纹与短片段，包括：
  - `动作:对象+动作`
  - `台词开头`
  - `台词收尾`
  - 高频短语片段
- 目标是在不增加重试、不增加额外 LLM 调用的前提下，减少动作模板、句式节奏和跨字段复述。

## Step 10 角色记忆

- 为 Step 10 记忆更新增加本地兜底逻辑。
- 当模型空返、返回非有效 JSON、或解析失败时，后端会从本轮已生成的 `scene`、`player_action`、`relationship_stage`、`mood` 等信息组装最小中性记忆，避免整轮记忆丢失。
- 正常情况下仍优先使用模型生成的高质量 `memory_entry` 和 `repetition_profile`。

## 测试与诊断

- replay 测试结果新增 `memory_raw` 字段，方便后续定位 Step 10 失败原因。
- 对完整分步链路进行多轮 replay 测试，观察第 7 步 `response` 与历史、本轮 `body_state` 的重复命中情况。
- 修复测试中发现的 `台词收尾` 指纹未纳入最终硬约束的问题。

## 涉及文件

- `Backend/galgame/generate.py`
- `Backend/galgame/memory.py`
- `Backend/scripts/replay_yunbao_repetition_full_chain.py`
