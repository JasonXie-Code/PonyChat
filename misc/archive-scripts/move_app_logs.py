#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
移动 App/.logs 文件夹到根目录并改名为 .AppLogs
"""
import sys
import io
import shutil
from pathlib import Path

# 设置标准输出为 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import resolve_project_root

ROOT = resolve_project_root(Path(__file__))
OLD_DIR = ROOT / "app" / ".logs"
if not OLD_DIR.exists():
    _legacy = ROOT / "App" / ".logs"
    if _legacy.exists():
        OLD_DIR = _legacy
NEW_DIR = ROOT / ".AppLogs"

def move_app_logs_dir():
    """移动 App/.logs 到根目录并改名为 .AppLogs"""
    print("=" * 60)
    print("移动 App/.logs 文件夹到根目录并改名为 .AppLogs")
    print("=" * 60)
    
    # 检查源目录是否存在
    if not OLD_DIR.exists():
        print(f"⚠️  源目录不存在: {OLD_DIR}")
        print("   可能已经被移动或不存在，跳过移动操作")
    else:
        # 如果目标目录已存在，先删除
        if NEW_DIR.exists():
            print(f"⚠️  目标目录已存在: {NEW_DIR}")
            response = input("   是否删除现有目录并继续？(y/n): ")
            if response.lower() != 'y':
                print("❌ 操作已取消")
                return False
            shutil.rmtree(NEW_DIR)
        
        # 移动目录
        try:
            print(f"📦 正在移动: {OLD_DIR} -> {NEW_DIR}")
            shutil.move(str(OLD_DIR), str(NEW_DIR))
            print(f"✅ 目录移动成功！")
        except Exception as e:
            print(f"❌ 移动目录失败: {e}")
            return False
    
    # 更新代码引用
    print("\n" + "=" * 60)
    print("更新代码引用")
    print("=" * 60)
    
    files_to_update = [
        "AAA安装APP.py",
    ]
    
    replacements = [
        ('APP_DIR / ".ChatLogs"', 'PROJECT_ROOT / ".AppLogs"'),
        ('APP_DIR / ".logs"', 'PROJECT_ROOT / ".AppLogs"'),
        ('App/.logs', '.AppLogs'),
        ('App\\.logs', '.AppLogs'),
        ('App/.ChatLogs', '.AppLogs'),
        ('App\\.ChatLogs', '.AppLogs'),
    ]
    
    updated_count = 0
    for filename in files_to_update:
        file_path = ROOT / filename
        if not file_path.exists():
            print(f"⚠️  文件不存在: {file_path}")
            continue
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            for old, new in replacements:
                if old in content:
                    content = content.replace(old, new)
                    print(f"  ✅ {filename}: {old} -> {new}")
            
            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                updated_count += 1
                print(f"✅ 已更新: {filename}")
        except Exception as e:
            print(f"❌ 更新文件失败 {filename}: {e}")
    
    print(f"\n✅ 完成！共更新 {updated_count} 个文件")
    return True

if __name__ == "__main__":
    success = move_app_logs_dir()
    sys.exit(0 if success else 1)
