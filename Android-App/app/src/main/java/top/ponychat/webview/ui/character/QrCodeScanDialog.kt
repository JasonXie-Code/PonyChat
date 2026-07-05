package top.ponychat.webview.ui.character

import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

private val CameraPermission = android.Manifest.permission.CAMERA

/**
 * 全屏相机扫码（二维码与常见一维/二维条码，与 ML Kit 默认支持范围一致），
 * 成功后回调 [onDecoded] 原文；不执行跳转、不打开链接。
 */
@Composable
fun QrCodeScanDialog(
    visible: Boolean,
    onDismiss: () -> Unit,
    onDecoded: (String) -> Unit,
) {
    if (!visible) return

    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var permissionTick by remember { mutableIntStateOf(0) }
    var permissionDenied by remember { mutableStateOf(false) }

    val hasPermission = remember(permissionTick) {
        ContextCompat.checkSelfPermission(context, CameraPermission) == PackageManager.PERMISSION_GRANTED
    }

    val launcher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        permissionTick++
        if (!granted) permissionDenied = true
    }

    LaunchedEffect(visible) {
        if (visible && ContextCompat.checkSelfPermission(context, CameraPermission) != PackageManager.PERMISSION_GRANTED) {
            launcher.launch(CameraPermission)
        }
    }

    if (permissionDenied) {
        Dialog(
            onDismissRequest = {
                permissionDenied = false
                onDismiss()
            },
        ) {
            Text(
                "需要相机权限才能扫码",
                color = MaterialTheme.colorScheme.onBackground,
                textAlign = TextAlign.Center,
            )
        }
        return
    }

    if (!hasPermission) {
        Dialog(
            onDismissRequest = onDismiss,
            properties = DialogProperties(
                usePlatformDefaultWidth = false,
                decorFitsSystemWindows = false,
            ),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black)
                    .statusBarsPadding(),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "正在请求相机权限…",
                    color = Color.White,
                    textAlign = TextAlign.Center,
                )
            }
        }
        return
    }

    val decoded = remember { AtomicBoolean(false) }
    val mainExecutor = remember { ContextCompat.getMainExecutor(context) }
    val cameraExecutor = remember { Executors.newSingleThreadExecutor() }

    /** 不限制格式，与 [BarcodeScanning.getClient] 默认行为一致，含 QR 与 EAN/UPC/Code128 等一维码 */
    val scanner = remember { BarcodeScanning.getClient() }

    DisposableEffect(Unit) {
        onDispose {
            cameraExecutor.shutdown()
            scanner.close()
        }
    }

    DisposableEffect(context, mainExecutor) {
        onDispose {
            runCatching {
                val future = ProcessCameraProvider.getInstance(context)
                mainExecutor.execute {
                    runCatching { future.get().unbindAll() }
                }
            }
        }
    }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(
            usePlatformDefaultWidth = false,
            decorFitsSystemWindows = false,
        ),
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black),
        ) {
            AndroidView(
                modifier = Modifier.fillMaxSize(),
                factory = { ctx ->
                    val previewView = PreviewView(ctx)
                    val cameraProviderFuture = ProcessCameraProvider.getInstance(ctx)
                    cameraProviderFuture.addListener(
                        {
                            if (decoded.get()) return@addListener
                            val cameraProvider = cameraProviderFuture.get()
                            val preview = Preview.Builder().build().also {
                                it.setSurfaceProvider(previewView.surfaceProvider)
                            }
                            val analysis = ImageAnalysis.Builder()
                                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                                .build()
                            analysis.setAnalyzer(cameraExecutor) { imageProxy: ImageProxy ->
                                if (decoded.get()) {
                                    imageProxy.close()
                                    return@setAnalyzer
                                }
                                val mediaImage = imageProxy.image
                                if (mediaImage == null) {
                                    imageProxy.close()
                                    return@setAnalyzer
                                }
                                val rotation = imageProxy.imageInfo.rotationDegrees
                                val input = InputImage.fromMediaImage(mediaImage, rotation)
                                scanner.process(input)
                                    .addOnSuccessListener { barcodes ->
                                        for (b in barcodes) {
                                            val raw = b.rawValue ?: continue
                                            if (decoded.compareAndSet(false, true)) {
                                                mainExecutor.execute {
                                                    runCatching { cameraProvider.unbindAll() }
                                                    onDecoded(raw)
                                                }
                                            }
                                            break
                                        }
                                    }
                                    .addOnCompleteListener {
                                        imageProxy.close()
                                    }
                            }
                            runCatching {
                                cameraProvider.unbindAll()
                                cameraProvider.bindToLifecycle(
                                    lifecycleOwner,
                                    CameraSelector.DEFAULT_BACK_CAMERA,
                                    preview,
                                    analysis,
                                )
                            }
                        },
                        ContextCompat.getMainExecutor(ctx),
                    )
                    previewView
                },
            )
            IconButton(
                onClick = onDismiss,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .statusBarsPadding()
                    .padding(8.dp),
            ) {
                Icon(
                    imageVector = Icons.Filled.Close,
                    contentDescription = "关闭",
                    tint = Color.White,
                )
            }
        }
    }
}
