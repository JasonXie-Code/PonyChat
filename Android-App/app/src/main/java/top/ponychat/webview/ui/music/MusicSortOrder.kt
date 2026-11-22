package top.ponychat.webview.ui.music

import java.text.Collator

private val releaseDateFormat = Regex("[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?")

// The music site's album browser groups the catalog, then orders albums within each group.
private val websiteAlbumOrder = compareBy<MusicAlbum> { MusicAlbumCategory.forAlbum(it.id) }
    .thenBy { album ->
        when {
            album.id.startsWith("season-") -> 0
            album.id == "credits" -> 1
            else -> 2
        }
    }
    .thenBy { album ->
        if (MusicAlbumCategory.PONY_TOWN.matches(album)) album.releaseDate.orEmpty().ifEmpty { "9999" }
        else ""
    }
    .thenBy(MusicAlbum::id)

internal enum class MusicSortOrder(val label: String) {
    DEFAULT("默认顺序"),
    NAME_ASC("名称正序"),
    NAME_DESC("名称倒序"),
    RELEASE_ASC("发布时间正序"),
    RELEASE_DESC("发布时间倒序");

    fun sortCatalogAlbums(albums: List<MusicAlbum>): List<MusicAlbum> =
        if (this == DEFAULT) albums.sortedWith(websiteAlbumOrder)
        else sort(albums, MusicAlbum::title, MusicAlbum::releaseDate)

    fun <T> sort(entries: List<T>, title: (T) -> String, releaseDate: (T) -> String?): List<T> {
        return when (this) {
            DEFAULT -> entries
            NAME_ASC, NAME_DESC -> {
                val collator = Collator.getInstance()
                val byTitle = Comparator<T> { left, right -> collator.compare(title(left), title(right)) }
                entries.sortedWith(if (this == NAME_DESC) byTitle.reversed() else byTitle)
            }
            RELEASE_ASC, RELEASE_DESC -> {
                val dateOrder = if (this == RELEASE_ASC) naturalOrder<String>() else reverseOrder<String>()
                entries.sortedWith(compareBy<T, String?>(nullsLast(dateOrder)) { entry ->
                    releaseDate(entry)?.trim()?.takeIf(releaseDateFormat::matches)
                })
            }
        }
    }
}
