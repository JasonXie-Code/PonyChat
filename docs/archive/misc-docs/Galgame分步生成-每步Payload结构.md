# Galgame / 锁分模式 · 分步生成 6 步完整 Payload 结构

> 一比一复刻 `nonstream.py` / `galgame_handler.py` / `request_context.py` 实际实现。
>
> 示例场景：角色小艾（咖啡馆店员）、当前局第 3 轮、分数 55、用户消息「我们一起去看电影吧。」

---

## 一、消息流与历史限制

| 阶段 | 来源 | 说明 |
|------|------|------|
| 历史轮数 | `max_galgame_history_turns = 8` | 最多 8 轮 AI 回复，从 DB 取最近 `8*2` 条消息 |
| 旧轮精简 | `_normalize_galgame_assistant_history` | 最近 2 轮 assistant 保留完整 scene；更早的 assistant 只保留 `scene.time/location/response`，删除 `_strategy_analysis`、`suggested_options` |
| 骨架化 | `_build_slim_payload_for_text_steps` | Steps 1–4 中，**除最后一条 assistant 外**全部骨架化；对应 user 消息合并进骨架后删除 |

---

## 二、公共前置：Steps 1–4 共用

### 2.1 System 消息

**【System 1 - 用户信息】**（来自 `build_user_context`）
```
【系统信息：当前与你对话的用户名叫 {effective_username}，性别是{gender_str}。记忆中提到的就是这位用户，你已经认识他/她。当对方问起自己是谁时，直接用名字 {effective_username} 称呼即可。请在回复和剧情中自然地使用这个名字。】
```

**【System 2 - Galgame 系统模板】**（来自 `build_galgame_lock_system_prompt` / `build_galgame_system_prompt`）
- 含 `# [角色设定]` + 角色 profile
- `# [逻辑]` 当前分数、锁分规则
- `# [评分]`、`# [关键] 格式规则`、人称/视角等
- 分步生成：各文本字段目标字数由**第1步导演** `field_scores` 与服务端映射（如 `generate._score_to_word_limit`）决定，不再使用旧版「场景档位 → 固定字数」函数。

### 2.2 旧轮骨架格式（`_build_slim_payload_for_text_steps`）

```
玩家: {紧邻该 assistant 之前的 user 消息全文}
时间: {scene.time} | 地点: {scene.location} | 关系: {relationship_stage} | 心情: {mood}
角色回复: {scene.response}
```

- 对应那条 user 消息会从列表中**删除**
- 最后一条 assistant 消息**不骨架化**，只做 `_strip_is_refusal` 清洗

---

## 三、Steps 1–4 消息结构

**消息顺序（骨架化后）**：
1. System（用户信息）
2. System（Galgame 模板）
3. Assistant（骨架）… × N
4. Assistant（**完整**，上一轮 JSON 或渲染后内容）
5. User（本回合用户消息 + 分步指令）

**User 消息构成**：原始内容（可含 `地点为【xxx】`、本回合输入、`/no_think` 等）+ `_inject_instruction_to_last_user` 追加的 Step 指令。

---

## 四、各步指令原文（直接来自代码）

### Step 1：环境描写

```
【分步生成 · 第1步/共6步 · 环境描写】
请只生成本回合的**环境描写**（对应 scene.env 字段）。
要求：旁白口吻的客观第三人称（可用她/他/角色名），禁用第一/第二人称代词（我/你），仅写环境与感官事实（光线、气味、温度、声响等），禁止心理活动与对话。约{word_limit}字。
原则：优先捕捉**本回合动作或事件在环境中留下的痕迹与变化**，而非对场景的静态重述。
**禁止**在输出开头加「*（环境描写）*」或类似冗余标签，字段名已说明类型，直接输出正文即可。不要输出JSON格式。
```

### Step 2：身体描写

```
【分步生成 · 第2步/共6步 · 身体描写】
已确定的环境描写如下：
「{prev_env}」

请只生成本回合的**身体状态描写**（对应 scene.body_state 字段）。
要求：旁白口吻的客观第三人称（可用她/他/角色名），禁用第一/第二人称代词（我/你），仅写可观察的身体状态（体温、呼吸、姿态、触感、伤势等），禁止心理活动与对话。**严格控制在150字以内**，超过150字必须精简。
原则：聚焦于**当前动作正在引发的身体反应**，描写应随情节发展而递进，而非对上一轮状态的重复。
**禁止**在输出开头加「*（身体描写）*」或类似冗余标签，直接输出正文即可。不要输出JSON格式。
```

### Step 3：心理描写

```
【分步生成 · 第3步/共6步 · 心理描写】
已确定的环境描写如下：
「{prev_env}」
已确定的身体描写如下：
「{prev_body_state}」

请只生成本回合的**心理描写**（对应 scene.thoughts 字段）。
要求：角色自己的第一人称「我」（我=AI角色），禁止用她/他指代自己，写内心感受、情绪、想法。约{word_limit}字。
原则：紧扣**本回合的具体刺激与新情绪**，展现角色此刻的真实心理动向，而非泛化的情绪状态。
**禁止**在输出开头加「*（心理描写）*」或类似冗余标签，字段名已说明类型，直接输出正文即可。不要输出JSON格式。
```

### Step 4：角色回复

```
【分步生成 · 第4步/共6步 · 角色回复】
已确定的环境描写如下：
「{prev_env}」
已确定的身体描写如下：
「{prev_body_state}」
已确定的心理描写如下：
「{prev_thoughts}」

请只生成本回合的**角色回复**（对应 scene.response 字段）。
要求：第一人称「我」（我=AI角色），动作用**加粗**，神态/细节用*斜体*，对话用"双引号"。不少于40字、建议40-120字。
原则：回复必须**直接回应玩家本轮的具体行为**，体现角色在当前身体状态与心情下的真实反应，而非套用固定话术。
**禁止**在输出开头加「*（角色回复）*」或类似冗余标签，直接输出正文即可。不要输出JSON格式。
```

---

## 五、Steps 1–4 查重与字数

### 5.1 阶段 1：查重 / 拒绝（最多 5 次）

- 每步生成后：拒绝检测（0.8B 小模型 + 关键词）
- 每步生成后：查重（`_check_inline_dedup`）
- 查重阈值：`env 0.72`、`body_state 0.82`、`thoughts 0.70`、`response` 精确匹配视为 1.0
- `body_state` 只与**最近 1 轮**比较（`_BODY_STATE_COMPARE_TURNS = 1`）

### 5.2 阶段 2：查字数（最多 5 次，与查重独立）

- `env` / `thoughts`：`word_limit`（档位值）
- `body_state`：固定 150 字
- `response`：固定 120 字
- 超限触发：`len(clean) > int(char_limit * 1.3)` 时重试

### 5.3 重试时

- 去重重试：`temperature` 提升、`presence_penalty` / `frequency_penalty`、随机 `seed`、反重复指令
- 字数重试：字数缩减指令、新 payload、`enable_thinking=False`、`response_format` 移除
- 拒绝重试：`_strip_no_think_from_payload` 移除 `/no_think`，让模型可用思考链理解指令

---

## 六、Step 5：元数据 JSON

### 6.1 Payload 结构

- **无 System 消息**
- **仅 1 条 User 消息**，顺序：
  1. `玩家消息: {user_last_msg}`
  2. `【上一轮状态（供参考，保持连续性）】` + 上一轮摘要
  3. `当前好感度分数: {current_score}`
  4. Step 5 指令（含 4 段文本 + JSON 要求）

### 6.2 上一轮状态字段（`_build_minimal_payload_for_json_step`）

```
时间: ...
地点: ...
关系阶段: ...
心情: ...
角色姿态: ...
玩家姿态: ...
角色种族: ...
玩家种族: ...
角色服装: ...
玩家服装: ...
上一轮分数: ...
事件标记(上一轮): {"first_handhold": true, ...}  # 若有
```

### 6.3 Step 5 指令核心（`_SEQ_JSON_STEP_INSTRUCTION`）

```
【分步生成 · 第5步/共6步 · 元数据JSON】
场景文本已由前4步生成完毕，内容如下：
--- 环境描写(env) ---
{prev_env}
--- 身体描写(body_state) ---
{prev_body_state}
--- 心理描写(thoughts) ---
{prev_thoughts}
--- 角色回复(response) ---
{prev_response}
--- 以上文本将由系统自动注入JSON，你**不需要**输出这四个字段 ---

当前好感度分数: {current_score}

请根据以上场景内容，输出一个JSON对象，只包含以下字段：
1. score（对象，含 current/change/status，current 基于当前分数 {current_score} 进行加减）
2. scene（对象，**只含** time/location/third_party_dialogue 三个字段，不要写 env/body_state/thoughts/response）
3. relationship_stage（中文短词，≤6字）
4. mood（中文短词，≤6字）
5. character_pose（≤10字）
6. player_pose（≤10字）
7. character_race
8. player_race
9. character_outfit（无衣物填「赤裸」）
10. player_outfit
11. memory_tags（数组，每项必须为简体中文短词，≤8字，禁止英文）
12. event_flags（对象，必须根据本回合场景内容逐项判断，不要照搬上一轮的值！…）
13. score_delta_reason（一句话+具体分值）

输出合法JSON，第一个键必须是 score。不要使用 ```json 代码块。
不要输出 _strategy_analysis 或 suggested_options 字段（选项由第6步单独生成）。
```

---

## 七、Step 6：玩家选项

### 7.1 Payload 结构

- **无 System 消息**
- **无历史消息**
- **仅 1 条 User 消息**：`content` 初始为空，`_inject_instruction_to_last_user` 注入 Step 6 指令

### 7.2 Step 6 指令（`_SEQ_OPTIONS_STEP_INSTRUCTION`）

- 含 `env`、`body_state`、`response`（**不含 thoughts**）
- 角色回复中的「我」会被替换为「角色」，避免与选项中「我」= 玩家混淆

```
【分步生成 · 第6步/共6步 · 玩家选项】
根据以下本轮场景，生成5个玩家（'我'）下一步的行动/对话选项。

--- 环境描写 ---
{prev_env}

--- 角色的身体状态（第三人称） ---
{prev_body_state}

--- 角色对玩家说的话/做的动作 ---
{prev_response}   # 此处「我」已替换为「角色」

【label 写法规范】
视角：'我'=玩家，'你'=角色。label 必须用第一人称「我」开头，描述玩家的具体动作或话语。
action 类型：… dialogue 类型：…
禁止写成抽象短语或标题，必须是完整的、有画面感的短句。
label 严格≤20字（超过20字判定失败），对话内容用「」包裹，禁止使用ASCII双引号"。

输出一个JSON对象，只含一个字段 suggested_options（数组）：
· 首元素：{"_options_perspective": "⚠️ 以下选项视角切换：'我'=玩家，'你'=角色。选项描述玩家的下一步行动！"}
· 之后5个选项，每个含 label / type / tone 三个字段
  type："dialogue" 或 "action"
  tone：简短中文情绪词（如"温柔"/"调皮"/"害羞"/"主动"/"关切"）

只输出JSON对象，不要有任何说明文字。
```

---

## 八、对比小结

| 步骤   | 角色设定 | 对话历史  | 本回四段文本                        | 用户消息 |
| ------ | -------- | --------- | ----------------------------------- | -------- |
| Step 1 | ✅ 完整  | ✅ 骨架化 | —                                   | ✅       |
| Step 2 | ✅ 完整  | ✅ 骨架化 | env                                 | ✅       |
| Step 3 | ✅ 完整  | ✅ 骨架化 | env, body_state                     | ✅       |
| Step 4 | ✅ 完整  | ✅ 骨架化 | env, body_state, thoughts           | ✅       |
| Step 5 | ❌       | ❌ 仅摘要 | env, body_state, thoughts, response | ✅       |
| Step 6 | ❌       | ❌        | env, body_state, response           | ❌       |

---

## 九、输出与组装

| 步骤   | 模型输出                       | 用途                          |
| ------ | ------------------------------ | ----------------------------- |
| Step 1 | 纯文本（env）                  | 写入 `scene.env`              |
| Step 2 | 纯文本（body_state）           | 写入 `scene.body_state`       |
| Step 3 | 纯文本（thoughts）             | 写入 `scene.thoughts`         |
| Step 4 | 纯文本（response）             | 写入 `scene.response`         |
| Step 5 | JSON（score / scene 元数据等） | 组装最终 JSON，不含 scene 文本 |
| Step 6 | JSON（suggested_options）      | 注入到 Step 5 的 JSON 中      |

---

## 十、其他说明

- **`/no_think`**：本地 `append_no_think` 模型会在最后 user 消息末尾追加 `/no_think`；去重重试时会 `_strip_no_think_from_payload` 移除
- **`max_tokens`**：Steps 1–4 每步 1024；Step 5 为 4096；Step 6 为 1024
- **schema 重试**：`json_incomplete_schema` 时只重试 Step 5 和 Step 6，保留 Steps 1–4 结果
