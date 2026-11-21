"""Unique-owner expression manuals plus a fail-closed, serial read contract."""
from __future__ import annotations

import json

from expression_path_experiment import PATHS, WHEN, partition

OWNERS = {
    'reply_expression': (1, 2, 4, 6, 8, 12, 13, 14, 16, 17),
    'reply_conditions': (7,),
    'conversation_reply': (5, 9),
    'interaction_reply': (10, 11, 15),
    'description_reply': (),
    'reply_perspective': (3,),
    'reply_review': (18,),
}
DEPENDENCIES = {
    'reply_expression': (),
    'reply_conditions': ('reply_expression',),
    'reply_perspective': ('reply_conditions',),
    'conversation_reply': ('reply_conditions',),
    'interaction_reply': ('reply_perspective',),
    'description_reply': ('reply_perspective',),
}
LINKS = {
    'reply_expression': '接着串行调用load_chat_skill读取reply_conditions。',
    'reply_conditions': '依据本轮输入用select_reply_paths声明适用路径。混合任务可以多选；按工具返回的next_required串行读取。',
    'conversation_reply': '其他当前任务通过select_reply_paths追加适用路径；完成全部路径后读取reply_review。',
    'interaction_reply': '其他当前任务通过select_reply_paths追加适用路径；完成全部路径后读取reply_review。',
    'description_reply': '描写的人称规则见reply_perspective，触发条件见reply_conditions；具体描写目标和承载要求遵守已适用的shortcut、narrative与delivery，不在此复制其正文。完成全部路径后读取reply_review。',
    'reply_perspective': '接着读取next_required指定的已选路径。',
    'reply_review': '按上面的原规则复核，然后提交回复；若新增任务路径，先完成新增路径及依赖，再读取本技能。',
}


def serial_session_class(base, full_text, tool_class):
    rules = partition(full_text)
    owners = [number for numbers in OWNERS.values() for number in numbers]
    assert sorted(owners) == list(range(1, 19)), 'Every original rule must have exactly one owner'

    class SerialSession(base):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.selected_paths = []
            self.gate_events = []
            self.route_input = None
            for name, numbers in OWNERS.items():
                hint = WHEN.get(name, '按表达技能返回的next_required串行读取。')
                body = '\n'.join(rules[i] for i in numbers)
                self.catalog[name] = (hint, body + '\n' + LINKS[name])

        def transform(self, prompt, system, *, allow_tools=True):
            data = json.loads(prompt if isinstance(prompt, str) else
                              next(block['text'] for block in prompt if block.get('type') == 'text'))
            batch = data.get('current_user_batch') or [data.get('latest_user_message') or {}]
            identity = json.dumps([
                [{key: row.get(key) for key in ('message_id', 'content', 'image_url', 'attachments')}
                 for row in batch], bool(data.get('description_shortcut_contract'))
            ], ensure_ascii=False, sort_keys=True)
            if self.route_input is not None and identity != self.route_input:
                self.selected_paths = []
                self.loaded.difference_update(set(PATHS) | {'reply_review'})
                self.gate_events.append({'status': 'input_changed', 'next_required': 'select_reply_paths'})
            self.route_input = identity
            return super().transform(prompt, system, allow_tools=allow_tools)

        def skill_instructions(self, name):
            if name in OWNERS:
                return '【' + name + '】\n' + self.catalog[name][1]
            return super().skill_instructions(name)

        def next_required(self):
            for name in ('reply_expression', 'reply_conditions'):
                if name not in self.loaded:
                    return name
            if not self.selected_paths:
                return 'select_reply_paths'
            for path in self.selected_paths:
                for dependency in DEPENDENCIES[path]:
                    if dependency not in self.loaded:
                        return dependency
                if path not in self.loaded:
                    return path
            if 'reply_review' not in self.loaded:
                return 'reply_review'
            return None

        async def select_paths(self, args):
            paths = args.get('paths')
            if (not isinstance(paths, list) or not paths or len(paths) != len(set(paths)) or
                    any(path not in PATHS for path in paths)):
                raise ValueError('paths must contain unique known expression paths')
            if any(name not in self.loaded for name in ('reply_expression', 'reply_conditions')):
                return {'status': 'blocked', 'next_required': self.next_required()}
            # The explicit shortcut contract is authoritative, not a keyword guess.
            if self.task_snapshot.get('description_shortcut_contract') and 'description_reply' not in paths:
                return {'status': 'blocked', 'reason': '当前明确描写合同必须选择description_reply。',
                        'next_required': 'select_reply_paths'}
            added = [path for path in paths if path not in self.selected_paths]
            if added:
                self.selected_paths.extend(added)
                self.loaded.discard('reply_review')
            return {'status': 'selected', 'paths': list(self.selected_paths), 'next_required': self.next_required()}

        async def load(self, args):
            name = args['name']
            if name not in OWNERS:
                return await super().load(args)
            if name in self.loaded:
                return {'status': 'already_loaded', 'skill': name, 'next_required': self.next_required()}
            required = self.next_required()
            if name != required:
                event = {'status': 'blocked', 'requested': name, 'next_required': required,
                         'reason': '按next_required串行读取；尚未完成的依赖或选择不得跳过。'}
                self.gate_events.append(event)
                return event
            result = await super().load(args)
            result['next_required'] = self.next_required()
            return result

        def runner(self, base_runner):
            async def with_selector(prompt, config, tools, **options):
                tools = dict(tools)
                if options.get('max_tool_calls') != 0:
                    tools['select_reply_paths'] = tool_class(
                        self.select_paths,
                        '读取reply_conditions后声明本轮表达路径；日常接话、当前动作互动、明确描写可按真实任务组合。不要为仅有历史动作选择动作路径。',
                        {'type': 'object', 'properties': {'paths': {'type': 'array', 'minItems': 1,
                         'maxItems': 3, 'items': {'type': 'string', 'enum': list(PATHS)}}},
                         'required': ['paths'], 'additionalProperties': False})
                return await base_runner(prompt, config, tools, **options)

            wrapped = super().runner(with_selector)

            async def guarded(prompt, config, tools, **options):
                current = prompt
                for attempt in range(3):
                    result = await wrapped(current, config, tools, **options)
                    if result.get('finish_reason') != 'completed' or self.next_required() is None:
                        return result
                    missing = self.next_required()
                    self.gate_events.append({'status': 'delivery_blocked', 'next_required': missing,
                                             'attempt': attempt})
                    if attempt == 2 or options.get('max_tool_calls') == 0 or options.get('force_no_tools'):
                        raise RuntimeError('Expression read contract incomplete: ' + missing)
                    data = json.loads(prompt)
                    data['previous_attempt'] = {'reply': result.get('final_response', '')}
                    data['completion_feedback'] = ('回复尚未交付：表达路径读取合同未完成。下一步调用'
                        + ('select_reply_paths声明适用路径' if missing == 'select_reply_paths'
                           else 'load_chat_skill读取' + missing)
                        + '，按返回的next_required串行完成，不能跳过。保留用户原意及已确认事实。')
                    current = json.dumps(data, ensure_ascii=False)
                raise AssertionError('unreachable')

            return guarded

    return SerialSession
