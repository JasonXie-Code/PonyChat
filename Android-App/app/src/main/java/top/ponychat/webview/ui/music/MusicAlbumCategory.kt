package top.ponychat.webview.ui.music

internal enum class MusicAlbumCategory(val label: String) {
    ALL("全部专辑"),
    PONY("小马宝莉"),
    EQUESTRIA_GIRLS("小马国女孩"),
    PONY_TOWN("Pony Town"),
    HIGHEST_TOWER("4EverfreeBrony"),
    SHADY_VOX("ShadyVox"),
    DAVID_LARSEN("David Larsen");

    fun matches(album: MusicAlbum): Boolean = this == ALL || this == forAlbum(album.id)

    companion object {
        // Use the same grouping rules as the music site's album browser.
        fun forAlbum(id: String) = when {
            id.startsWith("equestria-girls") -> EQUESTRIA_GIRLS
            id.startsWith("soundtracks-pony-town-") -> PONY_TOWN
            id == "4everfreebrony-the-highest-tower" -> HIGHEST_TOWER
            id == "shadyvox-dont-mine-at-night" -> SHADY_VOX
            id == "david-larsen-double-rainboom" -> DAVID_LARSEN
            else -> PONY
        }
    }
}
