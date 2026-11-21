"""Three characters x three independent scenes; observe current prompt without legacy limits."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import time
import uuid

import httpx

from Backend.scripts.test_normal_scene_anchor_matrix import (
    character_name, cleanup, clone_characters, connect, create_test_user,
    load_target_system_characters, make_token,
)
from Backend.scripts.test_normal_sound_mark_acceptance import chat, count_tilde, set_relationship

TARGET_NAMES = ('碧琪', '柔柔', '紫悦')
SCENES = [
    dict(key='A_cuddle', label='亲近互动：安静拥抱', stage='committed_partner',
         message='今晚别急着睡，我想一直这样抱着你，慢慢来就好'),
    dict(key='B_affection', label='亲近互动：牵手撒娇', stage='committed_partner',
         message='我轻轻握住你的前蹄，笑着靠近你。今天想多陪你一会儿，你也向我撒个娇好不好？'),
    dict(key='C_daily', label='普通聊天：周末安排', stage='uncertain',
         message='帮我想想周末怎么安排比较好，我想休息一下，也想出门走走'),
]


async def main() -> int:
    workspace = Path(os.environ['PONYCHAT_DB_PATH']).parent
    cases_path = workspace / 'cases.jsonl'
    conn = connect()
    username = ''
    user_id = 0
    clones = []
    cases = []
    started = time.perf_counter()
    try:
        username, user_id = create_test_user(conn)
        source = {character_name(row): row for row in load_target_system_characters(conn)}
        token = make_token(username)
        fixtures = []
        for scene in SCENES:
            group = clone_characters(conn, user_id, [source[name] for name in TARGET_NAMES])
            clones.extend(group)
            fixtures.extend((scene, character) for character in group)
        print(json.dumps(dict(username=username, roles=TARGET_NAMES, scenes=SCENES,
                              concurrency=3, cases=9), ensure_ascii=False), flush=True)
        semaphore = asyncio.Semaphore(3)
        async with httpx.AsyncClient() as client:
            async def one(scene, character):
                async with semaphore:
                    await set_relationship(client, token, username, character['id'], scene['stage'])
                    conversation = 'sound_mark_matrix_' + uuid.uuid4().hex
                    began = time.time()
                    result = await chat(client, token, username, character['id'], conversation, scene['message'])
                    valid = bool(result.get('ok') and result.get('persisted') and
                                 result.get('reply') and not result.get('no_reply'))
                    case = dict(character=character['name'], character_id=character['id'],
                                scene=scene['key'], scene_label=scene['label'], stage=scene['stage'],
                                user_message=scene['message'], started_at_unix=began,
                                completed_at_unix=time.time(), valid=valid,
                                tilde_count=count_tilde(result.get('reply', '')),
                                **result)
                    cases.append(case)
                    with cases_path.open('a', encoding='utf8') as handle:
                        handle.write(json.dumps(case, ensure_ascii=False) + '\n')
                    print(json.dumps(dict(character=case['character'], scene=case['scene'],
                                          valid=valid, tilde=case['tilde_count'],
                                          elapsed=case['elapsed']), ensure_ascii=False), flush=True)
            outcomes = await asyncio.gather(*(one(*fixture) for fixture in fixtures), return_exceptions=True)
            errors = [repr(outcome) for outcome in outcomes if isinstance(outcome, BaseException)]
        summary = dict(cases=len(cases), valid=sum(c['valid'] for c in cases), errors=errors,
                       wall_seconds=round(time.perf_counter()-started, 2))
        (workspace / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        return 0 if len(cases) == 9 and all(c['valid'] for c in cases) and not errors else 1
    finally:
        result = cleanup(conn, username, user_id, [c['id'] for c in clones], []) if username else {}
        conn.close()
        (workspace / 'cleanup.json').write_text(json.dumps(result, indent=2), encoding='utf8')
        print('CLEANUP ' + json.dumps(result), flush=True)
        if any(result.values()):
            raise RuntimeError('Test rows remain after cleanup')
