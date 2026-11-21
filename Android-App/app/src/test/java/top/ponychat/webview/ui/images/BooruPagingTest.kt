package top.ponychat.webview.ui.images

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.mutableStateOf

class BooruPagingTest {
    @Test
    fun loadingCompletionReactivatesRememberedBoundaryCheck() {
        val loading = mutableStateOf(true)
        val more = mutableStateOf(true)
        val last = mutableStateOf(17)
        val total = mutableStateOf(18)
        val trigger = derivedStateOf {
            shouldLoadNextBooruPage(last.value, total.value, more.value, loading.value)
        }
        assertFalse(trigger.value)
        loading.value = false
        assertTrue(trigger.value)
        loading.value = true
        assertFalse(trigger.value)
        total.value = 36
        loading.value = false
        assertFalse(trigger.value)
        last.value = 33
        assertTrue(trigger.value)
        more.value = false
        assertFalse(trigger.value)
    }
    @Test
    fun loadsWhenScrollApproachesEnd() {
        assertFalse(shouldLoadNextBooruPage(10, 20, canLoadMore = true, isLoading = false))
        assertTrue(shouldLoadNextBooruPage(15, 20, canLoadMore = true, isLoading = false))
        assertTrue(shouldLoadNextBooruPage(19, 20, canLoadMore = true, isLoading = false))
    }

    @Test
    fun stopsWhileLoadingOrAfterLastPage() {
        assertFalse(shouldLoadNextBooruPage(19, 20, canLoadMore = true, isLoading = true))
        assertFalse(shouldLoadNextBooruPage(19, 20, canLoadMore = false, isLoading = false))
        assertFalse(shouldLoadNextBooruPage(-1, 0, canLoadMore = true, isLoading = false))
    }

    @Test
    fun staticImagesOpenPreviewAndVideosKeepTheirPlayer() {
        assertTrue(booruOpenTarget(video = false) == BooruOpenTarget.ImagePreview)
        assertTrue(booruOpenTarget(video = true) == BooruOpenTarget.VideoPlayer)
    }
}
