

def _aliyun_sig(params: dict, secret: str, method: str = "GET") -> str:
    """Aliyun RPC 接口标准 HMAC-SHA1 签名。"""
    sorted_qs = "&".join(
        f"{_aliyun_url_encode(k)}={_aliyun_url_encode(v)}"
        for k, v in sorted(params.items())
    )
    string_to_sign = f"{method}&{_aliyun_url_encode('/')}&{_aliyun_url_encode(sorted_qs)}"
    key = (secret + "&").encode("utf-8")
    digest = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


async def _get_aliyun_nls_token() -> str:
    """获取阿里云 NLS Token，本地缓存 22 小时。"""
    global _aliyun_token_cache, _aliyun_token_expire
    now = time.time()
    if _aliyun_token_cache and now < _aliyun_token_expire - 300:
        return _aliyun_token_cache

    async with _aliyun_token_lock:
        if _aliyun_token_cache and time.time() < _aliyun_token_expire - 300:
            return _aliyun_token_cache

        params: dict = {
            "AccessKeyId":     ALIYUN_ACCESS_KEY_ID,
            "Action":          "CreateToken",
            "Format":          "JSON",
            "RegionId":        "cn-shanghai",
            "SignatureMethod":  "HMAC-SHA1",
            "SignatureNonce":   str(uuid.uuid4()),   # 官方要求 A-B-C-D-E 格式，不能用 .hex
            "SignatureVersion": "1.0",
            "Timestamp":       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "Version":         "2019-02-28",   # 中国区正确版本号
        }
        params["Signature"] = _aliyun_sig(params, ALIYUN_ACCESS_KEY_SECRET, "GET")

        try:
            # 不使用全局 httpx_client（lifespan 赋值，模块导入时为 None），
            # 改用一次性 AsyncClient 避免 import 时机问题。
            async with httpx.AsyncClient(timeout=20) as _client:
                resp = await _client.get(
                    "https://nls-meta.cn-shanghai.aliyuncs.com/",
                    params=params,
                )
            logger.info(f"[AliyunNLS] Token 接口响应 HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"Token API 响应非 JSON 对象: {data}")

            # 兼容不同 key 大小写（阿里云偶尔返回小写 key）
            token_info = data.get("Token") or data.get("token")
            if not isinstance(token_info, dict):
                raise RuntimeError(f"Token API 响应缺少 Token 字段，完整响应: {data}")

            token  = token_info.get("Id")  or token_info.get("id")  or ""
            expire = int(token_info.get("ExpireTime") or token_info.get("expireTime") or 0)
            if not token:
                raise RuntimeError(f"Token 为空，响应: {data}")
            _aliyun_token_cache  = token
            _aliyun_token_expire = float(expire)
            logger.info(f"[AliyunNLS] Token 已刷新，有效至 {time.strftime('%H:%M:%S', time.localtime(expire))}")
            return token
        except Exception as e:
            logger.error(f"[AliyunNLS] Token 获取失败: {type(e).__name__}: {e!r}", exc_info=True)
            raise


# ── 阿里云 NLS 实时语音识别 WebSocket 代理 ─────────────────────────────────────

@router.websocket("/ws/speech/aliyun")
async def speech_stream_aliyun(websocket: WebSocket):
    """
    阿里云 NLS 实时语音识别代理 WebSocket。
    客户端协议与 /ws/speech 完全相同 (pcm16le_seq_v1)，本端点转发到阿里云 NLS。
    """
    await websocket.accept()
    logger.info("[AliyunASR/WS] 新连接")

    if not ALIYUN_ACCESS_KEY_ID or not ALIYUN_NLS_APP_KEY:
        await websocket.send_json({"event": "error", "code": "not_configured", "message": "阿里云 NLS 未配置"})
        return

    started = False
    stop_requested = False
    task_id = uuid.uuid4().hex
    accumulated_text = ""
    last_partial = ""
    aliyun_ws = None

    try:
        import websockets as _ws_lib
    except ImportError:
        await websocket.send_json({"event": "error", "code": "server_error", "message": "websockets 库不可用"})
        return

    async def _aliyun_reader(aliyun_conn, client_conn):
        """后台任务：持续读取阿里云 NLS 响应并转发给 Android 客户端。"""
        nonlocal accumulated_text, last_partial
        try:
            async for raw in aliyun_conn:
                if not isinstance(raw, str):
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                name = (msg.get("header") or {}).get("name", "")
                payload = msg.get("payload") or {}

                if name == "TranscriptionResultChanged":
                    # 中间结果（随时更新），只推 partial，客户端不触发发送
                    text = payload.get("result", "").strip()
                    if text and text != last_partial:
                        last_partial = text
                        await client_conn.send_json({"event": "partial", "text": text})

                elif name == "SentenceEnd":
                    # 一句话已确认完成 → 推 final 事件，客户端立刻截图+发给模型
                    text = payload.get("result", "").strip()
                    if text:
                        accumulated_text = text
                        last_partial = ""
                        logger.info(f"[AliyunASR] 分句结果: {text!r}")
                        await client_conn.send_json({"event": "final", "text": text})

                elif name == "TranscriptionCompleted":
                    # 整个识别会话结束，发 end 通知客户端停止录音光环
                    await client_conn.send_json({
                        "event": "end",
                        "reason": "user_stop" if stop_requested else "completed",
                        "text": accumulated_text,
                    })
                    break

                elif name in ("TaskFailed", "SpeechTranscriberClosed"):
                    status = (msg.get("header") or {}).get("status", 0)
                    status_msg = (msg.get("header") or {}).get("status_message", "")
                    await client_conn.send_json({"event": "error", "code": f"aliyun_{status}", "message": status_msg})
                    break
        except Exception as e:
            logger.warning(f"[AliyunASR] reader 异常: {type(e).__name__}: {e!r}")
            try:
                await client_conn.send_json({"event": "end", "reason": "disconnect", "text": accumulated_text})
            except Exception:
                pass

    reader_task = None

    try:
        while True:
            msg = await websocket.receive()

            if msg.get("type") == "websocket.disconnect":
                break

            text_data = msg.get("text")
            if text_data is not None:
                try:
                    payload = json.loads(text_data)
                except Exception:
                    continue
                event = (payload.get("event") or "").lower()

                if event == "ping":
                    await websocket.send_json({"event": "pong"})
                    continue

                if event == "start" and not started:
                    try:
                        token = await _get_aliyun_nls_token()
                    except Exception as te:
                        await websocket.send_json({"event": "error", "code": "token_failed", "message": str(te)})
                        return

                    aliyun_url = f"wss://nls-gateway-cn-shenzhen.aliyuncs.com/ws/v1?token={token}"
                    try:
                        aliyun_ws = await _ws_lib.connect(aliyun_url, ping_interval=20, open_timeout=8)
                    except Exception as ce:
                        await websocket.send_json({"event": "error", "code": "aliyun_connect_failed", "message": str(ce)})
                        return

                    start_directive = json.dumps({
                        "header": {
                            "message_id": uuid.uuid4().hex,
                            "task_id":    task_id,
                            "namespace":  "SpeechTranscriber",
                            "name":       "StartTranscription",
                            "appkey":     ALIYUN_NLS_APP_KEY,
                        },
                        "payload": {
                            "format":                       "pcm",
                            "sample_rate":                  16000,
                            "enable_intermediate_result":   True,
                            "enable_punctuation_prediction": True,
                            "enable_inverse_text_normalization": True,
                            "max_sentence_silence":         500,  # 分句停顿阈值：500ms 在陪玩短句场景响应更快（原800ms）
                        },
                    })
                    await aliyun_ws.send(start_directive)

                    try:
                        first_resp = await asyncio.wait_for(aliyun_ws.recv(), timeout=8.0)
                        first_msg  = json.loads(first_resp)
                    except Exception as e:
                        await websocket.send_json({"event": "error", "code": "aliyun_start_timeout", "message": str(e)})
                        await aliyun_ws.close()
                        return

                    if (first_msg.get("header") or {}).get("name") != "TranscriptionStarted":
                        await websocket.send_json({"event": "error", "code": "aliyun_start_failed", "message": str(first_msg)})
                        await aliyun_ws.close()
                        return

                    started = True
                    accumulated_text = ""
                    await websocket.send_json({
                        "event":           "started",
                        "lang":            "zh",
                        "protocol":        "pcm16le_seq_v1",
                        "max_duration_sec": 120,
                    })
                    reader_task = asyncio.create_task(_aliyun_reader(aliyun_ws, websocket))
                    logger.info(f"[AliyunASR/WS] 识别已启动 task_id={task_id[:8]}")
                    continue

                if event == "stop" and started:
                    stop_requested = True
                    stop_directive = json.dumps({
                        "header": {
                            "message_id": uuid.uuid4().hex,
                            "task_id":    task_id,
                            "namespace":  "SpeechTranscriber",
                            "name":       "StopTranscription",
                            "appkey":     ALIYUN_NLS_APP_KEY,
                        }
                    })
                    try:
                        await aliyun_ws.send(stop_directive)
                    except Exception:
                        pass
                    # 等待 reader_task 发完 end 事件后自然退出，最多 5s
                    if reader_task:
                        try:
                            await asyncio.wait_for(asyncio.shield(reader_task), timeout=5.0)
                        except (asyncio.TimeoutError, Exception):
                            pass
                    break
                continue

            # 二进制音频帧（格式：4字节小端 seq + PCM16LE）
            chunk = msg.get("bytes")
            if chunk and started and aliyun_ws and len(chunk) >= 6:
                pcm = chunk[4:]  # 去掉 seq 前缀，阿里云只要裸 PCM
                try:
                    await aliyun_ws.send(pcm)
                except Exception as se:
                    logger.warning(f"[AliyunASR] 音频发送失败: {se}")
                    break

    except WebSocketDisconnect:
        logger.info("[AliyunASR/WS] 客户端断开")
    except Exception as e:
        logger.error(f"[AliyunASR/WS] 未捕获异常: {e}", exc_info=True)
        try:
            await websocket.send_json({"event": "error", "code": "server_error", "message": str(e)})
        except Exception:
            pass
    finally:
        if reader_task and not reader_task.done():
            reader_task.cancel()
        if aliyun_ws:
            try:
                await aliyun_ws.close()
            except Exception:
                pass
        if not started or stop_requested:
            return
        # 兜底：如果异常退出还没发 end，补一条
        try:
            await websocket.send_json({"event": "end", "reason": "disconnect", "text": accumulated_text})
        except Exception:
            pass


# ── WebSocket /ws/speech/dashscope（DashScope 实时语音识别） ─────────────────────

@router.websocket("/ws/speech/dashscope")
async def speech_stream_dashscope(websocket: WebSocket):
    """
    DashScope Qwen-ASR-Realtime 实时语音识别代理。

    客户端协议与 /ws/speech/aliyun 完全相同（pcm16le_seq_v1）：
      客户端 → 后端  JSON {"event":"start"/"stop"/"ping"}
      客户端 → 后端  二进制  [4字节小端 seq][PCM16LE 裸帧]
      后端   → 客户端 JSON {"event":"started"/"partial"/"final"/"end"/"error"}

    内部将 PCM 音频以 base64 转发至 DashScope Realtime WebSocket，
    并将 Qwen-ASR-Realtime 的转写事件映射回客户端协议。
    """
    await websocket.accept()
    logger.info("[DashscopeASR/WS] 新连接")

    if not DASHSCOPE_ASR_API_KEY:
        await websocket.send_json({
            "event": "error", "code": "not_configured",
            "message": "DashScope API Key 未配置（PONYCHAT_DASHSCOPE_API_KEY）",
        })
        return

    try:
        import websockets as _ws_lib
    except ImportError:
        await websocket.send_json({"event": "error", "code": "server_error", "message": "websockets 库不可用"})
        return

    dashscope_url = f"wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={DASHSCOPE_ASR_MODEL}"

    # ── 共享状态（主循环 + reader_task 共同访问） ────────────────────────────
    started          = False   # True：session.updated 已收到，客户端已收到 started
    stop_requested   = False   # True：客户端已发 stop，等待最后一次 response.done
    accumulated_text = ""      # 最近一次 final 文本（用于 end 事件兜底）
    last_partial     = ""      # 去重用：避免向客户端重复推送相同 partial 文本
    transcript_buf   = ""      # 当前句的实时拼接缓冲（input_audio_transcription.delta）
    response_in_progress = False  # True：DashScope 正在生成当前句的 response

    qwen_ws     = None
    reader_task = None

    async def _qwen_reader(qwen_conn):
        """持续读取 DashScope 事件，映射为客户端协议。"""
        nonlocal started, accumulated_text, last_partial, transcript_buf, response_in_progress

        try:
            async for raw in qwen_conn:
                if not isinstance(raw, str):
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                msg_type = msg.get("type", "")

                # ── 会话握手 ─────────────────────────────────────────────────
                if msg_type == "session.created":
                    # 配置 ASR 专属参数：纯文本输出 + 服务端 VAD + 输入音频实时转写
                    await qwen_conn.send(json.dumps({
                        "type": "session.update",
                        "session": {
                            "modalities": ["text"],
                            "input_audio_format": "pcm",
                            "turn_detection": {
                                "type": "server_vad",
                                "threshold": 0.0,
                                "silence_duration_ms": 400,
                            },
                            # 开启输入音频实时转写，以获取说话中的 partial 结果
                            "input_audio_transcription": {
                                "model": DASHSCOPE_ASR_MODEL,
                                "language": "zh",
                            },
                        },
                    }))

                elif msg_type == "session.updated":
                    # 会话配置完成，通知客户端可以开始发音频
                    started = True
                    await websocket.send_json({
                        "event":            "started",
                        "lang":             "zh",
                        "protocol":         "pcm16le_seq_v1",
                        "max_duration_sec": 120,
                    })
                    logger.info(f"[DashscopeASR] 会话就绪 model={DASHSCOPE_ASR_MODEL}")

                # ── VAD 事件 ──────────────────────────────────────────────────
                elif msg_type == "input_audio_buffer.speech_started":
                    transcript_buf   = ""
                    last_partial     = ""
                    accumulated_text = ""   # 新语音段开始，重置去重缓存，允许用户重复同一句话
                    response_in_progress = False
                    # VAD 检测到用户开口：立即通知客户端停止 TTS（Barge-in 打断）
                    # 无需等第一个 transcription.delta 到来（那需要 200-500ms）
                    try:
                        await websocket.send_json({"event": "speech_started"})
                    except Exception:
                        break

                elif msg_type == "input_audio_buffer.speech_stopped":
                    response_in_progress = True

                # ── 实时转写（说话中的中间结果） ─────────────────────────────
                elif msg_type == "conversation.item.input_audio_transcription.delta":
                    delta = msg.get("delta", "")
                    if delta:
                        transcript_buf += delta
                        if transcript_buf and transcript_buf != last_partial:
                            last_partial = transcript_buf
                            try:
                                await websocket.send_json({"event": "partial", "text": transcript_buf})
                            except Exception:
                                break

                elif msg_type == "conversation.item.input_audio_transcription.completed":
                    # 输入音频转写完整结果（在 response 产生前已可用）
                    text = (msg.get("transcript") or transcript_buf).strip()
                    transcript_buf = ""
                    # 去重：DashScope 偶尔对同一句话重复推送此事件，需与 accumulated_text 比对
                    if text and text != accumulated_text:
                        accumulated_text = text
                        last_partial     = ""
                        logger.info(f"[DashscopeASR] input_audio_transcription 完成: {text!r:.80}")
                        try:
                            await websocket.send_json({"event": "final", "text": text})
                        except Exception:
                            break

                # ── 模型响应文本（ASR 结果，与 input_audio_transcription.completed 可能重叠） ──
                elif msg_type == "response.text.delta":
                    # 若 input_audio_transcription 已经发过 partial，此处更新合并
                    delta = msg.get("delta", "")
                    if delta:
                        combined = (last_partial + delta).strip() if not transcript_buf else delta
                        # 只在没有更精细的 input_audio_transcription 流时才推 partial
                        # （通过判断 transcript_buf 是否为空来区分）
                        if not transcript_buf and combined and combined != last_partial:
                            last_partial = combined
                            try:
                                await websocket.send_json({"event": "partial", "text": combined})
                            except Exception:
                                break

                elif msg_type == "response.text.done":
                    text = (msg.get("text") or "").strip()
                    if text and text != accumulated_text:
                        # 若 input_audio_transcription.completed 已发过 final，去重
                        accumulated_text = text
                        last_partial     = ""
                        transcript_buf   = ""
                        logger.info(f"[DashscopeASR] response.text.done: {text!r:.80}")
                        try:
                            await websocket.send_json({"event": "final", "text": text})
                        except Exception:
                            break

                elif msg_type == "response.done":
                    response_in_progress = False
                    if stop_requested:
                        logger.info("[DashscopeASR] stop 后 response.done，发送 end")
                        try:
                            await websocket.send_json({
                                "event":  "end",
                                "reason": "user_stop",
                                "text":   accumulated_text,
                            })
                        except Exception:
                            pass
                        break

                elif msg_type == "error":
                    err      = msg.get("error") or {}
                    err_code = err.get("code", "qwen_error")
                    err_msg  = err.get("message", "未知错误")
                    # "Error committing input audio buffer" 是用户断开/停说时的正常边界情况，降级为 DEBUG
                    if "committing input audio buffer" in err_msg or "no invalid audio stream" in err_msg:
                        logger.debug(f"[DashscopeASR] ASR buffer 提交忽略（正常断开）: {err_msg}")
                    else:
                        logger.warning(f"[DashscopeASR] Qwen 错误 {err_code}: {err_msg}")
                    try:
                        await websocket.send_json({"event": "error", "code": err_code, "message": err_msg})
                    except Exception:
                        pass

        except Exception as re:
            logger.warning(f"[DashscopeASR] reader 异常: {type(re).__name__}: {re!r}")
        finally:
            # 与 Aliyun 分支一致：仅在已向客户端发过 started 后，reader 退出才补 end；
            # 若 session.updated 从未到达，发 error，避免客户端误将「未就绪」当成正常 end 而疯狂重连。
            try:
                if started:
                    await websocket.send_json({"event": "end", "reason": "disconnect", "text": accumulated_text})
                else:
                    await websocket.send_json({
                        "event": "error",
                        "code": "dashscope_session_aborted",
                        "message": "DashScope 会话在就绪前结束，请检查 API Key / 模型名或网络",
                    })
            except Exception:
                pass

    try:
        while True:
            msg = await websocket.receive()

            if msg.get("type") == "websocket.disconnect":
                break

            text_data = msg.get("text")
            if text_data is not None:
                try:
                    payload = json.loads(text_data)
                except Exception:
                    continue
                event = (payload.get("event") or "").lower()

                if event == "ping":
                    await websocket.send_json({"event": "pong"})
                    continue

                if event == "start" and not started:
                    try:
                        qwen_ws = await _ws_lib.connect(
                            dashscope_url,
                            additional_headers={"Authorization": f"Bearer {DASHSCOPE_ASR_API_KEY}"},
                            ping_interval=20,
                            open_timeout=15,
                        )
                    except Exception as ce:
                        logger.error(f"[DashscopeASR] 连接失败: {ce}")
                        await websocket.send_json({
                            "event": "error", "code": "dashscope_connect_failed",
                            "message": str(ce),
                        })
                        return
                    # 启动后台 reader，session.updated 收到后才会给客户端发 started
                    reader_task = asyncio.create_task(_qwen_reader(qwen_ws))
                    logger.info(f"[DashscopeASR] 连接成功，等待 session.updated model={DASHSCOPE_ASR_MODEL}")
                    continue

                if event == "stop" and started:
                    stop_requested = True
                    # 提交缓冲区剩余音频（用户说话中途停止时），触发最后一次转写
                    if qwen_ws:
                        try:
                            await qwen_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                        except Exception:
                            pass
                        try:
                            # 若已有 response 在进行中，不重复创建
                            if not response_in_progress:
                                await qwen_ws.send(json.dumps({"type": "response.create"}))
                        except Exception:
                            pass
                    # 等待 reader_task 发出 end 事件后退出，最多 5s
                    if reader_task:
                        try:
                            await asyncio.wait_for(asyncio.shield(reader_task), timeout=5.0)
                        except (asyncio.TimeoutError, Exception):
                            pass
                    break
                continue

            # ── 二进制音频帧（4字节小端 seq + PCM16LE 裸帧） ─────────────────
            chunk = msg.get("bytes")
            if chunk and started and qwen_ws and len(chunk) >= 6:
                pcm       = chunk[4:]          # 去掉 seq 前缀
                audio_b64 = base64.b64encode(pcm).decode()
                try:
                    await qwen_ws.send(json.dumps({
                        "type":  "input_audio_buffer.append",
                        "audio": audio_b64,
                    }))
                except Exception as se:
                    logger.warning(f"[DashscopeASR] 音频发送失败: {se}")
                    break

    except WebSocketDisconnect:
        logger.info("[DashscopeASR/WS] 客户端断开")
    except Exception as e:
        logger.error(f"[DashscopeASR/WS] 未捕获异常: {e}", exc_info=True)
        try:
            await websocket.send_json({"event": "error", "code": "server_error", "message": str(e)})
        except Exception:
            pass
    finally:
        if reader_task and not reader_task.done():
            reader_task.cancel()
        if qwen_ws:
            try:
                await qwen_ws.close()
            except Exception:
                pass
        # 与上方 Aliyun ASR 的 finally 对齐：仅当已成功 started 且非用户 stop 收尾时，补发 disconnect end。
        if not started or stop_requested:
            return
        try:
            await websocket.send_json({"event": "end", "reason": "disconnect", "text": accumulated_text})
        except Exception:
            pass


# ── WebSocket /ws/tts/aliyun（阿里云 TTS） ───────────────────────────────────────

@router.websocket("/ws/tts/aliyun")
async def tts_stream_aliyun(websocket: WebSocket):
    """
    阿里云 NLS 语音合成 WebSocket 代理（持久连接版）。

    客户端与后端保持一条长连接，依次发送多个 speak 请求，避免每句重建 TCP/TLS 开销。

    协议（客户端 → 服务端）：
      {"event": "speak", "text": "...", "id": "unique_id"}  — 请求合成一句话
      {"event": "close"}                                     — 主动关闭连接
    协议（服务端 → 客户端）：
      {"event": "ready"}                                     — 连接就绪，可发 speak
      <二进制 PCM 帧（16kHz 16bit mono）>                    — 音频数据
      {"event": "done",  "id": "..."}                        — 当前句合成完毕
      {"event": "error", "id": "...", "message": "..."}      — 合成失败
    """
    await websocket.accept()
    if not is_voice_feature_enabled():
        await websocket.send_json({"event": "error", "code": "voice_paused", "message": VOICE_DISABLED_MESSAGE})
        await websocket.close(code=1000)
        return

    try:
        import websockets as _ws_lib
    except ImportError:
        await websocket.send_json({"event": "error", "message": "websockets 库不可用"})
        return

    aliyun_ws = None
    voice = ALIYUN_NLS_TTS_VOICE.strip()

    async def _ensure_aliyun() -> object:
        """确保阿里云 WS 连接存活，必要时重建。"""
        nonlocal aliyun_ws
        if aliyun_ws is not None:
            try:
                if not aliyun_ws.closed:
                    return aliyun_ws
            except Exception:
                pass
            aliyun_ws = None
        token = await _get_aliyun_nls_token()
        aliyun_url = f"wss://nls-gateway-cn-shenzhen.aliyuncs.com/ws/v1?token={token}"
        aliyun_ws = await _ws_lib.connect(aliyun_url, ping_interval=20, open_timeout=8)
        return aliyun_ws

    try:
        # 预连阿里云，减少首句延迟
        try:
            await _ensure_aliyun()
        except Exception as pre_err:
            logger.warning(f"[AliyunTTS] 预连失败，后续按需重试: {pre_err}")

        # 通知客户端连接已就绪
        await websocket.send_json({"event": "ready"})

        # ── 持久循环：依次处理每句 speak 请求 ──────────────────────────────────
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive(), timeout=120.0)
            except asyncio.TimeoutError:
                logger.info("[AliyunTTS] 持久连接 120s 无活动，主动关闭")
                break

            if msg.get("type") == "websocket.disconnect":
                break

            raw_text = msg.get("text") or ""
            if not raw_text:
                continue
            try:
                req = json.loads(raw_text)
            except Exception:
                continue

            ev = req.get("event", "")
            if ev == "close":
                logger.info("[AliyunTTS] 收到 close 事件，关闭持久连接")
                break
            if ev != "speak":
                continue

            speak_text = (req.get("text") or "").strip()
            speak_id   = req.get("id", "")

            if not speak_text:
                await websocket.send_json({"event": "done", "id": speak_id})
                continue

            # 确保阿里云连接存活（首次 / 断线后重建）
            try:
                conn = await _ensure_aliyun()
            except Exception as ce:
                logger.warning(f"[AliyunTTS] 阿里云连接失败: {ce}")
                await websocket.send_json({"event": "error", "id": speak_id,
                                           "message": f"aliyun_connect_failed: {ce}"})
                continue

            # 发送 StartSynthesis
            task_id = uuid.uuid4().hex
            tts_payload: dict = {
                "text":        speak_text,
                "format":      "pcm",
                "sample_rate": 16000,
                "volume":      50,
                "speech_rate": 0,
                "pitch_rate":  0,
            }
            if voice:
                tts_payload["voice"] = voice
            start_directive = json.dumps({
                "header": {
                    "message_id": uuid.uuid4().hex,
                    "task_id":    task_id,
                    "namespace":  "SpeechSynthesizer",
                    "name":       "StartSynthesis",
                    "appkey":     ALIYUN_NLS_APP_KEY,
                },
                "payload": tts_payload,
            })
            try:
                await conn.send(start_directive)
            except Exception as se:
                logger.warning(f"[AliyunTTS] StartSynthesis 发送失败: {se}")
                aliyun_ws = None  # 强制下次重建
                await websocket.send_json({"event": "error", "id": speak_id, "message": str(se)})
                continue

            t_start = time.perf_counter()
            t_first: float | None = None
            logger.info(f"[AliyunTTS] 合成开始 text={speak_text!r:.80} voice={voice}")

            # 接收本句 PCM 帧，直到 SynthesisCompleted（break）或失败
            synthesis_done = False
            try:
                async for raw in conn:
                    if isinstance(raw, bytes):
                        if t_first is None:
                            t_first = time.perf_counter()
                        await websocket.send_bytes(raw)
                    else:
                        try:
                            ev_msg = json.loads(raw)
                        except Exception:
                            continue
                        name = (ev_msg.get("header") or {}).get("name", "")
                        if name == "SynthesisStarted":
                            pass
                        elif name == "SynthesisCompleted":
                            t_total = time.perf_counter() - t_start
                            t_ff    = (t_first - t_start) if t_first else t_total
                            logger.info(
                                f"[AliyunTTS] 合成完成 text={speak_text!r:.80} "
                                f"| 首帧={t_ff:.2f}s 总计={t_total:.2f}s"
                            )
                            await websocket.send_json({"event": "done", "id": speak_id})
                            synthesis_done = True
                            break
                        elif name == "TaskFailed":
                            status_msg = (ev_msg.get("header") or {}).get("status_message", "unknown")
                            logger.warning(f"[AliyunTTS] 合成失败: {status_msg}")
                            await websocket.send_json({"event": "error", "id": speak_id,
                                                       "message": status_msg})
                            # TaskFailed 后连接可能不可用，标记重建
                            aliyun_ws = None
                            synthesis_done = True
                            break
            except Exception as recv_err:
                logger.warning(f"[AliyunTTS] 接收阿里云响应异常: {recv_err}")
                aliyun_ws = None
                await websocket.send_json({"event": "error", "id": speak_id,
                                           "message": str(recv_err)})

            if not synthesis_done:
                # 未正常结束（连接意外断开），补发 error
                aliyun_ws = None
                try:
                    await websocket.send_json({"event": "error", "id": speak_id,
                                               "message": "synthesis_incomplete"})
                except Exception:
                    break

    except WebSocketDisconnect:
        logger.info("[AliyunTTS] 客户端断开（持久连接）")
    except Exception as e:
        logger.error(f"[AliyunTTS] 未捕获异常: {type(e).__name__}: {e!r}", exc_info=True)
        try:
            await websocket.send_json({"event": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        if aliyun_ws:
            try:
                await aliyun_ws.close()
            except Exception:
                pass
        # 显式 close frame（code=1000），避免客户端 OkHttp 收到 EOF 触发 onFailure
        try:
            await websocket.close(code=1000)
        except Exception:
            pass


# ── WebSocket /ws/tts/dashscope（DashScope TTS） ────────────────────────────────

@router.websocket("/ws/tts/dashscope")
async def tts_stream_dashscope(websocket: WebSocket):
    """
    DashScope Qwen TTS Realtime 语音合成 WebSocket 代理（持久连接版）。

    与 /ws/tts/aliyun 对客户端协议完全兼容：
      客户端 → 服务端：{"event":"speak","text":"...","id":"..."}  — 合成一句
      客户端 → 服务端：{"event":"close"}                          — 主动关闭
      服务端 → 客户端：{"event":"ready"}                          — 就绪
      服务端 → 客户端：<二进制 PCM 帧（16kHz 16bit mono）>        — 音频数据
      服务端 → 客户端：{"event":"done","id":"..."}                 — 当前句完毕
      服务端 → 客户端：{"event":"error","id":"...","message":"..."} — 失败

    后端与 DashScope 保持一条持久 Realtime WebSocket，使用 commit 模式：
    每次收到 speak 请求，发送 input_text_buffer.append + input_text_buffer.commit，
    等待 response.audio.delta 帧转发给客户端，response.done 后发 done 事件。
    """
    await websocket.accept()
    if not is_voice_feature_enabled():
        await websocket.send_json({"event": "error", "code": "voice_paused", "message": VOICE_DISABLED_MESSAGE})
        await websocket.close(code=1000)
        return

    if not DASHSCOPE_TTS_API_KEY:
        await websocket.send_json({
            "event": "error", "message": "DashScope API Key 未配置（PONYCHAT_DASHSCOPE_API_KEY）"
        })
        return

    try:
        import websockets as _ws_lib
    except ImportError:
        await websocket.send_json({"event": "error", "message": "websockets 库不可用"})
        return

    dashscope_tts_url = f"wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={DASHSCOPE_TTS_MODEL}"

    qwen_ws = None
    session_ready = False   # session.updated 收到后置 True

    # 每句合成的共享状态（主循环写，reader 任务读）
    current_speak_id = ""
    audio_done_event = asyncio.Event()   # response.done 到达后置位

    async def _reader_task(qwen_conn):
        """持续读取 DashScope 事件，转发音频帧，设置 done 事件。"""
        nonlocal session_ready, current_speak_id
        try:
            async for raw in qwen_conn:
                if isinstance(raw, bytes):
                    # DashScope 也可能直接发二进制音频（当前协议用 base64，保留兜底）
                    if not audio_done_event.is_set():
                        try:
                            await websocket.send_bytes(raw)
                        except Exception:
                            break
                    continue

                if not isinstance(raw, str):
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "session.created":
                    # 配置 TTS 参数：commit 模式，Cherry 音色，16kHz PCM
                    await qwen_conn.send(json.dumps({
                        "type": "session.update",
                        "session": {
                            "voice": DASHSCOPE_TTS_VOICE,
                            "output_audio_format": "pcm",
                            "sample_rate": 16000,
                            "mode": "commit",
                            "language_type": "Chinese",
                        },
                    }))

                elif msg_type == "session.updated":
                    session_ready = True
                    logger.info(f"[DashscopeTTS] 会话就绪 model={DASHSCOPE_TTS_MODEL} voice={DASHSCOPE_TTS_VOICE}")
                    try:
                        await websocket.send_json({"event": "ready"})
                    except Exception:
                        break

                elif msg_type == "response.audio.delta":
                    # 解码 base64 PCM 并转发给客户端
                    delta_b64 = msg.get("delta", "")
                    if delta_b64 and not audio_done_event.is_set():
                        try:
                            pcm = base64.b64decode(delta_b64)
                            await websocket.send_bytes(pcm)
                        except Exception:
                            pass

                elif msg_type == "response.done":
                    # 当前句合成完毕，通知主循环
                    sid = current_speak_id
                    logger.info(f"[DashscopeTTS] response.done id={sid[:8] if sid else ''}")
                    audio_done_event.set()

                elif msg_type == "session.finished":
                    logger.info("[DashscopeTTS] session.finished，reader 退出")
                    audio_done_event.set()
                    break

                elif msg_type == "error":
                    err = msg.get("error") or {}
                    logger.warning(f"[DashscopeTTS] 错误: {err}")
                    audio_done_event.set()   # 防止主循环永久等待
                    try:
                        await websocket.send_json({
                            "event": "error", "id": current_speak_id,
                            "message": err.get("message", "qwen_tts_error"),
                        })
                    except Exception:
                        pass

        except Exception as re:
            logger.warning(f"[DashscopeTTS] reader 异常: {type(re).__name__}: {re!r}")
        finally:
            audio_done_event.set()   # 确保主循环不会卡死

    reader = None

    try:
        # ── 预连 DashScope，session.updated 后发 ready ──────────────────────────
        try:
            qwen_ws = await _ws_lib.connect(
                dashscope_tts_url,
                additional_headers={"Authorization": f"Bearer {DASHSCOPE_TTS_API_KEY}"},
                ping_interval=20,
                open_timeout=15,
            )
        except Exception as ce:
            logger.error(f"[DashscopeTTS] 预连失败: {ce}")
            await websocket.send_json({"event": "error", "message": f"dashscope_connect_failed: {ce}"})
            return

        reader = asyncio.create_task(_reader_task(qwen_ws))

        # 等待 session.updated（最多 10s）
        for _ in range(100):
            if session_ready:
                break
            await asyncio.sleep(0.1)
        else:
            await websocket.send_json({"event": "error", "message": "session.updated 超时"})
            return

        # ── 主循环：依次处理每句 speak 请求 ────────────────────────────────────
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive(), timeout=120.0)
            except asyncio.TimeoutError:
                logger.info("[DashscopeTTS] 120s 无活动，关闭连接")
                break

            if msg.get("type") == "websocket.disconnect":
                break

            raw_text = msg.get("text") or ""
            if not raw_text:
                continue
            try:
                req = json.loads(raw_text)
            except Exception:
                continue

            ev = req.get("event", "")
            if ev == "close":
                logger.info("[DashscopeTTS] 收到 close 事件")
                break
            if ev != "speak":
                continue

            speak_text = (req.get("text") or "").strip()
            speak_id   = req.get("id", "")

            if not speak_text:
                await websocket.send_json({"event": "done", "id": speak_id})
                continue

            logger.info(f"[DashscopeTTS] 合成开始 id={speak_id[:8] if speak_id else ''} text={speak_text!r:.80}")

            # 重置 done 事件，记录当前句 id
            audio_done_event.clear()
            current_speak_id = speak_id

            # 向 DashScope 发送文本并立即提交
            try:
                await qwen_ws.send(json.dumps({
                    "type": "input_text_buffer.append",
                    "text": speak_text,
                }))
                await qwen_ws.send(json.dumps({"type": "input_text_buffer.commit"}))
            except Exception as se:
                logger.warning(f"[DashscopeTTS] 发送失败: {se}")
                await websocket.send_json({"event": "error", "id": speak_id, "message": str(se)})
                break

            # 等待 response.done（最多 30s）
            try:
                await asyncio.wait_for(audio_done_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning(f"[DashscopeTTS] response.done 超时 id={speak_id[:8] if speak_id else ''}")
                await websocket.send_json({"event": "error", "id": speak_id, "message": "synthesis_timeout"})
                continue

            # 发送 done 事件
            t_total = 0.0
            logger.info(f"[DashscopeTTS] 合成完成 id={speak_id[:8] if speak_id else ''} text={speak_text!r:.80}")
            try:
                await websocket.send_json({"event": "done", "id": speak_id})
            except Exception:
                break

    except WebSocketDisconnect:
        logger.info("[DashscopeTTS] 客户端断开")
    except Exception as e:
        logger.error(f"[DashscopeTTS] 未捕获异常: {type(e).__name__}: {e!r}", exc_info=True)
        try:
            await websocket.send_json({"event": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        if reader and not reader.done():
            reader.cancel()
        if qwen_ws:
            try:
                # 通知 DashScope 结束会话
                await qwen_ws.send(json.dumps({"type": "session.finish"}))
            except Exception:
                pass
            try:
                await qwen_ws.close()
            except Exception:
                pass
        try:
            await websocket.close(code=1000)
        except Exception:
            pass
