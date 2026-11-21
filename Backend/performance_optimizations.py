"""
性能优化工具模块
用于提升系统并发处理能力
"""

import os
import multiprocessing
from typing import Optional

def get_optimal_workers() -> int:
    """
    根据CPU核心数计算最优的worker数量
    推荐：CPU核心数 × 2 + 1
    """
    cpu_count = multiprocessing.cpu_count()
    # 对于I/O密集型应用（如Web服务），可以设置更多workers
    # 对于CPU密集型应用，workers数量应该接近CPU核心数
    # 这里假设是I/O密集型（文件读写、网络请求）
    optimal = min(cpu_count * 2 + 1, 8)  # 最多8个worker，避免过多
    return max(1, optimal)  # 至少1个


def get_uvicorn_config() -> dict:
    """
    获取优化的 uvicorn 配置
    """
    workers = get_optimal_workers()
    
    return {
        "host": "0.0.0.0",
        "port": 5000,
        "workers": workers,  # 🔧 [性能优化] 多进程模式
        "log_level": "info",
        "access_log": False,  # 🔧 [性能优化] 关闭访问日志，减少I/O
        "loop": "asyncio" if os.name == "nt" else "uvloop",
        "limit_concurrency": 1000,  # 🔧 [性能优化] 限制并发连接数
        "timeout_keep_alive": 30,  # 🔧 [性能优化] 保持连接超时
    }


# WebSocket 连接限制配置
class ConnectionLimits:
    """WebSocket连接数限制配置"""
    MAX_CONNECTIONS_PER_USER = 5  # 每个用户最多5个设备同时连接
    MAX_TOTAL_CONNECTIONS = 1000  # 总连接数上限
    CONNECTION_TIMEOUT = 300  # 连接超时时间（秒）


# 文件I/O优化配置
class FileIOConfig:
    """文件I/O优化配置"""
    USE_ORJSON = True  # 使用更快的orjson库（需要安装：pip install orjson）
    BATCH_WRITE_SIZE = 10  # 批量写入大小
    CACHE_ENABLED = True  # 启用内存缓存
    CACHE_TTL = 300  # 缓存过期时间（秒）


def check_dependencies() -> dict:
    """
    检查性能优化所需的依赖
    返回缺失的依赖列表
    """
    missing = []
    optional = {}
    
    # 检查 orjson（可选，但推荐）
    try:
        import orjson
        optional['orjson'] = True
    except ImportError:
        optional['orjson'] = False
        missing.append('orjson (可选，但推荐安装: pip install orjson)')
    
    # 检查 uvloop（可选，但推荐）
    try:
        import uvloop
        optional['uvloop'] = True
    except ImportError:
        optional['uvloop'] = False
        missing.append('uvloop (可选，但推荐安装: pip install uvloop)')
    
    # 检查 redis（可选，用于缓存）
    try:
        import redis
        optional['redis'] = True
    except ImportError:
        optional['redis'] = False
        missing.append('redis (可选，用于缓存: pip install redis)')
    
    return {
        'missing': missing,
        'optional': optional
    }


def print_optimization_status():
    """打印优化状态和建议"""
    deps = check_dependencies()
    workers = get_optimal_workers()
    
    print("\n" + "="*60)
    print("🚀 性能优化状态检查")
    print("="*60)
    print(f"✅ CPU核心数: {multiprocessing.cpu_count()}")
    print(f"✅ 推荐Worker数量: {workers}")
    print(f"✅ 连接限制: {ConnectionLimits.MAX_TOTAL_CONNECTIONS} 总连接")
    print(f"✅ 每用户限制: {ConnectionLimits.MAX_CONNECTIONS_PER_USER} 设备")
    
    if deps['optional'].get('orjson'):
        print("✅ orjson: 已安装（JSON处理速度提升2-3倍）")
    else:
        print("⚠️  orjson: 未安装（建议安装以提升性能）")
    
    if deps['optional'].get('uvloop'):
        print("✅ uvloop: 已安装（事件循环速度提升）")
    else:
        print("⚠️  uvloop: 未安装（建议安装以提升性能）")
    
    if deps['optional'].get('redis'):
        print("✅ redis: 已安装（可用于缓存）")
    else:
        print("ℹ️  redis: 未安装（可选，用于大规模部署）")
    
    if deps['missing']:
        print("\n📦 建议安装的依赖:")
        for dep in deps['missing']:
            print(f"   - {dep}")
    
    print("\n" + "="*60)
    print("💡 优化建议:")
    print("   1. 启用多进程模式（workers参数）")
    print("   2. 安装 orjson 提升JSON处理速度")
    print("   3. 安装 uvloop 提升事件循环性能")
    print("   4. 根据实际并发量调整连接限制")
    print("="*60 + "\n")


if __name__ == "__main__":
    print_optimization_status()
