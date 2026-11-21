"""Record scene, memory and follow-up after delivery; never regenerate a reply."""
from __future__ import annotations

import asyncio
from contextlib import closing
import json
import re
import time
from types import SimpleNamespace

from .post_reply_state import connect, mark


def parse_state_response(text):
    """Accept a single JSON code fence without weakening state validation."""
    raw = text.strip()
    fenced = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL | re.IGNORECASE)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError('后台必须返回完整JSON对象，禁止说明文字或代码块。输出开头：' + raw[:160]) from exc


def valid_evidence(conn, job, payload):
    from ..agent_memory.evidence import matches
    state = conn.execute('SELECT epoch,enabled FROM agent_memory_state WHERE username=? AND character_id=?',
                         (job['username'], job['character_id'])).fetchone()
    if not state or not state['enabled'] or state['epoch'] != payload['epoch']:
        return False
    settings = conn.execute('SELECT settings FROM user_settings s JOIN users u ON u.id=s.user_id '
                            'WHERE u.username=?', (job['username'],)).fetchone()
    if settings and json.loads(settings[0]).get('memory_enabled') is False:
        return False
    return all(matches(conn, job['username'], job['character_id'], mid, fingerprint)
               for mid, fingerprint in payload['evidence'].items())


def load_material(path, job, payload):
    with closing(connect(path)) as conn:
        if not valid_evidence(conn, job, payload):
            return None
        replies = []
        for mid in payload['reply_ids']:
            row = conn.execute('SELECT message_id,role,content,timestamp FROM messages '
                'WHERE conversation_id=? AND message_id=? AND deleted_at IS NULL AND COALESCE(is_hidden,0)=0',
                (job['conversation_id'], mid)).fetchone()
            if not row:
                return None
            replies.append(dict(row))
        return replies


async def business_for(job, payload):
    from ..proactive_settings import load_proactive_settings
    from .autonomous_contracts import user_batch
    request = SimpleNamespace(username=job['username'], character_id=payload['main_character_id'],
        conversation_id=job['conversation_id'], reply_character_id=job['character_id'],
        **payload.get('request_flags', {}))
    return SimpleNamespace(request=request, history=payload['messages'],
        text='\n'.join(m.get('content', '') for m in user_batch(payload['messages'])),
        settings=await load_proactive_settings(job['username']),
        shortcut=SimpleNamespace(description=payload.get('description', False)),
        lifecycle=payload.get('dead'), schedules=[], followup_decision=None)


def validate_result(data, payload, replies, store, business, snapshot):
    from .autonomous_scene_state import validate_patch
    from .autonomous_followup import finalize_followup
    if not isinstance(data, dict) or set(data) != {'scene_patch', 'memories', 'followup_decision'}:
        raise ValueError('后台只返回scene_patch、memories、followup_decision三个字段')
    patch = validate_patch(data['scene_patch'], set(payload['evidence']),
                           initial=not snapshot['fields'], previous=snapshot['fields'])
    mode = payload.get('interaction_mode')
    if mode in ('instant_messaging', 'virtual_roleplay'):
        refs = payload['reply_ids'] or [m['message_id'] for m in payload['messages'] if m.get('message_id')][-1:]
        patch['changes']['interaction_mode'] = {'value': mode, 'source_message_ids': refs}
    memories = data['memories']
    if not isinstance(memories, list) or len(memories) > 8:
        raise ValueError('memories必须是最多8项的数组，无需记忆时为空数组')
    covered = set()
    for item in memories:
        if not isinstance(item, dict) or set(item) - {'content','source_message_ids','category','importance','certainty','occurred_at'}:
            raise ValueError('记忆项字段不符合合同')
        if item.get('category') not in {'fact','preference','episode','activity','commitment','relationship','understanding'}:
            raise ValueError('记忆category非法')
        refs = item.get('source_message_ids')
        if not isinstance(refs, list) or not refs or not set(refs) <= payload['evidence'].keys():
            raise ValueError('记忆必须引用本轮可核对的消息ID')
        # Understanding is an inference by definition. Conservatively lower its
        # certainty here instead of spending another model call repairing a label.
        certainty = item.get('certainty', 'explicit')
        if item['category'] == 'understanding':
            certainty = 'inferred'
        store.stage(kind='fact', content=item.get('content'), source_message_ids=refs,
            occurred_at=item.get('occurred_at'), category=item['category'],
            certainty=certainty, importance=item.get('importance', 5))
        covered.update(refs)
    if set(payload.get('required_memory_ids', [])) - covered:
        raise ValueError('用户明确要求记住的本轮消息尚未写入memories')
    text_replies = [row for row in replies if row.get('content')]
    text_replies = text_replies[:payload.get('bubble_count', len(text_replies))]
    delivered = {'bubbles': [{'index': i+1, 'type': 'text', 'purpose': 'answer_user',
        'parts': [{'kind': 'speech', 'text': row['content']}]} for i, row in enumerate(text_replies)]}
    finalize_followup(business, {**delivered, 'bubble_count': len(text_replies),
                                  'followup_decision': data['followup_decision']})
    return patch


def commit_result(path, job, payload, store, business, snapshot, patch):
    from .autonomous_scene_state import commit_scene
    from .autonomous_schedule import persist_schedules
    with closing(connect(path)) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute('SELECT status FROM normal_post_reply_jobs WHERE id=?', (job['id'],)).fetchone()
        if not current or current['status'] in ('done', 'cancelled'):
            return
        if not valid_evidence(conn, job, payload):
            conn.execute("UPDATE normal_post_reply_jobs SET status='cancelled',payload='{}',updated_ms=? WHERE id=?",
                         (int(time.time()*1000), job['id']))
            return
        store.commit_on_connection(conn, generation_is_current=lambda: True)
        commit_scene(conn, store, snapshot, patch, payload['reply_ids'])
        # New queued user messages cancel optional follow-up, even though their
        # generation is correctly waiting behind this job.
        anchor = conn.execute('SELECT MAX(sequence_number) FROM messages WHERE conversation_id=? '
            'AND message_id IN (' + ','.join('?' for _ in payload['reply_ids']) + ')',
            (job['conversation_id'], *payload['reply_ids'])).fetchone()[0] if payload['reply_ids'] else None
        newer = anchor is None or conn.execute('SELECT 1 FROM messages WHERE conversation_id=? '
            "AND role='user' AND sequence_number>? AND deleted_at IS NULL AND COALESCE(is_hidden,0)=0 LIMIT 1",
            (job['conversation_id'], anchor)).fetchone()
        settings = conn.execute('SELECT settings FROM user_settings s JOIN users u ON u.id=s.user_id '
                                'WHERE u.username=?', (job['username'],)).fetchone()
        proactive = not settings or json.loads(settings[0]).get('proactive_messages_enabled') is not False
        dead = conn.execute("SELECT 1 FROM normal_character_lifecycle WHERE username=? AND character_id=? "
                            "AND conversation_id=? AND state='dead'",
                            (job['username'], job['character_id'], job['conversation_id'])).fetchone()
        if newer or not proactive or dead:
            business.schedules.clear()
        persist_schedules(conn, business)
        conn.execute("UPDATE normal_post_reply_jobs SET status='done',payload='{}',last_error=NULL,updated_ms=? WHERE id=?",
                     (int(time.time()*1000), job['id']))


async def process(path, job, *, harness_runner=None, model_config=None):
    from .agent_logging import log_scope
    from types import SimpleNamespace
    payload = json.loads(job['payload'])
    async with log_scope(job['username'], job['character_id'], 'normal',
            request=SimpleNamespace(character_id=payload['main_character_id']),
            params={'trace_id': 'post_reply:' + job['id'], 'phase': 'background_memory',
                    'conversation_id': job['conversation_id'], 'post_reply_job_id': job['id']},
            model_config=model_config):
        return await _process(path, job, harness_runner=harness_runner, model_config=model_config)


async def _process(path, job, *, harness_runner=None, model_config=None):
    from ..agent_memory.store import AgentMemoryStore
    from ..agent_memory.usage import record, meter_user
    from .autonomous_scene_state import load_scene
    from .harness_runtime import run_harness_turn
    from .Prompts import POST_REPLY_STATE_PROMPT, continuity, followup_contract
    payload = json.loads(job['payload'])
    replies = await asyncio.to_thread(load_material, path, job, payload)
    if replies is None:
        await asyncio.to_thread(mark, path, job['id'], 'cancelled')
        return
    store = AgentMemoryStore(path, username=job['username'], character_id=job['character_id'],
                            conversation_id=job['conversation_id'], allowed_sources=payload['evidence'])
    try:
        snapshot = await asyncio.to_thread(load_scene, store)
        business = await business_for(job, payload)
        from .autonomous_followup import eligibility
        if model_config is None:
            from .. import config
            model_config = config.model_manager.get_model_for_task('normal')
        prompt = {'phase': 'post_reply_state', 'character_profile': payload['profile'],
            'current_scene': snapshot, 'messages': payload['messages'], 'delivered_reply': replies,
            'required_memory_ids': payload.get('required_memory_ids', []),
            'interaction_mode': payload.get('interaction_mode'),
            'allowed_source_ids': list(payload['evidence']), 'continuity_rules': continuity,
            'validation_feedback': job.get('last_error'),
            'position_dependencies': [
                {'changed_field': moving, 'recheck_field': other,
                 'include_recheck_field_when_changed': True,
                 'must_not_invent_movement': True,
                 'preserve_value': snapshot['fields'][other]['value']}
                for moving, other, subject in [('character_position', 'user_position', '角色'),
                                               ('user_position', 'character_position', '用户')]
                if subject in str(snapshot['fields'].get(other, {}).get('value') or '')],
            'followup_contract': followup_contract, 'followup_blocked_reason': eligibility(business)}
        if model_config.get('harness_provider') == 'local-openai':
            from .local_state_contract import add_local_state_contract
            add_local_state_contract(prompt, payload['messages'], replies, snapshot)
        usage = {}
        try:
            result = await (harness_runner or run_harness_turn)(json.dumps(prompt, ensure_ascii=False),
                model_config, {}, system_prompt=POST_REPLY_STATE_PROMPT, reasoning_effort='low',
                timeout_seconds=60, max_tokens=8192)
            usage = {**result, 'incomplete': False}
            if result.get('finish_reason') != 'completed':
                raise ValueError('后台状态生成未完成：' + str(result.get('finish_reason'))
                                 + '；只输出必要变化和简洁JSON，不重复历史或展开解释。')
            data = parse_state_response(result['final_response'])
            patch = validate_result(data, payload, replies, store, business, snapshot)
            if business.schedules:
                import aiosqlite
                from ..scheduled_followup import proactive_reply_limit_reached
                async with aiosqlite.connect(path) as conn:
                    if (await proactive_reply_limit_reached(conn, job['conversation_id'])).get('reached'):
                        business.schedules.clear()
            await asyncio.to_thread(commit_result, path, job, payload, store, business, snapshot, patch)
        except BaseException as exc:
            usage = usage or getattr(exc, 'harness_usage', {})
            if usage:
                usage['incomplete'] = True
            raise
        finally:
            if usage:
                await asyncio.shield(meter_user(job['username'], usage, charge_membership=True))
                await asyncio.shield(asyncio.to_thread(record, path, job['username'], job['character_id'],
                                                       'post_reply', usage))
    finally:
        store.discard()
