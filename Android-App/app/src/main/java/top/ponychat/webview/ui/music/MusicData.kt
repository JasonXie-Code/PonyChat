package top.ponychat.webview.ui.music

import android.net.Uri
import androidx.annotation.Keep
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Query
import top.ponychat.webview.BuildConfig
import top.ponychat.webview.data.prefs.AppPreferences
import java.util.concurrent.TimeUnit

@Keep
internal data class MusicAlbum(
    val id: String,
    val title: String,
    val cover: String?,
    val trackCount: Int,
    val releaseDate: String? = null,
)

@Keep
internal data class MusicSong(
    val id: String,
    val title: String,
    val albumId: String,
    val src: String?,
    val alias: String?,
    val artist: String?,
    val track: Int?,
    val episode: String?,
    val releaseKind: String?,
    val showByDefault: Boolean?,
    val supersededBy: String?,
    val lyricsStatus: String?,
    val duration: Double?,
    val releaseDate: String? = null,
) {
    val isDefault get() = supersededBy.isNullOrBlank() && (releaseKind == "official" || showByDefault == true)
}

@Keep
internal data class MusicCatalog(
    val albums: List<MusicAlbum> = emptyList(),
    val songs: List<MusicSong> = emptyList(),
) {
    val albumsById by lazy { albums.associateBy(MusicAlbum::id) }
    val songsById by lazy { songs.associateBy(MusicSong::id) }
}

@Keep
internal data class MusicSearchHit(val id: String, val lyricSnippet: String?)
@Keep
internal data class MusicSearch(val songs: List<MusicSearchHit> = emptyList())
@Keep
internal data class MusicLyrics(val lines: List<MusicLyric> = emptyList())
@Keep
internal data class MusicLyric(val start: Double, val end: Double, val en: String?, val zh: String?) {
    val startMs get() = (start * 1000).toLong()
    val originalText get() = en?.takeIf(String::isNotBlank) ?: zh.orEmpty()
}

@Keep
internal data class MyMusic(
    val favorites: List<String> = emptyList(),
    val favoriteAlbums: List<String> = emptyList(),
    val playlists: List<MusicPlaylist> = emptyList(),
    val history: List<MusicHistory> = emptyList(),
    val historyEnabled: Boolean = true,
    val historyRevision: Long = 0,
)

@Keep
internal data class MusicPlaylist(val id: String, val name: String, val songIds: List<String>)
@Keep
internal data class MusicHistory(val songId: String, val count: Int, val playedAtMs: Long, val positionMs: Long)
@Keep
internal data class MusicCommand(
    val action: String,
    val songId: String? = null,
    val albumId: String? = null,
    val enabled: Boolean? = null,
    val playlistId: String? = null,
    val name: String? = null,
    val direction: Int? = null,
    val playId: String? = null,
    val revision: Long? = null,
    val sequence: Long? = null,
    val positionMs: Long? = null,
)

internal object MusicSite {
    private val root = "https://music.ponychat.org/".toHttpUrl()
    val api: PublicMusicApi = Retrofit.Builder()
        .baseUrl(root)
        .client(OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS).build())
        .addConverterFactory(GsonConverterFactory.create())
        .build()
        .create(PublicMusicApi::class.java)

    fun mediaUri(path: String?): Uri? {
        if (path.isNullOrBlank()) return null
        val url = if (path.startsWith("/") && !path.startsWith("//")) {
            root.newBuilder().addPathSegments(path.drop(1)).build()
        } else {
            root.resolve(path) ?: return null
        }
        if (!url.isHttps || url.host !in setOf(root.host, "www.music.ponychat.org")) return null
        return Uri.parse(url.toString())
    }
}

internal interface PublicMusicApi {
    @GET("api/library")
    suspend fun catalog(): MusicCatalog

    @GET("api/search")
    suspend fun search(@Query("q") query: String, @Query("versions") versions: Boolean): MusicSearch

    @GET("api/lyrics")
    suspend fun lyrics(@Query("song") songId: String): MusicLyrics
}

internal data class MusicAccount(val username: String, val base: String, private val token: String) {
    val bearer get() = "Bearer $token"

    override fun toString() = "MusicAccount"

    companion object {
        fun current(prefs: AppPreferences): MusicAccount? {
            val username = prefs.username
            val token = prefs.authToken
            if (username.isBlank() || token.isBlank()) return null
            val base = prefs.effectiveApiBase().toHttpUrlOrNull() ?: return null
            if (base.host == "music.ponychat.org" || base.host == "www.music.ponychat.org") return null
            return MusicAccount(username, base.toString().trimEnd('/') + "/", token)
        }
    }
}

internal interface MyMusicApi {
    @GET("api/me/music")
    suspend fun load(@Header("Authorization") bearer: String): MyMusic

    @POST("api/me/music")
    suspend fun update(@Header("Authorization") bearer: String, @Body command: MusicCommand): MyMusic
}

internal data class MusicAccountState(val account: MusicAccount? = null, val library: MyMusic? = null)

internal object MusicAccountStore {
    private val client = OkHttpClient.Builder()
        .followRedirects(false)
        .retryOnConnectionFailure(false)
        .callTimeout(12, TimeUnit.SECONDS)
        .addInterceptor { chain ->
            chain.proceed(chain.request().newBuilder()
                .header("X-PonyChat-Client", "android")
                .header("X-App-Version", BuildConfig.VERSION_CODE.toString())
                .header("X-App-Version-Name", BuildConfig.VERSION_NAME)
                .build())
        }
        .build()
    private val mutex = Mutex()
    private val mutableState = MutableStateFlow(MusicAccountState())
    val state = mutableState.asStateFlow()
    private var api: Pair<String, MyMusicApi>? = null

    fun activate(account: MusicAccount?) {
        if (state.value.account != account) mutableState.value = MusicAccountState(account)
    }

    fun library(account: MusicAccount?): MyMusic? =
        state.value.takeIf { it.account == account }?.library

    suspend fun refresh(account: MusicAccount): MyMusic? = request(account) { it.load(account.bearer) }

    suspend fun update(account: MusicAccount, command: MusicCommand): MyMusic? =
        request(account) { it.update(account.bearer, command) }

    private suspend fun request(account: MusicAccount, call: suspend (MyMusicApi) -> MyMusic): MyMusic? =
        mutex.withLock {
            if (state.value.account != account) return@withLock null
            val service = api?.takeIf { it.first == account.base }?.second ?: Retrofit.Builder()
                .baseUrl(account.base)
                .client(client)
                .addConverterFactory(GsonConverterFactory.create())
                .build()
                .create(MyMusicApi::class.java)
                .also { api = account.base to it }
            val library = call(service)
            if (state.value.account != account) return@withLock null
            mutableState.value = MusicAccountState(account, library)
            library
        }
}
