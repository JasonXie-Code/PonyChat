package top.ponychat.companion

import android.app.Application
import android.os.UserManager
import android.util.Log
import top.ponychat.companion.reply.CompanionSessionStore

class CompanionApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        val userManager = getSystemService(UserManager::class.java)
        if (userManager?.isUserUnlocked == false) {
            Log.i("CompanionSession", "Waiting for user unlock before restoring role session")
            return
        }
        CompanionSessionStore.initialize(this)
        val session = CompanionSessionStore.current
        Log.i(
            "CompanionSession",
            "Restored username=${session?.username.orEmpty()} " +
                "character=${session?.characterId.orEmpty()} ready=${session?.isReady == true}",
        )
    }
}
