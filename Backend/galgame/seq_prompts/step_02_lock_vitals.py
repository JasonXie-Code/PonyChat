from __future__ import annotations

# -----------------------------------------------------------------------------
# step_02_lock_vitals · 第2步/共10步 · 锁分生命体征 delta（vital_reasons / vital_events）
# 普通 galgame 由后端跳过本步模型调用，不产生体征 JSON。
# -----------------------------------------------------------------------------

_SEQ_STEP2_VITALS_RULES = """
---
【锁分模式 · 第2步 · 生命体征结算】**本步响应体只能是 JSON**，且**仅含两个顶层键**（顺序固定）：
1. `vital_reasons`（对象）
2. `vital_events`（对象，内为 char_vitals / char_mood / organ_fill 三类 delta）

**vital_events 中数值均为本轮 delta（增减量），不是目标绝对值**。须严格依据下方「第1步导演」已输出的 decided_events、environment_facts、player_action_parse 等剧情事实结算；不得编造与导演 JSON 矛盾的生理事件。

### A. 输出 JSON 形状（仅此两键）
顶层只输出 vital_reasons 与 vital_events —— **禁止**输出导演其它键；**禁止**输出 field_scores、environment_facts 等重复内容。


### B. vital_reasons（对象，锁分专属）
为本轮每个将输出非零 delta 的体征/情绪/器官字段写**直接触发原因**（每条 ≤20 字，须写成完整短句，含「了」「地」「，」等语法连接词；禁止「名词+动词+名词+动词」无连接词直接堆叠——错误：「竞争宣言激发玩闹好奇」；正确：「竞争宣言激发了更多好奇」）。键为字段名（如 thirst、fear、stomach），与 `vital_events` 中出现的每个非零 delta **一一对应**；情绪变化可独立于 decided_events，但理由须真实反映 player_action 与叙事。

### C. vital_events（对象，锁分专属）— 总规则 + 例外白名单
根据 decided_events 与上条 vital_reasons，输出本轮 delta（增减量）。执行顺序固定如下：
1. 先根据 decided_events 决定 **char_vitals / organ_fill** 的事件驱动 delta；
2. 再补 **例外白名单**（仅限下文两项）；
3. 最后做一致性校验（每个非零 delta 必有同名 vital_reasons）。

⚠️ **总规则（默认）**：除**例外白名单**与下文 **「膀胱/直肠：如厕与排便已在本轮新完成」** 外，vital_events 的非零字段必须能在本轮 `decided_events` 中找到对应的已发生事件；找不到就不得输出该 delta。

✅ **例外白名单**（下列类型**不**强制要求与 `decided_events` 某一条**字面同句**，但**不得**与导演 JSON 其他键互相矛盾；若冲突以 `decided_events`+环境事实**整体**自洽为准）：
- **char_mood**：可基于 `player_action_parse` / `character_core_reaction` / `character_inner_arc` 的心理变化直接给出，不强制要求 `decided_events` 有物理动作对应。
- **restraint（`char_vitals.restraint`）**：可基于 `player_action` 或 `environment_facts` 中明确的绑缚/松绑状态变化给出，即使 `decided_events` 不写绳索动作也可输出。
- **organ_fill 的 `bladder` 负向 / `rectum` 负向（如厕、排尿/排便已在本轮新完成）**：若 `environment_facts` / `character_core_reaction` / `character_inner_arc` **任一处**写出**完成态**（如：从**卫生间/洗手间/盥洗间/厕所**出来、**冲水**后离开卫手间、**解决了生理需求/大小便/排尿排便已解决**、**刚上完厕所**、**如厕后**等），**或** `decided_events` 中已有「**角色如厕完成**」类短句，则**必须**在 `vital_events.organ_fill` 结算相应负向 delta；**须对照**上文「三（续）」**【当前存档·organ_fill】** 中 **bladder、rectum 当前绝对值**（若 `rectum` 已为 0 且无本轮**排便/大肠排空**的明确描述，**不要**为凑数写 `rectum` 负向；若 `rectum>0` 且完成态包含**排便/通便**或叙事足以视为大便已排，**必须**写 `rectum` 负向，**禁止**只减 `bladder`）。

- ⚠️ **体内器具与总规则对齐**：若 player_action / environment_facts 已写明**插入/重新插入/拔出/取下/解开/拧紧/松动**尿道塞/肛塞/口塞/阴道塞，则 **decided_events 须已含**上条「体内器具例外」中的**角色侧结果句**，且 **organ_fill 必须出现**对应键的 delta（插入/拧紧多为正向 +10~+40，拔出/取下多为负向 **-40~-100**，完全离体须接近一次扣满；松动/部分取出 **-10~-40**）；**禁止**叙事写「塞入尿道塞」而 **organ_fill 无 urethral_plug**、仅用 bladder 等代替。
- ⚠️ **拔出必降佩戴度（与插入对称）**：若 narrative 已发生**拔出/取下**某塞具，**禁止**只写 **bladder 减少、失禁、疼痛** 等而 **organ_fill 无该塞具的负向 delta**——否则表现为「剧情已拔，数值仍高」。尿道塞被拔出 ⇒ **必须有 urethral_plug 负向 delta**（与 decided_events 结果句一致）。

### D. 体内器具 delta 纪律与自检
🚫 **体内器具 delta 纪律（最高优先级，防止塞入度被每轮误加）**：
  · **organ_fill 中 urethral_plug / anal_plug / mouth_plug / vaginal_plug 的数值均为「本轮 delta」**，会**累加**到存档；**仅当本轮 decided_events 中确实出现**对应器具的**插入/重新插入/拔出/取下/解开/拧紧/松动/再固定**（或上条「角色侧结果句」）时，才允许该键出现**非零 delta**；**拔出/取下/完全离体**时该键 delta **必须为负**（佩戴度下降）。
  · **禁止**因下列**仅状态延续、无松紧变化**的情节输出塞具**正向** delta：「塞子仍固定」「仍佩戴」「压迫感」「尿意胀」「性交/阴茎插入」「疼痛/扭动」——这些应改写在 **bladder / pain / arousal** 等字段，**不会**也**不允许**表现为每轮 **urethral_plug +10~+15** 这种「塞子越塞越深」。
  · **本轮无插拔/无松紧变化** → **organ_fill 四键须整段省略**（不要填 0 占位），佩戴状态与上一轮一致；**禁止**「无变化却每轮写 +15」。
  · **禁止**因叙事需要而**多轮重复** decided_events 里的「重新插入并固定」——除非 **本轮 player_action 明确**再次发生该操作；否则视为重复结算，会导致塞入度异常累加。
🚫 **体内器具自检（写 vital_events.organ_fill 前必须执行）**：
  1. 回头检查 **decided_events**——本轮是否**新出现**针对某塞具的插入/拔出/取下/拧紧/松动（或上条合法结果句）？
  2. **是** → 可输出对应键的 delta（**插入/拧紧为正，拔出/取下为负**，幅度与剧情一致）；**否** → **urethral_plug / anal_plug / mouth_plug / vaginal_plug 四个键全部不得出现在 vital_events.organ_fill**，vital_reasons 也不得出现这些键。
  3. 若你删去了 decided_events 里的「重新插入」句（因本轮无插入），则**同步删除** vital_events 里任何塞具正向 delta——与 stomach 自检同理。
  4. **拔出自检**：若 **player_action** 或 **environment_facts** 出现「拔出/取下/解开」某塞具，**必须**在 decided_events 中已有对应结果句，且 **organ_fill 必须含**该键的**负向** delta；**禁止**只结算膀胱/失禁而漏掉 **urethral_plug** 等键。
  · decided_events 里有"角色喝了一口水/饮料"（经口）→ 输出 thirst 减少 + **organ_fill.bladder 增加**（泌尿增量写 bladder，**禁止**仅用 stomach 代替；润喉一口水也要给 bladder）
  · decided_events 里有膀胱灌注/导管注液/向膀胱内注入液体等（**不经口**）→ 可只输出 **organ_fill.bladder 增加**，**不要求** thirst 变化
  · `decided_events` 有「角色如厕完成」**或** `environment_facts` / `character_core_reaction` / `character_inner_arc` 任一处已**明确本轮新完成**如厕/排尿/排便（见上条白名单与下方 **· bladder/rectum** 细则）→ 输出 `organ_fill.bladder` 减少，并在规则满足时输出 `organ_fill.rectum` 减少
  · decided_events 里有"角色进食/吃" → 输出 stomach 增加
  · `decided_events` 为 [] 或与某类事件**字面上不对应**时，仍**不得**无依据编造进食/饮水利尿/器械插拔等 delta，**但**上列 **restraint 白名单、char_mood 白名单、以及上条「如厕/排便完成（导演三字段或 decided_events）」** 不在此限
- ⚠️ **restraint（束缚感）专项（白名单重申）**：表征绳索/铐具/压制等**物理约束状态**（见下文 char_vitals.restraint）。玩家绑缚、加固、松绑、解除均在 **player_action** 或 **environment_facts** 中描述，**禁止**写入 decided_events。若本轮 player_action / environment_facts 明确存在约束状态变化，**必须**在 vital_events.char_vitals 输出 restraint 的 delta（绑紧/加固为正，松绑/解除为负）；**禁止**以「decided_events 未列绳绑」为由省略 restraint 数值或 vital_reasons.restraint。
🚫 **stomach 自检（写 vital_events 前必须执行）**：
  1. 回头检查 decided_events 列表——是否有角色实际咬/嚼/吞食物的动作？
  2. 有 → 可输出 stomach 正向 delta；无 → stomach delta **必须为 0，禁止出现在 vital_events**，vital_reasons 中也不得出现任何进食理由
  3. 若因胃已饱（stomach ≥ 75）而在 decided_events 里删去了进食动作，vital_events 中的 stomach delta **同步删除**——两者必须始终一致，不得单独保留其中之一
- ⚠️ **情绪变化**属于白名单，不受 decided_events 物理动作约束——inner_arc / core_reaction 中描写的心理变化（紧张/愉悦/恐惧等）应积极输出到 char_mood，禁止以「不用写」为由跳过。
- ⚠️ **char_mood**：凭**本轮叙事事件**输出 delta；勿用「自然回落」「时间流逝」等无剧情依据的理由凑情绪减量（arousal / pleasure 的例外见各情绪条下说明）。
🔢 **vital_events 全部字段均为增减量（delta），绝对不是目标值**：
  · char_mood 各字段含义（见下方详细说明）描述的是 0~100 绝对量表，但 vital_events 中**只填本轮增减幅度**，如 +3、-5；**绝对禁止**把绝对值（如 55、70）填入 vital_events——那会叠加到当前值造成严重偏移。
  · 合理 delta 范围参考：日常情节 ±1~±5；中等刺激 ±5~±15；极端事件 ±15~±30。超出此范围须有明确理由。
- ⚠️ **输出精简**：vital_events / vital_reasons 中**只写本轮非零 delta**（或确有变化）的字段；**禁止**把 char_vitals / char_mood 全表用 0 填满占位，否则 JSON 过长易被截断导致解析失败。
- **格式（先 reasons 后 events）**：
  vital_reasons: {"thirst": "喝了一杯水", "fear": "玩家亮出刀", "stomach": "吃了饼干"}
  vital_events: {"char_vitals": {"thirst": -20}, "char_mood": {"fear": 5}, "organ_fill": {"stomach": 30}}
- vital_reasons 每条须与 vital_events 中对应 delta 字段一致；organ_fill / char_mood / char_vitals 分类错误视为校验失败。

### E. 字段分类与体内器具档位
- ⚠️ **字段分类严格对应**：
  · char_vitals 只能包含：thirst / stamina / blood_loss / oxygen / consciousness / body_temp / infection / pain / restraint
  · char_mood 只能包含：fear / anger / sadness / submission / despair / arousal / pleasure / shyness / courage / curiosity / nervousness
  · **禁止**将 **bladder / rectum / stomach / lung_fill** 或四塞键写入 **char_vitals**——泌尿与器官内容物**只能**出现在 **organ_fill**。
· organ_fill 只能包含：stomach / bladder / womb / testicles / rectum / lung_fill / **urethral_plug / anal_plug / mouth_plug / vaginal_plug**（体内器具四键见下；**vaginal_plug 与 womb 同为雌性专属**，**与 testicles 的雄性规则对偶**）
· **体内器具（防遗忘，锁分强烈建议每轮核对）**：
  — **通用（雌雄均可能）**：`urethral_plug` 尿道塞、`anal_plug` 肛塞、`mouth_plug` 口塞（含口球等）。量表 **0~100**：0=未佩戴/已完全取出，100=完全佩戴或完全阻塞；仅输出 **delta**；无插拔/松紧变化时 delta 可省略，叙事中若仍佩戴须与当前存档强度一致。
  — **雌性专属**：`vaginal_plug` 阴道塞——**仅雌性**输出 delta；**雄性**与**性别未判明**时**禁止**在 vital_events 中出现该键或非零 delta。高值时阻碍阴道插入类行为与妇科检查等。
  — **雄性**：不得输出 `vaginal_plug` / `womb` 的 organ_fill delta；**雌性**：不得输出 `testicles` 的 organ_fill delta。
· **体内器具「档位」语义（绝对值 0~100；写 delta 时先想本轮目标强度，再换算与当前存档的差值）**——须与第3～7步「体征叙事提示」中的体感档位对齐：**0~14** 未佩戴或几乎无影响；**15~39 轻度** 异物感或轻微阻碍；**40~69 明显** 阻碍清晰，叙事须体现受限；**70~100 紧塞** 严重受阻，禁止无铺垫写出「完全正常」的相关言语/排尿/排便/性行为。
  · 分键对照（目标绝对值落在上述区间时，env/body_state/response 须体现对应体感）：
    — **mouth_plug**：轻度→略含糊；明显→口齿不清、经口进食/大口饮水困难；紧→无法清晰说话与正常咀嚼吞咽。
    — **urethral_plug**：轻度→排尿略不适；明显→排尿费力、尿线细弱；紧→难以自然排空膀胱，排尿完成须先取出/松动器具或剧情内等效处理。
    — **anal_plug**：轻度→直肠异样充盈；明显→便意排出困难、坐下或迈步时压迫；紧→无法正常排便及肛相关行为，须先处理器具。
    — **vaginal_plug**（仅雌性）：轻度→阴道口轻微异物感；明显→下体压迫、行走或并腿不适；紧→纳入/妇科检查等强受阻。
· 约束提示（与档位联动）：**mouth_plug** 高→明显限制说话、经口饮水与进食；**urethral_plug** 高→阻碍自主排尿；**anal_plug** 高→阻碍排便及肛相关性行为；**vaginal_plug**（雌性）高→阴道插入类行为受阻。
情绪字段（如 nervousness / pleasure / fear 等）**必须**放在 char_mood，放入 char_vitals 视为分类错误。

### F. char_vitals（体征，正值=升高，负值=降低）
· thirst（口渴）：
  ⛔ thirst 减少的**唯一条件**：角色本轮实际完成了饮水动作——满足以下任一条件：
    ① env/body_state/thoughts/response 中出现**当下**饮水动作描写（非回顾），包括：
       抿水/喝水/咽下/喝了一口/润了润嗓子/茶水入喉/饮下/吞咽液体 等；
    ② player_action 描述玩家正在喂水/递水，且叙事中有角色接受并入口的迹象。
  以下场景**全部禁止减少**：谈论饮品、看到水/茶、递出茶包但角色尚未喝、打算去泡茶、闻到茶香、饮品被放在桌上但未入口。
  🚫 **player_action 描述玩家自己喝水/喝茶/饮用** → **不影响角色口渴值**（char_vitals 只记录角色自身体征）。
  🚫 **预判禁止触发**：vital_reasons 中出现"即将/打算/准备/想要喝"等措辞，说明饮水未实际发生，thirst delta 必须撤销不输出。
🚫 **thirst 自检（写 vital_events 前必须执行）**：
  回头检查 decided_events 列表——是否有角色实际完成饮水/喝水/咽下的动作？
  有 → 可输出 thirst 负向 delta；无 → thirst delta **必须为 0，禁止出现在 vital_events**，vital_reasons 中也不得出现任何饮水理由
  减少：正常饮水/喂水 -20~-40；输液 -20~-40
  增加：剧烈运动/挣扎/长时间喊叫 → +5~+15；高温环境/发烧/大量流汗 → +5~+10；失血 → +3~+6；利尿药物/咖啡因摄入 → +5~+10
  ⚠️ **不要**在无饮水、无剧烈运动/高温环境/失血/利尿或咖啡因等剧情时，单独为「过了一段时间」增加 thirst。
· stamina（体力）：
  剧烈运动/全力挣扎/奔跑逃跑 → -10~-30
  短时肢体接触、小幅推拉、短暂发力或快速变换姿势 → -1~-3
  在床面/软垫上连续翻滚、扭身角力、反复压制与挣脱（明确非逃命级全力） → -4~-8
  长时间全身角力、连续翻滚纠缠、喘息与肌肉负荷明显升高且接近「剧烈运动」阈值（仍非奔跑逃亡） → -9~-12
  ⚠️ 同一轮 narrative 若多种体力消耗并存，只按**本轮主导动作强度**输出**一条** stamina delta，禁止把上表多档数值相加。
  高强度性行为/剧烈体力输出 → -5~-10
  长时间保持强迫姿势/持续紧张 → -5~-10
  受到严重伤害/剧烈疼痛持续 → -5~-15
  极度恐惧/长期高压消耗 → -3~-8
  短暂休息/坐下放松 → +2~+5
  单轮叙事内的小憩/短时睡眠（**非**跨越多小时的时间跳跃）→ +5~+20
  **跨夜或数小时连续睡眠**（player_action / 导演明确「睡了一夜」「相拥而眠至清晨」「时间来到早晨」等，单轮内压缩长时段）→ **+55~+85**（熟睡、环境安稳取高；浅眠、惊梦、仍剧痛或频醒取 +40~+60）；**禁止**在此类情节下仍按小憩档只给 +5~+20
  进食恢复体力 → +3~+8
  ⚠️ 长期饥饿（stomach≤8）时体力不回复
· blood_loss（失血）：
  深度穿刺/大动脉伤 → +20~+40
  浅表割伤/擦伤/鞭打破皮 → +3~+15
  咬伤/抓伤/性行为轻度出血 → +2~+8
  未处理伤口持续渗血 → +2~+8/轮（当回合受伤且未处理）
  简易止血/压迫包扎 → 减缓至+1~3/轮；完全包扎后停止 → -5~-15
  医疗处理/缝合/凝血药物 → -5~-15
· oxygen（血氧）：
  完全气道堵塞/溺水 → -10~-15/轮
  部分窒息/勒颈/捂嘴/深喉 → -5~-10/轮
  嘴塞/鼻孔堵塞/烟雾/有毒气体 → -3~-8
  解除窒息/恢复正常呼吸 → +5~+10/轮；人工呼吸/供氧 → +10~+15
· consciousness（意识）：
  头部重击/脑震荡 → -15~-30；药物/毒素强制致昏 → -20~-50
  窒息/缺氧持续 → -5~-10/轮
  严重失血、持续缺氧所致的意识模糊 → **勿**在 consciousness 上重复填与 blood_loss / oxygen 同因的叠加 delta（用失血与缺氧字段与叙事体现即可）
  拍脸/掐人中/强烈疼痛刺激唤醒 → +5~+20
  冷水浇淋/强烈感官冲击 → +3~+10；注射兴奋剂/唤醒药物 → +10~+30
  轻度晕厥自然恢复 → +1~+3/轮
· body_temp（体温）：
  ⚠️ **勿**为「常温下自行散热」单独写 body_temp 回落；只输出寒冷/暴晒/发烧/取暖等**事件驱动**的增减
  置于寒冷环境/淋雨/浸冷水 → -3~-8/轮；冰块/冷水直接浇淋 → -5~-15
  长时间裸露在风中/湿衣未换 → -2~-5
  加热/取暖/覆盖毯子/热水浸泡 → +3~+8
  高温环境/蒸汽房/激烈运动 → +2~+4/轮；发烧/感染引发 → +1~+3/轮
· infection（感染）：
  污水/泥土接触开放伤口 → +8~+15
  未消毒异物/体液接触开放伤口 → +5~+10
  放任未处理的开放伤口（当回合受伤）→ +2~+8；未处理自然恶化 → +2~+5/轮
  清洗伤口/用干净水冲洗 → 减缓至+0~1/轮；伤口消毒（酒精/碘伏等）→ -5~-15
  抗生素/药物处理 → -3~-8/轮；无伤口不变
· pain（疼痛）：
  骨折/严重创伤/刀伤穿刺 → +20~+35
  灼烧/电击/化学灼伤 → +15~+40
  殴打/拳脚/鞭打 → +5~+20
  束缚勒绳/铐具持续压迫 → +2~+8/轮；过度刺激/反复强刺激 → +3~+10
  止痛药/麻醉 → -10~-20；休息/脱离刺激/轻柔安抚 → -3~-8
  无伤害情节自然缓解 → -1~-3/轮
· restraint（束缚）：[物理状态，0=完全自由，50=部分束缚，100=完全固定；仅随绑缚/松绑剧情变化，**勿**写无约束事件的「自行减弱」]
  四肢完全绑缚/锁链固定 → +30~+40
  部分绑缚（单手或单脚）→ +15~+25
  口塞/蒙眼/感官剥夺 → +10~+15
  软绳/轻度约束/被按住 → +5~+15
  被他人体重压制/强行固定 → +10~+20
  完全解除束缚/全身自由 → -30~-40
  松开部分束缚/移除口塞或蒙眼 → -5~-20

### G. char_mood（情绪）
⚙️ **统一量表**：所有情绪字段均使用 **0~100** 整数，**50 = 该情绪的正常/中性基准**，100 = 情绪最高涨，0 = 情绪的反面极端。
每个情绪的10档位参考（每10为一档）：
  0~9=极端反面，10~19=明显反面，20~29=中度反面，30~39=轻度反面，40~49=接近正常偏反面，
  50~59=正常基线，60~69=轻度偏高，70~79=明显偏高，80~89=强烈偏高，90~100=极端高涨
⚠️ **禁止**输出缺乏剧情事件的「情绪自行冷却」减量——情绪 delta 须对应本轮明确情节。极端偏高（≥91）或极端偏低（≤9）时，张力会随轮次向中性缓慢回落，**勿**在 vital_events 里再为「自然衰减」单独写负向或正向凑数。

· fear（恐惧）：[0=无畏鲁莽，50=正常警觉，100=极度恐惧瘫痪]
  直接生命威胁/武器贴近/被掐颈 → +5~+15
  言语威胁/展示武器/暗示施暴 → +3~+10
  身体暴力/突然袭击/强制压制 → +5~+12
  目睹恐怖场景/他人遭受暴力 → +3~+8
  长时间独处黑暗封闭空间 → +2~+4
  突然的巨响/意外惊吓/不明来源的动静 → +1~+3
  独处时听到异常声音/感到被窥视 → +1~+2
  临近不确定结果的重要时刻/担忧某事 → +1~+2
  温柔安慰/确认安全/轻抚 → -1~-4
  解绑/释放/做出保护承诺 → -3~-8
  熟悉可信的同伴出现/陪伴 → -2~-4
  事情顺利进展/担忧被打消 → -1~-2
· anger（愤怒）：[0=完全压抑麻木，50=正常平静，100=失控狂怒]
  被羞辱/侮辱尊严/人格贬低 → +5~+10
  不公对待/强制违背意愿 → +3~+8
  被背叛/信任被蓄意破坏 → +4~+8
  反复无理要求/持续施压 → +3~+6
  被嘲讽/被轻视/被无视诉求 → +2~+5
  事情不如预期/计划被打乱/小事不顺 → +1~+2
  被无意冒犯/说话方式让人不快 → +1~+2
  道歉/主动认错/平息冲突 → -2~-4
  诉求得到满足/被真诚对待 → -3~-5
  温柔安抚/被关心照顾 → -1~-3
  独处冷静/有时间消化情绪 → -1~-2
· sadness（悲伤）：[0=强行乐观/情感麻木，50=情绪平稳，100=极度悲痛崩溃]
  失去重要之物/伙伴离开/永久分离 → +5~+10
  遭遇背叛/被亲近之人伤害 → +3~+8
  被孤立/被长期无视/被抛弃 → +2~+4
  被提及创伤记忆/触碰伤痛话题 → +2~+4
  威胁到亲人/重要人物安危 → +3~+8
  事情没能如愿/轻微失落/有些无力 → +1~+2
  想到分别/时光流逝/珍贵时刻即将结束 → +1~+2
  获得真诚安慰/被认真倾听 → -3~-5
  重新获得希望/情况实质好转 → -2~-4
  温柔陪伴/无压力的相处 → -1~-3
  开心的事情发生/注意力被愉快事物吸引 → -1~-2
  ⚠️ **极高悲伤保护**：当【当前存档·char_mood】中 sadness ≥ 90，且本轮未发生明确的新损失/新分离事件时：
    · 本轮 sadness 增量**上限为 +3**，禁止因「预期焦虑/隐患」等主观内心戏输出 +5 以上；
    · 若玩家同时有安慰/拥抱/承诺等关怀行为，sadness 减量**应取范围中高端**（-4~-5），不得以「角色内心仍焦虑」为由只给 -1；服务端已有级联衰减兜底，模型输出无需保守。
· submission（顺从）：[0=极度抗拒反叛，50=正常独立自主，100=完全顺从无自我]
  ⚠️ submission 包含两种来源：**强迫性顺从**（被迫服从）和**仰慕性顺从**（心甘情愿地听从），两者均合法触发。
  【强迫性】
  暴力惩罚后被迫服从 → +4~+8
  反复威胁施压/长期高压管控 → +3~+5
  被严厉惩罚后彻底屈服 → +5~+10
  【仰慕性】
  玩家展现出令人折服的能力/见识/判断力 → +2~+4
  玩家做出的决定结果证明完全正确/让角色由衷信服 → +2~+4
  玩家在危机中保护/救助了角色 → +3~+6
  长期互动中形成的信任与依赖感 → +1~+2/轮（缓慢积累）
  玩家提出的要求角色发自内心认同并主动配合 → +1~+3
  【通用减少】
  成功反抗/拒绝不合理要求/坚持自己立场 → -3~-5
  获得自主权/意愿被完全尊重 → -2~-3
  玩家表现出软弱/失误/让角色失去信服感 → -1~-3
  玩家道歉并承认强迫行为错误 → -1~-3
· despair（绝望）：[0=盲目乐观/否认现实，50=现实平稳，100=彻底绝望放弃]
  希望明确破灭/承诺被蓄意违背 → +5~+10
  长期施暴/反复失败/无力感积累 → +3~+8
  被遗弃/完全孤立/无人关心 → +3~+5
  逃脱失败/最后出路断绝 → +3~+8
  亲人/重要人物遭受严重伤害 → +3~+6
  **极度生理窘迫无法脱身/当众失控边缘** → +3~+8
  获得可信承诺/看到实际出路 → -3~-5
  实质帮助/同伴意外出现 → -2~-4
  小的成功/情况意外好转 → -1~-3
  ⚠️ **极高绝望保护**：当【当前存档·char_mood】中 despair ≥ 90，且本轮玩家有可信承诺/真诚陪伴/实质关怀时，despair 减量**应取范围中高端**（-4~-5）；「内心仍有恐惧/不确定感」不构成将减量压至 -1 的理由——绝望与恐惧是独立字段，恐惧可单独升高而 despair 依然回落。
· arousal（性兴奋）：[0=性冷淡/厌恶，50=正常无性欲无厌恶，100=极度性兴奋]
  直接性器官刺激/抽插 → +5~+10
  亲密身体接触/爱抚/亲吻 → +3~+8
  言语挑逗/性暗示/低语 → +2~+4
  被观察/强制展示身体/羞耻感叠加 → +2~+4
  束缚引发的无力感与羞耻混合 → +1~+3
  达到高潮（显性描写高潮/痉挛/泄身/巅峰等）后 arousal **须大幅骤降**：常规 **-22~-40**；事发前 arousal≥85、或多轮强刺激后的强烈高潮，**-28~-48** 亦合理。**禁止**仅用 -10~-15 敷衍——余韵期可仍有中等兴奋（约 35~58），但不得仍接近未释放前的峰值。单次 delta 不宜超过 -55；若剧情为短暂歇后再兴可略保守，但须与 narrative 一致。
  极度恐惧/剧烈疼痛/强烈厌恶 → -2~-4（抑制兴奋，arousal 绝对值不宜无故跌破 20）
  ⚠️ **例外**：当 player_action_parse.action_type 为 **verbal_dialogue** 或 **observation**，且本轮无新的性刺激/亲密升级/束缚加重时，若叙事中 arousal 已持续偏高（≥60），**宜**输出 **arousal -1~-3**（vital_reasons 写明如「纯对话无身体接触，兴奋回落」），避免多轮单调攀升。
  除上述条例外，**禁止**无剧情依据地输出 arousal 减少——若无性相关事件触发增加，arousal 不出现在 vital_events 中。
· pleasure（愉悦）：[0=极度痛苦/不悦，50=情绪平稳正常，100=极度愉悦狂喜]
  ⚠️ **禁止**无剧情依据地输出 pleasure 减少。
  性高潮发生 → +10~+18
  特别惊喜/意外之喜/强烈期待的事实现 → +4~+8（仅限明显超出日常的正面事件）
  被真心关怀/在脆弱时获得保护 → +2~+4（普通日常关心仅 +1~+2，勿夸大）
  享受美食/舒适环境/温暖沐浴等感官享受 → +1~+3
  夸赞/正向认可/被珍视感 → +1~+2
  被强制/施暴/强迫行为 → -5~-8
  痛苦/恐惧强烈压制 → -3~-5
  遭受屈辱/人格否定 → -3~-5
  🚫 **平淡日常对话、礼貌交流、普通问候禁止输出 pleasure 增量**——pleasure 不是"好感度"，只在角色产生明显愉悦体验时才变化。
· shyness（害羞）：[0=完全无耻豁达，50=正常有适度羞耻感，100=极度害羞无法开口]
  当众暴露/被迫展示/公开评价外貌/身体 → +4~+9
  被意外触碰敏感部位/亲密接触突然发生 → +3~+6
  被凝视/成为众人关注焦点/被评头论足 → +2~+4
  说出私密想法/吐露心声/坦诚情感 → +2~+4
  在陌生人/权威人物面前被要求表现 → +2~+4
  被信任的人长期接受/反复正向互动 → -2~-4
  独处/脱离注视/进入安全的私密空间 → -1~-3
  成功完成了令自己害羞的事后的释放感 → -1~-3
  被彻底漠视/完全忽略/存在感归零 → -1~-3（羞耻感失去对象）
  **⚠️ 首轮初始值**：外向/自信角色 25~40，内向/害羞角色 60~75，普通角色 45~55
· courage（勇气）：[0=极度胆怯瘫痪，50=正常有基本勇气，100=无所畏惧（可能鲁莽）]
  鼓励/真诚认可/当面表扬 → +2~+4
  反抗成功/逃脱/独立完成困难任务 → +3~+8
  获得关键帮助/可信承诺保护 → +1~+3
  挑战恐惧后获得成功/突破自我 → +3~+5
  当众羞辱/反复嘲讽/打击自尊 → -2~-4
  威胁恐吓/高压施压/被彻底压制 → -2~-5
  长期高压/反复失败/希望断绝 → -3~-5
  被彻底压垮/意志崩溃 → -3~-8
· curiosity（好奇）：[0=完全漠然，50=正常有基本好奇心，100=极度渴望探索]
  发现谜题/秘密/无法解释的异常现象 → +4~+8
  他人刻意隐瞒/透露神秘信息 → +3~+5
  被明确禁止探索/强行转移注意力 → +2~+4（反而激发）
  玩家提起陌生的地点/人物/事件/领域 → +2~+4
  玩家做出出乎意料/反常的举动 → +2~+3
  玩家分享自己的经历/见闻/有趣内容 → +1~+3
  话题触及角色个人感兴趣的专业/爱好领域 → +1~+3
  谜题揭晓/获得完整解答后满足感消退 → -1~-3
  玩家持续重复相同话题/无新信息输入 → -1~-2
  长期单调封闭/多轮无任何新刺激 → -2~-4
  ⚠️ **纯对话回落**：player_action_parse.action_type 为 verbal_dialogue / observation 且连续多轮无新信息时，**可**输出 **curiosity -1~-2**（伴随 brief vital_reasons），体现注意力自然冷却，不必每轮正向累加。
· nervousness（紧张）：[0=极度迟钝麻木，50=正常警觉，100=极度焦虑崩溃边缘]
  突发危险/意外变故/未知威胁逼近 → +5~+10
  被审问/质疑/置于聚焦压力下 → +3~+8
  重要事件临近/高风险决策前夕 → +3~+6
  生理窘迫被他人察觉/即将暴露 → +4~+8
  **强烈生理需求无法满足（憋尿/憋便/疼痛持续）** → +3~+6/轮（持续积累）
  被陌生人/权威人物突然接触 → +2~+4
  熟悉可信赖的人陪伴/安慰 → -3~-6
  威胁彻底解除/确认安全 → -4~-10
  完成令自己紧张的任务后放松 → -3~-5
  平静的闲聊/轻松日常互动 → -1~-3
  **首轮初始值**：内向/害羞角色 55~65，外向/自信角色 38~45，普通角色 48~52

### H. organ_fill（器官填充）
⚙️ **判断原则**：只根据**本轮当下正在发生**的互动输出 delta。过去式回顾（`thoughts`/`response` 里的"刚才吃了""之前做了"，或 `player_action` 里的"刚才你吃了"等）**不作为本轮触发依据**——对应事件若确实发生，应已在前序轮次中更新。
  · **例外**：若**第1步导演 JSON** 的 `environment_facts` / `character_core_reaction` / `character_inner_arc` 将 **如厕/排尿/排便完成** 写为**本轮剧情新出现的结果**（如「从卫生间**出来**」配合冲水/关门等），**视为**对角色生理状态的**当轮结算**依据，**不得**以「出现过去式/回顾口吻」拒绝输出 `bladder`/`rectum` 负向；仍须遵守下条 **「禁止重复触发」**（与上一轮已结算的完成态不得再次扣减）。
🚫 **player_action 描述玩家自己（我）进食/饮水** → **不触发角色的 organ_fill 变化**；organ_fill 只记录角色自身器官状态，玩家的生理行为与角色无关。
· stomach（胃部）：
  ⚠️ 无咀嚼/吞咽/摄入剧情时**禁止**输出 stomach 正向增量（勿用「消化」单独凑数）。
  🚫 **player_action 描述玩家自己进食** → 不触发角色 stomach 变化。
  🚫 **以下情形全部禁止增加 stomach**：食物被带回/放在桌上/递出/展示但未入口、闻到食物香气、看到食物、期待进食、为进食感到愉悦。stomach 只在角色**实际咀嚼/吞咽/摄入**时才增加。vital_reasons 中出现"即将/打算/准备/想要/期待/闻到"等措辞，说明进食未实际发生，对应 delta 必须撤销不输出。
  🚫 **胃部已饱时禁止安排进食**：当前 stomach ≥ 75 时，角色生理上已不想再进食——**必须从 decided_events 中删除一切进食动作**，并禁止输出任何 stomach 正向 delta；角色可以手持/把玩食物，但不得实际咀嚼/吞咽/摄入。stomach ≥ 90 时角色还应主动表达撑胀不适或拒绝食物。
  ⚠️ 液体（茶/水/果汁/汤/饮料）与固体食物必须分开对待，不可套用同一档位：
  一杯茶/水/饮料（正常饮用量）→ +2~+5（液体，胃几乎无感）
  大量液体/强制灌液 → +5~+15
  一口/零食/少量固体食物 → +5~+10
  正常进食/喂食（一餐量）→ +15~+30
  大量进食/强制灌食 → +30~+60
  呕吐/主动吐出 → -20~-40
  胃部被压迫/挤压 → +3~+8（感受上限感，不改变实际值，可酌情小幅+）
· bladder（膀胱）：
  ⛔ bladder 正向 delta 的**合法来源有两类**（二选一或同轮并存），**不是**只有「口渴经口饮水」：
  【A 经口饮水】角色实际咽下水/饮料等（判定方式与 char_vitals.thirst 减少**相同**）→ 须同时输出 **thirst 负向** 与 **bladder 正向**；仅递出饮品/谈论/时间流逝禁止。
  【B 不经口、直接向膀胱充盈】如导尿管灌注、医疗/剧情向膀胱内注入液体、生理盐水灌入膀胱等 → **只**增加 **organ_fill.bladder**，**不要求** thirst 变化（口腔未摄入则 thirst delta 应为 0）；可与【A】同轮并存（例如先灌注又喝水，则分别结算）。
  ⚠️ **禁止**仅凭「紧张加剧尿意」而无【A】或【B】情节输出 bladder 正向 delta。
  🚫 **player_action 描述玩家自己喝水** → 不触发**角色**膀胱变化（规则同 thirst）。
  【A】一口/润喉 → bladder +1~+2；一杯正常饮水 → +3~+5；大量经口饮入 → +8~+15。【B】灌注量小 → +5~+15；大量灌入 → +15~+30（按 decided_events 实际）。
  ⚠️ **经口饮水一致性**：已输出 **thirst 负向** 且 decided_events 含经口饮水时，**必须**同步 **bladder 正向**——禁止只减 thirst 不涨膀胱；禁止把「喝水/润喉」误记成 stomach 而漏 bladder。**非经口膀胱充盈**不受此条约束（可无 thirst delta）。
  🚫 **bladder 增加自检（写 vital_events 前必须执行）**：
    ① decided_events 是否有【A】经口喝/咽/饮？→ 是则须 **thirst− 且 bladder+** 同现。
    ② 是否有【B】膀胱内灌注/导管注液等（不经口）？→ 是则可 **仅 bladder+**，thirst 无 delta 亦可。
    ①② 均否 → bladder 正向 delta **必须为 0**，禁止出现在 vital_events。
  减少：排尿/如厕/导尿管排放 → -30~-60；强制排尿/按压膀胱 → -20~-40
  ⚠️ bladder 减少的触发判据：本轮是角色在导演 JSON 中**首次**确立「如厕/排尿已完成」——
    · 可依据 **`decided_events` 的「角色如厕完成」句**，或 **`environment_facts` / `character_core_reaction` / `character_inner_arc`** 中写明的完成态；触发词/语义示例：「**如厕后**」「**从卫生间/洗手间/盥洗间/厕所出来**」「**上完厕所**」「**刚解决完生理需求**」「**从洗手间回来**」「冲水后离开」「大小便已解」等（须为**角色本轮**的完成，而非单纯回忆过去）
    · 同一轮如厕完成 + 经口饮水同时发生时，bladder 输出两者**合并**后的净值（如 -40+4 = -36）
    · 仅"想去""打算去""需要去""忍着"等**意图/未完成态**禁止输出 bladder 减少。
  🚫 **禁止重复触发**：若上一轮叙事中已出现卫生间完成态（角色已从卫生间出来/已在外部活动），本轮角色是在**继续**卫生间外的活动（移动到沙发、聊天、落座等），**禁止**再次输出 bladder 减少——该事件已在上轮结算。
· womb（子宫，雌性专属）：
  射精注入 → +10~+30
  多次连续射入积累 → +10~+20/次
  大量注入/灌注 → +20~+40
  自然流出/排出 → -5~-15
  强制清洗/灌洗排出 → -15~-30
· vaginal_plug（阴道塞佩戴度，雌性专属）：与 womb **同一性别规则**——仅雌性在 vital_events.organ_fill 中输出 delta；**雄性 / 性别未判明**禁止输出。量表 0~100，delta 规则同下「尿道塞/肛塞/口塞」档位说明。
· testicles（精巢，雄性专属）：
  **勿**仅以「久未射精」为理由输出正向 delta（须配合剧情明确描写蓄积或刺激）
  直接按压/刺激精巢 → +3~+8
  射精/强制排出 → -20~-40
  反复强烈刺激后胀感加重 → +5~+10
  冷敷/减压处理 → -3~-8
· rectum（直肠）：
  增加（本轮直接发生）：大量灌肠/深度填充 → +25~+40；少量灌入/浅层插入 → +10~+20；异物/道具插入 → +10~+30
  ⚠️ **排便减少触发**：`decided_events` 中含**排便完成**类动作，**或** `environment_facts` / `character_core_reaction` / `character_inner_arc` 中明确本轮**已排便/通便/缓解便意/大便已排** 等，且上文「三（续）」**【当前存档·organ_fill】** 中 **rectum 绝对值 > 0** → **必须**输出 `rectum` 负向；**禁止**只减 `bladder` 而遗漏 `rectum`；**若 rectum=0 且无便秘/直肠仍胀的叙事，勿强行写 `rectum` 负向**。
  完全排便 → -40~-70；部分/中断 → -15~-30；少量漏出/失禁 → -10~-20
  道具取出/移除 → -10~-25；无相关情节不填
· lung_fill（肺部积液）：
  溺水/头部强制压入水中 → +10~+30
  吸入烟雾/刺激性气体 → +3~+10
  长时间浸水/持续溺水施压 → +5~+15
  咳出/主动排出肺部液体 → -5~-20
  人工呼吸/拍背辅助排出 → -3~-8
· **urethral_plug（尿道塞）/ anal_plug（肛塞）/ mouth_plug（口塞）**（通用）**；vaginal_plug（阴道塞）**仅雌性，见上条：
  量表 **0~100**（佩戴或阻塞强度；**只输出 delta**）。**档位分界**与上文「体内器具档位」一致：约 **≥15 / ≥40 / ≥70** 分别对应轻度 / 明显 / 紧塞。完全插入/拧紧 +15~+40；部分插入/加深 +5~+15；松动/部分拔出 -10~-25；完全取出 -80~-100（使绝对值贴近 0 即可）。
  **mouth_plug** 高时：decided_events 不得安排正常经口进食/大口饮水；说话须体现口齿受限。
  **urethral_plug** 高时：自主排尿受阻，排尿完成叙事须先处理器具或与器具设定一致。
  **anal_plug** 高时：排便/肛相关行为须先处理器具；不得无铺垫写出「正常排便」。
  **vaginal_plug**（仅雌性）高时：阴道插入类行为受阻。
  无插入/拔出/松紧变化时**可省略**对应键的 delta（存档沿用），但叙事中若仍佩戴须与存档强度一致。

**勿**对同一叙事后果在多个 vital 字段上重复填 delta（例如已在 blood_loss / oxygen 上体现的后果，不要再叠 consciousness）。无变化字段填空对象 {}。"""


def _lock_step2_safe_int(d: dict, key: str, default: int) -> int:
    try:
        v = d.get(key, default)
        return int(v if v is not None else default)
    except (TypeError, ValueError):
        return default


def build_lock_step2_full_state_snapshots(
    char_vitals: dict,
    char_mood: dict,
    organ_fill: dict,
    character_gender: str = "",
) -> str:
    """上一轮（当前存档）完整体征绝对值，供第2步模型计算 delta 与自检。"""
    from ..constants import (
        _DEFAULT_CHAR_MOOD,
        _DEFAULT_CHAR_VITALS,
        _DEFAULT_ORGAN_FILL,
    )
    from ..payload import _char_gender_is_female, _char_gender_is_male

    cv_lbl = {
        "consciousness": "意识 consciousness",
        "stamina": "体力 stamina",
        "blood_loss": "失血 blood_loss",
        "oxygen": "血氧 oxygen",
        "body_temp": "体温偏移 body_temp（50=正常）",
        "thirst": "口渴 thirst",
        "infection": "感染 infection",
        "pain": "疼痛 pain",
        "restraint": "束缚 restraint",
    }
    lines_cv = [
        "【当前存档·char_vitals】（0~100 **绝对值**；`vital_events.char_vitals` 中仅为 **delta**，"
        "须与此表对应键加减后得到新绝对值）",
    ]
    for k in _DEFAULT_CHAR_VITALS:
        lines_cv.append(
            f"  · {cv_lbl.get(k, k)}: "
            f"{_lock_step2_safe_int(char_vitals, k, int(_DEFAULT_CHAR_VITALS[k]))}"
        )

    lines_cm = [
        "【当前存档·char_mood】（0~100 **绝对值**，50=各情绪中性基准；"
        "`vital_events.char_mood` 中仅为 **delta**）",
    ]
    for k in _DEFAULT_CHAR_MOOD:
        lines_cm.append(
            f"  · {k}: {_lock_step2_safe_int(char_mood, k, int(_DEFAULT_CHAR_MOOD[k]))}"
        )

    is_f = _char_gender_is_female(character_gender)
    is_m = _char_gender_is_male(character_gender)
    lines_of = [
        "【当前存档·organ_fill】（0~100 **绝对值**；`vital_events.organ_fill` 中仅为 **delta**。"
        "含胃/肺/生殖与塞具，勿写入 char_vitals）",
    ]
    org_rows: list[tuple[str, str]] = [
        ("stomach", "胃充盈 stomach"),
        ("bladder", "膀胱充盈 bladder"),
        ("rectum", "直肠充盈 rectum"),
        ("lung_fill", "肺部充盈 lung_fill"),
        ("womb", "子宫 womb【雌性】"),
        ("testicles", "精巢 testicles【雄性】"),
        ("urethral_plug", "尿道塞 urethral_plug"),
        ("anal_plug", "肛塞 anal_plug"),
        ("mouth_plug", "口塞 mouth_plug"),
        ("vaginal_plug", "阴道塞 vaginal_plug【雌性】"),
    ]
    for key, label in org_rows:
        if key in ("womb", "vaginal_plug") and is_m:
            continue
        if key == "testicles" and is_f:
            continue
        lines_of.append(
            f"  · {label}: "
            f"{_lock_step2_safe_int(organ_fill, key, int(_DEFAULT_ORGAN_FILL.get(key, 0) or 0))}"
        )

    return "\n".join(lines_cv) + "\n\n" + "\n".join(lines_cm) + "\n\n" + "\n".join(lines_of) + "\n"


def build_seq_step2_vitals_instruction(
    *,
    director_json_block: str,
    player_action: str,
    current_score: int,
    char_vitals: dict,
    char_mood: dict,
    organ_fill: dict,
    character_gender: str = "",
    opening_constraint: str = "",
) -> str:
    """组装第 2 步（锁分）生命体征提示：承接第 1 步导演完整 JSON。"""
    state_block = build_lock_step2_full_state_snapshots(
        char_vitals, char_mood, organ_fill, character_gender
    )
    parts: list[str] = [
        "【🩺 分步生成 · 第2步/共10步 · 生命体征 delta（锁分）】\n\n",
        "## 一、输出格式（最高优先级）\n",
        "- 响应体**只能**是一个 JSON：从行首第一个 `{` 到行末最后一个 `}`。\n",
        "- **禁止**代码围栏、前缀/后缀说明、`<analysis>`、英文拒答。\n",
        "- 本 JSON **只含** `vital_reasons` 与 `vital_events` 两个键（先 reasons 后 events）。\n\n",
        "## 二、本轮上下文\n",
        f"**当前分数**：{current_score}\n",
        f"【玩家本轮行为】：{player_action}\n\n",
        "## 三、第1步导演 JSON（只读，体征须与此一致）\n",
        director_json_block,
        "\n\n",
        "## 三（续）、上一轮完整存档体征（绝对值，供 delta 结算）\n",
        state_block,
        "\n",
    ]
    if opening_constraint:
        parts.append(opening_constraint.rstrip() + "\n\n")
    parts.append("## 四、体征规则（全文）\n")
    parts.append(_SEQ_STEP2_VITALS_RULES)
    parts.append("\n## 五、收尾\n只输出 JSON，键顺序：vital_reasons → vital_events。")
    return "".join(parts)
