"""Serial expression skill dependencies and delivery completeness guard."""
from __future__ import annotations
import json
from copy import deepcopy
from .Prompts import CHAT_SKILL_TEXTS, SKILL_WHEN, EXPRESSION_PATH_TEXT

OWNERS = ('reply_expression', 'reply_conditions', 'conversation_reply', 'interaction_reply', 'description_reply', 'reply_perspective', 'reply_deduplication', 'reply_review')
PATHS = ('conversation_reply', 'interaction_reply', 'description_reply')
DEPENDENCIES = {
    'reply_expression': (),
    'reply_conditions': ('reply_expression',),
    'reply_perspective': ('reply_conditions',),
    'conversation_reply': ('reply_conditions',),
    'interaction_reply': ('reply_perspective',),
    'description_reply': ('reply_perspective',),
}

class ExpressionReadIncomplete(RuntimeError):
    retryable = False


def serial_session_class(base, tool_class):
    class SerialSession(base):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.selected_paths = []
            self.gate_events = []
            self.route_input = None
            self.deduplication_reads = []
            self.deduplication_read_reason = 'initial'
            for name in OWNERS:
                self.catalog[name] = (SKILL_WHEN[name], CHAT_SKILL_TEXTS[name])

        def prepare_task_manuals(self, data):
            super().prepare_task_manuals(data)
            data['expression_read_contract'] = self.read_progress()
            data['available_skills'] = [row for row in data['available_skills']
                                        if row['name'] not in OWNERS or row['name'] == 'reply_expression']

        def update_route_input(self, data):
            batch = data.get('current_user_batch') or [data.get('latest_user_message') or {}]
            identity = json.dumps([
                [{key: row.get(key) for key in ('message_id', 'content', 'image_url', 'attachments')}
                 for row in batch], bool(data.get('description_shortcut_contract'))
            ], ensure_ascii=False, sort_keys=True)
            if self.route_input is not None and identity != self.route_input:
                self.deduplication_read_reason = 'input_changed'
                self.selected_paths = []
                self.loaded.difference_update(set(PATHS) | {'reply_deduplication', 'reply_review'})
                self.gate_events.append({'status': 'input_changed', 'next_required': 'select_reply_paths'})
            self.route_input = identity

        def transform(self, prompt, system, *, allow_tools=True):
            data = json.loads(prompt if isinstance(prompt, str) else
                              next(block['text'] for block in prompt if block.get('type') == 'text'))
            self.update_route_input(data)
            return super().transform(prompt, system, allow_tools=allow_tools)

        def bind_live_input(self, channel):
            if channel is None or channel is self.input_channel:
                return
            super().bind_live_input(channel)
            prepare = channel.prepare_input

            async def update(rows):
                blocks = await prepare(rows)
                self.update_route_input(self.task_snapshot)
                for block in blocks:
                    if block.get('type') == 'text':
                        data = json.loads(block['text'])
                        data['expression_read_contract'] = self.read_progress()
                        block['text'] = json.dumps(data, ensure_ascii=False)
                        break
                return blocks

            channel.prepare_input = update

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
            for name in ('reply_deduplication', 'reply_review'):
                if name not in self.loaded:
                    return name
            return None

        def read_progress(self):
            required = self.next_required()
            if required is None:
                call = None
            elif required == 'select_reply_paths':
                call = {'tool': 'select_reply_paths', 'required_arguments': ['paths'],
                        'choose_from': [{'name': name, 'when': SKILL_WHEN[name]} for name in PATHS],
                        'required_paths': ['description_reply'] if self.task_snapshot.get(
                            'description_shortcut_contract') else []}
            else:
                call = {'tool': 'read_next_reply_skill', 'arguments': {}, 'reads': required}
            return {'complete': required is None, 'selected_paths': list(self.selected_paths),
                    'next_call': call}

        def with_progress(self, result):
            return {**result, 'next_required': self.next_required(), **self.read_progress()}

        async def read_next(self, args):
            if args:
                raise ValueError('read_next_reply_skill takes no arguments')
            name = self.next_required()
            if name is None or name == 'select_reply_paths':
                return self.with_progress({'status': 'complete' if name is None else 'selection_required'})
            return await self.load({'name': name})

        async def select_paths(self, args):
            paths = args.get('paths')
            if (not isinstance(paths, list) or not paths or
                    any(not isinstance(path, str) or path not in PATHS for path in paths) or
                    len(paths) != len(set(paths))):
                raise ValueError('paths must contain unique known expression paths')
            if any(name not in self.loaded for name in ('reply_expression', 'reply_conditions')):
                return self.with_progress({'status': 'blocked'})
            # The explicit shortcut contract is authoritative, not a keyword guess.
            if self.task_snapshot.get('description_shortcut_contract') and 'description_reply' not in paths:
                return {'status': 'blocked', 'reason': EXPRESSION_PATH_TEXT['text_1'],
                        'next_required': 'select_reply_paths'}
            added = [path for path in paths if path not in self.selected_paths]
            if added:
                self.selected_paths.extend(added)
                if 'reply_deduplication' in self.loaded:
                    self.deduplication_read_reason = 'path_added'
                self.loaded.difference_update({'reply_deduplication', 'reply_review'})
            return self.with_progress({'status': 'selected', 'paths': list(self.selected_paths)})

        async def load(self, args):
            if 'names' in args:
                names = args['names']
                if (not isinstance(names, list) or not names or 'name' in args
                        or any(not isinstance(name, str) or name not in self.catalog for name in names)):
                    raise ValueError('Provide a valid names list')
                results = []
                for name in dict.fromkeys(names):
                    result = await self.load({'name': name})
                    results.append(result)
                    if result.get('status') == 'blocked':
                        break
                return self.with_progress({'skills': results})
            name = args['name']
            if name not in OWNERS:
                return await super().load(args)
            if name in self.loaded:
                return self.with_progress({'status': 'already_loaded', 'skill': name})
            required = self.next_required()
            if name != required:
                event = {'status': 'blocked', 'requested': name, 'next_required': required,
                         'reason': EXPRESSION_PATH_TEXT['text_2']}
                self.gate_events.append(event)
                return event
            result = await super().load(args)
            if name == 'reply_deduplication' and name in self.loaded:
                self.deduplication_reads.append(self.deduplication_read_reason)
            return self.with_progress(result)

        def runner(self, base_runner):
            async def with_selector(prompt, config, tools, **options):
                tools = dict(tools)
                if 'load_chat_skill' in tools and not options.get('delivery_only'):
                    tools['read_next_reply_skill'] = tool_class(
                        self.read_next, EXPRESSION_PATH_TEXT['read_next'],
                        {'type': 'object', 'properties': {}, 'additionalProperties': False})
                    tools['select_reply_paths'] = tool_class(
                        self.select_paths,
                        EXPRESSION_PATH_TEXT['text_3'],
                        {'type': 'object', 'properties': {'paths': {'type': 'array', 'minItems': 1,
                         'maxItems': 3, 'items': {'type': 'string', 'enum': list(PATHS)}}},
                         'required': ['paths'], 'additionalProperties': False})
                return await base_runner(prompt, config, tools, **options)

            wrapped = super().runner(with_selector)

            async def guarded(prompt, config, tools, **options):
                result = await wrapped(prompt, config, tools, **options)
                if result.get('finish_reason') == 'completed' and self.next_required() is not None:
                    missing = self.next_required()
                    self.gate_events.append({'status': 'delivery_blocked', 'next_required': missing,
                                             'attempt': 0})
                    exc = ExpressionReadIncomplete('Expression read contract incomplete: ' + missing)
                    exc.harness_usage = {key: deepcopy(result[key]) for key in
                                         ('usage', 'llm_api_calls', 'tool_call_count') if key in result}
                    raise exc
                return result

            return guarded

    return SerialSession
