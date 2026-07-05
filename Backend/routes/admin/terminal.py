"""
管理端 Web 终端：Python 日志广播 + PTY shell（Unix）；Windows 下仅日志与 ping。
WebSocket: /ws/admin/terminal?token=<admin_token>
消息: 下行 JSON {type:'log'|'pty', line?|data?}；上行 {type:'stdin', data: str}。
"""
from __future__ import annotations

import asyncio
import errno
import logging
import os
import queue
import select
import subprocess
import sys
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

_ADMIN_TOKEN_PLACEHOLDER = "admin_token_placeholder"


class _WebSocketLogHandler(logging.Handler):
    """线程安全：任意线程写日志，由 asyncio 侧从 Queue 取出后发到 WS。"""

    def __init__(self, q: queue.Queue):
        super().__init__()
        self._q = q
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            try:
                self._q.put_nowait({"type": "log", "line": msg})
            except queue.Full:
                pass
        except Exception:
            self.handleError(record)


def _verify_token(token: Optional[str]) -> bool:
    if not token:
        return False
    return token.strip() == _ADMIN_TOKEN_PLACEHOLDER


async def handle_admin_terminal(websocket: WebSocket) -> None:
    if not _verify_token(websocket.query_params.get("token")):
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept()

    log_queue: queue.Queue = queue.Queue(maxsize=500)
    log_handler = _WebSocketLogHandler(log_queue)
    log_handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(log_handler)

    pump_task = asyncio.create_task(_pump_thread_queue_to_ws(websocket, log_queue))

    try:
        if sys.platform == "win32":
            await _windows_interactive_loop(websocket)
        else:
            await _unix_pty_loop(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        root.removeHandler(log_handler)
        pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass
        try:
            await websocket.close()
        except Exception:
            pass


async def _pump_thread_queue_to_ws(websocket: WebSocket, q: queue.Queue) -> None:
    loop = asyncio.get_event_loop()
    while True:
        try:
            item = await loop.run_in_executor(None, lambda: q.get(timeout=0.5))
        except queue.Empty:
            await asyncio.sleep(0)
            continue
        except (WebSocketDisconnect, asyncio.CancelledError):
            break
        try:
            await websocket.send_json(item)
        except Exception:
            break


async def _windows_interactive_loop(websocket: WebSocket) -> None:
    while True:
        try:
            raw = await websocket.receive_json()
        except WebSocketDisconnect:
            break
        if raw.get("type") == "ping":
            await websocket.send_json({"type": "pong"})


async def _unix_pty_loop(websocket: WebSocket) -> None:
    import fcntl
    import pty

    master_fd: Optional[int] = None
    proc: Optional[subprocess.Popen] = None
    try:
        master_fd, slave_fd = pty.openpty()
        fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        shell = "/bin/bash"
        if os.path.isfile(shell):
            proc = subprocess.Popen(
                [shell, "-l"],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=os.setsid,
                cwd=os.environ.get("HOME") or "/",
            )
        else:
            proc = subprocess.Popen(
                ["/bin/sh", "-l"],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                preexec_fn=os.setsid,
                cwd=os.environ.get("HOME") or "/",
            )
        os.close(slave_fd)
        slave_fd = -1

        loop = asyncio.get_event_loop()

        async def read_pty():
            while proc and proc.poll() is None:
                try:
                    r, _, _ = await loop.run_in_executor(
                        None, lambda: select.select([master_fd], [], [], 0.15)
                    )
                    if master_fd in r:
                        try:
                            chunk = os.read(master_fd, 65536)
                        except OSError as e:
                            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                                await asyncio.sleep(0)
                                continue
                            break
                        if chunk:
                            await websocket.send_json(
                                {
                                    "type": "pty",
                                    "data": chunk.decode("utf-8", errors="replace"),
                                }
                            )
                    else:
                        await asyncio.sleep(0)
                except WebSocketDisconnect:
                    break
                except asyncio.CancelledError:
                    break

        read_task = asyncio.create_task(read_pty())

        try:
            while True:
                try:
                    raw = await websocket.receive_json()
                except WebSocketDisconnect:
                    break
                t = raw.get("type")
                if t == "stdin" and isinstance(raw.get("data"), str):
                    data = raw["data"].encode("utf-8")
                    try:
                        os.write(master_fd, data)
                    except OSError:
                        break
                elif t == "ping":
                    await websocket.send_json({"type": "pong"})
        finally:
            read_task.cancel()
            try:
                await read_task
            except asyncio.CancelledError:
                pass
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
    finally:
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
