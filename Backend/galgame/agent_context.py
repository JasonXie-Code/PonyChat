"""Immutable, save-scoped evidence and compact context for the game Agent."""
from copy import deepcopy
import hashlib
import json
import re

from ..chat_modules.autonomous_prompt_skills import search_profile
from ..chat_modules.reply_repetition_context import build_reply_repetition_context


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def visible(rows):
    return [m for m in rows if isinstance(m, dict) and m.get('role') in ('user', 'assistant')
            and not (m.get('isHidden') or m.get('is_hidden') or m.get('deleted_at') is not None)]


def raw_text(row):
    return str(row.get('rawContent') or row.get('content') or '')


def previous_agent_state(state):
    rows = visible(state.get('messages') or [])
    fingerprints = {message_digest(r) for r in rows}
    for row in reversed(rows):
        if row['role'] == 'assistant':
            try:
                raw = json.loads(raw_text(row))
                value = raw.get('_agent_state', {})
                return deepcopy(value) if valid_notes(raw, fingerprints) else {}
            except (ValueError, AttributeError):
                return {}
    return {}


def state_guard(state):
    """Version/session checked again inside the database write transaction."""
    return {'version': state.get('version'), 'active_session_id': state.get('active_session_id')}


class GameEvidence:
    def __init__(self, state, messages, profile):
        self.profile = profile
        self.rows = []
        # The state was loaded for this username/character/mode/active session.
        for index, row in enumerate(visible(state.get('messages') or [])):
            self.rows.append({'source_id': f'history:{index}', 'role': row['role'],
                              'content': raw_text(row), 'message_id': row.get('message_id')})
        # Only the latest incoming user action is new evidence. Earlier client
        # history is not a source and cannot smuggle another save's messages in.
        latest = next((m for m in reversed(messages) if isinstance(m, dict) and m.get('role') == 'user'), None)
        if latest:
            text = str(latest.get('content') or '')
            if not self.rows or self.rows[-1]['role'] != 'user' or self.rows[-1]['content'] != text:
                self.rows.append({'source_id': 'input:current', 'role': 'user', 'content': text})
        self.read_ids = {'profile:card'}
        self.previous = previous_agent_state(state)
        self.memories = []
        for key in ('shortTermMemory', 'longTermMemory'):
            if state.get(key):
                self.memories.append({'kind': key, 'text': str(state[key])})
        for entry in (state.get('char_memory') or {}).get('entries', []):
            if isinstance(entry, dict):
                self.memories.append({'kind': 'summary', 'text': canonical(entry)})
        # Staged facts live with the delivered reply, so no separate memory
        # commit can survive a failed turn or cross a save boundary.
        fingerprints = {message_digest(r) for r in self.rows}
        for row in self.rows:
            if row['role'] != 'assistant':
                continue
            try:
                raw = json.loads(row['content'])
                if not valid_notes(raw, fingerprints):
                    continue
                notes = raw.get('_agent_state', {})
                for item in notes.get('memories', []):
                    self.memories.append({'kind': 'delivered_fact', 'text': item['text'],
                                          'source_id': row['source_id']})
            except (ValueError, AttributeError, KeyError, TypeError):
                continue

    def page(self, rows, offset=0):
        result = []
        for row in rows:
            content = row['content']
            end = min(len(content), offset + 12000)
            result.append({**row, 'content': content[offset:end], 'offset': offset,
                           'next_offset': end if end < len(content) else None})
            self.read_ids.add(row['source_id'])
        return result

    def context(self):
        recent = self.rows[-12:]
        prose = []
        for row in self.rows:
            content = row['content']
            if row['role'] == 'assistant':
                try:
                    scene = json.loads(content).get('scene', {})
                    content = '\n'.join(str(scene.get(k) or '') for k in
                                        ('env', 'body_state', 'thoughts', 'third_party_dialogue', 'response'))
                except (ValueError, AttributeError):
                    pass
            prose.append({'role': row['role'], 'content': content})
        return {'recent_raw_messages': self.page(recent), 'history_message_count': len(self.rows),
                'previous_agent_state': self.previous,
                'profile_source_id': 'profile:card',
                'reply_repetition_context': build_reply_repetition_context(prose),
                'evidence_note': 'source_id仅属于当前存档；history原文来自服务器，input是当前玩家输入。'}

    async def history(self, args):
        rows = self.rows
        source_id = args.get('source_id')
        if source_id:
            rows = [r for r in rows if r['source_id'] == source_id]
        else:
            before = args.get('before_source_id')
            if before:
                index = next((i for i, r in enumerate(rows) if r['source_id'] == before), None)
                if index is None:
                    return {'messages': [], 'error': '游标不属于当前存档'}
                rows = rows[:index]
            query = str(args.get('query') or '').strip().casefold()
            if query:
                terms = re.findall(r'\w+', query)[:16]
                rows = [r for r in rows if any(t in r['content'].casefold() for t in terms)]
        chosen = rows[-min(8, max(1, args.get('limit', 4))):]
        return {'messages': self.page(chosen, args.get('offset', 0)),
                'next_before_source_id': chosen[0]['source_id'] if len(rows) > len(chosen) else None,
                'hint': '多个关键词用空格分开，匹配任一关键词。无结果不证明事件没发生，可减少关键词或不带query分页。',
                'scope': 'current_save_only'}

    async def reference(self, args):
        result = search_profile(self.profile, args.get('query', ''), args.get('offset'))
        self.read_ids.add('profile:reference')
        return {**result, 'source_id': 'profile:reference'}

    async def search_memory(self, args):
        query = args['query'].strip().casefold()
        terms = re.findall(r'\w+', query)[:16]
        hits = [m for m in self.memories if any(t in m['text'].casefold() for t in terms)]
        return {'items': [{**m, 'text': m['text'][:4000]} for m in hits[-8:]],
                'usable_as_original_quote': False, 'scope': 'current_save_only'}


def source_digest(rows):
    return hashlib.sha256(canonical(rows).encode()).hexdigest()


def message_digest(row):
    return source_digest({'role': row.get('role'), 'content': raw_text(row)})


def seal_notes(data):
    """Bind staged facts to the actual normalized reply, after server rendering."""
    if isinstance(data.get('_agent_state'), dict):
        data['_agent_state']['delivered_content_sha256'] = source_digest(
            {k: v for k, v in data.items() if k != '_agent_state'})


def valid_notes(data, fingerprints):
    notes = data.get('_agent_state') if isinstance(data, dict) else None
    if not isinstance(notes, dict) or notes.get('delivered_content_sha256') != source_digest(
            {k: v for k, v in data.items() if k != '_agent_state'}):
        return False
    return all(ref.get('sha256') in fingerprints for ref in notes.get('sources', []) if isinstance(ref, dict))
