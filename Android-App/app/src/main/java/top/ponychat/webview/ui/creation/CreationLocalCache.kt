package top.ponychat.webview.ui.creation

import android.util.AtomicFile
import com.google.gson.Gson
import top.ponychat.webview.data.prefs.AppPreferences
import java.io.File
import java.security.MessageDigest

/** Account-scoped durable snapshots, separate from normal chat and never used as server authority. */
internal class CreationLocalCache(private val prefs: AppPreferences) {
    private val gson = Gson()
    private val account = prefs.username
    private fun file(key: String): AtomicFile {
        val owner = MessageDigest.getInstance("SHA-256").digest(account.toByteArray()).joinToString("") { "%02x".format(it) }
        val name = MessageDigest.getInstance("SHA-256").digest(key.toByteArray()).joinToString("") { "%02x".format(it) }
        return AtomicFile(File(prefs.applicationContext.filesDir, "creation-cache/$owner/$name.json"))
    }
    @Synchronized private fun write(key: String, value: Any) {
        val target = file(key)
        target.baseFile.parentFile?.mkdirs()
        var stream: java.io.FileOutputStream? = null
        try {
            stream = target.startWrite(); stream.write(gson.toJson(value).toByteArray()); target.finishWrite(stream)
        } catch (_: Exception) { stream?.let(target::failWrite) }
    }
    @Synchronized private fun read(key: String): String? = runCatching { file(key).openRead().bufferedReader().use { it.readText() } }.getOrNull()
    fun session(id: String): CreationSession? = runCatching { gson.fromJson(read("session:$id"), CreationSession::class.java) }.getOrNull()
    fun history(character: String): List<CreationHistory> = runCatching {
        gson.fromJson(read("history:$character"), Array<CreationHistory>::class.java)?.toList().orEmpty()
    }.getOrDefault(emptyList())
    fun save(session: CreationSession) = write("session:${session.id}", session.copy(busy = false))
    fun saveHistory(character: String, history: List<CreationHistory>) = write("history:$character", history)
    @Synchronized fun remove(id: String) { file("session:$id").delete() }
}
