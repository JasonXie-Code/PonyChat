#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
移动 model_config.json 从根目录到 config/ 目录并更新所有引用
"""
import sys
import io
import shutil
import json
from pathlib import Path

# 设置标准输出为 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 项目根目录
ROOT = Path(__file__).parent.parent
OLD_FILE = ROOT / "model_config.json"
NEW_FILE = ROOT / "config" / "model_config.json"

def move_model_config():
    """移动 model_config.json 到 config/ 目录"""
    print("=" * 60)
    print("移动 model_config.json 到 config/ 目录")
    print("=" * 60)
    
    # 检查源文件是否存在
    if not OLD_FILE.exists():
        print(f"⚠️  源文件不存在: {OLD_FILE}")
        print("   可能已经被移动或不存在，跳过移动操作")
    else:
        # 如果目标文件已存在，比较内容
        if NEW_FILE.exists():
            print(f"⚠️  目标文件已存在: {NEW_FILE}")
            try:
                with open(OLD_FILE, 'r', encoding='utf-8') as f:
                    old_content = json.load(f)
                with open(NEW_FILE, 'r', encoding='utf-8') as f:
                    new_content = json.load(f)
                
                if old_content != new_content:
                    print("   根目录和 config/ 目录的文件内容不同")
                    response = input("   是否用根目录的文件替换 config/ 目录的文件？(y/n): ")
                    if response.lower() == 'y':
                        shutil.copy2(OLD_FILE, NEW_FILE)
                        print(f"✅ 已替换: {NEW_FILE}")
                    else:
                        print("   保留 config/ 目录的文件")
                else:
                    print("   文件内容相同，直接删除根目录的文件")
            except Exception as e:
                print(f"   比较文件失败: {e}")
                response = input("   是否继续移动？(y/n): ")
                if response.lower() != 'y':
                    return False
        
        # 移动或删除根目录的文件
        try:
            if NEW_FILE.exists() and OLD_FILE.exists():
                # 如果目标文件已存在且内容相同，直接删除源文件
                try:
                    with open(OLD_FILE, 'r', encoding='utf-8') as f:
                        old_content = json.load(f)
                    with open(NEW_FILE, 'r', encoding='utf-8') as f:
                        new_content = json.load(f)
                    if old_content == new_content:
                        OLD_FILE.unlink()
                        print(f"✅ 已删除根目录的重复文件: {OLD_FILE}")
                    else:
                        shutil.move(str(OLD_FILE), str(NEW_FILE))
                        print(f"✅ 文件已移动: {OLD_FILE} -> {NEW_FILE}")
                except:
                    shutil.move(str(OLD_FILE), str(NEW_FILE))
                    print(f"✅ 文件已移动: {OLD_FILE} -> {NEW_FILE}")
            elif OLD_FILE.exists():
                shutil.move(str(OLD_FILE), str(NEW_FILE))
                print(f"✅ 文件已移动: {OLD_FILE} -> {NEW_FILE}")
        except Exception as e:
            print(f"❌ 移动文件失败: {e}")
            return False
    
    # 更新代码引用
    print("\n" + "=" * 60)
    print("更新代码引用")
    print("=" * 60)
    
    files_to_update = [
        "backend/model_manager.py",
    ]
    
    replacements = [
        ('Path("model_config.json")', 'Path("config/model_config.json")'),
        ("Path('model_config.json')", "Path('config/model_config.json')"),
        ('"model_config.json"', '"config/model_config.json"'),
        ("'model_config.json'", "'config/model_config.json'"),
        ('os.path.join(os.getcwd(), "model_config.json"', 'os.path.join(os.getcwd(), "config", "model_config.json"'),
        ("os.path.join(os.getcwd(), 'model_config.json'", "os.path.join(os.getcwd(), 'config', 'model_config.json'"),
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
    success = move_model_config()
    sys.exit(0 if success else 1)
