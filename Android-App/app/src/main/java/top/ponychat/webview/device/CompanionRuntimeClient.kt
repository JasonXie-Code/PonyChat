package top.ponychat.webview.device

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.os.IBinder
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import top.ponychat.companion.ipc.ICompanionRuntime
import top.ponychat.webview.data.prefs.AppPreferences

sealed interface CompanionRuntimeState {
    data object Detecting : CompanionRuntimeState
    data object Unavailable : CompanionRuntimeState
    data object Untrusted : CompanionRuntimeState
    data object NotProvisioned : CompanionRuntimeState
    data class Ready(val runtimeVersion: String, val protocolVersion: Int) : CompanionRuntimeState
    data class Incompatible(val protocolVersion: Int) : CompanionRuntimeState
    data class Error(val message: String) : CompanionRuntimeState
}

class CompanionRuntimeClient(context: Context) {
    private val appContext = context.applicationContext
    private val _state = MutableStateFlow<CompanionRuntimeState>(CompanionRuntimeState.Detecting)
    val state: StateFlow<CompanionRuntimeState> = _state.asStateFlow()
    private var bound = false
    private var overlayBound = false
    private var runtime: ICompanionRuntime? = null
    private var desiredOverlayVisible = false
    private val preferences = AppPreferences(appContext)
    private var observingPreferences = false
    private val preferenceListener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key == AppPreferences.KEY_LAST_CHARACTER_ID) {
            runtime?.let(::syncSession)
        }
    }

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
            val runtime = ICompanionRuntime.Stub.asInterface(service)
            this@CompanionRuntimeClient.runtime = runtime
            _state.value = runCatching {
                val protocol = runtime.protocolVersion
                when {
                    protocol != SUPPORTED_PROTOCOL_VERSION -> CompanionRuntimeState.Incompatible(protocol)
                    !runtime.isDeviceProvisioned -> CompanionRuntimeState.NotProvisioned
                    else -> {
                        runtime.setOverlayVisible(desiredOverlayVisible)
                        syncSession(runtime)
                        CompanionRuntimeState.Ready(runtime.runtimeVersion, protocol)
                    }
                }
            }.getOrElse { CompanionRuntimeState.Error(it.message.orEmpty()) }
            bindOverlayIfNeeded()
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            bound = false
            runtime = null
            _state.value = CompanionRuntimeState.Unavailable
        }

        override fun onBindingDied(name: ComponentName?) {
            bound = false
            runtime = null
            _state.value = CompanionRuntimeState.Unavailable
        }

        override fun onNullBinding(name: ComponentName?) {
            bound = false
            runtime = null
            _state.value = CompanionRuntimeState.Error("runtime_null_binding")
        }
    }

    private val overlayConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) = Unit
        override fun onServiceDisconnected(name: ComponentName?) { overlayBound = false }
        override fun onBindingDied(name: ComponentName?) { overlayBound = false }
        override fun onNullBinding(name: ComponentName?) { overlayBound = false }
    }

    fun connect() {
        if (!observingPreferences) {
            preferences.registerOnChangeListener(preferenceListener)
            observingPreferences = true
        }
        if (bound) {
            runtime?.let(::syncSession)
            bindOverlayIfNeeded()
            return
        }
        if (_state.value !is CompanionRuntimeState.Ready) {
            _state.value = CompanionRuntimeState.Detecting
        }
        if (!runtimePackageInstalled()) {
            _state.value = CompanionRuntimeState.Unavailable
            return
        }
        if (appContext.packageManager.checkSignatures(
                appContext.packageName,
                RUNTIME_PACKAGE,
            ) != PackageManager.SIGNATURE_MATCH
        ) {
            _state.value = CompanionRuntimeState.Untrusted
            return
        }
        val intent = Intent().setComponent(ComponentName(RUNTIME_PACKAGE, RUNTIME_SERVICE))
        try {
            bound = appContext.bindService(intent, connection, Context.BIND_AUTO_CREATE)
            if (!bound) _state.value = CompanionRuntimeState.Unavailable
        } catch (error: Exception) {
            bound = false
            _state.value = CompanionRuntimeState.Error(error.message.orEmpty())
        }
        bindOverlayIfNeeded()
    }

    fun disconnect() {
        if (bound) runCatching { appContext.unbindService(connection) }
        if (overlayBound) runCatching { appContext.unbindService(overlayConnection) }
        bound = false
        overlayBound = false
        runtime = null
        if (observingPreferences) {
            preferences.unregisterOnChangeListener(preferenceListener)
            observingPreferences = false
        }
    }

    fun setOverlayVisible(visible: Boolean) {
        desiredOverlayVisible = visible
        if (!visible || _state.value is CompanionRuntimeState.Ready) {
            runCatching { runtime?.setOverlayVisible(visible) }
        }
        if (visible) {
            bindOverlayIfNeeded()
        } else if (overlayBound) {
            runCatching { appContext.unbindService(overlayConnection) }
            overlayBound = false
        }
    }

    fun diagnosticSnapshot(): String? =
        runCatching { runtime?.diagnosticSnapshot }.getOrNull()

    fun repairSystemProvisioning(): String? =
        runCatching { runtime?.repairSystemProvisioning() }.getOrNull()

    private fun bindOverlayIfNeeded() {
        if (overlayBound || !desiredOverlayVisible || _state.value !is CompanionRuntimeState.Ready) return
        overlayBound = runCatching {
            appContext.bindService(
                Intent().setComponent(ComponentName(RUNTIME_PACKAGE, OVERLAY_SERVICE)),
                overlayConnection,
                Context.BIND_AUTO_CREATE,
            )
        }.getOrDefault(false)
    }

    private fun syncSession(runtime: ICompanionRuntime) {
        runtime.configureSession(
            preferences.activeApiBase,
            preferences.username,
            preferences.authToken,
            preferences.lastCharacterId,
            "canonical",
        )
    }

    private fun runtimePackageInstalled(): Boolean = try {
        @Suppress("DEPRECATION")
        appContext.packageManager.getPackageInfo(RUNTIME_PACKAGE, 0)
        true
    } catch (_: PackageManager.NameNotFoundException) {
        false
    }

    companion object {
        const val SUPPORTED_PROTOCOL_VERSION = 4
        const val RUNTIME_PACKAGE = "top.ponychat.companion"
        const val RUNTIME_SERVICE =
            "top.ponychat.companion.ipc.CompanionRuntimeCapabilityService"
        const val OVERLAY_SERVICE =
            "top.ponychat.companion.overlay.AgentStatusOverlayService"
    }
}

fun CompanionRuntimeState.statusText(): String = when (this) {
    CompanionRuntimeState.Detecting -> "正在连接 Companion Runtime"
    CompanionRuntimeState.Unavailable -> "Companion Runtime 未连接"
    CompanionRuntimeState.Untrusted -> "Companion Runtime 签名不可信"
    CompanionRuntimeState.NotProvisioned -> "Companion Runtime 尚未完成设备预装"
    is CompanionRuntimeState.Ready -> "Companion Runtime ${runtimeVersion.ifBlank { "已连接" }}"
    is CompanionRuntimeState.Incompatible -> "Companion Runtime 协议不兼容（$protocolVersion）"
    is CompanionRuntimeState.Error -> "Companion Runtime 连接异常"
}

fun shouldUseDeviceExperience(
    enteredFromDeviceHome: Boolean,
    deviceHomeEnabled: Boolean = false,
): Boolean = enteredFromDeviceHome || deviceHomeEnabled
