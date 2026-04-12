package com.gredinlabs.gimomesh.ui.setup

import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.common.InputImage
import com.gredinlabs.gimomesh.ui.theme.GimoBorders
import com.gredinlabs.gimomesh.ui.theme.GimoMono
import com.gredinlabs.gimomesh.ui.theme.GimoText
import com.gredinlabs.gimomesh.ui.theme.GimoTypography

data class QrResult(
    val coreUrl: String,
    val code: String,
    val sig: String,
)

fun parseGimoQr(raw: String): QrResult? {
    val uri = try {
        Uri.parse(raw)
    } catch (_: Exception) {
        return null
    }
    if (uri.scheme != "gimo") return null

    val host = uri.host?.takeIf(String::isNotBlank) ?: return null
    val port = uri.port.takeIf { it > 0 } ?: return null
    val code = uri.pathSegments.singleOrNull()?.takeIf { it.length == 6 && it.all(Char::isDigit) } ?: return null
    val sig = uri.getQueryParameter("sig")?.takeIf {
        it.length == 16 && it.all { char -> char.isDigit() || char.lowercaseChar() in 'a'..'f' }
    } ?: return null

    return QrResult(
        coreUrl = "http://$host:$port",
        code = code,
        sig = sig,
    )
}

@Composable
fun QrScannerScreen(
    onQrScanned: (QrResult) -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var hasCameraPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED,
        )
    }
    var scanned by remember { mutableStateOf(false) }
    var cameraProvider by remember { mutableStateOf<ProcessCameraProvider?>(null) }
    val scanner = remember { BarcodeScanning.getClient() }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        hasCameraPermission = granted
    }

    LaunchedEffect(Unit) {
        if (!hasCameraPermission) permissionLauncher.launch(Manifest.permission.CAMERA)
    }

    DisposableEffect(lifecycleOwner) {
        onDispose {
            cameraProvider?.unbindAll()
            scanner.close()
        }
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(Color(0xFF0A0A0A)),
    ) {
        if (hasCameraPermission && !scanned) {
            AndroidView(
                factory = { ctx ->
                    PreviewView(ctx).also { previewView ->
                        val providerFuture = ProcessCameraProvider.getInstance(ctx)
                        providerFuture.addListener(
                            {
                                val provider = providerFuture.get()
                                cameraProvider = provider

                                val preview = Preview.Builder().build().also {
                                    it.surfaceProvider = previewView.surfaceProvider
                                }
                                val analysis = ImageAnalysis.Builder()
                                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                                    .build()

                                analysis.setAnalyzer(ContextCompat.getMainExecutor(ctx)) { imageProxy ->
                                    val mediaImage = imageProxy.image
                                    if (mediaImage == null) {
                                        imageProxy.close()
                                        return@setAnalyzer
                                    }
                                    val inputImage = InputImage.fromMediaImage(
                                        mediaImage,
                                        imageProxy.imageInfo.rotationDegrees,
                                    )
                                    scanner.process(inputImage)
                                        .addOnSuccessListener { barcodes ->
                                            if (scanned) return@addOnSuccessListener
                                            barcodes.firstNotNullOfOrNull { barcode ->
                                                barcode.rawValue?.let(::parseGimoQr)
                                            }?.let { result ->
                                                scanned = true
                                                onQrScanned(result)
                                            }
                                        }
                                        .addOnCompleteListener { imageProxy.close() }
                                }

                                try {
                                    provider.unbindAll()
                                    provider.bindToLifecycle(
                                        lifecycleOwner,
                                        CameraSelector.DEFAULT_BACK_CAMERA,
                                        preview,
                                        analysis,
                                    )
                                } catch (_: Exception) {
                                    imageProxySafeClose(analysis)
                                }
                            },
                            ContextCompat.getMainExecutor(ctx),
                        )
                    }
                },
                modifier = Modifier.fillMaxSize(),
            )

            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(32.dp),
                verticalArrangement = Arrangement.SpaceBetween,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    "Scan the QR code from your Core dashboard",
                    style = GimoTypography.bodyLarge.copy(color = Color.White),
                )
                Box(
                    modifier = Modifier
                        .size(250.dp)
                        .clip(RoundedCornerShape(20.dp))
                        .background(Color.White.copy(alpha = 0.1f)),
                )
                ScannerSecondaryAction("Cancel", onCancel)
            }
        } else if (!hasCameraPermission) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(24.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    "Camera permission is required to scan QR codes",
                    style = GimoTypography.bodyLarge.copy(color = GimoText.secondary),
                )
                Spacer(modifier = Modifier.height(16.dp))
                ScannerSecondaryAction("Enter code manually", onCancel)
            }
        }
    }
}

@Composable
private fun ScannerSecondaryAction(text: String, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        shape = RoundedCornerShape(14.dp),
        colors = ButtonDefaults.outlinedButtonColors(contentColor = GimoText.secondary),
        border = androidx.compose.foundation.BorderStroke(1.dp, GimoBorders.primary),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(
            text.uppercase(),
            fontFamily = GimoMono,
            fontSize = 10.sp,
            letterSpacing = 0.8.sp,
        )
    }
}

private fun imageProxySafeClose(analysis: ImageAnalysis) {
    try {
        analysis.clearAnalyzer()
    } catch (_: Exception) {
        // Best-effort cleanup if camera binding fails.
    }
}
