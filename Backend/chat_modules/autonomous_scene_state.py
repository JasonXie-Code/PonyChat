"""Evidence-bound, per-conversation scene patches committed with delivered replies."""
from .Prompts import AUTONOMOUS_SCENE_STATE_TEXT

from contextlib import closing
import json

from ..agent_memory import evidence
from ..agent_memory.schema import connect

FIELDS = {'scene_time', 'location', 'user_position', 'character_position', 'contact', 'surroundings'}


def validate_patch(value, allowed_sources, *, initial=False, previous=None):
    if not isinstance(value, dict) or set(value) != {'reset', 'changes'} or type(value['reset']) is not bool:
        raise ValueError(AUTONOMOUS_SCENE_STATE_TEXT['validate_patch_1'])
    changes = value['changes']
    if not isinstance(changes, dict) or len(changes) > 48 or value['reset'] and not changes:
        raise ValueError(AUTONOMOUS_SCENE_STATE_TEXT['validate_patch_2'])
    if initial and not FIELDS <= changes.keys():
        raise ValueError(AUTONOMOUS_SCENE_STATE_TEXT['validate_patch_3'] +
                         ','.join(sorted(FIELDS - changes.keys())))
    if not value['reset']:
        for moving, other, subject in [('character_position', 'user_position', '角色'),
                                       ('user_position', 'character_position', '用户')]:
            old_position = str((previous or {}).get(other, {}).get('value') or '')
            if moving in changes and other not in changes and subject in old_position:
                raise ValueError(AUTONOMOUS_SCENE_STATE_TEXT['validate_patch_9'] + other + AUTONOMOUS_SCENE_STATE_TEXT['validate_patch_8'])
    clean = {}
    for key, item in changes.items():
        if key not in FIELDS | {'interaction_mode'} and not (key.startswith('item:') and 5 < len(key) <= 85):
            raise ValueError('未知场景字段：' + key)
        if not isinstance(item, dict) or set(item) != {'value', 'source_message_ids'}:
            raise ValueError(AUTONOMOUS_SCENE_STATE_TEXT['validate_patch_4'])
        text, refs = item['value'], item['source_message_ids']
        if key == 'interaction_mode' and text not in ('instant_messaging', 'virtual_roleplay'):
            raise ValueError(AUTONOMOUS_SCENE_STATE_TEXT['validate_patch_5'])
        if text is not None and (not isinstance(text, str) or not text.strip() or len(text) > 600):
            raise ValueError(AUTONOMOUS_SCENE_STATE_TEXT['validate_patch_6'])
        if (not isinstance(refs, list) or not 1 <= len(refs) <= 8 or
                any(not isinstance(ref, str) or ref not in allowed_sources | {'$reply'} for ref in refs)):
            raise ValueError(AUTONOMOUS_SCENE_STATE_TEXT['validate_patch_7'])
        clean[key] = {'value': text.strip() if text is not None else None,
                      'source_message_ids': list(dict.fromkeys(refs))}
    return {'reset': value['reset'], 'changes': clean}


def _row(conn, store):
    return conn.execute('SELECT * FROM normal_agent_scene_cards WHERE username=? AND character_id=? '
                        'AND conversation_id=? AND epoch=?',
                        (store.username, store.character_id, store.conversation_id, store.epoch)).fetchone()


def _valid_fields(conn, store, fields):
    return {key: item for key, item in fields.items() if item.get('evidence') and all(
        evidence.matches(conn, store.username, store.character_id, ref, expected)
        for ref, expected in item['evidence'].items())}


def load_scene(store):
    with closing(connect(store.path)) as conn:
        conn.execute('BEGIN')
        state = conn.execute('SELECT epoch,enabled FROM agent_memory_state WHERE username=? AND character_id=?',
                             (store.username, store.character_id)).fetchone()
        if not state or state['epoch'] != store.epoch or not state['enabled']:
            return {'revision': 0, 'fields': {}}
        row = _row(conn, store)
        fields = _valid_fields(conn, store, json.loads(row['fields_json'])) if row else {}
        return {'revision': row['revision'] if row else 0,
                'fields': {key: {'value': item['value'], 'source_message_ids': list(item['evidence'])}
                           for key, item in fields.items()}}


def commit_scene(conn, store, snapshot, patch, reply_ids):
    """Called inside the reply transaction: rollback/cancellation also rolls back the card."""
    state = conn.execute('SELECT epoch,enabled FROM agent_memory_state WHERE username=? AND character_id=?',
                         (store.username, store.character_id)).fetchone()
    if not state or state['epoch'] != store.epoch or not state['enabled']:
        raise RuntimeError('Scene memory disabled or reset before commit')
    row = _row(conn, store)
    revision = row['revision'] if row else 0
    if revision != snapshot['revision']:
        raise RuntimeError('Scene changed during generation')
    old_fields = json.loads(row['fields_json']) if row else {}
    previous_evidence = {ref: expected for field in old_fields.values()
                         for ref, expected in field.get('evidence', {}).items()}
    fields = _valid_fields(conn, store, old_fields)
    if patch['reset']:
        fields = {}
    for key, item in patch['changes'].items():
        if '$reply' in item['source_message_ids'] and not reply_ids:
            # 本轮没有保存任何 assistant 段落（回复级重复保护清空，或零文本静默交付）：
            # 丢弃依赖 $reply 的字段，不让整笔回复事务失败。该字段下一轮按新原文重新判定，
            # 其它不依赖 $reply 的字段照常提交。
            continue
        refs = []
        for ref in item['source_message_ids']:
            refs.extend(reply_ids if ref == '$reply' else [ref])
        manifest = {}
        for ref in dict.fromkeys(refs):
            # Scene state must not borrow evidence from another private conversation.
            raw = conn.execute(evidence.RAW_SELECT + evidence.RAW_REF_FILTER + " AND m.conversation_id=?4",
                (store.username, store.character_id, ref, store.conversation_id)).fetchone()
            fingerprint = evidence.resolve(conn, store.username, store.character_id, ref) if raw else None
            if not fingerprint:
                raise RuntimeError('Scene evidence unavailable at commit')
            expected = store._allowed.get(ref) or previous_evidence.get(ref)
            if expected and not evidence.matches(conn, store.username, store.character_id, ref, expected):
                raise RuntimeError('Scene evidence changed during generation')
            manifest[ref] = fingerprint
        fields[key] = {'value': item['value'], 'evidence': manifest}
    if len(fields) > 48:
        raise ValueError('Scene card exceeds 48 fields')
    conn.execute('''INSERT INTO normal_agent_scene_cards
        (username,character_id,conversation_id,epoch,revision,fields_json) VALUES(?,?,?,?,?,?)
        ON CONFLICT(username,character_id,conversation_id) DO UPDATE SET
        epoch=excluded.epoch,revision=excluded.revision,fields_json=excluded.fields_json''',
        (store.username, store.character_id, store.conversation_id, store.epoch, revision + 1,
         json.dumps(fields, ensure_ascii=False)))
