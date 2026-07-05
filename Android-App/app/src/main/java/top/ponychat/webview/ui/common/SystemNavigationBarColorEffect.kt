package top.ponychat.webview.ui.common

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.os.Build
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

@Composable
fun SystemNavigationBarColorEffect(
    color: Color,
    useDarkIcons: Boolean = color.luminance() > 0.5f,
    restoreOnDispose: Boolean = false
) {
    val activity = LocalContext.current.findActivity()
    val lifecycleOwner = LocalLifecycleOwner.current
    val latestColor = rememberUpdatedState(color.toArgb())
    val latestUseDarkIcons = rememberUpdatedState(useDarkIcons)
    val latestRestoreOnDispose = rememberUpdatedState(restoreOnDispose)

    fun applyNavigationBarColor() {
        val window = activity?.window ?: return
        window.navigationBarColor = latestColor.value
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            window.isNavigationBarContrastEnforced = false
        }
        WindowInsetsControllerCompat(window, window.decorView)
            .isAppearanceLightNavigationBars = latestUseDarkIcons.value
    }

    DisposableEffect(activity, lifecycleOwner) {
        if (activity == null) return@DisposableEffect onDispose { }

        val window = activity.window
        val previousColor = window.navigationBarColor
        val insetsController = WindowInsetsControllerCompat(window, window.decorView)
        val previousLightNav = insetsController.isAppearanceLightNavigationBars
        val previousContrastEnforced = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            window.isNavigationBarContrastEnforced
        } else {
            false
        }

        applyNavigationBarColor()

        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                window.decorView.post { applyNavigationBarColor() }
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)

        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            if (latestRestoreOnDispose.value) {
                window.navigationBarColor = previousColor
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    window.isNavigationBarContrastEnforced = previousContrastEnforced
                }
                insetsController.isAppearanceLightNavigationBars = previousLightNav
            }
        }
    }

    SideEffect {
        applyNavigationBarColor()
    }
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
