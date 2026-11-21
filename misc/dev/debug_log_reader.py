import json
import sys
from pathlib import Path

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import resolve_project_root, chatlogs_dir

if len(sys.argv) < 2:
    print("用法: python misc/dev/debug_log_reader.py <日志文件绝对路径> 或 <相对 var/chatlogs 的子路径>")
    sys.exit(1)

_root = resolve_project_root(Path(__file__))
_arg = Path(sys.argv[1])
log_path = _arg if _arg.is_file() else (chatlogs_dir(_root) / sys.argv[1])

with open(log_path, "r", encoding="utf-8") as f:
    content = f.read()
    # 日志赋给变量，需去掉 'const debug_log = ' 与 ';'
    json_str = content.strip().replace("const debug_log = ", "", 1)
    if json_str.endswith(";"):
        json_str = json_str[:-1]

    data = json.loads(json_str)
    system_msg = data["data"]["messages"][0]["content"]

    print("--- START OF SYSTEM PROMPT ---")
    print(system_msg[:500])
    print("\n--- END OF SYSTEM PROMPT ---")
    print(system_msg[-1500:])
