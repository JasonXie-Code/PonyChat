"""Run real HTTP acceptance using a fresh DB containing only System role fixtures."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def run(workspace: Path, source: Path) -> int:
    import httpx
    import uvicorn
    from Backend import config, login_control
    from Backend.db import get_database
    from Backend.agent_memory import jobs
    if os.getenv('PONYCHAT_SOUND_MARK_SUITE') == 'three-character':
        from Backend.scripts import test_sound_mark_three_character as acceptance
    else:
        from Backend.scripts import test_normal_sound_mark_acceptance as acceptance

    db = get_database()
    assert Path(db.db_path).resolve() == workspace / 'test.db'
    await db.init()
    # Read only public System character definitions, never user conversations.
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src:
        src.row_factory = sqlite3.Row
        rows = [dict(row) for row in src.execute(
            "SELECT c.* FROM characters c JOIN users u ON u.id=c.user_id "
            "WHERE u.username='System' AND COALESCE(c.is_hidden,0)=0")]
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO users(username,password) VALUES('System','isolated-disabled')")
        user_id = conn.execute("SELECT id FROM users WHERE username='System'").fetchone()[0]
        columns = {r[1] for r in conn.execute('PRAGMA table_info(characters)')}
        for row in rows:
            row = {k: v for k, v in row.items() if k in columns}
            row['user_id'] = user_id
            conn.execute(f"INSERT OR REPLACE INTO characters ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))
    original_create = acceptance.create_test_user

    def create_allowed_user(conn):
        username, user_id = original_create(conn)
        login_control.ALLOWED_APP_LOGIN_USERS |= {username}
        return username, user_id

    acceptance.create_test_user = create_allowed_user
    config.httpx_client = httpx.AsyncClient(timeout=240)
    jobs.initialize(db.db_path)
    server = uvicorn.Server(uvicorn.Config(config.app, host='127.0.0.1', port=5001,
                                          lifespan='off', log_level='warning'))
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            if task.done():
                await task
                raise RuntimeError('Isolated server failed to start')
            await asyncio.sleep(0.1)
        return await acceptance.main()
    finally:
        server.should_exit = True
        await task
        await config.httpx_client.aclose()
        await db.close()


def main() -> int:
    if sys.version_info < (3, 11):
        raise SystemExit('Use the project .venv/Scripts/python.exe (Python 3.11 or later).')
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    source = Path(os.getenv('PONYCHAT_DB_PATH', str(Path(os.environ['LOCALAPPDATA']) / 'PonyChat/ponychat.db'))).resolve()
    workspace = ROOT / '.tmp' / ('sound-mark-' + time.strftime('%Y%m%d-%H%M%S'))
    workspace.mkdir(parents=True, exist_ok=False)
    os.environ.update(PONYCHAT_DB_PATH=str(workspace / 'test.db'),
                      PONYCHAT_BACKUP_DIR=str(workspace / 'backups'),
                      PONYCHAT_MLP_VECTOR_DB_PATH=str(workspace / 'vectors.db'),
                      PONYCHAT_VOICE_ENABLED='0',
                      PONYCHAT_TEST_BASE_URL='http://127.0.0.1:5001',
                      PONYCHAT_SOUND_MARK_LOG=str(workspace / 'cases.jsonl'))
    print('ISOLATED_WORKSPACE ' + str(workspace), flush=True)
    return asyncio.run(run(workspace.resolve(), source))


if __name__ == '__main__':
    raise SystemExit(main())
