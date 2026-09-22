package top.ponychat.webview.data.repo

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.Request
import okhttp3.OkHttpClient
import okhttp3.RequestBody.Companion.toRequestBody
import top.ponychat.webview.data.api.NetworkClient
import top.ponychat.webview.data.model.MessageAttachment
import top.ponychat.webview.data.prefs.AppPreferences
import top.ponychat.webview.ui.chat.rememberLocalChatImageRemote
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/** Save and verify on the phone before acknowledging deletion of server bytes. */
internal object WebImageReceiver {
    private val lock = Mutex()
    private val transferPath = Regex("/chat_images/tmp_[A-Za-z0-9_-]+\\.(jpg|gif|webp|png)")
    private const val maxBytes = 8L * 1024 * 1024
    private val client by lazy {
        NetworkClient.okHttpClient.newBuilder().cache(null)
            .followRedirects(false).followSslRedirects(false)
            .callTimeout(15, TimeUnit.SECONDS).build()
    }

    internal fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    internal fun supports(attachment: MessageAttachment): Boolean =
        attachment.type == "image" &&
            attachment.metadata?.get("source") in setOf("web_search", "history_repeat")

    suspend fun receive(prefs: AppPreferences, attachment: MessageAttachment,
                        httpClient: OkHttpClient = client): MessageAttachment {
        if (!supports(attachment)) return attachment
        val url = attachment.url?.takeIf { transferPath.matches(it) } ?: return attachment
        val digest = (attachment.metadata?.get("sha256") as? String)
            ?.takeIf { it.matches(Regex("[a-f0-9]{64}")) } ?: return attachment
        val username = prefs.username.takeIf { it.isNotBlank() } ?: return attachment
        return withContext(Dispatchers.IO) {
            lock.withLock {
                try {
                    val context = prefs.applicationContext
                    val directory = File(context.filesDir, "chat_images").also { it.mkdirs() }
                    val key = sha256("$username\n$url".toByteArray())
                    val extension = url.substringAfterLast('.')
                    val file = File(directory, "web_$key.$extension")
                    if (!file.isFile || file.length() > maxBytes || sha256(file.readBytes()) != digest) {
                        val request = Request.Builder().url(prefs.effectiveApiBase().trimEnd('/') + url).get().build()
                        httpClient.newCall(request).execute().use { response ->
                            if (!response.isSuccessful) return@withLock attachment
                            val body = response.body ?: return@withLock attachment
                            if (body.contentLength() > maxBytes) return@withLock attachment
                            val temporary = File(directory, "web_$key.part")
                            try {
                                body.byteStream().use { input ->
                                    FileOutputStream(temporary).use { output ->
                                        val buffer = ByteArray(65536)
                                        var total = 0L
                                        while (true) {
                                            val count = input.read(buffer)
                                            if (count < 0) break
                                            total += count
                                            check(total <= maxBytes) { "Image exceeds transfer limit" }
                                            output.write(buffer, 0, count)
                                        }
                                        output.fd.sync()
                                    }
                                }
                                check(sha256(temporary.readBytes()) == digest) { "Incomplete image transfer" }
                                check(temporary.renameTo(file)) { "Image could not be saved" }
                            } finally {
                                temporary.delete()
                            }
                        }
                    }
                    if (prefs.username != username) return@withLock attachment
                    // The persisted URL mapping survives a process death between
                    // receipt and chat-message caching. History can still find it.
                    val localUrl = android.net.Uri.fromFile(file).toString()
                    check(rememberLocalChatImageRemote(context, localUrl, url, synchronous = true))
                    acknowledge(prefs, username, url, httpClient)
                    attachment // Keep the shared reference; UI resolves it locally.
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (failure: Exception) {
                    top.ponychat.webview.util.DebugLog.w("WebImageReceiver",
                        "Image transfer or receipt failed (${failure.javaClass.simpleName})")
                    attachment // No deletion receipt on failed save or verification.
                }
            }
        }
    }

    private suspend fun acknowledge(prefs: AppPreferences, username: String, url: String, httpClient: OkHttpClient) {
        repeat(3) { attempt ->
            if (prefs.username != username) return
            try {
                val path = "/api/chat_images/${url.substringAfterLast('/')}/received"
                val request = Request.Builder().url(prefs.effectiveApiBase().trimEnd('/') + path)
                    .post(ByteArray(0).toRequestBody()).build()
                httpClient.newCall(request).execute().use { if (it.isSuccessful) return }
            } catch (_: java.io.IOException) {
                // Retry only the receipt: the saved phone file remains valid.
            }
            if (attempt < 2) delay(250L * (attempt + 1))
        }
    }
}
