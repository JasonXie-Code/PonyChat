"""One deterministic settlement shared by the game Agent preview and persistence."""
from copy import deepcopy

from .constants import _DEFAULT_CHAR_VITALS, _DEFAULT_CHAR_MOOD, _DEFAULT_ORGAN_FILL, _clamp_vitals_dict
from .vitals import _apply_lock_side_effects, _check_lock_death_conditions

BLOCKS = {'char_vitals': _DEFAULT_CHAR_VITALS, 'char_mood': _DEFAULT_CHAR_MOOD,
          'organ_fill': _DEFAULT_ORGAN_FILL}

LOCK_STATE_RULES = """锁分体征先用preview_lock_state工具结算，再据返回的最终状态写剧情和最终JSON。每次整轮重试也须调用；工具是确定性计算，不是另一个生成模型。
工具只提交changes数组，每项为field/value/reason：field如char_vitals.thirst，value为本轮新事件直接改变后的绝对值，reason说明该事件。没有直接变化就提交changes=[]，不复制三个完整状态对象；服务器自动保留未提交字段。value不是delta，也不是你自己算过联动的最终值。
只结算本轮真正新发生的事件，不重复结算历史、意图或持续状态。进食影响stomach；经口饮水降低thirst并增加bladder；如厕完成须降低对应bladder/rectum；束缚解除降低restraint；器具仅在本轮新插拔或松紧改变时调整，仍佩戴保持原值。提议、递来或准备不等于已吃喝。角色与玩家的动作后果不可混淆。
沿用原分步量级：一口/润喉仅让bladder直接增加1~2；正常一杯增加3~5；大量经口饮水增加8~15，不能把一小口当成大量饮水。这些是基线上的直接增量，转换为value绝对值后提交，服务器每轮膀胱+2另算。一般日常直接变化约±1~±5，中等刺激±5~±15，极端事件±15~±30，超出须有明确事实；不要对失血或缺氧的同一原因再重复扣减意识，阈值联动交由服务器。
服务器负责每轮胃部-1、膀胱+2、直肠+1、口渴+1、体温回归、进食传导、疼痛衰减、健康恢复和所有阈值联动，工具输入不要重复加这些变化。情绪50为中性，体温50为正常；情绪按本轮角色实际体验变化，不因每次关心机械恶化。特殊生理需要应影响角色自主行为和具体回应。
本轮开始时存档已经达到游戏死亡阈值，终局就已成立，工具会保留终局快照；不能通过本轮补写治疗或下调数值恢复生存。救援“刚到”不等于已经完成输血或恢复，应呈现救援赶到时的真实状态。尚未到死亡阈值的及时救治仍可按实际发生的事件结算。
工具返回settled_state是最终三个完整数值对象，必须逐值复制到最终JSON；叙事依据narrative_hints和death判断，不能昏迷却流利说话、剧痛却无事发生，或数值已经恢复而沿用旧症状。工具不写存档；回复验证成功后服务器保存该快照，不再重复计算副作用。
锁分分数活着时下限为1：关系变差本身不能触发死亡。只有本轮实际终局死亡，或工具death=true时，score.current=0、status=lose；普通下降仍playing，达到100为win。死亡时写终局场景，不继续健康活动；仍须输出全部顶层字段，scene.response之后关闭scene对象，身份、事件、选项和三个数值对象都是scene的同级字段。
"""

GAME_CONTINUITY_RULES = """先按原始消息的role还原人称：user原文中的“我”是玩家，“你”是当前角色；assistant历史叙述中的“我”是角色，“你”是玩家。不能沿用上一条assistant里的代词归属去解释最新user消息。用户原文描述“你做了某事”时，动作主体是角色，不是玩家；在最终角色视角转写为“我做了某事”，相应后果结算到角色数值。只有用户原文的“我做了某事”才归玩家。字段player_action只能写玩家实际动作，不能把整条user原文机械塞入该字段。
先在内部确定本轮新事件、角色反应及结果，再让scene各字段和选项共同描述同一轮。玩家推进剧情时须有实质进展，不能只用微表情和同义纠结原地打转；用户明确要求停留则保持地点。已开始的角色行动应适时完成，不能每轮都准备做同一件事。未变化的环境简写，把篇幅给当前真正重要的对白、动作或心理；第三者仅被提及不等于在场，已离开的NPC不得无故说话。选项始终从玩家视角出发，符合角色当前体征和场景，不替玩家作出新选择。"""


def baseline(state):
    result = {key: _clamp_vitals_dict({**defaults, **(state.get(key) or {})}, defaults)
              for key, defaults in BLOCKS.items()}
    if not state.get('char_mood'):
        for key, delta in (state.get('_init_mood_delta') or {}).items():
            if key in result['char_mood']:
                result['char_mood'][key] = max(0, min(100, result['char_mood'][key] + delta))
    return result


def settle(previous, direct):
    if _check_lock_death_conditions(previous['char_vitals'], previous['char_mood'], previous['organ_fill'])[0]:
        # A terminal saved snapshot cannot be resurrected by an ordinary turn's
        # healing deltas. Loading/restarting a game establishes a new baseline.
        return deepcopy(previous)
    result = deepcopy(direct)
    stomach_delta = result['organ_fill']['stomach'] - previous['organ_fill']['stomach']
    if stomach_delta > 0:
        result['organ_fill']['rectum'] = min(100, result['organ_fill']['rectum'] + round(stomach_delta / 3))
    _apply_lock_side_effects(result['char_vitals'], result['char_mood'], result['organ_fill'])
    return result


def preview_tool(request, state):
    from ..chat_modules.harness_runtime import HarnessTool, HarnessToolValidationError
    before = baseline(state)
    terminal_at_start = _check_lock_death_conditions(before['char_vitals'], before['char_mood'], before['organ_fill'])[0]
    request._galgame_lock_settlement = None
    paths = [block + '.' + key for block, defaults in BLOCKS.items() for key in defaults]

    async def preview(args):
        direct, explanations = deepcopy(before), {}
        for change in args['changes']:
            path, value = change['field'], change['value']
            if path not in paths or path in explanations:
                raise HarnessToolValidationError('直接变化字段未知或重复：' + path)
            if type(value) is not int or not 0 <= value <= 100:
                raise HarnessToolValidationError('体征须为0到100整数')
            reason = str(change.get('reason') or '').strip()
            if not reason:
                raise HarnessToolValidationError('直接变化缺少本轮事件依据：' + path)
            block, key = path.split('.')
            direct[block][key], explanations[path] = value, reason
        settled = settle(before, direct)
        dead, reason = _check_lock_death_conditions(settled['char_vitals'], settled['char_mood'], settled['organ_fill'])
        from .hints import _build_lock_vitals_hints
        hints = _build_lock_vitals_hints(settled['char_vitals'], settled['char_mood'], settled['organ_fill'],
            str(getattr(request, '_galgame_char_name', '') or ''), str(args.get('character_gender') or ''))
        request._galgame_lock_settlement = {'baseline': deepcopy(before), 'settled_state': deepcopy(settled),
            'direct_state': deepcopy(direct), 'change_reasons': deepcopy(explanations), 'death': dead, 'death_reason': reason}
        if dead:
            hints = ('终局：根据本次死亡原因描写停止活动的身体，不再套用濒死求救动作。',
                     '终局：只写意识消退前的最后感受或意识已经终止，不产生死后新的心理活动。',
                     '终局：呈现本轮生命终止的结果，不继续求救或健康活动。')
        return {'settled_state': settled, 'death': dead, 'death_reason': reason,
                'terminal_at_start': terminal_at_start,
                'narrative_hints': dict(zip(('body_state', 'thoughts', 'response'), hints)),
                'note': ('存档已达到死亡阈值，本轮治疗变化不再生效，必须保持终局。' if terminal_at_start else '') +
                        '完整复制settled_state到最终JSON顶层的三个同名对象，不放入scene；不要再次加减。未变化的身份、事件和选项也完整输出。尚未写入存档。'}

    return HarnessTool(preview, '结算本轮锁分状态并预览剧情所需的真实体征；不会写库。', {
        'type': 'object', 'properties': {'changes': {'type': 'array', 'maxItems': len(paths),
            'items': {'type': 'object', 'properties': {
                'field': {'type': 'string', 'enum': paths},
                'value': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                'reason': {'type': 'string', 'minLength': 1, 'maxLength': 160}},
                'required': ['field', 'value', 'reason'], 'additionalProperties': False}},
            'character_gender': {'type': 'string', 'maxLength': 20}},
        'required': ['changes', 'character_gender'], 'additionalProperties': False})


def validate_preview(request, data, state):
    receipt = getattr(request, '_galgame_lock_settlement', None)
    if not receipt:
        return '锁分最终回复前须先调用preview_lock_state完成本轮体征结算'
    if baseline(state) != receipt['baseline']:
        return '存档基线已变化，本轮预览过期'
    for block in BLOCKS:
        if data.get(block) != receipt['settled_state'][block]:
            return '最终' + block + '须逐值复制本轮preview_lock_state返回的settled_state，不能重新计算'
    if receipt['death'] and (data['score'].get('status') != 'lose' or data['score'].get('current') != 0):
        return '本轮体征结算已触发终局死亡，score须为current=0、status=lose，场景须对齐终局'
    return ''
