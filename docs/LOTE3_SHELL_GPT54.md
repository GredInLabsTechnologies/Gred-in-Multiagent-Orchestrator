# GIMO Mesh — Lote 3: Shell Embebido + Model Runner

**Delegado a**: GPT 5.4
**Prerequisito**: Lote 2 completado (SetupWizardScreen, OnboardingClient, etc.)
**Contexto**: El dispositivo ya tiene bearer_token y un .gguf descargado en disco.
Ahora necesita ejecutar inferencia localmente.

---

## Objetivo

Despues del Setup Wizard, el dispositivo tiene:
- `bearer_token` en DataStore
- `modelo.gguf` en `context.filesDir/models/`

Necesita:
1. Un shell Unix embebido (busybox) para ejecutar procesos nativos
2. Lanzar llama.cpp server con el modelo descargado
3. Reportar al Core que esta operativo (heartbeat con `model_loaded`)

---

## Tech Stack

Mismo que Lote 2. Sin deps nuevas en build.gradle.kts.

**Binarios nativos** (se incluyen como assets en el APK):
- `busybox` — static arm64 binary (~1.8MB), provee 300+ comandos Unix
- `llama-server` — llama.cpp server binary, compilado para arm64 (~5MB)

Ambos van en `app/src/main/assets/bin/` y se extraen al primer arranque.

---

## Archivos a CREAR

### 1. `service/ShellEnvironment.kt` (~120 LOC)

Inicializa el entorno shell con busybox + llama.cpp.

```kotlin
package com.gredinlabs.gimomesh.service

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Manages the embedded Unix shell environment.
 *
 * On first run, extracts busybox and llama-server from APK assets
 * to context.filesDir/bin/. Creates symlinks for common commands.
 * Provides exec() to run commands with the correct PATH/env.
 */
class ShellEnvironment(private val context: Context) {

    private val binDir = File(context.filesDir, "bin")
    private val modelsDir = File(context.filesDir, "models")
    private val tmpDir = File(context.cacheDir, "tmp")

    /** True after init() succeeds */
    var isReady: Boolean = false
        private set

    /**
     * Extract native binaries from assets if not already present.
     * Call once at app startup (idempotent).
     */
    suspend fun init(): Boolean = withContext(Dispatchers.IO) {
        try {
            binDir.mkdirs()
            modelsDir.mkdirs()
            tmpDir.mkdirs()

            // Extract busybox
            extractAsset("bin/busybox", File(binDir, "busybox"))

            // Extract llama-server
            extractAsset("bin/llama-server", File(binDir, "llama-server"))

            // Create busybox symlinks for common commands
            val commands = listOf(
                "sh", "wget", "curl", "ls", "cat", "grep", "sed", "awk",
                "tar", "gzip", "gunzip", "cp", "mv", "rm", "mkdir",
                "chmod", "kill", "ps", "top", "df", "du", "head", "tail",
                "wc", "sort", "uniq", "find", "xargs", "tee", "nohup",
            )
            val busybox = File(binDir, "busybox")
            for (cmd in commands) {
                val link = File(binDir, cmd)
                if (!link.exists()) {
                    // Android doesn't have ln -s in all versions,
                    // so we use busybox itself to create the symlink
                    Runtime.getRuntime().exec(
                        arrayOf(busybox.absolutePath, "ln", "-sf",
                            busybox.absolutePath, link.absolutePath)
                    ).waitFor()
                }
            }

            isReady = true
            true
        } catch (e: Exception) {
            false
        }
    }

    /**
     * Execute a shell command with the mesh environment.
     * Returns ShellResult with stdout, stderr, exitCode.
     */
    suspend fun exec(
        command: String,
        env: Map<String, String> = emptyMap(),
        timeoutMs: Long = 30_000,
    ): ShellResult = withContext(Dispatchers.IO) {
        val fullEnv = buildMap {
            put("PATH", "${binDir.absolutePath}:/system/bin:/system/xbin")
            put("HOME", context.filesDir.absolutePath)
            put("TMPDIR", tmpDir.absolutePath)
            put("LD_LIBRARY_PATH", "/system/lib64:/system/lib")
            put("MODELS_DIR", modelsDir.absolutePath)
            putAll(env)
        }

        try {
            val process = ProcessBuilder("sh", "-c", command)
                .directory(context.filesDir)
                .also { pb ->
                    pb.environment().clear()
                    pb.environment().putAll(fullEnv)
                }
                .redirectErrorStream(false)
                .start()

            val stdout = process.inputStream.bufferedReader().readText()
            val stderr = process.errorStream.bufferedReader().readText()

            val finished = process.waitFor(timeoutMs, java.util.concurrent.TimeUnit.MILLISECONDS)
            if (!finished) {
                process.destroyForcibly()
                return@withContext ShellResult(
                    stdout = stdout,
                    stderr = "TIMEOUT after ${timeoutMs}ms",
                    exitCode = -1,
                )
            }

            ShellResult(
                stdout = stdout.trim(),
                stderr = stderr.trim(),
                exitCode = process.exitValue(),
            )
        } catch (e: Exception) {
            ShellResult(stdout = "", stderr = e.message ?: "exec failed", exitCode = -1)
        }
    }

    /**
     * Get the path to the models directory.
     */
    fun getModelsDir(): File = modelsDir

    /**
     * Get the path to a specific binary.
     */
    fun getBinaryPath(name: String): File = File(binDir, name)

    private fun extractAsset(assetPath: String, target: File) {
        if (target.exists() && target.length() > 0) return  // Already extracted
        context.assets.open(assetPath).use { input ->
            target.outputStream().use { output ->
                input.copyTo(output)
            }
        }
        target.setExecutable(true, false)
    }
}

data class ShellResult(
    val stdout: String,
    val stderr: String,
    val exitCode: Int,
) {
    val isSuccess get() = exitCode == 0
}
```

### 2. `service/InferenceRunner.kt` (~180 LOC)

Gestiona el proceso llama-server: start, stop, health check.

```kotlin
package com.gredinlabs.gimomesh.service

import android.content.Context
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Manages the llama.cpp inference server process.
 *
 * Starts llama-server with the selected model on a local port.
 * Monitors health via /health endpoint.
 * Reports status changes via StateFlow.
 */
class InferenceRunner(
    private val context: Context,
    private val shell: ShellEnvironment,
) {
    enum class Status { STOPPED, STARTING, RUNNING, ERROR }

    private val _status = MutableStateFlow(Status.STOPPED)
    val status: StateFlow<Status> = _status

    private var serverProcess: Process? = null
    private var healthJob: Job? = null

    private val healthClient = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(2, TimeUnit.SECONDS)
        .build()

    /**
     * Start llama-server with the given model.
     *
     * @param modelPath  Full path to the .gguf file
     * @param port       Local port for the HTTP server (default 8080)
     * @param threads    Number of CPU threads (default 4)
     * @param contextSize  Context window size (default 2048)
     */
    suspend fun start(
        modelPath: String,
        port: Int = 8080,
        threads: Int = 4,
        contextSize: Int = 2048,
    ): Boolean = withContext(Dispatchers.IO) {
        if (_status.value == Status.RUNNING) return@withContext true

        _status.value = Status.STARTING

        val llamaServer = shell.getBinaryPath("llama-server")
        if (!llamaServer.exists()) {
            _status.value = Status.ERROR
            return@withContext false
        }

        val modelFile = File(modelPath)
        if (!modelFile.exists()) {
            _status.value = Status.ERROR
            return@withContext false
        }

        try {
            // Build command
            val cmd = listOf(
                llamaServer.absolutePath,
                "--model", modelPath,
                "--port", port.toString(),
                "--threads", threads.toString(),
                "--ctx-size", contextSize.toString(),
                "--host", "0.0.0.0",  // Accept connections from Core
                "--log-disable",       // Reduce noise
            )

            val env = mapOf(
                "PATH" to "${shell.getBinaryPath("").parent}:/system/bin",
                "HOME" to context.filesDir.absolutePath,
                "TMPDIR" to context.cacheDir.absolutePath,
                "LD_LIBRARY_PATH" to "/system/lib64:/system/lib",
            )

            serverProcess = ProcessBuilder(cmd)
                .directory(context.filesDir)
                .also { pb ->
                    pb.environment().clear()
                    pb.environment().putAll(env)
                }
                .redirectErrorStream(true)
                .start()

            // Wait for server to be ready (poll /health)
            val ready = waitForHealth(port, timeoutMs = 60_000)
            if (ready) {
                _status.value = Status.RUNNING
                startHealthMonitor(port)
                true
            } else {
                stop()
                _status.value = Status.ERROR
                false
            }
        } catch (e: Exception) {
            _status.value = Status.ERROR
            false
        }
    }

    /**
     * Stop the inference server.
     */
    fun stop() {
        healthJob?.cancel()
        healthJob = null
        serverProcess?.destroyForcibly()
        serverProcess = null
        _status.value = Status.STOPPED
    }

    /**
     * Check if the server is responding.
     */
    suspend fun isHealthy(port: Int = 8080): Boolean = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("http://127.0.0.1:$port/health")
                .get()
                .build()
            healthClient.newCall(request).execute().use { it.isSuccessful }
        } catch (e: Exception) {
            false
        }
    }

    private suspend fun waitForHealth(port: Int, timeoutMs: Long): Boolean {
        val start = System.currentTimeMillis()
        while (System.currentTimeMillis() - start < timeoutMs) {
            if (isHealthy(port)) return true
            delay(1_000)  // Check every second
        }
        return false
    }

    private fun startHealthMonitor(port: Int) {
        healthJob = CoroutineScope(Dispatchers.IO).launch {
            while (isActive) {
                delay(15_000)  // Check every 15s
                if (!isHealthy(port)) {
                    _status.value = Status.ERROR
                    // Could attempt auto-restart here
                }
            }
        }
    }
}
```

### 3. `service/MeshService.kt` — MODIFICAR

Este archivo ya existe (es el foreground service que corre el mesh loop).
Necesita integrar ShellEnvironment + InferenceRunner en su lifecycle.

**Cambios necesarios** (busca el `MeshService` existente y agrega):

```kotlin
// En onCreate o onStartCommand:
private lateinit var shell: ShellEnvironment
private lateinit var inference: InferenceRunner

// En el metodo de inicio:
shell = ShellEnvironment(this)
shell.init()  // Extract binaries

inference = InferenceRunner(this, shell)

// Despues de que el modelo esta descargado y settings cargados:
val modelPath = "${filesDir}/models/${settings.model}.gguf"
inference.start(
    modelPath = modelPath,
    port = settings.inferencePort,
    threads = settings.threads,
    contextSize = settings.contextSize,
)

// En heartbeat, reportar modelo cargado:
// HeartbeatPayload(..., modelLoaded = settings.model, inferenceEndpoint = "http://<ip>:${settings.inferencePort}")

// En onDestroy:
inference.stop()
```

---

## Assets a incluir

Crear directorio `app/src/main/assets/bin/` con:

### Obtener busybox (arm64 static)

```bash
# Descargar busybox static para arm64
wget https://busybox.net/downloads/binaries/1.35.0-arm64-linux-musl/busybox -O app/src/main/assets/bin/busybox
```

**Alternativa**: Si no se consigue la version exacta, buscar en:
- https://github.com/niclas68/busybox-android-builds/releases
- https://github.com/niclas68/bbxy/releases

El binario debe ser **static linked, arm64, ~1.8MB**.

### Obtener llama-server (arm64)

```bash
# Compilar llama.cpp para Android arm64 o usar release precompilado
# Ver: https://github.com/ggml-org/llama.cpp/releases
# Buscar: llama-server-android-arm64

# O compilar con NDK:
cmake -B build-android \
  -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
  -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-28 \
  -DGGML_OPENMP=OFF \
  -DCMAKE_BUILD_TYPE=Release

cmake --build build-android --target llama-server -j$(nproc)
cp build-android/bin/llama-server app/src/main/assets/bin/
```

**Nota**: Si no puedes compilar ahora, crea los archivos placeholder vacios.
El ShellEnvironment.init() los extraera cuando esten disponibles.

---

## Archivos a MODIFICAR

### 1. `data/store/SettingsStore.kt`

Agregar keys para inference:

```kotlin
// En Keys:
val INFERENCE_RUNNING = booleanPreferencesKey("inference_running")

// En Settings data class:
val inferenceRunning: Boolean = false,

// En settings Flow:
inferenceRunning = prefs[Keys.INFERENCE_RUNNING] ?: false,

// Metodo:
suspend fun updateInferenceRunning(running: Boolean) {
    context.dataStore.edit { it[Keys.INFERENCE_RUNNING] = running }
}
```

### 2. `ui/dashboard/DashboardScreen.kt`

Agregar indicador de estado de inferencia:

```kotlin
// En la seccion de status del dashboard, agregar:
// - Indicador verde/rojo si llama-server esta corriendo
// - Nombre del modelo cargado
// - Puerto de inferencia
// Ejemplo:
// "🟢 qwen2.5:3b — port 8080" o "🔴 Inference stopped"
```

---

## Estructura de archivos final

```
apps/android/gimomesh/app/
├── src/main/
│   ├── assets/
│   │   └── bin/
│   │       ├── busybox          ← ~1.8MB static arm64
│   │       └── llama-server     ← ~5MB static arm64
│   └── java/com/gredinlabs/gimomesh/
│       └── service/
│           ├── MeshService.kt       ← MODIFICAR (integrar shell + inference)
│           ├── ShellEnvironment.kt  ← NUEVO (~120 LOC)
│           └── InferenceRunner.kt   ← NUEVO (~180 LOC)
```

---

## Criterios de aceptacion

1. **Shell init**: Al primer arranque, busybox + llama-server extraidos a filesDir/bin/.
2. **Shell exec**: `shell.exec("busybox --list")` retorna lista de comandos.
3. **Idempotent**: Llamar `init()` multiples veces no re-extrae si ya existen.
4. **Inference start**: `inference.start(modelPath)` lanza llama-server, espera health check.
5. **Inference health**: `inference.isHealthy()` retorna true cuando server responde.
6. **Inference stop**: `inference.stop()` mata el proceso limpiamente.
7. **Status flow**: `inference.status` emite STOPPED → STARTING → RUNNING (o ERROR).
8. **Heartbeat integration**: heartbeat incluye `model_loaded` y `inference_endpoint`.
9. **Dashboard**: Muestra si inferencia esta activa y que modelo.

---

## NO hacer

- NO instalar Termux como app separada — todo esta embebido en el APK
- NO usar JNI/NDK para llamar a llama.cpp — usamos el binario server via Process
- NO hardcodear IPs — el puerto viene de SettingsStore
- NO crear un ViewModel nuevo para InferenceRunner — el MeshService ya tiene lifecycle
- NO tocar OnboardingClient ni SetupWizardScreen (Lote 2)

---

## Test manual

```
1. Instalar APK → completar Setup Wizard (Lote 2)
2. Verificar en logs: "busybox extracted" + "llama-server extracted"
3. Verificar shell:
   adb shell run-as com.gredinlabs.gimomesh ls files/bin/
   → busybox, llama-server, sh, wget, curl, ...
4. Verificar inferencia:
   adb shell run-as com.gredinlabs.gimomesh files/bin/busybox ps
   → llama-server process visible
5. Verificar health:
   adb shell curl http://127.0.0.1:8080/health
   → {"status":"ok"}
6. Dashboard muestra modelo activo + indicador verde
7. Core dashboard muestra heartbeat con model_loaded + inference_endpoint
```

---

## Impacto en APK

| Componente | Tamano |
|---|---|
| busybox static arm64 | ~1.8 MB |
| llama-server arm64 | ~5 MB |
| Kotlin code | ~10 KB |
| **Total** | **~7 MB adicionales** |

Con ProGuard + resource shrinking el impacto neto en el APK release es ~6.5MB.
