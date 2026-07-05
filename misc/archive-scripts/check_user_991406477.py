#!/usr/bin/env python3
"""确认原账号 A991406477 (user_id=34) 对话在各个备份中的状态"""
import sys
sys.path.insert(0, 'P:/ServerKeys')
from ssh_lib import load_server, prepare_ssh_key, cleanup_temp_key, deploy_upload_env, _no_proxy_args, ssh_common_opts
import subprocess

entry = load_server('usa')
act_key, tmp = prepare_ssh_key(entry.key)

BACKUPS = {
    '2026-04-27 18:45': '/opt/ponychat/Backend/backups/backup_20260427_184548.db',
    '2026-04-27 23:25': '/opt/ponychat/Backend/backups/backup_20260427_232548.db',
    '2026-04-27 23:35': '/opt/ponychat/Backend/backups/backup_20260427_233548.db',
    '2026-05-11 16:35': '/opt/ponychat/Backend/backups/backup_20260511_163501.db',
    '2026-05-11 21:18': '/opt/ponychat/Backend/backups/backup_20260511_211825.db',
    '当前库':            '/opt/ponychat/Backend/database/ponychat.db',
}

def ssh_sql(db, sql):
    cmd = f'sqlite3 {db} "{sql}"'
    args = (
        ['ssh'] + _no_proxy_args()
        + ['-i', str(act_key), '-p', str(entry.port)]
        + ssh_common_opts()
        + [entry.target, cmd]
    )
    r = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       env=deploy_upload_env(), stdin=subprocess.DEVNULL)
    return r.stdout.strip() or '0'

try:
    print(f"{'备份时间':<22} {'用户名':>14} {'对话数':>6} {'消息数':>6} {'软删对话':>8}")
    print('-' * 60)
    for label, db in BACKUPS.items():
        # 用户名
        uname = ssh_sql(db, "SELECT username FROM users WHERE id=34;")
        # 活跃对话数
        conv_active = ssh_sql(db,
            "SELECT COUNT(*) FROM conversations WHERE user_id=34 AND COALESCE(is_hidden,0)=0;")
        # 消息数（全部活跃对话）
        msg_count = ssh_sql(db,
            "SELECT COUNT(*) FROM messages m "
            "JOIN conversations c ON c.id=m.conversation_id "
            "WHERE c.user_id=34 AND m.deleted_at IS NULL;")
        # 软删对话数
        conv_hidden = ssh_sql(db,
            "SELECT COUNT(*) FROM conversations WHERE user_id=34 AND is_hidden=1;")
        print(f"{label:<22} {uname:>14} {conv_active:>6} {msg_count:>6} {conv_hidden:>8}")

    print('\n=== 当前库：原账号所有对话（含隐藏）===')
    from ssh_lib import ssh_exec
    db = '/opt/ponychat/Backend/database/ponychat.db'
    result = ssh_sql(db,
        "SELECT id, title, is_hidden, hidden_reason, updated_at "
        "FROM conversations WHERE user_id=34 ORDER BY updated_at DESC;"
    )
    print(result or '(无)')

    print('\n=== 当前库：deletion_audits 关于 user_id=34 的记录 ===')
    print(ssh_sql(db,
        "SELECT action, object_type, object_id, reason, source, created_at "
        "FROM deletion_audits WHERE user_id=34 ORDER BY created_at DESC LIMIT 20;"
    ))

finally:
    cleanup_temp_key(tmp)
