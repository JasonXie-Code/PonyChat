package top.ponychat.webview.ui.music

import androidx.annotation.Keep
import com.google.gson.Gson
import top.ponychat.webview.data.prefs.AppPreferences

@Keep
internal data class MusicResumeSnapshot(
    val owner: String,
    val revision: Long,
    val songId: String,
    val songIds: List<String>,
    val positionMs: Long,
    val savedAtMs: Long,
    val shuffleIds: List<String>,
    val repeat: Int,
)

internal val MusicAccount.resumeOwner get() = "$base\n$username"

private val resumeGson = Gson()

internal fun AppPreferences.readMusicResume(): MusicResumeSnapshot? =
    runCatching { resumeGson.fromJson(musicResumeSnapshot, MusicResumeSnapshot::class.java) }.getOrNull()

internal fun AppPreferences.writeMusicResume(snapshot: MusicResumeSnapshot?) {
    musicResumeSnapshot = snapshot?.let(resumeGson::toJson)
}
