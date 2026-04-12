# GIMO Mesh — Lote 4: mDNS Discovery + QR Scanner (Android)

**Delegado a**: GPT 5.4
**Prerequisito**: Lotes 2+3 completados (SetupWizardScreen, OnboardingClient, etc.)
**Backend**: Ya implementado y testeado (18/18 tests passing)

---

## Objetivo

Dos features que eliminan friccion del onboarding:

1. **mDNS Auto-Discovery**: La app encuentra el Core automaticamente en la LAN
   sin que el usuario escriba la URL
2. **QR Scanner**: El admin muestra un QR, el usuario lo escanea, el onboarding
   es 100% automatico (0 texto escrito)

Ambas features tienen **hardening de seguridad** integrado (HMAC signatures).

---

## Contratos del Backend (ya implementados)

### mDNS Service

El Core anuncia `_gimo._tcp.local.` via mDNS con TXT records:

```
TXT: version=1.0.0, mesh=true, core_id=gimo, hmac=<16 hex chars>
```

- `hmac` = HMAC-SHA256(ORCH_TOKEN, "{hostname}:{port}") truncado a 16 chars
- **Desactivado por defecto** — solo activo si admin pone `ORCH_MDNS_ENABLED=true`
- El dispositivo pre-enrollment NO puede verificar el HMAC (no tiene token)
- Post-enrollment SI puede verificar

### QR Payload (en `POST /ops/mesh/onboard/code` response)

```json
{
  "code": "482917",
  "workspace_id": "default",
  "expires_at": "2026-04-12T15:30:00+00:00",
  "qr_payload": "gimo://192.168.0.49:9325/482917?sig=a1b2c3d4e5f6g7h8"
}
```

- Formato: `gimo://{host}:{port}/{code}?sig={hmac}`
- `sig` = HMAC-SHA256(ORCH_TOKEN, "{host}:{port}/{code}") truncado a 16 hex chars
- El admin muestra `qr_payload` como QR code en el dashboard
- TTL 5 minutos (el codigo expira)

### HMAC Verification

```python
# Backend utility (for reference — implement equivalent in Kotlin)
import hmac, hashlib

def verify(token: str, payload: str, sig: str) -> bool:
    expected = hmac.new(token.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return hmac.compare_digest(expected, sig)
```

En Kotlin:
```kotlin
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

fun verifyHmac(token: String, payload: String, sig: String): Boolean {
    val mac = Mac.getInstance("HmacSHA256")
    mac.init(SecretKeySpec(token.toByteArray(), "HmacSHA256"))
    val expected = mac.doFinal(payload.toByteArray())
        .joinToString("") { "%02x".format(it) }
        .take(16)
    return expected == sig
}
```

---

## Tech Stack

Mismo que Lotes anteriores. Deps nuevas:

```gradle
// QR Scanning (ML Kit + CameraX)
implementation("com.google.mlkit:barcode-scanning:17.3.0")
implementation("androidx.camera:camera-camera2:1.4.1")
implementation("androidx.camera:camera-lifecycle:1.4.1")
implementation("androidx.camera:camera-view:1.4.1")
```

**mDNS en Android**: `NsdManager` built-in (API 16+), **0 deps adicionales**.

---

## Archivos a CREAR

### 1. `data/network/CoreDiscoveryManager.kt` (~100 LOC)

Descubre el Core en la LAN via mDNS usando `NsdManager` (Android built-in).

```kotlin
package com.gredinlabs.gimomesh.data.network

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo

/**
 * Discovers GIMO Core servers on the LAN via mDNS.
 *
 * Uses Android's built-in NsdManager to find _gimo._tcp services.
 * The Core advertises HMAC-signed TXT records for authentication.
 *
 * Pre-enrollment: device has no token → cannot verify HMAC → shows "unverified"
 * Post-enrollment: device has bearer token → can verify HMAC → shows "verified"
 */
class CoreDiscoveryManager(context: Context) {

    private val nsdManager = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private var discoveryListener: NsdManager.DiscoveryListener? = null

    data class DiscoveredCore(
        val host: String,
        val port: Int,
        val version: String = "",
        val coreId: String = "",
        val hmac: String = "",
        val verified: Boolean = false,
    ) {
        val url: String get() = "http://$host:$port"
    }

    /**
     * Start discovering _gimo._tcp services on the LAN.
     *
     * @param token  Device's bearer token (empty pre-enrollment)
     * @param onFound  Callback with discovered Core info
     * @param timeoutMs  Auto-stop discovery after this duration (default 10s)
     */
    fun startDiscovery(
        token: String = "",
        onFound: (DiscoveredCore) -> Unit,
        timeoutMs: Long = 10_000,
    ) {
        stopDiscovery()  // Clean up any previous listener

        discoveryListener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {}
            override fun onDiscoveryStopped(serviceType: String) {}
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {}
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {}

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                // Resolve the service to get IP + port + TXT records
                nsdManager.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                    override fun onResolveFailed(si: NsdServiceInfo, errorCode: Int) {}
                    override fun onServiceResolved(si: NsdServiceInfo) {
                        val host = si.host?.hostAddress ?: return
                        val port = si.port

                        // Extract TXT record attributes
                        val attrs = si.attributes
                        val version = attrs["version"]?.decodeToString() ?: ""
                        val coreId = attrs["core_id"]?.decodeToString() ?: ""
                        val hmac = attrs["hmac"]?.decodeToString() ?: ""

                        // Verify HMAC if we have a token
                        val verified = if (token.isNotBlank() && hmac.isNotBlank()) {
                            verifyHmac(token, "$host:$port", hmac)
                        } else {
                            false
                        }

                        onFound(DiscoveredCore(
                            host = host,
                            port = port,
                            version = version,
                            coreId = coreId,
                            hmac = hmac,
                            verified = verified,
                        ))
                    }
                })
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) {}
        }

        nsdManager.discoverServices("_gimo._tcp.", NsdManager.PROTOCOL_DNS_SD, discoveryListener)

        // Auto-stop after timeout
        android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
            stopDiscovery()
        }, timeoutMs)
    }

    fun stopDiscovery() {
        discoveryListener?.let {
            try {
                nsdManager.stopServiceDiscovery(it)
            } catch (_: Exception) {}
        }
        discoveryListener = null
    }

    companion object {
        fun verifyHmac(token: String, payload: String, sig: String): Boolean {
            val mac = javax.crypto.Mac.getInstance("HmacSHA256")
            mac.init(javax.crypto.spec.SecretKeySpec(token.toByteArray(), "HmacSHA256"))
            val expected = mac.doFinal(payload.toByteArray())
                .joinToString("") { "%02x".format(it) }
                .take(16)
            return expected == sig
        }
    }
}
```

### 2. `ui/setup/QrScannerScreen.kt` (~130 LOC)

Compose screen con CameraX preview + ML Kit barcode scanning.

```kotlin
package com.gredinlabs.gimomesh.ui.setup

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.common.InputImage
import com.gredinlabs.gimomesh.ui.theme.*

/**
 * QR payload format: gimo://{host}:{port}/{code}?sig={hmac}
 */
data class QrResult(
    val coreUrl: String,   // "http://192.168.0.49:9325"
    val code: String,      // "482917"
    val sig: String,       // HMAC sig (16 hex chars)
)

/**
 * Parse a gimo:// QR payload.
 * Returns null if the format doesn't match.
 */
fun parseGimoQr(raw: String): QrResult? {
    // Expected: gimo://host:port/code?sig=xxxx
    if (!raw.startsWith("gimo://")) return null
    val withoutScheme = raw.removePrefix("gimo://")

    val (pathPart, queryPart) = if ("?" in withoutScheme) {
        withoutScheme.split("?", limit = 2)
    } else {
        listOf(withoutScheme, "")
    }

    val lastSlash = pathPart.lastIndexOf('/')
    if (lastSlash == -1) return null

    val hostPort = pathPart.substring(0, lastSlash)
    val code = pathPart.substring(lastSlash + 1)
    if (code.length != 6 || !code.all { it.isDigit() }) return null

    val sig = queryPart
        .split("&")
        .firstOrNull { it.startsWith("sig=") }
        ?.removePrefix("sig=")
        .orEmpty()

    return QrResult(
        coreUrl = "http://$hostPort",
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
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED
        )
    }
    var scanned by remember { mutableStateOf(false) }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> hasCameraPermission = granted }

    LaunchedEffect(Unit) {
        if (!hasCameraPermission) {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    Box(modifier = modifier.fillMaxSize().background(Color(0xFF0A0A0A))) {
        if (hasCameraPermission && !scanned) {
            // CameraX Preview + ML Kit analysis
            AndroidView(
                factory = { ctx ->
                    val previewView = PreviewView(ctx)
                    val cameraProviderFuture = ProcessCameraProvider.getInstance(ctx)

                    cameraProviderFuture.addListener({
                        val cameraProvider = cameraProviderFuture.get()
                        val preview = Preview.Builder().build().also {
                            it.surfaceProvider = previewView.surfaceProvider
                        }

                        val scanner = BarcodeScanning.getClient()
                        val analysis = ImageAnalysis.Builder()
                            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                            .build()

                        analysis.setAnalyzer(ContextCompat.getMainExecutor(ctx)) { imageProxy ->
                            val mediaImage = imageProxy.image ?: run {
                                imageProxy.close(); return@setAnalyzer
                            }
                            val inputImage = InputImage.fromMediaImage(
                                mediaImage, imageProxy.imageInfo.rotationDegrees
                            )
                            scanner.process(inputImage)
                                .addOnSuccessListener { barcodes ->
                                    for (barcode in barcodes) {
                                        val raw = barcode.rawValue ?: continue
                                        val result = parseGimoQr(raw)
                                        if (result != null && !scanned) {
                                            scanned = true
                                            onQrScanned(result)
                                        }
                                    }
                                }
                                .addOnCompleteListener { imageProxy.close() }
                        }

                        try {
                            cameraProvider.unbindAll()
                            cameraProvider.bindToLifecycle(
                                lifecycleOwner,
                                CameraSelector.DEFAULT_BACK_CAMERA,
                                preview,
                                analysis,
                            )
                        } catch (_: Exception) {}
                    }, ContextCompat.getMainExecutor(ctx))

                    previewView
                },
                modifier = Modifier.fillMaxSize(),
            )

            // Overlay: scan frame + instructions
            Column(
                modifier = Modifier.fillMaxSize().padding(32.dp),
                verticalArrangement = Arrangement.SpaceBetween,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    "Scan the QR code from your Core dashboard",
                    style = GimoTypography.bodyLarge.copy(color = Color.White),
                )
                // Scan frame indicator
                Box(
                    modifier = Modifier
                        .size(250.dp)
                        .clip(RoundedCornerShape(20.dp))
                        .background(Color.White.copy(alpha = 0.1f))
                )
                SecondaryAction("Cancel") { onCancel() }
            }
        } else if (!hasCameraPermission) {
            // Permission denied
            Column(
                modifier = Modifier.fillMaxSize().padding(24.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    "Camera permission is required to scan QR codes",
                    style = GimoTypography.bodyLarge.copy(color = GimoText.secondary),
                )
                Spacer(modifier = Modifier.height(16.dp))
                SecondaryAction("Enter code manually") { onCancel() }
            }
        }
    }
}
```

---

## Archivos a MODIFICAR

### 3. `app/build.gradle.kts` — agregar deps

Despues del bloque `// DataStore`:
```gradle
// QR Scanning (ML Kit + CameraX)
implementation("com.google.mlkit:barcode-scanning:17.3.0")
implementation("androidx.camera:camera-camera2:1.4.1")
implementation("androidx.camera:camera-lifecycle:1.4.1")
implementation("androidx.camera:camera-view:1.4.1")
```

### 4. `AndroidManifest.xml` — agregar permiso

Despues de los permisos existentes de network:
```xml
<uses-permission android:name="android.permission.CAMERA" />
<uses-feature android:name="android.hardware.camera" android:required="false" />
```

`required="false"` — la app funciona sin camara (flujo manual).

### 5. `ui/setup/SetupWizardScreen.kt` — integrar QR + mDNS

**5a. Agregar step al sealed class** (linea ~76):
```kotlin
sealed class SetupStep {
    object Welcome : SetupStep()
    object QRScanner : SetupStep()     // ← NUEVO
    object CoreUrl : SetupStep()
    object ManualCode : SetupStep()
    // ... rest unchanged
}
```

**5b. Modificar Welcome step** — dos botones:
```kotlin
SetupStep.Welcome -> StepCard {
    StepTitle("Join the mesh", "...")
    Spacer(modifier = Modifier.height(18.dp))
    PrimaryAction("Scan QR Code", true) { step = SetupStep.QRScanner }
    Spacer(modifier = Modifier.height(10.dp))
    SecondaryAction("Enter code manually") { step = SetupStep.CoreUrl }
}
```

**5c. Agregar QRScanner step** al `AnimatedContent`:
```kotlin
SetupStep.QRScanner -> QrScannerScreen(
    onQrScanned = { result ->
        // Auto-fill from QR
        coreUrlInput = result.coreUrl
        connectedCoreUrl = result.coreUrl
        code = result.code
        lastSubmittedCode = ""
        error = ""
        // Skip CoreUrl + ManualCode — go straight to enrolling
        step = SetupStep.Enrolling
    },
    onCancel = { step = SetupStep.CoreUrl },
)
```

**5d. Agregar mDNS discovery en CoreUrl step**:
```kotlin
SetupStep.CoreUrl -> {
    // Auto-discover Core on LAN
    val discoveryManager = remember { CoreDiscoveryManager(context) }
    var discoveredUrl by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        discoveryManager.startDiscovery { core ->
            if (discoveredUrl.isBlank()) {
                discoveredUrl = core.url
                coreUrlInput = core.url
            }
        }
    }

    DisposableEffect(Unit) {
        onDispose { discoveryManager.stopDiscovery() }
    }

    StepCard {
        StepTitle("Locate the Core", "...")
        if (discoveredUrl.isNotBlank()) {
            Banner("Core auto-discovered at $discoveredUrl (unverified)", SetupAccent)
            Spacer(modifier = Modifier.height(12.dp))
        }
        // ... rest of existing CoreUrl UI unchanged
    }
}
```

---

## Estructura de archivos final

```
apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/
├── data/
│   ├── network/
│   │   └── CoreDiscoveryManager.kt     ← NUEVO (mDNS, ~100 LOC)
│   └── ...
├── ui/
│   └── setup/
│       ├── SetupWizardScreen.kt        ← MODIFICAR (+QR step, +mDNS)
│       └── QrScannerScreen.kt          ← NUEVO (CameraX+MLKit, ~130 LOC)
└── ...
```

---

## Criterios de aceptacion

1. **mDNS Discovery**: En step CoreUrl, si el Core tiene `ORCH_MDNS_ENABLED=true`,
   la URL aparece automaticamente en 3-5 segundos con banner "auto-discovered"
2. **mDNS Timeout**: Si no descubre nada en 10s, el usuario sigue con entrada manual
3. **QR Scan**: Welcome → "Scan QR" → pide permiso camara → escanea → onboarding completo
4. **QR Parse**: Solo acepta formato `gimo://host:port/code?sig=xxx`
5. **Permission denied**: Si usuario deniega camara → "Enter code manually"
6. **No regressions**: "Enter code manually" sigue funcionando identico

---

## NO hacer

- NO tocar OnboardingClient.kt — los endpoints son los mismos
- NO tocar backend — ya esta implementado y testeado
- NO verificar HMAC pre-enrollment — el dispositivo no tiene token aun
- NO bloquear si HMAC es invalido — el codigo 6-digit es la validacion real
- NO instalar zeroconf en Android — NsdManager es built-in

---

## Test manual

```
1. [mDNS] En el Core: ORCH_MDNS_ENABLED=true python -m tools.gimo_server.main
2. [mDNS] Abrir app → Welcome → "Enter code manually" → CoreUrl step
3. [mDNS] En 3-5s: banner "Core auto-discovered at 192.168.x.x:9325"
4. [QR] En el Core: generar codigo con curl POST /ops/mesh/onboard/code
5. [QR] Copiar qr_payload del response → generar QR con cualquier herramienta
6. [QR] Abrir app → Welcome → "Scan QR Code" → aceptar permiso camara
7. [QR] Apuntar camara al QR → onboarding automatico sin escribir nada
8. [Fallback] Denegar camara → "Enter code manually" → flujo manual funciona
```
