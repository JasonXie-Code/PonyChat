"""Real service/routing/SQLite/SSE; only the external model and account are synthetic."""
import asyncio
import json
import sqlite3
import sys
import os
import time
from pathlib import Path

import pytest

from test_autonomous_upgrade_integration import database
from test_autonomous_normal import model_result
from expression_skill_contract import read_expression_contract
from Backend.chat_modules import service, live_turn, harness_runtime
from Backend.utils import ChatMessage, ChatRequest


@pytest.mark.parametrize('phase', ['burst', 'generating', 'persisted'])
@pytest.mark.parametrize('third_message', [False, True])
def test_comment_then_at_only_delivers_addressed_character(database, monkeypatch, phase, third_message):
    from Backend.routes import auth
    from Backend import background_jobs
    from Backend.chat_modules import state, normal_nonstream
    from Backend.chat_modules.service_impl import chat_request_helpers
    async def noop(*args, **kwargs): pass
    async def verify(_): return 'alice'
    async def authenticated(req, client, token, model):
        return dict(active_model={'model_name': 'synthetic'}, request_tokens=0, client_id=client,
                    character_id=req.character_id, username=req.username, effective_username=req.username)
    for name, module in list(sys.modules.items()):
        if not name.startswith('Backend') or module is None:
            continue
        if hasattr(module, 'get_database'):
            monkeypatch.setattr(module, 'get_database', lambda: database)
        if hasattr(module, 'save_chat_debug_log'):
            monkeypatch.setattr(module, 'save_chat_debug_log', noop)
    monkeypatch.setattr(auth, 'auth_token_verify', verify)
    monkeypatch.setattr(service, 'resolve_auth_and_quota', authenticated)
    monkeypatch.setattr(service, '_is_new_contact_opening', noop)
    async def context(*a, **kw): return '测试用户'
    monkeypatch.setattr(service, 'build_user_context', context)
    for module in (service, state, normal_nonstream, chat_request_helpers):
        monkeypatch.setattr(module, 'is_generation_current', lambda *a, **kw: True)
    monkeypatch.setattr(service.generation_locker, 'release', noop)
    monkeypatch.setattr(service.manager, 'broadcast_to_user', noop)
    monkeypatch.setattr(service.manager, 'broadcast_sync', noop)
    monkeypatch.setattr(service.manager, 'is_active_chat', lambda *a, **kw: True)
    monkeypatch.setattr(background_jobs, 'create_tracked_task', lambda coro, **kw: asyncio.create_task(coro))

    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()
        attempts = []
        raw_replies, receipts = [], []
        if phase == 'persisted':
            from Backend.chat_modules.normal_delivery import NormalDeliverySession
            original_release = NormalDeliverySession.release
            async def release(session, event, req, **kwargs):
                if req._normal_reply_revision == 1:
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.set()
                return await original_release(session, event, req, **kwargs)
            monkeypatch.setattr(NormalDeliverySession, 'release', release)
        async def runner(prompt, model, tools, **kwargs):
            task = json.loads(prompt)
            attempts.append(task)
            if phase == 'generating' and len(attempts) == 1:
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            await tools['load_chat_skill'].callback({'name': 'instant_messaging'})
            await tools['read_character_reference'].callback({'query': '角色名称'})
            value = model_result('我来评价这条评论。')
            data = json.loads(value['final_response'])
            data['reply_language']['language'] = 'Chinese'
            from Backend.chat_modules.autonomous_scene_state import FIELDS
            data['scene_patch'] = {'reset': False, 'changes': {
                field: {'value': None, 'source_message_ids': [task['latest_user_message']['message_id']]}
                for field in FIELDS}}
            raw = json.dumps(data, ensure_ascii=False)
            raw_replies.append(raw)
            # These are ordinary chat batches, so the compliant turn selects the
            # conversation path and finishes the remaining serial reads.
            await read_expression_contract(tools)
            return {**value, 'final_response': raw}
        monkeypatch.setattr(harness_runtime, 'run_harness_turn', runner)
        def req(text, mid):
            return ChatRequest(username='alice', character_id='twilight', conversation_id='c1',
                mode='normal', memory_enabled=True, messages=[ChatMessage(role='user', content=text,
                message_id=mid, timestamp=2000)])
        async def send(text, mid):
            started_at = time.monotonic()
            response = await asyncio.wait_for(live_turn.normal_live_response(req(text, mid), 'android', 'test', {},
                                      use_json=False, handler=service.handle_chat_request), 1)
            iterator = response.body_iterator
            ack = json.loads((await asyncio.wait_for(anext(iterator), .2))[6:])
            assert ack['client_message_id'] == mid and ack['type'] == 'accepted'
            receipts.append({'message_id': mid, 'elapsed_ms': round((time.monotonic()-started_at)*1000, 2),
                             'event': ack})
            with sqlite3.connect(database.db_path) as conn:
                assert conn.execute('SELECT count(*) FROM messages WHERE message_id=?', (mid,)).fetchone()[0] == 1
            return iterator, ack
        first, ack1 = await send('我觉得这条评论很有意思', 'comment')
        if phase != 'burst':
            await asyncio.wait_for(entered.wait(), 4)
        second, ack2 = await send('@碧琪', 'at')
        assert ack1['job_id'] == ack2['job_id']
        extra = []
        if third_message:
            third, ack3 = await send('请谈谈你的看法', 'detail')
            assert ack3['job_id'] == ack1['job_id']
            extra.append(third)
        async def drain(iterator):
            return ''.join([packet async for packet in iterator])
        streams = await asyncio.wait_for(asyncio.gather(drain(first), drain(second), *map(drain, extra)), 8)
        for stream in streams:
            events = [json.loads(line[6:]) for line in stream.splitlines()
                      if line.startswith('data: ') and line != 'data: [DONE]']
            assert not any(e.get('type') == 'error' for e in events), events
            visible = [e for e in events if e.get('type') == 'assistant_paragraph']
            assert visible and all(e['speaker_character_id'] == 'pinkie' for e in visible)
        batch = attempts[-1]['current_user_batch']
        assert {m['message_id'] for m in batch} >= {'comment', 'at'}
        assert cancelled.is_set() == (phase != 'burst')
        with sqlite3.connect(database.db_path) as conn:
            rows = conn.execute("SELECT speaker_character_id FROM messages WHERE role='assistant' "
                                "AND deleted_at IS NULL AND COALESCE(is_hidden,0)=0").fetchall()
            assert rows and all(row[0] == 'pinkie' for row in rows)
        output = os.environ.get('PONYCHAT_BATCH_ARTIFACT_DIR')
        if output:
            target = Path(output)
            target.mkdir(parents=True, exist_ok=True)
            (target / f'{phase}-third-{third_message}.json').write_text(json.dumps({
                'model': 'synthetic - not a real role model response', 'phase': phase,
                'third_message': third_message, 'receipts': receipts,
                'merged_user_batch': batch, 'raw_model_replies': raw_replies,
                'response_streams': streams, 'visible_database_speakers': rows},
                ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    asyncio.run(scenario())
