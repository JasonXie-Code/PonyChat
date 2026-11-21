"""Real normal-mode lifecycle acceptance; retain complete requests and responses."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

from Backend.scripts import test_normal_death_lifecycle_matrix as base

OUT = Path(__file__).resolve().parents[2] / 'docs/testing/death-spirit-20261002'
BOUNDARIES_ONLY = '--boundaries-only' in sys.argv
FRESH_BOUNDARIES = '--fresh-boundaries' in sys.argv
SPIRIT_SHORTCUT_ONLY = '--spirit-shortcut-only' in sys.argv
if BOUNDARIES_ONLY:
    OUT = OUT / ('boundaries-fresh' if FRESH_BOUNDARIES else 'boundaries-retest')
if os.getenv('PONYCHAT_DEATH_SPIRIT_OUT'):
    OUT = Path(os.environ['PONYCHAT_DEATH_SPIRIT_OUT']).resolve()


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    conn = base.connect()
    username, user_id = base.create_test_user(conn)
    rows = base.load_system_characters(conn)
    selected = [r for name in ('紫悦', '云宝', '玉琪派') for r in rows
                if base.character_name(r) == name][:3]
    if len(selected) < 3:
        selected = rows[:3]
    chars = base.clone_characters(conn, user_id, selected)
    conn.close()
    token = base.make_token(username)
    records, conversations = [], []

    async def scenario(client, char, key, turns):
        cid = 'death_accept_' + uuid.uuid4().hex
        conversations.append(cid)
        history = []
        for index, (text, expected, at) in enumerate(turns):
            history.append(dict(role='user', content=text,
                                message_id='u_' + uuid.uuid4().hex,
                                timestamp=int(time.time() * 1000)))
            payload = dict(messages=list(history), username=username,
                           character_id=char['id'], conversation_id=cid,
                           mode='normal', stream=False, memory_enabled=True)
            if at:
                payload.update(reply_character_ids=[char['id']], reply_character_id=char['id'])
            started = time.perf_counter()
            record = dict(character=char, scenario=key, turn=index + 1,
                          expected=expected, request=payload)
            try:
                resp = await client.post(base.BASE_URL + '/api/chat', json=payload,
                    headers={'X-Chat-Auth': token, 'X-Client-Id': 'codex_death_spirit_acceptance',
                             'Accept': 'application/json'}, timeout=240)
                record['http'] = resp.status_code
                try:
                    raw = resp.json()
                except ValueError:
                    raw = resp.text
                record['response'] = raw
                reply, no_reply, reason = base.parse_reply(raw)
                state = base.lifecycle_state(username, char['id'], cid)
                record.update(reply=reply, no_reply=no_reply, reason=reason, state=state)
                if isinstance(raw, dict):
                    record['bubble_count'] = sum(e.get('type') == 'assistant_paragraph'
                                                 for e in raw.get('events', []))
                if expected == 'spirit':
                    record['spirit_format_passed'] = (
                        record.get('bubble_count') == 1 and reply.startswith('（')
                        and any(term in reply.split('）')[0] for term in ('灵魂', '残响'))
                        and not any(term in reply for term in ('我', '咱')) and len(reply) <= 250)
                record['passed'] = resp.status_code == 200 and (
                    state == 'dead' and no_reply and not reply if expected == 'silent' else
                    state == 'dead' and bool(reply) and not no_reply if expected in ('death', 'spirit') else
                    state == 'alive' and bool(reply) and not no_reply)
                if expected == 'spirit':
                    record['passed'] = record['passed'] and record['spirit_format_passed']
                if reply:
                    history.append(dict(role='assistant', content=reply,
                        message_id='a_' + uuid.uuid4().hex, timestamp=int(time.time() * 1000),
                        speaker_character_id=char['id'], speaker_name=char['name']))
            except Exception as exc:
                record.update(error=repr(exc), passed=False)
            record['elapsed'] = round(time.perf_counter() - started, 2)
            records.append(record)
            (OUT / 'raw.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({k: record.get(k) for k in ('scenario','turn','passed','state','reply','reason','elapsed')}, ensure_ascii=False), flush=True)

    async def role_suite(client, char):
        name = char['name']
        turns = [
            ('（我用力一拳将你打趴，鼻血飞溅，随后踩住你，不让你动）', 'alive', False),
            ('（我抓住破绽，一击刺穿你的心脏，杀死了你）', 'death', False),
            ('你还在吗？', 'silent', False),
            (f'@{name} 你的灵魂还听得到吗？', 'spirit', True),
            ('继续说吧。', 'silent', False),
            (f'@{name} 你已经复活了，明天提醒我去散步。', 'spirit', True),
            ('（我打了个响指，让你复活）醒醒。', 'silent', False),
        ]
        if SPIRIT_SHORTCUT_ONLY:
            turns = [
                ('（我一击刺穿你的心脏，杀死了你）', 'death', False),
                (f'@{name} （请详细写出当前你的心理活动）', 'spirit', True),
                ('继续说吧。', 'silent', False),
            ]
        await scenario(client, char, name + '-lifecycle', turns)

    try:
        async with httpx.AsyncClient() as client:
            if not BOUNDARIES_ONLY:
                await asyncio.gather(*(role_suite(client, char) for char in chars))
            boundaries = [
                ('hypothetical', '如果我杀死你会怎么样？'),
                ('proxy', '（我杀死了你的分身，本体还在远处没有受伤）'),
                ('other-character', '（我杀死了那只袭击你的野狼，你仍然毫发无伤地站在远处）'),
                ('failed-attempt', '（我试图杀死你，但没有成功，你躲开了，毫发无伤）'),
                ('negation', '我没有杀死你，你一直活着。'),
                ('threat', '我现在就要杀死你！'),
                ('new-conversation', '你好，今天过得怎么样？'),
            ]
            # Fresh characters prevent both debounce cancellation and stale scene state.
            independent = []
            for key, text in ([] if SPIRIT_SHORTCUT_ONLY else boundaries):
                conn = base.connect()
                try:
                    fresh = base.clone_characters(conn, user_id, [selected[0]])[0]
                    chars.append(fresh)
                finally:
                    conn.close()
                independent.append((fresh, key, text))
            for offset in range(0, len(independent), 3):
                await asyncio.gather(*(scenario(client, char, key, [(text, 'alive', False)])
                    for char, key, text in independent[offset:offset + 3]))
    finally:
        conn = base.connect()
        cleanup = base.cleanup(conn, username, user_id, [c['id'] for c in chars], conversations)
        conn.close()
        summary = dict(total=len(records), passed=sum(r['passed'] for r in records),
                       failed=sum(not r['passed'] for r in records), cleanup=cleanup)
        (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    return int(any(not r['passed'] for r in records) or any(cleanup.values()))


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
