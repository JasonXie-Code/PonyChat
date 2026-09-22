# 语音风格提示按词边界裁剪（含相关遗留修复）

## 主修复：emotion_prompt 不再被切成半个单词

- `voice_reply.emotion_prompt` 之前按字符硬切 100 个字符，英文指令会留下半个单词（现场存库值是 `...warm and a little hesitant, trailin`），这段残缺指令会被原样当作 instruct 送进 TTS。
- 新增 `Backend/chat_modules/text_limits.py`：`truncate_prompt_text()` 优先在标点（句号、问号、分号、逗号、换行）处断开，没有可用标点时退回整词边界，且只在“窗口后仍是词内字符”时才丢掉末词（`...on the last word.` 会保留 `word`）；中文无标点时仍按字符裁剪。
- 两处同源硬切改用该函数（上限不变）：`Backend/chat_modules/autonomous_delivery.py`（`EMOTION_PROMPT_MAX_CHARS = 100`）与 `Backend/chat_modules/voice_messages_impl/fullwidth_pair.py` 的 `normalize_voice_sentence_entries`（220）。
  - 示例：`...a little hesitant, trailing off at the end.` 由 `...a little hesitant, trailin` 变为 `...warm and a little hesitant`。
- 第三处同类硬切：`Backend/cosyvoice_client.py` 的 `trim_cosyvoice_tts_instruction` 保留“CJK 记 2 单位”的预算语义，实际断开位置改由同一函数决定。

## 相关遗留修复

- `Backend/chat_modules/autonomous_web_images.py` 的两段中文规则散文（subject_type 校验提示与工具参数说明）移入 `Prompts.py` 的 `AUTONOMOUS_WEB_IMAGES_TEXT`，满足“静态提示词单一来源”约束。
- `Backend/tests/test_autonomous_wire_format.py` 的过期断言：交付 JSON 合同已在 `32ca60c` 从常驻系统提示移入按需读取的 `delivery` 技能，断言改为校验该技能文本。
- `Backend/tests/test_new_endpoints.py`、`test_server_files.py`、`test_server_import.py`、`run_migration.py` 在 import 期替换 `sys.stdout/sys.stderr`，会让 pytest 采集后读取捕获输出时报 `I/O operation on closed file`（整目录 `pytest -k ...` 直接崩）。改为 `reconfigure()`。
- `Backend/tests/test_scheduled_followup_prompting.py` 引用了已随 `aacda56` 删除的 `prompt_context_tests.py`，导致整目录采集失败；现按“旧对话管线测试、待按现行 Agent 管线重写”整文件跳过。
- `Backend/Agent-Test/run_agent_voice_probe.py` 补上 `scripts/ops` 搜索路径（`smoke_deployed_harness` 已迁走），文档里的语音验收命令恢复可用。

## 历史数据修复

- 新增 `scripts/ops/repair_truncated_emotion_prompts.py`（默认只读扫描）：把“长度正好落在旧上限且以词内字符结尾”的历史 emotion_prompt 裁到完整词边界。已对生产库执行 `--apply`，修复 5 条语音状态（3 条柔柔消息 + 2 条手工测试会话）。
- 回滚材料：`var/backups/emotion-prompt-repair-20260913/`（修复前整库快照 + 前后对照 JSON）。

## 验证

- 新增 `Backend/tests/test_prompt_text_truncation.py`；相关套件 400 项通过（未计入跳过的 41 项旧管线测试）。
- 改前为红的 `test_autonomous_wire_format`（2 项）与 `test_prompt_source_registry`（1 项）现已通过。
- 真实链路语音验收通过：`Backend/Agent-Test/run_agent_voice_probe.py`（隔离库 + 真实模型 + 本机 Qwen3TTS）8/8 场景 `passed=true`，报告在 `var/voice-acceptance/emotion-prompt-boundary-20260913/report.json`。
- 边界说明：本次只修提示词输入完整性与上述遗留缺陷，不主张音频末尾吞字的原因；音频侧仍按模型偶发处理。

## 复核追加修复（同日）：词边界判定、候选与验收口径

复核指出上面这版仍有三处不成立，本次逐条修掉。

### 1. 词内撇号仍是半个词

- `Please don't shout` 上限 10 旧结果 `Please don`：`_cut_inside_word()` 只看下一个字符是不是字母数字，把撇号当成了安全边界。
- 现在 `_WORD_APOSTROPHES`（直撇号 `'` 与弯撇号 `’`）与字母数字同等算“词的一部分”，`_continues_word()` 判断“下一个字符是词内撇号且其后仍是字母数字”；结果改为 `Please`。
- 完整的词尾撇号保留（`the cats' toys` 上限 9 → `the cats`），落单的尾部撇号清掉（`it's fine now` 上限 3 → `it`）。

### 2. 切在空格后会误删完整末词

- `Speak softly today` 上限 13 旧结果 `Speak`：窗口先 `rstrip()`，却仍用原始 `prefix_chars` 判断是否切在词内，于是把完整的 `softly` 当成半个词丢掉。
- `_ends_inside_word()` 改为按**实际裁剪后的窗口长度**判断，结果恢复 `Speak softly`；真的切进下一个词（上限 14–17）时同样退回 `Speak softly`，只有整段可用前缀本身就是一个词时才退回字符裁剪（`Softly` 上限 4 → `Soft`）。
- 回归测试：`Backend/tests/test_prompt_text_truncation.py` 补撇号切点、尾部撇号、空格边界三组用例，并参数化 `1..len+1` 全部上限检查“结果不得停在词中（除非整段只有一个词）”。

### 3. 历史修复脚本不能靠长度条件自动 apply

- “长度正好 100/220 且以字母数字结尾”既可能被硬切，也可能本来就是完整提示：`Bright, bouncy and fast-paced, ... on the last word` 的前 100 字符就是完整末词，旧条件会把它选中并删掉 `word`。
- `scripts/ops/repair_truncated_emotion_prompts.py` 现在只读扫描输出**候选**（并在输出里写明候选条件不是证据）；`--apply` 必须配 `--confirm`：确认文件里每条要么给 `original_prompt`（原始生成记录，脚本用新增的公开判定 `text_limits.cut_inside_word()` 验证该位置确实切在词中间），要么给 `confirmed_truncated: true` + `verified_by`。
- apply 前逐条校验，任一条不成立就整体不写：确认项必须仍是当前候选、原始记录必须证明切在词中间、修复结果必须是原始记录的前缀；未确认的候选原样留在报告里不修改。
- 顺带修掉 `_snapshot_database()` 未关闭连接导致快照文件被句柄占住（Windows），并在 `drop_incomplete_tail_word()` 文档里写明“前提是已证明被截断，不能当作是否需要修复的判据”。
- 新增 `scripts/ops/test_repair_truncated_emotion_prompts.py`（9 项），含“完整 100 字符提示不得被删掉完整末词”“无证据的确认必须整体拒绝”等反例。
- 生产库只读扫描当前 0 候选；上一轮修改的 5 条与备份一致，本次未改任何生产数据。

### 4. 8/8 报告不能当作最终版本的完整验收

- 新增 `scripts/ops/verify_emotion_prompt_acceptance.py`：不调模型、不写库，把报告里记录的决策提示词按**当前实现**重新裁剪，逐条比对实际交付值，并核对 `source_hashes`（含 `text_limits.py`）是否对应同一版代码。
- 源码哈希按内容比对：记录值与当前文件的“原样字节哈希”或“忽略 CRLF 的内容哈希”任一相符即算同一份代码（`core.autocrlf=true` 重新 checkout 不该让报告失效），真正的代码改动仍会被发现。
- 旧的 8/8 报告经复核**不通过**：`english_voice` 交付值结束于 `...on the last`，当前实现对同一份输入给出 `...on the last word`；报告也没有记录 `text_limits.py` 哈希。这就是“报告至少有一处不对应最终行为”的证据。
- `Backend/Agent-Test/run_agent_voice_probe.py` 接入同一套检查：以已校验 envelope 的决策提示为准（同时留档原始响应、识别兜底提示），每个用例记录 `prompt_check` 并计入 `passed`，`source_hashes` 增加 `text_limits.py`。
- 新报告 `var/voice-acceptance/emotion-prompt-boundary-final-20260913/report.json`：8/8 `passed=true`，其中 `continue_chinese_voice` 真实触发裁剪（决策提示 116 字符 → 交付 84 字符，停在 `volume` 之后）；独立复核 `scripts/ops/verify_emotion_prompt_acceptance.py` exit 0。
- 边界说明不变：仍只覆盖提示词输入完整性，不主张音频末尾吞字的原因。

### 测试

- 相关套件 `Backend/tests scripts/ops`：1631 passed、41 skipped。
- 7 failed / 2 errors 为改动前既有失败（`test_sexual_language_style`×3、`test_unified_vision_model`、`test_agent_recovery`、`test_normal_guest_integration`×2、`test_image_context_store`×2），已用 baseline 对照（`git stash` 去掉本次改动后同批失败）确认与本改动无关；41 skipped 仍是待按现行 Agent 管线重写的旧管线测试。
- `Backend/chat_modules/autonomous_delivery.py` 的 diff 偏大：该文件此前遗留 18 行 CRLF，本次按 `core.autocrlf=true` 归一为 LF，实际改动只有常量提取与默认提示词引用。

### 部署

- 用 `scripts/ops/deploy_scoped_local.py` 部署 4 个文件（`text_limits.py`、`autonomous_delivery.py`、`Agent-Test/run_agent_voice_probe.py`、`tests/test_prompt_text_truncation.py`），release `local-emotion-prompt-boundary-fix-20260913-014042-b2ecb6d4`，revision `b2ecb6d4`，进程 70188 → 63804。
- 回滚材料逐字节对齐 live marker，回执 `unverified_rollback_files` 为空；本机、CN、官网 `deploy_token` 均为新 release。
- 回执与验收证据：`docs/testing/emotion-prompt-boundary-20260913/`（deployment.json、acceptance.json、acceptance-verification.json、旧报告对照及其复核结果、README）。
