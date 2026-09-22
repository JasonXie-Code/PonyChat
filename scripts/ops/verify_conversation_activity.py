"""Read-only verification of the authenticated public activity card endpoint; no chat/login."""
import argparse
import asyncio
import json
from pathlib import Path
import sqlite3
import sys

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(username):
    from Backend.db import get_database, get_users_dao
    from Backend.routes.auth import _auth_token_create
    from Backend.conversation_activity import read_conversation_activity
    db = get_database()
    with sqlite3.connect(Path(db.db_path).resolve().as_uri() + '?mode=ro', uri=True) as conn:
        row = conn.execute('''SELECT c.id,c.character_id FROM conversations c JOIN users u ON u.id=c.user_id
            WHERE u.username=? AND COALESCE(c.is_hidden,0)=0 ORDER BY c.timestamp DESC LIMIT 1''',
            (username,)).fetchone()
    assert row, 'An existing owned conversation is required'
    conversation, character = row
    # Sign without logging in: do not invalidate the user's phone session or store the token.
    token = _auth_token_create(username, await get_users_dao().get_token_version(username))
    result = {}
    async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
        for label, base in [('local', 'http://127.0.0.1:5000'), ('cn', 'https://39.101.74.217'),
                            ('official', 'https://www.ponychat.org')]:
            params = dict(character_id=character, conversation_id=conversation, mode='normal')
            unauthenticated = await client.get(base + '/api/agent/status', params=params)
            assert unauthenticated.status_code == 401
            response = await client.get(base + '/api/agent/status', params=params, headers={'X-Chat-Auth': token})
            response.raise_for_status()
            current = response.json()['conversation_activity']
            assert current['state'] not in ('unavailable', 'unknown', 'no_conversation')
            expected = await read_conversation_activity(username, character, 'normal', conversation)
            assert current['proactive_enabled'] == expected['proactive_enabled']
            assert response.headers['cache-control'] == 'no-store'
            assert not {'seed', 'reason', 'planner_json', 'source_message_id'} & current.keys()
            game = await client.get(base + '/api/agent/status', params={**params, 'mode': 'galgame_lock'},
                                    headers={'X-Chat-Auth': token})
            game.raise_for_status()
            assert game.json()['conversation_activity']['state'] == 'unsupported'
            result[label] = {'http_status': response.status_code, 'unauthenticated': 401,
                             'state': current['state'], 'game_isolated': True, 'cache_control': 'no-store'}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(verify(args.username))
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report), flush=True)
