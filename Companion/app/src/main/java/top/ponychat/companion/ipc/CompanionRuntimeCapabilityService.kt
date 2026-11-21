package top.ponychat.companion.ipc

import android.app.Service
import android.content.Intent
import android.os.IBinder
import android.util.Log
import top.ponychat.companion.android.DeviceProvisioningPolicy
import top.ponychat.companion.overlay.AgentOverlayController
import top.ponychat.companion.reply.CompanionSession
import top.ponychat.companion.reply.CompanionSessionStore

/**
 * System-runtime capability endpoint.
 *
 * The manifest protects this service with a signature permission. Production devices additionally
 * provision Companion in a system partition. Debug installs and emulators are not devices.
 */
class CompanionRuntimeCapabilityService : Service() {
    private val binder = object : ICompanionRuntime.Stub() {
        override fun getProtocolVersion(): Int = PROTOCOL_VERSION

        override fun getRuntimeVersion(): String = runCatching {
            packageManager.getPackageInfo(packageName, 0).versionName.orEmpty()
        }.getOrDefault("")

        override fun isDeviceProvisioned(): Boolean =
            DeviceProvisioningPolicy.isProvisioned(this@CompanionRuntimeCapabilityService)

        override fun configureSession(
            apiBase: String,
            username: String,
            authToken: String,
            characterId: String,
            personalityStyle: String,
        ) {
            CompanionSessionStore.configure(
                this@CompanionRuntimeCapabilityService,
                CompanionSession(
                    apiBase = apiBase.trimEnd('/'),
                    username = username.trim(),
                    authToken = authToken,
                    characterId = characterId.trim(),
                    personalityStyle = personalityStyle.trim().ifBlank { "canonical" },
                ),
            )
            Log.i(
                "CompanionSession",
                "Configured username=${username.trim()} character=${characterId.trim()} " +
                    "ready=${apiBase.startsWith("http") && authToken.isNotBlank() && characterId.isNotBlank()}",
            )
        }

        override fun setOverlayVisible(visible: Boolean) {
            AgentOverlayController.setOverlayVisible(this@CompanionRuntimeCapabilityService, visible)
        }

        override fun getDiagnosticSnapshot(): String = CompanionRuntimeDiagnostics.snapshot(
            this@CompanionRuntimeCapabilityService,
            PROTOCOL_VERSION,
        )

        override fun repairSystemProvisioning(): String =
            CompanionRuntimeDiagnostics.repairProvisioning(
                this@CompanionRuntimeCapabilityService,
                PROTOCOL_VERSION,
            )
    }

    override fun onBind(intent: Intent?): IBinder = binder

    companion object {
        const val PROTOCOL_VERSION = 4
    }
}
