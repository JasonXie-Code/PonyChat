import json
import hashlib
from pathlib import Path
from collections import defaultdict
import sys

# 强制设置输出编码为 UTF-8 以兼容 Windows 终端
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def get_file_hash(file_path):
    """提取对话内容中的角色和文字，忽略时间戳等元数据，计算内容的哈希值"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # 提取核心内容: 只看 role 和 content
        messages = data.get('messages', [])
        content_stream = []
        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            content_stream.append(f"{role}:{content}")
            
        # 如果没有消息内容，则退回到文件哈希或跳过
        if not content_stream:
            return None
            
        # 将结构化的内容序列化为字符串进行哈希
        normalized_content = "|".join(content_stream)
        return hashlib.md5(normalized_content.encode('utf-8')).hexdigest()
    except Exception as e:
        print(f"⚠️ 无法解析文件 {file_path.name}: {e}")
        return None


def cleanup_conversations(target_root, dry_run=True):
    print(f"{' [PREVIEW] ' if dry_run else ' [EXECUTING] '} 开始清理目录: {target_root}")
    
    # 统计信息
    total_files = 0
    deleted_count = 0
    saved_space = 0
    
    # 结构: { char_id: { content_hash: [file_paths] } }
    # 只在同一个角色（目录）下进行查重，防止跨角色内容误删
    conv_root = Path(target_root) / "conversations"
    
    if not conv_root.exists():
        print(f"[!] 目录不存在: {conv_root}")
        return

    for char_dir in conv_root.iterdir():
        if not char_dir.is_dir():
            continue
            
        print(f"\n[SCAN] 正在扫描角色目录: {char_dir.name}")
        content_groups = defaultdict(list)
        
        # 1. 扫描并分组
        # 支持新目录结构: conversations/charId/convId.json
        # 同时兼容子目录中的 .json 文件 (如 convId/conv_xxx.json)
        files = list(char_dir.rglob("*.json"))  # 递归查找所有 json 文件
        for file_path in files:
            total_files += 1
            try:
                f_hash = get_file_hash(file_path)
                # 跳过无法解析的文件（hash 为 None）
                if f_hash is None:
                    continue
                content_groups[f_hash].append(file_path)
            except Exception as e:
                print(f"⚠️ 无法读取文件 {file_path.name}: {e}")

        # 2. 识别并清理重复项
        for f_hash, paths in content_groups.items():
            if len(paths) > 1:
                # 按修改时间排序，保留最新的
                paths.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                keep_file = paths[0]
                duplicates = paths[1:]
                
                print(f"🔎 发现重复内容 (Hash: {f_hash[:8]}...):")
                print(f"   ✅ 保留最新: {keep_file.name} ({keep_file.stat().st_size} bytes)")
                
                for dup in duplicates:
                    size = dup.stat().st_size
                    deleted_count += 1
                    saved_space += size
                    print(f"   🗑️ {'[将删除]' if dry_run else '[已删除]'} {dup.name}")
                    if not dry_run:
                        try:
                            os.remove(dup)
                        except Exception as e:
                            print(f"      ❌ 删除失败: {e}")

    print("\n" + "="*50)
    print(f"📊 清理结果汇总 ({'预览模式' if dry_run else '完成'}):")
    print(f"   - 总扫描文件数: {total_files}")
    print(f"   - {'预计' if dry_run else '实际'}删除重复文件数: {deleted_count}")
    print(f"   - {'预计' if dry_run else '实际'}释放空间: {saved_space / 1024:.2f} KB")
    print("="*50)

if __name__ == "__main__":
    import os

    _MISC = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_MISC))
    from project_paths import resolve_project_root

    _ROOT = resolve_project_root(Path(__file__))
    # 默认清理仓库内 user_data/<用户名>；可通过环境变量覆盖：PONYCHAT_CLEANUP_USER_DIR
    _default = _ROOT / "user_data" / "Jason"
    TARGET_USER_PATH = os.environ.get("PONYCHAT_CLEANUP_USER_DIR", str(_default))

    # 第一次运行：预览模式 (dry_run=True)
    # 请确认输出无误后，将 dry_run 改为 False 执行真实删除
    cleanup_conversations(TARGET_USER_PATH, dry_run=False)
