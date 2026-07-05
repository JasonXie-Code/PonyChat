import psutil
import time
from fastapi import APIRouter
from ..config import logger

router = APIRouter(prefix="/api")

@router.get("/status")
async def get_system_load():
    """汇报服务器硬件负载（CPU, RAM, DISK）"""
    try:
        cpu = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        return {
            "cpu": cpu,
            "memory": memory,
            "disk": disk,
            "uptime": int(time.time()),
            "status": "healthy"
        }
    except Exception as e:
        logger.error(f"获取系统负载失败: {e}")
        return {"status": "error", "message": str(e)}
