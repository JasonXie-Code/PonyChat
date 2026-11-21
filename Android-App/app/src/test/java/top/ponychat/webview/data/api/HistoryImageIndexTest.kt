package top.ponychat.webview.data.api

import org.junit.Assert.assertEquals
import org.junit.Test

class HistoryImageIndexTest {
    @Test fun preservesImageOrderAndDeduplicatesInlinePaths() {
        val local = "file:///data/user/0/top.ponychat.webview/files/chat_images/old.jpg"
        assertEquals(listOf(local, "/chat_images/tmp_second.jpg"), HistoryImageIndex.urls(
            "看这个 ![旧图]($local) 和 ![第二张](/chat_images/tmp_second.jpg)"))
    }

    @Test fun missingFileStillHasAnIndexAndOrdinaryLinksAreExcluded() {
        assertEquals(listOf("/chat_images/missing.jpg"), HistoryImageIndex.urls(
            "![外链](https://example.com/picture.jpg) /chat_images/missing.jpg"))
    }

    @Test fun plainTextIsNotAnImageAndImageCountIsBounded() {
        assertEquals(emptyList<String>(), HistoryImageIndex.urls("还记得那张图吗？"))
        assertEquals(4, HistoryImageIndex.urls((1..8).joinToString(" ") { "/chat_images/$it.jpg" }).size)
    }
}
