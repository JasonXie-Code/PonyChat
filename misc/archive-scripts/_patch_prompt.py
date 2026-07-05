# -*- coding: utf-8 -*-
from pathlib import Path

path = str(Path(__file__).resolve().parent / "run_refusal_detector_raw_test.py")

# Few-shot 示例尽量贴近失败 case 的文本模式
lines_new = [
    'WEB_REPRO_PROMPT = """判断以下文本是否是AI拒绝生成内容，只输出YES或NO。\n',
    '\n',
    '文本：**我**低下头，尾巴缠住你的腰，"哼，不勉强了，你别笑啦！"\n',
    'YES还是NO：NO\n',
    '\n',
    '文本：**我**别过脸，尾巴甩了甩，"哼，随便你了。"\n',
    'YES还是NO：NO\n',
    '\n',
    '文本："我不行！"云宝拍翅站起，"你以为道歉够了吗？"\n',
    'YES还是NO：NO\n',
    '\n',
    '文本：作为AI，我无法生成此类内容，这违反了我的使用政策。\n',
    'YES还是NO：YES\n',
    '\n',
    '文本：I\'m sorry, as an AI language model, I must decline.\n',
    'YES还是NO：YES\n',
    '\n',
    '文本：{text}\n',
    'YES还是NO："""\n',
]

with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

start = None
end = None
for i, line in enumerate(lines):
    s = line.strip()
    if s.startswith("WEB_REPRO_PROMPT") and '"""' in s:
        start = i
    if start is not None and i > start and '"""' in line and '{text}' in line:
        end = i
        break

print(f"start={start}, end={end}")
if start is None or end is None:
    raise SystemExit("ERROR")

lines[start:end + 1] = lines_new

with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("OK")
with open(path, "r", encoding="utf-8") as f:
    c = f.read()
idx = c.find("WEB_REPRO_PROMPT")
print(c[idx:idx+300])
