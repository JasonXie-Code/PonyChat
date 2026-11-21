package top.ponychat.webview.data.api

import android.content.Context
import android.content.ContextWrapper
import android.security.NetworkSecurityPolicy
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.junit.Assert.*
import org.junit.Test
import top.ponychat.webview.data.prefs.AppPreferences
import java.net.InetAddress
import java.security.KeyStore
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLException
import javax.net.ssl.SSLServerSocket
import javax.net.ssl.SSLSocket

class TlsTransportInstrumentedTest {
    @Test fun productionHttpsWorksForApiChatAndVoiceClients() = runBlocking {
        val url = AppPreferences.DEFAULT_WAN_URL
        assertEquals("https://39.101.74.217", url)
        val clients = listOf(NetworkClient.okHttpClient, NetworkClient.chatJsonResponseHttpClient,
            NetworkClient.createTrustAllClient())
        for (client in clients) {
            assertFalse(client.followSslRedirects)
            client.newCall(Request.Builder().url("$url/api/health").build()).execute().use {
                assertEquals(200, it.code)
                assertNotNull(it.handshake)
                assertTrue(it.body!!.string().contains("running"))
            }
        }
        assertTrue(NetworkClient.createDirectApiService(url, 15000, 20000).getStatus().isSuccessful)
    }

    @Test fun productionIpRejectsCleartextAndLegacyPreferenceMigrates() {
        assertFalse(NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted("39.101.74.217"))
        val real = InstrumentationRegistry.getInstrumentation().targetContext
        val prefix = "tls_test_${System.nanoTime()}_"
        val context = object : ContextWrapper(real) {
            override fun getApplicationContext(): Context = this
            override fun getSharedPreferences(name: String, mode: Int) =
                super.getSharedPreferences(prefix + name, mode)
        }
        val prefs = AppPreferences(context)
        prefs.debugMode = true
        prefs.activeApiBase = "http://39.101.74.217:80"
        assertEquals("https://39.101.74.217", prefs.effectiveApiBase())
    }

    @Test fun historicalHttpMediaOriginUpgradesBeforeNetworkAccess() {
        NetworkClient.createTrustAllClient().newCall(Request.Builder()
            .url("http://39.101.74.217:80/api/health").build()).execute().use {
            assertEquals(200, it.code)
            assertEquals("https", it.request.url.scheme)
            assertNotNull(it.handshake)
        }
    }

    @Test fun untrustedCertificateIsRejectedByEverySharedClient() {
        val store = KeyStore.getInstance("PKCS12")
        InstrumentationRegistry.getInstrumentation().context.assets.open("untrusted-test.p12").use {
            store.load(it, "test-only-ponychat".toCharArray())
        }
        val km = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm())
        km.init(store, "test-only-ponychat".toCharArray())
        val tls = SSLContext.getInstance("TLS").apply { init(km.keyManagers, null, null) }
        val clients = listOf(NetworkClient.okHttpClient, NetworkClient.chatJsonResponseHttpClient,
            NetworkClient.createTrustAllClient())
        for (client in clients) {
            (tls.serverSocketFactory.createServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))
                as SSLServerSocket).use { server ->
                server.soTimeout = 10000
                val worker = Thread {
                    runCatching { (server.accept() as SSLSocket).use { it.startHandshake() } }
                }.apply { isDaemon = true; start() }
                val failure = runCatching {
                    client.newCall(Request.Builder().url("https://127.0.0.1:${server.localPort}/").build())
                        .execute().use { fail("Untrusted certificate was accepted") }
                }.exceptionOrNull()
                assertTrue("Expected TLS rejection, got $failure", failure is SSLException)
                worker.join(10000)
            }
        }
    }

    @Test fun certificateHostnameMustMatch() {
        val client = NetworkClient.createTrustAllClient()
        (client.sslSocketFactory.createSocket("39.101.74.217", 443) as SSLSocket).use { socket ->
            socket.soTimeout = 15000
            socket.startHandshake()
            assertTrue(client.hostnameVerifier.verify("39.101.74.217", socket.session))
            assertFalse(client.hostnameVerifier.verify("wrong.example", socket.session))
        }
    }

    @Test fun wssExchangesHeartbeatOverVerifiedTls() {
        val done = CountDownLatch(1)
        val error = AtomicReference<Throwable?>()
        val socket = NetworkClient.createTrustAllClient().newWebSocket(
            Request.Builder().url("wss://39.101.74.217/ws/heartbeat").build(),
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    if (response.handshake == null) {
                        error.set(AssertionError("Missing TLS handshake")); done.countDown()
                    } else webSocket.send("{\"type\":\"init\",\"username\":\"System\"}")
                }
                override fun onMessage(webSocket: WebSocket, text: String) {
                    if (text.contains("connected")) webSocket.send("{\"type\":\"ping\"}")
                    if (text.contains("pong")) done.countDown()
                }
                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    error.set(t); done.countDown()
                }
            })
        try {
            assertTrue("No WSS pong", done.await(30, TimeUnit.SECONDS))
            error.get()?.let { throw AssertionError("WSS failed", it) }
        } finally { socket.close(1000, "TLS acceptance finished") }
    }
}
