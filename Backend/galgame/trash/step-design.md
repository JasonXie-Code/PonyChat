# Galgame 分步生成设计示例

## 核心结论

第 1 步导演是唯一读取完整资料的步骤：完整角色设定、长期/短期记忆、最近历史、后端权威状态、原始锁分体征、玩家本轮行为都只进入导演。

第 2-6 步是字段执行器，不再直接读取完整角色设定、长记忆、原始锁分提示。它们只执行达到后端阈值的字段，并消费导演下发给该字段的指令。除**固定禁令 + 字数 + `step_directives`** 外，后端须注入**权威状态摘要**（来自上一轮已落库的结构化元数据/请求内 game state 快照）——如双方种族、性别、位置、服装、心情、关系阶段、当前姿势/动作、可选 `memory_tags`、以及与本步相关的 `event_flags` 等——作为最小事实锚点，避免执行器在无人设全文时「凭空造设定」。

三层控制分开理解：

- 导演语义阈值：`field_scores >= 30` 表示导演认为该字段值得生成，因此应填写 `step_directives`。
- 后端执行阈值：当前 `_FIELD_SCORE_ACTIVE_MIN = 40`，用于抵消模型打分偏高，只实际调用更必要的字段。
- 字数控制：`field_scores` 同时决定该字段的生成篇幅，后端通过 `_score_to_word_limit()` 将 `env/body_state/thoughts/response` 按 `**分数×1.6`**（再 clamp 到 20–200 字）换算为 `word_limit` 并注入各步 prompt；`third_party` 为分数字本身。`step_directives` 只描述内容任务，导演不直接输出字数。
- **禁令分层**：与步种绑定的、长期稳定的禁止项（例如 body_state 禁止台词/问句/写玩家身体、thoughts 禁止可观察动作等）**不由导演逐轮输出**，由后端在对应步（`seq_prompts/step_0N_*.py` 等）**固定注入**。导演在 `step_directives` 中**只写可变部分**，推荐键：`focus`（本字段叙事焦点）、`must_include`（须体现的关键点/短语，可空数组）。若某轮需要**额外**限制，可选用 `forbidden_extra`（短数组，仅本轮特化），**不要**重复粘贴各步的通用 `forbidden` 全表。
- `**scene.env` 与 `scene.body_state` 人称**（与 `[step_02_text_env.py](./step_02_text_env.py)`、`[step_03_text_body_state.py](./step_03_text_body_state.py)` 一致）：两笔均为**客观旁白/镜头式描写**——**第三人称**（她/他/角色名/玩家/来访者等），**禁止第一人称**（我、我们）与**第二人称**（你、你的、你们）。`env` 只写环境事实；`body_state` 只写**角色本人**可观察的体态，同样不得写「我……」。涉及玩家时 env 用「玩家」等第三称谓，**禁止**写玩家身体细部到 body 里（见 step_03 边界）。
- `**scene.thoughts` 人称**（与 `[step_04_text_thoughts.py](./step_04_text_thoughts.py)` 一致）：与上两行相反，本步为**主视角角色纯内心**，默认 **第一人称**（我……），**禁止**第三人称代写。不得写成对白、不得复述 env/body 的可见动作长镜。

## 示例前提

玩家本轮输入：

```text
可是我不会飞啊，不然我们比赛跑步吧
```

前置权威状态假设：

```text
当前时间：午后
当前地点：小马谷草坪
角色：云宝，雌性飞马
玩家：Jason，人类雄性
关系：高度亲密
上轮状态：云宝站在玩家前方半米，前蹄指向天空；玩家站在喷泉旁
体征：明显便意，未在卫生间
情绪：愉悦、好奇、好胜
同场：苹果嘉儿在跑道外侧卸农货小车，物理在场，可接一句嘴（供 third_party）
```

## 第 1 步：Director

本例用于演示 **第 2～6 步五类文本字段全部出现** 的走法：`env` / `body_state` / `thoughts` / `third_party` / `response` 的 `field_scores` 均 **≥ 40**（其中 `third_party` 的字数上限在代码里为**分数字本身**，不乘 1.6）。导演对五者均生成 `step_directives`（仅 `focus` / `must_include` / 可选 `forbidden_extra`），并在 `environment_facts` 中**写清第三者同场依据**（见 step_01 中 third_party 档位说明）。

**本例 `field_scores` 与三层逻辑对照**（`word_limit` 由后端 `[_score_to_word_limit](../generate.py)` 换算，导演 JSON 不写字数）：


| 字段          | 分数  | 写 directive（>=30） | 实际调模型（>=40） | 若执行则 word_limit（`env`/`body`/`thoughts`/`response` 为分×1.6；`third_party` 为**分数字**） |
| ----------- | --- | ----------------- | ----------- | --------------------------------------------------------------------------------- |
| env         | 45  | 是                 | 是           | 72（45×1.6）                                                                        |
| body_state  | 50  | 是                 | 是           | 80（50×1.6）                                                                        |
| thoughts    | 45  | 是                 | 是           | 72（45×1.6）                                                                        |
| response    | 70  | 是                 | 是           | 112（70×1.6）                                                                       |
| third_party | 45  | 是                 | 是           | 45（分数字，clamp 20–200）                                                              |


```json
{
  "player_action_parse": {
    "action_type": "verbal_dialogue",
    "note": "玩家说明自己不会飞，并提出改为地面跑步比赛，既化解飞行限制，也继续接受云宝的竞争邀约。"
  },
  "vital_reasons": {
    "curiosity": "跑步挑战带来新鲜感",
    "pleasure": "玩家愿意继续比赛",
    "stamina": "准备进行短距离奔跑",
    "nervousness": "便意造成短暂分心"
  },
  "vital_events": {
    "char_mood": {
      "curiosity": 5,
      "pleasure": 2,
      "nervousness": 2
    },
    "char_vitals": {
      "stamina": -2
    }
  },
  "field_scores": {
    "env": 45,
    "body_state": 50,
    "thoughts": 45,
    "response": 70,
    "third_party": 45
  },
  "character_core_reaction": "云宝被玩家的跑步提议激起好胜心，觉得即使不用飞也能证明自己速度够强，同时不想让便意影响她在玩家面前的气势。",
  "environment_facts": "午后小马谷草坪，喷泉与开阔草地仍在；一阵风卷起草屑、水雾从喷泉脚下掠过跑道边缘；**跑道外**停着农货小车，**苹果嘉儿**正在卸货，抬头看见两人要赛跑，是本轮场上明确在场的第三者。无换大场景。",
  "character_inner_arc": "她把玩家不会飞这件事迅速转化成新的比赛规则，心里觉得地面赛跑也足够有趣，但身体的不适让她意识到必须稍微忍住；又瞥见熟人在旁，**不想**在嘉儿和玩家面前出洋相。",
  "third_party_hint": "苹果嘉儿在跑道外卸货、看见两人要跑，**一句**路过后排的打趣提醒，不抢主戏。",
  "decided_events": [
    "云宝后退两步，前蹄交替踏地做出起跑姿态",
    "尾巴兴奋地左右甩动，翅膀微微张开又收拢",
    "明显便意让她腹下短暂绷紧"
  ],
  "response_type_scores": {
    "statement": 20,
    "silence": 5,
    "question": 25,
    "exclamation": 80,
    "initiative": 65,
    "plead": 0,
    "deflect": 35,
    "consent": 10,
    "tender": 5,
    "refuse": 0
  },
  "step_directives": {
    "env": {
      "focus": "风、水雾、草皮与远处小车及卸货动线，点出同场有第三者**在场边**的客观空间关系。",
      "must_include": ["午后光线", "喷泉或草屑/水雾", "跑道外农货与卸货", "不描写角色身体动作（动作留给 body_state）"]
    },
    "body_state": {
      "focus": "云宝进入跑步准备姿态，同时因明显便意短暂忍耐。",
      "must_include": ["后退两步", "前蹄交替踏地", "尾巴兴奋甩动", "翅膀张开又收拢", "腹下短暂绷紧"]
    },
    "thoughts": {
      "focus": "以第一人称写：把不会飞改成地面赛的好胜，与便意、以及「有熟人在看」的包袱如何在心里打架。",
      "must_include": ["跑步也要赢", "便意", "被看见的微妙压力"]
    },
    "third_party": {
      "focus": "苹果嘉儿**一句**打趣，带一点乡土口吻，不展开长篇。",
      "must_include": ["提醒别绊倒或注意安全", "不替角色抢台词"]
    },
    "response": {
      "focus": "接受跑步比赛，并围绕玩家不会飞这一点做轻微调侃。",
      "must_include": ["接受跑步比赛", "轻微调侃不会飞", "表现好胜心"]
    }
  }
}
```

（上例中未展示 `forbidden_extra`；若某轮需禁止提具体事物，可由导演加 `"forbidden_extra": ["烤摊", "点单"]` 等短列表。）各步**通用**禁令见后端 `step_02`～`step_06` 的固定提示词，不占用导演 token。

`response_type_scores` 负责回复的语气/收束形态，本例中 `exclamation=80`，后端会据此选出最终发言模式。`step_directives.response` 只负责**可变内容任务**（`focus` / `must_include`），`tone` 由 `response_type_scores` 与第 6 步规则共同约束，不另设 `speech_style` 键。五段并跑时，前序步（env、body、thoughts、third_party）已生成，第 6 步仍只负责**主视角角色台词**。

## 第 2 步：env

后端看到：

```json
{ "env": 45 }
```

达到导演语义下限与执行阈值，**调用第 2 步**。`env=45` 对应 `word_limit ≈ 72`（45×1.6）。输入为 **后端固定 env 禁令**（不写**角色**具名动作与台词，见 step_02）+ **权威状态中的 time/location 锚点** + **导演 `environment_facts`**（本轮物理事实，env 从中提取客观环境后果，排除角色动作部分）+ 导演 `step_directives.env` 的 `focus`/`must_include`；本步只产出**客观环境**（风、光、声、空间、**未点名**的场边车与人声等），与身体/心理/第三者的**具名**台词分离。**全段须客观第三人称旁白，禁止我/你。**

```text
【后端固定】只写 scene.env；不得写可归属角色的对白与具体肢体动作（见 step_02）。人称：客观第三人称，禁止第一/第二人称代词（我/你/我们/你们），与 step_02 同。
【后端注入】字数上限约 72 字；time/location 与权威状态一致。
【导演·environment_facts】本轮物理事实（env 只提取其中的客观空间/感官后果，禁止写入角色动作部分）。
【导演可变】focus / must_include：风、水雾、草屑、喷泉、跑道外农货与卸货**声响**、场边空间关系（不展开成 body_state）。
```

理想 `scene.env`（示意，一行写入 JSON 时转义自洽即可）：

```text
scene.env = "午后阳光把草皮晒得发白，喷泉溅起的水雾随风扫过跑道边线；一阵风卷起细草屑，跑道外停着绑好麻袋的农货小车，卸货声与轮轴轻响从场边传来，与喷泉的哗哗水声叠在一起。"
```

## 第 3 步：body_state

后端看到：

```json
{ "body_state": 50 }
```

达到执行阈值，调用第 3 步。`body_state=50` 对应 `word_limit ≈ 80`（50×1.6）。输入不再包含完整角色卡、长记忆、原始锁分大段，由 **后端固定 body_state 禁令** + **权威状态** + 字数 + 导演指令拼装（顺序可在实现中微调，但五类信息缺一不可）。`**body_state` 与第 2 步相同：可观察的第三人称旁白，禁止我/你**（不得写成「我往后撤……我下腹……」）；用「她/他/云宝」作叙述主语。与第 4 步「我」式内心在人称上**刻意切分**。

`**decided_events` 与 `step_directives.body_state.must_include` 的分层**：`decided_events` 是导演对「本轮角色确定要执行的物理动作列表」的权威决策（强制体现、禁止删减）；`step_directives.body_state` 是导演对「如何渲染这些动作」的附加提示（`focus` 给出叙事基调，`must_include` 给出关键词/短语）。两者同时注入 body_state，不互斥。若 `must_include` 与 `decided_events` 重叠，以 `decided_events` 为物理基准，`must_include` 作渲染补充。

```text
【后端固定，每轮相同】字段规则：只写 scene.body_state，禁止台词、心理、写玩家身体、禁止我/你；连贯第三人称旁白（见 step_03 模块）。
【后端注入】字数上限约 80 字（由 field_scores 换算）。
【导演·decided_events】⚠️ 本轮已决定发生的物理事件，必须体现，禁止删减（体现方式由 body_state 自行散文化）。
【后端注入·权威状态快照】来源为上一轮 assistant 已写入的结构化元数据 / 当前请求侧状态，仅作**事实锚点**（可写成键值对或短列表，不贴长文记忆）：

  relationship_stage, mood
  character_pose, player_pose, character_position, player_position
  character_action, player_action
  character_gender, player_gender, character_race, player_race
  character_outfit, player_outfit
  可选：memory_tags（短标签，非 narrative 记忆块）
  可选：event_flags 中与身体/安全边界相关的子集（只读、防越界，不要求模型复述 flags）

  与第 7 步元数据同构的示例（值随轮次变化，此处仅为形状示意）：

{
  "relationship_stage": "高度亲密",
  "mood": "兴奋",
  "character_pose": "起跑姿态",
  "player_pose": "站立",
  "character_position": "草坪前方",
  "player_position": "喷泉旁",
  "character_action": "准备赛跑",
  "player_action": "提出跑步",
  "character_gender": "雌性",
  "player_gender": "雄性",
  "character_race": "飞马",
  "player_race": "人类",
  "character_outfit": "赤裸",
  "player_outfit": "赤裸",
  "memory_tags": ["跑步挑战"],
  "event_flags": { "first_kiss": true, "physical_intimacy": true }
}
  （`event_flags` 可按本步需要只注入相关子集，不必全量 20+ 键。）

【导演可变】
focus：云宝进入跑步准备姿态，同时因明显便意短暂忍耐。
must_include：后退两步、前蹄交替踏地、尾巴兴奋甩动、翅膀张开又收拢、腹下短暂绷紧。
（若导演提供了 forbidden_extra，则追加在固定禁令之后。）
```

理想输出（第三人称、无「我/你」）：

```text
云宝向后退出两大步，前蹄在草皮上急促地交替点踏，尾巴在身后左右兴奋甩动，双翅一扬又一收。小腹坠感顶上来，她腹下肌肉一绷一松，将那点不适忍成不发声的细紧。
```

程序校验应挡掉这类错误：

```text
我往后撤两大步，前蹄在草皮上点踏。  ← 第一人称，须重写为第三人称
“跑步？哈！你这是在给我送分啊！”
```

因前者违反人称规则，后者含引号与台词。

（若用「我」写 body 与 step_04 的「我」式 thoughts 会打架，也违背 step_03 的固定禁令。）

## 第 4 步：thoughts

后端看到：

```json
{ "thoughts": 45 }
```

达到阈值，**调用第 4 步**。`thoughts=45` 对应 `word_limit ≈ 72`。输入为 **后端固定 thoughts 禁令** + 上游已产出的 `scene.env` / `scene.body_state` 提要（**禁止**重复可观察动作/环境长镜，须在禁令规定的「只写心理」上延伸）+ **导演 `character_inner_arc`**（叙事者第三人称总结，作情绪方向背景）+ 导演 `step_directives.thoughts`（第一人称执行指令）+ **玩家本轮行为摘要**（`player_action_parse.note`，让内心知道在对什么事做反应）+ 权威状态中的 mood/relationship 锚点（短引）。

**人称与体裁**：`scene.thoughts` 为**主视角角色内心**，须用 **第一人称**（我……），与 `step_04` 中「多数角色为口语化『我』式内心、禁止突换旁白她/他」一致；不把内心写成第 6 步的台词、不把身体动作再描一遍。

`**character_inner_arc` 与 `step_directives.thoughts` 的关系**：`inner_arc` 是导演叙事者视角的方向总结（「她把……转化成……」），作为情绪背景；`step_directives.thoughts.focus` 是对内心独白「如何写」的可变指令（「以第一人称写……」）。两者语义互补：前者给情绪背景，后者给写作角度。thoughts 步同时消费两者，不冲突。

可能输出（第一人称、约压在上限内）：

```text
不飞就改地上比，我才不把这当成认输。肚子里坠得烦，可一瞥坡边有嘉儿在，熟人盯着我，我不能先怂。发令一响我就冲，先把气势抢到手再说。
```

```text
scene.thoughts = "不飞就改地上比，我才不把这当成认输。肚子里坠得烦，可一瞥坡边有嘉儿在，熟人盯着我，我不能先怂。发令一响我就冲，先把气势抢到手再说。"
```

## 第 5 步：third_party

后端看到：

```json
{ "third_party": 45 }
```

`third_party` 达到**语义门槛（≥30）与执行门槛（≥40）**，**调用第 5 步**。`word_limit` 为**分数字** 45 字内（不乘 1.6，见 `generate._score_to_word_limit`）。输入含 **固定格式要求**（如 `NPC 名：台词`）+ `**third_party_hint`**（说明是谁、为何此刻开口，来自导演顶层字段）+ 导演 `step_directives.third_party`（如何写这一句）+ 与 env 一致的**在场事实**（苹果嘉儿确在 `environment_facts` 中已落地）。

注意：`third_party_hint` 与 `step_directives.third_party` 是**两个信号、同时注入**：前者提供「谁/为何开口」，后者提供「如何写这一句」；缺一则第 5 步缺乏 NPC 身份定位或写法方向。

理想输出（示意）：

```text
苹果嘉儿：喂，你俩要跑也给跑道边边留点神！别被麻袋线绊一跤，我可不当裁判啊。
```

```text
scene.third_party_dialogue = "苹果嘉儿：喂，你俩要跑也给跑道边边留点神！别被麻袋线绊一跤，我可不当裁判啊。"
```

## 第 6 步：response

后端看到：

```json
{ "response": 70 }
```

调用第 6 步。`response=70` 对应 `word_limit ≈ 112`（70×1.6）。输入为 **后端固定 response 规则**、字数、导演 `focus`/`must_include`、`response_type_scores` 选型；**须**在提示中给前序步骤的**极短提要**，避免 response 重述已有内容，且须包含**角色声音摘要**（`char_voice`，由权威状态或系统层维护）以保证台词口吻。

**角色声音（`char_voice`）**：完整角色卡被剥离后，response 步需要一个**精简的语气与口吻说明**（例：「云宝：好胜、嘴硬、不直说喜欢、常用反将调侃」），来自角色卡提炼后存入权威状态或系统 prompt 顶层。这是剥离角色卡后 response 口吻一致的关键保障，**不可省略**。

`**thoughts` 未执行时的 response 情绪来源**：若 `thoughts` 分数未达 40（本步未生成），response 不能从 `scene.thoughts` 中获取情绪背景——此时以导演 `character_inner_arc`（第三人称情绪总结）代替，作为 response 情绪基调的隐性输入。

```text
【后端固定，每轮相同】第 6 步字段级禁令与格式要求（见 step_06 模块）：必须有中文对白、控制字数、不重述 body_state 动作等。
【后端注入】字数上限约 112 字（由 field_scores 换算）。
【后端注入·角色声音】char_voice 短摘要，保持台词口吻一致（若 thoughts 未跑，改由 character_inner_arc 补情绪背景）。
【后端注入·前序提要】body_state 要点（避免 response 重述动作）+ third_party 要点（避免与 NPC 台词冲突或重复）。
【导演可变】
focus：接受跑步比赛，并围绕玩家不会飞这一点做轻微调侃。
must_include：接受跑步比赛、轻微调侃不会飞、表现好胜心。
发言模式：exclamation（来自 response_type_scores，不替代 must_include 的内容义务）。
（若需本轮特化，导演可提供 forbidden_extra。）
```

理想输出：

```text
云宝扬起下巴，眼里亮起胜负欲：“跑步也行！别以为换到地面我就会输，Jason，等会儿可别拿不会飞当借口！”
```

## 第 7 步：metadata_json

第 7 步整理最终 JSON，不负责剧情创作。

输入：

```text
第2步 env = 午后风、水雾、草屑、喷泉、场外农货…
第3步 body_state = 云宝起跑姿态与便意…
第4步 thoughts = 好胜与腹坠、嘉儿在场压力…
第5步 third_party = 苹果嘉儿一句…
第6步 response = 云宝扬起下巴…
上一轮状态
当前分数
导演预算后的体征值
```

输出示例（`scene` 五段均有内容）：

```json
{
  "score": {
    "current": 100,
    "change": 0,
    "status": "win"
  },
  "score_delta_reason": "玩家提出跑步比赛并延续互动，角色积极接受，场边 NPC 有轻量接话，关系维持稳定。（本轮+0分）",
  "scene": {
    "time": "午后",
    "location": "小马谷草坪",
    "env": "午后阳光把草皮晒得发白，喷泉溅起的水雾随风扫过跑道边线；一阵风卷起细草屑，跑道外停着绑好麻袋的农货小车，卸货声与轮轴轻响从场边传来，与喷泉的哗哗水声叠在一起。",
    "thoughts": "不飞就改地上比，我才不把这当成认输。肚子里坠得烦，可一瞥坡边有嘉儿在，熟人盯着我，我不能先怂。发令一响我就冲，先把气势抢到手再说。",
    "body_state": "云宝向后退出两大步，前蹄在草皮上急促地交替点踏，尾巴在身后左右兴奋甩动，双翅一扬又一收。小腹坠感顶上来，她腹下肌肉一绷一松，将那点不适忍成不发声的细紧。",
    "third_party_dialogue": "苹果嘉儿：喂，你俩要跑也给跑道边边留点神！别被麻袋线绊一跤，我可不当裁判啊。",
    "response": "云宝扬起下巴，眼里亮起胜负欲：“跑步也行！别以为换到地面我就会输，Jason，等会儿可别拿不会飞当借口！”"
  },
  "relationship_stage": "高度亲密",
  "mood": "兴奋",
  "character_pose": "起跑姿态",
  "player_pose": "站立",
  "character_position": "草坪前方",
  "player_position": "喷泉旁",
  "character_action": "准备赛跑",
  "player_action": "提出跑步",
  "character_gender": "雌性",
  "player_gender": "雄性",
  "character_race": "飞马",
  "player_race": "人类",
  "character_outfit": "赤裸",
  "player_outfit": "赤裸",
  "memory_tags": ["跑步挑战"],
  "event_flags": {
    "first_handhold": true,
    "confessed": false,
    "first_hug": true,
    "first_kiss": true,
    "physical_intimacy": true,
    "exclusive_confirmed": false,
    "trust_broken": false,
    "relationship_public": false,
    "captivity_established": false,
    "coercion_explicit": false,
    "violence_inflicted": false,
    "torture_inflicted": false,
    "bloodshed_occurred": false,
    "injury_persistent": false,
    "corpse_present": false,
    "escape_attempted": false
  },
  "char_vitals": {
    "stamina": 98
  },
  "char_mood": {
    "curiosity": 55,
    "pleasure": 72,
    "nervousness": 22
  },
  "organ_fill": {
    "rectum": 45
  }
}
```

第 7 步的关键是：`scene.time/location` 与姿态、位置、动作字段成为下一轮权威状态来源；**本全字段例** 中 `scene.env` / `scene.thoughts` / `scene.body_state` / `scene.third_party_dialogue` / `scene.response` **均有正文**。

## 第 8 步：options

第 8 步生成玩家选项。它只读本轮结果和 metadata，不读完整角色设定（若场边有 NPC，可在选项中自然出现，非必填）。

输出示例：

```json
{
  "suggested_options": [
    {"_options_perspective": "玩家视角"},
    {"label": "摆好起跑姿势", "type": "action", "tone": "期待"},
    {"label": "朝嘉儿挥蹄应一声", "type": "action", "tone": "轻松"},
    {"label": "调侃她别摔倒", "type": "dialogue", "tone": "玩笑"},
    {"label": "提议先去洗手间", "type": "dialogue", "tone": "关心"},
    {"label": "请求让三秒", "type": "dialogue", "tone": "示弱"},
    {"label": "直接开始倒数", "type": "action", "tone": "果断"}
  ]
}
```

后端把 options 注入第 7 步 JSON。

## 第 9 步：memory

第 9 步在最终回复保存后异步执行。它不是剧情生成器，只做中性转写。

输入来自最终 assistant raw JSON：

```text
玩家本轮：可是我不会飞啊，不然我们比赛跑步吧
env 提要：风、水雾、喷泉、场外农货
thoughts 提要：换规则也要赢、便意、嘉儿在场
third_party 提要：嘉儿场边提醒别绊
response 提要：云宝接受跑步、调侃不会飞
time/location：后端从最终 JSON 注入
```

输出示例：

```json
{
  "turn": 61,
  "player_action": "玩家表示自己不会飞，并提议将比赛改为跑步。",
  "event": "午后小马谷草坪，喷泉与场边风声中，云宝以起跑姿态回应，苹果嘉儿在跑道外接一句安全打趣；云宝在好胜与身体不适的交织下，接受地面赛跑并以调侃向玩家下战书。",
  "time": "午后",
  "location": "小马谷草坪",
  "relationship": "高度亲密",
  "emotional_note": "兴奋"
}
```

## 最终链路

```text
第1步导演读全量资料，输出 field_scores + step_directives + response_type_scores；
第2-6步只执行达到后端阈值的字段：每步先拼后端固定禁令、权威状态与字数，再拼导演可变指令（上文「全字段例」中五步均跑）；
第7步整理状态（scene 五段可全非空）；
第8步生成选项；
第9步写记忆。
```

关键约束：

- `step_directives` 的生成阈值按导演语义：`field_scores >= 30`；内容以 `**focus` + `must_include**` 为主，**不**在导演 JSON 中重复各步通用 `forbidden` 长表；通用禁止项由对应 `step_0N_text_*.py` 注入。
- 字段实际模型调用阈值按后端校准：当前为 `field_scores >= 40`。
- 同一份 `field_scores` 在「执行了」的字段上，同时决定该步 `word_limit`（`env/body_state/thoughts/response` 为分×1.6 并 clamp 到 20–200；`third_party` 为分数字本身，见 `generate._score_to_word_limit`）。
- `response_type_scores` 是回复语气/收束形态控制器；`step_directives.response` 只描述**可变**内容任务（`focus` / `must_include`）。
- `scene.env` / `scene.body_state`：客观**第三人称**，禁止**我/你**（与 step_02、step_03 一致）。
- `scene.thoughts`：**第一人称**内心（默认「我」），禁止第三人称代写，详见 `step_04_text_thoughts.py`；与 2/3 步在人称上必须区分。
- `**environment_facts` 注入 env**：导演顶层的 `environment_facts` 须注入第 2 步，env 从中提取客观环境后果，排除角色动作部分。
- `**decided_events` 注入 body_state**：`decided_events` 为物理基准（强制体现），`step_directives.body_state` 为渲染补充，两者同时注入第 3 步，不互斥。
- `**player_action_parse.note` 注入 thoughts**：第 4 步须知道玩家做了什么，才能产生内心反应，不可仅靠 env/body 提要。
- `**character_inner_arc` 注入 thoughts 与 response**：第 4 步消费作情绪背景；thoughts 未执行时，response 以 `inner_arc` 代替 `scene.thoughts` 作情绪来源。
- `**third_party_hint` + `step_directives.third_party` 同时注入第 5 步**：前者提供 NPC 身份与开口动机，后者提供写法方向，缺一不可。
- `**char_voice`（角色声音摘要）须注入 response**：完整角色卡剥离后，response 步需要一份精简的口吻说明（由角色卡提炼、存入权威状态或系统 prompt 顶层），以保证台词口吻一致。
- **前序步骤提要注入 response**：body_state 与 third_party 的要点须作为「已完成」背景注入第 6 步，避免 response 重述已有动作或与 NPC 台词冲突。
- **导演 directive 缺失的降级策略**：若 `field_scores >= 40` 但导演漏写对应 `step_directives`，后端降级为「仅依据 `environment_facts`/`decided_events`/权威状态自行补全」，不报错，但叙事方向精度由导演负责。
- **首轮无上轮元数据**：权威状态来自「上一轮已落库元数据」，首轮无此来源，须以角色设定默认值（种族/性别/服装/姿态等）初始化；后续轮用数据库最新条目。

## 按当前计划的一轮全链路模拟（含游戏资料包、体征结算、2～6 递进、7/8/9）

> 本模拟对应「**角色卡预拆分为游戏资料包** → **第 1 步导演只出关键帧** → **第 1B 步体征结算独立**（锁分/游戏共用体征接口）→ **第 2～6 步用字段胶囊 + 手递摘要补中间帧** → **第 7 元数据 → 第 8 选项 → 第 9 记忆**」的架构。下列文本均为示意，便于你把它当成「一整轮可对照的样例数据」继续迭代提示词与后端拼装逻辑。

### 玩家本轮

```text
可是我不会飞啊，不然我们比赛跑步吧
```

### 0. 预生成：游戏/锁分模式「角色资料包」

> 来自角色卡离线派生、保存后写入 DB 的结构化内容；第 1 步可只读一个短摘要，第 2～6 步按字段只注入各自胶囊。此处按当前计划用 JSON 写清形状。

```json
{
  "world_capsule": "Equestria/小马国风格：明亮色彩、轻喜剧社交氛围；云边小镇户外场景常见风、土路、集市场、田野与农货。",
  "body_capsule": "飞马：双翼+四蹄+尾巴+耳朵的体态语言；云宝为天马，飞行相关肌肉群发达；外向好胜时步幅更开、耳尖上翘；尴尬或生理不适时耳尖会压低、尾尖僵直。",
  "mind_capsule": "底色素：好胜、行动派、嘴硬。隐藏面：被认真夸奖或正面情感冲击时会先梗住再用玩笑反弹。对熟人围观敏感，不想露怯。",
  "voice_capsule": "直来直去、带挑衅式玩笑；用短句。兴奋时口癖偏「哈/喂/来啊」；被戳中羞耻点时语速略乱、句尾会硬转折。对玩家可直呼名，不必每句点名。",
  "director_capsule": "长期动机：想证明自己快、想赢。底线：不恶意羞辱玩家。倾向：用比赛推动气氛，不拖泥带水。",
  "vitals_capsule": "锁分体征为叙事接口：便意/尿意/体力等必须表现为可观察身体外显，不得用台词替代生理推进；在卫生间/马桶场景若体征提示有排便需求，排便过程不可被长期「忍耐」一句话糊弄过去。"
}
```

### 0b. 上轮权威元数据短摘录（本模拟假设已有）

> 第 1 步与第 1B 步读「后端权威状态」时，会吃到类似下述摘要（不必是全文 JSON）。

```json
{
  "time": "午后",
  "location": "小马谷草坪，喷泉旁与跑道线附近",
  "relationship_stage": "高度亲密",
  "mood": "愉悦、好奇、好胜",
  "character_position": "草坪前方、跑道起点附近，面向玩家",
  "player_position": "喷泉旁、跑道内侧",
  "character_pose": "半张开翅膀、站姿前倾，跃跃欲试",
  "player_pose": "站立",
  "character_outfit": "日常轻便装束（本模拟略）",
  "player_outfit": "日常装束（本模拟略）",
  "char_vitals": { "stamina": 100, "restraint": 0 },
  "char_mood": { "curiosity": 50, "pleasure": 70, "nervousness": 20 },
  "organ_fill": { "rectum": 35, "bladder": 20, "stomach": 20, "thirst": 20 },
  "body_handoff_last_round": "云宝重心前倾，前蹄在草皮上轻点，尾巴小幅度左右甩，翼尖因兴奋微微颤动。"
}
```

### 1. 第 1 步：导演 JSON（无体征数值；含关键帧与 `step_directives`）

> 与上文「**导演不应承担体征计算**」一致：本步不输出 `vital_events` / `vital_reasons` 数值块；只输出剧情事实、字段强度、与每字段写作关键帧。锁分下体征由第 1B 步结算。

```json
{
  "player_action_parse": {
    "action_type": "verbal_dialogue",
    "note": "玩家承认自己不会飞，并将比赛从飞行改为地面跑步，以延续竞争与互动。"
  },
  "field_scores": { "env": 45, "body_state": 50, "thoughts": 45, "third_party": 45, "response": 70 },
  "character_core_reaction": "好胜被点燃，同时腹坠的生理不适和场边熟人会让她更在意“气势不能掉”。",
  "environment_facts": "午后小马谷草坪，喷泉在跑道内侧喷水，水雾与草屑在风里掠过跑道边；跑道外停着农货小车，苹果嘉儿在卸货，抬头看到两人要赛跑。",
  "character_inner_arc": "她把“不会飞”转写成新的比赛规则，心里既兴奋又腹坠，嘉儿在旁更让她想先把气势抢赢。",
  "third_party_hint": "嘉儿在跑道外，一句场边安全打趣，不抢主戏。",
  "decided_events": [
    "云宝后退出两大步，前蹄在草皮上交替点踏进入起跑准备",
    "双翅一扬又一收，翼尖在兴奋里轻颤",
    "尾巴兴奋左右甩动，同时腹坠带来的不适让下腹短暂绷紧"
  ],
  "response_type_scores": {
    "statement": 20,
    "silence": 5,
    "question": 25,
    "exclamation": 80,
    "initiative": 65,
    "plead": 0,
    "deflect": 35,
    "consent": 10,
    "tender": 5,
    "refuse": 0
  },
  "step_directives": {
    "env": {
      "focus": "风、水雾、草屑、喷泉声与场边农货小车的空间关系；点出同场有嘉儿在跑道外。",
      "must_include": ["午后光线", "喷泉或水雾", "跑道外农货与轮轴/卸货声", "不描写角色具名动作（动作给 body_state）"]
    },
    "body_state": {
      "focus": "进入起跑准备的同时被明显便意短暂牵制，用身体细节体现兴奋与腹坠的拉扯。",
      "must_include": ["后退并点踏", "翼扬又收", "尾甩", "腹下绷紧"]
    },
    "thoughts": {
      "focus": "第一人称写换规则也要赢的嘴硬、腹坠的烦躁、被熟人盯着的包袱。",
      "must_include": ["地面赛也要赢", "便意", "熟人围观压力"]
    },
    "third_party": {
      "focus": "嘉儿一句乡土口吻的打趣，提醒别绊。",
      "must_include": ["场边", "别绊", "不替主角抢台"]
    },
    "response": {
      "focus": "接受地面赛跑，并拿「不会飞」做轻微调侃，末句有感叹号。",
      "must_include": ["接受跑步", "调侃不会飞", "好胜心"]
    }
  },
  "performance_keyframe": {
    "base_trait": "外向、好胜、嘴硬、行动派",
    "current_mask": "被玩家认真提出新规则时先梗一下，再用更亮的挑衅把害羞压回舌头后面",
    "visible_tells": ["下巴微扬", "耳尖一抖又强行抬高", "尾尖一僵再甩动"],
    "voice_shift": "比平常多一口气口的挑衅，但句里会有半拍停顿再硬接回去"
  }
}
```

### 1B. 体征结算步（原导演内的锁分 `vital_*`，独立成步；示意）

> 本步不生成剧情正文。输入是：上轮体征 + 玩家句 + 导演 `environment_facts` + `decided_events` + `vitals_capsule`。输出是本轮 delta/理由。此处仅展示「为何 body_state 必须写腹坠而不把台词写进身体层」的数值化承接。

```json
{
  "vital_reasons": {
    "stamina": "短距离启动准备，体力轻微消耗。",
    "nervousness": "同场有熟人、腹坠分心，让注意力更紧。",
    "pleasure": "玩家接招比赛，竞赛欲被满足。"
  },
  "vital_events": {
    "char_vitals": { "stamina": -1 },
    "char_mood": { "nervousness": 2, "pleasure": 2 },
    "organ_fill": { "rectum": 0 }
  },
  "resolved_snapshot_for_text_steps": {
    "body_hint_line": "明显便意 · 未处于卫生间，表现为下腹坠胀与肌紧张。",
    "mood_line": "兴奋上扬，紧张小幅上升。"
  }
}
```

### 2～6. 分步执行：只展示「递进手递 + 本步 output」

> 说明：为贯彻「递进但不互相复述全文」，每步在 prompt 里只读**手递**与**本字段胶囊**，不读其他字段全文。下列 `scene.*` 为最终要落入 JSON 的文本。

- **2）env 手递 → output**

  ```text
  env_handoff = 午后草坪跑道被晒得发亮的草缘；喷泉在跑道内侧扬水，水雾被风切向边线，草屑在风里翻滚；场边有农货小车与轮轴细响。第三者：苹果嘉儿在跑道外卸货、抬头看向这边。
  ```

  ```text
  scene.env = "午后阳光把草皮晒得发白，喷泉溅起的水雾被风带向跑道边线，草屑在风里一掀一落；场边农货小车的轮轴与绑绳轻轻作响，和喷泉的哗哗水声叠在一起。跑道外停着未卸完的小车，人影在麻袋后隐约移动，像是也在留意这边的动静。"
  ```

- **3）body_state 手递（承接 env + decided_events + 体征摘要行） → output**

  ```text
  body_in = env_handoff + 体征摘要：明显便意、下腹坠胀；须体现：后退出两大步/前蹄点踏/翼扬又收/尾甩/腹下绷紧。
  ```

  ```text
  scene.body_state = "云宝向后连退两大步，前蹄在草皮上急促地交替点踏，像把起跑的节拍敲进草里；她双翅一扬又一收，翼尖的兴奋在风里轻颤。尾巴在身后左右甩出兴奋的弧线，可小腹坠得发顶，她腹下肌肉一绷一松，把那点不适压成不愿声张的细紧。"
  ```

- **4）thoughts 手递（承接 body 要点，不写可见动作长镜） → output**

  ```text
  thought_in = 身体要点：起跑准备+腹坠绷紧；心理任务：换规则也要赢+熟人围观不想露怯+便意让人分心。
  ```

  ```text
  scene.thoughts = "不飞就改地上比，我才不把这当成认输。可肚子里坠得烦，嘉儿在坡边一瞥过来，我脑子里先冒出的是“别出洋相”——要赢，也要先把这口气撑住。发令一响我就冲，先把气势抢到手再说。"
  ```

- **5）third_party 手递（同场已成立） → output**

  ```text
  tp_in = 同场：嘉儿在卸货、看见两人要跑；要一句、乡土口吻、不抢主戏。
  ```

  ```text
  scene.third_party_dialogue = "苹果嘉儿：喂，你俩要跑也给跑道边边留点神！别被麻袋线绊一跤，我可不当裁判啊。"
  ```

- **6）response 手递（极短提要 + 声音胶囊 + 表演关键帧 + 发言收束 exclamation） → output**

  ```text
  resp_in = 玩家：不会飞/改赛跑步。情绪：想赢+腹坠+嘉儿在旁。声音：直球挑衅+半拍停顿。收束：末句以「！」结束（exclamation）。
  ```

  ```text
  scene.response = "云宝耳尖一抖又猛地扬起下巴，尾尖在身后僵了半拍再甩起来：“行啊！地面跑就跑——别以为换到地上我就会让你，Jason，等会儿输了可别拿不会飞当借口！”"
  ```

### 7. 第 7 步：metadata JSON（全字段都落到顶层或 scene）

> 本步仍遵循「`scene` 在 JSON 中不再重复拼五段，五段以代码从第 2～6 步写入；此处为**文档可读性**把五段也展开列出。」锁分下合并体征快照。

```json
{
  "score": { "current": 100, "change": 0, "status": "win" },
  "score_delta_reason": "玩家以地面赛跑延续竞赛互动，云宝积极接受，场边嘉儿接一句轻量提醒；亲密度下情绪总体正向。（本轮+0 分，示意）",
  "scene": {
    "time": "午后",
    "location": "小马谷草坪",
    "env": "午后阳光把草皮晒得发白，喷泉溅起的水雾被风带向跑道边线，草屑在风里一掀一落；场边农货小车的轮轴与绑绳轻轻作响，和喷泉的哗哗水声叠在一起。跑道外停着未卸完的小车，人影在麻袋后隐约移动，像是也在留意这边的动静。",
    "body_state": "云宝向后连退两大步，前蹄在草皮上急促地交替点踏，像把起跑的节拍敲进草里；她双翅一扬又一收，翼尖的兴奋在风里轻颤。尾巴在身后左右甩出兴奋的弧线，可小腹坠得发顶，她腹下肌肉一绷一松，把那点不适压成不愿声张的细紧。",
    "thoughts": "不飞就改地上比，我才不把这当成认输。可肚子里坠得烦，嘉儿在坡边一瞥过来，我脑子里先冒出的是“别出洋相”——要赢，也要先把这口气撑住。发令一响我就冲，先把气势抢到手再说。",
    "third_party_dialogue": "苹果嘉儿：喂，你俩要跑也给跑道边边留点神！别被麻袋线绊一跤，我可不当裁判啊。",
    "response": "云宝耳尖一抖又猛地扬起下巴，尾尖在身后僵了半拍再甩起来：“行啊！地面跑就跑——别以为换到地上我就会让你，Jason，等会儿输了可别拿不会飞当借口！”"
  },
  "relationship_stage": "高度亲密",
  "mood": "兴奋",
  "character_pose": "起跑准备姿态，翼轻颤",
  "player_pose": "站立",
  "character_position": "草坪前方跑道起点附近，面向玩家",
  "player_position": "喷泉旁跑道内侧",
  "character_action": "准备与玩家进行地面跑步比赛",
  "player_action": "因不会飞而提议改为跑步比赛",
  "character_gender": "雌性",
  "player_gender": "雄性",
  "character_race": "飞马",
  "player_race": "人类",
  "character_outfit": "（略）",
  "player_outfit": "（略）",
  "memory_tags": ["地面赛跑", "同场嘉儿", "便意与好胜并行"],
  "event_flags": {
    "first_handhold": true,
    "confessed": false,
    "first_hug": true,
    "first_kiss": true,
    "physical_intimacy": true,
    "exclusive_confirmed": false,
    "trust_broken": false,
    "relationship_public": false,
    "captivity_established": false,
    "coercion_explicit": false,
    "violence_inflicted": false,
    "torture_inflicted": false,
    "bloodshed_occurred": false,
    "injury_persistent": false,
    "corpse_present": false,
    "escape_attempted": false
  },
  "char_vitals": { "stamina": 99, "restraint": 0 },
  "char_mood": { "curiosity": 52, "pleasure": 72, "nervousness": 22 },
  "organ_fill": { "rectum": 35, "bladder": 20, "stomach": 20, "thirst": 20 },
  "_director_meta": { "response_type": "exclamation", "player_action_type": "verbal_dialogue" }
}
```

### 8. 第 8 步：options（同上文结构）

```json
{
  "suggested_options": [
    { "_options_perspective": "玩家视角" },
    { "label": "摆好起跑姿势", "type": "action", "tone": "期待" },
    { "label": "朝嘉儿挥蹄应一声", "type": "action", "tone": "轻松" },
    { "label": "调侃她别摔倒", "type": "dialogue", "tone": "玩笑" },
    { "label": "先让她缓一缓不适再比", "type": "dialogue", "tone": "关心" },
    { "label": "说要比就比别磨蹭", "type": "dialogue", "tone": "挑衅" },
    { "label": "开始倒数发令", "type": "action", "tone": "果断" }
  ]
}
```

### 9. 第 9 步：memory（中性转写，示意）

```json
{
  "turn": 61,
  "player_action": "玩家表示不会飞，并建议把比赛从飞行改为地面跑步。",
  "event": "午后草坪喷泉与风声中，云宝以起跑姿态接受地面赛跑，苹果嘉儿在场边以一句安全打趣接戏；云宝在好胜与生理不适的拉扯下，用挑衅式台词与玩家下战书。",
  "time": "午后",
  "location": "小马谷草坪",
  "relationship": "高度亲密",
  "emotional_note": "兴奋"
}
```

