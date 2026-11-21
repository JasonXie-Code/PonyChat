"""Per-turn tools, evidence gates and reviewed-output receipt; no writes here."""
from copy import deepcopy
import json

from ..chat_modules.harness_runtime import HarnessTool, HarnessToolValidationError
from .agent_context import GameEvidence, canonical, source_digest, message_digest
from .agent_skills import CATALOG
from .lock_state import validate_preview


def obj(properties, required=None):
    return {'type': 'object', 'properties': properties, 'required': list(properties) if required is None else required,
            'additionalProperties': False}


def string(maximum=800, **kwargs):
    return {'type': 'string', 'maxLength': maximum, **kwargs}


def array(item, maximum=32):
    return {'type': 'array', 'items': item, 'maxItems': maximum}


REFS = array(string(100, minLength=1), 10)
STATE_FIELDS = ('character_pose', 'player_pose', 'character_position', 'player_position',
                'character_gender', 'player_gender', 'character_race', 'player_race',
                'character_outfit', 'player_outfit', 'scene.time', 'scene.location')


def prior_fields(state):
    result = dict(state)
    for row in reversed(state.get('messages') or []):
        if isinstance(row, dict) and row.get('role') == 'assistant' and not (
                row.get('isHidden') or row.get('is_hidden') or row.get('deleted_at') is not None):
            try:
                result = {**json.loads(row.get('rawContent') or row.get('content') or ''), **result}
            except (ValueError, TypeError):
                pass
            break
    return result


def field_value(data, field):
    parts = field.split('.')
    if len(parts) == 2:
        return (data.get(parts[0]) or {}).get(parts[1])
    return data.get(field)


class GameAgentSession:
    def __init__(self, request, state, messages, profile, mode):
        self.request, self.state, self.mode = request, deepcopy(state), mode
        self.evidence = GameEvidence(state, messages, profile)
        self.loaded = set()
        self.trace = []
        self.receipt = None
        self.required = {'core', 'expression', 'relationship', 'options', 'character_body'}
        if mode == 'galgame_lock':
            self.required.add('lock_settlement')

    def context(self):
        return {**self.evidence.context(), 'required_skills': sorted(self.required),
                'available_skills': [{'name': k, 'when': v[0]} for k, v in CATALOG.items()
                                     if self.mode == 'galgame_lock' or k != 'lock_settlement']}

    def require_skills(self):
        missing = self.required - self.loaded
        if missing:
            raise HarnessToolValidationError('先用load_game_skill批量读取：' + ','.join(sorted(missing)))

    async def load(self, args):
        names = args['names']
        if not names or any(n not in CATALOG or n == 'lock_settlement' and self.mode != 'galgame_lock' for n in names):
            raise HarnessToolValidationError('技能名不在本轮目录中')
        self.loaded.update(names)
        return {'skills': [{'name': n, 'text': CATALOG[n][1]} for n in dict.fromkeys(names)]}

    def refs(self, refs, *, allow_reply=True):
        allowed = self.evidence.read_ids | ({'$reply'} if allow_reply else set())
        if not refs or any(r not in allowed for r in refs):
            raise HarnessToolValidationError('证据须引用本轮实际读到的source_id；新角色行为可用$reply')

    async def review(self, args):
        self.receipt = None
        self.require_skills()
        try:
            draft = json.loads(args['draft_json'])
        except ValueError as exc:
            raise HarnessToolValidationError('draft_json不是合法JSON') from exc
        if not isinstance(draft, dict) or '_agent_state' in draft:
            raise HarnessToolValidationError('草稿必须是完整游戏对象，不自行填写_agent_state')
        from .output_contract import game_output_contract
        contract = game_output_contract(self.mode)
        if set(contract['required_top_fields']) - draft.keys():
            raise HarnessToolValidationError('草稿缺少完整游戏字段')
        scene, options = draft.get('scene'), draft.get('suggested_options')
        if not isinstance(scene, dict) or any(k not in scene for k in contract['required_object_keys']['scene']):
            raise HarnessToolValidationError('草稿缺少完整scene')
        if not isinstance(options, list) or len(options) != 5 or any(not isinstance(o, dict) for o in options):
            raise HarnessToolValidationError('须有恰好五个玩家选项')
        labels = [str(o.get('label') or '').strip() for o in options]
        if not all(labels) or len(set(labels)) != 5:
            raise HarnessToolValidationError('选项为空或完全重复，请生成不同走向')
        effects = set()
        for event in args['events']:
            self.refs(event['source_message_ids'], allow_reply=event['subject'] != 'player')
            if event['subject'] == 'player' and any(r.startswith('profile:') for r in event['source_message_ids']):
                raise HarnessToolValidationError('角色设定不能作为玩家动作的证据')
            if event['effect_fields'] and event['status'] != 'completed':
                raise HarnessToolValidationError('提议或尝试不能作为已完成事件结算体征')
            if event['kind'] == 'drink' and event['subject'] == 'player' and event['effect_fields']:
                raise HarnessToolValidationError('玩家自己饮水不能改变角色体征')
            if event['kind'] == 'drink' and event['quantity'] == 'none':
                raise HarnessToolValidationError('饮水事件须说明sip/cup/large量级')
            effects.update(event['effect_fields'])
        if self.mode == 'galgame_lock':
            error = validate_preview(self.request, draft, self.state)
            if error:
                raise HarnessToolValidationError(error)
            changed = set(self.request._galgame_lock_settlement['change_reasons'])
            if changed != effects:
                raise HarnessToolValidationError('completed事件的effect_fields须与preview直接变化字段完全一致')
            receipt = self.request._galgame_lock_settlement
            drinks = [e for e in args['events'] if e['kind'] == 'drink' and e['subject'] == 'character'
                      and e['status'] == 'completed']
            other_bladder_effect = any(e not in drinks and 'organ_fill.bladder' in e['effect_fields']
                                       for e in args['events'])
            if drinks and not receipt['death'] and not other_bladder_effect:
                amounts = {'sip': (1, 2), 'cup': (3, 5), 'large': (8, 15)}
                lower = sum(amounts[e['quantity']][0] for e in drinks)
                upper = sum(amounts[e['quantity']][1] for e in drinks)
                prior = receipt['baseline']['organ_fill']['bladder']
                value = receipt['direct_state']['organ_fill']['bladder']
                if not min(100, prior + lower) <= value <= min(100, prior + upper):
                    raise HarnessToolValidationError(f'饮水直接膀胱值须为{min(100, prior + lower)}到{min(100, prior + upper)}；'
                        '不含服务器每轮+2。请重新preview_lock_state，再按结果改草稿并review。')
        elif effects:
            raise HarnessToolValidationError('普通游戏没有锁分体征变化')
        before = prior_fields(self.state)
        flags = draft.get('event_flags') or {}
        fields = (*STATE_FIELDS, *('event_flags.' + k for k in flags))
        changed = {f for f in fields if field_value(before, f) != field_value(draft, f)}
        changes = args['state_changes']
        if len({c['field'] for c in changes}) != len(changes) or any(c['field'] not in fields for c in changes):
            raise HarnessToolValidationError('状态变化字段未知或重复')
        # Initial false event flags are schema defaults, not newly occurred events.
        changed = {f for f in changed if not (f.startswith('event_flags.') and field_value(draft, f) is False)}
        if changed - {c['field'] for c in changes}:
            raise HarnessToolValidationError('状态变化缺少依据：' + ','.join(sorted(changed - {c['field'] for c in changes})))
        for change in changes:
            self.refs(change['source_message_ids'])
        relationship = args['relationship']
        self.refs(relationship['source_message_ids'])
        if relationship['stage'] != draft.get('relationship_stage'):
            raise HarnessToolValidationError('内部关系stage须等于最终relationship_stage')
        for memory in args['memories']:
            self.refs(memory['source_message_ids'])
        self.receipt = {'draft': deepcopy(draft), 'metadata': {
            'version': 1, 'events': deepcopy(args['events']), 'state_changes': deepcopy(changes),
            'consistency_checks': deepcopy(args['consistency_checks']),
            'relationship': deepcopy(relationship), 'memories': deepcopy(args['memories']),
            'sources': [{'source_id': r['source_id'], 'message_id': r.get('message_id'),
                         'sha256': message_digest(r)} for r in self.evidence.rows
                        if r['source_id'] in self.evidence.read_ids],
            'profile_sha256': source_digest(self.evidence.profile),
            'skills': sorted(self.loaded)}}
        return {'accepted': True, 'instruction': '交付这份完整draft_json；若改动任何字段须重新复核。尚未写入存档。'}

    def finish(self, text):
        try:
            value = json.loads(text)
        except ValueError as exc:
            raise ValueError('Game Agent final reply is not JSON') from exc
        if not self.receipt or canonical(value) != canonical(self.receipt['draft']):
            raise ValueError('Game Agent must deliver the exact draft accepted by review_game_turn')
        value['_agent_state'] = self.receipt['metadata']
        return json.dumps(value, ensure_ascii=False)

    def tools(self):
        def tool(name, callback, description, schema):
            async def observed(args):
                result = await callback(args)
                self.trace.append({'tool': name, 'arguments': deepcopy(args), 'result': deepcopy(result)})
                return result
            return HarnessTool(observed, description, schema)
        tools = {
            'load_game_skill': tool('load_game_skill', self.load, '批量读取本轮游戏技能。',
                obj({'names': array(string(40, enum=list(CATALOG)), 8)})),
            'read_character_reference': tool('read_character_reference', self.evidence.reference,
                '按关键词检索完整角色原始设定，或按offset分页。', obj({
                    'query': string(200), 'offset': {'type': 'integer', 'minimum': 0}}, [])),
            'read_game_history': tool('read_game_history', self.evidence.history,
                '仅读当前存档可见原文；query关键词，before_source_id向前翻页，source_id与offset读取长消息。', obj({
                    'query': string(200), 'before_source_id': string(100), 'source_id': string(100),
                    'offset': {'type': 'integer', 'minimum': 0},
                    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 8}}, [])),
            'search_game_memory': tool('search_game_memory', self.evidence.search_memory,
                '查当前存档摘要与随已交付回合保存的事实；引用原话须再读原文。', obj({'query': string(200, minLength=1)})),
            'review_game_turn': tool('review_game_turn', self.review,
                '交付前复核完整草稿、事件归属、状态证据、关系及记忆；仅暂存，失败不写库。', obj({
                    'draft_json': string(32768, minLength=2),
                    'consistency_checks': obj({key: string(800, minLength=8) for key in (
                        'body_and_actions', 'state_and_speech', 'player_options', 'progress_and_repetition')}),
                    'events': array(obj({'subject': string(enum=['player', 'character', 'third_party']),
                        'kind': string(enum=['other', 'drink']), 'quantity': string(enum=['none', 'sip', 'cup', 'large']),
                        'status': string(enum=['proposed', 'attempted', 'completed']),
                        'description': string(minLength=1), 'source_message_ids': REFS,
                        'effect_fields': array(string(80, description='仅锁分直接体征字段，如organ_fill.bladder；普通游戏必须为空。'),
                                               50 if self.mode == 'galgame_lock' else 0)})),
                    'state_changes': array(obj({'field': string(100), 'reason': string(minLength=1), 'source_message_ids': REFS}), 50),
                    'relationship': obj({'stage': string(40), 'intimacy_style': string(enum=['reserved', 'balanced', 'expressive']),
                        'pressure': string(enum=['low', 'medium', 'high']), 'willingness': string(minLength=1),
                        'reason': string(minLength=1), 'source_message_ids': REFS}),
                    'memories': array(obj({'text': string(minLength=1), 'source_message_ids': REFS}), 8)})),
        }
        return tools
