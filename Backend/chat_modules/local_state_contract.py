"""Expose the existing post-reply JSON types explicitly to local models."""
from .autonomous_scene_state import FIELDS
from .autonomous_normal import _source_message_times


def add_local_state_contract(prompt, messages, replies, snapshot):
    refs = {'type': 'array', 'minItems': 1, 'maxItems': 8,
            'items': {'type': 'string', 'enum': prompt['allowed_source_ids']}}
    change = {'type': 'object', 'required': ['value', 'source_message_ids'],
              'additionalProperties': False, 'properties': {
                  'value': {'type': ['string', 'null'], 'maxLength': 600}, 'source_message_ids': refs}}
    changes = {'type': 'object', 'maxProperties': 48,
               'description': '字段名作为键的JSON对象，不是field/value条目数组。未知状态value为null，不编造位置或接触。',
               'properties': {field: change for field in sorted(FIELDS)},
               'additionalProperties': change}
    if not snapshot['fields']:
        changes['required'] = sorted(FIELDS)
    prompt['source_message_times'] = _source_message_times([*messages, *replies])
    prompt['output_json_schema'] = {
        'type': 'object', 'required': ['scene_patch', 'memories', 'followup_decision'],
        'additionalProperties': False, 'properties': {
            'scene_patch': {'type': 'object', 'required': ['reset', 'changes'],
                            'additionalProperties': False, 'properties': {
                                'reset': {'type': 'boolean'}, 'changes': changes}},
            'memories': {'type': 'array', 'maxItems': 8, 'items': {
                'type': 'object', 'additionalProperties': False,
                'required': ['content', 'source_message_ids', 'category', 'importance', 'certainty', 'occurred_at'],
                'properties': {
                    'content': {'type': 'string', 'maxLength': 50, 'description': '沿用对话语言记录新增事实'},
                    'source_message_ids': refs,
                    'category': {'enum': ['fact', 'preference', 'episode', 'activity', 'commitment', 'relationship', 'understanding']},
                    'importance': {'type': 'integer', 'minimum': 1, 'maximum': 10},
                    'certainty': {'enum': ['explicit', 'observed', 'inferred']},
                    'occurred_at': {'type': ['string', 'null'],
                                    'description': '未知则null；已知则复制source_message_times的ISO时间，禁止数字时间戳或臆造日期'}}}},
            'followup_decision': {'type': 'object', 'required': ['enabled', 'reason'],
                'properties': {'enabled': {'type': 'boolean'}, 'reason': {'type': 'string'},
                               'summary': {'type': 'string'}, 'target_delay_seconds': {'type': 'integer'}}}}}
