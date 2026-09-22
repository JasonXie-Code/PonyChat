package top.ponychat.webview.ui.chat

import android.content.ClipData
import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/** Share original bytes from private cache; never insert into MediaStore. */
internal suspend fun createPreviewImageShareIntent(context: Context, imageUrl: String): Intent? =
    withContext(Dispatchers.IO) {
        val original = loadOriginalPreviewBytes(context, imageUrl) ?: return@withContext null
        if (original.bytes.isEmpty()) return@withContext null
        val directory = File(context.cacheDir, "shared-preview-images").apply { mkdirs() }
        // Keep recent shares available to receiving apps; discard only old private copies.
        val cutoff = System.currentTimeMillis() - 7L * 24 * 60 * 60 * 1000
        directory.listFiles()?.filter { it.isFile && it.lastModified() < cutoff }?.forEach { it.delete() }
        val file = File.createTempFile("PonyChat_", ".${original.extension}", directory)
        file.writeBytes(original.bytes)
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
        Intent(Intent.ACTION_SEND).apply {
            type = original.mimeType
            putExtra(Intent.EXTRA_STREAM, uri)
            clipData = ClipData.newRawUri("图片", uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }
