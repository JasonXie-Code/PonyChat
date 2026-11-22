package top.ponychat.webview.ui.music

import com.google.gson.Gson
import org.junit.Assert.assertEquals
import org.junit.Test

class MusicLyricsStatusTest {
    private val gson = Gson()

    @Test
    fun instrumentalVersionsUseThePureMusicNoticeUnlessLyricsAreAvailable() {
        fun status(fields: String) =
            gson.fromJson("""{"albumId":"best-gift-ever-2018",$fields}""", MusicSong::class.java).resolvedLyricsStatus

        assertEquals(MusicLyricsStatus.INSTRUMENTAL, status(""" "lyricsStatus":"instrumental" """))
        assertEquals(MusicLyricsStatus.INSTRUMENTAL, status(""" "lyricsStatus":"excluded","instrumental":true """))
        assertEquals(MusicLyricsStatus.INSTRUMENTAL, status(""" "lyricsStatus":"missing","versionKind":"instrumental" """))
        assertEquals(MusicLyricsStatus.AVAILABLE, status(""" "lyricsStatus":"available","instrumental":true """))
        assertEquals(MusicLyricsStatus.MISSING, status(""" "lyricsStatus":"missing","versionKind":"original" """))
    }

    @Test
    fun ponyTownSoundtrackUsesTheInstrumentalNotice() {
        val track = gson.fromJson(
            """{"albumId":"soundtracks-pony-town-ponytown-beach-update","versionKind":"original","lyricsStatus":"missing"}""",
            MusicSong::class.java,
        )

        assertEquals(MusicLyricsStatus.INSTRUMENTAL, track.resolvedLyricsStatus)
    }

    @Test
    fun lyricResponseDistinguishesUnavailableLyricsFromPlayableCues() {
        fun status(json: String) = gson.fromJson(json, MusicLyrics::class.java).resolvedStatus

        assertEquals(MusicLyricsStatus.NO_VOCALS, status("""{"status":"no-vocals-detected","lines":[]}"""))
        assertEquals(MusicLyricsStatus.MISSING, status("""{"status":"available","lines":[]}"""))
        assertEquals(
            MusicLyricsStatus.AVAILABLE,
            status("""{"status":"available","lines":[{"start":0,"end":2,"en":"First line","zh":""}]}"""),
        )
    }
}
