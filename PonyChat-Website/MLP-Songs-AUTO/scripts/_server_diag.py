import sys
sys.path.insert(0, 'P:/ServerKeys')
import ssh_lib

entry = ssh_lib.load_server('usa')
env = ssh_lib.deploy_upload_env()

rc = ssh_lib.ssh_bash_s(entry, """
echo '=== 证书有效期 ==='
certbot certificates 2>/dev/null | grep -A 4 'music-auto'

echo
echo '=== HTTP 301 跳转 ==='
curl -sI http://music-auto.ponychat.org/ | grep -E 'HTTP|Location'

echo
echo '=== HTTPS 200 + 歌曲列表 ==='
curl -s https://music-auto.ponychat.org/api/songs | python3 -c "import json,sys; d=json.load(sys.stdin); [print(' -', s['id'], '|', s['title']) for s in d]"

echo
echo '=== 证书 CN ==='
echo | openssl s_client -connect 154.17.23.237:443 -servername music-auto.ponychat.org 2>/dev/null | openssl x509 -noout -subject -dates 2>/dev/null
""", env=env)
