"""一次性缩进修复脚本：目标文件为仓库内 backend/routes/chat.py（请按需修改）。"""
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
file_path = str(_ROOT / "backend" / "routes" / "chat.py")

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 定位 try 块的开始位置 (大约 527 行)
try_start_index = -1
for i, line in enumerate(lines):
    if "try:" in line and "model_name = active_model.get" in lines[i+1]:
        try_start_index = i
        break
    # 或者如果我之前插入了 try，找那个位置
    # Step 788 插入的 try 在 519 行附近
    if line.strip() == "try:":
        # 检查上下文是否匹配
        if i < len(lines)-10 and "0.5 获取用户信息" in "".join(lines[i:i+10]):
            try_start_index = i
            break

if try_start_index == -1:
    print("Could not find try block start")
    # 强制定位到大概位置
    for i, line in enumerate(lines):
        if "model_name = active_model.get" in line:
            try_start_index = i - 1
            if lines[try_start_index].strip() != "try:":
                print("Try not found immediately before model_name assignment")
                # 可能是空的或注释
            break

print(f"Try block starts at line {try_start_index + 1}")

# 需要缩进的范围：从 try 下一行开始，直到 except 之前
# 但是之前的 edits 可能已经缩进了一部分 (比如整个上半部分)
# 让我们检查 625 行 (user_context_prompt) 的缩进
# 如果它是 4 空格，且 try 是 4 空格，那它需要缩进到 8 空格

target_line_index = -1
for i, line in enumerate(lines):
    if "if user_context_prompt:" in line:
        target_line_index = i
        break

print(f"Target indent check at line {target_line_index + 1}: {repr(lines[target_line_index][:10])}")

# 找到 except 块的开始
except_index = -1
for i in range(len(lines)-1, 0, -1):
    if lines[i].strip().startswith("except Exception as e:"):
        except_index = i
        break

print(f"Except block starts at line {except_index + 1}")

# 执行缩进
new_lines = []
for i, line in enumerate(lines):
    # try 块本身及其之后的代码 (除了 loop 内部已经缩进好的部分？)
    # 不，最安全的方式是：
    # 1. 保持 try 之前以及 try 行不变
    # 2. 从 try+1 到 except-1，确保每一行都至少有 8 空格缩进 (除了空行)
    # 对于我之前已经缩进过的部分 (528 - 624)，它们可能已经是 8 空格了。
    # 对于 625 - except_index-1，它们只有 4 空格。
    
    should_indent = False
    if try_start_index < i < except_index:
        # 检查当前缩进
        stripped = line.lstrip()
        if not stripped:
            new_lines.append(line)
            continue
            
        current_indent = len(line) - len(stripped)
        if current_indent == 4:
            should_indent = True
        elif current_indent == 8:
            # 可能是已经缩进好的，也可能是原本逻辑就需要 8 空格
            # 但既然 user_context_prompt (625) 是 4 空格，那么这之后的所有 4 空格都要变 8
            pass

    if should_indent:
        new_lines.append("    " + line)
    else:
        new_lines.append(line)

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("File fixed.")
