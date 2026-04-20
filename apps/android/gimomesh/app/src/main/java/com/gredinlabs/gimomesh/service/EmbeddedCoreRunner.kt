package com.gredinlabs.gimomesh.service

import android.content.Context
import android.util.Log
import com.gredinlabs.gimomesh.data.model.LogLevel
import com.gredinlabs.gimomesh.data.model.LogSource
import com.gredinlabs.gimomesh.data.store.SettingsStore
import java.io.File
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/**
 * Owns the lifecycle of the server-mode GIMO Core inside the APK.
 *
 * Fase B — the Python interpreter is Chaquopy-embedded (no subprocess).
 * `gimo_server_entry.py` spawns a daemon thread inside the JVM that runs
 * uvicorn with the unmodified `tools.gimo_server.main:app`. The Kotlin
 * side sees uvicorn exactly like before through the `/health` + `/ready`
 * HTTP endpoints — the process/thread swap is invisible to the health
 * monitor.
 *
 * Runtime layering at start:
 *   1. Rove bundle provides the GIMO Core source tree (tools.gimo_server package)
 *      plus bionic-cross-compiled C/Rust wheels (pydantic_core, cryptography,
 *      psutil) under `extracted/site-packages/`.
 *   2. Chaquopy provides the CPython 3.13 interpreter itself plus the
 *      pure-Python wheels (fastapi, uvicorn, starlette, anyio, …) that
 *      don't need platform-specific binaries.
 *   3. The entrypoint merges both layers into `sys.path` before importing
 *      `tools.gimo_server.main` — rove first so its C/Rust extensions win
 *      over any Chaquopy duplicates.
 */
class EmbeddedCoreRunner(
    private val context: Context,
    private val shell: ShellEnvironment,
    private val terminalBuffer: TerminalBuffer,
    private val reporter: HostRuntimeReporter,
) {
    private val runnerScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val healthClient = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(2, TimeUnit.SECONDS)
        .build()

    @Volatile
    private var pythonStarted: Boolean = false
    private var monitorJob: Job? = null

    suspend fun start(settings: SettingsStore.Settings): Boolean = withContext(Dispatchers.IO) {
        if (pythonStarted && isReady()) {
            reporter.setStatus(
                status = HostRuntimeStatus.READY,
                available = true,
                lanUrl = buildLanUrl(),
            )
            return@withContext true
        }

        val runtime = shell.getEmbeddedCoreRuntime()
        if (runtime == null) {
            reporter.setStatus(
                status = HostRuntimeStatus.UNAVAILABLE,
                available = false,
                error = "embedded GIMO Core runtime missing",
            )
            terminalBuffer.append(
                LogSource.SYS,
                "embedded GIMO Core runtime missing (runtime/gimo-core-runtime.json not found)",
                LogLevel.WARN,
            )
            return@withContext false
        }

        if (settings.localCoreToken.isBlank()) {
            reporter.setStatus(
                status = HostRuntimeStatus.ERROR,
                available = true,
                error = "local control token missing",
            )
            terminalBuffer.append(
                LogSource.SYS,
                "embedded GIMO Core cannot start without local control token",
                LogLevel.ERROR,
            )
            return@withContext false
        }

        stop(forceOnly = true)
        reporter.setStatus(status = HostRuntimeStatus.STARTING, available = true)
        terminalBuffer.append(LogSource.SYS, "starting embedded GIMO Core (chaquopy)")
        Log.i(TAG_RUN, "starting embedded GIMO Core (chaquopy) repoRoot=${runtime.repoRoot}")

        try {
            ChaquopyBridge.ensureStarted(context)

            val rovePaths = resolveRovePaths(runtime)
            Log.i(TAG_RUN, "rove paths: site=${rovePaths.sitePackages} repo=${rovePaths.repoRoot} extra=${rovePaths.extraPaths} wheelhouse=${runtime.wheelhouseDir?.absolutePath}")
            val envMap = buildRuntimeEnvironment(settings, runtime)
            val args = mutableMapOf<String, Any>(
                "rove_site_packages" to rovePaths.sitePackages,
                "rove_repo_root" to rovePaths.repoRoot,
                "rove_extra_paths" to rovePaths.extraPaths,
                "rove_wheelhouse_dir" to (runtime.wheelhouseDir?.absolutePath ?: ""),
                "rove_wheelhouse_target" to File(runtime.rootDir, "wheelhouse-site-packages").absolutePath,
                "host" to "0.0.0.0",
                "port" to LOCAL_CORE_PORT,
                "env" to envMap,
            )

            ChaquopyBridge.startServer(args)
            Log.i(TAG_RUN, "ChaquopyBridge.startServer returned")
            pythonStarted = true

            val ready = waitForReady(timeoutMs = 60_000)
            if (!ready) {
                stop(forceOnly = true)
                reporter.setStatus(
                    status = HostRuntimeStatus.ERROR,
                    available = true,
                    error = "embedded GIMO Core failed readiness check",
                )
                terminalBuffer.append(
                    LogSource.SYS,
                    "embedded GIMO Core failed readiness check",
                    LogLevel.ERROR,
                )
                return@withContext false
            }

            reporter.setStatus(
                status = HostRuntimeStatus.READY,
                available = true,
                lanUrl = buildLanUrl(),
            )
            terminalBuffer.append(LogSource.SYS, "embedded GIMO Core ready on $LOCAL_CORE_URL")
            startHealthMonitor()
            true
        } catch (e: Exception) {
            Log.e(TAG_RUN, "embedded core start failed", e)
            stop(forceOnly = true)
            reporter.setStatus(
                status = HostRuntimeStatus.ERROR,
                available = true,
                error = e.message ?: "embedded GIMO Core failed to start",
            )
            terminalBuffer.append(
                LogSource.SYS,
                "embedded GIMO Core start failed: ${e.message}",
                LogLevel.ERROR,
            )
            false
        }
    }

    companion object {
        private const val TAG_RUN = "EmbeddedCoreRunner"
    }

    suspend fun stop(forceOnly: Boolean = false) {
        monitorJob?.cancel()
        monitorJob = null

        if (!pythonStarted) {
            reporter.reset()
            return
        }

        if (!forceOnly) {
            requestGracefulShutdown()
        }

        // Signal uvicorn + wait for the daemon thread to exit. The
        // interpreter itself stays up (Chaquopy singleton — cannot be
        // torn down without killing the JVM). On next start() we'll
        // spin a fresh daemon thread for uvicorn.
        ChaquopyBridge.stopServer()
        val exited = ChaquopyBridge.waitForServerShutdown(timeoutSeconds = 5.0)
        if (!exited) {
            terminalBuffer.append(
                LogSource.SYS,
                "embedded GIMO Core did not shut down within 5s (leaked thread)",
                LogLevel.WARN,
            )
        }
        pythonStarted = false
        reporter.reset()
    }

    suspend fun isHealthy(): Boolean = withContext(Dispatchers.IO) {
        if (!pythonStarted) return@withContext false
        try {
            val request = Request.Builder().url("$LOCAL_CORE_URL/health").get().build()
            healthClient.newCall(request).execute().use { it.isSuccessful }
        } catch (_: Exception) {
            false
        }
    }

    suspend fun isReady(): Boolean = withContext(Dispatchers.IO) {
        if (!pythonStarted) return@withContext false
        try {
            val request = Request.Builder().url("$LOCAL_CORE_URL/ready").get().build()
            healthClient.newCall(request).execute().use { it.isSuccessful }
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Discovers the `site-packages` directory inside the extracted rove
     * bundle. Convention: any `pythonPathEntries` entry whose basename is
     * `site-packages` wins. Fallback: a subdir named `site-packages` directly
     * under `repoRoot.parentFile`. Any remaining entries become
     * [RovePaths.extraPaths] (os.pathsep-joined for the Python side).
     */
    private data class RovePaths(
        val sitePackages: String,
        val repoRoot: String,
        val extraPaths: String,
    )

    private fun resolveRovePaths(runtime: EmbeddedCoreRuntime): RovePaths {
        // Split the colon-joined path we built in ShellEnvironment back into
        // entries. Android path separator is `:` (Linux) so this is safe.
        val entries = runtime.pythonPath.split(":").filter { it.isNotBlank() }
        var sitePackages = ""
        val extras = mutableListOf<String>()
        for (entry in entries) {
            if (sitePackages.isEmpty() && File(entry).name == "site-packages") {
                sitePackages = entry
            } else {
                extras += entry
            }
        }
        if (sitePackages.isEmpty()) {
            val parent = runtime.repoRoot.parentFile
            val fallback = parent?.let { File(it, "site-packages") }
            if (fallback != null && fallback.isDirectory) sitePackages = fallback.absolutePath
        }
        return RovePaths(
            sitePackages = sitePackages,
            repoRoot = runtime.repoRoot.absolutePath,
            extraPaths = extras.joinToString(":"),
        )
    }

    private fun buildRuntimeEnvironment(
        settings: SettingsStore.Settings,
        runtime: EmbeddedCoreRuntime,
    ): Map<String, String> = shell.buildEnvironment(
        buildMap {
            putAll(runtime.extraEnv)
            if (runtime.pythonPath.isNotBlank()) {
                put("PYTHONPATH", runtime.pythonPath)
            }
            put("ORCH_PORT", LOCAL_CORE_PORT.toString())
            put("ORCH_OPERATOR_TOKEN", settings.localCoreToken)
            put("GIMO_MESH_HOST_ENABLED", "true")
            put("GIMO_MESH_HOST_DEVICE_ID", resolveDeviceId(settings))
            put("GIMO_MESH_HOST_DEVICE_NAME", resolveDeviceName(settings))
            // rev 2 Cambio 4 — derive device_mode from the hybrid capability pills
            // so toggling "Serve" in Settings flips the embedded Core into server
            // mode (binds 0.0.0.0, auto-enables mDNS) without requiring the user
            // to separately set `deviceMode`.
            put("GIMO_MESH_HOST_DEVICE_MODE", resolveEffectiveDeviceMode(settings))
            put("GIMO_MESH_HOST_DEVICE_CLASS", "smartphone")
            put("GIMO_MESH_HOST_INFERENCE_ENDPOINT", "")
        }
    )

    /** rev 2 Cambio 4 — single source of truth for device_mode derived from
     *  the UI pills. `Serve` always wins (a host that serves must bind LAN);
     *  otherwise we degrade to hybrid / utility / inference in that order. */
    private fun resolveEffectiveDeviceMode(settings: SettingsStore.Settings): String {
        if (settings.hybridServe) return "server"
        val inf = settings.hybridInference
        val util = settings.hybridUtility
        return when {
            inf && util -> "hybrid"
            util -> "utility"
            inf -> "inference"
            else -> settings.deviceMode.lowercase().ifBlank { "inference" }
        }
    }

    private fun resolveDeviceId(settings: SettingsStore.Settings): String =
        settings.deviceId.ifBlank { "android-${UUID.randomUUID().toString().take(8)}" }

    private fun resolveDeviceName(settings: SettingsStore.Settings): String =
        settings.deviceName.ifBlank { android.os.Build.MODEL ?: "Android host" }

    // Chaquopy routes Python's stdout/stderr to logcat via its own JNI
    // bridge — no custom output pump needed (subprocess.inputStream is
    // gone along with ProcessBuilder). Server-side uvicorn logs show up
    // under the `python.stdout` logcat tag.

    private suspend fun waitForReady(timeoutMs: Long): Boolean {
        val startedAt = System.currentTimeMillis()
        while (System.currentTimeMillis() - startedAt < timeoutMs) {
            if (isReady()) return true
            delay(1_000)
        }
        return false
    }

    private fun startHealthMonitor() {
        monitorJob?.cancel()
        monitorJob = runnerScope.launch {
            while (isActive) {
                delay(15_000)
                val status = when {
                    isReady() -> HostRuntimeStatus.READY
                    isHealthy() -> HostRuntimeStatus.DEGRADED
                    else -> HostRuntimeStatus.ERROR
                }
                reporter.setStatus(
                    status = status,
                    available = true,
                    lanUrl = buildLanUrl(),
                    error = if (status == HostRuntimeStatus.ERROR) "embedded GIMO Core health check failed" else "",
                )
                if (status == HostRuntimeStatus.ERROR) {
                    terminalBuffer.append(
                        LogSource.SYS,
                        "embedded GIMO Core health check failed",
                        LogLevel.ERROR,
                    )
                    return@launch
                }
            }
        }
    }

    private suspend fun requestGracefulShutdown() {
        try {
            val request = Request.Builder()
                .url("$LOCAL_CORE_URL/ops/shutdown")
                .post(ByteArray(0).toRequestBody(null))
                .build()
            healthClient.newCall(request).execute().close()
        } catch (_: Exception) {
            // Fall back to process destroy path below.
        }
    }

    private fun buildLanUrl(): String {
        val ip = getLocalIp()
        return if (ip == "0.0.0.0") "" else "http://$ip:$LOCAL_CORE_PORT"
    }

    private fun getLocalIp(): String {
        return try {
            java.net.NetworkInterface.getNetworkInterfaces()?.toList()
                ?.flatMap { it.inetAddresses.toList() }
                ?.firstOrNull { !it.isLoopbackAddress && it is java.net.Inet4Address }
                ?.hostAddress
                ?: "0.0.0.0"
        } catch (_: Exception) {
            "0.0.0.0"
        }
    }
}
