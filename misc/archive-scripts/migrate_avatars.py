#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
迁移头像文件到 database/avatars/ 目录
"""
import os
import shutil
import sys
from pathlib import Path

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import backend_package_dir, resolve_project_root

ROOT = resolve_project_root(Path(__file__))
_BACKEND = backend_package_dir(ROOT)
USER_DATA_ROOT = ROOT / "user_data"
CHARACTER_DATA_ROOT = ROOT / "character_data"
TARGET_ROOT = _BACKEND / "database" / "avatars"

def migrate_user_avatars():
    """迁移用户头像"""
    if not USER_DATA_ROOT.exists():
        print(f"[SKIP] 用户数据目录不存在: {USER_DATA_ROOT}")
        return 0
    
    moved_count = 0
    for username_dir in USER_DATA_ROOT.iterdir():
        if not username_dir.is_dir() or username_dir.name == "users.json":
            continue
        
        avatars_dir = username_dir / "avatars"
        if not avatars_dir.exists():
            continue
        
        # 目标目录：database/avatars/user_data/{username}/
        target_dir = TARGET_ROOT / "user_data" / username_dir.name
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # 移动所有头像文件
        for avatar_file in avatars_dir.iterdir():
            if avatar_file.is_file():
                target_file = target_dir / avatar_file.name
                try:
                    if target_file.exists():
                        print(f"[SKIP] 已存在: {target_file}")
                        continue
                    shutil.move(str(avatar_file), str(target_file))
                    moved_count += 1
                    print(f"[MOVE] {avatar_file} -> {target_file}")
                except Exception as e:
                    print(f"[ERROR] 移动失败 {avatar_file}: {e}")
        
        # 如果原目录为空，删除它
        try:
            if avatars_dir.exists() and not any(avatars_dir.iterdir()):
                avatars_dir.rmdir()
                print(f"[CLEAN] 删除空目录: {avatars_dir}")
        except Exception as e:
            print(f"[WARN] 无法删除目录 {avatars_dir}: {e}")
    
    return moved_count

def migrate_character_avatars():
    """迁移角色头像"""
    if not CHARACTER_DATA_ROOT.exists():
        print(f"[SKIP] 角色数据目录不存在: {CHARACTER_DATA_ROOT}")
        return 0
    
    avatars_dir = CHARACTER_DATA_ROOT / "avatars"
    if not avatars_dir.exists():
        return 0
    
    # 目标目录：database/avatars/character_data/
    target_dir = TARGET_ROOT / "character_data"
    target_dir.mkdir(parents=True, exist_ok=True)
    
    moved_count = 0
    for avatar_file in avatars_dir.iterdir():
        if avatar_file.is_file():
            target_file = target_dir / avatar_file.name
            try:
                if target_file.exists():
                    print(f"[SKIP] 已存在: {target_file}")
                    continue
                shutil.move(str(avatar_file), str(target_file))
                moved_count += 1
                print(f"[MOVE] {avatar_file} -> {target_file}")
            except Exception as e:
                print(f"[ERROR] 移动失败 {avatar_file}: {e}")
    
    # 如果原目录为空，删除它
    try:
        if avatars_dir.exists() and not any(avatars_dir.iterdir()):
            avatars_dir.rmdir()
            print(f"[CLEAN] 删除空目录: {avatars_dir}")
    except Exception as e:
        print(f"[WARN] 无法删除目录 {avatars_dir}: {e}")
    
    return moved_count

def main():
    print("=" * 60)
    print("开始迁移头像文件到 database/avatars/")
    print("=" * 60)
    
    # 创建目标目录
    TARGET_ROOT.mkdir(parents=True, exist_ok=True)
    
    # 迁移用户头像
    print("\n--- 迁移用户头像 ---")
    user_count = migrate_user_avatars()
    
    # 迁移角色头像
    print("\n--- 迁移角色头像 ---")
    char_count = migrate_character_avatars()
    
    print("\n" + "=" * 60)
    print(f"迁移完成！")
    print(f"  用户头像: {user_count} 个")
    print(f"  角色头像: {char_count} 个")
    print(f"  总计: {user_count + char_count} 个")
    print("=" * 60)

if __name__ == "__main__":
    main()
