#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
最终整理：只保留四个AAA文件，移动其他文件并更新所有引用
"""
import os
import shutil
import re
from pathlib import Path

# 根目录
ROOT = Path(__file__).parent.parent

# 要保留的文件（AAA开头的）
KEEP_FILES = [
    "AAA安装APP.py",
    "AAA绿色部署.bat",
    "AAA_launch_backend.py",
    "AAA现在备份.py"
]

# 文件移动映射：{文件名: 目标目录}
FILE_MOVES = {
    "index.html": "web",
    "admin.html": "web",
    "sw.js": "web",
    "package.json": "web",
    "package-lock.json": "web",
    "requirements.txt": "config",
    "backend.log": ".logs",
}

# 需要更新引用的文件映射：{文件路径: [(旧路径, 新路径), ...]}
REFERENCE_UPDATES = {
    # backend/__init__.py 路由注册
    "backend/__init__.py": [
        ('FileResponse("index.html")', 'FileResponse("web/index.html")'),
        ('FileResponse("admin.html")', 'FileResponse("web/admin.html")'),
    ],
    # backend/routes/system.py 系统路由
    "backend/routes/system.py": [
        ('FileResponse("index.html")', 'FileResponse("web/index.html")'),
    ],
    # backend/config.py 配置
    "backend/config.py": [
        ('log_file = "backend.log"', 'log_file = ".logs/backend.log"'),
        ('"/index.html"', '"/web/index.html"'),
    ],
    # scripts/launch/AAA_launch_backend.py（历史键名曾用 AAA启动后端.py）
    "scripts/launch/AAA_launch_backend.py": [
        ('self.log_file = "backend.log"', 'self.log_file = ".logs/backend.log"'),
        ("'backend.log'", "'.logs/backend.log'"),
        ('"backend.log"', '".logs/backend.log"'),
        ("os.path.join(os.getcwd(), 'backend.log')", "os.path.join(os.getcwd(), '.logs', 'backend.log')"),
    ],
    # AAA绿色部署.bat
    "AAA绿色部署.bat": [
        ('"%PROJECT_ROOT%\\requirements.txt"', '"%PROJECT_ROOT%\\config\\requirements.txt"'),
        ('requirements.txt', 'config\\requirements.txt'),
    ],
}

def update_file_references(file_path, updates):
    """更新文件中的引用"""
    if not file_path.exists():
        return False
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        for old_ref, new_ref in updates:
            content = content.replace(old_ref, new_ref)
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False
    except Exception as e:
        print(f"  [ERROR] 更新引用失败 {file_path}: {e}")
        return False

def organize_files():
    """整理文件并更新引用"""
    moved_count = 0
    updated_count = 0
    
    print("=" * 60)
    print("开始最终整理：只保留四个AAA文件")
    print("=" * 60)
    
    # 1. 创建必要的目录
    for target_dir in set(FILE_MOVES.values()):
        target_path = ROOT / target_dir
        target_path.mkdir(exist_ok=True)
        print(f"[CREATE] 目录: {target_dir}/")
    
    # 2. 移动文件
    print("\n--- 移动文件 ---")
    for file_name, target_dir in FILE_MOVES.items():
        source_path = ROOT / file_name
        if not source_path.exists():
            print(f"[SKIP] {file_name} (不存在)")
            continue
        
        target_path = ROOT / target_dir / file_name
        try:
            if target_path.exists():
                # 备份已存在的文件
                backup_path = target_path.with_suffix(target_path.suffix + '.backup')
                shutil.move(str(target_path), str(backup_path))
                print(f"[BACKUP] {target_dir}/{file_name} -> {target_dir}/{file_name}.backup")
            
            shutil.move(str(source_path), str(target_path))
            moved_count += 1
            print(f"[MOVE] {file_name} -> {target_dir}/")
        except PermissionError:
            print(f"[SKIP-LOCKED] {file_name} (文件被占用)")
        except Exception as e:
            print(f"[ERROR] {file_name}: {e}")
    
    # 3. 更新引用
    print("\n--- 更新引用 ---")
    for file_path_str, updates in REFERENCE_UPDATES.items():
        file_path = ROOT / file_path_str
        if not file_path.exists():
            print(f"[SKIP] {file_path_str} (不存在)")
            continue
        
        if update_file_references(file_path, updates):
            updated_count += 1
            print(f"[UPDATE] {file_path_str}")
            for old_ref, new_ref in updates:
                print(f"  {old_ref} -> {new_ref}")
        else:
            print(f"[NO-CHANGE] {file_path_str}")
    
    # 4. 更新 sw.js 中的缓存路径（需要特殊处理）
    sw_js_path = ROOT / "web" / "sw.js"
    if sw_js_path.exists():
        try:
            with open(sw_js_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 更新缓存列表中的路径
            content = re.sub(r"'/index\.html'", "'/web/index.html'", content)
            content = re.sub(r'"/index\.html"', '"/web/index.html"', content)
            content = re.sub(r"'/admin\.html'", "'/web/admin.html'", content)
            content = re.sub(r'"/admin\.html"', '"/web/admin.html"', content)
            content = re.sub(r"url\.pathname === '/'", "url.pathname === '/' || url.pathname === '/web'", content)
            content = re.sub(r"url\.pathname === '/index\.html'", "url.pathname === '/web/index.html'", content)
            content = re.sub(r"caches\.match\('/index\.html'\)", "caches.match('/web/index.html')", content)
            
            with open(sw_js_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"[UPDATE] web/sw.js (缓存路径)")
        except Exception as e:
            print(f"[ERROR] 更新 sw.js 失败: {e}")
    
    # 5. 更新 index.html 中的 Service Worker 注册路径和相对路径
    index_html_path = ROOT / "web" / "index.html"
    if index_html_path.exists():
        try:
            with open(index_html_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 更新 Service Worker 注册路径
            content = re.sub(r"navigator\.serviceWorker\.register\('/sw\.js'\)", 
                           "navigator.serviceWorker.register('/web/sw.js')", content)
            content = re.sub(r'navigator\.serviceWorker\.register\("/sw\.js"\)', 
                           'navigator.serviceWorker.register("/web/sw.js")', content)
            
            # 注意：CSS和JS的相对路径不需要修改，因为它们相对于HTML文件位置
            
            with open(index_html_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"[UPDATE] web/index.html (Service Worker路径)")
        except Exception as e:
            print(f"[ERROR] 更新 index.html 失败: {e}")
    
    # 6. 显示结果
    print("\n" + "=" * 60)
    print("整理完成！")
    print(f"  移动文件: {moved_count} 个")
    print(f"  更新引用: {updated_count} 个文件")
    print("=" * 60)
    
    # 7. 显示根目录剩余文件
    print("\n根目录剩余文件:")
    remaining_files = [f.name for f in ROOT.iterdir() if f.is_file()]
    remaining_files.sort()
    for f in remaining_files:
        if f in KEEP_FILES:
            print(f"  [KEEP] {f}")
        else:
            print(f"  [?] {f} (未处理)")

if __name__ == "__main__":
    try:
        organize_files()
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
