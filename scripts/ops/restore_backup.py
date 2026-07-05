"""
备份恢复工具
从备份中恢复文件
"""

import sys
import zipfile
import shutil
from pathlib import Path
from datetime import datetime

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MISC = _REPO_ROOT / "misc"
sys.path.insert(0, str(_MISC))
from project_paths import resolve_project_root, backend_package_dir

PROJECT_ROOT = resolve_project_root(_REPO_ROOT)
BACKUP_DIR = backend_package_dir(PROJECT_ROOT) / "backups"

def list_backups():
    """列出所有备份"""
    backups = sorted(
        list(BACKUP_DIR.glob("backup_*.zip"))
        + list(BACKUP_DIR.glob("manual_backup_*.zip")), 
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    
    if not backups:
        print("❌ 没有找到备份文件")
        return []
    
    print("\n" + "=" * 80)
    print("📂 可用备份列表:")
    print("=" * 80)
    
    for i, backup in enumerate(backups, 1):
        mod_time = datetime.fromtimestamp(backup.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        size = backup.stat().st_size / 1024 / 1024
        print(f"{i}. {backup.name:<35} | {mod_time} | {size:>8.2f} MB")
    
    print("=" * 80)
    return backups

def restore_backup(backup_path, target_dir=None):
    """恢复备份"""
    if target_dir is None:
        target_dir = PROJECT_ROOT
    
    print(f"\n🔄 开始恢复备份: {backup_path.name}")
    print(f"📁 恢复到: {target_dir}")
    
    confirm = input("\n⚠️  警告: 这将覆盖现有文件! 确认继续? (yes/no): ")
    
    if confirm.lower() != 'yes':
        print("❌ 已取消恢复操作")
        return
    
    try:
        with zipfile.ZipFile(backup_path, 'r') as zipf:
            file_count = len(zipf.namelist())
            print(f"\n📦 解压 {file_count} 个文件...")
            
            zipf.extractall(target_dir)
            
            print(f"✅ 恢复完成! 已恢复 {file_count} 个文件")
            
    except Exception as e:
        print(f"❌ 恢复失败: {e}")

def main():
    """主函数"""
    backups = list_backups()
    
    if not backups:
        return
    
    print(f"\n请选择要恢复的备份 (1-{len(backups)}):")
    
    try:
        choice = int(input("输入编号: "))
        
        if 1 <= choice <= len(backups):
            selected_backup = backups[choice - 1]
            restore_backup(selected_backup)
        else:
            print("❌ 无效的编号")
            
    except ValueError:
        print("❌ 请输入有效的数字")
    except KeyboardInterrupt:
        print("\n\n❌ 已取消")

if __name__ == "__main__":
    main()
