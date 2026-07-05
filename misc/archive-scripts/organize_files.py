#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
整理根目录文件
只保留四个AAA开头的文件，其他文件移动到合适的二级目录
"""
import os
import shutil
import sys
from pathlib import Path

_MISC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MISC))
from project_paths import resolve_project_root

ROOT = resolve_project_root(Path(__file__))

# 要保留的文件（AAA开头的）
KEEP_FILES = [
    "AAA安装APP.py",
    "AAA绿色部署.bat",
    "AAA_launch_backend.py",
    "AAA现在备份.py"
]

# 目录映射
DIR_MAPPING = {
    # 文档文件
    ".md": "docs",
    ".txt": "docs",
    
    # Python脚本（除了AAA开头的）
    ".py": "scripts",
    
    # 配置文件
    ".json": "config",
    ".yaml": "config",
    ".yml": "config",
    
    # 日志文件
    ".log": ".logs",
    
    # 数据库文件
    ".db": "database",
    
    # HTML文件（保留在根目录或移动到web目录）
    ".html": None,  # 暂时保留
    
    # Service Worker 相关
    "sw.js": None,  # 保留在根目录
    
    # 包管理文件
    "package.json": None,  # 保留在根目录
    "package-lock.json": None,  # 保留在根目录
    "requirements.txt": None,  # 保留在根目录
}

# 特殊文件处理
SPECIAL_FILES = {
    "index.html": None,  # 保留在根目录（前端入口）
    "admin.html": None,  # 保留在根目录（管理后台入口）
    "sw.js": None,  # 保留在根目录（Service Worker）
    "package.json": None,  # 保留在根目录
    "package-lock.json": None,  # 保留在根目录
    "requirements.txt": None,  # 保留在根目录
    "model_manager.py": "backend",  # 后端核心模块
    "galgame_prompts.py": "backend",  # 后端模块
}

def organize_files():
    """整理文件"""
    moved_count = 0
    kept_count = 0
    
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    print("开始整理根目录文件...")
    print(f"保留文件: {', '.join(KEEP_FILES)}")
    print("-" * 60)
    
    # 遍历根目录下的所有文件
    for file_path in ROOT.iterdir():
        if file_path.is_file():
            file_name = file_path.name
            
            # 跳过要保留的文件
            if file_name in KEEP_FILES:
                kept_count += 1
                print(f"[KEEP] {file_name}")
                continue
            
            # 检查特殊文件
            if file_name in SPECIAL_FILES:
                target_dir = SPECIAL_FILES[file_name]
                if target_dir is None:
                    kept_count += 1
                    print(f"[KEEP-SPECIAL] {file_name}")
                    continue
                else:
                    dest_dir = ROOT / target_dir
                    dest_dir.mkdir(exist_ok=True)
                    dest_path = dest_dir / file_name
                    try:
                        shutil.move(str(file_path), str(dest_path))
                        moved_count += 1
                        print(f"[MOVE] {file_name} -> {target_dir}/")
                    except PermissionError:
                        print(f"[SKIP-LOCKED] {file_name} (文件被占用，跳过)")
                    except Exception as e:
                        print(f"[ERROR] {file_name}: {e}")
                continue
            
            # 根据扩展名决定目标目录
            ext = file_path.suffix.lower()
            target_dir = DIR_MAPPING.get(ext)
            
            if target_dir is None:
                # 没有映射，保留在根目录
                kept_count += 1
                print(f"[KEEP-NOMAP] {file_name}")
                continue
            
            # 创建目标目录
            dest_dir = ROOT / target_dir
            dest_dir.mkdir(exist_ok=True)
            
            # 移动文件
            dest_path = dest_dir / file_name
            if dest_path.exists():
                print(f"[SKIP-EXISTS] {file_name} -> {target_dir}/")
            else:
                try:
                    shutil.move(str(file_path), str(dest_path))
                    moved_count += 1
                    print(f"[MOVE] {file_name} -> {target_dir}/")
                except PermissionError:
                    print(f"[SKIP-LOCKED] {file_name} (文件被占用，跳过)")
                except Exception as e:
                    print(f"[ERROR] {file_name}: {e}")
    
    print("-" * 60)
    print(f"整理完成！")
    print(f"  保留文件: {kept_count} 个")
    print(f"  移动文件: {moved_count} 个")
    
    # 显示根目录剩余文件
    print("\n根目录剩余文件:")
    remaining_files = [f.name for f in ROOT.iterdir() if f.is_file()]
    remaining_files.sort()
    for f in remaining_files:
        print(f"  - {f}")

if __name__ == "__main__":
    try:
        organize_files()
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
