import sys
sys.path.insert(0, "P:/ServerKeys")
from ssh_lib import load_server, ssh_exec

srv = load_server("usa")

# 查看 ponychat-www 完整 sites-enabled 配置（仅第一个 server 块，80 行）
r1 = ssh_exec(srv, "cat /etc/nginx/sites-enabled/ponychat-www | head -130")
print(r1)
