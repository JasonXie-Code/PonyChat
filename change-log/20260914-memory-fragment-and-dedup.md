# 记忆碎片限长、二字重复检测、记忆不作表达依据（含柔柔记忆清理）

## 背景：柔柔为什么会一直说“方才”

- 生产日志（`var/.chatlogs`）证据：柔柔 157 条最终回复里出现 27 次“方才”、命中 23 轮（约 30%），同期其他角色 76 条回复 0 次；碧琪 193 条 0 次，紫悦 122 条 1 次。
- 时间线：首次出现在 2026-09-13 04:31:25，此前 81 轮、4739 个含柔柔的日志文件里 0 次。首次出处是模型自己的推理草稿（`reasoning-delta` 先吐出“方才”，再写进最终正文），人设里没有这个词，用户也没用过。
- 扩散路径：进入可见历史（某轮请求里 119 条助手历史有 16 条含“方才”）、进入长期记忆（77 个柔柔记忆日志含该词），此后每轮回灌，形成自我模仿。
- 没被拦住的根因：`reply_repetition_context.py` 只统计长度 ≥4 字的重复片段，“方才”只有 2 字且嵌在长分词里，永远不会进入 `repeated_spans`。

## 本次修改

### 1. 记忆碎片限长 40 字

- `Backend/memory/extractor.py`：提取提示词由 `15~80字` 改为 `15~40字`，并写明“碎片只保留事实、主体和关键细节”“内容多时拆成多条短碎片”。
- 新增 `MAX_FRAGMENT_CHARS = 40` 与 `limit_fragment_content()`：写入前按标点边界（。；！？…，、）收束，边界会砍掉一半以上时退回按字数硬截，保证入库碎片不超过 40 字；触发收束时打 INFO 日志。
- 现状参考（清理前）：柔柔 187 条层 0 碎片中位数 37 字、最大 71 字，68 条超过 40 字。

### 2. 去重纳入 2 字重复

- `Backend/chat_modules/reply_repetition_context.py`：最小统计片段由 4 字改为 2 字（`len(span) < 2` 与 `range(2, …)`），单字词（“嗯/哈”）统计行为不变。
- 首版上线后按真实历史复核，发现展示质量不合格：16 个展示位里 15 条是二字片段、≥4 字 0 条，长片段（`去洗一洗`、`留在里面`）被挤出，且出现 `才那`（出自“刚才那张”）、`么样`（出自“怎么样”）这类跨词碎片。同轮收敛如下：
  - **分句边界过滤**：二字片段只在分句首尾出现过才成为候选（`_is_observable_span`，token 边界即标点边界）。习惯用词、副词和连接语通常落在分句首尾，跨词碎片永远落在词中间，无需中文分词词典即可区分；三字以上片段不受影响。未引入 jieba 等分词依赖（venv 内无任何分词库，加依赖会改动生产环境与锁文件）。
  - **配额预留**：`DISPLAY_LIMIT = 24`、`MAX_SHORT_SPANS = 6`。1~2 字片段最多占 6 位（含单字语气词，避免 `唔` 这类短语气词被长片段挤掉），先为它们预留名额、再用长片段填满剩余位，两类都不会被对方整体挤出。
- 同一段真实历史的对照（柔柔 seq 700–724，25 条）：

  | | 上一版 | 本版 |
  | --- | --- | --- |
  | 候选片段 | 170 | 95 |
  | 展示条数 | 16（短 15 / 长 1） | 23（短 6 / 长 17） |
  | `方才` | 有 | 有（第 2 位，4 轮 5 次） |
  | 跨词碎片 | `才那`、`么样`、`的那`、`在这` | 已移除 |
  | 长片段 | 0~1 条 | `从你身上`、`一节一节`、`去洗一洗`、`留在里面` 等 17 条 |
  | JSON 长度 | 1021 字符 | 1668 字符 |

- 边界：三字片段仍可能跨词（`留在里` 与 `留在里面` 会同时出现）；边界过滤只覆盖二字，这是刻意取舍。

### 3. 记忆正文不再作为表达方式依据

- `Backend/chat_modules/request_context.py`：普通对话记忆注入块前置新增
  `【记忆只作事实依据，不作为表达方式依据】…不得把记忆正文的用词、句式、比喻、语气、口癖或叙述方式当作表达范本，也不因为某个词在记忆里出现过就在回复中继续使用它。`
- `Backend/scheduled_followup_impl/followup_delivery.py`：主动续接的跨会话记忆块加入同一条规则。
- `Backend/chat_modules/Prompts.py`：`memory` 技能新增第 18 条；`reply_deduplication` 第 2 条由“历史…不作为照抄语言风格的范本”扩展为“记忆正文同理，只提供事实依据，不作为表达方式依据”。

### 4. 把“展示重复用词”变成明确要求

复核要求侧发现缺口：`reply_repetition_context` 已经会列出二字习惯用词，但 `reply_deduplication` 规则 2 的动作清单是“意象域、情绪所依赖的身体动作、开场句式、称呼、拟音和收尾含义”，**不含用词**；唯一涉及“词”的删除要求是“已反复作为起头的无实义语气词直接省略”，而“方才”是句首/句中的实义时间副词；同时“统计只作定位证据，不是禁词表”和“换近义词、换同类部位或调整标点不算跳出同一模板”两条还在把模型往“不必改”的方向推。邻近条款分别只管称呼（规则 4）、情绪结论与陪伴承诺（规则 6）、拟音（规则 7）、身体部位（规则 8）；`reply_expression` 第 7 条禁的是“刻意”口癖，不要求消除自然形成的口癖。这与观测一致：09-14 00:30 用户明确要求“不要使用方才，使用刚才”，00:32 那条生效，01:49 复发，此后 20 轮里又出现 6 轮 10 次。

- `Backend/chat_modules/Prompts.py` 的 `reply_deduplication` 规则 2 两处改动（不新增编号规则）：
  - 检查清单补入“习惯用词”：`…开场句式、称呼、拟音、收尾含义和习惯用词；`
  - 在“换近义词、换同类部位或调整标点不算跳出同一模板。”之后补边界说明：习惯用词是例外，某个词在近期连续多轮反复出现并已成口癖时，本轮按当前表达需要改用自然说法、常见同义词或直接省略；命中统计的习惯用词没有新的表达作用时不再沿用；这属于消除口癖，不算用同义改写掩盖同一模板。
- 保留“统计只作定位证据，不是禁词表”“专有名称可以正常重复”两条既有边界（不永久禁用某个词、不机械替换专名）；未使用“例如/比如/示例”，未引用“第N条”（`test_prompt_source_registry`、`test_prompt_mechanical_audit` 会拦）。

## 测试

- 新增 `Backend/tests/test_memory_fragment_length.py`（11 项）：限长常量、短文本不动、标点边界收束、无边界硬截、`41/60/200/4000` 字参数化不超限、提示词改为 15~40 字、`do_extract` 端到端把超长内容收束后入库、正常内容原样入库。
- 新增 `Backend/tests/test_memory_not_expression_source.py`（4 项）：四个注入/技能位置都带该规则，且说明排在记忆正文之前。
- `Backend/tests/test_reply_repetition_context.py` 增补 6 项：二字习惯词跨轮计数、不同上下文里的二字词不被更长片段吞掉、二字与长片段并存、跨词碎片（`才那`）不进展示而更长片段保留、短片段配额上限、长片段泛滥时短习惯词仍有预留位。
- 新增 `scripts/ops/test_clear_character_memories.py`（6 项）：干跑不删、确认串不符拒绝、只删目标角色、保留关系/场景/调度状态、备份含完整行快照与 manifest、审核游标仅在显式要求时推进。
- `Backend/tests/test_reply_deduplication.py` 新增 1 项：检查清单含“习惯用词”、动作与边界措辞齐全、措辞单一归属 `reply_deduplication`、“不是禁词表”与“专有名称可以正常重复”未被移除。
- 全量 `Backend/tests`：首版 **1686 passed / 25 failed / 41 skipped / 2 errors**；用 `git stash` 去掉本次改动跑同一套为 **1668 passed / 同样的 25 failed 与 2 errors**（本次新增 18 项通过）。去重收敛版 **1691 passed / 25 failed / 41 skipped / 2 errors**，失败集合与基线逐项一致。25 项失败与 2 项 error 均为改动前既有失败，例如 `test_prompt_source_registry` 的两项：HEAD 的 `speech` 技能文本里本来就有“例如”，`autonomous_images.py:10` 本来就有静态规则散文，两个文件都不是本次改动对象（前者 diff 未触及，后者工作区与 HEAD 完全一致）。
- 真实模型验收：`scripts/ops/smoke_deployed_harness.py`（隔离库 + 真实 `/api/chat` SSE）首版 `{"passed": true, "status": 200, "elapsed_seconds": 30.14}`、收敛版 `32.297`、要求补齐版 `31.093`；报告 `docs/testing/memory-expression-scope-20260914/` 下的 `smoke.json`、`smoke-repeat-span-quota.json`、`smoke-lexical-habit-requirement.json`。首次以合成用户名登录被 403 拒绝，改用文档给出的 `PONYCHAT_SMOKE_USERNAME=System` 后通过。

## 部署

- `scripts/ops/deploy_scoped_local.py`，首版 release `local-memory-expression-scope-20260914-184207-729715ff`、revision `729715ff`，进程 33364 → 由 supervisor 重启；回执 `docs/testing/memory-expression-scope-20260914/deployment.json`。
- 去重收敛版 release `local-repeat-span-quota-20260914-193916-3f47eff8`、revision `3f47eff8`，进程 44936 → 由 supervisor 重启；`unverified_rollback_files: []`（两个受控文件按 CRLF 逐字节对齐），回执 `deployment-repeat-span-quota.json`。
- 要求补齐版 release `local-lexical-habit-requirement-20260914-194554-fcb91c2a`、revision `fcb91c2a`，进程 45228 → 由 supervisor 重启；`unverified_rollback_files: []`，回执 `deployment-lexical-habit-requirement.json`。
- 三次部署后本机、CN（39.101.74.217）、官网（www.ponychat.org）三处 `/api/health` 的 `deploy_token` 均为当次 release。
- 首版 `unverified_rollback_files` 为 `extractor.py`、`followup_delivery.py`：上一次部署的 marker 记录的是**混合换行**的原始字节，与 `git show` 的 LF blob、或整文件 CRLF 都不逐字节相等。回滚内容是这两份文件改动前的完整提交版本，只是换行形态无法与旧 marker 逐字节对齐；其余 4 个受控文件逐字节对齐（Prompts.py、reply_repetition_context.py 用 LF，request_context.py 用 CRLF）。

## 柔柔记忆清理（Jason / fluttershy__u_1）

- 新增 `scripts/ops/clear_character_memories.py`：默认只读；`--apply` 必须配 `--confirm Jason/fluttershy__u_1`；校验角色确属该用户；先导出行快照与整库快照（sqlite backup API）再单事务删除。
- 范围（记忆内容）：`character_memories`、`agent_memory_heads`、`agent_memory_versions`、`agent_memory_entries`、`normal_chat_memory`、`agent_memory_notes`、`agent_memory_importance_reviews`。
- 按用户选择保留（关系/场景/调度状态）：`agent_memory_state`、`agent_memory_reviews`、`agent_memory_attempts`、`agent_memory_participants`、`agent_memory_group_turns`、`normal_agent_scene_cards`、`normal_scene_state`、`relationship_controls`、`relationship_presence_states`。
- 实际删除：`character_memories` 243（187 碎片 + 28 日 + 15 周 + 7 月 + 6 年）、`agent_memory_heads` 86、`agent_memory_versions` 194，其余为 0；删除后上述记忆表均为 0 行，保留表全部 unchanged。
- 另两个名为“柔柔”的角色（`fluttershy__u_1_2`、`1771241700568_xwyi0u` 即“柔柔-NSFW”）本来就没有任何记忆数据，本次未涉及。
- 时点选择：执行前发现 `agent_memory_state` 有一次审核正在运行（lease 有效、`revision 112558 > reviewed_revision 110398`），先等该次审核结束（`reviewed_revision` 自行推进到 112559、pending=False）再删除，避免删完立刻被这次审核重建；因此本次没有改动审核游标。
- 备份：`var/backups/character-memory-clear-20260914-184453/`（`deleted-rows.json` 完整行快照、`ponychat.db` 整库快照、`manifest.json` 计数与哈希）。

## 边界说明

- 只保证“入库碎片 ≤40 字”“二字重复会被统计出来”“要求侧明确写了要对命中用词采取动作”，不主张模型一定不再使用“方才”：真实生成是否停止用语癖，需要后续按 `scripts/ops/probe_fluttershy_repeated_history.py` 一类真实模型探针复核。
- 要求补齐版验证到“运行中的进程确实把新措辞发给了模型”：第三版 smoke 报告的链路里 `reply_deduplication` 出现 11 次，`习惯用词是例外`／`收尾含义和习惯用词`／`没有新的表达作用时不再沿用` 各命中 3 处；磁盘 `Prompts.py` 哈希与部署标记记录的哈希一致（`b8207fda…`）。
- 去重的边界过滤只覆盖二字片段，三字片段仍可能跨词（`留在里` 与 `留在里面` 会同时出现）；`我不`、`这儿`、`看我` 这类分句边界上的高频搭配仍会占用短片段配额，判定权留给技能文本（“统计只作定位证据，不是禁词表”）。
- 清理只覆盖 `fluttershy__u_1` 的记忆内容；`agent_memory_reviews`/`attempts` 的 tool_trace 审计记录按“只删记忆内容”的约定保留，它们不参与提示词注入。
- 清理后新会话仍会正常产生新记忆（实测 19:19 重置后写入 1 条 `relationship_page`），这是设计行为；碎片层 `character_memories` 仍为 0。
