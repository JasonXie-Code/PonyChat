"""
与启动脚本 AAA_launch_backend.save_logs 对齐：将当前 backend 日志合并导出到 var/backlogs。
供 Web 管理控制台「log」指令调用。
"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime

from ...config import BACKLOGS_DIR, logger

BACKEND_LOG_FILE = os.path.join(BACKLOGS_DIR, "backend.log")
ACCESS_FULL_LOG_FILE = os.path.join(BACKLOGS_DIR, "backend_access_full.log")


def save_backend_logs_to_file() -> tuple[bool, str]:
    """
    刷新 handler 后将 backend.log + backend_access_full.log 合并写入
    backend_YYYYMMDD_HHMMSS.log。
    返回 (成功, 消息或路径)
    """
    backlog_dir = BACKLOGS_DIR
    os.makedirs(backlog_dir, exist_ok=True)

    if not os.path.exists(BACKEND_LOG_FILE) and not os.path.exists(ACCESS_FULL_LOG_FILE):
        msg = "未找到可保存的日志文件（backend.log / backend_access_full.log）"
        logger.warning(msg)
        return False, msg

    try:
        seen_handlers = set()
        for logger_obj in [logging.getLogger()] + [
            lg
            for lg in logging.Logger.manager.loggerDict.values()
            if isinstance(lg, logging.Logger)
        ]:
            for handler in getattr(logger_obj, "handlers", []):
                try:
                    handler_id = id(handler)
                    if handler_id in seen_handlers:
                        continue
                    seen_handlers.add(handler_id)
                    handler.flush()
                except Exception:
                    pass

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_log = os.path.join(backlog_dir, f"backend_{timestamp}.log")

        with open(dest_log, "w", encoding="utf-8", errors="replace") as out_fp:
            out_fp.write(f"# PonyChat 完整日志导出\n# 时间: {timestamp}\n\n")
            if os.path.exists(BACKEND_LOG_FILE):
                out_fp.write(f"===== {BACKEND_LOG_FILE} =====\n")
                with open(BACKEND_LOG_FILE, "r", encoding="utf-8", errors="replace") as src_fp:
                    shutil.copyfileobj(src_fp, out_fp)
                out_fp.write("\n\n")
            if os.path.exists(ACCESS_FULL_LOG_FILE):
                out_fp.write(f"===== {ACCESS_FULL_LOG_FILE} =====\n")
                with open(ACCESS_FULL_LOG_FILE, "r", encoding="utf-8", errors="replace") as src_fp:
                    shutil.copyfileobj(src_fp, out_fp)
                out_fp.write("\n")

        ok_msg = f"完整日志已保存到: {dest_log}"
        logger.info(f"✅ {ok_msg}")
        return True, ok_msg
    except Exception as e:
        err = f"保存日志时出错: {e}"
        logger.error(f"❌ {err}")
        return False, err
