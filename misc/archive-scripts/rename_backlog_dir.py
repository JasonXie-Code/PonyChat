#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
重命名 .backlog 文件夹为 .BackLogs 并更新所有代码引用
"""
import sys
import io
import shutil
from pathlib import Path

# 设置标准输出为 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 项目根目录
ROOT = Path(__file__).parent.parent
OLD_DIR = ROOT / ".backlog"
NEW_DIR = ROOT / ".BackLogs"

def rename_backlog_dir():
    """重命名 .backlog 为 .BackLogs"""
    print("=" * 60)
    print("重命名 .backlog 文件夹为 .BackLogs")
    print("=" * 60)
    
    # 检查源目录是否存在
    if not OLD_DIR.exists():
        print(f"⚠️  源目录不存在: {OLD_DIR}")
        print("   可能已经被重命名或不存在，跳过重命名操作")
    else:
        # 如果目标目录已存在，先删除
        if NEW_DIR.exists():
            print(f"⚠️  目标目录已存在: {NEW_DIR}")
            response = input("   是否删除现有目录并继续？(y/n): ")
            if response.lower() != 'y':
                print("❌ 操作已取消")
                return False
            shutil.rmtree(NEW_DIR)
        
        # 重命名目录
        try:
            print(f"📦 正在重命名: {OLD_DIR} -> {NEW_DIR}")
            shutil.move(str(OLD_DIR), str(NEW_DIR))
            print(f"✅ 目录重命名成功！")
        except Exception as e:
            print(f"❌ 重命名目录失败: {e}")
            return False
    
    # 更新代码引用
    print("\n" + "=" * 60)
    print("更新代码引用")
    print("=" * 60)
    
    files_to_update = [
        "AAA_launch_backend.py",
    ]
    
    replacements = [
        ('.backlog', '.BackLogs'),
        ('".backlog"', '".BackLogs"'),
        ("'.backlog'", "'.BackLogs'"),
        ('/.backlog', '/.BackLogs'),
        ("'/.backlog'", "'/.BackLogs'"),
        ('"/.backlog"', '"/.BackLogs"'),
        ('os.path.join(os.getcwd(), ".backlog"', 'os.path.join(os.getcwd(), ".BackLogs"'),
        ("os.path.join(os.getcwd(), '.backlog'", "os.path.join(os.getcwd(), '.BackLogs'"),
        ('Path(".backlog")', 'Path(".BackLogs")'),
        ("Path('.backlog')", "Path('.BackLogs')"),
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
    success = rename_backlog_dir()
    sys.exit(0 if success else 1)
