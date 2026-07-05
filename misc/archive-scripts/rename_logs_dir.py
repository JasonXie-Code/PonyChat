#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
重命名 .logs 文件夹为 .ChatLogs 并更新所有代码引用
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
OLD_DIR = ROOT / ".logs"
NEW_DIR = ROOT / ".ChatLogs"

# 需要更新的文件列表
FILES_TO_UPDATE = [
    "backend/config.py",
    "backend/utils.py",
    "backend/routes/suggestions.py",
    "AAA_launch_backend.py",
    "AAA安装APP.py",
]

def rename_directory():
    """重命名目录"""
    if not OLD_DIR.exists():
        print(f"[SKIP] 目录不存在: {OLD_DIR}")
        return False
    
    if NEW_DIR.exists():
        print(f"[SKIP] 目标目录已存在: {NEW_DIR}")
        return False
    
    try:
        shutil.move(str(OLD_DIR), str(NEW_DIR))
        print(f"[RENAME] {OLD_DIR.name} -> {NEW_DIR.name}")
        return True
    except Exception as e:
        print(f"[ERROR] 重命名失败: {e}")
        return False

def update_file_references(file_path):
    """更新文件中的引用"""
    file_path = ROOT / file_path
    if not file_path.exists():
        print(f"[SKIP] 文件不存在: {file_path}")
        return False
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # 替换所有 .logs 引用
        content = content.replace('.logs', '.ChatLogs')
        content = content.replace('".logs"', '".ChatLogs"')
        content = content.replace("'.logs'", "'.ChatLogs'")
        content = content.replace('"/.logs"', '"/.ChatLogs"')
        content = content.replace("'/.logs'", "'/.ChatLogs'")
        
        # 特殊处理：路径拼接
        content = content.replace('os.path.join(os.getcwd(), ".logs"', 'os.path.join(os.getcwd(), ".ChatLogs"')
        content = content.replace("os.path.join(os.getcwd(), '.logs'", "os.path.join(os.getcwd(), '.ChatLogs'")
        content = content.replace('Path(__file__).parent.parent.parent / ".logs"', 'Path(__file__).parent.parent.parent / ".ChatLogs"')
        content = content.replace('APP_DIR / ".logs"', 'APP_DIR / ".ChatLogs"')
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False
    except Exception as e:
        print(f"[ERROR] 更新失败 {file_path}: {e}")
        return False

def main():
    print("=" * 60)
    print("重命名 .logs 文件夹为 .ChatLogs")
    print("=" * 60)
    
    # 1. 重命名目录
    print("\n--- 重命名目录 ---")
    if rename_directory():
        print("[SUCCESS] 目录重命名成功")
    else:
        print("[SKIP] 目录重命名跳过")
    
    # 2. 更新文件引用
    print("\n--- 更新文件引用 ---")
    updated_count = 0
    for file_path in FILES_TO_UPDATE:
        if update_file_references(file_path):
            updated_count += 1
            print(f"[UPDATE] {file_path}")
        else:
            print(f"[NO-CHANGE] {file_path}")
    
    print("\n" + "=" * 60)
    print(f"完成！")
    print(f"  更新文件: {updated_count} 个")
    print("=" * 60)

if __name__ == "__main__":
    main()
