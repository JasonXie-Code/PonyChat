"""Stage narrow, evidence-backed edits to user settings, separate from memory."""

from .Prompts import PREFERENCE_POLICY
import json

from .autonomous_contracts import user_batch
from .harness_runtime import HarnessToolValidationError
from .personal_preferences import MAX_PREFERENCE_LENGTH




def value_from(settings, character_id, mode):
    value = (settings or {}).get('personal_preferences', {}).get(character_id, {}).get(mode, '')
    return value if isinstance(value, str) else ''


class PreferenceEdits:
    def __init__(self, username, character_id, mode, value, messages):
        self.username, self.character_id, self.mode = username, character_id, mode
        self.original = self.value = value
        self.sources = {m['message_id']: m.get('content', '') for m in user_batch(messages)
                        if m.get('message_id')}
        self.edits = []

    def register(self, capability):
        if not self.username or not self.sources:
            return
        capability('stage_personal_preference',
            '追加、调整或取消当前角色当前模式的长期表达偏好。纯表达习惯使用此工具，不用记忆碎片。', {
                'type': 'object', 'properties': {
                    'before': {'type': 'string', 'maxLength': MAX_PREFERENCE_LENGTH},
                    'after': {'type': 'string', 'maxLength': MAX_PREFERENCE_LENGTH},
                    'source_message_id': {'type': 'string'},
                    'source_quote': {'type': 'string', 'minLength': 1},
                    'reason': {'type': 'string', 'minLength': 1, 'maxLength': 300}},
                'required': ['before', 'after', 'source_message_id', 'source_quote', 'reason'],
                'additionalProperties': False}, self.stage)

    async def stage(self, arguments):
        mid, quote = arguments['source_message_id'], arguments['source_quote']
        if mid not in self.sources or not quote.strip() or quote not in self.sources[mid]:
            raise HarnessToolValidationError('必须引用本轮用户消息中的准确原文')
        before, after = arguments['before'], arguments['after']
        if any(e == arguments for e in self.edits):
            return {'staged': True, 'duplicate_ignored': True, 'personal_preferences': self.value}
        if len(self.edits) >= 8:
            raise HarnessToolValidationError('本轮偏好修改过多')
        if before:
            if self.value.count(before) != 1:
                raise HarnessToolValidationError('待调整片段必须在当前个人偏好中唯一存在')
            updated = self.value.replace(before, after, 1)
        elif after.strip():
            updated = self.value if after.strip() in self.value else (self.value.rstrip() + '\n' + after.strip()).lstrip('\n')
        else:
            raise HarnessToolValidationError('不能提交空修改')
        if len(updated) > MAX_PREFERENCE_LENGTH:
            raise HarnessToolValidationError('个人偏好超过长度限制；只精简本次相关要求，不删除无关偏好')
        self.value = updated
        self.edits.append(dict(arguments))
        return {'staged': True, 'personal_preferences': self.value,
                'note': '与本轮回复一起保存；本轮立即按新要求表达'}

    def commit_on_connection(self, conn):
        if not self.edits:
            return
        row = conn.execute('SELECT u.id,s.settings FROM users u LEFT JOIN user_settings s ON s.user_id=u.id WHERE u.username=?',
                           (self.username,)).fetchone()
        if row is None:
            raise RuntimeError('Preference owner no longer exists')
        settings = json.loads(row[1]) if row[1] else {}
        current = value_from(settings, self.character_id, self.mode)
        if current != self.original:
            raise RuntimeError('Personal preferences changed while generating; retry using the latest settings')
        settings.setdefault('personal_preferences', {}).setdefault(self.character_id, {})[self.mode] = self.value
        conn.execute('INSERT INTO user_settings(user_id,settings,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) '
                     'ON CONFLICT(user_id) DO UPDATE SET settings=excluded.settings,updated_at=excluded.updated_at',
                     (row[0], json.dumps(settings, ensure_ascii=False)))
