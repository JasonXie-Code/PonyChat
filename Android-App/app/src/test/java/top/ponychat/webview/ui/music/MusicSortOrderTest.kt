package top.ponychat.webview.ui.music

import org.junit.Assert.assertEquals
import org.junit.Test

class MusicSortOrderTest {
    @Test
    fun defaultCatalogOrderMatchesMusicSiteGroups() {
        val albums = listOf(
            "best-gift-ever-2018" to null,
            "credits" to null,
            "equestria-girls__2013-equestria-girls" to null,
            "season-02-2011" to null,
            "season-01-2010" to null,
            "soundtracks-pony-town-a-undated" to null,
            "soundtracks-pony-town-b-later" to "2023-01-05",
            "soundtracks-pony-town-z-earlier" to "2016-12-17",
            "4everfreebrony-the-highest-tower" to "2019-02-25",
        ).map { (id, date) -> MusicAlbum(id, id, null, 1, date) }

        assertEquals(
            listOf(
                "season-01-2010", "season-02-2011", "credits", "best-gift-ever-2018",
                "equestria-girls__2013-equestria-girls", "soundtracks-pony-town-z-earlier",
                "soundtracks-pony-town-b-later", "soundtracks-pony-town-a-undated",
                "4everfreebrony-the-highest-tower",
            ),
            MusicSortOrder.DEFAULT.sortCatalogAlbums(albums).map(MusicAlbum::id),
        )
        assertEquals(
            MusicSortOrder.RELEASE_DESC.sort(albums, MusicAlbum::title, MusicAlbum::releaseDate),
            MusicSortOrder.RELEASE_DESC.sortCatalogAlbums(albums),
        )
    }

    @Test
    fun releaseOrderKeepsUndatedEntriesLastInBothDirections() {
        val entries = listOf(
            "unknown" to null,
            "new" to "2024-12-21",
            "early" to "2017-08-28",
            "same day" to "2024-12-21",
            "blank date" to " ",
        )

        assertEquals(
            listOf("early", "new", "same day", "unknown", "blank date"),
            MusicSortOrder.RELEASE_ASC.sort(entries, { it.first }, { it.second }).map { it.first },
        )
        assertEquals(
            listOf("new", "same day", "early", "unknown", "blank date"),
            MusicSortOrder.RELEASE_DESC.sort(entries, { it.first }, { it.second }).map { it.first },
        )
    }
}
