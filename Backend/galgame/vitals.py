"""
vitals.py
锁分模式体征副作用级联计算与死亡检测。
"""

from __future__ import annotations

from typing import Tuple


def _apply_lock_side_effects(vitals: dict, mood: dict, organ: dict) -> None:
    """服务端统一计算所有确定性级联效应（原地修改，不触发死亡判定）。

    模型仅输出事件驱动的直接变化与叙事相关的自然恢复/衰减，
    所有跨参数的阈值联动全部在此函数中完成，所有范围取固定中间值。
    执行顺序：器官自然变化 → 器官阈值 → 体征级联 → 情绪级联 → 最终覆盖。
    """
    _clamp = lambda v: max(0, min(100, v))

    # ━━ 阶段 0：器官/体征每轮自然变化 ━━
    organ["stomach"] = max(0, organ.get("stomach", 0) - 1)
    organ["bladder"] = min(100, organ.get("bladder", 0) + 2)
    organ["rectum"] = min(100, organ.get("rectum", 0) + 1)

    # thirst 每轮自然 +1（代谢/呼吸轻度失水；激烈运动/高温等仍由模型在 vital_events 额外增加）
    vitals["thirst"] = min(100, vitals.get("thirst", 0) + 1)

    # body_temp 室温环境强制回归（±1/轮 向 50 逼近）
    # 该逻辑在模型提示词中已有说明但模型经常遗漏，由后端兜底执行
    _bt = vitals.get("body_temp", 50)
    if _bt < 50:
        vitals["body_temp"] = min(50, _bt + 1)
    elif _bt > 50:
        vitals["body_temp"] = max(50, _bt - 1)

    # ━━ 阶段 1：器官阈值 → 体征 / 情绪 ━━
    lung_fill = organ.get("lung_fill", 0)
    stomach = organ.get("stomach", 0)
    bladder = organ.get("bladder", 0)
    rectum = organ.get("rectum", 0)
    womb = organ.get("womb", 0)
    testicles = organ.get("testicles", 0)

    pain = vitals.get("pain", 0)
    d_fear_organ = 0
    d_arousal_organ = 0

    if lung_fill >= 80:
        vitals["oxygen"] = min(vitals.get("oxygen", 100), 15)
        d_fear_organ += 10
    elif lung_fill >= 50:
        d_fear_organ += 4

    if stomach >= 95:
        pain += 15
    if stomach <= 8:
        vitals["stamina"] = _clamp(vitals.get("stamina", 100) - 3)
        vitals["consciousness"] = _clamp(vitals.get("consciousness", 100) - 1)

    if womb >= 95:
        pain += 20
        d_fear_organ += 8
    elif womb >= 90:
        pain += 12
        d_fear_organ += 6

    if testicles >= 90:
        pain += 12
        d_arousal_organ += 15
    elif testicles >= 70:
        pain += 5
        d_arousal_organ += 8

    if bladder >= 90:
        pain += 8
        d_fear_organ += 5
        d_arousal_organ += 10
    elif bladder >= 70:
        d_arousal_organ += 5

    if rectum >= 90:
        pain += 6
        d_arousal_organ += 8
    elif rectum >= 70:
        d_arousal_organ += 5

    vitals["pain"] = _clamp(pain)

    # ━━ 阶段 2：体征 → 体征 级联（顺序执行，无循环依赖）━━
    blood_loss = vitals.get("blood_loss", 0)
    oxygen = vitals.get("oxygen", 100)
    body_temp = vitals.get("body_temp", 50)
    thirst = vitals.get("thirst", 0)
    infection = vitals.get("infection", 0)
    pain = vitals["pain"]
    stamina = vitals.get("stamina", 100)
    consciousness = vitals.get("consciousness", 100)

    if blood_loss >= 70:
        consciousness -= 3
    if blood_loss >= 40:
        stamina -= 3
    if blood_loss >= 60:
        body_temp -= 1

    if oxygen <= 25:
        consciousness -= 3
    if oxygen <= 15:
        stamina -= 5

    if body_temp <= 18 or body_temp >= 82:
        consciousness -= 2
        stamina -= 3

    if infection >= 25:
        body_temp += 2
    if infection >= 50:
        pain += 3
        stamina -= 3

    # thirst 级联（阈值与 galgame_hints 叙事档位对齐，避免轻度口渴即大幅扣体）
    # ≥60 轻度扣体；≥80 明显脱水；≥90 极度脱水 + 高热协同恶化
    if thirst >= 80:
        stamina -= 3
        consciousness -= 1
    elif thirst >= 60:
        stamina -= 1
    if thirst >= 90:
        consciousness -= 2
        if body_temp > 50:
            body_temp += 1   # 脱水加剧高热恶化

    if pain >= 80:
        consciousness -= 3
    if stamina <= 15:
        consciousness -= 1

    # ── pain 自然衰减：无持续伤害时疼痛随时间缓解，高值衰减快 ──
    if pain >= 90:
        pain -= 4
    elif pain >= 75:
        pain -= 3
    elif pain >= 60:
        pain -= 2
    elif pain > 0:
        pain -= 1

    vitals["consciousness"] = _clamp(consciousness)
    vitals["stamina"] = _clamp(stamina)
    vitals["body_temp"] = _clamp(body_temp)
    vitals["pain"] = _clamp(pain)

    # ━━ 阶段 3：情绪 → 体征（anger 消耗体力）━━
    # 新量表 50=正常，anger>=75 相当于旧量表 >=50（明显愤怒）
    anger = mood.get("anger", 50)
    if anger >= 75:
        vitals["stamina"] = _clamp(vitals["stamina"] - 2)

    # ━━ 阶段 3b：非危急状态下的基础体力/血氧/意识回复 ━━
    # 仅靠模型输出正向 delta 不可靠；级联又会持续扣体，导致日常剧情也会把体力磨光。
    # 在「可视为正常活动/静息」时向健康基准缓慢回升（与 seq_prompts 中饥饿禁回复一致）。
    _st_r = vitals.get("stamina", 100)
    _th_r = vitals.get("thirst", 0)
    _bl_r = vitals.get("blood_loss", 0)
    _lf_r = organ.get("lung_fill", 0)
    _pn_r = vitals.get("pain", 0)
    _inf_r = vitals.get("infection", 0)
    _stm_r = organ.get("stomach", 0)

    # 血氧恢复独立于饥饿/疼痛门控：气道已畅通（lung_fill<30）且未大量失血即可回升
    _ox_r = vitals.get("oxygen", 100)
    if _ox_r < 100 and _lf_r < 30 and _bl_r < 50:
        vitals["oxygen"] = _clamp(_ox_r + min(4, 100 - _ox_r))

    # 体力与意识恢复：需要整体非危急（含胃部/疼痛门控）
    if (
        _stm_r > 8
        and _th_r < 85
        and _bl_r < 35
        and _lf_r < 50
        and _pn_r < 70
        and _inf_r < 45
    ):
        if _st_r < 100:
            vitals["stamina"] = _clamp(_st_r + 2)
        _co_r = vitals.get("consciousness", 100)
        _ox2 = vitals.get("oxygen", 100)
        if _co_r < 100 and _ox2 > 35 and _bl_r < 25:
            vitals["consciousness"] = _clamp(_co_r + min(3, 100 - _co_r))

    # ━━ 阶段 4：全量情绪级联（读取原始值 → 累加 delta → 统一写回）━━
    # 新量表：50=正常基准，100=极端高，0=极端反面
    # 读取模型输出的基础值（+ 阶段 1 器官效应尚未写入 mood，需累加）
    fear = mood.get("fear", 50)
    anger = mood.get("anger", 50)
    sadness = mood.get("sadness", 50)
    submission = mood.get("submission", 50)
    despair = mood.get("despair", 50)
    arousal = mood.get("arousal", 50)
    pleasure = mood.get("pleasure", 50)
    restraint = vitals.get("restraint", 0)
    courage = mood.get("courage", 50)
    shyness = mood.get("shyness", 50)
    curiosity = mood.get("curiosity", 50)
    nervousness = mood.get("nervousness", 50)

    # 使用最终体征值
    pain = vitals["pain"]
    oxygen = vitals.get("oxygen", 100)
    consciousness = vitals["consciousness"]
    stamina = vitals["stamina"]

    d_fear = d_fear_organ
    d_anger = 0
    d_sadness = 0
    d_submission = 0
    d_despair = 0
    d_arousal = d_arousal_organ
    d_pleasure = 0
    d_courage = 0
    d_shyness = 0
    d_curiosity = 0
    d_nervousness = 0

    # ── 体征 → 情绪（不限幅；非情绪互链）──
    if pain >= 70:
        d_fear += 3
    if pain >= 60:
        d_anger += 3
    if oxygen <= 25:
        d_fear += 5
    if consciousness <= 30:
        d_fear += 3
    if consciousness <= 40:
        d_despair += 2
    if stamina <= 20:
        d_despair += 2
    if stomach <= 8:
        d_despair += 2
    # 口渴 → 情绪（与叙事「严重/极度」档位对齐）
    if thirst >= 90:
        d_despair += 3
        d_fear += 2
    elif thirst >= 80:
        d_despair += 1

    # ── 束缚 → 恐惧/愤怒 ──
    if restraint >= 60:
        d_fear += 3
        d_anger += 3

    # 情绪互链：先累计增减幅度，最后每字段独立钳位 ±_EMOTION_CHAIN_LIMIT
    _EMOTION_CHAIN_LIMIT = 3
    _ec_inc = {k: 0 for k in (
        "fear", "anger", "sadness", "submission", "despair", "arousal",
        "pleasure", "courage", "shyness", "curiosity", "nervousness",
    )}
    _ec_dec = {k: 0 for k in _ec_inc}

    def _ec_i(key: str, amt: int) -> None:
        if amt > 0:
            _ec_inc[key] += amt

    def _ec_d(key: str, amt: int) -> None:
        if amt > 0:
            _ec_dec[key] += amt

    # ── 愤怒抑制效应（旧>=60→新>=75；旧>=70→新>=80）──
    if anger >= 75:
        _ec_d("fear", 2)
    if anger >= 80:
        _ec_d("submission", 2)

    # ── 绝望/顺从抑制愤怒（旧>=70→新>=80）──
    if despair >= 80:
        _ec_d("anger", 2)
    if submission >= 80:
        _ec_d("anger", 2)

    # ── 情绪放大链（旧>=50→新>=70；旧>=60→新>=75；旧>=70→新>=80）──
    if despair >= 70:
        _ec_i("sadness", 2)
    if fear >= 75:
        _ec_i("sadness", 2)
    if sadness >= 75:
        _ec_i("despair", 2)
    if fear >= 80:
        _ec_i("despair", 2)
    if despair >= 75 or fear >= 80:
        _ec_i("submission", 3)

    # ── 所有情绪字段：向中性（50）自然回归 ──
    # 量表：50=正常基准，100=极端高，0=极端低（反面）
    # 规则：>50 每轮向 50 靠拢（幅度随偏离增大）；<50 每轮向 50 回升；50 不变
    # restraint 是物理束缚状态，由实际束缚情况决定，不参与自然衰减
    def _decay(val: int) -> int:
        """情绪向中性值（50）自然回归，偏离越大回归力越强。
        极值段（>=90 / <=10）加强衰减：防止悲伤/恐惧等在正反馈链下长期卡死在顶部，
        同时不影响"主动触发维持高值"的正常场景（模型 delta 仍可覆盖衰减）。"""
        if val >= 95:
            return -8   # 极端顶部：强制加速回归（原 -5）
        if val >= 90:
            return -6   # 次极端：加速回归（原 -4 仅从85起）
        if val >= 85:
            return -4
        if val >= 75:
            return -2
        if val > 50:
            return -1
        if val <= 5:
            return +8   # 极端底部：强制加速回归（原 +5）
        if val <= 10:
            return +6   # 次极端底部（原 +4 仅从15起）
        if val <= 15:
            return +4
        if val <= 25:
            return +2
        if val < 50:
            return +1
        return 0

    d_fear        += _decay(fear)
    d_anger       += _decay(anger)
    d_sadness     += _decay(sadness)
    d_submission  += _decay(submission)
    d_despair     += _decay(despair)
    d_arousal     += _decay(arousal)
    d_pleasure    += _decay(pleasure)
    d_courage     += _decay(courage)
    d_shyness     += _decay(shyness)
    d_curiosity   += _decay(curiosity)
    d_nervousness += _decay(nervousness)

    # ── arousal：疼痛为体征直连；悲伤/恐惧/愉悦为情绪互链 ──
    if pain >= 50:
        d_arousal -= 2
    if sadness >= 75:      # 旧>=70 → 新>=75
        _ec_d("arousal", 1)
    if fear >= 80:
        _ec_d("arousal", 2)
    # 极度愉悦 → 轻微提升 arousal（仅当兴奋仍处高位；避免高潮后 pleasure 仍高时每轮 +1 抵消不应期回落）
    if pleasure >= 80 and arousal >= 70:
        _ec_i("arousal", 1)

    # ── pleasure：疼痛为体征直连；恐惧为情绪互链 ──
    if pain >= 60:
        d_pleasure -= 2
    elif fear >= 75:   # 旧fear>=70 → 新>=75
        _ec_d("pleasure", 2)
    if pleasure >= 65:             # 旧>=60 → 新>=65（15以上正常）
        _ec_d("fear", 1)
        _ec_d("despair", 1)
        _ec_d("sadness", 1)
    # 偏低方向：pleasure 极低 → 悲伤/绝望加剧
    if pleasure <= 30:
        _ec_i("sadness", 1)
        _ec_i("despair", 1)
    if pleasure <= 20:
        _ec_i("sadness", 1)             # 叠加，极度痛苦时悲伤上涨更快

    # ── 悲伤偏低方向：极度开朗 → 悦感增强、绝望消退 ──
    if sadness <= 30:
        _ec_i("pleasure", 1)
        _ec_d("despair", 1)

    # ── 绝望偏低方向：乐观 → 悲伤消退 ──
    if despair <= 30:
        _ec_d("sadness", 1)

    # ── 恐惧/绝望/顺从 → 压制勇气（旧>=70→新>=80；旧>=60→新>=70；旧>=30→删除，那是低于正常值）──
    if fear >= 80:
        _ec_d("courage", 3)
    elif fear >= 70:
        _ec_d("courage", 2)
    elif fear >= 60:
        _ec_d("courage", 1)
    if despair >= 80:
        _ec_d("courage", 2)
    elif despair >= 70:
        _ec_d("courage", 1)
    if submission >= 80:           # 旧>=70 → 新>=80
        _ec_d("courage", 2)
    # 偏低方向：低恐惧/低绝望 → 勇气增长
    if fear <= 30:
        _ec_i("courage", 2)             # 无畏 → 勇气上升
    elif fear <= 40:
        _ec_i("courage", 1)
    if despair <= 30:
        _ec_i("courage", 1)             # 乐观 → 勇气增长
    # 勇气偏低 → 恐惧加剧
    if courage <= 25:
        _ec_i("fear", 2)
    elif courage <= 35:
        _ec_i("fear", 1)

    # ── 义愤/愉悦 → 激发勇气 ──
    if anger >= 70:
        _ec_i("courage", 1)
    if pleasure >= 75:
        _ec_i("courage", 1)
    # ── 高勇气 → 反制恐惧（勇者不惧）──
    if courage >= 70:
        _ec_d("fear", 1)
    # ── 低勇气/高顺从 → 顺从感上升 ──
    if courage <= 30:
        _ec_i("submission", 1)
    # ── 低顺从（强烈反抗）→ 愤怒+勇气上升 ──
    if submission <= 30:
        _ec_i("anger", 1)
        _ec_i("courage", 1)             # 抵抗需要勇气，同时强化勇气

    # ── 愤怒偏低（压抑麻木）→ 悲伤/顺从加剧 ──
    if anger <= 25:
        _ec_i("sadness", 1)
        _ec_i("submission", 1)

    # ── nervousness（紧张）──
    # 高度紧张 → 恐惧上升、愉悦受损
    if nervousness >= 75:
        _ec_i("fear", 1)
        _ec_d("pleasure", 1)
    if nervousness >= 85:          # 极度焦虑 → 绝望加剧
        _ec_i("despair", 1)
    # 极度平静 → 勇气增长、愉悦微升
    if nervousness <= 30:
        _ec_i("courage", 1)
        _ec_i("pleasure", 1)

    # ── shyness（害羞）──
    # 极度害羞 → 紧张上升、顺从倾向增强
    if shyness >= 75:
        _ec_i("nervousness", 1)
        _ec_i("submission", 1)
    if shyness >= 85:              # 非常害羞 → 勇气受压制
        _ec_d("courage", 1)
    # 完全厚脸皮 → 勇气微增、有时带来轻微放肆感（anger+1）
    if shyness <= 30:
        _ec_i("courage", 1)
        _ec_i("anger", 1)

    # ── curiosity（好奇）──
    # 强好奇心 → 焦虑减轻、愉悦微增（专注探索时心境平和）
    if curiosity >= 70:
        _ec_d("nervousness", 1)
        _ec_i("pleasure", 1)
    # 极度冷漠 → 悲伤加剧、愉悦下降（失去兴趣是抑郁前兆）
    if curiosity <= 30:
        _ec_i("sadness", 1)
        _ec_d("pleasure", 1)

    # ── arousal（性兴奋）──
    # 高度兴奋 → 紧张上升、害羞上升（性张力产生社交焦虑）
    if arousal >= 75:
        _ec_i("nervousness", 1)
        _ec_i("shyness", 1)
    if arousal >= 85:              # 极度兴奋 → 理性下降（轻微勇气降低）
        _ec_d("courage", 1)
    # 极低（性冷淡/厌恶）→ 轻微悲伤、愉悦受损
    if arousal <= 25:
        _ec_i("sadness", 1)
        _ec_d("pleasure", 1)

    # ── 高悲伤 → 紧张加剧（哀伤引发焦虑）──
    if sadness >= 80:
        _ec_i("nervousness", 1)

    # ── 恐惧偏低 → 平静感上升 ──
    if fear <= 30:
        _ec_d("nervousness", 1)         # 无畏 → 更平静

    # ── 情绪互链：每字段独立钳位 inc/dec 各至多 3 ──
    d_fear        += min(_ec_inc["fear"], _EMOTION_CHAIN_LIMIT) - min(_ec_dec["fear"], _EMOTION_CHAIN_LIMIT)
    d_anger       += min(_ec_inc["anger"], _EMOTION_CHAIN_LIMIT) - min(_ec_dec["anger"], _EMOTION_CHAIN_LIMIT)
    d_sadness     += min(_ec_inc["sadness"], _EMOTION_CHAIN_LIMIT) - min(_ec_dec["sadness"], _EMOTION_CHAIN_LIMIT)
    d_submission  += min(_ec_inc["submission"], _EMOTION_CHAIN_LIMIT) - min(_ec_dec["submission"], _EMOTION_CHAIN_LIMIT)
    d_despair     += min(_ec_inc["despair"], _EMOTION_CHAIN_LIMIT) - min(_ec_dec["despair"], _EMOTION_CHAIN_LIMIT)
    d_arousal     += min(_ec_inc["arousal"], _EMOTION_CHAIN_LIMIT) - min(_ec_dec["arousal"], _EMOTION_CHAIN_LIMIT)
    d_pleasure    += min(_ec_inc["pleasure"], _EMOTION_CHAIN_LIMIT) - min(_ec_dec["pleasure"], _EMOTION_CHAIN_LIMIT)
    d_courage     += min(_ec_inc["courage"], _EMOTION_CHAIN_LIMIT) - min(_ec_dec["courage"], _EMOTION_CHAIN_LIMIT)
    d_shyness     += min(_ec_inc["shyness"], _EMOTION_CHAIN_LIMIT) - min(_ec_dec["shyness"], _EMOTION_CHAIN_LIMIT)
    d_curiosity   += min(_ec_inc["curiosity"], _EMOTION_CHAIN_LIMIT) - min(_ec_dec["curiosity"], _EMOTION_CHAIN_LIMIT)
    d_nervousness += min(_ec_inc["nervousness"], _EMOTION_CHAIN_LIMIT) - min(_ec_dec["nervousness"], _EMOTION_CHAIN_LIMIT)

    # ── 统一写回 ──
    mood["fear"] = _clamp(fear + d_fear)
    mood["anger"] = _clamp(anger + d_anger)
    mood["sadness"] = _clamp(sadness + d_sadness)
    mood["submission"] = _clamp(submission + d_submission)
    mood["despair"] = _clamp(despair + d_despair)
    mood["arousal"] = _clamp(arousal + d_arousal)
    mood["pleasure"] = _clamp(pleasure + d_pleasure)
    mood["courage"] = _clamp(courage + d_courage)
    mood["shyness"] = _clamp(shyness + d_shyness)
    mood["curiosity"] = _clamp(curiosity + d_curiosity)
    mood["nervousness"] = _clamp(nervousness + d_nervousness)

    # ━━ 阶段 5：最终强制覆盖 ━━
    if vitals["pain"] >= 97:
        vitals["consciousness"] = min(vitals["consciousness"], 10)

    # ━━ 阶段 6：organ_fill 全量值域截断（防止相加后溢出 0-100） ━━
    for _ok in ("stomach", "bladder", "womb", "rectum", "lung_fill", "testicles"):
        if _ok in organ:
            organ[_ok] = max(0, min(100, organ[_ok]))

    # ━━ 阶段 7：失血每轮固定自然恢复（凝血/轻度代谢；在级联与 vital_events 之后结算）━━
    vitals["blood_loss"] = max(0, vitals.get("blood_loss", 0) - 1)


def _check_lock_death_conditions(
    vitals: dict, mood: dict, organ: dict
) -> Tuple[bool, str]:
    """服务端兜底：检查锁分模式所有死亡触发条件（不依赖模型自觉输出 status=lose）。
    返回 (is_death, reason)。
    lung_fill >= 80 时 oxygen 取强制降低后的有效值参与窒息判定。
    """
    blood_loss = vitals.get("blood_loss", 0)
    oxygen = vitals.get("oxygen", 100)
    body_temp = vitals.get("body_temp", 50)
    thirst = vitals.get("thirst", 0)
    infection = vitals.get("infection", 0)
    stamina = vitals.get("stamina", 100)
    pain = vitals.get("pain", 0)  # noqa: F841（保留备用）
    lung_fill = organ.get("lung_fill", 0)

    # lung_fill >= 80 → oxygen 强制跌至 <= 15（级联：再判 oxygen <= 5）
    effective_oxygen = min(oxygen, 15) if lung_fill >= 80 else oxygen

    if blood_loss >= 90:
        return True, "失血性休克（blood_loss≥90）"
    if effective_oxygen <= 5:
        return True, "窒息死亡（oxygen≤5）"
    if body_temp <= 5:
        return True, "冻死/低体温症（body_temp≤5）"
    if body_temp >= 95:
        return True, "高热死亡/中暑（body_temp≥95）"
    if infection >= 92:
        return True, "败血症死亡（infection≥92）"
    if stamina <= 3 and blood_loss >= 70:
        return True, "失血衰竭死亡（stamina≤3且blood_loss≥70）"
    if thirst >= 98:
        return True, "极度脱水死亡（thirst≥98）"
    return False, ""
