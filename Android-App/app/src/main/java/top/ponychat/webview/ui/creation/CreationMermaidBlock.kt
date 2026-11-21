package top.ponychat.webview.ui.creation

import android.annotation.SuppressLint
import android.graphics.Color
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import org.json.JSONObject
import java.io.ByteArrayInputStream

/** Local Mermaid runtime; diagram text never becomes executable HTML or a remote request. */
@SuppressLint("SetJavaScriptEnabled")
@Composable
internal fun CreationMermaidBlock(source: String) {
    val dark = MaterialTheme.colorScheme.surface.luminance() < .5f
    var height by remember(source, dark) { mutableIntStateOf(260) }
    var failed by remember(source, dark) { mutableStateOf(false) }
    CreationCard(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Text("流程图", Modifier.padding(12.dp), style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        AndroidView(modifier = Modifier.fillMaxWidth().height(if (failed) 0.dp else height.dp),
            onRelease = { it.removeJavascriptInterface("DiagramResult"); it.destroy() },
            factory = { context ->
                WebView(context).apply {
                    contentDescription = "Mermaid 流程图"
                    setBackgroundColor(Color.TRANSPARENT)
                    settings.apply {
                        javaScriptEnabled = true
                        allowFileAccess = false
                        allowContentAccess = false
                        blockNetworkLoads = true
                        setSupportZoom(true)
                        builtInZoomControls = true
                        displayZoomControls = false
                        useWideViewPort = true
                    }
                    setOnTouchListener { view, event ->
                        if (event.actionMasked == android.view.MotionEvent.ACTION_MOVE)
                            view.parent?.requestDisallowInterceptTouchEvent(true)
                        false
                    }
                }
            }, update = { view ->
                val identity = source to dark
                if (view.tag != identity) {
                    view.tag = identity
                    view.removeJavascriptInterface("DiagramResult")
                    view.addJavascriptInterface(object {
                        @JavascriptInterface fun complete(cssHeight: Int, success: Boolean) {
                            view.post {
                                if (view.tag == identity) {
                                    height = cssHeight.coerceIn(160, 480)
                                    failed = !success
                                }
                            }
                        }
                    }, "DiagramResult")
                    view.webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(webView: WebView, request: WebResourceRequest) = true
                        override fun shouldInterceptRequest(webView: WebView, request: WebResourceRequest): WebResourceResponse {
                            val uri = request.url
                            if (uri.scheme == "https" && uri.host == "appassets.androidplatform.net" &&
                                uri.path == "/mermaid/mermaid.min.js") {
                                return WebResourceResponse("application/javascript", "UTF-8",
                                    webView.context.assets.open("mermaid/mermaid.min.js"))
                            }
                            return WebResourceResponse("text/plain", "UTF-8", ByteArrayInputStream(ByteArray(0)))
                        }
                        override fun onPageFinished(webView: WebView, url: String) {
                            if (webView.tag == identity)
                                webView.evaluateJavascript("renderDiagram(${JSONObject.quote(source)}, $dark)", null)
                        }
                    }
                    val html = view.context.assets.open("mermaid/diagram.html").bufferedReader().use { it.readText() }
                    view.loadDataWithBaseURL("https://appassets.androidplatform.net/mermaid/", html, "text/html", "UTF-8", null)
                }
            })
        if (failed) Text("流程图语法无法解析，已保留原始内容。", Modifier.padding(12.dp),
            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    if (failed) CreationCodeBlock(source, "mermaid")
}
