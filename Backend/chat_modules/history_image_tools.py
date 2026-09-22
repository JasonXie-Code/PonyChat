"""Account-bound discovery and native visual rereading of old chat images."""
from .Prompts import HISTORY_IMAGE_TOOLS_TEXT
import asyncio
import base64
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from .autonomous_images import resolve_harness_image_blocks
from .history_image_transfer import request_from_phone


IMAGE_SOURCE_RULE = (HISTORY_IMAGE_TOOLS_TEXT['IMAGE_SOURCE_RULE_1'])


class HistoryImageTools:
    def __init__(self, db_path, *, username, character_id, conversation_id, allowed_message_ids=None):
        self.db_path = db_path
        self.scope = (username, character_id, conversation_id)
        self._catalog_image_counts = {}
        self.allowed_message_ids = None if allowed_message_ids is None else tuple(sorted(set(allowed_message_ids)))
        self.repeated = []

    def _rows(self, message_ids):
        if not all(self.scope) or not message_ids or self.allowed_message_ids == ():
            return []
        with closing(sqlite3.connect(Path(self.db_path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            columns = {r[1] for r in conn.execute('PRAGMA table_info(messages)')}
            conditions = ['u.username=?', 'c.character_id=?', 'c.id=?',
                          'COALESCE(c.is_hidden,0)=0', "m.role IN ('user','assistant')"]
            scope_args = list(self.scope)
            if self.allowed_message_ids is not None:
                conditions.append("COALESCE(NULLIF(m.message_id,''),m.id) IN ("
                                  + ','.join('?' for _ in self.allowed_message_ids) + ')')
                scope_args.extend(self.allowed_message_ids)
            for column, clause in [('deleted_at', 'm.deleted_at IS NULL'),
                                   ('is_hidden', 'COALESCE(m.is_hidden,0)=0')]:
                if column in columns:
                    conditions.append(clause)
            sequence = 'COALESCE(m.sequence_number,0)' if 'sequence_number' in columns else 'CAST(0 AS INTEGER)'
            select = ("SELECT COALESCE(NULLIF(m.message_id,''),m.id) AS message_id,m.content,m.role,m.timestamp,m.rowid AS position,"
                      + sequence + ' AS sequence ')
            source = 'FROM messages m JOIN conversations c ON c.id=m.conversation_id JOIN users u ON u.id=c.user_id WHERE '
            visible = ' AND '.join(conditions)
            selected = visible + " AND COALESCE(NULLIF(m.message_id,''),m.id) IN (" + ','.join('?' for _ in message_ids) + ')'
            rows = [dict(r) for r in conn.execute(select + source + selected, [*scope_args, *message_ids])]
            for row in rows:
                neighbors = []
                for operator, order in [('<', 'DESC'), ('>', 'ASC')]:
                    page = [dict(r) for r in conn.execute(select + source + visible +
                        f' AND (COALESCE(m.timestamp,0),{sequence},m.rowid) {operator} (?,?,?) '
                        f'ORDER BY COALESCE(m.timestamp,0) {order},{sequence} {order},m.rowid {order} LIMIT 2',
                        [*scope_args, row['timestamp'] or 0, row['sequence'], row['position']])]
                    neighbors.append(list(reversed(page)) if operator == '<' else page)
                row['context'] = {'before': [self._context_message(r) for r in neighbors[0]],
                                  'after': [self._context_message(r) for r in neighbors[1]]}
            return rows

    @staticmethod
    def _context_message(row):
        text = re.sub(r'!\[[^\]]*\]\([^)]+\)', '[图片]', row['content'] or '')
        text = re.sub(r'data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+', '[图片]', text)
        return {'message_id':row['message_id'], 'role':row['role'], 'timestamp':row['timestamp'], 'text':text[:260]}

    def _request(self, action, **arguments):
        return request_from_phone(self.scope[0], {
            'action': action, 'character_id': self.scope[1], 'conversation_id': self.scope[2], **arguments})

    @staticmethod
    def unavailable(message=None):
        return {'status': 'unavailable',
                'reason': 'original_image_unavailable' if message else 'image_catalog_unavailable',
                'scope': 'history',
                'message_id': message['message_id'] if message else None,
                'role': message['role'] if message else None,
                'note': HISTORY_IMAGE_TOOLS_TEXT['unavailable_1']}

    async def list_images(self, arguments):
        offset, limit = arguments.get('offset', 0), arguments.get('limit', 20)
        page = await self._request('list', offset=offset, limit=limit)
        if not page or page.get('status') != 'ok':
            return self.unavailable()
        candidates = page.get('images', [])
        if not isinstance(candidates, list):
            return self.unavailable()
        candidates = [r for r in candidates[:limit] if isinstance(r, dict)
                      and isinstance(r.get('message_id'), str) and 0 < len(r['message_id']) <= 256
                      and type(r.get('image_count')) is int and 1 <= r['image_count'] <= 4]
        trusted = {r['message_id']: r for r in await asyncio.to_thread(self._rows, [r['message_id'] for r in candidates])}
        self._catalog_image_counts.update({r['message_id']: r['image_count']
                                          for r in candidates if r['message_id'] in trusted})
        if not trusted and page.get('has_more') is not True:
            return {'status': 'ok', 'images': [], 'next_offset': None,
                    'note': HISTORY_IMAGE_TOOLS_TEXT['list_images_2']}
        return {'images': [{'message_id': r['message_id'], 'role': trusted[r['message_id']]['role'],
                            'timestamp': trusted[r['message_id']]['timestamp'],
                            'text': self._context_message(trusted[r['message_id']])['text'],
                            'surrounding_messages': trusted[r['message_id']]['context'],
                            'image_count': r['image_count']} for r in candidates if r['message_id'] in trusted],
                'next_offset': offset + limit if page.get('has_more') is True else None,
                'note': HISTORY_IMAGE_TOOLS_TEXT['list_images_1']}

    async def read_image(self, arguments):
        rows = await asyncio.to_thread(self._rows, [arguments['message_id']])
        if not rows:
            return {'status': 'not_found', 'note': HISTORY_IMAGE_TOOLS_TEXT['read_image_1']}
        index = arguments.get('image_index', 1)
        image_count = self._catalog_image_counts.get(arguments['message_id'], 0)
        if not image_count:
            return {'status': 'not_found', 'reason': 'image_not_confirmed',
                    'note': HISTORY_IMAGE_TOOLS_TEXT['read_image_2']}
        if type(index) is not int or not 1 <= index <= image_count:
            return {'status': 'not_found', 'reason': 'image_index_out_of_range',
                    'note': HISTORY_IMAGE_TOOLS_TEXT['read_image_3']}
        response = await self._request('read', message_id=arguments['message_id'], image_index=index)
        original = response.get('image') if response else None
        blocks = await resolve_harness_image_blocks([original], self.db_path) if original else []
        if not blocks:
            return self.unavailable(rows[0])
        label = {'message_id': rows[0]['message_id'], 'image_index': index,
                 'role': rows[0]['role'],
                 'timestamp': rows[0]['timestamp'], 'status': 'original_image',
                 'surrounding_messages': rows[0]['context'],
                 'note': HISTORY_IMAGE_TOOLS_TEXT['label_1']}
        return {'content': [{'type': 'text', 'text': json.dumps(label, ensure_ascii=False)}, *blocks]}

    async def resend_image(self, arguments):
        message_id = arguments['message_id']
        rows = await asyncio.to_thread(self._rows, [message_id])
        if not rows:
            raise ValueError(HISTORY_IMAGE_TOOLS_TEXT['resend_image_2'])
        image_count = self._catalog_image_counts.get(message_id, 0)
        image_index = arguments.get('image_index', 1)
        if not image_count or type(image_index) is not int or not 1 <= image_index <= image_count:
            raise ValueError(HISTORY_IMAGE_TOOLS_TEXT['resend_image_3'])
        response = await self._request('read', message_id=message_id, image_index=image_index)
        original = response.get('image') if response else None
        match = re.fullmatch(r'data:([^;,]+);base64,([A-Za-z0-9+/=]+)', str(original or ''))
        if not match:
            return self.unavailable(rows[0])
        try:
            data = base64.b64decode(match.group(2), validate=True)
        except ValueError:
            return self.unavailable(rows[0])
        if not data or not await resolve_harness_image_blocks([original], self.db_path):
            return self.unavailable(rows[0])
        from ..chat_image_transfer import store_web_image_transfer
        source_hash = hashlib.sha256(data).hexdigest()
        request_id = 'agent_history_repeat_' + hashlib.sha256(
            (message_id + ':' + str(image_index) + ':' + source_hash).encode()).hexdigest()[:20]
        attachment = {'id': request_id, 'type': 'image',
            'url': store_web_image_transfer(data, match.group(1), self.scope[0]),
            'name': '重发的图片',
            'metadata': {'source': 'history_repeat', 'request_id': request_id,
                         'source_message_id': message_id, 'source_image_index': image_index,
                         'source_role': rows[0]['role'],
                         'sha256': source_hash, 'ephemeral': True}}
        self.repeated = [(attachment, min(arguments.get('after_bubble_index', 1), 6))]
        return {'staged': True, 'message_id': message_id, 'image_index': image_index,
                'note': HISTORY_IMAGE_TOOLS_TEXT['resend_image_1']}

    def apply_to_request(self, request, bubble_count):
        if not self.repeated:
            return
        from .autonomous_stickers import apply_image_attachments
        apply_image_attachments(request, self.repeated, bubble_count, append=True)
        self.repeated = []

    def register(self, capability):
        capability('list_history_images', HISTORY_IMAGE_TOOLS_TEXT['register_1'], {
            'type': 'object', 'properties': {'offset': {'type': 'integer', 'minimum': 0},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 40}}, 'additionalProperties': False}, self.list_images)
        capability('read_history_image', HISTORY_IMAGE_TOOLS_TEXT['register_2'], {
            'type': 'object', 'properties': {'message_id': {'type': 'string', 'minLength': 1, 'maxLength': 256},
                'image_index': {'type': 'integer', 'minimum': 1, 'maximum': 4},
                'selection_reason': {'type': 'string', 'minLength': 1, 'maxLength': 400}},
            'required': ['message_id', 'selection_reason'], 'additionalProperties': False}, self.read_image)
        capability('resend_history_image', HISTORY_IMAGE_TOOLS_TEXT['register_3'], {
                'type': 'object', 'properties': {'message_id': {'type': 'string', 'minLength': 1, 'maxLength': 256},
                    'image_index': {'type': 'integer', 'minimum': 1, 'maximum': 4},
                    'after_bubble_index': {'type': 'integer', 'minimum': 0, 'maximum': 6}},
                'required': ['message_id'], 'additionalProperties': False}, self.resend_image)
