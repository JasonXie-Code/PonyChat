#!/usr/bin/env python3
"""
恢复操作：
1. 将新注册的空账号 991406477 (user_id=98) 改名为 991406477_new
2. 将原账号 A991406477 (user_id=34) 改回 991406477
3. 使新账号的旧 token 失效（递增 token_version）
"""
import sys
sys.path.insert(0, 'P:/ServerKeys')
from ssh_lib import load_server, prepare_ssh_key, cleanup_temp_key, deploy_upload_env, _no_proxy_args, ssh_common_opts
import subprocess

entry = load_server('usa')
act_key, tmp = prepare_ssh_key(entry.key)
DB = '/opt/ponychat/Backend/database/ponychat.db'

def ssh_sql(sql):
    cmd = f'sqlite3 {DB} "{sql}"'
    args = (
        ['ssh'] + _no_proxy_args()
        + ['-i', str(act_key), '-p', str(entry.port)]
        + ssh_common_opts()
        + [entry.target, cmd]
    )
    r = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       env=deploy_upload_env(), stdin=subprocess.DEVNULL)
    return r.stdout.strip(), r.returncode

def do(label, sql):
    out, rc = ssh_sql(sql)
    status = '✅' if rc == 0 else '❌'
    print(f'{status} {label}')
    if out:
        print(f'   → {out}')
    if rc != 0:
        raise RuntimeError(f'操作失败: {label}')
    return out

try:
    print('=== 执行前确认 ===')
    u34, _ = ssh_sql("SELECT username FROM users WHERE id=34;")
    u98, _ = ssh_sql("SELECT username FROM users WHERE id=98;")
    print(f'user_id=34 当前用户名: {u34}')
    print(f'user_id=98 当前用户名: {u98}')
    assert u34 == 'A991406477', f'预期 A991406477，实际是 {u34}'
    assert u98 == '991406477', f'预期 991406477，实际是 {u98}'
    print()

    # 第一步：把空账号 user_id=98 改名为 991406477_new
    do('将空账号 991406477 (user_id=98) 改名为 991406477_new',
       "UPDATE users SET username='991406477_new' WHERE id=98;")

    # 第二步：把原账号 user_id=34 改回 991406477
    do('将原账号 A991406477 (user_id=34) 改回 991406477',
       "UPDATE users SET username='991406477' WHERE id=34;")

    # 第三步：使空账号已签发的 token 失效（递增 token_version，旧 JWT 校验时 version 不匹配即拒绝）
    do('使空账号旧 token 失效（token_version + 1）',
       "UPDATE users SET token_version = COALESCE(token_version, 0) + 1 WHERE id=98;")

    # 第四步：将 normal_image_contexts / normal_image_context_state 中属于原账号的记录改回正确用户名
    # （当前这些表里 username='991406477' 的记录实际属于 user_id=34，改回后仍正确）
    do('normal_image_contexts 用户名保持 991406477（无需修改，已正确）',
       "SELECT COUNT(*) FROM normal_image_contexts WHERE username='991406477';")

    print()
    print('=== 执行后验证 ===')
    v34, _ = ssh_sql("SELECT username FROM users WHERE id=34;")
    v98, _ = ssh_sql("SELECT username FROM users WHERE id=98;")
    conv34, _ = ssh_sql(
        "SELECT COUNT(*) FROM conversations WHERE user_id=34 AND COALESCE(is_hidden,0)=0;"
    )
    msg34, _ = ssh_sql(
        "SELECT COUNT(*) FROM messages m "
        "JOIN conversations c ON c.id=m.conversation_id "
        "WHERE c.user_id=34 AND m.deleted_at IS NULL;"
    )
    print(f'user_id=34 → 用户名: {v34}  活跃对话: {conv34}  消息: {msg34}')
    print(f'user_id=98 → 用户名: {v98}')
    print()
    print('✅ 完成！用户现在用 991406477 登录即可看到原来的全部聊天记录。')
    print('   空账号已改名为 991406477_new，原 token 已失效。')

finally:
    cleanup_temp_key(tmp)
