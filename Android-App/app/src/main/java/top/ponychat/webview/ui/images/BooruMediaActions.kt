package top.ponychat.webview.ui.images

import android.app.DownloadManager
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Environment
import android.webkit.MimeTypeMap
import android.widget.Toast
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.util.concurrent.TimeUnit
import top.ponychat.webview.data.model.BooruImage

private val shareClient = OkHttpClient.Builder().callTimeout(90, TimeUnit.SECONDS).build()
private fun extension(image: BooruImage) = Uri.parse(image.imageUrl).lastPathSegment
    ?.substringAfterLast('.', "")?.lowercase()?.takeIf { it in setOf("jpg", "jpeg", "png", "gif", "webp", "webm", "mp4") }
    ?: if (image.video) "webm" else "jpg"
private fun mime(image: BooruImage) = MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension(image))
    ?: if (image.video) "video/webm" else "image/jpeg"

internal fun downloadBooruMedia(context: Context, image: BooruImage) {
    runCatching {
        val request = DownloadManager.Request(Uri.parse(image.imageUrl))
            .setTitle("PonyChat ${image.id}")
            .setMimeType(mime(image))
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS,
                "PonyChat_${image.id.replace(':', '_')}_${System.currentTimeMillis()}.${extension(image)}")
        (context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager).enqueue(request)
    }.onSuccess { Toast.makeText(context, "已加入下载", Toast.LENGTH_SHORT).show() }
        .onFailure { Toast.makeText(context, "无法开始下载", Toast.LENGTH_SHORT).show() }
}

internal suspend fun shareBooruMedia(context: Context, image: BooruImage) {
    try {
        val intent = withContext(Dispatchers.IO) {
            val directory = File(context.cacheDir, "booru-shares").apply { mkdirs() }
            val cutoff = System.currentTimeMillis() - TimeUnit.DAYS.toMillis(1)
            directory.listFiles()?.filter { it.isFile && it.lastModified() < cutoff }?.forEach { it.delete() }
            val file = File.createTempFile("PonyChat_", ".${extension(image)}", directory)
            try {
                shareClient.newCall(Request.Builder().url(image.imageUrl).build()).execute().use { response ->
                    check(response.isSuccessful) { "下载失败" }
                    val body = checkNotNull(response.body)
                    body.byteStream().use { input -> file.outputStream().use { output ->
                        val buffer = ByteArray(32768)
                        var total = 0L
                        while (true) {
                            val count = input.read(buffer)
                            if (count < 0) break
                            total += count
                            check(total <= 128L * 1024 * 1024) { "文件过大" }
                            output.write(buffer, 0, count)
                        }
                        check(total > 0)
                    } }
                }
                val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
                Intent(Intent.ACTION_SEND).apply {
                    type = mime(image)
                    putExtra(Intent.EXTRA_STREAM, uri)
                    clipData = ClipData.newRawUri("媒体", uri)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
            } catch (error: Exception) { file.delete(); throw error }
        }
        context.startActivity(Intent.createChooser(intent, "分享"))
    } catch (error: kotlinx.coroutines.CancellationException) { throw error }
      catch (_: Exception) { Toast.makeText(context, "分享失败，请稍后重试", Toast.LENGTH_SHORT).show() }
}
