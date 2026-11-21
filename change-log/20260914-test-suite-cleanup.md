# 测试套件历史失败清理（25 failed / 2 errors → 0）

## 背景

前一轮工作（记忆碎片限长 / 二字去重 / 记忆不作表达依据）在跑全量 `Backend/tests` 时暴露出
**改动前就存在**的 25 项 failed 与 2 项 errors。用 `git stash` 去掉当次改动跑同一套确认失败集合
逐项一致后，本次把它们全部清掉。分类与处理如下。

## 1. 提示词卫生（影响生产提示词）

- `Prompts.speech`：删掉内嵌示例「例如“唔～”或“呣～”」，改为「优先用“～”标记实际延长的音节」。
  该技能文本里出现“例如”，违反项目自己的“技能文本不得内嵌示例”约束
  （`test_prompt_source_registry`、`test_sound_mark_style` 各自因此变红）。
- `autonomous_images.py` 的 `CURRENT_IMAGE_GUIDANCE`（602 字中文规则散文）迁入
  `Prompts.AUTONOMOUS_IMAGES_TEXT['current_image_guidance']`；运行时代码只保留字典投影
  `CURRENT_IMAGE_GUIDANCE = AUTONOMOUS_IMAGES_TEXT['current_image_guidance']`，
  `autonomous_service.py` 的调用点不变。修掉“运行时代码不得持有静态规则散文”那条违规
  （原先报在 `autonomous_images.py:10`）。
- 未引入新依赖，未改变注入内容：迁移前后取值逐字符相同（602 字）。

## 2. 过期断言（规则搬家或文案重写后测试没跟上）

| 测试 | 原断言 | 现在断言的位置 |
| --- | --- | --- |
| `test_agent_speech_followup_policy` | `'近期连续几轮及本轮'`、`'拟音仍须符合角色当下意愿与已确认边界'` 在 `speech` | 两条规则现在都归 `reply_deduplication` 规则 7；`speech` 只保留指针，测试同时断言指针与归属 |
| `test_natural_curiosity_prompt`（2 项） | `'不代写用户反应'`、`'所有非speech片段固定从当前角色的第一人称视角呈现'` 在 `reply_expression` | 前者归 `interaction_reply` 规则 1，后者是 `reply_perspective` 首句；`'用户明确要求重复的动作可以自然延续'` 归 `interaction_reply` 规则 3 |
| `test_autonomous_web_search`（2 项） | `'角色自身固有设定不受季数限制'`、`'后续新发生的关系、任职和事件不得写成当前角色已经经历'` | mlp_reference 重写后的当前句子（固有背景定义、以及“后续获得或改变的能力、形态、身份、关系、任职及事件仍受时间线限制…”） |
| `test_sexual_language_style`（3 项） | 中文档位标签 `性相关语言风格：默认/委婉/直白`、`聊天中要求切换委婉、默认、直白` | 现行契约：注入 `【当前偏好配置】\nsexual_language_style: <enum>`（未设置时不注入但仍解析为 `default`），三档含义在 `preferences` 技能规则 12–15，聊天文本无法携带该键且技能禁止执行聊天内切换 |
| `test_normal_request_context`（1 项，断言在 impl） | writer anchor（`NORMAL_MODE_WRITER_ANCHOR_PROMPT`，已随 `4f98f8d` 删除） | `ROLEPLAY_ANCHOR_PROMPT` 只属于非 normal 模式（`companion` 有、`normal` 无），normal 模式框架由 `autonomous_normal.SYSTEM` 的 `COGNITION_CORE` 承担 |
| `test_unified_vision_model`（1 项） | 清单里所有模型源都必须只有 `deepseek-flash` | 清单合法地多出本地模型源（`models/local.json` 的 `qwen3.5-4b-local`，有独立测试 `test_local_model_switch.py`）；改为断言只载入统一主模型源与本地模型源、且主模型源内全部是 `active_model`，测试名同步改为 `test_manifest_only_loads_sanctioned_model_sources` |

## 3. 集成测试缺串行技能读取（11 项）

`test_autonomous_upgrade_integration`×3、`test_normal_reply_batch_integration`×6、`test_normal_guest_integration`×2
原先统一报 `ExpressionReadIncomplete: Expression read contract incomplete: reply_expression`：假 transport
没有按 `next_required()` 顺序读完表达技能。

- 新增 `Backend/tests/expression_skill_contract.py`：`read_expression_contract(tools, paths=…)` 循环调用
  `read_next_reply_skill`，`selection_required` 时 `select_reply_paths`，`complete` 时返回；上限 16 步，
  工具为空（格式修复轮 `max_tool_calls=0`）时直接返回。
- 关键细节：技能读取返回的是 `with_progress(load(...))`，**没有 `status` 键**（只有 `skill`/`next_required`/`complete`），
  只按 `status` 两分支判断会误报。
- `test_normal_guest_integration` 另有两处非契约问题：缺少 `instant_messaging` 读取（会话模式必读），
  以及 `model_result()` 生成的合成信封缺少 `scene_patch` 且 `language='auto'`（导致格式修复重试时工具为空而 KeyError）。

## 4. 装配与加载修复

- `test_agent_recovery`：`harness_live_input.py` 使用相对导入，原先用
  `spec_from_file_location` 当顶层模块 exec 会报 `attempted relative import with no known parent package`；
  改为包内导入（SDK 在该模块内按需导入，测试仍在其后注入桩）。
- `test_image_context_store`：2 项 error 的真因不是超时，而是 **async autouse fixture 无插件处理**
  （仓库没有 pytest 配置文件，`pytest-asyncio` 处于 strict 模式）。改为本目录既有写法：
  同步测试函数内 `asyncio.run()`，并在同一事件循环里 `await get_database().close()`。

## 5. `test_normal_guest_integration` 的 live-input 断言按批次契约改写

该文件的两处 live-input 断言仍是 **ReplyBatch 批次合并之前**的设计。`b2ce31d`（"Merge normal inputs until
first reply and acknowledge receipt immediately"）之后，生成中的新消息由 `ReplyBatch.admit()` 并入同一批次：
持久化 → 追加到 `template.messages` → 写入 `known` → `revision += 1` → 取消当前 attempt 并重跑；
`LiveTurn.pending`/`join_turn`/`defer_speaker_change` 在该路径不再使用（插桩显示 3 次 admit、`pending` 恒为 0、
`join_turn` 从未被调用）。改写如下，意图逐条保留：

| 原断言 | 新断言 | 保留的意图 |
| --- | --- | --- |
| `active_turn(...).routing_waiting` | 同一批次对象 `is` 原回合、`not delivered`、`'at' in known`、`revision >= 2`，且两次响应的 accepted `job_id` 都等于该批次 job_id | 生成中到达的 @ 消息被并入正在进行的这一回合（同一载体、仍由该回合持有） |
| `wait_for_inbox()` 轮询 `.pending` | `wait_for_merge()` 轮询 `'supplement' in known`，再断言 `{"ordinary","supplement"} <= known`、`revision >= 2` | 补充消息确实进入同一回合 |
| runner 内 `take_pending()`→`prepare_input()`→`try_seal()` | 断言 `'supplement' in channel.known`、重跑 attempt 的 `current_user_batch` 含两条消息、`not channel.pending`、`not channel.delivered` | 补充消息进入同一回合的模型输入；队列没有残留、仍由该回合持有（对应 try_seal 的原意） |

其余断言全部未动：群聊窗口看不到主聊天私密内容、临时群聊见闻只对参与者可读、handoff 是真实的第二个角色请求、
送达说话人、数据库行、Agent Memory 写入 episode。

另有一处脚手架修正：合成模型原先两轮返回逐字相同的台词，触发回复级重复保护
（`runtime.py` 约 L539-544：与上一条 assistant 消息前 100 字相同且在 10 秒内则 `should_add_assistant=False`），
导致 `ai_msg_ids` 为空 → 交互模式场景动作（`$reply` 证据）无法提交 →
`RuntimeError('Scene action requires a saved reply')` → 整个回复事务回滚（实测 `save_status success=False`）。
现改为每轮不同措辞，与真实模型一致。

## 6. 仍未处理 / 需产品决策

- **`compact` 是死参数**：`personal_preferences.py:26` 的 `personal_preferences_prompt(..., compact=False)`
  函数体从不读取 `compact`，实测 `compact=True/False` 输出逐字节相同（均 60 字）。但四处生产调用点
  传 `compact=True`：`autonomous_service.py:87`、`opening_agent.py:49`、`chat_request.py:231`、
  `request_context.py:411`；其中 `autonomous_service.py:87-88` 与 `opening_agent.py:49-50`
  **同时算 compact 与非 compact 两份**，期望得到长短两版，现在拿到的是同一份 → 同一提示词里偏好文本重复注入。
  `test_autonomous_compact_context.py` 因此成为空断言（`'例如' not in …` 恒真）。
- **无 assistant 段落时交互模式条目会让整笔回复失败**：合成模型返回逐字重复台词时，重复保护清空
  `_paragraphs`/`ai_msg_ids`，`interaction_modes.attach_mode` 的 `$reply` 证据无从提交，
  `commit_scene` 抛 `RuntimeError('Scene action requires a saved reply')`，整笔事务回滚。
  零文本/零气泡的静默分支（`normal_nonstream_sse.py:156-173`，`persist_user_only=True`）走同一条提交路径，
  据代码分析同样可能触发（未实测）。待决策：无 assistant 段落时，交互模式条目应当丢弃、还是改用用户消息作证据，
  而不是让整笔回复失败。
- `request_context.py:1008` 的日志仍写 `+ 普通模式输出习惯`，但 normal 模式已不再注入该风格提示
  （`4f98f8d` 删除）；`character.py:288` 注释仍引用已删除的 `NORMAL_MODE_OUTPUT_STYLE`（仅日志/注释漂移）。
- `test_autonomous_web_search.py` 单独运行会 `ModuleNotFoundError`：它依赖同级测试模块注册的合成包
  `prompt_skills_under_test`（仓库无 `conftest.py`）；全量运行时不受影响。
- `Backend/tests/test_scheduled_followup_prompting.py` 整文件 skip 的 **41 项**：它们测的是
  `aacda56` 已删除的旧对话管线（`_coerce_planner`、`_planner_policy_block`、`_voice_reply_system`、
  `_PLANNER_SYSTEM` 等，其辅助模块 `prompt_context_tests.py` 同时被删），只能按现行 Agent 管线重写或整文件移除，
  属另一项决策，本次未动。
- 批次合并会取消并重跑进行中的 attempt，被丢弃那次 attempt 的模型开销不再回收（`b2ce31d` 的既定取舍，
  现已被测试固定为 `generated == ["twilight","pinkie","twilight"]`）。

## 7. 三项产品决策的落地（用户确认后实施）

### 7.1 `compact` 死参数 + 偏好块重复注入

- `personal_preferences.py`：删除从未被读取的 `compact` 参数；三处调用点
  （`autonomous_service.py`、`opening_agent.py`、`request_context.py`）不再传它。
  `autonomous_service.py` 与 `opening_agent.py` 原先各算两份期望长短两版，现改为算一次、
  两份槽位共用同一字符串（系统提示词一份 + `preferences` 技能目录一份）。
- `autonomous_prompt_skills.py`：技能目录拼接偏好正文时，若 `preference_guidance` 与已保存值
  指向同一段文本，不再在"当前已保存偏好："后面重复拼一遍；两者不同（预留的长短两版设计）时两段都保留。
- 实测后果消除：同一段偏好文本在一次请求里的出现次数由 **3**（系统提示词 1 + 技能目录 2）降为 **2**
  （系统提示词 1 + 技能目录 1）。
- 测试：`test_autonomous_compact_context.py` 的空断言（`'例如' not in …` 恒真）替换为
  「技能目录里偏好块只出现一次」与「guidance 与保存值不同时两段都保留」两项有效断言；
  `test_personal_preferences_priority.py` 桩函数里断言 `compact is True` 的一行随参数删除；
  `test_sexual_language_style.py` 去掉两处 `compact=True`。

### 7.2 无 assistant 段落时丢弃交互模式条目

- `autonomous_scene_state.py::commit_scene`：补丁里某个字段的 `source_message_ids` 含 `$reply`、
  而本轮没有保存任何 assistant 段落时，**丢弃该字段并保留原值**，不再抛
  `RuntimeError('Scene action requires a saved reply')` 让整笔回复事务回滚。其它不依赖 `$reply`
  的字段照常提交；证据不可用、证据变化等原有完整性校验不变。
- 触发场景：回复级重复保护清空段落，或零文本/零气泡静默交付（`normal_nonstream_sse.py`
  的 `persist_user_only=True` 分支）。字段下一轮按新原文重新判定。
- 测试：`test_autonomous_scene_state.py::test_invalid_evidence_and_reply_without_delivery_rejected`
  由"断言抛错"改为"断言该字段保留原值、同补丁其它字段照常提交"。

### 7.3 删除旧对话管线的 41 项 skip

- `Backend/tests/test_scheduled_followup_prompting.py`（兼容加载器 + 整文件 `pytest.mark.skip`）
  与 `Backend/tests/test_scheduled_followup_prompting_impl/`（`delivery_prompt_tests.py`，41 项）
  整文件删除：被测的 `normal_planner` 系列函数已在 `aacda56` 随旧对话管线删除，
  其辅助模块 `prompt_context_tests.py` 同时被删，函数不存在、无法只改断言。
- 删除后仓库不再有该文件的 skip 占位；历史报告里的引用（`docs/testing/*/REPORT.md`、
  `scripts/ops/write_reliability_report.py` 的复盘段落）作为当时记录保留未改。
- 全量 `Backend/tests`：**1730 passed / 0 failed / 0 errors / 0 skipped**（此前为 1728 passed / 41 skipped）。

## 测试与部署

- 全量 `Backend/tests`：**改动前 25 failed / 2 errors → 现在 1728 passed / 41 skipped / 0 failed / 0 errors**
  （0:01:48）。41 skipped 全部来自上面那一个待重写的旧管线文件。
- 部署：release `local-test-suite-cleanup-20260914-200741-e5dfcb80`，revision `e5dfcb80`，
  受控文件 `Prompts.py`、`autonomous_images.py`；本机/CN/官网三处 `deploy_token` 一致。
  `unverified_rollback_files` 只含 `autonomous_images.py`：上一次部署的 marker 记录的是**混合换行**的原始字节，
  回滚内容仍是改动前的完整提交版本，只是无法与旧 marker 逐字节对齐。
- 真实模型验收：`smoke-test-suite-cleanup.json` `{"passed": true, "status": 200, "elapsed_seconds": 27.532}`；
  同一份载荷里可核实：迁移后的图片规则已实际注入（出现 1 次），
  `speech` 的旧示例不再出现，且上一轮的三条用词要求仍在（各 2 次）。
- 回执与验收：`docs/testing/memory-expression-scope-20260914/deployment-test-suite-cleanup.json`、
  `smoke-test-suite-cleanup.json`。
