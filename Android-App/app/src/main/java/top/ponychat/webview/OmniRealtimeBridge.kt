package top.ponychat.webview

import android.graphics.Bitmap
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import top.ponychat.webview.audio.MobileVoiceEffect
import top.ponychat.webview.data.api.NetworkClient
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * Qwen-Omni-Realtime 陪玩桥接。
 *
 * 单个 WebSocket 连接，覆盖所有陪玩交互：
 *  - 单次截图评论：sendFrame() + triggerScreenshot()
 *  - 对话框文字输入：sendText()
 *  - 实时语音模式（长按）：startVoiceMode() / stopVoiceMode()
 *
 * 帧率策略：
 *  - ACTIVE（语音激活 / AI 回复中）：最多 1fps
 *  - IDLE（正常等待）：最多 0.5fps
 *  - PAUSED：不发送
 *
 * 协议（与后端 /ws/companion/realtime 对接）：
 *  Android→后端 二进制：0x01 + PCM16 = 音频；0x02 + JPEG = 画面帧
 *  Android→后端 文本 JSON：init / voice_start / voice_stop / text / cancel / end
 *  后端→Android 二进制：裸 PCM24 字节（AI 音频，转为 PCM16 @ 24kHz 播放）
 *  后端→Android 文本 JSON：ready / speech_started / speech_stopped /
 *                           transcript_delta / transcript_done / response_done /
 *                           user_transcript / error
 */
class OmniRealtimeBridge(
    private val apiBase: String,
    private val authToken: String,
    private val characterId: String,
    private val username: String,
    private val callback: Callback,
    /** 后端 WebSocket 路径，默认实时版；传入 "/ws/companion/omni_chat" 切换到 HTTP 流式版 */
    private val wsPath: String = "/ws/companion/realtime",
) {
    interface Callback {
        /** 会话初始化完成，可以开始交互 */
        fun onReady()
        /** AI 回复文字增量（用于流式更新 UI） */
        fun onTranscriptDelta(text: String)
        /** AI 回复完整文字（一轮结束时） */
        fun onTranscriptDone(text: String)
        /** AI 本轮全部响应（文字+音频）完成 */
        fun onResponseDone()
        /** VAD 检测到用户开始说话 */
        fun onSpeechStarted()
        /** VAD 检测到用户停止说话 */
        fun onSpeechStopped()
        /** 用户本轮语音识别结果（显示在对话框用户气泡） */
        fun onUserTranscript(text: String)
        /** 出错通知 */
        fun onError(message: String)
        /** 连接已关闭 */
        fun onClosed()
    }

    enum class FrameMode { ACTIVE, IDLE, PAUSED }

    companion object {
        private const val TAG = "OmniRealtimeBridge"
        private const val MIC_SAMPLE_RATE = 16000   // input: pcm16 = 16kHz 16-bit
        private const val PLAYBACK_SAMPLE_RATE = 24000  // output: pcm24 = 24kHz 16-bit
        private const val FRAME_QUALITY = 70    // JPEG 质量（提高以确保 UI 文字可读）
        private const val FRAME_MAX_SIDE = 960  // 最长边缩放上限（保证竖屏文字清晰）
    }

    /**
     * 每次 AI 回复的最大字数上限（0 = 不限制）。
     * 可随时从外部修改，将在下一次请求时生效。
     */
    @Volatile var maxReplyChars: Int = 0

    // ── 帧率控制 ───────────────────────────────────────────────────────────────
    @Volatile var frameMode: FrameMode = FrameMode.IDLE

    private var lastFrameSentMs: Long = 0L
    private var lastFrameHash: Int = 0

    // ── WebSocket & 状态 ──────────────────────────────────────────────────────
    private val isConnected = AtomicBoolean(false)
    private var ws: WebSocket? = null

    // ── AudioRecord（语音输入，仅实时语音模式下激活） ─────────────────────────
    private var audioRecord: AudioRecord? = null
    private var recordingThread: Thread? = null
    @Volatile private var isVoiceModeActive = false
    @Volatile private var stopMicRequested = false

    // ── AudioTrack（AI 音频输出，24kHz PCM16） ────────────────────────────────
    private var audioTrack: AudioTrack? = null
    private var playbackPcmProcessor: MobileVoiceEffect.PcmProcessor? = null
    private var audioPlayThread: Thread? = null
    private val audioQueue = java.util.concurrent.LinkedBlockingQueue<ByteArray>()
    @Volatile private var stopPlaybackRequested = false

    private val okHttpClient: OkHttpClient = NetworkClient.createTrustAllClient(
        connectTimeoutSec = 10,
        readTimeoutSec = 120,
        writeTimeoutSec = 30,
        pingIntervalSec = 20,
    )

    // ── 公开接口 ───────────────────────────────────────────────────────────────

    /** 建立连接并发送 init 事件。调用后等待 onReady() 回调。 */
    fun connect() {
        if (isConnected.get()) return

        val wsUrl = "${apiBase.trimEnd('/').replace("http://", "ws://").replace("https://", "wss://")}$wsPath"
        Log.i(TAG, "connect: $wsUrl")

        val request = Request.Builder()
            .url(wsUrl)
            .addHeader("X-Chat-Auth", authToken)
            .build()

        ws = okHttpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.i(TAG, "WebSocket opened")
                isConnected.set(true)
                // 发 init
                webSocket.send(
                    JSONObject()
                        .put("event", "init")
                        .put("character_id", characterId)
                        .put("username", username)
                        .toString()
                )
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleServerText(text)
            }

            override fun onMessage(webSocket: WebSocket, bytes: okio.ByteString) {
                handleServerAudio(bytes.toByteArray())
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, reason)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WebSocket closed: $code $reason")
                handleDisconnect()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "WebSocket failure: ${t.message}")
                callback.onError("连接断开: ${t.message}")
                handleDisconnect()
            }
        })

        startAudioPlayback()
    }

    /** 断开连接，释放所有资源 */
    fun disconnect() {
        ws?.send(JSONObject().put("event", "end").toString())
        stopVoiceModeInternal()
        stopAudioPlayback()
        ws?.close(1000, "client_end")
        ws = null
        isConnected.set(false)
    }

    /**
     * 向桥接提供一帧截图。桥接根据当前帧率模式决定是否真正发送。
     * 由 CompanionService 的帧捕获循环以 ≤2fps 调用。
     */
    fun offerFrame(bitmap: Bitmap) {
        if (!isConnected.get()) { bitmap.recycle(); return }
        val mode = frameMode
        if (mode == FrameMode.PAUSED) { bitmap.recycle(); return }

        val now = System.currentTimeMillis()
        val minIntervalMs = if (mode == FrameMode.ACTIVE) 1000L else 2000L
        if (now - lastFrameSentMs < minIntervalMs) { bitmap.recycle(); return }

        // 简单内容变化检测（像素 hash 差异太小则跳过）
        val hash = bitmapHash(bitmap)
        if (hash == lastFrameHash && (now - lastFrameSentMs) < minIntervalMs * 3) {
            bitmap.recycle()
            return
        }

        lastFrameSentMs = now
        lastFrameHash = hash
        sendFrameInternal(bitmap)
    }

    /**
     * 截图触发（单击场景）：立即发送当前帧并请求 AI 评论当前画面。
     * 调用前应先调用 offerFrame() 确保画面已在缓冲区中，或传入非 null 的 bitmap。
     * @param hint 给 AI 的提示语（追加到 response instructions）
     * @param maxChars 本次回复的最大字数，0 = 使用 maxReplyChars 属性值，-1 = 不限
     */
    fun triggerScreenshot(bitmap: Bitmap?, hint: String = "请用一句话评论当前画面，简短有趣", maxChars: Int = 0) {
        if (!isConnected.get()) { bitmap?.recycle(); return }
        if (bitmap != null) {
            lastFrameSentMs = System.currentTimeMillis()
            lastFrameHash = bitmapHash(bitmap)
            sendFrameInternal(bitmap)
        }
        val effectiveMax = if (maxChars == 0) maxReplyChars else if (maxChars < 0) 0 else maxChars
        val payload = JSONObject()
            .put("event", "text")
            .put("text", "")
            .put("hint", hint)
        if (effectiveMax > 0) payload.put("max_chars", effectiveMax)
        ws?.send(payload.toString())
    }

    /**
     * 发送文字消息（对话框输入）。
     * @param maxChars 本次回复的最大字数，0 = 使用 maxReplyChars 属性值，-1 = 不限
     */
    fun sendText(text: String, hint: String = "", maxChars: Int = 0) {
        if (!isConnected.get()) return
        val effectiveMax = if (maxChars == 0) maxReplyChars else if (maxChars < 0) 0 else maxChars
        val payload = JSONObject()
            .put("event", "text")
            .put("text", text)
        if (hint.isNotBlank()) payload.put("hint", hint)
        if (effectiveMax > 0) payload.put("max_chars", effectiveMax)
        ws?.send(payload.toString())
    }

    /** 取消当前 AI 回复 */
    fun cancelResponse() {
        if (!isConnected.get()) return
        ws?.send(JSONObject().put("event", "cancel").toString())
        stopAudioPlayback()
        startAudioPlayback()
    }

    /** 停止 AI 音频播放（用户开始说话时调用） */
    fun stopAudioOutput() {
        audioQueue.clear()
        audioTrack?.pause()
        audioTrack?.flush()
        audioTrack?.play()
    }

    /** 进入实时语音模式（开启 VAD + 麦克风采集） */
    fun startVoiceMode() {
        if (!isConnected.get()) return
        if (isVoiceModeActive) return
        isVoiceModeActive = true
        stopMicRequested = false
        frameMode = FrameMode.ACTIVE
        ws?.send(JSONObject().put("event", "voice_start").toString())
        startMic()
        Log.i(TAG, "Voice mode started")
    }

    /** 退出实时语音模式（关闭 VAD + 停止麦克风） */
    fun stopVoiceMode() {
        if (!isVoiceModeActive) return
        stopVoiceModeInternal()
        ws?.send(JSONObject().put("event", "voice_stop").toString())
        frameMode = FrameMode.IDLE
        Log.i(TAG, "Voice mode stopped")
    }

    fun isVoiceActive(): Boolean = isVoiceModeActive
    fun isConnected(): Boolean = isConnected.get()

    // ── 内部：服务端消息处理 ───────────────────────────────────────────────────

    private fun handleServerText(text: String) {
        val json = try {
            JSONObject(text)
        } catch (e: Exception) {
            Log.w(TAG, "invalid JSON from server: $text")
            return
        }
        when (json.optString("event")) {
            "ready" -> {
                Log.i(TAG, "Session ready, voice=${json.optString("voice")}")
                callback.onReady()
            }
            "speech_started" -> {
                frameMode = FrameMode.ACTIVE
                stopAudioOutput()  // 打断 AI 正在说的话
                callback.onSpeechStarted()
            }
            "speech_stopped" -> {
                callback.onSpeechStopped()
            }
            "transcript_delta" -> {
                val delta = json.optString("text")
                if (delta.isNotBlank()) callback.onTranscriptDelta(delta)
            }
            "transcript_done" -> {
                val full = json.optString("text")
                callback.onTranscriptDone(full)
            }
            "response_done" -> {
                frameMode = FrameMode.IDLE
                callback.onResponseDone()
            }
            "user_transcript" -> {
                val transcript = json.optString("text")
                if (transcript.isNotBlank()) callback.onUserTranscript(transcript)
            }
            "error" -> {
                val msg = json.optString("message", "未知错误")
                Log.w(TAG, "Server error: $msg")
                callback.onError(msg)
            }
        }
    }

    private fun handleServerAudio(data: ByteArray) {
        if (data.isEmpty()) return
        // pcm24 = 24kHz、16-bit PCM（数字指采样率 kHz，不是位深）
        // 与 input pcm16（16kHz、16-bit）对应，无需格式转换，直接入队播放
        audioQueue.offer(data)
    }

    private fun handleDisconnect() {
        isConnected.set(false)
        isVoiceModeActive = false
        stopMicRequested = true
        stopPlaybackRequested = true
        callback.onClosed()
    }

    // ── 内部：麦克风采集 ──────────────────────────────────────────────────────

    private fun startMic() {
        if (recordingThread != null) return
        val minBufSize = AudioRecord.getMinBufferSize(
            MIC_SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (minBufSize <= 0) {
            callback.onError("麦克风初始化失败")
            return
        }
        val bufSize = (minBufSize * 2).coerceAtLeast(3200)
        val record = try {
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                MIC_SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufSize,
            )
        } catch (e: SecurityException) {
            callback.onError("没有麦克风权限")
            return
        } catch (e: Exception) {
            callback.onError("麦克风打开失败: ${e.message}")
            return
        }
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            callback.onError("麦克风未就绪")
            return
        }
        if (AcousticEchoCanceler.isAvailable()) {
            AcousticEchoCanceler.create(record.audioSessionId)?.enabled = true
        }
        if (NoiseSuppressor.isAvailable()) {
            NoiseSuppressor.create(record.audioSessionId)?.enabled = true
        }
        audioRecord = record
        recordingThread = thread(name = "OmniMicThread") {
            val buf = ByteArray(bufSize)
            try {
                record.startRecording()
                while (isVoiceModeActive && !stopMicRequested) {
                    val read = record.read(buf, 0, buf.size)
                    if (read > 0 && isConnected.get()) {
                        // 协议：0x01 前缀 + PCM16 数据
                        val packet = ByteArray(1 + read)
                        packet[0] = 0x01
                        System.arraycopy(buf, 0, packet, 1, read)
                        ws?.send(packet.toByteString())
                    } else if (read < 0) {
                        break
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "mic thread error: ${e.message}")
            } finally {
                try { record.stop() } catch (_: Exception) {}
                try { record.release() } catch (_: Exception) {}
            }
        }
    }

    private fun stopVoiceModeInternal() {
        isVoiceModeActive = false
        stopMicRequested = true
        try { audioRecord?.stop() } catch (_: Exception) {}
        try { audioRecord?.release() } catch (_: Exception) {}
        audioRecord = null
        recordingThread = null
    }

    // ── 内部：AI 音频播放（24kHz PCM16） ─────────────────────────────────────

    private fun startAudioPlayback() {
        if (audioPlayThread?.isAlive == true) return
        stopPlaybackRequested = false

        val minBuf = AudioTrack.getMinBufferSize(
            PLAYBACK_SAMPLE_RATE,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val track = try {
            AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setSampleRate(PLAYBACK_SAMPLE_RATE)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .build()
                )
                .setBufferSizeInBytes((minBuf * 4).coerceAtLeast(8192))
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build()
        } catch (e: Exception) {
            Log.w(TAG, "AudioTrack 创建失败: ${e.message}")
            return
        }
        audioTrack = track
        playbackPcmProcessor = MobileVoiceEffect.newPcmProcessor(PLAYBACK_SAMPLE_RATE)
        audioPlayThread = thread(name = "OmniPlayThread") {
            track.play()
            while (!stopPlaybackRequested) {
                val chunk = audioQueue.poll(200, java.util.concurrent.TimeUnit.MILLISECONDS)
                if (chunk != null) {
                    playbackPcmProcessor?.processPcm16InPlace(chunk)
                    track.write(chunk, 0, chunk.size)
                }
            }
            track.stop()
            track.release()
        }
    }

    private fun stopAudioPlayback() {
        stopPlaybackRequested = true
        audioQueue.clear()
        try { audioTrack?.pause(); audioTrack?.flush() } catch (_: Exception) {}
        try { audioTrack?.stop(); audioTrack?.release() } catch (_: Exception) {}
        audioTrack = null
        playbackPcmProcessor = null
        audioPlayThread = null
    }

    // ── 内部：发送画面帧 ──────────────────────────────────────────────────────

    private fun sendFrameInternal(bitmap: Bitmap) {
        thread(name = "OmniFrameEncode") {
            try {
                // 缩放（保持宽高比，最长边 ≤ FRAME_MAX_SIDE）
                val scaled = scaleBitmap(bitmap)
                bitmap.recycle()
                val baos = ByteArrayOutputStream()
                scaled.compress(Bitmap.CompressFormat.JPEG, FRAME_QUALITY, baos)
                scaled.recycle()
                val jpeg = baos.toByteArray()
                // 协议：0x02 前缀 + JPEG
                val packet = ByteArray(1 + jpeg.size)
                packet[0] = 0x02
                System.arraycopy(jpeg, 0, packet, 1, jpeg.size)
                ws?.send(packet.toByteString())
            } catch (e: Exception) {
                Log.w(TAG, "sendFrame failed: ${e.message}")
            }
        }
    }

    private fun scaleBitmap(src: Bitmap): Bitmap {
        val w = src.width
        val h = src.height
        val maxSide = FRAME_MAX_SIDE
        if (w <= maxSide && h <= maxSide) return src
        val scale = maxSide.toFloat() / maxOf(w, h)
        val newW = (w * scale).toInt().coerceAtLeast(1)
        val newH = (h * scale).toInt().coerceAtLeast(1)
        return Bitmap.createScaledBitmap(src, newW, newH, true)
    }

    private fun bitmapHash(bitmap: Bitmap): Int {
        // 采样 16×16 像素点计算简单 hash，用于跳过静止帧
        val step = maxOf(bitmap.width / 16, 1)
        val stepY = maxOf(bitmap.height / 16, 1)
        var hash = 0
        var x = 0
        while (x < bitmap.width) {
            var y = 0
            while (y < bitmap.height) {
                hash = hash * 31 + bitmap.getPixel(x, y)
                y += stepY
            }
            x += step
        }
        return hash
    }
}
