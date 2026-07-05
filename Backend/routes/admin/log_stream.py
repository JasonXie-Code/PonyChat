"""
PonyChat 管理端后端控制台 WebSocket：实时日志流 + 内置命令（非 PTY Shell）。
WebSocket: /ws/admin/console?token=<admin_token>
下行: {type:'pty', data: str} 日志/命令输出（可含 ANSI）
上行: {type:'stdin', data: str} 与 {type:'ping'}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import urllib.error
import urllib.request
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

from ...config import BACKLOGS_DIR, logger
from .console_save_logs import save_backend_logs_to_file
from .terminal import _verify_token

_ADMIN_PORT = int(os.getenv("PONYCHAT_PORT", "5000"))
_SYSTEMD_UNIT = os.getenv("PONYCHAT_SYSTEMD_UNIT", "ponychat-backend.service")
_BACKEND_LOG = os.path.join(BACKLOGS_DIR, "backend.log")


def _help_lines() -> list[str]:
    return [
        "",
        "  ─── 控制台可用指令 ───",
        "  log           保存完整日志到 var/backlogs（含 job 轮询访问日志）",
        "  tm            测试模型大厅可见模型可用性",
        "  tma           测试全部可见模型（含绘画模型）",
        "  backups       列出数据库备份（1=最新，需服务已启动）",
        "  restore <序号>    恢复第 N 个备份，如 restore 1",
        "  restore <文件名>  恢复指定备份，如 restore backup_20260212_120000.db",
        "  restart       重启 PonyChat 后端服务（连接将短暂断开）",
        "  help 或 ? 或 h  再次显示本说明",
        "  ─────────────────────",
        "",
    ]


def _http_json(method: str, url: str, body: Optional[dict] = None, timeout: int = 120) -> tuple[bool, Any]:
    try:
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return True, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            return False, err_body
        except Exception:
            return False, str(e)
    except Exception as e:
        return False, str(e)


async def _send_text(ws: WebSocket, text: str) -> None:
    await ws.send_json({"type": "pty", "data": text})


async def _cmd_help(ws: WebSocket) -> None:
    for line in _help_lines():
        await _send_text(ws, line + "\r\n")


async def _cmd_log(ws: WebSocket) -> None:
    ok, msg = await asyncio.to_thread(save_backend_logs_to_file)
    color = "\x1b[32m" if ok else "\x1b[31m"
    await _send_text(ws, f"{color}{msg}\x1b[0m\r\n")


async def _cmd_tm(ws: WebSocket, mode: str) -> None:
    port = _ADMIN_PORT
    base = f"http://127.0.0.1:{port}"

    ok, models_data = await asyncio.to_thread(
        _http_json, "GET", f"{base}/api/models", None, 15
    )
    if not ok:
        await _send_text(ws, f"\x1b[31m获取模型列表失败: {models_data}\x1b[0m\r\n")
        return
    model_map = {
        m.get("id"): m.get("name", m.get("id", ""))
        for m in (models_data.get("models") or [])
    }

    ok2, data = await asyncio.to_thread(
        _http_json, "POST", f"{base}/api/models/test_all", {"mode": mode}, 300
    )
    if not ok2:
        await _send_text(ws, f"\x1b[31m模型测试失败: {data}\x1b[0m\r\n")
        return
    if isinstance(data, dict) and data.get("status") != "success":
        await _send_text(
            ws,
            f"\x1b[31m{data.get('message', '模型测试失败')}\x1b[0m\r\n",
        )
        return
    if not isinstance(data, dict):
        await _send_text(ws, f"\x1b[31m异常响应\x1b[0m\r\n")
        return

    results = data.get("results") or {}
    rows = []
    for model_id, result in results.items():
        rows.append(
            {
                "id": model_id,
                "name": model_map.get(model_id, model_id),
                "available": bool(result.get("available")),
                "message": str(result.get("message", "")),
            }
        )
    total = len(rows)
    avail = sum(1 for x in rows if x["available"])
    await _send_text(ws, f"\x1b[36m共 {total} 个模型，{avail} 个可用\x1b[0m\r\n")
    for item in rows:
        status = "✅ 可用" if item["available"] else "❌ 不可用"
        await _send_text(ws, f"  {status}  {item['name']} ({item['id']})\r\n")
        if not item["available"]:
            await _send_text(ws, f"      原因: {item['message']}\r\n")


async def _cmd_backups(ws: WebSocket) -> None:
    ok, out = await asyncio.to_thread(
        _http_json, "GET", f"http://127.0.0.1:{_ADMIN_PORT}/api/admin/backups", None, 30
    )
    if not ok:
        await _send_text(ws, f"\x1b[31m获取备份列表失败: {out}\x1b[0m\r\n")
        return
    if isinstance(out, dict) and not out.get("success"):
        await _send_text(ws, f"\x1b[31m{out.get('message', '失败')}\x1b[0m\r\n")
        return
    backups = out.get("backups") if isinstance(out, dict) else []
    if not backups:
        await _send_text(ws, "\x1b[33m当前没有备份文件\x1b[0m\r\n")
        return
    await _send_text(ws, "\x1b[36m备份列表（1=最新，restore <序号> 恢复）:\x1b[0m\r\n")
    for i, b in enumerate(backups, start=1):
        name = b.get("filename") or b.get("display_name") or str(b)
        await _send_text(ws, f"  [{b.get('index', i)}] {name}\r\n")


async def _cmd_restore(ws: WebSocket, arg: str) -> None:
    arg = arg.strip()
    body: dict[str, Any] = {}
    if arg.isdigit():
        body["backup_index"] = int(arg)
    else:
        body["backup_file"] = arg
    ok, out = await asyncio.to_thread(
        _http_json,
        "POST",
        f"http://127.0.0.1:{_ADMIN_PORT}/api/admin/restore",
        body,
        120,
    )
    if not ok:
        await _send_text(ws, f"\x1b[31m恢复请求失败: {out}\x1b[0m\r\n")
        return
    if isinstance(out, dict) and out.get("success"):
        await _send_text(
            ws,
            f"\x1b[32m{out.get('message', '恢复成功')} {out.get('restored_from', '')}\x1b[0m\r\n",
        )
    else:
        msg = out.get("message", str(out)) if isinstance(out, dict) else str(out)
        await _send_text(ws, f"\x1b[31m{msg}\x1b[0m\r\n")


async def _cmd_restart(ws: WebSocket) -> None:
    if sys.platform == "win32":
        await _send_text(
            ws,
            "\x1b[33mWindows 开发环境请手动重启后端进程；未执行 systemctl。\x1b[0m\r\n",
        )
        return
    if not shutil.which("systemctl"):
        await _send_text(ws, "\x1b[31m未找到 systemctl，无法重启。\x1b[0m\r\n")
        return
    await _send_text(ws, "\x1b[33m正在重启服务，连接将断开…\x1b[0m\r\n")

    async def _fire():
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl",
                "restart",
                _SYSTEMD_UNIT,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception as e:
            logger.warning("systemctl restart: %s", e)

    asyncio.create_task(_fire())


async def _replay_recent(ws: WebSocket, lines: int = 50) -> None:
    """重连或首次连接时回放最近若干行，减少空白感。"""
    unit = _SYSTEMD_UNIT
    if sys.platform != "win32" and shutil.which("journalctl"):
        try:
            proc = await asyncio.create_subprocess_exec(
                "journalctl",
                "-u",
                unit,
                "-n",
                str(lines),
                "--no-pager",
                "-o",
                "short-iso",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            if out:
                await _send_text(
                    ws,
                    f"\x1b[36m─── 最近 {lines} 行（journalctl）───\x1b[0m\r\n",
                )
                await _send_text(ws, out.decode("utf-8", errors="replace"))
            return
        except Exception as e:
            logger.debug("journalctl replay: %s", e)

    if os.path.isfile(_BACKEND_LOG):
        def _tail_file() -> str:
            with open(_BACKEND_LOG, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            return "".join(all_lines[-lines:])

        chunk = await asyncio.to_thread(_tail_file)
        if chunk:
            await _send_text(
                ws,
                f"\x1b[36m─── 最近 {lines} 行（{_BACKEND_LOG}）───\x1b[0m\r\n",
            )
            await _send_text(ws, chunk if chunk.endswith("\n") else chunk + "\n")


async def _run_log_follow(ws: WebSocket, stop: asyncio.Event) -> None:
    unit = _SYSTEMD_UNIT
    proc: Optional[asyncio.subprocess.Process] = None
    try:
        if sys.platform != "win32" and shutil.which("journalctl"):
            proc = await asyncio.create_subprocess_exec(
                "journalctl",
                "-u",
                unit,
                "-f",
                "--no-pager",
                "-o",
                "short-iso",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        elif sys.platform != "win32" and shutil.which("tail"):
            if not os.path.isfile(_BACKEND_LOG):
                open(_BACKEND_LOG, "a", encoding="utf-8").close()
            proc = await asyncio.create_subprocess_exec(
                "tail",
                "-F",
                "-n",
                "0",
                _BACKEND_LOG,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        else:
            await _tail_file_poll(ws, stop)
            return

        assert proc and proc.stdout
        while not stop.is_set():
            line = await proc.stdout.readline()
            if not line:
                break
            await _send_text(ws, line.decode("utf-8", errors="replace"))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("log follow: %s", e)
        await _send_text(ws, f"\x1b[31m[日志流异常] {e}\x1b[0m\r\n")
    finally:
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


async def _tail_file_poll(ws: WebSocket, stop: asyncio.Event) -> None:
    """Windows：轮询 backend.log 尾部。"""
    path = _BACKEND_LOG
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.isfile(path):
        open(path, "a", encoding="utf-8").close()
    pos = os.path.getsize(path)
    while not stop.is_set():
        await asyncio.sleep(0.2)
        try:
            sz = os.path.getsize(path)
            if sz < pos:
                pos = 0
            if sz > pos:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                if chunk:
                    await _send_text(ws, chunk)
        except Exception as e:
            logger.debug("tail poll: %s", e)


async def _handle_line(ws: WebSocket, line: str) -> None:
    s = line.strip()
    if not s:
        return
    low = s.lower()
    parts = s.split(maxsplit=1)
    head = parts[0].lower() if parts else ""

    if low in ("help", "h", "?"):
        await _cmd_help(ws)
    elif low == "log":
        await _cmd_log(ws)
    elif low == "tm":
        await _cmd_tm(ws, "chat")
    elif low == "tma":
        await _cmd_tm(ws, "all")
    elif low == "backups":
        await _cmd_backups(ws)
    elif head == "restart":
        await _cmd_restart(ws)
    elif head == "restore" and len(parts) > 1:
        await _cmd_restore(ws, parts[1])
    elif head == "restore":
        await _send_text(ws, "\x1b[33m用法: restore <序号|文件名>\x1b[0m\r\n")
    else:
        await _send_text(
            ws,
            "\x1b[33m未知命令，输入 help 查看可用指令\x1b[0m\r\n",
        )


async def handle_admin_console(websocket: WebSocket) -> None:
    if not _verify_token(websocket.query_params.get("token")):
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept()

    await _send_text(
        websocket,
        "\x1b[32m已连接 PonyChat 后端控制台（非 Shell）。输入 help 查看指令。\x1b[0m\r\n",
    )
    await _replay_recent(websocket, 50)

    stop_follow = asyncio.Event()
    follow_task = asyncio.create_task(_run_log_follow(websocket, stop_follow))

    line_buf = ""

    try:
        while True:
            try:
                raw = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            t = raw.get("type")
            if t == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if t != "stdin" or not isinstance(raw.get("data"), str):
                continue
            data = raw["data"]
            for ch in data:
                if ch in "\r\n":
                    cmd = line_buf.strip()
                    line_buf = ""
                    if cmd:
                        await _handle_line(websocket, cmd)
                else:
                    line_buf += ch
    except WebSocketDisconnect:
        pass
    finally:
        stop_follow.set()
        follow_task.cancel()
        try:
            await follow_task
        except asyncio.CancelledError:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
