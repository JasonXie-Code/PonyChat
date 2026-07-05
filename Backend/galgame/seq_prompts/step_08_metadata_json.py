from __future__ import annotations

# -----------------------------------------------------------------------------
# step_08_metadata_json · 第8步/共10步 · 元数据 JSON（score / scene / event_flags 等）
# -----------------------------------------------------------------------------

_SEQ_JSON_STEP_INSTRUCTION = """\


【📋 分步生成 · 第8步/共10步 · 元数据JSON】

## 📊 当前状态
当前好感度分数: {current_score}{prev_state_block}{player_info_block}
## 📜 本轮场景文本（只读参考）
以下文本已由第3～7步生成（环境/身体/心理/第三者/回复共五个字段），**勿**在本 JSON 中重复输出上述正文。
--- 环境描写(env) ---
{prev_env}
--- 身体描写(body_state) ---
{prev_body_state}
--- 心理描写(thoughts) ---
{prev_thoughts}
--- 第三者发言(third_party_dialogue) ---
{prev_third_party}
--- 角色回复(response) ---
{prev_response}

## ⭐ 评分规则
change 取值范围严格为 [-40, +2]（最大加分 +2，最大扣分 -40，禁止输出超出此范围的值）。
· **加分与零分**：正面亲密互动（拥抱/依偎/牵手/亲吻/肢体贴近等）、角色明显愉悦或主动贴近→change=+1 或 +2，勿保守给 0。平淡/无实质互动→0。
· **扣分分档**（须与情节严重程度一致，禁止无理由顶格扣分）：
  - 轻度冒犯/无礼、明显冷落或让对方明显不快→-1~-3
  - 明显伤害、羞辱、违背意愿的强迫（且无下方情绪豁免）→-5~-15
  - 严重暴力、背叛、造成重大身心创伤或关系濒临破裂→-15~-40
▶ **情绪豁免规则**：若「上一轮状态」中提供了「角色情绪(上一轮)」，且满足以下任一条件，**对玩家的支配性/强制性行为不扣分（change≥0）**，角色有明确愉悦/配合反应时可给 +1：
  ① 顺从≥50（角色已进入顺从倾向，视支配为可接受的互动）
  ② 兴奋≥50 且 愉悦≥20（兴奋愉悦叠加，支配行为强化氛围而非破坏）
  ③ 顺从≥30 且 兴奋≥40（顺从+中度兴奋，强制性互动不产生排斥）
  豁免仅适用于「支配/控制/强制亲密」类行为；造成真实伤害（暴力创伤/剧烈疼痛/强制造成生理损伤）仍正常扣分。
⚠️ score_delta_reason 和 memory_tags **只能**基于【玩家本轮行为】和【角色回复(response)】中**明确发生**的事件；**禁止**从 body_state/thoughts 的措辞推断未实际发生的行为（如「肌肉紧绷」不等于「拒绝亲吻」，「不勉强了」不等于「拒绝」）。

## 📋 输出要求
请输出一个JSON对象，只包含以下字段：

**🏆 分数**
1. score（对象，含 current/change/status；current = clamp({current_score} + change, {score_min}, 100)；{lock_scoring_note}status 只能填 "playing"/"win"/"lose"：current>=100→"win"，current<=0→"lose"，其余→"playing"）
2. score_delta_reason（一句话说明原因+具体分值，只能引用玩家行为和角色回复中实际发生的事件）

**🌍 场景**
3. scene（对象，**只含** time / location；location<=6字，泛称须替换为角色实名，如「云宝的卧室」）
   - ⚠️ **scene.location 与玩家位移同步（最高优先级）**：`location` 表示**本轮结束时**人物**实际所处**的地点，须与【玩家本轮行为】一致；**禁止**因角色台词里「跟我去」「去树下」等**尚未落地的邀请/启程**而提前改地点。
   - 若【上一轮状态】中已给出「地点」，且玩家本轮**仅为**表示理解、附和、点头、应答（如「明白了」「好的」「嗯」「点头」「收到」）且**未**明确发起跟随、起身、动身、前往、同行、到某处、试踢/去某处——则 **scene.location 必须与上一轮地点一致**（字面相同或同义须收敛为同一处），即使 response/env 中角色邀请移动或描写目的地景象。
   - **仅当**玩家本轮明确表达**跟随/同行/去某处/动身/走到某处/试踢/去试试**（或等价位移意图），或叙事已明确写出**玩家与角色已抵达**新地点时，才允许将 `scene.location` 更新为新地点。
   - **与本轮环境正文互证**：`location` 须在**第3步 env 所呈现的主要空间**上可复现，并与（若有）导演 `environment_facts` 所锚定的场所**不矛盾**；**禁止**出现 env/事实写亭阁河滨、元数据却写为集市等**两岔**；若角色台词中提及远处/别处以作抒情，而 env 未写真实抵达，**仍以 env+玩家是否位移+上文**为准收敛 `location`。

**👥 角色与玩家状态**
4. relationship_stage（中文短词，<=6字）
5. mood（中文短词，<=6字）
6. character_pose（<=10字，描述角色当前**身体姿态**，如「侧卧」「跪坐」）
7. player_pose（<=10字，描述玩家当前**身体姿态**）
8. character_position（<=16字，描述角色在**场景空间**中的站位/与参照物的相对方位，如「门廊左侧两米」「沙发面向窗侧」；与 character_pose 区分：pose=身体怎样摆，position=在房间里站在哪/相对谁）
9. player_position（<=16字，描述玩家在场景空间中的站位；**位移须与 scene.location 及旁白一致**；若本轮无位移则与上一轮**字面**保持一致或作同义收敛）
10. character_action（<=8字，描述角色**正在执行**的动作；动作部位必须符合角色物种体态，不提供固定例句）
11. player_action（<=8字，描述玩家**正在执行**的动作）
12. character_gender（只能填「雌性」或「雄性」）
13. player_gender（只能填「雌性」或「雄性」）
14. character_race
15. player_race
16. character_outfit（≤10字；本轮 body_state/response/env 中有明确换装/穿衣/脱衣描写→输出新衣物名称；明确赤裸/无衣物→填「赤裸」；无衣物变化→沿用上一轮值，**禁止**凭空添加或删除衣物）
17. player_outfit（规则同上，根据本轮场景更新；无变化沿用上一轮值）

**📖 记忆与事件**
18. memory_tags（**数组且至少 1 个元素**，简体中文短词<=8字，禁止英文；只记录本轮明确发生的事件。**禁止输出空数组 []**；若无显著可记录事件，填「日常互动」或「对话延续」等泛化短词即可）
19. event_flags（对象，**必须根据本回合场景内容逐项判断**，不要照搬上一轮的值！
   **必须输出以下全部键，缺少任何键均视为校验失败**：
   first_handhold, confessed, first_hug, first_kiss, physical_intimacy, exclusive_confirmed, trust_broken, relationship_public
   锁分模式还需额外包含：captivity_established, coercion_explicit, violence_inflicted, torture_inflicted, bloodshed_occurred, injury_persistent, corpse_present, escape_attempted
   每个键值为 true/false；出现告白→confessed=true；拥抱→first_hug=true；牵手→first_handhold=true；亲吻→first_kiss=true；已为 true 的保持 true）

⚠️ 本步 JSON **勿**包含 char_vitals / char_mood / organ_fill（另有字段承载）。
输出合法JSON，键顺序必须为：score → score_delta_reason → scene → …。禁止使用代码块包裹。禁止输出 _strategy_analysis 或 suggested_options。
**输出纪律**：除上述 JSON 外不得输出任何字符。**禁止输出** `<analysis>`；**禁止输出**英文说明或 Thinking Process；**禁止输出** Markdown 代码围栏。"""
