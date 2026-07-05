"""
管理后台系统管理相关接口（纯数据库模式）
包含：密码修改、数据库备份、数据库还原等功能
"""
import json
import os
import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel
from ...config import logger, DB_PATH, BACKUP_DIR
from ...db.backup_scheduler import (
    create_backup_if_changed,
    format_file_size,
    prune_backups,
    get_sorted_backup_files,
    check_db_integrity,
)

router = APIRouter()

BACKUP_DIR = Path(BACKUP_DIR)
BACKUP_KEEP = 5

# ==================== 管理员配置管理 ====================

ADMIN_CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "admin_config.json"

def load_admin_config() -> dict:
    """加载管理员配置"""
    if not ADMIN_CONFIG_FILE.exists():
        default_config = {
            "username": "admin",
            "password": "admin123",
            "created_at": datetime.now().isoformat()
        }
        save_admin_config(default_config)
        return default_config
    
    try:
        with open(ADMIN_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载管理员配置失败: {e}")
        return {}

def save_admin_config(config: dict):
    """保存管理员配置（原子写入：先写临时文件再替换，避免写入中断导致文件损坏）"""
    tmp_path = ADMIN_CONFIG_FILE.parent / (ADMIN_CONFIG_FILE.name + ".tmp")
    try:
        ADMIN_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, ADMIN_CONFIG_FILE)
    except Exception as e:
        logger.error(f"保存管理员配置失败: {e}")
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        raise

# ==================== API 端点 ====================

class AdminChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

@router.post("/change-password")
async def change_admin_password(request: AdminChangePasswordRequest):
    """更改管理员密码"""
    try:
        admin_config = load_admin_config()
        
        if request.current_password != admin_config.get("password"):
            return {"success": False, "message": "当前密码错误"}
        
        admin_config["password"] = request.new_password
        admin_config["password_changed_at"] = datetime.now().isoformat()
        save_admin_config(admin_config)
        
        logger.info("管理员密码已更改")
        return {"success": True, "message": "密码修改成功"}
    except Exception as e:
        logger.error(f"更改管理员密码失败: {str(e)}")
        return {"success": False, "message": str(e)}

@router.post("/backup")
async def backup_all_data():
    """备份数据库（使用 SQLite 备份 API），并自动保留最多 5 个备份"""
    try:
        backup_dir = BACKUP_DIR
        backup_filename, err, skipped = create_backup_if_changed(DB_PATH, backup_dir)
        deleted = prune_backups(backup_dir, keep=BACKUP_KEEP)

        if err:
            logger.warning(f"备份失败: {err}")
            return {"success": False, "message": err}

        if skipped:
            logger.info(f"数据库内容无变化，未创建新备份；已清理 {deleted} 个旧备份")
            return {
                "success": True,
                "skipped": True,
                "message": "数据库内容无变化，未创建新备份",
                "timestamp": datetime.now().isoformat(),
            }

        backup_path = backup_dir / backup_filename
        size_str = format_file_size(backup_path.stat().st_size)
        logger.info(f"数据库备份成功: {backup_filename} ({size_str})；已清理 {deleted} 个旧备份")

        return {
            "success": True,
            "skipped": False,
            "backup_file": backup_filename,
            "size": size_str,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"备份失败: {str(e)}")
        return {"success": False, "message": str(e)}

@router.get("/backups")
async def list_backups():
    """获取所有备份文件列表（按时间倒序，index 1 为最新，可用于恢复时指定 backup_index）"""
    try:
        backup_dir = BACKUP_DIR
        if not backup_dir.exists():
            return {"success": True, "backups": []}
        
        # 仅 .db，按修改时间降序，与恢复接口的 backup_index 一致
        backup_files = get_sorted_backup_files(backup_dir)
        backups = []
        for idx, backup_file in enumerate(backup_files):
            file_stat = backup_file.stat()
            file_size = file_stat.st_size
            size_str = format_file_size(file_size)
            
            filename = backup_file.name
            timestamp_str = filename.replace("backup_", "").replace(".db", "").replace(".zip", "")
            try:
                try:
                    timestamp_obj = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S_%f")
                except ValueError:
                    timestamp_obj = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                display_name = timestamp_obj.strftime("%Y年%m月%d日 %H:%M:%S")
                timestamp_iso = timestamp_obj.isoformat()
            except:
                display_name = filename
                timestamp_iso = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
            
            backups.append({
                "index": idx + 1,
                "filename": filename,
                "display_name": display_name,
                "size": size_str,
                "size_bytes": file_size,
                "timestamp": timestamp_iso
            })
        
        return {"success": True, "backups": backups}
    except Exception as e:
        logger.error(f"获取备份列表失败: {str(e)}")
        return {"success": False, "message": str(e), "backups": []}

class RestoreRequest(BaseModel):
    """backup_file 与 backup_index 二选一。backup_index 为列表中的序号，1 为最新备份。"""
    backup_file: Optional[str] = None
    backup_index: Optional[int] = None


def _resolve_restore_file(backup_file: Optional[str], backup_index: Optional[int]) -> str | None:
    """根据 backup_file 或 backup_index 解析出要恢复的文件名，不存在返回 None。"""
    backup_dir = BACKUP_DIR
    if backup_file:
        if (backup_dir / backup_file).exists():
            return backup_file
        return None
    if backup_index is not None:
        files = get_sorted_backup_files(backup_dir)
        if 1 <= backup_index <= len(files):
            return files[backup_index - 1].name
        # 兼容旧控制台或脚本仍传 0 的情况；管理后台不会再显示 0。
        if backup_index == 0 and files:
            return files[0].name
        return None
    return None


@router.post("/restore")
async def restore_data(request: RestoreRequest):
    """还原数据库。可传 backup_file（文件名）或 backup_index（列表序号，1 为最新）。"""
    try:
        if not request.backup_file and request.backup_index is None:
            return {"success": False, "message": "请指定 backup_file 或 backup_index"}
        
        restore_filename = _resolve_restore_file(request.backup_file, request.backup_index)
        if not restore_filename:
            return {"success": False, "message": "备份文件不存在或索引无效"}
        
        backup_dir = BACKUP_DIR
        backup_path = backup_dir / restore_filename
        
        if not backup_path.exists():
            return {"success": False, "message": "备份文件不存在"}
        
        if not restore_filename.endswith('.db'):
            return {"success": False, "message": "不支持的备份文件格式，请使用 .db 备份"}
        
        # 还原前检查备份文件的完整性，防止用损坏的备份覆盖主库
        is_ok, integrity_msg = check_db_integrity(str(backup_path))
        if not is_ok:
            logger.warning(f"备份文件完整性检查失败，已拒绝还原: {restore_filename} -> {integrity_msg}")
            return {
                "success": False,
                "message": f"该备份文件已损坏（{integrity_msg}），无法用于还原。请选择其他备份。"
            }

        # 先创建紧急备份（仅当主库完好时才创建，避免备份损坏的库）
        emergency_backup = backup_dir / f"emergency_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        main_ok, _ = check_db_integrity(DB_PATH)
        if main_ok:
            source = sqlite3.connect(DB_PATH)
            dest = sqlite3.connect(str(emergency_backup))
            source.backup(dest)
            dest.close()
            source.close()
        else:
            logger.warning("主数据库已损坏，跳过紧急备份，直接执行还原")
        
        try:
            backup_source = sqlite3.connect(str(backup_path))
            restore_dest = sqlite3.connect(DB_PATH)
            backup_source.backup(restore_dest)
            restore_dest.close()
            backup_source.close()
            
            logger.info(f"数据库还原成功: {restore_filename}")
            return {
                "success": True,
                "message": "数据库还原成功",
                "restored_from": restore_filename
            }
        except Exception as e:
            logger.error(f"还原失败: {e}")
            # 仅当紧急备份存在时才尝试回滚
            if emergency_backup.exists():
                logger.info("正在从紧急备份回滚...")
                emergency_source = sqlite3.connect(str(emergency_backup))
                emergency_dest = sqlite3.connect(DB_PATH)
                emergency_source.backup(emergency_dest)
                emergency_dest.close()
                emergency_source.close()
            return {"success": False, "message": f"还原失败: {str(e)}"}
            
    except Exception as e:
        logger.error(f"还原数据失败: {str(e)}")
        return {"success": False, "message": str(e)}
