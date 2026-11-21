"""
服务启动入口
"""


if __name__ == "__main__":
    import uvicorn
    import os
    from .config import app
    ssl_certfile = os.getenv("PONYCHAT_SSL_CERTFILE")
    ssl_keyfile = os.getenv("PONYCHAT_SSL_KEYFILE")
    https_flag = os.getenv("PONYCHAT_ENABLE_HTTPS", "0").strip().lower() not in ("0", "false", "no", "off")
    https_enabled = https_flag and bool(ssl_certfile and ssl_keyfile)
    
    # 🔧 [性能优化] 检查并应用优化配置
    try:
        from .performance_optimizations import (
            get_uvicorn_config, 
            print_optimization_status,
            ConnectionLimits
        )
        print_optimization_status()
        uvicorn_config = get_uvicorn_config()
        
        # 允许通过环境变量覆盖配置
        workers = int(os.getenv("UVICORN_WORKERS", uvicorn_config["workers"]))
        port = int(os.getenv("PORT", uvicorn_config["port"]))
        
        print("=" * 70)
        print("🚀 PonyChat 后端服务")
        print("=" * 70)
        scheme = "https" if https_enabled else "http"
        print(f"📡 前端页面: {scheme}://localhost:{port}/")
        print(f"📚 API 文档: {scheme}://localhost:{port}/docs")
        print(f"💚 健康检查: {scheme}://localhost:{port}/api/health")
        print("=" * 70)
        print(f"⚙️  工作进程数: {workers} (可通过 UVICORN_WORKERS 环境变量调整)")
        print(f"⚙️  连接限制: {ConnectionLimits.MAX_TOTAL_CONNECTIONS} 总连接")
        print("=" * 70)
        print("💡 提示: 模型与密钥在 conf/model_config.json / .env 中配置（云端 API）")
        print("=" * 70)
        
        # 多进程 workers>1 时，Uvicorn 要求传入可导入的应用字符串，否则会退出。
        # 以 `python -m Backend` 从仓库根（含 Backend 包）启动时，使用 Backend.config:app
        _app_arg = "Backend.config:app" if workers > 1 else app
        _run_kwargs = {
            "host": uvicorn_config["host"],
            "port": port,
            "workers": workers,
            "log_level": uvicorn_config["log_level"],
            "access_log": uvicorn_config.get("access_log", True),
            "limit_concurrency": uvicorn_config.get("limit_concurrency", 1000),
            "timeout_keep_alive": uvicorn_config.get("timeout_keep_alive", 30),
            "ssl_certfile": ssl_certfile,
            "ssl_keyfile": ssl_keyfile,
        }
        if uvicorn_config.get("loop"):
            _run_kwargs["loop"] = uvicorn_config["loop"]
        uvicorn.run(_app_arg, **_run_kwargs)
    except ImportError:
        # 如果优化模块不存在，使用默认配置
        print("=" * 70)
        print("🚀 PonyChat 后端服务")
        print("=" * 70)
        scheme = "https" if https_enabled else "http"
        print(f"📡 前端页面: {scheme}://localhost:5000/")
        print(f"📚 API 文档: {scheme}://localhost:5000/docs")
        print(f"💚 健康检查: {scheme}://localhost:5000/api/health")
        print("=" * 70)
        print("💡 提示: 模型与密钥在 conf/model_config.json / .env 中配置（云端 API）")
        print("=" * 70)
        print("⚠️  性能优化模块未找到，使用默认单进程模式")
        print("   建议: 查看 performance_optimizations.py 了解优化选项")
        print("=" * 70)
        
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=5000,
            log_level="info",
            ssl_certfile=ssl_certfile,
            ssl_keyfile=ssl_keyfile,
        )
