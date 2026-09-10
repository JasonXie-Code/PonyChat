"""Serve an existing isolated benchmark DB for Android acceptance on loopback."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import time


async def serve(workspace, port):
    import httpx
    import uvicorn
    import Backend
    from Backend import config, login_control
    from Backend.db import get_database, CharactersDAO, ConversationsDAO
    from Backend.agent_memory import jobs
    account_path = workspace / 'test-account.json'
    account = json.loads(account_path.read_text(encoding='utf8'))
    login_control.ALLOWED_APP_LOGIN_USERS |= {account['username']}
    db = get_database()
    assert Path(db.db_path).resolve().is_relative_to(workspace)
    await db.init()
    jobs.initialize(db.db_path)
    first_character = 'first_round_' + str(int(time.time()))
    first_conversation = first_character + '_chat'
    with sqlite3.connect(db.db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute(
            "SELECT message_id,role,content,timestamp FROM messages WHERE conversation_id='relationship_bench_chat' ORDER BY timestamp,rowid")]
    first_rows = []
    for row in rows:
        if row['message_id'] == 'user_2':
            break
        first_rows.append({**row, 'id': first_character + row['message_id'],
                           'message_id': first_character + row['message_id']})
    assert any(row['role'] == 'assistant' for row in first_rows)
    await CharactersDAO(db).save_characters(account['username'], [{
        'id': first_character, 'name': '青禾·首轮测试',
        'prompt': '你叫青禾，是成年陆马，温和，喜欢读书和散步。', 'bio': '关系加载首轮验收'}])
    await ConversationsDAO(db).save_conversation(account['username'], first_character, {
        'id': first_conversation, 'title': '首轮真实聊天回放', 'timestamp': int(time.time()*1000), 'messages': first_rows})
    # Keep this cold-page fixture cold until Android explicitly opens it.
    # Only its idle archive schedule is delayed; GET requests still enqueue now.
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE agent_memory_state SET due_at=unixepoch()+3600,last_review_day=date('now','+8 hours') WHERE username=? AND character_id=?",
                     (account['username'], first_character))
    account.update(first_character_id=first_character, first_conversation_id=first_conversation,
                   conversation_id='relationship_bench_chat')
    cold_character = first_character + '_fifteen'
    cold_conversation = cold_character + '_chat'
    await CharactersDAO(db).save_characters(account['username'], [{
        'id': cold_character, 'name': '青禾·十五轮测试',
        'prompt': '你叫青禾，是成年陆马，温和，喜欢读书和散步。', 'bio': '关系首次加载验收'}])
    await ConversationsDAO(db).save_conversation(account['username'], cold_character, {
        'id': cold_conversation, 'title': '十五轮真实聊天回放', 'timestamp': int(time.time()*1000),
        'messages': [{**row, 'id': cold_character + row['message_id'],
                      'message_id': cold_character + row['message_id']} for row in rows]})
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE agent_memory_state SET due_at=unixepoch()+3600,last_review_day=date('now','+8 hours') WHERE username=? AND character_id=?",
                     (account['username'], cold_character))
    account.update(cold_character_id=cold_character, cold_conversation_id=cold_conversation)
    account_path.write_text(json.dumps(account, ensure_ascii=False), encoding='utf8')
    config.httpx_client = httpx.AsyncClient(timeout=240)
    worker = asyncio.create_task(jobs.worker_loop())
    server = uvicorn.Server(uvicorn.Config(config.app, host='127.0.0.1', port=port, lifespan='off', log_level='warning'))
    @config.app.post('/api/benchmark/stop')
    async def stop():
        server.should_exit = True
        return {'stopping': True}
    print('Isolated Android relationship server ready on port ' + str(port), flush=True)
    try:
        await server.serve()
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await config.httpx_client.aclose()
        await db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('--port', type=int, default=8769)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[2]
    workspace = args.workspace.resolve()
    assert workspace.is_relative_to(source / '.tmp') and (workspace / 'test-account.json').is_file()
    from dotenv import dotenv_values
    for key, value in dotenv_values(source / '.env').items():
        if value is not None:
            os.environ.setdefault(key, value)
    os.environ.update(PONYCHAT_DB_PATH=str(workspace / 'test.db'),
                      PONYCHAT_BACKUP_DIR=str(workspace / 'backups'),
                      PONYCHAT_MLP_VECTOR_DB_PATH=str(workspace / 'vectors.db'),
                      PONYCHAT_VOICE_ENABLED='0')
    sys.path.insert(0, str(workspace))
    os.chdir(workspace)
    asyncio.run(serve(workspace, args.port))


if __name__ == '__main__':
    main()
