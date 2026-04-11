# GIMO Mesh — Lote 2: Android Zero-ADB Onboarding

**Delegado a**: GPT 5.4
**Contexto**: El backend (Lote 1) ya esta implementado y testeado (19/19 tests passing).
Este documento es autocontenido — no necesitas leer mas codigo del repo.

---

## Objetivo

Cuando un usuario instala el APK de GIMO Mesh y lo abre por primera vez, debe ver
un Setup Wizard que le permite escribir un codigo de 6 digitos, enrollarse en el mesh,
seleccionar un modelo GGUF, descargarlo, y empezar a operar. **Sin ADB, sin cables.**

### Flujo del usuario (30-60 segundos)

```
1. Instala APK (descarga desde GIMO Web o Core LAN)
2. Abre la app → detecta first-run (token vacio) → Setup Wizard
3. Admin en el dashboard genera codigo de 6 digitos
4. Usuario escribe el codigo en la app
5. App contacta al Core, se enrolla, recibe bearer token
6. Admin aprueba (o auto-aprueba)
7. App muestra catalogo de modelos del Core
8. Usuario elige modelo → descarga desde Core LAN (fallback HF)
9. Descarga completa → mesh arranca automaticamente → Dashboard
```

---

## Tech Stack (ya configurado)

| Tecnologia | Version | Notas |
|------------|---------|-------|
| Kotlin | 2.x | JVM target 17 |
| Jetpack Compose | BOM 2024.12.01 | Material3 |
| min SDK | 28 | Android 9+ |
| OkHttp | 4.12.0 | Ya en deps |
| kotlinx-serialization-json | 1.7.3 | Ya en deps, plugin configurado |
| DataStore Preferences | 1.1.1 | Ya en deps (NO Room/SQL) |
| Navigation Compose | 2.8.5 | Ya en deps |

**Package base**: `com.gredinlabs.gimomesh`

---

## API Contracts (Backend ya implementado)

### 1. POST `/ops/mesh/onboard/redeem` — SIN AUTH

Redime un codigo de 6 digitos para enrollar un dispositivo.

**Request**:
```json
{
  "code": "482917",
  "device_id": "galaxy-s10-a1b2",
  "name": "Galaxy S10",
  "device_mode": "inference",
  "device_class": "smartphone"
}
```

**Response 200**:
```json
{
  "device_id": "galaxy-s10-a1b2",
  "bearer_token": "Pzw-JL3CMdIWUTiZsbY46D8BNd7biLa-YeU8P54t0Eg",
  "workspace_id": "default",
  "workspace_name": "Default",
  "status": "pending_approval"
}
```

**Response 400** (codigo invalido/expirado/usado):
```json
{ "detail": "Invalid or expired onboarding code" }
```

**Notas**:
- NO requiere Authorization header — el codigo ES la autenticacion
- `device_id`: genera un ID unico por dispositivo (ej: `Build.MODEL-UUID.randomUUID().toString().take(8)`)
- `bearer_token`: guardar en DataStore — es el token para TODAS las llamadas futuras
- `device_mode`: "inference" | "utility" | "server" | "hybrid"
- `device_class`: "smartphone" | "tablet" | "laptop" | "server"
- Rate-limited: 5 intentos/min por IP

### 2. GET `/ops/mesh/onboard/discover` — SIN AUTH

Verifica que el Core esta activo y soporta mesh.

**Response 200**:
```json
{
  "mesh_enabled": true,
  "version": "1.0.0",
  "core_id": "gimo-core"
}
```

### 3. GET `/ops/mesh/models` — AUTH REQUERIDA

Lista modelos GGUF disponibles en el Core.

**Header**: `Authorization: Bearer <bearer_token>`

**Response 200**:
```json
[
  {
    "model_id": "qwen2.5_3b_q4_k_m",
    "filename": "qwen2.5_3b_q4_k_m.gguf",
    "name": "qwen2.5",
    "params": "3b",
    "quantization": "q4_k_m",
    "size_bytes": 2147483648,
    "sha256": "a1b2c3d4..."
  }
]
```

### 4. GET `/ops/mesh/models/{model_id}` — AUTH REQUERIDA

Metadata de un modelo especifico.

**Header**: `Authorization: Bearer <bearer_token>`

**Response 200**: mismo schema que un item de la lista.

### 5. GET `/ops/mesh/models/{model_id}/download` — AUTH REQUERIDA

Descarga streaming del archivo GGUF.

**Header**: `Authorization: Bearer <bearer_token>`

**Response 200**:
- `Content-Type: application/octet-stream`
- `Content-Disposition: attachment; filename="qwen2.5_3b_q4_k_m.gguf"`
- `Content-Length: 2147483648`
- Soporta `Range` header para resume

**Resume**: Si la descarga se interrumpe, enviar:
```
Range: bytes=1073741824-
```
Response sera `206 Partial Content` con `Content-Range: bytes 1073741824-2147483647/2147483648`

---

## Archivos a CREAR

### 1. `data/api/OnboardingClient.kt` (~150 LOC)

Cliente HTTP ligero SIN bearer token (para endpoints unauthenticated pre-enrollment).

```kotlin
package com.gredinlabs.gimomesh.data.api

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * HTTP client for onboarding endpoints (no auth required).
 * Used ONLY during setup wizard before the device has a bearer token.
 */
class OnboardingClient(private val coreUrl: String) {

    private val json = Json { ignoreUnknownKeys = true; isLenient = true }
    private val jsonMediaType = "application/json".toMediaType()

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    // Client with longer timeout for model downloads
    private val downloadClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES)  // large files
        .build()

    /**
     * GET /ops/mesh/onboard/discover — check if Core is reachable and mesh-enabled
     */
    suspend fun discoverCore(): CoreDiscovery? = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$coreUrl/ops/mesh/onboard/discover")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext null
                response.body?.string()?.let { json.decodeFromString<CoreDiscovery>(it) }
            }
        } catch (e: Exception) {
            null
        }
    }

    /**
     * POST /ops/mesh/onboard/redeem — redeem 6-digit code, get bearer token
     */
    suspend fun redeemCode(
        code: String,
        deviceId: String,
        name: String,
        deviceMode: String = "inference",
        deviceClass: String = "smartphone",
    ): OnboardResult? = withContext(Dispatchers.IO) {
        try {
            val payload = json.encodeToString(RedeemRequest(
                code = code,
                deviceId = deviceId,
                name = name,
                deviceMode = deviceMode,
                deviceClass = deviceClass,
            ))
            val request = Request.Builder()
                .url("$coreUrl/ops/mesh/onboard/redeem")
                .post(payload.toRequestBody(jsonMediaType))
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext null
                response.body?.string()?.let { json.decodeFromString<OnboardResult>(it) }
            }
        } catch (e: Exception) {
            null
        }
    }

    /**
     * GET /ops/mesh/models — list available GGUF models (requires bearer token)
     */
    suspend fun listModels(bearerToken: String): List<ModelInfo> =
        withContext(Dispatchers.IO) {
            try {
                val request = Request.Builder()
                    .url("$coreUrl/ops/mesh/models")
                    .header("Authorization", "Bearer $bearerToken")
                    .get()
                    .build()
                client.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) return@withContext emptyList()
                    response.body?.string()?.let {
                        json.decodeFromString<List<ModelInfo>>(it)
                    } ?: emptyList()
                }
            } catch (e: Exception) {
                emptyList()
            }
        }

    /**
     * GET /ops/mesh/models/{id}/download — streaming download with progress + resume
     *
     * @param bearerToken  device bearer token
     * @param modelId      model ID from catalog
     * @param targetFile   local file to write to
     * @param onProgress   callback(bytesDownloaded, totalBytes) — call from IO thread
     * @return true if download completed successfully
     */
    suspend fun downloadModel(
        bearerToken: String,
        modelId: String,
        targetFile: File,
        onProgress: (downloaded: Long, total: Long) -> Unit = { _, _ -> },
    ): Boolean = withContext(Dispatchers.IO) {
        try {
            // Resume support: if partial file exists, request remaining bytes
            val existingBytes = if (targetFile.exists()) targetFile.length() else 0L

            val requestBuilder = Request.Builder()
                .url("$coreUrl/ops/mesh/models/$modelId/download")
                .header("Authorization", "Bearer $bearerToken")
                .get()

            if (existingBytes > 0) {
                requestBuilder.header("Range", "bytes=$existingBytes-")
            }

            downloadClient.newCall(requestBuilder.build()).execute().use { response ->
                if (!response.isSuccessful && response.code != 206) return@withContext false

                val body = response.body ?: return@withContext false
                val contentLength = body.contentLength()
                val totalBytes = if (response.code == 206) {
                    // Parse Content-Range: bytes start-end/total
                    response.header("Content-Range")
                        ?.substringAfter("/")?.toLongOrNull() ?: (existingBytes + contentLength)
                } else {
                    contentLength
                }

                val outputStream = if (existingBytes > 0 && response.code == 206) {
                    targetFile.outputStream().apply { channel.position(existingBytes) }
                } else {
                    targetFile.outputStream()
                }

                outputStream.use { out ->
                    val buffer = ByteArray(8192)
                    var downloaded = existingBytes
                    val source = body.byteStream()

                    while (true) {
                        val read = source.read(buffer)
                        if (read == -1) break
                        out.write(buffer, 0, read)
                        downloaded += read
                        onProgress(downloaded, totalBytes)
                    }
                }
                true
            }
        } catch (e: Exception) {
            false
        }
    }

    fun shutdown() {
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
        downloadClient.dispatcher.executorService.shutdown()
        downloadClient.connectionPool.evictAll()
    }
}
```

### 2. `ui/setup/SetupWizardScreen.kt` (~300 LOC)

Compose wizard con pasos. **UI style**: fondo negro, accent verde (#4ADE80), tipografia
mono industrial (misma que el resto de la app — usa `GimoTypography` y `GimoAccents`
del theme existente).

**Steps**:

```
sealed class SetupStep {
    object Welcome : SetupStep()
    object CoreUrl : SetupStep()          // Pedir Core URL (o discover automatico)
    object ManualCode : SetupStep()       // Campo de 6 digitos
    object Enrolling : SetupStep()        // Spinner "Registrando..."
    object WaitApproval : SetupStep()     // "Esperando aprobacion..."
    object ModelSelect : SetupStep()      // Lista de modelos
    object Downloading : SetupStep()      // Progress bar
    object Done : SetupStep()             // "Listo!" → Dashboard
}
```

**Implementacion**:

```kotlin
@Composable
fun SetupWizardScreen(
    onSetupComplete: () -> Unit,  // callback to navigate to Dashboard
    settingsStore: SettingsStore,
) {
    var step by remember { mutableStateOf<SetupStep>(SetupStep.Welcome) }
    var coreUrl by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var error by remember { mutableStateOf("") }
    var bearerToken by remember { mutableStateOf("") }
    var workspaceId by remember { mutableStateOf("") }
    var models by remember { mutableStateOf<List<ModelInfo>>(emptyList()) }
    var downloadProgress by remember { mutableFloatStateOf(0f) }
    var selectedModel by remember { mutableStateOf<ModelInfo?>(null) }

    val scope = rememberCoroutineScope()
    val context = LocalContext.current

    // Generate device ID once
    val deviceId = remember {
        val model = android.os.Build.MODEL.replace(" ", "-").lowercase()
        "$model-${java.util.UUID.randomUUID().toString().take(8)}"
    }
    val deviceName = remember { android.os.Build.MODEL }

    when (step) {
        SetupStep.Welcome -> {
            // GIMO logo + "Enter a code to join the mesh"
            // Button: "Start" → SetupStep.CoreUrl
        }
        SetupStep.CoreUrl -> {
            // TextField for Core URL (e.g. "http://192.168.1.10:9325")
            // Button: "Connect" → discover() → if ok → SetupStep.ManualCode
            // On failure: show error, let user retry
        }
        SetupStep.ManualCode -> {
            // 6-digit code input (BasicTextField, monospaced, large)
            // Auto-submit when 6 digits entered
            // Button: "Redeem" → SetupStep.Enrolling
        }
        SetupStep.Enrolling -> {
            // CircularProgressIndicator + "Registering device..."
            // LaunchedEffect: call redeemCode()
            // On success → save token to SettingsStore → SetupStep.WaitApproval or ModelSelect
            // On failure → back to ManualCode with error
        }
        SetupStep.WaitApproval -> {
            // "Waiting for admin approval..."
            // Poll heartbeat every 5s — when status != pending_approval → ModelSelect
            // (For MVP, can skip this and go directly to ModelSelect)
        }
        SetupStep.ModelSelect -> {
            // LaunchedEffect: call listModels()
            // LazyColumn of models with name, size, quantization
            // On select → SetupStep.Downloading
        }
        SetupStep.Downloading -> {
            // LinearProgressIndicator + "${(progress*100).toInt()}%"
            // Text: "Downloading ${model.name}..."
            // LaunchedEffect: call downloadModel()
            // On complete → save model name to SettingsStore → SetupStep.Done
        }
        SetupStep.Done -> {
            // Checkmark animation + "Ready!"
            // Button: "Open Dashboard" → onSetupComplete()
        }
    }
}
```

**Notas de UI**:
- Cada paso es una `Column(modifier = Modifier.fillMaxSize().padding(24.dp))` centrada
- Usar `AnimatedContent` para transiciones entre pasos (opcional pero nice)
- Error messages en rojo (`Color(0xFFEF4444)`)
- Code input: 6 cajas separadas, monospace, accent border en foco
- Progress bar: `LinearProgressIndicator` con `GimoAccents.primary` color

### 3. `data/model/OnboardingModels.kt` (~30 LOC)

Nuevos data classes para onboarding. Agregar a `MeshModels.kt` o crear archivo separado.

```kotlin
// ── Onboarding models ──────────────────────────────────────

@Serializable
data class RedeemRequest(
    val code: String,
    @SerialName("device_id") val deviceId: String,
    val name: String,
    @SerialName("device_mode") val deviceMode: String = "inference",
    @SerialName("device_class") val deviceClass: String = "smartphone",
)

@Serializable
data class OnboardResult(
    @SerialName("device_id") val deviceId: String,
    @SerialName("bearer_token") val bearerToken: String,
    @SerialName("workspace_id") val workspaceId: String,
    @SerialName("workspace_name") val workspaceName: String,
    val status: String = "pending_approval",
)

@Serializable
data class CoreDiscovery(
    @SerialName("mesh_enabled") val meshEnabled: Boolean,
    val version: String,
    @SerialName("core_id") val coreId: String = "",
)

@Serializable
data class ModelInfo(
    @SerialName("model_id") val modelId: String,
    val filename: String,
    val name: String,
    val params: String = "",
    val quantization: String = "",
    @SerialName("size_bytes") val sizeBytes: Long = 0,
    val sha256: String = "",
)
```

---

## Archivos a MODIFICAR

### 1. `ui/navigation/NavGraph.kt`

**Cambio**: Agregar `Screen.SETUP` y first-run routing.

```kotlin
// En el enum Screen, agregar:
enum class Screen(val label: String) {
    SETUP("Setup"),   // ← NUEVO
    DASH("Dash"),
    TERM("Term"),
    AGENT("Agent"),
    CONFIG("Config"),
}

// En GimoMeshNavHost, agregar first-run check:
@Composable
fun GimoMeshNavHost(viewModel: MeshViewModel = viewModel()) {
    val settings by viewModel.settingsStore.settings.collectAsState(
        initial = SettingsStore.Settings()
    )

    // First-run detection: no token = needs setup
    val isFirstRun = settings.token.isEmpty()

    var currentScreen by remember(isFirstRun) {
        mutableStateOf(if (isFirstRun) Screen.SETUP else Screen.DASH)
    }

    // ... rest of Box layout ...

    when (currentScreen) {
        Screen.SETUP -> SetupWizardScreen(
            onSetupComplete = { currentScreen = Screen.DASH },
            settingsStore = viewModel.settingsStore,
        )
        Screen.DASH -> DashboardScreen(...)
        // ... etc
    }

    // Hide bottom nav during setup
    if (currentScreen != Screen.SETUP) {
        BottomNavBar(...)
    }
}
```

**IMPORTANTE**: La condicion de first-run es `settings.token.isEmpty()`. El `coreUrl`
default actual es `"http://192.168.0.49:9325"` — NO cambiar ese default. El wizard
pide la Core URL al usuario en el paso `CoreUrl`.

### 2. `data/store/SettingsStore.kt`

**Cambio minimo** — agregar key para el modelo descargado:

```kotlin
// En Keys, agregar:
val DOWNLOADED_MODEL_PATH = stringPreferencesKey("downloaded_model_path")

// En Settings data class, agregar:
val downloadedModelPath: String = "",

// En settings Flow, agregar al map:
downloadedModelPath = prefs[Keys.DOWNLOADED_MODEL_PATH] ?: "",

// Agregar metodo:
suspend fun updateDownloadedModelPath(path: String) {
    context.dataStore.edit { it[Keys.DOWNLOADED_MODEL_PATH] = path }
}
```

### 3. `data/model/MeshModels.kt`

Agregar los data classes de `OnboardingModels.kt` (ver seccion anterior).
Puedes agregarlos al final del archivo existente o crear un archivo separado.

---

## Referencia: Codigo existente

### GimoCoreClient.kt (patron HTTP a seguir)

```kotlin
// PATRON: usar OkHttp + kotlinx-serialization + withContext(Dispatchers.IO)
// PATRON: client.newCall(request).execute().use { response -> ... }
// PATRON: json.decodeFromString<T>(body) para deserializar
// PATRON: return null/emptyList() en caso de error
```

Ya lo tienes arriba completo — la estructura de `OnboardingClient` sigue exactamente
el mismo patron pero SIN el header `Authorization: Bearer` en los endpoints de onboarding.

### SettingsStore.kt (DataStore pattern)

```kotlin
// PATRON: stringPreferencesKey/intPreferencesKey/booleanPreferencesKey
// PATRON: context.dataStore.edit { it[KEY] = value }
// PATRON: Flow<Settings> que mapea preferencias
```

### Theme (colores y tipografia)

Los archivos de theme estan en `ui/theme/`:
- `GimoAccents.primary` = verde (#4ADE80)
- `GimoText.primary` = blanco
- `GimoText.secondary` = gris claro
- `GimoText.tertiary` = gris oscuro
- `GlassBackground` = fondo oscuro semitransparente
- `GimoTypography` = tipografia del sistema de diseno
- Fondo general: negro (#0A0A0A)

---

## Estructura de archivos final

```
apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/
├── data/
│   ├── api/
│   │   ├── GimoCoreClient.kt          ← existente (NO tocar)
│   │   └── OnboardingClient.kt        ← NUEVO
│   ├── model/
│   │   └── MeshModels.kt              ← MODIFICAR (agregar 4 data classes)
│   └── store/
│       └── SettingsStore.kt           ← MODIFICAR (1 key + 1 metodo)
├── ui/
│   ├── navigation/
│   │   └── NavGraph.kt               ← MODIFICAR (first-run routing)
│   └── setup/
│       └── SetupWizardScreen.kt       ← NUEVO (~300 LOC)
└── ...
```

---

## Criterios de aceptacion

1. **First-run**: App con token vacio → Setup Wizard aparece. App con token → Dashboard directo.
2. **Core discovery**: El wizard verifica que el Core esta activo antes de pedir codigo.
3. **Code redeem**: Codigo de 6 digitos → POST sin auth → recibe bearer_token → guardado en DataStore.
4. **Model list**: Despues de redeem, muestra catalogo de modelos del Core.
5. **Download**: Descarga streaming con progress bar. Resume si se interrumpe.
6. **Completion**: Token + modelo guardados en DataStore. Transicion a Dashboard.
7. **Error handling**: Codigo invalido/expirado → mensaje claro, retry. Core no alcanzable → mensaje claro.
8. **No regresiones**: El resto de la app (Dashboard, Terminal, Agent, Config) sigue funcionando igual.

---

## NO hacer

- NO tocar `GimoCoreClient.kt` — ese es para operaciones post-enrollment con auth
- NO tocar `build.gradle.kts` — todas las deps necesarias ya estan
- NO implementar QR scan ni Bluetooth — solo codigo manual de 6 digitos
- NO implementar mDNS discovery — el usuario escribe la URL del Core manualmente
- NO usar Room/SQLite — DataStore Preferences solamente
- NO crear ViewModels nuevos si puedes evitarlo — manejar estado local en el Composable

---

## Test manual

```
1. Desinstalar app / limpiar datos → abrir → debe aparecer Setup Wizard
2. Escribir URL del Core → "Connect" → debe mostrar "Core found"
3. Generar codigo en el Core:
   curl -X POST http://<core>:9325/ops/mesh/onboard/code \
     -H "Authorization: Bearer $TOKEN" \
     -d '{"workspace_id":"default"}'
4. Escribir codigo en la app → debe mostrar "Registering..."
5. Si hay modelos en el Core → debe mostrar lista
6. Seleccionar modelo → progress bar → download completa
7. "Open Dashboard" → llega al Dashboard normal
8. Cerrar y reabrir app → va directo al Dashboard (token ya guardado)
```
