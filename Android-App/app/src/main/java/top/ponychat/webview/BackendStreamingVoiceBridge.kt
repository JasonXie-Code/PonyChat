package top.ponychat.webview

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.util.Log
import top.ponychat.webview.util.DebugLog
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * 原生麦克风采集 + 后端 /ws/speech 流式识别桥接。
 * 仅负责音频采集与协议转发，不做本地识别。
 */
class BackendStreamingVoiceBridge(
    private val callback: Callback
) {
    interface Callback {
        fun onStarted()
        fun onPartial(text: String)
        fun onFinal(text: String)
        fun onError(code: String, message: String? = null)
        fun onEnded(reason: String, text: String?)
    }

    companion object {
        private const val TAG = "BackendVoiceBridge"
        private const val SAMPLE_RATE = 16000
        private const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        private const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
    }

    @Volatile
    private var isRunning = false
    @Volatile
    private var isSocketReady = false
    @Volatile
    private var stopRequested = false
    @Volatile
    private var hasEndedCallback = false
    @Volatile
    private var hasFinalCallback = false
    /** 预热模式：WS 连接已建立，但暂不开启麦克风，也不触发 onStarted 回调 */
    @Volatile
    private var prewarmMode = false

    private var ws: WebSocket? = null
    private var audioRecord: AudioRecord? = null
    private var recordingThread: Thread? = null
    private var seq: Int = 0
    private var wsUrl: String = ""
    private var lang: String = "auto"
    private var lastFinalText: String? = null
    private val sessionCounter = AtomicLong(0)
    @Volatile
    private var activeSessionId: Long = 0L

    private val okHttpClient: OkHttpClient = top.ponychat.webview.data.api.NetworkClient.createTrustAllClient(
        connectTimeoutSec = 10,
        readTimeoutSec = 60,
        writeTimeoutSec = 30,
        pingIntervalSec = 20
    )

    fun isActive(): Boolean = isRunning

    /** WS 已就绪（握手完成）且处于预热等待状态，可立即激活录音。 */
    fun isPrewarmed(): Boolean = isSocketReady && prewarmMode

    /**
     * 预热模式启动：建立 WS 连接并完成握手，但不开启麦克风，不触发 onStarted。
     * 用于进入 classic 模式时提前建好连接，用户长按时通过 [activateRecording] 零延迟开录。
     */
    @Synchronized
    fun prewarm(targetWsUrl: String, targetLang: String?) {
        prewarmMode = true
        start(targetWsUrl, targetLang)
    }

    /**
     * 激活录音（配合 [prewarm] 使用）：开启麦克风并触发 onStarted 回调。
     * - 若 WS 已就绪（isPrewarmed()），立即开始录音，零延迟。
     * - 若 WS 尚在连接中，清除预热标记，后续 started 事件到来时自动开录。
     */
    @Synchronized
    fun activateRecording() {
        prewarmMode = false
        if (!isRunning) return
        if (isSocketReady) {
            // 握手已完成，直接开录
            callback.onStarted()
            startRecordingLoop()
        }
        // 若 isSocketReady = false，started 事件到达时 prewarmMode = false 会正常走录音流程
    }

    @Synchronized
    fun start(targetWsUrl: String, targetLang: String?) {
        if (isRunning) {
            Log.w(TAG, "start ignored: already running")
            return
        }

        wsUrl = targetWsUrl
        lang = (targetLang ?: "auto").ifBlank { "auto" }
        isRunning = true
        isSocketReady = false
        stopRequested = false
        hasEndedCallback = false
        hasFinalCallback = false
        lastFinalText = null
        seq = 0
        activeSessionId = sessionCounter.incrementAndGet()
        val startSessionId = activeSessionId

        val request = Request.Builder().url(wsUrl).build()
        ws = okHttpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (startSessionId != activeSessionId) return
                Log.i(TAG, "WebSocket connected: $wsUrl")
                val startPayload = JSONObject()
                    .put("event", "start")
                    .put("lang", lang)
                    .put("protocol", "pcm16le_seq_v1")
                    .toString()
                webSocket.send(startPayload)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (startSessionId != activeSessionId) return
                handleServerMessage(text)
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                // 服务端协议当前只推 JSON 文本，忽略二进制回包。
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                if (startSessionId != activeSessionId) return
                Log.w(TAG, "WebSocket closing: code=$code reason=$reason")
                webSocket.close(code, reason)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (startSessionId != activeSessionId) return
                Log.i(TAG, "WebSocket closed: code=$code reason=$reason")
                handleSocketClosed()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (startSessionId != activeSessionId) return
                DebugLog.e(TAG, "WebSocket failure: ${t.message}", t)
                Log.e(TAG, "[onFailure] stopRequested=$stopRequested isRunning=$isRunning hasEndedCallback=$hasEndedCallback lastFinalText=$lastFinalText")
                if (isRunning && !hasEndedCallback) {
                    if (!stopRequested) {
                        callback.onError("network_error", t.message)
                    }
                    callback.onEnded(if (stopRequested) "user_stop" else "disconnect", lastFinalText)
                    hasEndedCallback = true
                }
                cleanupInternal()
            }
        })
    }

    @Synchronized
    fun stop() {
        if (!isRunning) return
        Log.i(TAG, "[stop] 开始停止录音，stopRequested=${stopRequested} isSocketReady=${isSocketReady}")
        stopRequested = true
        val stopSessionId = activeSessionId
        try {
            val sent = ws?.send(JSONObject().put("event", "stop").toString()) ?: false
            Log.i(TAG, "[stop] stop 事件发送: sent=$sent ws=${if (ws != null) "非null" else "null"}")
        } catch (e: Exception) {
            DebugLog.w(TAG, "send stop failed: ${e.message}", e)
        }
        Log.i(TAG, "[stop] 开始 stopRecordingLoop...")
        stopRecordingLoop()
        Log.i(TAG, "[stop] stopRecordingLoop 完成，等待服务端 end 响应（兜底 1800ms）")
        // 兜底：如果服务端/连接没有回 end，强制收敛状态，避免后续 start 被 isRunning 阻塞。
        thread(start = true, name = "BackendVoiceStopFallback") {
            Thread.sleep(1800)
            if (stopSessionId == activeSessionId && isRunning) {
                Log.w(TAG, "[stop/fallback] 1800ms 后仍未收到 end，强制结束 hasEndedCallback=$hasEndedCallback lastFinalText=$lastFinalText")
                if (!hasEndedCallback) {
                    callback.onEnded("user_stop", lastFinalText)
                    hasEndedCallback = true
                }
                cleanupInternal()
            }
        }
    }

    @Synchronized
    fun release() {
        stopRequested = true
        cleanupInternal()
    }

    private fun handleServerMessage(text: String) {
        val payload = try {
            JSONObject(text)
        } catch (e: Exception) {
            DebugLog.w(TAG, "Invalid JSON payload: $text", e)
            return
        }

        when ((payload.optString("event", "") ?: "").lowercase()) {
            "started" -> {
                if (!isRunning) return
                isSocketReady = true
                if (prewarmMode) {
                    // 预热模式：握手完成，静默等待 activateRecording() 调用
                    Log.i(TAG, "prewarm: ASR 握手完成，等待用户触发录音")
                } else {
                    callback.onStarted()
                    startRecordingLoop()
                }
            }
            "speech_started" -> {
                // VAD 检测到用户开口，立即触发 onPartial 停止 TTS（Barge-in 打断）
                // 无需等第一个 transcription delta，节省 200-500ms
                callback.onPartial("")
            }
            "partial" -> {
                val partialText = payload.optString("text", "")
                if (partialText.isNotBlank()) {
                    callback.onPartial(partialText)
                }
            }
            "final" -> {
                val finalText = payload.optString("text", "")
                if (finalText.isNotBlank()) {
                    hasFinalCallback = true
                    lastFinalText = finalText
                    callback.onFinal(finalText)
                }
            }
            "error" -> {
                val code = payload.optString("code", "server_error")
                val message = payload.optString("message", "")
                callback.onError(code, message.ifBlank { null })
            }
            "end" -> {
                val reason = payload.optString("reason", if (stopRequested) "user_stop" else "disconnect")
                val textFromEnd = payload.optString("text", "")
                Log.i(TAG, "[onMessage/end] reason=$reason text=$textFromEnd hasFinalCallback=$hasFinalCallback")
                if (!hasFinalCallback && textFromEnd.isNotBlank()) {
                    hasFinalCallback = true
                    lastFinalText = textFromEnd
                    callback.onFinal(textFromEnd)
                }
                if (!hasEndedCallback) {
                    callback.onEnded(reason, if (textFromEnd.isBlank()) lastFinalText else textFromEnd)
                    hasEndedCallback = true
                }
                cleanupInternal()
            }
            else -> {
                // stats/warning/pong 等消息不需要前端 UI 介入，保留静默
            }
        }
    }

    private fun startRecordingLoop() {
        if (!isRunning || !isSocketReady || recordingThread != null) return

        val minBufferSize = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT)
        if (minBufferSize == AudioRecord.ERROR || minBufferSize == AudioRecord.ERROR_BAD_VALUE) {
            callback.onError("microphone_error", "invalid_buffer_size:$minBufferSize")
            if (!hasEndedCallback) {
                callback.onEnded("error", null)
                hasEndedCallback = true
            }
            cleanupInternal()
            return
        }

        val bufferSize = (minBufferSize * 2).coerceAtLeast(3200)
        val record = try {
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_COMMUNICATION,  // 启用硬件级 AEC + 噪声抑制
                SAMPLE_RATE,
                CHANNEL_CONFIG,
                AUDIO_FORMAT,
                bufferSize
            )
        } catch (e: SecurityException) {
            DebugLog.e(TAG, "permission_denied: ${e.message}", e)
            callback.onError("permission_denied", e.message)
            if (!hasEndedCallback) {
                callback.onEnded("error", null)
                hasEndedCallback = true
            }
            cleanupInternal()
            return
        } catch (e: Exception) {
            DebugLog.e(TAG, "microphone_error: ${e.message}", e)
            callback.onError("microphone_error", e.message)
            if (!hasEndedCallback) {
                callback.onEnded("error", null)
                hasEndedCallback = true
            }
            cleanupInternal()
            return
        }

        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            callback.onError("microphone_error", "record_not_initialized")
            if (!hasEndedCallback) {
                callback.onEnded("error", null)
                hasEndedCallback = true
            }
            cleanupInternal()
            return
        }

        // 软件层回声消除 + 噪声抑制（硬件不支持时的补充）
        if (AcousticEchoCanceler.isAvailable()) {
            AcousticEchoCanceler.create(record.audioSessionId)?.enabled = true
        }
        if (NoiseSuppressor.isAvailable()) {
            NoiseSuppressor.create(record.audioSessionId)?.enabled = true
        }

        audioRecord = record
        recordingThread = thread(start = true, name = "BackendVoiceRecordThread") {
            val readBuffer = ByteArray(bufferSize)
            try {
                record.startRecording()
                while (isRunning && isSocketReady && !stopRequested) {
                    val readBytes = record.read(readBuffer, 0, readBuffer.size)
                    if (readBytes == 0) {
                        // 设备偶发无数据帧时避免空转占满 CPU
                        Thread.sleep(12)
                        continue
                    }
                    if (readBytes < 0) {
                        // stopRequested 时是由 stop() 主动调用 audioRecord.stop() 导致 read() 返回负数，
                        // 属于正常停止路径，不能在此关闭 WebSocket，需等待服务端返回转写结果。
                        if (!stopRequested) {
                            callback.onError("microphone_error", "audio_read_failed:$readBytes")
                            if (!hasEndedCallback) {
                                callback.onEnded("error", lastFinalText)
                                hasEndedCallback = true
                            }
                            cleanupInternal()
                        }
                        break
                    }

                    val packet = ByteBuffer.allocate(4 + readBytes).order(ByteOrder.LITTLE_ENDIAN)
                    packet.putInt(seq)
                    packet.put(readBuffer, 0, readBytes)
                    val sent = ws?.send(packet.array().copyOf(packet.position()).toByteString()) ?: false
                    if (!sent) {
                        // stopRequested 时发送失败（WebSocket 正在关闭中）属于预期行为，
                        // 直接退出循环，由服务端响应或兜底超时处理后续状态。
                        if (!stopRequested) {
                            callback.onError("network_error", "websocket_send_failed")
                            if (!hasEndedCallback) {
                                callback.onEnded("disconnect", lastFinalText)
                                hasEndedCallback = true
                            }
                            cleanupInternal()
                        }
                        break
                    }
                    seq += 1
                }
            } catch (e: SecurityException) {
                DebugLog.e(TAG, "recording permission_denied: ${e.message}", e)
                callback.onError("permission_denied", e.message)
            } catch (e: Exception) {
                DebugLog.e(TAG, "recording microphone_error: ${e.message}", e)
                callback.onError("microphone_error", e.message)
            } finally {
                stopRecordingLoop()
            }
        }
    }

    private fun stopRecordingLoop() {
        try {
            audioRecord?.stop()
        } catch (e: Exception) {
            DebugLog.w(TAG, "audioRecord.stop failed: ${e.message}", e)
        }
        try {
            audioRecord?.release()
        } catch (e: Exception) {
            DebugLog.w(TAG, "audioRecord.release failed: ${e.message}", e)
        }
        audioRecord = null
        recordingThread = null
    }

    @Synchronized
    private fun cleanupInternal() {
        if (!isRunning && ws == null && audioRecord == null) return

        isRunning = false
        isSocketReady = false
        stopRequested = true

        stopRecordingLoop()

        try {
            ws?.close(1000, "client_end")
        } catch (e: Exception) {
            DebugLog.w(TAG, "ws.close failed: ${e.message}", e)
        }
        ws = null
    }

    private fun handleSocketClosed() {
        if (!isRunning) return
        if (!hasEndedCallback) {
            callback.onEnded(if (stopRequested) "user_stop" else "disconnect", lastFinalText)
            hasEndedCallback = true
        }
        cleanupInternal()
    }
}
