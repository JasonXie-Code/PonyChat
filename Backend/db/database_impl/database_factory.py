

# 全局数据库实例
_db_instance: Optional[Database] = None


def get_database(db_path: str = DEFAULT_DB_PATH) -> Database:
    """
    获取数据库实例（单例模式）
    
    参数：
        db_path: 数据库文件路径
        
    返回：
        Database 实例
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = Database(db_path)
    return _db_instance


async def init_database(db_path: str = DEFAULT_DB_PATH):
    """
    初始化数据库（应用启动时调用）
    
    参数：
        db_path: 数据库文件路径
    """
    db = get_database(db_path)
    await db.init()
