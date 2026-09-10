from __future__ import annotations


def _build_mood_desc_lines(cm: dict, char_gender: str = "", cv: dict | None = None) -> list[str]:
    """
    将 char_mood 数值转换为人类可读的情绪描述列表。
    被 _build_lock_vitals_hints（叙事提示）和 prev_state_block（第8步元数据 JSON 评分参考）共同调用。
    """
    lines: list[str] = []

    # 新量表：50=正常/中性基准。情绪提示按每 10 分一档（60/70/80/90 与 40/30/20/10）渐进：
    # 微妙初显 → 明显 → 强烈 → 主宰心智。正常带 40~59 不输出条目。

    fear = cm.get("fear", 50) or 0
    if fear >= 90:
        lines.append(
            "恐惧主宰——思维停滞，无法进行理性判断；全身剧烈颤抖，瞳孔放大，"
            "心率极快，呼吸急促而浅；行为上只剩本能的逃跑或蜷缩反应，无法执行任何需要思考的动作"
        )
    elif fear >= 80:
        lines.append(
            "强烈恐惧——身心被恐慌攥紧；持续颤抖、心跳剧烈、呼吸浅促，"
            "注意力被威胁牢牢吸住，难以思考他事，偶有失控的惊跳或退缩"
        )
    elif fear >= 70:
        lines.append(
            "明显恐惧——持续心悸、肌肉难以放松，对细微动静反应过度，"
            "声音发紧，需要刻意才能维持表面镇定"
        )
    elif fear >= 60:
        lines.append("隐约不安——心跳略快，下意识多打量四周，肩背略有紧绷，仍能理性对话")
    elif fear <= 10:
        lines.append("毫无畏惧——对危险缺乏正常的恐惧反应，行事极度鲁莽，可能对真实威胁视而不见")
    elif fear <= 20:
        lines.append("几乎无畏——对危险信号反应迟钝，倾向于低估风险，不会主动表现出恐惧")
    elif fear <= 30:
        lines.append("偏无畏——对一般威胁态度淡然，不容易被吓到，压力下仍显从容")
    elif fear <= 40:
        lines.append("略胆大——对风险感知偏弱，偶有轻率之举，但不至完全无视后果")

    despair = cm.get("despair", 50) or 0
    if despair >= 90:
        lines.append(
            "绝望主宰——情绪完全平坦化，面部无表情，对任何刺激都没有反应；"
            "不再尝试任何行动，不主动说话，被问到时只给出最简短的回应或沉默"
        )
    elif despair >= 80:
        lines.append(
            "深度绝望——主动意愿近乎熄灭，对未来持否定态度，"
            "对鼓励多敷衍或沉默，难以被轻易拉回参与感"
        )
    elif despair >= 70:
        lines.append(
            "明显绝望——常感「做了也没用」，动力严重不足，语气消沉，"
            "需要外力反复推动才肯行动"
        )
    elif despair >= 60:
        lines.append("隐隐颓丧——偶尔叹气，易泄气，对积极提议回应疲软，但仍能勉强配合")
    elif despair <= 10:
        lines.append("盲目乐观——完全否认负面现实，对明显的危机保持不合理的乐观，回避一切悲观可能")
    elif despair <= 20:
        lines.append("过度乐观——对现实困境轻描淡写，难以真正感受到绝望或沉重感")
    elif despair <= 30:
        lines.append("偏乐观——整体心态积极，不容易陷入沮丧，对坏消息会下意识淡化")
    elif despair <= 40:
        lines.append("略偏乐观——对挫折恢复较快，偶有低落但能自我调节，不易长时间消沉")

    submission = cm.get("submission", 50) or 0
    if submission >= 90:
        lines.append(
            "顺从主宰——几乎不会对玩家的意愿产生抵触；"
            "主动配合、甚至提前猜测并迎合，几乎不发出实质性异议"
        )
    elif submission >= 80:
        lines.append(
            "高度顺从——绝大多数情况听从玩家；有不同看法也多压下，"
            "分歧时优先让步，很少坚持己见"
        )
    elif submission >= 70:
        lines.append(
            "明显顺从——遇分歧倾向于让步，会主动配合玩家安排，"
            "偶有犹豫但最终多选择配合"
        )
    elif submission >= 60:
        lines.append("略偏顺从——更愿意协商与配合，坚持己见时需要较强理由")
    elif submission <= 10:
        lines.append("极度反叛——对玩家的任何指令都会本能地抗拒，甚至做相反的事，服从意愿近乎为零")
    elif submission <= 20:
        lines.append("强烈抗拒——主动表达异议，不轻易妥协，视顺从为对自我的贬低")
    elif submission <= 30:
        lines.append("偏独立——重视自主权，面对玩家意见会认真评估后决定是否接受")
    elif submission <= 40:
        lines.append("略偏独立——多数事可商量，触及底线时会明确拒绝，不会无原则让步")

    arousal = cm.get("arousal", 50) or 0
    _is_male = char_gender.lower() in ("male", "男", "男性", "雄", "雄性")
    # 性兴奋提示：只写生殖器官与体内感受（供模型对齐档位），不写衣物；文末另有「叙述提醒」说明用语边界。
    if arousal >= 90:
        if _is_male:
            lines.append(
                "性兴奋主宰——阴茎完全勃起至胀痛，龟头敏感到最轻刺激即战栗；尿道口溢液，"
                "睾丸与会阴坠胀难忍；呼吸急乱，下腹与腰骶收缩感压过思考，射出冲动占据主导"
            )
        else:
            lines.append(
                "性兴奋主宰——阴蒂充血敏胀，阴唇肿胀；阴道润滑涌流、内壁酸胀、不自主收缩；"
                "乳头硬胀酥麻，胸颈潮红；呼吸紊乱，盆腔深处空虚与渴求被填满的冲动淹没理性"
            )
    elif arousal >= 80:
        if _is_male:
            lines.append(
                "强烈性兴奋——阴茎持续完全勃起，整根充血发胀；龟头胀满，稍受刺激即整条发紧；"
                "睾丸与下腹坠胀酸麻，会阴脉动感明显，骨盆偶有不自觉前倾"
            )
        else:
            lines.append(
                "强烈性兴奋——阴蒂与阴唇明显充血胀大；阴道润滑增多、深处酸胀、内壁蠕动感加重；"
                "乳头勃起敏感，小腹与盆底坠胀，体液沿会阴与腿根皮肤滑落"
            )
    elif arousal >= 70:
        if _is_male:
            lines.append(
                "明显性兴奋——阴茎由半勃向完全勃起过渡，血流涌动感清晰；龟头胀感加重，"
                "会阴开始发紧发热，睾丸轻微上提感，腰骶发僵"
            )
        else:
            lines.append(
                "明显性兴奋——阴蒂开始勃起样敏胀，阴唇微肿发热；阴道口润湿、内壁偶有收缩，"
                "乳头对触碰反应明显，小腹隐隐坠胀"
            )
    elif arousal >= 60:
        if _is_male:
            lines.append(
                "初显性兴奋——阴茎轻微充血或半勃倾向，龟头略胀；下腹隐隐收紧，"
                "会阴皮温略升，敏感带被触碰时血流反应快于意识"
            )
        else:
            lines.append(
                "初显性兴奋——外阴血流略增，阴蒂轻微胀敏；阴道开始分泌润滑，"
                "内壁偶有酥痒，乳头略敏感，小腹略有充盈感"
            )
    elif arousal <= 10:
        lines.append(
            "性冷淡/厌恶——对任何性相关刺激有明显的排斥反应，亲密接触会引起不适甚至抗拒；"
            "外生殖器与内壁感觉麻木干涩，腺体几乎无兴奋分泌"
        )
    elif arousal <= 20:
        lines.append("明显性冷漠——对性刺激几乎无反应，对亲密行为感到疏离或无趣，不会主动寻求亲密")
    elif arousal <= 30:
        lines.append("偏性冷淡——性欲低迷，对亲密接触缺乏热情，需要较强刺激才有轻微血流或分泌反应")
    elif arousal <= 40:
        lines.append("略低性欲——性反应阈值偏高，一般亲密下身体仅有微弱反应，不易进入兴奋状态")

    if arousal >= 60 or arousal <= 40:
        lines.append(
            "叙述提醒——上文出现的解剖与器官用语仅用于对齐本档生理强度，不得当作角色原话模板；"
            "主观表达须符合该角色身份与口语习惯，用感受与情绪承载同等强度，避免教科书式直呼学名；"
            "可观察的外在表现与主观表达分工清晰、互不替代。"
        )

    pleasure = cm.get("pleasure", 50) or 0
    if pleasure >= 90:
        lines.append(
            "愉悦主宰——正向情绪将思维完全淹没，难以抑制地想笑或落泪，"
            "对周围一切充满好感；无法维持严肃表情或理性判断，思维飘忽，只想让这一刻永远延续"
        )
    elif pleasure >= 80:
        lines.append(
            "强烈愉悦——内心充实温热，精神高度愉悦；强烈想延续当下、拉近距离，"
            "对外界积极信号反应热烈，包容度很高"
        )
    elif pleasure >= 70:
        lines.append(
            "明显愉悦——注意力多被积极感受占据，情绪轻松上扬，"
            "对玩笑与亲近的接受度明显提高"
        )
    elif pleasure >= 60:
        lines.append("心情略好——嘴角易上扬，对小事也容易感到满足，整体比平常更温和")
    elif pleasure <= 10:
        lines.append(
            "痛苦主宰——强烈的负面情绪笼罩全身，难以抑制地感到悲苦或厌恶；"
            "无法正常享受任何事物，思维持续被负面感受占据"
        )
    elif pleasure <= 20:
        lines.append("明显不悦——情绪压抑，对大多数事物感到乏味或不满，难以找到正面感受")
    elif pleasure <= 30:
        lines.append("有些不悦——情绪偏低落，不太容易感到开心，比平时更容易产生消极想法")
    elif pleasure <= 40:
        lines.append("略偏低落——偶有好感但很快消散，需要额外积极刺激才能暖起来")

    restraint = (cv.get("restraint", 0) if cv is not None else cm.get("restraint", 0)) or 0
    if restraint >= 88:
        lines.append("完全固定——身体无法做出任何幅度的移动，四肢和躯干被完全限制，已停止挣扎")
    elif restraint >= 70:
        lines.append("严重束缚——活动范围极小，挣扎多次无效后已减少尝试，只能做微幅动作")
    elif restraint >= 50:
        lines.append("明显束缚——行动受到显著限制，无法自由改变姿势或位置")
    elif restraint >= 30:
        lines.append("有束缚感——部分肢体活动受限，偶尔尝试挣脱")
    elif restraint >= 15:
        lines.append("轻微束缚——活动略受限制但基本行动不受影响")

    sadness = cm.get("sadness", 50) or 0
    if sadness >= 90:
        lines.append(
            "悲痛主宰——持续流泪且无法控制，面部肌肉因哭泣而抽搐，"
            "呼吸因抽泣而断续不规则，无法正常说话，对外界事物完全失去兴趣和反应"
        )
    elif sadness >= 80:
        lines.append(
            "强烈悲伤——眼泪难以止住，频繁哽咽，声音低沉颤抖，"
            "需费力才能说出完整句子，易被安慰触动而崩溃"
        )
    elif sadness >= 70:
        lines.append(
            "明显悲伤——眼眶常湿，语调发闷，笑容勉强，"
            "对往常感兴趣的事提不起劲"
        )
    elif sadness >= 60:
        lines.append("隐隐伤感——眉宇低沉，话变少，偶有叹息，仍能完成日常互动")
    elif sadness <= 10:
        lines.append("情感麻木/强行乐观——无法感知悲伤，对本应伤心的事反应平淡甚至刻意回避；可能以夸张的乐观掩盖内心空洞")
    elif sadness <= 20:
        lines.append("情绪压抑——内心可能存在悲伤但无法或不愿表达，表面维持正常但缺乏真实情感流露")
    elif sadness <= 30:
        lines.append("偏乐观——整体情绪偏向积极，不容易被悲伤情绪影响，对伤感话题会快速转开")
    elif sadness <= 40:
        lines.append("略偏开朗——偶有低落但能较快振作，对悲伤叙事保持一定距离")

    anger = cm.get("anger", 50) or 0
    if anger >= 90:
        lines.append(
            "愤怒主宰——已完全丧失理性控制：肌肉紧绷，牙关咬紧，呼吸粗重，"
            "行为具有攻击性（大喊、摔打、踢踹或冲撞），无法进行正常对话，任何劝说都会激化愤怒"
        )
    elif anger >= 80:
        lines.append(
            "强烈愤怒——面部涨红，声音提高带刺，敌意外露，"
            "肢体动作幅度大，濒临动手或砸物边缘"
        )
    elif anger >= 70:
        lines.append(
            "明显愤怒——语气生硬急促，反复压制发作冲动，眼神发冷，"
            "身体姿态紧绷，易被挑衅点燃"
        )
    elif anger >= 60:
        lines.append("隐隐动怒——眉头紧锁，回答简短带刺，耐心变短，仍在用理智压着火气")
    elif anger <= 10:
        lines.append("完全压抑/麻木——几乎失去表达愤怒的能力，即便遭受不公也不会产生任何愤怒反应，情绪极度压制")
    elif anger <= 20:
        lines.append("极度压抑——极少表达不满，对侵犯和冒犯的忍耐度异常高，回避任何冲突")
    elif anger <= 30:
        lines.append("脾气温和——很少动怒，面对冒犯倾向于忍让或转移话题")
    elif anger <= 40:
        lines.append("略好脾气——偶有不快多咽下，触及底线才会明确表达不满")

    courage = cm.get("courage", 50) or 0
    if courage >= 90:
        lines.append(
            "勇气主宰——行事果断无畏，面对压力或威胁时率先迎上而非退缩；"
            "表情自信从容，语气坚定，即便遭遇危险也不显露慌乱；可能因过度自信而冒险"
        )
    elif courage >= 80:
        lines.append(
            "相当勇敢——遇到困难主动应对，不轻易回避冲突，"
            "敢于表态与拒绝，言行笃定"
        )
    elif courage >= 70:
        lines.append(
            "偏勇敢——面对压力能主动表达意见，心跳虽快仍能站定，"
            "不会一压就退"
        )
    elif courage >= 60:
        lines.append("略偏勇敢——比平常更敢开口，愿承担小风险，仍会对大威胁犹豫")
    elif courage <= 10:
        lines.append(
            "极度胆怯——几乎无法在威胁情境下做出主动反抗；"
            "身体本能退缩，声音发颤，任何需要抵抗的行动都需要极大的外力推动"
        )
    elif courage <= 20:
        lines.append("明显胆怯——言行保守内敛，不主动出头，容易在高压下沉默或回避对抗")
    elif courage <= 30:
        lines.append("有些胆怯——倾向于退让，面对冲突或危险会犹豫，需要鼓励才能主动行动")
    elif courage <= 40:
        lines.append("略偏谨慎——非必要时不愿出头，但若被点名或关乎重要之人仍会硬着头皮上")

    shyness = cm.get("shyness", 50) or 0
    if shyness >= 90:
        lines.append(
            "羞怯主宰——全身泛红，无法维持视线接触，说话时声音轻到几乎听不见；"
            "被注视或被触碰时会本能地缩起身体，恨不得消失在空气里"
        )
    elif shyness >= 80:
        lines.append(
            "非常害羞——脸颊持续泛红，言行局促，被赞美或关注时立刻慌乱，"
            "掩饰失败，语序易乱"
        )
    elif shyness >= 70:
        lines.append(
            "明显害羞——易脸红，回避对视，涉及私密话题时结巴或停顿增多，"
            "可出现符合角色体态的细小局促动作或摆弄随身小物"
        )
    elif shyness >= 60:
        lines.append("略易害羞——被直视或调侃时会短暂脸红，很快强作镇定")
    elif shyness <= 10:
        lines.append("完全无耻/豁达——对任何暴露、评价或亲密接触毫无羞耻反应，行事完全不受害羞情绪影响")
    elif shyness <= 20:
        lines.append("几乎不害羞——对亲密话题和身体暴露反应平淡，很少表现出局促或脸红")
    elif shyness <= 30:
        lines.append("偏豁达——整体大方，只在极特殊情境下才会有轻微的局促感")
    elif shyness <= 40:
        lines.append("略大方——多数场合从容，仅在意外关注下有一丝不自在")

    nervousness = cm.get("nervousness", 50) or 0
    if nervousness >= 90:
        lines.append(
            "焦虑主宰——全身肌肉僵硬，呼吸浅促，注意力无法集中；"
            "任何细小动静都会引发过激反应，难以维持正常交谈，处于崩溃边缘"
        )
    elif nervousness >= 80:
        lines.append(
            "强烈紧张——动作拘谨，语速忽快忽慢，易说错话或打翻东西，"
            "反复确认细节，明显想逃离现场"
        )
    elif nervousness >= 70:
        lines.append(
            "明显紧张——肩颈僵硬，手心易汗，视线游移，"
            "需刻意放慢呼吸才能说完一段话"
        )
    elif nervousness >= 60:
        lines.append("隐隐紧绷——表面镇定，但细小动作发颤、吞咽变多，对突发声响反应偏大")
    elif nervousness <= 10:
        lines.append("极度迟钝/麻木——对任何紧张刺激几乎毫无反应，哪怕面对真实危险也显得异常平静，缺乏正常的警觉本能")
    elif nervousness <= 20:
        lines.append("几乎不紧张——即便在压力情境下也显得过于从容，警觉反应迟钝")
    elif nervousness <= 30:
        lines.append("偏放松——面对一般压力很少产生紧绷感，整体表现从容")
    elif nervousness <= 40:
        lines.append("略从容——多数场合不紧不慢，仅在高压截止期前才会略急")

    curiosity = cm.get("curiosity", 50) or 0
    if curiosity >= 90:
        lines.append(
            "好奇主宰——对周围一切充满强烈探索欲，眼神专注而充满问号；"
            "即便在压力下也难以抑制追问和观察的冲动"
        )
    elif curiosity >= 80:
        lines.append(
            "强烈好奇——不停追问细节、凑近观察，话题易被未知吸走，"
            "打断后仍会绕回疑问"
        )
    elif curiosity >= 70:
        lines.append(
            "明显好奇——主动发问、侧耳倾听，对新信息眼睛发亮，"
            "愿意为此多停留片刻"
        )
    elif curiosity >= 60:
        lines.append("略好奇——对新鲜事物愿意多打听一两句，不追到底但也不立刻走开")
    elif curiosity <= 10:
        lines.append(
            "完全漠然——对周遭事物毫无兴趣；"
            "眼神空洞，不会主动发问，即便遇到异常情况也只是被动接受"
        )
    elif curiosity <= 20:
        lines.append("明显漠然——很少主动探索或追问，对新事物态度冷淡")
    elif curiosity <= 30:
        lines.append("兴趣不浓——对大多数事物反应平淡，需主动引导才会投入关注")
    elif curiosity <= 40:
        lines.append("略淡漠——可应付对话，但不会自找话题，对异常现象也懒得多问")

    return lines


def _build_lock_vitals_hints(cv: dict, cm: dict, of: dict, char_name: str = "", char_gender: str = "") -> tuple[str, str, str]:
    """
    基于当前体征数据构建游戏 Agent 叙事提示字符串。
    体征类字段多为多档渐进描述；char_mood 叙事与行为指引与 _build_mood_desc_lines 一致，
    按每 10 分一档（偏高 60/70/80/90，偏低 40/30/20/10）从微妙过渡到主宰。
    char_name: 角色名，用于在提示行前标注"XX现在是 ..."增强模型感知。
    返回 (body_hint, mood_hint, response_hint)，无需注入时返回空字符串。
    mood_hint 包含「主动需求」板块，提示角色主动寻求满足生理需求（进食/饮水/如厕），而不是被动忍耐。
    """
    _name_prefix = f"{char_name}现在" if char_name else ""
    body_lines: list[str] = []
    mood_lines: list[str] = []
    need_lines: list[str] = []          # 主动需求行为倾向，将并入 mood_hint
    mood_behavior_lines: list[str] = []  # 情绪驱动行为指引，将并入 mood_hint
    response_speech_lines: list[str] = []  # 仅锁分：口塞等与「怎么说」强绑定的 response 台词规则，单独注入 response 步

    # ── char_vitals（角色体征） ────────────────────────────────────────────────

    # pain 0=无痛 → 100=极度疼痛
    pain = cv.get("pain", 0)
    if pain >= 90:
        body_lines.append(
            "极度剧痛——疼痛已完全超出忍耐极限：全身因痛觉反射不受控制地剧烈颤抖和痉挛，"
            "四肢蜷缩并死死抠住身下的东西，额头冒冷汗，牙关咬得发酸。"
            "无法维持任何正常姿态，连翻身都会引发剧痛；面部表情完全扭曲，"
            "说话时声音因疼痛而断续颤抖、无法组成完整句子，甚至只能发出呻吟或哭喊。"
            "思维几乎被疼痛吞没，无法集中注意力在任何事情上。"
            "任何外部触碰都会引起强烈的痛觉反射——即使是轻柔的安抚也会让身体本能地缩开或抽搐"
        )
        need_lines.append("极度剧痛：角色无法维持正常行为——**必须**发出求救或呻吟，若玩家在场须向其表达剧痛、请求帮助（止痛/扶稳/不要再碰疼痛部位）；不得假装若无其事地继续对话")
    elif pain >= 70:
        body_lines.append(
            "剧烈疼痛——持续而强烈的痛感占据了大部分注意力：身体不自主地紧绷、频繁改变姿势试图缓解，"
            "面部时常因痛感而皱眉咬唇。说话声音发颤，时不时因突如其来的一阵痛感而中断话语。"
            "难以做需要集中注意力的事，动作因疼痛而变得小心翼翼和迟缓"
        )
        need_lines.append("剧烈疼痛：角色应向玩家表达疼痛难忍，主动请求帮助（如扶住自己、不要触碰疼痛部位、寻找止痛方法）；不应强撑装作没事")
    elif pain >= 50:
        body_lines.append(
            "中度疼痛——明显且持续的痛感令人分心：身体本能地想保护疼痛部位、抵抗接触，"
            "偶尔会因为一阵痛感而吸气或皱眉。能勉强正常对话但注意力明显不集中"
        )
        need_lines.append("中度疼痛：角色应主动告知玩家自己在痛，请玩家注意避免触碰或加重疼痛的动作；可婉转请求休息或换个更舒适的姿势")
    elif pain >= 30:
        body_lines.append("轻度疼痛——隐隐作痛，偶尔牵扯一下，不至于严重干扰行动但无法忽视")
        need_lines.append("轻度疼痛：角色可提及哪里有些不舒服，若玩家关心可如实说，不必刻意隐瞒")
    elif pain >= 10:
        body_lines.append("微弱疼痛感——隐约的不适，偶尔意识到疼痛的存在")
        need_lines.append("微弱疼痛：若玩家询问或话题自然引到，角色可轻描淡写地提一下有点不舒服")

    # consciousness 100=完全清醒 → 0=昏迷
    con = cv.get("consciousness", 100)
    if con <= 10:
        body_lines.append(
            "意识濒临消失——角色已经处于昏迷或半昏迷状态：眼睛无法睁开或只能微微翕动、"
            "瞳孔无法聚焦，四肢完全失去自主控制而瘫软，对外界呼唤几乎没有反应。"
            "不可能进行任何有意义的对话——只能发出含糊的呻吟或完全无声。"
            "不可能做任何自主动作——连抬手、点头都做不到。"
            "呼吸变得极浅极弱，有时甚至让人担心是否还在呼吸"
        )
        # <= 10：角色完全失去主动能力，不加 need_line，避免模型给昏迷角色写出清醒求救台词
    elif con <= 30:
        body_lines.append(
            "意识极度模糊——思维完全涣散，分不清周围发生什么：眼神涣散、目光无法锁定目标，"
            "对别人说的话只能听到片段、无法理解完整含义。说话含糊不清、词不达意，"
            "常常话说一半就忘了自己要说什么。动作迟缓而无目的，需要依靠支撑才能保持姿势"
        )
        need_lines.append("意识极度模糊：角色几乎失去主动能力，只剩下生理性本能——可能无意识地用颤抖的手抓握玩家、发出含混呻吟；角色自身感知不到在求救，这只是本能反射，不得写出逻辑清晰的完整求救句")
    elif con <= 50:
        body_lines.append(
            "意识明显恍惚——反应极其迟钝：对方说完话需要好几秒才反应过来，回答时经常答非所问。"
            "目光不时失焦、呆滞地望着某处。动作慢得明显，需要努力集中才能完成简单的事"
        )
        need_lines.append("意识明显恍惚：角色无法组织完整语言，但在片刻清醒时会本能地抓住玩家或喃喃唤其名字；台词须断片、词不达意，不得写出条理清晰的求助句")
    elif con <= 70:
        body_lines.append("意识略有模糊——偶尔走神，反应比平时慢半拍，需要被叫两遍名字才回过神")
        need_lines.append("意识略有模糊：角色应向玩家表达自己头脑不太清醒，本能地想靠近或抓住玩家以稳住自己；可以开口说话但语言偶有断续")
    elif con <= 85:
        body_lines.append("意识轻微不清晰——脑袋有些沉，注意力难以持续集中")
        need_lines.append("意识轻微不清晰：角色应主动告知玩家自己有点发懵/集中不了，可请对方说慢一点或重复一遍；认知基本完整，能正常表达")

    # blood_loss 0=无失血 → 100=全身血量流失
    blood = cv.get("blood_loss", 0)
    if blood >= 80:
        body_lines.append(
            "极度失血——面色苍白无血色、嘴唇发紫、四肢冰冷无力：已接近失血性休克，"
            "连眼皮都无力睁开，脉搏微弱而快。任何动作都可能引发晕厥"
        )
        need_lines.append("极度失血：角色已濒临休克——**必须**向玩家发出求救，请求立即止血/搀扶/不要移动；不得自行行动，须依赖玩家帮助")
    elif blood >= 60:
        body_lines.append(
            "大量失血——面色惨白、持续性眩晕：四肢明显无力，稍微改变姿势就严重头晕，"
            "需要依靠支撑才能坐稳。思维因供血不足而变得迟钝"
        )
        need_lines.append("大量失血：角色应强烈请求玩家帮助止血或搀扶，不能自行站立行走；须告知玩家情况危急")
    elif blood >= 40:
        body_lines.append("中等失血——明显的头晕和乏力感，皮肤苍白发凉，做精细动作时手会发抖")
        need_lines.append("中等失血：角色应向玩家表明需要处理伤口，请求帮助包扎或止血；不应继续剧烈活动")
    elif blood >= 20:
        body_lines.append("轻度失血——轻微头晕，身体略感乏力，面色比平时白一些")
        need_lines.append("轻度失血：角色应提及伤口需要处理，若玩家可帮忙包扎或清洁伤口，应主动提出")
    elif blood >= 8:
        body_lines.append("微量失血——轻微的乏力感")
        need_lines.append("微量失血：角色可提一下伤口，若玩家关心可请其帮忙简单处理")

    # oxygen 100=正常 → 0=完全窒息
    oxy = cv.get("oxygen", 100)
    if oxy <= 10:
        body_lines.append(
            "极度缺氧——濒临窒息：嘴唇和四肢末端发紫（紫绀），胸部剧烈起伏却吸不进空气，"
            "喉咙发出嘶嘶或呼噜的窒息声。意识正在快速消失，四肢开始不自主地抽搐"
        )
        need_lines.append("极度缺氧：角色濒临窒息——若尚有意识，**必须**用尽全力向玩家发出求救信号（哪怕只是抓住对方或发出声音）；须设法移到有新鲜空气的地方")
    elif oxy <= 25:
        body_lines.append(
            "严重缺氧——胸口剧烈憋闷：呼吸急促而短浅，每次只能吸进很少空气，面色发青，"
            "四肢开始发软发麻。思维因供氧不足而变得混乱"
        )
        need_lines.append("严重缺氧：角色应立即向玩家表达呼吸困难、需要新鲜空气，请求帮助移到通风处或解除导致缺氧的原因")
    elif oxy <= 45:
        body_lines.append("中度缺氧——呼吸明显吃力，胸腔有压迫感，容易头晕，说长句子时需要中途喘气")
        need_lines.append("中度缺氧：角色应主动表示需要去通风处喘口气，或请玩家帮忙改善当前环境；不应继续高强度活动")
    elif oxy <= 65:
        body_lines.append("轻度缺氧——呼吸略显急促，偶有头晕感")
        need_lines.append("轻度缺氧：角色可提及有些喘不过气，表示想去透透风或换个姿势缓解")
    elif oxy <= 80:
        body_lines.append("血氧略低——轻微的呼吸不畅感")
        need_lines.append("血氧略低：角色可顺带提一下有点胸闷，若玩家关心可说想深呼吸一下")

    # body_temp 50=正常；低温向0，高温向100
    temp = cv.get("body_temp", 50)
    if temp <= 8:
        body_lines.append(
            "濒死性低温——全身失去知觉：肌肉已无法颤抖而完全僵硬，"
            "皮肤冰冷发青，意识极度模糊，对外界几乎没有反应"
        )
        need_lines.append("濒死低温：角色已近失去行动能力——若尚有片刻意识，**必须**向玩家发出求救；须立即被包裹/保暖/转移到温暖处，完全依赖玩家救助")
    elif temp <= 18:
        body_lines.append(
            "严重低体温——全身僵硬、四肢冰冷麻木：颤抖已经停止（不是好转而是恶化），"
            "动作极度迟缓笨拙，思维变得迟钝混沌"
        )
        need_lines.append("严重低体温：角色应强烈请求玩家帮助取暖（毯子/衣物/靠近热源），自己无法有效活动；须尽快进入温暖环境")
    elif temp <= 30:
        body_lines.append("中度低体温——持续颤抖、肌肉开始僵硬、动作迟缓，四肢不太听使唤")
        need_lines.append("中度低体温：角色应主动表示冻得受不了，请求玩家提供保暖（毯子、热饮、移到暖和的地方）")
    elif temp <= 38:
        body_lines.append("体温偏低——明显发抖怕冷，皮肤苍白，本能地想蜷缩起来取暖")
        need_lines.append("体温偏低：角色应提及很冷，向玩家表示想要取暖，可请求毯子或热饮")
    elif temp <= 46:
        body_lines.append("轻微体温偏低——偶尔发冷，手脚有些凉")
        need_lines.append("轻微偏冷：角色可顺带说一下有点凉，若玩家可提供保暖则表示接受")
    elif temp >= 92:
        body_lines.append(
            "极度高热——皮肤温度极高触之烫手：大量出汗，意识混乱并出现幻觉，"
            "全身无力瘫卧，已接近高热致死"
        )
        need_lines.append("极度高热：角色已濒临危险——若尚有意识，**必须**呻吟求救，请求玩家立即降温（冷水/冰块/通风）并寻求帮助；不得继续活动")
    elif temp >= 82:
        body_lines.append("严重高烧——皮肤滚烫、持续大量出汗、意识受明显影响，说话时会说糊涂话")
        need_lines.append("严重高烧：角色应强烈请求玩家帮助降温（冷毛巾敷额/冷水/休息），表示烧得头脑不清；须立即停止活动卧床")
    elif temp >= 72:
        body_lines.append("高烧——体温明显升高，皮肤发热潮红，出汗不止，身体发软")
        need_lines.append("高烧：角色应主动表达烧得很难受，请求玩家帮忙退烧或让自己休息；可要求凉水或帮忙降温")
    elif temp >= 62:
        body_lines.append("发烧——体温略高，皮肤微热，有燥热感")
        need_lines.append("发烧：角色应提及发烧，表示身体不舒服，若玩家可帮忙则请求退烧药或休息")
    elif temp >= 55:
        body_lines.append("体温轻微偏高——有些燥热，轻微不适")
        need_lines.append("轻微发热：角色可提一下有些燥热、身体不太对劲，若玩家关心可说想喝点凉水或歇一歇")

    # stamina 100=充沛 → 0=完全虚脱
    stamina = cv.get("stamina", 100)
    if stamina <= 8:
        body_lines.append(
            "完全虚脱——身体已经没有任何力气：几乎无法支撑自身重量，连抬起手/蹄子都极为吃力，"
            "只能瘫软地靠着或躺着。站立或行走完全不可能。"
            "说话声音虚弱得几乎听不见，每说几个字就要喘气。"
            "连保持眼睛睁开都需要努力"
        )
        need_lines.append("完全虚脱：角色已无法自主行动——**必须**告知玩家自己需要立即躺下/被搀扶，不能继续站立或任何活动；须请玩家帮助安置到可以休息的地方")
    elif stamina <= 20:
        body_lines.append(
            "极度疲惫——全身沉重无力：动作极其虚弱迟缓，四肢抬起来都费力。"
            "勉强能保持坐姿但站立困难，走几步就需要扶着东西休息。声音疲软低沉"
        )
        need_lines.append("极度疲惫：角色应强烈要求立即坐下或休息，告知玩家自己已撑不住；可请玩家搀扶或帮自己找地方坐下")
    elif stamina <= 38:
        body_lines.append("严重体力不支——动作明显迟缓，维持姿势都很吃力，需要频繁休息")
        need_lines.append("严重体力不支：角色应主动提出需要休息，表示快撑不住了；可请玩家稍作停歇或帮自己找地方坐")
    elif stamina <= 58:
        body_lines.append("体力明显下降——疲态明显，动作比平时慢且无力，容易气喘")
        need_lines.append("体力下降：角色应提及有些累，表示想坐下歇一歇；若玩家建议休息应顺势接受")
    elif stamina <= 75:
        body_lines.append("轻微疲惫——有点累，但尚能正常活动")
        need_lines.append("轻微疲惫：角色可顺带说一下有点累，若玩家提议休息可表示赞同")

    # thirst 0=不渴 → 100=严重脱水（档位与 galgame.vitals 级联对齐：40/60/70/80/90）
    thirst = cv.get("thirst", 0)
    if thirst >= 90:
        body_lines.append(
            "极度脱水——嘴唇龟裂出血，舌头肿胀发涩，几乎无法吞咽；"
            "皮肤失去弹性，眼眶深陷，头痛剧烈，"
            "四肢无力颤抖，思维陷入混乱，已接近脱水性休克；"
            "对水的渴求已完全超出其他一切感受，无法专注于任何事"
        )
        need_lines.append(
            "极度脱水，几乎无法正常对话，以找水为最优先——**必须**向玩家乞求水或尝试自行寻找水源；"
            "喝水是当前最迫切的需求"
        )
    elif thirst >= 80:
        body_lines.append(
            "严重口渴——喉咙灼热干燥，每次说话都要费力克服干涩感；"
            "频繁舔唇、吞咽，嘴唇开始皲裂；头晕且注意力涣散，"
            "主动寻找水源或乞求饮水的冲动强烈且难以压制"
        )
        need_lines.append("严重口渴，强烈想喝水、难压制：应明确向玩家表达想喝水；若玩家可帮忙提供水，应直接开口请求")
    elif thirst >= 70:
        body_lines.append(
            "明显口渴——咽喉持续干燥，说话声音略显沙哑；"
            "不时分心去想水，专注度下降；主动希望喝到水"
        )
        need_lines.append("明显口渴，易分心、想喝水：应主动提及口渴，接受玩家提供的水；若附近有水可主动寻求")
    elif thirst >= 60:
        body_lines.append("有些口渴——喉咙偶有干燥感，偶尔想喝点水，尚不强烈")
        need_lines.append("有些口渴，可写想喝点水：若玩家或场景中有水，角色可表示想喝一点")
    elif thirst >= 40:
        body_lines.append("轻微渴意——嘴里略有些干，基本不影响行动与对话节奏")
        need_lines.append("轻微渴意，嘴略干：非必须每轮提喝水，按需点缀即可")

    # infection 0=无感染 → 100=败血症
    inf = cv.get("infection", 0)
    if inf >= 85:
        body_lines.append(
            "败血症前兆——全身持续高烧、肌肉关节剧烈酸痛：伤口溃烂化脓散发异味，"
            "意识因持续高热而模糊，反复出现寒战与高热交替"
        )
        need_lines.append("败血症前兆：角色情况危急——**必须**向玩家求救，请求立即获得药物或医疗帮助；伤口极度恶化，不处理将危及生命")
    elif inf >= 65:
        body_lines.append("严重感染——持续高烧、全身酸痛、伤口化脓红肿，精神萎靡")
        need_lines.append("严重感染：角色应强烈请求玩家帮忙处理伤口或获取药物，不得再拖延；须让玩家了解伤口已化脓恶化")
    elif inf >= 45:
        body_lines.append("感染扩散——局部感染加重，皮肤红热，伴随发烧和疼痛加剧")
        need_lines.append("感染扩散：角色应主动表示伤口越来越不对劲，请求玩家帮忙清创或找消毒药品处理")
    elif inf >= 25:
        body_lines.append("轻度感染——伤口周围红肿发热，轻微发烧")
        need_lines.append("轻度感染：角色应提及伤口有些红肿，表示需要清洁消毒；若玩家可以帮忙应主动请求")
    elif inf >= 10:
        body_lines.append("初期感染迹象——伤口处轻微红热，偶有刺痛")
        need_lines.append("初期感染：角色可提一下伤口有点刺痛发红，若玩家关心可请其帮忙简单处理一下")

    # ── organ_fill（器官充盈度） ───────────────────────────────────────────────

    # stomach：饥饿（低值）和撑胀（高值）双向；默认30，自然-1/轮
    stomach = of.get("stomach", 20)
    if stomach <= 4:
        body_lines.append("极度饥饿——胃部剧烈痉挛收缩，腹部凹陷，头晕眼花站不稳，四肢发软发抖，已接近因饥饿而晕厥")
        need_lines.append("极度饥饿：角色无法再压制对食物的渴望——**必须**向玩家开口要食物，或自行取用附近食物；不得继续假装没事，进食是当前最紧迫的需求")
    elif stomach <= 6:
        body_lines.append("非常饥饿——胃部持续抽痛，腹部明显空瘪，全身乏力，难以集中注意力")
        need_lines.append("非常饥饿：角色应明确表达需要进食，可直接向玩家要食物，或主动寻找附近食物；若玩家提供食物须接受，不得再客气拒绝")
    elif stomach <= 8:
        body_lines.append("明显饥饿——胃部阵阵抽空感，身体有些虚弱")
        need_lines.append("明显饥饿：角色应主动提及想吃东西，或婉转向玩家示意需要食物；若玩家递来食物必须接受")
    elif stomach <= 15:
        body_lines.append("有些饿——胃部偶尔发出咕噜声，轻微的空腹感")
        need_lines.append("有些饿：若附近有食物或玩家主动提供，角色应表示愿意吃，不强撑着拒绝")
    elif stomach >= 97:
        body_lines.append("胃部极度撑胀——上腹部鼓起，食物已顶到食道，频繁干呕，呼吸因膈肌被挤压而变浅，无法弯腰或改变姿势")
        need_lines.append("胃部极度撑胀：角色**必须**拒绝任何食物，并立即告知玩家需要平躺或静止休息；若玩家继续递食物须明确拒绝")
    elif stomach >= 90:
        body_lines.append("胃部严重撑胀——胃鼓胀发硬，上腹持续胀痛，完全没有食欲，只想平躺以减轻压迫感")
        need_lines.append("胃部严重撑胀：角色应明确表示吃不下任何东西，强烈要求躺下休息；若玩家提供食物须拒绝")
    elif stomach >= 82:
        body_lines.append("胃部明显胀满——上腹部有沉重的饱胀感，弯腰或蹲下会加剧不适，动作因此受限")
        need_lines.append("胃部明显胀满：角色应主动说太撑了不能再吃，表示需要安静消化；若玩家提供食物应婉拒")
    elif stomach >= 75:
        body_lines.append("胃部较饱——有明显饱腹感，不想再进食")
        need_lines.append("胃部较饱：角色应礼貌表示已经吃饱，不再接受更多食物")

    # bladder：膀胱充盈，默认10，自然+2/轮
    bladder = of.get("bladder", 10)
    if bladder >= 95:
        body_lines.append("尿意已达极限——已有少量尿液不受控渗出，下腹剧烈绞痛；若当前在卫生间/马桶上，排尿正在发生，无法再控制；若不在卫生间，任何腹压变化（咳嗽、移动、笑）都会加剧漏尿。**【提示本轮仍出现 = 排尿尚未完毕】若已在马桶上，body_state 必须描写液体持续流出，禁止写成「仅剩湿意」或「已排完」**")
        need_lines.append("尿意已达极限：若不在卫生间，角色**必须**立即要求去卫生间或请玩家搀扶前往——任何继续等待都会当场失禁，此刻不得顾及礼貌或羞耻而沉默不言；若已在马桶上，排尿必须持续进行（液体流出中），不得停在「坐着/残留湿意」")
    elif bladder >= 90:
        body_lines.append("尿意接近极限——下腹绷紧发硬，勉强控制；若当前在卫生间/马桶上，应立即完全放松排尿；若不在卫生间，双腿本能夹紧，无法正常行走，身体僵在原地不敢动。**【提示本轮仍出现 = 排尿尚未完毕】若已在马桶上，body_state 必须描写液体持续流出，禁止写成「仅剩湿意」或「已排完」**")
        need_lines.append("尿意接近极限：若不在卫生间，角色必须立即开口表达需要去卫生间，可请玩家陪同或等候；若已在马桶上，排尿必须持续进行，body_state 须描写液体流出/身体放松，不得停在「已排完/仅剩湿意」；不得再勉强支撑")
    elif bladder >= 80:
        body_lines.append("强烈尿意——下腹持续胀痛，注意力被尿意占据大部分；若当前在卫生间/马桶上，排尿尚未完毕，须继续排出。**【提示本轮仍出现 = 排尿持续进行中】body_state 必须描写液体仍在流出/滴落，禁止写成「仅剩残留湿意/已排完/稍作缓解」**")
        need_lines.append("强烈尿意：若不在卫生间，角色应强烈表达需要去卫生间，可直接请玩家帮忙或陪同；若已在马桶上，排尿必须继续（body_state 须写液体流出），不得停止或写成「已排完」；不得继续默默忍耐")
    elif bladder >= 70:
        body_lines.append("明显尿意——下腹有胀感；若当前在卫生间/马桶上，排尿进行中或即将发生，须自然排尿，无需忍耐；若不在卫生间，需有意识地憋住。**【提示本轮仍出现且已在马桶上 = 排尿尚未完毕，body_state 须描写液体流出或身体继续放松排尿中】**")
        need_lines.append("明显尿意：若不在卫生间，角色应主动提出需要去卫生间；若已在马桶上，须继续排尿直到尿意消退，不要提前结束/站起来；若玩家在场，可请其等候")
    elif bladder >= 55:
        body_lines.append("轻微尿意——下腹隐约有充盈感，尚不影响行动")
        need_lines.append("轻微尿意：若不在卫生间且对话节奏合适，角色可提及需要去一趟洗手间")

    # womb：子宫充盈，默认0
    womb = of.get("womb", 0)
    if womb >= 95:
        body_lines.append("子宫极度充盈——小腹深处剧烈胀痛，子宫被撑到极限，持续的压迫感向骨盆和腰部放射，无法保持任何姿势")
        need_lines.append("子宫极度充盈：角色因剧烈胀痛无法维持正常姿势——**必须**向玩家表达无法继续当前状态，请求停止/调整/换到更舒适的姿势")
    elif womb >= 80:
        body_lines.append("子宫严重充盈——小腹深处持续胀痛，无法忽视，注意力完全被腹腔内的压迫感占据")
        need_lines.append("子宫严重充盈：角色应强烈请求玩家调整姿势或减轻腹部压力，表示肚子里胀痛难忍")
    elif womb >= 60:
        body_lines.append("子宫明显充盈——小腹深处有沉重的压迫感和胀感，改变姿势时尤为明显")
        need_lines.append("子宫明显充盈：角色应主动表示小腹撑胀不舒服，请求换一个减轻压迫的姿势")
    elif womb >= 38:
        body_lines.append("子宫有充盈感——小腹深处隐约有撑胀的异样感")
        need_lines.append("子宫有充盈感：角色可提及肚子里有点奇怪的撑胀感，若玩家询问可如实说")
    elif womb >= 18:
        body_lines.append("子宫轻微充盈——小腹深处偶尔有微弱的异样感")
        need_lines.append("子宫轻微充盈：角色可偶尔提及小腹有一丝异样，但不影响正常行动")

    # testicles：精巢充盈（雄性专属），默认0，自然+3~8/轮（高充盈时）
    testicles = of.get("testicles", 0)
    if testicles >= 95:
        body_lines.append("精巢极度充盈——阴囊胀痛已达极限，下腹和腹股沟持续沉重酸胀，无法忽视；身体对任何刺激都极度敏感，难以维持正常姿势")
        need_lines.append("精巢极度充盈：角色的性需求已完全压过羞耻感——会克制不住地向玩家暗示或明示性需求，或主动寻求性释放；可因情境有所迂回，但不得完全压制这股性冲动")
    elif testicles >= 80:
        body_lines.append("精巢严重充盈——阴囊持续胀痛难耐，下腹有沉重的坠胀感，注意力被这股酸胀不断拉走")
        need_lines.append("精巢严重充盈：角色应流露出明显的性渴望和不安，可向玩家迂回暗示自己「很难受」「有性需求」；羞耻感仍在但已很难完全掩盖性需求")
    elif testicles >= 60:
        body_lines.append("精巢明显充盈——阴囊有持续胀感，腹股沟偶尔酸胀，专注时会被这股感觉打断")
        need_lines.append("精巢明显充盈：角色应表现出明显的性躁动和注意力不集中，可含糊地表示「下面有点难受」或「有些憋得慌」；若玩家主动触碰敏感部位，角色不应完全拒绝")
    elif testicles >= 38:
        body_lines.append("精巢有充盈感——阴囊隐约有撑胀的异样感，偶尔意识到这股感觉")
        need_lines.append("精巢有充盈感：角色可在肢体语言或细微反应中流露出些许性躁动，若玩家有意触碰可不强烈拒绝")
    elif testicles >= 18:
        body_lines.append("精巢轻微充盈——下腹偶有微弱的异样感，不影响正常行动")
        need_lines.append("精巢轻微充盈：角色可偶尔因轻微性充盈感而分神，但无明显外在表现")

    # rectum：直肠充盈/便意，默认0，自然+1/轮
    rectum = of.get("rectum", 0)
    if rectum >= 92:
        body_lines.append("便意已达极限——随时可能失禁；若当前在卫生间/马桶上，排便正在发生，无法再控制；若不在卫生间，下腹和肛门持续剧烈胀痛，全身肌肉紧绷。**【提示本轮仍出现 = 排便尚未完毕】若已在马桶上，body_state 必须描写排便持续进行，禁止写成「已排完/坐着休息」**")
        need_lines.append("便意已达极限：若不在卫生间，角色**必须**立即要求去卫生间，否则将当场失禁——此刻不得因羞耻而沉默，必须开口；若已在马桶上，排便必须持续进行，body_state 须描写排泄物排出过程")
    elif rectum >= 90:
        body_lines.append("便意接近极限——勉强控制；若当前在卫生间/马桶上，应立即完全放松排便；若不在卫生间，下腹持续沉重胀痛，注意力完全被便意占据。**【提示本轮仍出现 = 排便尚未完毕】若已在马桶上，body_state 必须描写排便继续进行，禁止写成「已排完/仅剩不适感」**")
        need_lines.append("便意接近极限：若不在卫生间，角色必须立即表达需要去卫生间，可请玩家等候或帮助；若已在马桶上，排便必须持续进行，不得提前结束；不得继续撑着")
    elif rectum >= 80:
        body_lines.append("强烈便意——下腹有持续向下的压迫感；若当前在卫生间/马桶上，排便尚未完毕，须继续排出；若不在卫生间，需要持续用力忍耐。**【提示本轮仍出现且已在马桶上 = 排便持续进行中，body_state 须描写排泄物持续排出，禁止写成「已缓解/仅剩不适」**")
        need_lines.append("强烈便意：若不在卫生间，角色应明确表达需要去卫生间，可向玩家提出，不要默默硬撑；若已在马桶上，排便必须继续进行（body_state 须写排泄物排出），不得停止或写成「已排完」")
    elif rectum >= 70:
        body_lines.append("明显便意——直肠有压迫感；若当前在卫生间/马桶上，应自然排便，无需忍耐；若不在卫生间，需要有意识地收紧忍耐")
        need_lines.append("明显便意：若不在卫生间，角色应主动提出需要去卫生间，不要一直忍着不开口；**若本轮已在卫生间/马桶上，排便必须发生，不得只写排尿**")
    elif rectum >= 62:
        body_lines.append("中度便意——直肠已有明显充盈感，需要有意识地忍耐；若不在卫生间，下腹有隐约压迫感")
        need_lines.append("中度便意：若不在卫生间，角色应主动表达需要去洗手间，不宜继续拖延；不要仅说「有点胀」而不提如厕需求；**若本轮已在卫生间/马桶上，排便必须发生，不得只写排尿**")
    elif rectum >= 55:
        body_lines.append("轻微便意——直肠有轻微充盈感，尚可短暂忽略")
        need_lines.append("轻微便意：若不在卫生间且对话节奏合适，角色可提及需要去一趟洗手间")

    # lung_fill：肺部液体充盈，默认0
    lung_fill = of.get("lung_fill", 0)
    if lung_fill >= 90:
        body_lines.append("肺部极度灌液——肺泡大面积被液体填充，气体交换严重受阻，每次呼吸只能吸入极少量空气，血氧急剧下降，已接近窒息")
        need_lines.append("肺部极度灌液：角色已接近窒息——若尚有意识，**必须**向玩家发出求救，请求立即帮助排液/改变体位/获得医疗帮助；任何延误都危及生命")
    elif lung_fill >= 72:
        body_lines.append("肺部大量积液——每次呼吸伴随明显的湿啰音，胸腔沉重，呼吸极度费力，需要大口喘气")
        need_lines.append("肺部大量积液：角色应强烈请求玩家帮助坐起或调整体位（直立有助于呼吸），表示胸腔越来越难受，需要帮助")
    elif lung_fill >= 52:
        body_lines.append("肺部明显积液——胸腔有沉重感，呼吸时有阻力，频繁咳嗽且咳出液体")
        need_lines.append("肺部明显积液：角色应主动表示胸口很难受、呼吸费力，请求玩家帮自己坐得更直或找地方休息")
    elif lung_fill >= 32:
        body_lines.append("肺部少量积液——呼吸时偶尔听到湿啰音，呼吸略有阻力，时常咳嗽")
        need_lines.append("肺部少量积液：角色应提及胸口有些堵，表示需要坐正姿势或出去透透气；若玩家关心可如实说明")
    elif lung_fill >= 15:
        body_lines.append("肺部微量液体——偶尔咳嗽，深呼吸时胸腔有轻微不适")
        need_lines.append("肺部微量液体：角色可顺带说一下胸口偶尔不太舒服，深呼吸有点别扭")

    # 体内器具（0=未佩戴，100=完全佩戴/阻塞；导演步维护）
    _ug = int(of.get("urethral_plug", 0) or 0)
    if _ug >= 70:
        body_lines.append("尿道塞佩戴紧——排尿受阻，下腹与尿道口持续异物感与酸胀，无法自然排空膀胱")
        need_lines.append("尿道塞：排尿相关描写须与器具一致，禁止无铺垫写出完全正常排尿；需取出或导尿时应先处理器具")
    elif _ug >= 40:
        body_lines.append("尿道塞部分阻塞——排尿费力、尿线细弱，尿道口持续异物感")
        need_lines.append("尿道塞：角色应体现排尿不畅；若需完全排尿须先松动或移除器具")
    elif _ug >= 15:
        body_lines.append("尿道塞轻度佩戴——尿道口有轻微异物感，排尿时略有不适")
        need_lines.append("尿道塞：排尿描写须考虑器具影响")

    _ap = int(of.get("anal_plug", 0) or 0)
    if _ap >= 70:
        body_lines.append("肛塞深戴——直肠持续胀满异物感，括约肌被迫张开，便意与排便严重受阻")
        need_lines.append("肛塞：禁止无铺垫正常排便；排便或肛相关行为须先处理器具")
    elif _ap >= 40:
        body_lines.append("肛塞明显——直肠异物感持续，坐下或迈步时压迫感明显，便意排出困难")
        need_lines.append("肛塞：叙事须体现排便受阻；移除或润滑后再写排便完成")
    elif _ap >= 15:
        body_lines.append("肛塞轻度——直肠有异样充盈感")
        need_lines.append("肛塞：若有排便情节须考虑器具")

    _mp = int(of.get("mouth_plug", 0) or 0)
    if _mp >= 70:
        body_lines.append("口塞紧封——无法正常说话与经口进食，下颌酸胀，仅能发出含糊呜咽")
        need_lines.append(
            "口塞：禁止清晰长句与正常咀嚼吞咽；饮水进食须先解除或改鼻饲等剧情内合理方式；"
            "**response 台词**须极度含糊，与口塞强度一致"
        )
        response_speech_lines.append(
            "口塞紧封（mouth_plug 高）：**response 里角色说出口的对白**须接近无法正常交谈——"
            "仅允许短促含糊音节、呜咽、断续单字或破碎短句；**禁止**流利、完整、书面化长句；"
            "若须表意，须用含糊咬字、喉音、重复、拖长音与停顿体现，口齿不清程度须与当前 mouth_plug 数值（紧塞档）一致"
        )
    elif _mp >= 40:
        body_lines.append("口塞明显——口齿不清，说话严重受限，经口进食困难")
        need_lines.append(
            "口塞：对话须体现咬字困难；大口进食/饮水应先解除器具；"
            "**response 台词**须明显含糊、句子缩短"
        )
        response_speech_lines.append(
            "口塞明显（mouth_plug 中高）：**response 台词**须严重口齿不清——句子刻意缩短、多处停顿、咬字含混，"
            "禁止正常语速与清晰长对白；口齿含糊程度须随 mouth_plug 升高而加重（本档须明显差于轻度档）"
        )
    elif _mp >= 15:
        body_lines.append("口塞轻度——口腔异物感，说话略含糊")
        need_lines.append("口塞：长对话或大口吃食须受限；**response 台词**须略含糊，随数值升高而更不清")
        response_speech_lines.append(
            "口塞轻度（mouth_plug 较低）：**response 台词**须略含糊——偶发咬字不清、个别字黏连，长句略不顺；"
            "口齿应略差于无口塞时；若同轮 mouth_plug 较上一轮更高，本轮回话须比上一轮更含糊"
        )

    _vp = int(of.get("vaginal_plug", 0) or 0)
    _g_lo = (char_gender or "").strip().lower()
    _is_female_of = _g_lo in ("female", "f", "女", "女性", "雌", "雌性")
    if _is_female_of:
        if _vp >= 70:
            body_lines.append("阴道塞紧塞——阴道持续胀满异物感，纳入困难，妇科检查或插入类行为受阻")
            need_lines.append("阴道塞：阴道插入相关描写须先处理器具；禁止无铺垫写出完全畅通的纳入")
        elif _vp >= 40:
            body_lines.append("阴道塞明显——下体异物感持续，行走或并腿时压迫明显")
            need_lines.append("阴道塞：性行为描写须考虑器具阻碍")
        elif _vp >= 15:
            body_lines.append("阴道塞轻度——阴道口有轻微异物感")
            need_lines.append("阴道塞：亲密行为须提及器具影响")

    # ── char_mood（角色情绪） ───────────────────────────────────────────────────
    mood_lines.extend(_build_mood_desc_lines(cm, char_gender=char_gender, cv=cv))

    # ── char_mood 情绪驱动行为指引（情绪状态 → 行为/对话倾向）──────────────────────

    # 行为指引：与 _build_mood_desc_lines 对齐，每 10 分一档（60/70/80/90 与 40/30/20/10）

    _fear = cm.get("fear", 50) or 0
    if _fear >= 90:
        mood_behavior_lines.append("恐惧主宰：角色已失去理性控制——内心须充斥本能逃跑/蜷缩/失声的冲动，对外须呈本能反应（尖叫、颤抖、扑向任何可依靠之物），不得写出理性平静的对话；若玩家在场，角色会本能抓住或紧贴玩家")
    elif _fear >= 80:
        mood_behavior_lines.append("强烈恐惧：角色应主动向玩家表达恐惧、请求保护；内心须反复评估威胁与逃离冲动，难以转移注意力；不得强撑装作完全平静")
    elif _fear >= 70:
        mood_behavior_lines.append("明显恐惧：角色应向玩家寻求安慰或保证，声音发紧、肢体僵硬；若玩家提供安慰须接受，不应冷漠拒绝")
    elif _fear >= 60:
        mood_behavior_lines.append("隐约不安：角色可流露轻微紧张（多打量四周、肩背略僵），仍能理性对话，不必写成崩溃")
    elif _fear <= 10:
        mood_behavior_lines.append("无畏/鲁莽：角色对危险缺乏应有的恐惧反应——对外言行中不应表现出任何畏缩，甚至可能对明显风险视而不见；内心缺少对威胁的正常评估")
    elif _fear <= 20:
        mood_behavior_lines.append("几乎无畏：角色对威胁反应迟钝，倾向于低估风险，面对危险时不表现出恐惧")
    elif _fear <= 30:
        mood_behavior_lines.append("偏无畏：角色对一般威胁态度淡然，不容易被吓到，压力下仍显从容")
    elif _fear <= 40:
        mood_behavior_lines.append("略胆大：对风险感知偏弱，偶有轻率之举，但不至完全无视后果")

    _despair = cm.get("despair", 50) or 0
    if _despair >= 90:
        mood_behavior_lines.append("绝望主宰：角色已停止一切主动行为——对外表现只有沉默、最短的否定或空洞的应声；内心须体现完全的情绪平坦和放弃感，不得写出积极计划或主动请求")
    elif _despair >= 80:
        mood_behavior_lines.append("深度绝望：角色应以冷漠或消极拒绝回应玩家的积极提议，不再主动提出请求或计划；言行传达「不再抱有希望」")
    elif _despair >= 70:
        mood_behavior_lines.append("明显绝望：角色言行传达「做了也没用」，对鼓励只给疲软回应，需外力反复推动才肯动")
    elif _despair >= 60:
        mood_behavior_lines.append("隐隐颓丧：角色可偶尔叹气、回应疲软，但仍能勉强配合简单互动")
    elif _despair <= 10:
        mood_behavior_lines.append("盲目乐观：角色对负面现实完全否认——对外言行中应体现不合理的过度乐观，对危机轻描淡写，回避悲观讨论")
    elif _despair <= 20:
        mood_behavior_lines.append("过度乐观：角色对困境轻描淡写，难以真正感受到绝望或沉重感")
    elif _despair <= 30:
        mood_behavior_lines.append("偏乐观：整体心态积极，不容易陷入沮丧，对玩家的消极言论可自然给予积极回应")
    elif _despair <= 40:
        mood_behavior_lines.append("略偏乐观：对挫折恢复较快，偶有低落但能自我调节，不易长时间消沉")

    _submission = cm.get("submission", 50) or 0
    if _submission >= 90:
        mood_behavior_lines.append(
            "顺从主宰：角色几乎不对玩家的意愿产生抵触——"
            "对外须主动配合甚至提前迎合玩家意图，不发出实质性异议；"
            "内心须体现出对抗/坚持自我的冲动已极度减弱；"
            "若同时恐惧偏高，顺从中可带压迫感；若愉悦与顺从倾向均偏高，可偏温柔依附"
        )
    elif _submission >= 80:
        mood_behavior_lines.append(
            "高度顺从：角色多数情况听从玩家，有不同看法也多压下；"
            "对外言行中不主动发起对立，分歧时优先让步"
        )
    elif _submission >= 70:
        mood_behavior_lines.append("明显顺从：角色遇分歧倾向于让步，主动配合玩家提议，偶有犹豫但最终多选择配合")
    elif _submission >= 60:
        mood_behavior_lines.append("略偏顺从：更愿意协商与配合，坚持己见时需要较强理由")
    elif _submission <= 10:
        mood_behavior_lines.append("极度反叛：角色对玩家的任何指令都会本能抗拒——对外言行中应体现强烈的对立意识，不服从任何命令，甚至可能故意做相反的事；不得表现出任何顺从迹象")
    elif _submission <= 20:
        mood_behavior_lines.append("强烈抗拒：角色主动表达异议，不轻易妥协，坚决维护自主权；视顺从为对自我的贬低")
    elif _submission <= 30:
        mood_behavior_lines.append("偏独立：角色重视自主权，面对玩家意见会认真评估后决定是否接受")
    elif _submission <= 40:
        mood_behavior_lines.append("略偏独立：多数事可商量，触及底线时会明确拒绝，不会无原则让步")

    _arousal = cm.get("arousal", 50) or 0
    _is_male_b = char_gender.lower() in ("male", "男", "男性", "雄", "雄性")
    # 性兴奋行为指引：对齐体内感受与可观察反应，不写衣物；用语边界见 _build_mood_desc_lines 末条「叙述提醒」。
    if _arousal >= 90:
        if _is_male_b:
            mood_behavior_lines.append(
                "性兴奋主宰：角色已难以维持正常对话——"
                "内心须以该角色自然口吻呈现与本档等价的强烈体内感受与冲动失控感，并写出羞耻与无力，禁止照搬锁分条文的解剖措辞；"
                "对外须体现气息紊乱、腰腹发紧、双腿发软、说话断续；禁止假装若无其事"
            )
        else:
            mood_behavior_lines.append(
                "性兴奋主宰：角色已难以维持正常对话——"
                "内心须以该角色自然口吻呈现与本档等价的强烈体内感受、深处空虚与渴求感，并写出羞耻与无力，禁止照搬锁分条文的解剖措辞；"
                "对外须体现气息紊乱、盆底发紧、腿软夹紧、说话断续；禁止假装若无其事"
            )
    elif _arousal >= 80:
        if _is_male_b:
            mood_behavior_lines.append(
                "强烈性兴奋：内心呈现之强度须与锁分档位一致，用语须是角色主观口语而非术语复述；"
                "对外言行中移动或并腿时不适加剧、声音因紧绷偏低沉；玩家触碰敏感部位时不得毫无反应"
            )
        else:
            mood_behavior_lines.append(
                "强烈性兴奋：内心呈现之强度须与锁分档位一致，用语须是角色主观口语而非术语复述；"
                "对外言行中夹腿、呼吸变浅、被触碰时有压抑轻喘或轻哼；玩家触碰敏感部位时不得毫无反应"
            )
    elif _arousal >= 70:
        if _is_male_b:
            mood_behavior_lines.append(
                "明显性兴奋：内心须写出兴奋逐级加重的主观过程，不点名解剖结构亦可，禁止复制锁分原文；"
                "对外言行中被触碰时肌肉绷紧、吸气、腰骶发僵，不得表现得完全不受影响"
            )
        else:
            mood_behavior_lines.append(
                "明显性兴奋：内心须呈现性兴奋加重的主观体内感受链条，不依赖解剖点名亦可，禁止复制锁分原文；"
                "对外言行中被触碰时抖动、吸气、腿收紧，不得表现得完全不受影响"
            )
    elif _arousal >= 60:
        if _is_male_b:
            mood_behavior_lines.append(
                "初显性兴奋：内心仅须轻微暗示身体开始有了性反应，强度低于更高档位，禁止套用语料库式套句；"
                "对外言行中被触碰时略有僵滞、呼吸略促即可，不必写成强烈失控"
            )
        else:
            mood_behavior_lines.append(
                "初显性兴奋：内心仅须轻微暗示身体开始有了性反应，强度低于更高档位，禁止套用语料库式套句；"
                "对外言行中被触碰时有轻微反应即可，不必写成强烈失控"
            )
    elif _arousal <= 10:
        mood_behavior_lines.append(
            "性冷淡/厌恶：角色对任何性相关刺激有明显排斥——"
            "对外言行中对亲密接触应体现出抗拒、不适或冷漠；内心不得出现任何性方面的正面感受；"
            "即便被强制触碰，也只有厌恶和抗拒，不得出现兴奋反应"
        )
    elif _arousal <= 20:
        mood_behavior_lines.append("明显性冷漠：角色对性刺激几乎无反应，对亲密行为感到疏离；被触碰时反应平淡，不会主动寻求亲密")
    elif _arousal <= 30:
        mood_behavior_lines.append("偏性冷淡：角色性欲低迷，对亲密接触缺乏热情，需要较强的刺激才会有轻微血流或分泌反应")
    elif _arousal <= 40:
        mood_behavior_lines.append("略低性欲：性反应阈值偏高，一般亲密下身体仅有微弱反应，不易进入兴奋状态")

    _pleasure = cm.get("pleasure", 50) or 0
    if _pleasure >= 90:
        mood_behavior_lines.append("愉悦主宰：角色应主动表达喜悦，难以抑制地想延续当前状态；会主动靠近玩家、发起温柔的接触或言语，甚至难以维持正常克制")
    elif _pleasure >= 80:
        mood_behavior_lines.append("强烈愉悦：角色应主动靠近玩家、延续互动；对玩家的积极信号热烈回应，不宜矜持回避")
    elif _pleasure >= 70:
        mood_behavior_lines.append("明显愉悦：角色应表现出开心与轻松，对玩笑与亲近接受度高，可主动发起积极话题")
    elif _pleasure >= 60:
        mood_behavior_lines.append("心情略好：角色可比平常更温和、易笑，不必写成极度亢奋")
    elif _pleasure <= 10:
        mood_behavior_lines.append("痛苦主宰：角色被强烈的负面情绪笼罩——对外须体现明显悲苦、厌恶或身心痛苦，不得强撑愉悦；内心须描写无法抑制的负面感受")
    elif _pleasure <= 20:
        mood_behavior_lines.append("明显不悦：角色情绪压抑，对多数事物乏味或不满；对外言行中不得假装积极")
    elif _pleasure <= 30:
        mood_behavior_lines.append("有些不悦：角色比平时更难产生正面感受，对玩家的积极互动回应较为平淡")
    elif _pleasure <= 40:
        mood_behavior_lines.append("略偏低落：偶有好感但易消散，需额外积极刺激才能暖起来")

    _restraint = cv.get("restraint", 0) or 0
    if _restraint >= 88:
        mood_behavior_lines.append("完全固定：角色已无法做任何肢体动作——内心须体现放弃挣扎后的绝望或麻木，对外须明确反映无法移动；不得写出需要肢体自由的动作描写")
    elif _restraint >= 70:
        mood_behavior_lines.append("严重束缚：角色挣扎多次无效后已减少尝试——内心可体现想挣脱但无力的挫败感，对外须反映动作极为受限；可向玩家表达被束缚的痛苦或请求松开")
    elif _restraint >= 50:
        mood_behavior_lines.append("明显束缚：角色应偶尔尝试挣扎，向玩家表达被束缚的不适，可请求松开或减轻束缚")
    elif _restraint >= 30:
        mood_behavior_lines.append("有束缚感：角色应表达对束缚的抗拒，可请求玩家松开或减轻约束；不应默默接受")
    elif _restraint >= 15:
        mood_behavior_lines.append("轻微束缚：角色可提及有些受限，若玩家主动松开可表示接受")

    _sadness = cm.get("sadness", 50) or 0
    if _sadness >= 90:
        mood_behavior_lines.append("悲痛主宰：角色无法正常对话——内心须体现崩溃，对外须呈断续的哭泣或沉默，不得写出条理清晰的完整句子；若玩家在场，角色会本能地抓住对方或埋头哭泣")
    elif _sadness >= 80:
        mood_behavior_lines.append("强烈悲伤：角色应流露出强烈求安慰的需求，可向玩家哭诉或寻求拥抱；言行哽咽，不能强撑假装没事")
    elif _sadness >= 70:
        mood_behavior_lines.append("明显悲伤：角色应流露出不开心，语调发闷、笑容勉强；若玩家安慰须接受，不应冷漠推开")
    elif _sadness >= 60:
        mood_behavior_lines.append("隐隐伤感：角色可眉宇低沉、话变少、偶有叹息，仍能完成日常互动")
    elif _sadness <= 10:
        mood_behavior_lines.append("情感麻木/强行乐观：角色无法感知悲伤——即便面对本应悲痛的事也反应平淡甚至刻意乐观，对外言行中不得出现任何悲伤表达，内心可体现空洞或强行压制的感受")
    elif _sadness <= 20:
        mood_behavior_lines.append("情绪压抑：角色内心可能有悲伤但无法表达，表面维持正常但缺乏真实情感流露")
    elif _sadness <= 30:
        mood_behavior_lines.append("偏乐观：整体情绪偏积极，不容易被悲伤情绪影响，对消极话题可自然给出积极回应")
    elif _sadness <= 40:
        mood_behavior_lines.append("略偏开朗：偶有低落但能较快振作，对悲伤叙事保持一定距离")

    _anger = cm.get("anger", 50) or 0
    if _anger >= 90:
        mood_behavior_lines.append("愤怒主宰：角色已丧失理性——内心须体现失控冲动，对外须呈愤怒爆发（大喊/摔东西/踢踹/冲撞），无法进行正常对话；任何劝说或安抚在此刻只会激化愤怒")
    elif _anger >= 80:
        mood_behavior_lines.append("强烈愤怒：角色应以明显敌意回应玩家，敌意外露，肢体幅度大；可强烈拒绝或反抗，言辞带锋芒")
    elif _anger >= 70:
        mood_behavior_lines.append("明显愤怒：角色应生硬回应，眼神发冷，身体紧绷；易被挑衅点燃，仍在勉强压着不立刻爆发")
    elif _anger >= 60:
        mood_behavior_lines.append("隐隐动怒：角色回答简短带刺，耐心变短，眉头紧锁，仍能用理智收尾")
    elif _anger <= 10:
        mood_behavior_lines.append("完全压抑：角色几乎失去表达愤怒的能力——即便遭受侵犯也不会有愤怒反应，对外言行中不得出现任何不满情绪；内心可体现情绪被深度压制的空洞感")
    elif _anger <= 20:
        mood_behavior_lines.append("极度压抑：角色极少表达不满，对冒犯的忍耐度异常高，回避任何冲突")
    elif _anger <= 30:
        mood_behavior_lines.append("脾气温和：角色很少动怒，面对冒犯倾向于忍让或转移话题，不轻易表达不满")
    elif _anger <= 40:
        mood_behavior_lines.append("略好脾气：偶有不快多咽下，触及底线才会明确表达不满")

    _courage = cm.get("courage", 50) or 0
    if _courage >= 90:
        mood_behavior_lines.append("勇气主宰：角色应主动迎接挑战和冲突，不回避困难话题，可率先发起行动或表态；面对威胁时不慌乱而镇定应对；可能因过度自信而忽视风险")
    elif _courage >= 80:
        mood_behavior_lines.append("相当勇敢：角色遇到困难应主动应对而非回避，可坚持己见、拒绝不合理要求，不轻易被压力左右")
    elif _courage >= 70:
        mood_behavior_lines.append("偏勇敢：角色面对压力能主动表达观点，心跳虽快仍能站定，不会一压就退")
    elif _courage >= 60:
        mood_behavior_lines.append("略偏勇敢：比平常更敢开口，愿承担小风险，仍会对大威胁犹豫")
    elif _courage <= 10:
        mood_behavior_lines.append("极度胆怯：角色应几乎无法在威胁下做出抵抗——对外须以退让、服从或沉默为主；内心须体现强烈的恐惧与无力感，不得写出主动对抗行为")
    elif _courage <= 20:
        mood_behavior_lines.append("明显胆怯：角色应在威胁或压力情境下明显退缩，不主动对抗；在紧张情境下倾向于沉默或回避，须经鼓励才能行动")
    elif _courage <= 30:
        mood_behavior_lines.append("有些胆怯：角色言行应偏保守，面对冲突或危险倾向于退让；若玩家主动发起互动，角色可配合但不应率先行动或对抗")
    elif _courage <= 40:
        mood_behavior_lines.append("略偏谨慎：非必要时不愿出头，但若被点名或关乎重要之人仍会硬着头皮上")

    _shyness = cm.get("shyness", 50) or 0
    if _shyness >= 90:
        mood_behavior_lines.append("羞怯主宰：角色几乎无法直视对方，被关注或触碰时必须有脸红/颤抖/低头等反应；涉及私密/亲密内容时应局促甚至语塞，不得从容自如")
    elif _shyness >= 80:
        mood_behavior_lines.append("非常害羞：被赞美/凝视/私人话题时必须局促脸红；对外言行应有回避视线、掩饰或转移话题")
    elif _shyness >= 70:
        mood_behavior_lines.append("明显害羞：易脸红、回避对视，私密话题时结巴或停顿增多；可有符合角色体态的细小局促动作，不应平静如常")
    elif _shyness >= 60:
        mood_behavior_lines.append("略易害羞：被直视或调侃时短暂脸红，很快强作镇定")
    elif _shyness <= 10:
        mood_behavior_lines.append("完全无耻/豁达：角色对亲密/私密话题毫不拘束——对外言行中不得出现害羞、脸红或局促；即便暴露或被评价也自然大方")
    elif _shyness <= 20:
        mood_behavior_lines.append("几乎不害羞：对亲密话题和身体暴露反应平淡，很少局促或脸红")
    elif _shyness <= 30:
        mood_behavior_lines.append("偏豁达：整体大方，只在极特殊情境下才会有轻微的局促感；若玩家特意调侃，可有一丝不自在")
    elif _shyness <= 40:
        mood_behavior_lines.append("略大方：多数场合从容，仅在意外强烈关注下有一丝不自在")

    _nervousness = cm.get("nervousness", 50) or 0
    if _nervousness >= 90:
        mood_behavior_lines.append("焦虑主宰：对外言行中应出现明显失误、语句断续或过激反应；内心须体现无法自控的慌乱，禁止镇定自若，处于崩溃边缘")
    elif _nervousness >= 80:
        mood_behavior_lines.append("强烈紧张：角色应拘谨、语速不稳、易出错，反复确认细节，明显想逃离或缩短对话")
    elif _nervousness >= 70:
        mood_behavior_lines.append("明显紧张：肩颈僵硬、符合角色体态的紧张外显、视线游移，须刻意放慢呼吸才能说完一段话")
    elif _nervousness >= 60:
        mood_behavior_lines.append("隐隐紧绷：表面镇定，但细小动作发颤、吞咽变多，对突发声响反应偏大")
    elif _nervousness <= 10:
        mood_behavior_lines.append("极度迟钝/麻木：角色对任何紧张刺激几乎毫无反应——对外言行中不得出现任何紧张或警觉迹象，即便面对真实危险也异常平静；内心缺少正常的危机感")
    elif _nervousness <= 20:
        mood_behavior_lines.append("几乎不紧张：即便在压力情境下也显得过于从容，警觉反应迟钝，不会因外界压力产生紧绷迹象")
    elif _nervousness <= 30:
        mood_behavior_lines.append("偏放松：面对一般压力很少产生紧绷感，整体表现从容自然，可主动发起轻松话题")
    elif _nervousness <= 40:
        mood_behavior_lines.append("略从容：多数场合不紧不慢，仅在高压截止期前才会略急")

    _curiosity = cm.get("curiosity", 50) or 0
    if _curiosity >= 90:
        mood_behavior_lines.append("好奇主宰：角色应主动追问细节、观察环境、提出疑问，即便被打断也会绕回感兴趣的话题；内心须体现强烈探索冲动，对外可频繁反问或发掘信息")
    elif _curiosity >= 80:
        mood_behavior_lines.append("强烈好奇：不停追问、凑近观察，话题易被未知吸走，打断后仍会绕回疑问")
    elif _curiosity >= 70:
        mood_behavior_lines.append("明显好奇：主动发问、侧耳倾听，对新信息眼睛发亮，愿为此多停留")
    elif _curiosity >= 60:
        mood_behavior_lines.append("略好奇：对新鲜事物愿意多打听一两句，不追到底但也不立刻走开")
    elif _curiosity <= 10:
        mood_behavior_lines.append("完全漠然：角色对周遭一切毫无兴趣——对外言行中不得出现主动发问或探索；内心须体现空洞感，遇异常也只是被动承受")
    elif _curiosity <= 20:
        mood_behavior_lines.append("明显漠然：对几乎所有话题冷淡，对外言行减少追问，多以简短回应或沉默应对")
    elif _curiosity <= 30:
        mood_behavior_lines.append("兴趣不浓：对大多数话题反应平淡，须玩家多次引导才会产生参与感")
    elif _curiosity <= 40:
        mood_behavior_lines.append("略淡漠：可应付对话，不会自找话题，对异常现象也懒得多问")

    # ── 组装输出 ──────────────────────────────────────────────────────────────

    if not body_lines and not mood_lines and not mood_behavior_lines and not need_lines and not response_speech_lines:
        return "", "", ""

    _bullet = f"• {_name_prefix} " if _name_prefix else "• "

    def _trim_name(ln: str) -> str:
        """取体征/情绪名称（截断 —— 和全角括号后的说明）。"""
        ln = ln.split("（")[0]
        ln = ln.split("——")[0]
        return ln.strip()

    def _short(lines: list[str], n: int = 3) -> str:
        return "、".join(_trim_name(ln) for ln in lines[:n])

    def _split_colon(lines: list[str]) -> tuple[list[str], list[str]]:
        """将「名称：行动指引」格式的行拆分为名称列表和行动列表。"""
        names, actions = [], []
        for ln in lines:
            parts = ln.split("：", 1)
            names.append(parts[0].strip())
            actions.append(parts[1].strip() if len(parts) > 1 else ln.strip())
        return names, actions

    def _nr(ln: str) -> str:
        """按需去掉行内的「角色」二字（当角色名已在 bullet 前缀中时）。"""
        return ln.replace("角色", "") if char_name else ln

    # ── body_hint（身体状态提示） ───────────────────────────────────────────────
    body_hint = ""
    if body_lines:
        body_hint = (
            "【锁分·身体体征提示】body_state 须基于以下体征给出外在表现，"
            "禁止原文转述括号内说明或输出数值，不推荐使用医学/解剖学术语（如膀胱、直肠、子宫等）：\n"
            "【当前体征】\n"
            + "\n".join(f"{_bullet}{ln}" for ln in body_lines)
            + "\n\n【外在表现参考】\n"
            "优先通过可观察的外在表现（姿态、动作、表情等）来体现上述状态，不得套用括号内说明或直接输出数值"
        )

    # ── mood_hint（情绪提示） ──────────────────────────────────────────────────
    mood_hint = ""
    mood_sections: list[str] = []
    if mood_lines:
        _pure_mood = [ln for ln in mood_lines if not ln.startswith("叙述提醒——")]
        _meta_notes = [ln for ln in mood_lines if ln.startswith("叙述提醒——")]
        mood_sections.append(
            "【锁分·心理状态提示】以下情绪档位为叙事参考基线，须在生成内容中自然融入，"
            "禁止原文转述括号内说明或输出数值，不推荐使用医学/解剖学术语（如膀胱、直肠、子宫等）：\n"
            "【当前情绪】\n"
            + "\n".join(f"{_bullet}{ln}" for ln in _pure_mood)
            + "\n\n【运用方式】\n"
            "结合角色性格与口语习惯作委婉表达，禁止照搬括号内字句"
            + (("\n" + "\n".join(_meta_notes)) if _meta_notes else "")
        )
    if mood_behavior_lines:
        mb_names, mb_actions = _split_colon(mood_behavior_lines)
        mood_sections.append(
            "【锁分·情绪行为指引】当前情绪状态应驱动行为和对话方向，**不得与情绪状态相悖地表现得过于平静或反常**：\n"
            "【当前情绪倾向】\n"
            + "\n".join(f"{_bullet}{_nr(s)}" for s in mb_names)
            + "\n\n【行为参考】\n"
            + "\n".join(f"{_bullet}{_nr(a)}" for a in mb_actions)
        )
    if need_lines:
        nl_names, nl_actions = _split_colon(need_lines)
        mood_sections.append(
            "【锁分·主动需求提示】当前有以下未满足的生理需求，不应一直被动忍耐，须主动寻求满足：\n"
            "【当前需求】\n"
            + "\n".join(f"{_bullet}{_nr(s)}" for s in nl_names)
            + "\n\n【应对参考】\n"
            + "\n".join(f"{_bullet}{_nr(a)}" for a in nl_actions)
            + "\n内在须体现主动解决需求的冲动，对外须采取相应行动或向玩家开口表达"
        )
    if mood_sections:
        mood_hint = "\n\n".join(mood_sections)

    # ── response_hint（回复风格提示） ───────────────────────────────────────────
    resp_state_parts: list[str] = []
    if body_lines:
        resp_state_parts.append(f"身体：{_short(body_lines)}")
    if mood_lines:
        _mood_for_short = [ln for ln in mood_lines if not ln.startswith("叙述提醒——")]
        resp_state_parts.append(f"情绪：{_short(_mood_for_short)}")

    resp_action_parts: list[str] = []
    if need_lines:
        resp_action_parts.extend(nl_actions[:3] if need_lines else [])

    if not resp_state_parts and not resp_action_parts and not response_speech_lines:
        response_hint = ""
    else:
        resp_sections: list[str] = []
        hint_header = (
            "【锁分·体征驱动提示】角色输出须同时体现当前身心状态与应对行为，"
            "禁止直接输出括号内说明，不推荐使用医学/解剖学术语（如膀胱、直肠、子宫等），"
            "应优先用角色自身口语习惯的委婉说法："
        )
        if resp_state_parts:
            resp_sections.append("【状态体现】\n" + "\n".join(resp_state_parts))
        if resp_action_parts:
            resp_sections.append(
                "【应对行为参考】\n"
                + "\n".join(f"{_bullet}{a}" for a in resp_action_parts)
            )
        if response_speech_lines:
            resp_sections.append(
                "【台词口齿（最高优先级）】mouth_plug 越高，角色对白越含糊；须直接体现在引号内台词，不得写与口塞无关的清晰长对白：\n"
                + "\n".join(f"{_bullet}{ln}" for ln in response_speech_lines)
            )
        response_hint = hint_header + "\n" + "\n\n".join(resp_sections)

    return body_hint, mood_hint, response_hint
