"""
迁移脚本：将用户目录中的角色头像移动到角色头像目录
"""
import os
import json
import shutil
import sqlite3
import sys
from pathlib import Path

# 设置输出编码为UTF-8
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import backend_package_dir, resolve_project_root

# 配置路径（user_data 在项目根；数据库在 backend/database）
PROJECT_ROOT = resolve_project_root(Path(__file__))
_BACKEND = backend_package_dir(PROJECT_ROOT)
USER_DATA_ROOT = PROJECT_ROOT / "user_data"
AVATARS_ROOT = _BACKEND / "database" / "avatars"
USER_AVATARS_ROOT = AVATARS_ROOT / "user_data"
CHARACTER_AVATARS_ROOT = AVATARS_ROOT / "character_data"
DB_PATH = _BACKEND / "database" / "ponychat.db"

def is_user_avatar(filename: str) -> bool:
    """判断是否是用户头像（以avatar_开头）"""
    return filename.startswith("avatar_")

def migrate_character_avatars():
    """迁移角色头像到character_data目录"""
    moved_count = 0
    updated_json_count = 0
    updated_db_count = 0
    
    print("[开始扫描用户目录...]")
    
    # 确保角色头像目录存在
    CHARACTER_AVATARS_ROOT.mkdir(parents=True, exist_ok=True)
    
    # 1. 扫描所有用户目录
    if not USER_AVATARS_ROOT.exists():
        print(f"[错误] 用户头像目录不存在: {USER_AVATARS_ROOT}")
        return
    
    for user_folder in USER_AVATARS_ROOT.iterdir():
        if not user_folder.is_dir():
            continue
        
        username = user_folder.name
        print(f"\n[处理用户] {username}")
        
        # 2. 扫描该用户目录中的所有头像文件
        avatar_files = list(user_folder.glob("*.jpg"))
        character_avatars = []
        
        for avatar_file in avatar_files:
            filename = avatar_file.name
            # 如果不是用户头像（不以avatar_开头），则认为是角色头像
            if not is_user_avatar(filename):
                character_avatars.append((avatar_file, filename))
                print(f"  [发现角色头像] {filename}")
        
        # 3. 移动角色头像文件
        for avatar_file, filename in character_avatars:
            try:
                target_path = CHARACTER_AVATARS_ROOT / filename
                
                # 如果目标文件已存在，跳过（避免覆盖）
                if target_path.exists():
                    print(f"  [警告] 文件已存在，跳过: {filename}")
                    continue
                
                # 移动文件
                shutil.move(str(avatar_file), str(target_path))
                moved_count += 1
                print(f"  [已移动] {filename} -> character_data/")
                
            except Exception as e:
                print(f"  [错误] 移动失败 {filename}: {e}")
        
        # 4. 更新JSON文件中的路径引用
        user_char_file = USER_DATA_ROOT / username / "characters.json"
        if user_char_file.exists():
            try:
                with open(user_char_file, 'r', encoding='utf-8') as f:
                    characters = json.load(f)
                
                updated = False
                for char in characters:
                    avatar = char.get("avatar", "")
                    if avatar and "user_data" in avatar and "/avatars/" in avatar:
                        # 提取文件名
                        filename = avatar.split("/avatars/")[-1]
                        # 如果是角色头像（不是用户头像）
                        if filename in [f for _, f in character_avatars]:
                            # 更新路径为character_data格式
                            new_path = f"character_data/avatars/{filename}"
                            char["avatar"] = new_path
                            updated = True
                            print(f"  [更新JSON路径] {filename}")
                
                if updated:
                    with open(user_char_file, 'w', encoding='utf-8') as f:
                        json.dump(characters, f, indent=4, ensure_ascii=False)
                    updated_json_count += 1
                    print(f"  [已更新JSON文件]")
                    
            except Exception as e:
                print(f"  [错误] 更新JSON失败: {e}")
    
    # 5. 更新数据库中的路径引用
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            
            # 获取所有角色数据
            cursor.execute("SELECT id, avatar FROM characters WHERE avatar LIKE 'user_data/%/avatars/%'")
            rows = cursor.fetchall()
            
            for char_id, old_avatar in rows:
                # 提取文件名
                if "/avatars/" in old_avatar:
                    filename = old_avatar.split("/avatars/")[-1]
                    # 如果不是用户头像，更新路径
                    if not is_user_avatar(filename):
                        new_path = f"character_data/avatars/{filename}"
                        cursor.execute(
                            "UPDATE characters SET avatar = ? WHERE id = ?",
                            (new_path, char_id)
                        )
                        updated_db_count += 1
                        print(f"  [更新数据库路径] {char_id[:8]}... -> {filename}")
            
            conn.commit()
            conn.close()
            print(f"\n[已更新数据库] {updated_db_count} 条记录")
            
        except Exception as e:
            print(f"[错误] 更新数据库失败: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n[迁移完成统计]")
    print(f"  - 移动文件: {moved_count} 个")
    print(f"  - 更新JSON: {updated_json_count} 个文件")
    print(f"  - 更新数据库: {updated_db_count} 条记录")

if __name__ == "__main__":
    print("[开始迁移角色头像...]")
    migrate_character_avatars()
    print("\n[迁移完成]")
