package top.ponychat.webview

import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavController

/** An exiting screen can remain clickable until its animation has finished. */
internal fun NavController.popPage(entry: NavBackStackEntry): Boolean {
    // Read the controller synchronously: Compose may still be drawing the old entry.
    if (currentBackStackEntry !== entry || previousBackStackEntry == null) return false
    return popBackStack()
}
