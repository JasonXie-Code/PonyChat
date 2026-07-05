#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手动备份脚本 - 每次对话后运行一次
使用方法: python backup_now.py
"""

import os
import sys
import zipfile
from pathlib import Path
from datetime import datetime

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import resolve_project_root, backend_package_dir

# 项目根目录（脚本位于 misc/tmp-scripts，不可再用 __file__.parent 当根目录）
PROJECT_DIR = resolve_project_root(Path(__file__))
BACKUP_DIR = backend_package_dir(PROJECT_DIR) / "backups"

# 排除的目录
EXCLUDED_DIRS = {
    'backups',
    '__pycache__',
    '.git',
    'node_modules',
    '.venv',
    'venv',
    'models'
}

# 排除的文件
EXCLUDED_FILES = {
    '.DS_Store',
    'Thumbs.db',
    '.gitignore',
    'desktop.ini'
}

def should_ignore(path):
    """判断是否应该忽略该路径"""
    path_obj = Path(path)
    
    # 检查是否在排除目录中
    for part in path_obj.parts:
        if part in EXCLUDED_DIRS:
            return True
    
    # 检查是否在排除文件中
    if path_obj.name in EXCLUDED_FILES:
        return True
    
    return False

def create_backup():
    """创建备份"""
    # 创建备份目录
    BACKUP_DIR.mkdir(exist_ok=True)
    
    # 生成备份文件名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_filename = f'manual_backup_{timestamp}.zip'
    backup_path = BACKUP_DIR / backup_filename
    
    print(f'\n💾 开始手动备份...')
    print(f'📦 备份文件: {backup_filename}')
    
    # 创建ZIP文件
    file_count = 0
    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(PROJECT_DIR):
            # 过滤排除的目录
            dirs[:] = [d for d in dirs if not should_ignore(Path(root) / d)]
            
            for file in files:
                file_path = Path(root) / file
                
                if should_ignore(file_path):
                    continue
                
                # 添加到ZIP
                arcname = file_path.relative_to(PROJECT_DIR)
                zipf.write(file_path, arcname)
                file_count += 1
    
    # 获取备份大小
    backup_size = backup_path.stat().st_size / (1024 * 1024)
    
    print(f'✅ 备份完成!')
    print(f'📁 已保存 {file_count} 个文件')
    print(f'💾 备份大小: {backup_size:.2f} MB')
    print(f'📂 保存位置: {backup_path}')
    print()
    
    # 清理旧备份(只保留最近10个手动备份)
    # cleanup_old_backups() 清理旧备份

def cleanup_old_backups(keep_count=10):
    """清理旧的手动备份,只保留最近的N个"""
    manual_backups = sorted(
        [f for f in BACKUP_DIR.glob('manual_backup_*.zip')],
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )
    
    # 删除多余的备份
    for old_backup in manual_backups[keep_count:]:
        print(f'🗑️  删除旧备份: {old_backup.name}')
        old_backup.unlink()

if __name__ == '__main__':
    try:
        create_backup()
    except KeyboardInterrupt:
        print('\n\n⏹️  备份已取消')
    except Exception as e:
        print(f'\n❌ 备份失败: {e}')
