package top.ponychat.webview

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.util.Log
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject
import top.ponychat.webview.audio.MobileVoiceEffect
import top.ponychat.webview.data.api.NetworkClient
import java.net.URL
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/**
 * 陪玩 TTS 桥接：与后端 /ws/tts/dashscope 维持一条持久 WebSocket 连接，
 * 依次发送多个 speak 请求，接收 PCM 音频帧并通过 AudioTrack 实时播放。
 * 后端使用 DashScope Qwen TTS Realtime（Cherry 音色，16kHz PCM）。
 *
 * 优化要点（相对旧版每句新建 WS）：
 *   - 首句：建立持久 WS，等待 ready 事件后发送 speak，与旧版延迟相当
 *   - 第二句起：直接在已建立的 WS 上发送 speak，省去 TCP/TLS 握手（约 200~400ms/句）
 *
 * 使用方式：
 *   bridge.speak("你好啊！")   // 入队并按序播放
 *   bridge.stop()               // 立即停止播放并清空队列（保留 WS 连接供下次复用）
 *   bridge.release()            // 服务销毁时调用，发 close 并关闭 WS
 *
 * 线程安全：
 *   - speak / stop / release / processNextInQueue 均通过 synchronized(this) 保护共享状态
 *   - currentTrack / isStopped / persistentWs 用 @Volatile 保证可见性
 *   - currentTotalFrames 用 AtomicInteger 保证原子更新
 */
class CompanionTtsBridge(
    private val apiBase: String,
    private val authToken: String,
) {
    private val httpClient = NetworkClient.createTrustAllClient(
        connectTimeoutSec = 10L,
        readTimeoutSec = 30L,
    )

    // ── 播放队列：Triple(过滤后文本, voice, 唯一 speakId) ───────────────────────
    private val speakQueue = ArrayDeque<Triple<String, String, String>>()

    // ── 持久 WS 状态 ─────────────────────────────────────────────────────────────
    @Volatile private var persistentWs: WebSocket? = null
    /** wsGen 每次建立新 WS 时递增，用于使旧 WS 的异步回调失效 */
    private val wsGen = AtomicLong(0L)
    /** WS 已连接且后端已发出 ready，可以发送 speak 事件 */
    private var isWsReady = false  // 只在 synchronized(this) 内访问

    // ── 当前句播放状态 ───────────────────────────────────────────────────────────
    @Volatile private var currentTrack: AudioTrack? = null
    /** 当前句对应的 speakId；done 事件只有 id 匹配时才触发下一句 */
    @Volatile private var currentSpeakId = ""
    /** 已写入 AudioTrack 的总帧数（16-bit PCM，2 字节 = 1 帧） */
    private val currentTotalFrames = AtomicInteger(0)
    private var currentPcmProcessor: MobileVoiceEffect.PcmProcessor? = null

    // ── 全局停止标志 ─────────────────────────────────────────────────────────────
    @Volatile private var isStopped = false
    private var isSpeaking = false  // 只在 synchronized(this) 内访问

    /** 外部只读：当前 TTS 队列是否有内容正在播放或等待播放（粗粒度检查，无需精确同步）。 */
    val isCurrentlySpeaking: Boolean get() = isSpeaking || speakQueue.isNotEmpty()

    // ── 外部回调（由 CompanionService 设置） ─────────────────────────────────────
    /** 每句话开始合成时（speak 事件已发出）回调，参数为该句原始文本。主线程友好（调用方自行 post）。 */
    var onSentenceStarted: ((text: String) -> Unit)? = null

    /** 队列中所有句子播放完毕（非被 stop() 打断）时回调。主线程友好（调用方自行 post）。 */
    var onAllDone: (() -> Unit)? = null

    companion object {
        private const val TAG = "CompanionTtsBridge"
        private const val SAMPLE_RATE = 16000

        /**
         * 移除 emoji 及非语音符号，避免阿里云 NLS 返回乱码或静音。
         */
        fun stripEmoji(text: String): String {
            val sb = StringBuilder(text.length)
            var i = 0
            while (i < text.length) {
                val c = text[i]
                if (c.isHighSurrogate() && i + 1 < text.length && text[i + 1].isLowSurrogate()) {
                    i += 2; continue
                }
                val cp = c.code
                if (cp in 0x2600..0x27FF || cp in 0x2B00..0x2BFF
                    || cp in 0xFE00..0xFE0F || cp == 0x200D || cp == 0xFEFF) {
                    i++; continue
                }
                sb.append(c)
                i++
            }
            return sb.toString().trim()
        }
    }

    // ── 公开接口 ──────────────────────────────────────────────────────────────────

    /** 将文本加入播放队列，若当前空闲则立即开始（建立连接或直接发 speak）。 */
    @Synchronized
    fun speak(text: String, voice: String = "xiaoyun") {
        val noActions = text
            .replace(Regex("[（(][^）)]*[）)]"), " ")
            .replace(Regex("\\s{2,}"), " ")
            .trim()
        val filtered = stripEmoji(noActions)
        if (filtered.isBlank()) return

        isStopped = false
        val speakId = UUID.randomUUID().toString()
        speakQueue.add(Triple(filtered, voice, speakId))
        Log.i(TAG, "speak() 入队[${speakQueue.size}] isSpeaking=$isSpeaking text=${filtered.take(20)}")
        if (!isSpeaking) processNextInQueue()
    }

    /**
     * 立即停止当前播放并清空队列。
     * 保留持久 WS 连接（不关闭），供下次 speak() 直接复用。
     */
    @Synchronized
    fun stop() {
        val caller = Thread.currentThread().name
        Log.w(TAG, "stop() from $caller session=${wsGen.get()} isSpeaking=$isSpeaking queue=${speakQueue.size}")
        isStopped = true
        speakQueue.clear()
        isSpeaking = false
        currentSpeakId = ""       // 使后续到达的 done 事件无效
        currentPcmProcessor = null
        currentTotalFrames.set(0)
        val track = currentTrack; currentTrack = null
        forceRelease(track)
        // 不关闭 persistentWs，下次 speak() 可直接复用
    }

    /**
     * 服务销毁时调用：停止播放，发送 close 事件并关闭 WS 连接。
     */
    fun release() {
        stop()
        val ws = synchronized(this) {
            val w = persistentWs; persistentWs = null; isWsReady = false; w
        }
        try {
            ws?.send(JSONObject().put("event", "close").toString())
            ws?.close(1000, "release")
        } catch (_: Exception) {}
    }

    // ── 内部状态机 ────────────────────────────────────────────────────────────────

    /**
     * 取队首，决定是在已有 WS 上发 speak 还是先建立新 WS。
     * 必须在 synchronized(this) 内调用。
     */
    private fun processNextInQueue() {
        if (isStopped) { isSpeaking = false; return }
        val next = speakQueue.removeFirstOrNull()
        if (next == null) {
            isSpeaking = false
            Log.d(TAG, "processNextInQueue: 队列已空，触发 onAllDone")
            onAllDone?.invoke()
            return
        }

        isSpeaking = true
        val (text, voice, speakId) = next
        Log.i(TAG, "processNextInQueue: id=${speakId.take(8)} text=${text.take(20)} isWsReady=$isWsReady")

        if (isWsReady && persistentWs != null) {
            startSentencePlayback(text, voice, speakId)
        } else {
            connectAndStartSentence(text, voice, speakId)
        }
    }

    /**
     * 在已有持久 WS 上为新句子创建 AudioTrack 并发送 speak 事件。
     * 必须在 synchronized(this) 内调用。
     */
    private fun startSentencePlayback(text: String, voice: String, speakId: String) {
        val track = buildAudioTrack() ?: run {
            Log.w(TAG, "startSentencePlayback: AudioTrack 创建失败，跳过")
            isSpeaking = false
            processNextInQueue()
            return
        }
        currentTrack = track
        currentSpeakId = speakId
        currentPcmProcessor = MobileVoiceEffect.newPcmProcessor(SAMPLE_RATE)
        currentTotalFrames.set(0)
        track.play()

        Log.i(TAG, "startSentencePlayback: id=${speakId.take(8)} text=${text.take(20)}")
        val sent = persistentWs?.send(JSONObject().apply {
            put("event", "speak")
            put("text", text)
            put("voice", voice)
            put("id", speakId)
        }.toString()) ?: false

        if (!sent) {
            Log.w(TAG, "startSentencePlayback: WS 发送失败，重建连接后重试")
            isWsReady = false
            persistentWs = null
            forceRelease(track); currentTrack = null; currentPcmProcessor = null
            // 当前句放回队首，通过重新建立 WS 后再取出播放
            speakQueue.addFirst(Triple(text, voice, speakId))
            connectAndStartSentenceFromQueue()
        } else {
            // 发送成功：通知外部当前句开始合成（约 0.5s 后音频开始到达）
            onSentenceStarted?.invoke(text)
        }
    }

    /** WS 发送失败或连接断开时：从队首取出下一句，建立新 WS 后播放。 */
    private fun connectAndStartSentenceFromQueue() {
        val next = speakQueue.removeFirstOrNull() ?: run { isSpeaking = false; return }
        connectAndStartSentence(next.first, next.second, next.third)
    }

    /**
     * 建立新的持久 WS 连接，连接成功（收到 ready）后立即为首句启动播放。
     * 必须在 synchronized(this) 内调用（会在内部释放锁执行 WS 建立）。
     */
    private fun connectAndStartSentence(firstText: String, firstVoice: String, firstId: String) {
        val myGen = wsGen.incrementAndGet()
        isWsReady = false

        Log.i(TAG, "connectAndStartSentence: wsGen=$myGen firstId=${firstId.take(8)}")
        val request = Request.Builder()
            .url(buildTtsWsUrl())
            .addHeader("X-Chat-Auth", authToken)
            .build()

        val listener = object : WebSocketListener() {

            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (wsGen.get() != myGen) { webSocket.cancel(); return }
                Log.i(TAG, "onOpen: wsGen=$myGen")
                // 等待 ready 事件，在 onMessage 中处理首句发送
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (wsGen.get() != myGen) return
                try {
                    val msg = JSONObject(text)
                    when (msg.optString("event")) {
                        "ready" -> {
                            Log.i(TAG, "onMessage/ready: wsGen=$myGen，开始首句播放")
                            synchronized(this@CompanionTtsBridge) {
                                if (wsGen.get() != myGen || isStopped) {
                                    isSpeaking = false; return
                                }
                                isWsReady = true
                                startSentencePlayback(firstText, firstVoice, firstId)
                            }
                        }

                        "done" -> {
                            val doneId = msg.optString("id")
                            if (doneId != currentSpeakId) {
                                Log.d(TAG, "onMessage/done: id 不匹配 $doneId != $currentSpeakId，忽略")
                                return
                            }
                            // 等待 AudioTrack 缓冲区播完，再处理下一句
                            val myTrack      = currentTrack
                            val myFrameCount = currentTotalFrames.get()
                            val myGen2       = myGen
                            Thread {
                                if (myTrack != null) {
                                    val headPos  = try { myTrack.playbackHeadPosition } catch (_: Exception) { 0 }
                                    val remaining = (myFrameCount - headPos).coerceAtLeast(0)
                                    val hwLatencyMs = 250L
                                    val waitMs  = (remaining * 1000L / SAMPLE_RATE) + hwLatencyMs
                                    Log.i(TAG, "done: totalFrames=$myFrameCount headPos=$headPos remaining=${remaining}f waitMs=${waitMs}ms")
                                    try { Thread.sleep(waitMs) } catch (_: InterruptedException) {}
                                }
                                try {
                                    myTrack?.let { t ->
                                        if (t.state == AudioTrack.STATE_INITIALIZED) t.stop()
                                        t.release()
                                    }
                                } catch (_: Exception) {}
                                if (currentTrack == myTrack) {
                                    currentTrack = null
                                    currentPcmProcessor = null
                                }

                                synchronized(this@CompanionTtsBridge) {
                                    if (wsGen.get() == myGen2 && !isStopped) {
                                        processNextInQueue()
                                    } else {
                                        isSpeaking = false
                                    }
                                }
                            }.start()
                        }

                        "error" -> {
                            val errId = msg.optString("id")
                            Log.w(TAG, "onMessage/error id=$errId: ${msg.optString("message")}")
                            if (errId.isEmpty() || errId == currentSpeakId) {
                                forceRelease(currentTrack); currentTrack = null; currentPcmProcessor = null
                                synchronized(this@CompanionTtsBridge) {
                                    if (wsGen.get() == myGen) processNextInQueue()
                                    else isSpeaking = false
                                }
                            }
                        }
                    }
                } catch (_: Exception) {}
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                if (wsGen.get() != myGen) return
                val track = currentTrack ?: return
                val pcm = bytes.toByteArray()
                currentPcmProcessor?.processPcm16InPlace(pcm)
                track.write(pcm, 0, pcm.size)
                currentTotalFrames.addAndGet(pcm.size / 2)  // 16-bit PCM：2 字节 = 1 帧
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                if (wsGen.get() != myGen) return
                Log.d(TAG, "onClosing: code=$code wsGen=$myGen")
                webSocket.close(code, reason)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "onClosed: code=$code wsGen=$myGen current=${wsGen.get()}")
                synchronized(this@CompanionTtsBridge) {
                    if (wsGen.get() != myGen) return
                    isWsReady = false
                    if (persistentWs === webSocket) persistentWs = null
                    // WS 意外关闭（非 release() 主动关闭）时，若仍需播放则重建
                    if (isSpeaking && !isStopped) {
                        Log.w(TAG, "onClosed: WS 意外关闭，重建连接继续播放")
                        connectAndStartSentenceFromQueue()
                    }
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w(TAG, "onFailure: ${t.message} wsGen=$myGen current=${wsGen.get()}")
                synchronized(this@CompanionTtsBridge) {
                    if (wsGen.get() != myGen) return
                    isWsReady = false
                    if (persistentWs === webSocket) persistentWs = null
                    forceRelease(currentTrack); currentTrack = null; currentPcmProcessor = null
                    if (isSpeaking && !isStopped) {
                        connectAndStartSentenceFromQueue()
                    }
                }
            }
        }

        persistentWs = httpClient.newWebSocket(request, listener)
    }

    // ── 工具 ─────────────────────────────────────────────────────────────────────

    private fun buildAudioTrack(): AudioTrack? {
        val minBuf = AudioTrack.getMinBufferSize(
            SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT
        )
        return try {
            AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setSampleRate(SAMPLE_RATE)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .build()
                )
                .setBufferSizeInBytes(minBuf * 8)
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build()
        } catch (e: Exception) {
            Log.w(TAG, "AudioTrack 创建失败: ${e.message}")
            null
        }
    }

    private fun forceRelease(track: AudioTrack?) {
        if (track == null) return
        try {
            if (track.state == AudioTrack.STATE_INITIALIZED) {
                track.pause(); track.flush(); track.stop()
            }
            track.release()
        } catch (_: Exception) {}
    }

    private fun buildTtsWsUrl(): String {
        return try {
            val base = apiBase.trimEnd('/')
            val url = URL(base)
            val scheme = if (url.protocol == "https") "wss" else "ws"
            val portPart = if (url.port > 0 && url.port != 80 && url.port != 443) ":${url.port}" else ""
            "$scheme://${url.host}$portPart/ws/tts/dashscope"
        } catch (_: Exception) {
            apiBase.trimEnd('/').replace("https://", "wss://").replace("http://", "ws://") + "/ws/tts/dashscope"
        }
    }
}
