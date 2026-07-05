

def _start_https_reverse_proxy(
    listen_host: str,
    listen_port: int,
    target_host: str,
    target_port: int,
    cert_file: str,
    key_file: str,
):
    """启动轻量 HTTPS 反向代理：对外 HTTPS，回源本地 HTTP。"""

    class _ProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _is_websocket_upgrade(self) -> bool:
            connection = (self.headers.get("Connection", "") or "").lower()
            upgrade = (self.headers.get("Upgrade", "") or "").lower()
            return ("upgrade" in connection) and (upgrade == "websocket")

        def _build_upstream_headers(self, for_websocket: bool = False):
            upstream_headers = {}
            for header, value in self.headers.items():
                lower = header.lower()
                if lower == "host":
                    continue
                if lower in (
                    "keep-alive",
                    "proxy-connection",
                    "transfer-encoding",
                ):
                    continue
                if not for_websocket and lower in ("connection", "upgrade"):
                    continue
                upstream_headers[header] = value

            upstream_headers["Host"] = f"{target_host}:{target_port}"
            # 透传真实客户端来源，便于后端 access log 显示手机局域网 IP。
            client_ip = self.client_address[0] if self.client_address else ""
            prior_xff = self.headers.get("X-Forwarded-For", "")
            upstream_headers["X-Forwarded-For"] = (
                f"{prior_xff}, {client_ip}" if prior_xff else client_ip
            )
            upstream_headers["X-Real-IP"] = client_ip
            upstream_headers["X-Forwarded-Proto"] = "https"
            upstream_headers["X-Forwarded-Host"] = self.headers.get("Host", "")
            return upstream_headers

        def _forward_websocket(self, upstream_path: str):
            upstream_sock = socket.create_connection((target_host, target_port), timeout=10)
            try:
                upstream_headers = self._build_upstream_headers(for_websocket=True)
                upstream_headers["Connection"] = "Upgrade"
                upstream_headers["Upgrade"] = "websocket"

                req_lines = [f"{self.command} {upstream_path} HTTP/1.1"]
                for header, value in upstream_headers.items():
                    req_lines.append(f"{header}: {value}")
                req_raw = ("\r\n".join(req_lines) + "\r\n\r\n").encode("utf-8")
                upstream_sock.sendall(req_raw)

                upstream_resp_head = b""
                while b"\r\n\r\n" not in upstream_resp_head and len(upstream_resp_head) < 131072:
                    chunk = upstream_sock.recv(8192)
                    if not chunk:
                        break
                    upstream_resp_head += chunk

                if not upstream_resp_head:
                    raise RuntimeError("websocket upstream handshake empty response")

                self.connection.sendall(upstream_resp_head)

                first_line = upstream_resp_head.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
                if " 101 " not in first_line:
                    # 非升级响应直接返回给客户端（例如 4xx/5xx），不做隧道转发。
                    return

                self.connection.setblocking(False)
                upstream_sock.setblocking(False)
                sockets = [self.connection, upstream_sock]

                while True:
                    readable, _, _ = select.select(sockets, [], [], 30)
                    if not readable:
                        continue
                    for sock_obj in readable:
                        try:
                            data = sock_obj.recv(65536)
                        except (BlockingIOError, ssl.SSLWantReadError):
                            continue
                        if not data:
                            return
                        if sock_obj is self.connection:
                            try:
                                upstream_sock.sendall(data)
                            except (ssl.SSLWantWriteError, BlockingIOError):
                                # 下游写缓冲瞬态满，稍等重试一次
                                import time as _time; _time.sleep(0.01)
                                try:
                                    upstream_sock.sendall(data)
                                except Exception:
                                    return
                        else:
                            try:
                                self.connection.sendall(data)
                            except (ssl.SSLWantWriteError, BlockingIOError):
                                # 客户端写缓冲瞬态满（大帧/音频流时常见），稍等重试一次
                                import time as _time; _time.sleep(0.01)
                                try:
                                    self.connection.sendall(data)
                                except Exception:
                                    return
            finally:
                try:
                    upstream_sock.close()
                except Exception:
                    pass

        def _forward(self):
            parsed = urlsplit(self.path)
            upstream_path = parsed.path or "/"
            if parsed.query:
                upstream_path += f"?{parsed.query}"

            if self._is_websocket_upgrade():
                self._forward_websocket(upstream_path)
                return

            conn = http.client.HTTPConnection(target_host, target_port, timeout=300)
            try:
                body = None
                content_length = int(self.headers.get("Content-Length", "0") or "0")
                if content_length > 0:
                    body = self.rfile.read(content_length)

                upstream_headers = self._build_upstream_headers(for_websocket=False)

                conn.request(self.command, upstream_path, body=body, headers=upstream_headers)
                upstream_resp = conn.getresponse()

                self.send_response(upstream_resp.status, upstream_resp.reason)
                
                for header, value in upstream_resp.getheaders():
                    lower = header.lower()
                    if lower in (
                        "connection",
                        "keep-alive",
                        "proxy-connection",
                        "transfer-encoding",
                        "upgrade",
                    ):
                        continue
                    self.send_header(header, value)
                
                self.send_header("Connection", "close")
                self.end_headers()

                if self.command != "HEAD":
                    is_sse = "text/event-stream" in upstream_resp.getheader("Content-Type", "")
                    if is_sse:
                        # SSE 是行协议：每个 token 事件是一行 data:...，后跟一个空行。
                        # 用 readline() 逐行读取并立即 flush，确保每个 token 单独推送给客户端，
                        # 避免 http.client chunked 解码积攒多行后一次性返回导致批量到达。
                        while True:
                            line = upstream_resp.readline()
                            if not line:
                                break
                            self.wfile.write(line)
                            self.wfile.flush()
                    else:
                        while True:
                            chunk = upstream_resp.read(8192)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
            except Exception as proxy_err:
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                msg = f"upstream proxy error: {proxy_err}"
                encoded = msg.encode("utf-8", errors="replace")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            finally:
                conn.close()

        def do_GET(self):
            self._forward()

        def do_POST(self):
            self._forward()

        def do_PUT(self):
            self._forward()

        def do_PATCH(self):
            self._forward()

        def do_DELETE(self):
            self._forward()

        def do_OPTIONS(self):
            self._forward()

        def do_HEAD(self):
            self._forward()

        def log_message(self, fmt, *args):
            msg = fmt % args
            # 成功的 /api/chat/job 轮询不打印，只展示出错情况
            if "/api/chat/job/" in msg:
                m = re.search(r'"\s+(\d{3})\s', msg)
                if m and int(m.group(1)) < 400:
                    return
            logger.info(f"🔁 [LAN HTTPS Proxy] {self.client_address[0]} - {msg}")

    server = ThreadingHTTPServer((listen_host, listen_port), _ProxyHandler)

    # 静默 SSLWantReadError：客户端在 TLS 握手期间断开时会产生此噪声，不是真正的错误
    def _quiet_handle_error(request, client_address):
        import sys, ssl as _ssl
        exc = sys.exc_info()[1]
        if isinstance(exc, _ssl.SSLWantReadError):
            return
        ThreadingHTTPServer.handle_error(server, request, client_address)
    server.handle_error = _quiet_handle_error

    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls_context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    server.socket = tls_context.wrap_socket(server.socket, server_side=True)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def _shutdown_proxy():
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass

    atexit.register(_shutdown_proxy)
    return server, thread


def _is_windows_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _firewall_rule_exists(rule_name: str) -> bool:
    try:
        import subprocess as _sp
        result = _sp.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule_name}"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace"
        )
        text = f"{result.stdout or ''}\n{result.stderr or ''}"
        if "No rules match" in text or "没有与指定条件匹配的规则" in text:
            return False
        return result.returncode == 0
    except Exception:
        return False


def _firewall_profile_arg() -> str:
    """
    Windows 默认常把 Wi‑Fi 标为「公用网络」，仅 profile=private 的入站规则不会生效，
    手机与 PC 同网段也会连不上。开发环境默认用 any；可通过 PONYCHAT_FIREWALL_PROFILE
    覆盖为 private / public / domain / any（与 netsh advfirewall 一致）。
    """
    v = (os.getenv("PONYCHAT_FIREWALL_PROFILE") or "any").strip().lower()
    allowed = ("any", "private", "public", "domain")
    return v if v in allowed else "any"


def _apply_firewall_rule(rule_name: str, port: int):
    import subprocess as _sp
    profile = _firewall_profile_arg()
    _sp.run(
        ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={rule_name}"],
        capture_output=True, timeout=5
    )
    result = _sp.run(
        ["netsh", "advfirewall", "firewall", "add", "rule",
         f"name={rule_name}", "dir=in", "action=allow",
         "protocol=TCP", f"localport={port}",
         f"profile={profile}"],
        capture_output=True, text=True, timeout=5,
        encoding="utf-8", errors="replace"
    )
    return result.returncode == 0, (result.stderr or result.stdout or "").strip()


def _apply_firewall_rules_with_elevation(failed_rules):
    """
    failed_rules: [(rule_name, port), ...]
    失败后弹一次 UAC，提权批量补齐规则。
    """
    if not failed_rules:
        return True

    script_dir = os.path.join(os.getcwd(), "scripts")
    os.makedirs(script_dir, exist_ok=True)
    script_path = os.path.join(script_dir, "apply_firewall_rules_elevated.cmd")

    fw_profile = _firewall_profile_arg()
    lines = ["@echo off", "chcp 65001>nul"]
    for rule_name, port in failed_rules:
        safe_rule = rule_name.replace('"', '""')
        lines.append(f'netsh advfirewall firewall delete rule name="{safe_rule}" >nul 2>nul')
        lines.append(
            f'netsh advfirewall firewall add rule name="{safe_rule}" '
            f'dir=in action=allow protocol=TCP localport={port} profile={fw_profile}'
        )
    lines.append("exit /b %errorlevel%")

    with open(script_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\r\n".join(lines) + "\r\n")

    escaped_script_path = script_path.replace("'", "''")
    ps_command = (
        "Start-Process -FilePath 'cmd.exe' "
        f"-ArgumentList @('/c','\"{escaped_script_path}\"') "
        "-Verb RunAs -Wait"
    )
    try:
        import subprocess as _sp
        result = _sp.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace"
        )
        return result.returncode == 0
    except Exception as elevate_err:
        logger.warning(f"⚠️  自动提权放行失败: {elevate_err}")
        return False


# 运行服务
if __name__ == "__main__":
    import uvicorn
    import copy
    import os

    # 仅主进程执行：先抢占单实例锁，再清理残留启动器，避免误杀当前 py.exe 启动链
    if os.environ.get('RUN_MAIN') != 'true':
        if not _acquire_launcher_lock():
            sys.exit(1)
        _cleanup_stale_launcher_processes()
        if not _check_portable_runtime():
            sys.exit(1)

    # 0.0.0.0 可供局域网设备直连；127.0.0.1 仅本机。可通过环境变量 PONYCHAT_HOST 覆盖
    HOST = os.getenv("PONYCHAT_HOST", "0.0.0.0")
    PORT = int(os.getenv("PONYCHAT_PORT", "5000"))
    # 默认关闭本地 HTTPS，优先兼容“外层穿透 HTTPS + 内层本地 HTTP 回源”。
    # 如需局域网直连 HTTPS，可设置 PONYCHAT_ENABLE_HTTPS=1。
    HTTPS_ENABLED = os.getenv("PONYCHAT_ENABLE_HTTPS", "0").strip().lower() not in ("0", "false", "no", "off")
    LAN_HTTPS_PROXY_ENABLED = os.getenv("PONYCHAT_ENABLE_LAN_HTTPS_PROXY", "1").strip().lower() not in ("0", "false", "no", "off")
    LAN_HTTPS_PROXY_PORT = int(os.getenv("PONYCHAT_LAN_HTTPS_PORT", "5001"))
    SSL_CERTFILE = None
    SSL_KEYFILE = None
    if HTTPS_ENABLED or LAN_HTTPS_PROXY_ENABLED:
        SSL_CERTFILE, SSL_KEYFILE = _ensure_https_cert_files()
        if not SSL_CERTFILE or not SSL_KEYFILE:
            sys.exit(1)
    os.environ["PONYCHAT_SCHEME"] = "https" if HTTPS_ENABLED else "http"
    if LAN_HTTPS_PROXY_ENABLED:
        os.environ["PONYCHAT_LAN_SCHEME"] = "https"
        os.environ["PONYCHAT_LAN_PORT"] = str(LAN_HTTPS_PROXY_PORT)
    else:
        os.environ["PONYCHAT_LAN_SCHEME"] = os.environ["PONYCHAT_SCHEME"]
        os.environ["PONYCHAT_LAN_PORT"] = str(PORT)
    
    # 使用带颜色的输出
    logger.info("🚀 启动 AI 角色扮演对话服务...")
    print_console_help()

    # 仅主进程开启请求日志回显，确保当前终端可见 GET/POST 请求行
    _access_tail_stop_event.clear()
    if os.environ.get('RUN_MAIN') != 'true':
        start_access_log_tail(BACKEND_LOG_FILE)

    # 启动输入监听线程（传入端口供 backups/restore 请求本机 API）
    input_thread = threading.Thread(target=input_listener, args=(PORT,), daemon=True)
    input_thread.start()
    
    # 检查并清理端口
    if kill_process_on_port(PORT):
        logger.info(f"🔄 已清理端口 {PORT}，准备启动服务...")
    else:
        logger.info(f"✅ 端口 {PORT} 可用")

    if LAN_HTTPS_PROXY_ENABLED and LAN_HTTPS_PROXY_PORT != PORT:
        if kill_process_on_port(LAN_HTTPS_PROXY_PORT):
            logger.info(f"🔄 已清理内网 HTTPS 代理端口 {LAN_HTTPS_PROXY_PORT}")
        else:
            logger.info(f"✅ 内网 HTTPS 代理端口 {LAN_HTTPS_PROXY_PORT} 可用")
    
    # 🔥 [防火墙] 自动放行端口，确保局域网设备能直连（默认 profile=any，见 _firewall_profile_arg）
    if HOST == "0.0.0.0" and sys.platform == "win32":
        _fw_prof = _firewall_profile_arg()
        rule_specs = [(f"PonyChat Backend LAN (TCP {PORT})", PORT)]
        if LAN_HTTPS_PROXY_ENABLED and LAN_HTTPS_PROXY_PORT != PORT:
            # 名称与旧版「…Proxy」区分，便于在 profile=any 更新后自动新建入站规则（避免沿用仅 private 的旧规则）
            rule_specs.append((f"PonyChat LAN HTTPS Inbound (TCP {LAN_HTTPS_PROXY_PORT})", LAN_HTTPS_PROXY_PORT))

        failed_rules = []
        for rule_name, rule_port in rule_specs:
            if _firewall_rule_exists(rule_name):
                if rule_port == PORT:
                    logger.info(f"⏭️ 防火墙规则已存在，跳过端口 {rule_port}")
                else:
                    logger.info(f"⏭️ 防火墙规则已存在，跳过内网 HTTPS 代理端口 {rule_port}")
                continue
            try:
                ok, error_text = _apply_firewall_rule(rule_name, rule_port)
                if ok:
                    if rule_port == PORT:
                        logger.info(f"🔥 防火墙已放行端口 {rule_port} (profile={_fw_prof})")
                    else:
                        logger.info(f"🔥 防火墙已放行内网 HTTPS 代理端口 {rule_port} (profile={_fw_prof})")
                else:
                    failed_rules.append((rule_name, rule_port))
                    if rule_port == PORT:
                        logger.warning(f"⚠️  防火墙规则添加失败: {error_text}")
                    else:
                        logger.warning(f"⚠️  内网 HTTPS 代理防火墙规则添加失败: {error_text}")
            except Exception as fw_err:
                failed_rules.append((rule_name, rule_port))
                if rule_port == PORT:
                    logger.warning(f"⚠️  防火墙设置跳过: {fw_err}")
                else:
                    logger.warning(f"⚠️  内网 HTTPS 代理防火墙设置跳过: {fw_err}")

        auto_elevate = os.getenv("PONYCHAT_AUTO_ELEVATE_FIREWALL", "1").strip().lower() not in ("0", "false", "no", "off")
        if failed_rules and auto_elevate and not _is_windows_admin():
            logger.warning("⚠️  检测到防火墙放行失败，正在尝试自动提权（会弹 UAC 窗口）...")
            if _apply_firewall_rules_with_elevation(failed_rules):
                for rule_name, rule_port in failed_rules:
                    if _firewall_rule_exists(rule_name):
                        if rule_port == PORT:
                            logger.info(f"🔥 已通过提权放行端口 {rule_port} (profile={_fw_prof})")
                        else:
                            logger.info(f"🔥 已通过提权放行内网 HTTPS 代理端口 {rule_port} (profile={_fw_prof})")
                    else:
                        if rule_port == PORT:
                            logger.warning("⚠️  提权后仍未检测到后端端口防火墙规则，请手动放行")
                        else:
                            logger.warning("⚠️  提权后仍未检测到内网 HTTPS 代理端口防火墙规则，请手动放行")
            else:
                logger.warning("⚠️  自动提权未完成（可能取消了 UAC），请手动放行端口")

        if failed_rules:
            logger.warning("   如果局域网无法连接，请以管理员权限运行或手动放行端口")
    
    # 局域网模式时提示直连地址（排除 VPN/TUN 虚拟网卡，优先 WLAN）
    if HOST == "0.0.0.0":
        try:
            import socket
            lan_ip = None
            try:
                import ifaddr
                vpn_keywords = ("meta", "tap", "tun", "vpn", "ppp", "虚拟", "virtual")
                preferred = None
                for adapter in ifaddr.get_adapters():
                    name_lower = (adapter.nice_name or adapter.name or "").lower()
                    if any(kw in name_lower for kw in vpn_keywords):
                        continue
                    for ip_obj in adapter.ips:
                        if not ip_obj.is_IPv4:
                            continue
                        ip = ip_obj.ip
                        if not ip or ip == "127.0.0.1":
                            continue
                        if not (ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172.")):
                            continue
                        if any(k in name_lower for k in ("wifi", "wlan", "无线", "wi-fi")):
                            lan_ip = ip
                            break
                        if preferred is None:
                            preferred = ip
                    if lan_ip:
                        break
                lan_ip = lan_ip or preferred
            except Exception:
                pass
            if not lan_ip:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.settimeout(0.5)
                    s.connect(("8.8.8.8", 80))
                    ip = s.getsockname()[0]
                    s.close()
                    if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
                        lan_ip = ip
                except Exception:
                    pass
            if lan_ip:
                if LAN_HTTPS_PROXY_ENABLED:
                    logger.info(f"🌐 局域网直连: https://{lan_ip}:{LAN_HTTPS_PROXY_PORT}/ (同 WiFi 设备可优先使用)")
                else:
                    scheme = "https" if HTTPS_ENABLED else "http"
                    logger.info(f"🌐 局域网直连: {scheme}://{lan_ip}:{PORT}/ (同 WiFi 设备可优先使用)")
        except Exception:
            pass

    if LAN_HTTPS_PROXY_ENABLED:
        _start_https_reverse_proxy(
            listen_host=HOST,
            listen_port=LAN_HTTPS_PROXY_PORT,
            target_host="127.0.0.1",
            target_port=PORT,
            cert_file=SSL_CERTFILE,
            key_file=SSL_KEYFILE,
        )
        logger.info(f"🔐 内网 HTTPS 代理已启用: https://{HOST}:{LAN_HTTPS_PROXY_PORT} -> http://127.0.0.1:{PORT}")
    
    # 配置 uvicorn 日志（稳定链路 + 控制台彩色）
    uvicorn_log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    uvicorn_log_config["formatters"]["default"]["fmt"] = "%(asctime)s - %(levelprefix)s %(message)s"
    uvicorn_log_config["formatters"]["default"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
    uvicorn_log_config["formatters"]["default"]["use_colors"] = True
    uvicorn_log_config["formatters"]["access"]["fmt"] = (
        '%(asctime)s - %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    )
    uvicorn_log_config["formatters"]["access"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
    uvicorn_log_config["formatters"]["access"]["use_colors"] = True
    uvicorn_log_config["formatters"]["access_file"] = {
        "()": "uvicorn.logging.AccessFormatter",
        "fmt": '%(asctime)s - %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
        "datefmt": "%Y-%m-%d %H:%M:%S",
        "use_colors": False,
    }
    uvicorn_log_config.setdefault("filters", {})
    uvicorn_log_config["filters"]["suppress_job_polling_ok"] = {
        "()": UvicornAccessNoiseFilter
    }
    uvicorn_log_config["filters"]["suppress_runtime_noise"] = {
        "()": UvicornRuntimeNoiseFilter
    }
    uvicorn_log_config["handlers"]["access_file_full"] = {
        "class": "logging.FileHandler",
        "formatter": "access_file",
        "filename": ACCESS_FULL_LOG_FILE,
        "encoding": "utf-8",
        "mode": "w",
    }
    uvicorn_log_config["handlers"]["access"].setdefault("filters", [])
    if "suppress_job_polling_ok" not in uvicorn_log_config["handlers"]["access"]["filters"]:
        uvicorn_log_config["handlers"]["access"]["filters"].append("suppress_job_polling_ok")
    uvicorn_log_config["handlers"]["default"].setdefault("filters", [])
    if "suppress_runtime_noise" not in uvicorn_log_config["handlers"]["default"]["filters"]:
        uvicorn_log_config["handlers"]["default"]["filters"].append("suppress_runtime_noise")
    uvicorn_log_config["loggers"]["uvicorn.access"].setdefault("handlers", [])
    if "access_file_full" not in uvicorn_log_config["loggers"]["uvicorn.access"]["handlers"]:
        uvicorn_log_config["loggers"]["uvicorn.access"]["handlers"].append("access_file_full")

    uvicorn_config = {
        "app": app,
        "host": HOST,
        "port": PORT,
        "log_level": "info",
        "access_log": True,
        "reload": False,  # 关闭热重载，修改代码需手动重启服务
        "proxy_headers": True,
        "forwarded_allow_ips": os.getenv("PONYCHAT_FORWARDED_ALLOW_IPS", "127.0.0.1,::1"),
        # 使用统一后的 uvicorn 日志配置（与 backend/config.py 一致）
        "log_config": uvicorn_log_config
    }
    if HTTPS_ENABLED:
        uvicorn_config["ssl_certfile"] = SSL_CERTFILE
        uvicorn_config["ssl_keyfile"] = SSL_KEYFILE
        logger.info(f"🔒 HTTPS 已启用: cert={SSL_CERTFILE}")
    else:
        logger.warning("⚠️  HTTPS 已禁用（PONYCHAT_ENABLE_HTTPS=0）")

    # 启动服务
    try:
        uvicorn.run(**uvicorn_config)
    finally:
        # 解释器退出前先回收控制台回显线程，避免 Ctrl+C 触发 stdout 锁竞争崩溃
        stop_access_log_tail()
