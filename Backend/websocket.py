import asyncio
import time
from typing import Dict, Set, Optional
from contextlib import asynccontextmanager
from fastapi import WebSocket, WebSocketDisconnect
from .config import logger

class GalgameLockManager:
    def __init__(self):
        self.locks = {}
        self.global_lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, username: str, character_id: str):
        """
        获取或创建该用户专属的锁 (所有角色共享一个用户锁以保证文件完整性)
        使用上下文管理器模式,确保锁的自动释放
        """
        # [文件完整性修复] 使用用户级锁，因所有角色共享同一文件
        key = username
        
        # 获取或创建该用户专属的锁
        async with self.global_lock:
            if key not in self.locks:
                self.locks[key] = asyncio.Lock()
            lock = self.locks[key]
        
        # 进入临界区
        async with lock:
            try:
                yield
            finally:
                pass

class ConnectionManager:
    def __init__(self):
        # 存储所有活跃连接 {username: set(websocket)}
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # 用户当前前台打开的普通聊天。角色自动接话只能在这个会话仍处于前台时继续。
        self.active_chats: Dict[str, dict] = {}
        # 单设备：每个用户最多 1 个连接
        self.MAX_CONNECTIONS_PER_USER = 1
        self.MAX_TOTAL_CONNECTIONS = 1000  # 总连接数上限
        
    def _get_total_connections(self) -> int:
        """获取当前总连接数"""
        return sum(len(conns) for conns in self.active_connections.values())

    def get_connection_count(self, username: str) -> int:
        """获取某用户当前 WebSocket 连接数（用于单设备时禁用定时同步）"""
        return len(self.active_connections.get(username, set()))

    async def connect(self, websocket: WebSocket, username: str):
        await websocket.accept()
        await self.register_connection(websocket, username)

    async def register_connection(self, websocket: WebSocket, username: str) -> bool:
        """注册已接受连接的 WebSocket，返回 True 表示成功，False 表示被拒绝（连接已关闭）。
        若该用户已有旧连接，先踢掉旧连接再接受新连接（单设备强制登出）。"""
        total_connections = self._get_total_connections()
        if total_connections >= self.MAX_TOTAL_CONNECTIONS:
            logger.warning(f"⚠️ [连接限制] 总连接数已达上限 ({self.MAX_TOTAL_CONNECTIONS})，拒绝新连接")
            await websocket.close(code=1008, reason="Server connection limit reached")
            return False

        user_connections = self.active_connections.get(username, set())
        if len(user_connections) >= self.MAX_CONNECTIONS_PER_USER:
            # 踢掉旧连接，为新设备让路（异地登录场景兜底）
            logger.warning(f"⚠️ [单设备] 用户 {username} 已有连接，踢掉旧连接")
            await self.force_logout_user(username)

        if username not in self.active_connections:
            self.active_connections[username] = set()
        self.active_connections[username].add(websocket)
        self.clear_active_chat(username)
        logger.info(f"🔌 用户 {username} 已连接 WebSocket (用户连接数: {len(self.active_connections[username])}, 总连接数: {self._get_total_connections()})")
        return True

    async def force_logout_user(self, username: str):
        """向该用户所有在线 WS 连接推送 force_logout 并关闭，用于异地登录踢下线。"""
        targets = list(self.active_connections.get(username, set()))
        if not targets:
            return
        logger.info(f"🚫 [强制登出] 踢掉用户 {username} 的 {len(targets)} 个 WS 连接")
        for ws in targets:
            try:
                await ws.send_json({"type": "force_logout", "reason": "logged_in_elsewhere"})
                await ws.close(code=4001, reason="Logged in elsewhere")
            except Exception:
                pass
        self.active_connections.pop(username, None)

    async def disconnect(self, websocket: WebSocket, username: str, client_id: str = None):
        if username in self.active_connections:
            self.active_connections[username].discard(websocket)
            if not self.active_connections[username]:
                del self.active_connections[username]
                self.clear_active_chat(username)
        logger.info(f"🔌 用户 {username} 已断开 WebSocket")
        if client_id:
            try:
                await generation_locker.release_locks_by_client(client_id)
            except Exception as e:
                logger.error(f"自动释放锁失败: {e}")

    def set_active_chat(
        self,
        username: str,
        *,
        character_id: str,
        mode: str,
        conversation_id: str,
    ) -> None:
        username = str(username or "").strip()
        if not username:
            return
        character_id = str(character_id or "").strip()
        mode = str(mode or "normal").strip() or "normal"
        conversation_id = str(conversation_id or "").strip()
        if not character_id or not conversation_id:
            self.clear_active_chat(username)
            return
        self.active_chats[username] = {
            "character_id": character_id,
            "mode": mode,
            "conversation_id": conversation_id,
            "updated_at": time.time(),
        }

    def clear_active_chat(
        self,
        username: str,
        *,
        character_id: str | None = None,
        mode: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        username = str(username or "").strip()
        if not username:
            return
        current = self.active_chats.get(username)
        if current and character_id is not None:
            if str(current.get("character_id") or "") != str(character_id or "").strip():
                return
            if mode is not None and str(current.get("mode") or "") != (str(mode or "").strip() or "normal"):
                return
            if conversation_id is not None and str(current.get("conversation_id") or "") != str(conversation_id or "").strip():
                return
        self.active_chats.pop(username, None)

    def is_active_chat(
        self,
        username: str,
        *,
        character_id: str,
        mode: str,
        conversation_id: str,
    ) -> bool:
        username = str(username or "").strip()
        if not username or self.get_connection_count(username) <= 0:
            return False
        current = self.active_chats.get(username)
        if not current:
            return False
        return (
            str(current.get("character_id") or "") == str(character_id or "").strip()
            and (str(current.get("mode") or "").strip() or "normal") == (str(mode or "").strip() or "normal")
            and str(current.get("conversation_id") or "") == str(conversation_id or "").strip()
        )

    async def broadcast_to_user(self, username: str, message: dict):
        """向特定用户当前在线连接广播消息（并行发送）"""
        if username in self.active_connections:
            targets = list(self.active_connections[username])
            
            # 🔧 [优化] 并行发送到所有连接，不必逐个等待
            async def _send(connection):
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.warning(f"发送消息到 {username} 的连接失败: {str(e)}")
                    self.active_connections.get(username, set()).discard(connection)
            
            await asyncio.gather(*[_send(conn) for conn in targets], return_exceptions=True)

    async def broadcast_sync(self, username: str, reason: str, source: str = "server", **kwargs):
        """单设备模式：不再广播，保留接口兼容"""
        pass


class GenerationLockManager:
    """
    🔒 单账号生成互斥锁管理器
    确保同一用户同一角色在同一时间只有一个客户端请求可以触发 AI 生成
    """
    def __init__(self):
        # 存储生成锁 {username_charId: {client_id, timestamp, is_galgame}}
        self.locks: Dict[str, dict] = {}
        self.global_lock = asyncio.Lock()
        # 锁超时时间（秒）- 防止异常情况下锁永久占用
        self.lock_timeout = 180  # 3分钟

    def _make_key(self, username: str, character_id: str) -> str:
        return f"{username}_{character_id}"

    async def try_acquire(self, username: str, character_id: str, client_id: str, is_galgame: bool = False) -> tuple[bool, Optional[str]]:
        """
        尝试获取生成锁
        返回: (success, holder_client_id)
        - success=True: 成功获取锁
        - success=False: 锁被占用，holder_client_id 是当前持有者
        """
        key = self._make_key(username, character_id)
        now = time.time()
        
        async with self.global_lock:
            # 检查是否有现有锁
            if key in self.locks:
                lock_info = self.locks[key]
                if lock_info["client_id"] == client_id:
                    logger.info(f"🔄 [生成锁] 客户端 {client_id} 新生成取代旧生成 (续期)")
                    lock_info["timestamp"] = now
                    lock_info["is_galgame"] = is_galgame
                    lock_info["username"] = username
                    lock_info["character_id"] = character_id
                    return True, None

                # 检查锁是否超时
                if now - lock_info["timestamp"] > self.lock_timeout:
                    logger.warning(f"🔓 [生成锁] 锁 {key} 已超时，强制释放 (持有者: {lock_info['client_id']})")
                    del self.locks[key]
                else:
                    # 锁仍有效，返回失败
                    return False, lock_info["client_id"]
            
            # 获取锁
            self.locks[key] = {
                "client_id": client_id,
                "username": username,
                "character_id": character_id,
                "timestamp": now,
                "is_galgame": is_galgame
            }
            logger.info(f"🔒 [生成锁] 用户 {username} 角色 {character_id} 已锁定 (客户端: {client_id})")
            return True, None

    async def release(self, username: str, character_id: str, client_id: str) -> bool:
        """
        释放生成锁
        返回: True 表示成功释放，False 表示锁不存在或不属于该客户端
        """
        key = self._make_key(username, character_id)
        
        async with self.global_lock:
            if key not in self.locks:
                return False
            
            lock_info = self.locks[key]
            # 只有锁的持有者才能释放（或超时）
            if lock_info["client_id"] != client_id:
                logger.warning(f"⚠️ [生成锁] 客户端 {client_id} 尝试释放不属于自己的锁 (持有者: {lock_info['client_id']})")
                return False
            
            del self.locks[key]
            logger.info(f"🔓 [生成锁] 用户 {username} 角色 {character_id} 已解锁 (客户端: {client_id})")
            return True

    async def release_if_held_by(self, username: str, character_id: str, allowed_client_ids: Set[str]) -> Optional[str]:
        """
        仅当当前锁属于指定 client_id 集合时释放，并返回实际持有者。
        用于用户新消息打断主动生成，不开放为通用抢锁路径。
        """
        key = self._make_key(username, character_id)
        allowed = {str(client_id) for client_id in allowed_client_ids if client_id}

        async with self.global_lock:
            lock_info = self.locks.get(key)
            if not lock_info:
                return None
            holder = str(lock_info.get("client_id") or "")
            if holder not in allowed:
                return None
            del self.locks[key]
            logger.info(f"🔓 [生成锁] 主动生成被用户新消息打断: {key} (客户端: {holder})")
            return holder

    async def is_locked(self, username: str, character_id: str) -> tuple[bool, Optional[str]]:
        """
        检查是否被锁定
        返回: (is_locked, holder_client_id)
        """
        key = self._make_key(username, character_id)
        now = time.time()
        
        async with self.global_lock:
            if key in self.locks:
                lock_info = self.locks[key]
                # 检查是否超时
                if now - lock_info["timestamp"] > self.lock_timeout:
                    del self.locks[key]
                    return False, None
                return True, lock_info["client_id"]
            return False, None

    async def force_release(self, username: str, character_id: str) -> bool:
        """强制释放锁（用于管理员操作或异常恢复）"""
        key = self._make_key(username, character_id)
        
        async with self.global_lock:
            if key in self.locks:
                del self.locks[key]
                logger.info(f"🔓 [生成锁] 强制释放 {key}")
                return True
            return False

    async def release_locks_by_client(self, client_id: str) -> list:
        """
        [关键修复] 当 WebSocket 断开时，强制释放该客户端持有的所有生成锁
        返回被释放的锁信息列表
        """
        if not client_id:
            return []

        released_locks = []
        async with self.global_lock:
            # 找出该 client_id 持有的所有锁 keys
            keys_to_release = []
            for key, info in self.locks.items():
                if info.get("client_id") == client_id:
                    keys_to_release.append(key)
                    released_locks.append(info.copy())
            
            # 删除
            for key in keys_to_release:
                del self.locks[key]
                logger.info(f"🔓 [连接断开] 自动释放残留锁: {key} (客户端: {client_id})")
        
        return released_locks


# 全局单例
manager = ConnectionManager()
galgame_locker = GalgameLockManager()
generation_locker = GenerationLockManager()

__all__ = ['manager', 'galgame_locker', 'generation_locker', 'ConnectionManager', 'GalgameLockManager', 'GenerationLockManager']
