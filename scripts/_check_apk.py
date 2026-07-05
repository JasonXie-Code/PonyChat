import sys
from pathlib import Path
sys.path.insert(0, "P:/ServerKeys")
from ssh_lib import load_server, ssh_exec

srv = load_server("usa")
# 找 APK 文件
r = ssh_exec(srv, "find /var/www/ponychat-static /opt/ponychat -name '*.apk' 2>/dev/null || echo NO_APK")
print("APK files:", r)
# 测试 download url 响应
r2 = ssh_exec(srv, "curl -sI https://ponychat.top/download/apk | head -5")
print("URL response:", r2)
