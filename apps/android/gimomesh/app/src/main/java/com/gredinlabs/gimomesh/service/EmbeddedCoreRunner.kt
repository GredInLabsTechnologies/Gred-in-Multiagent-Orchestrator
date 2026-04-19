package com.gredinlabs.gimomesh.service

import android.content.Context
import com.gredinlabs.gimomesh.data.model.LogLevel
import com.gredinlabs.gimomesh.data.model.LogSource
import com.gredinlabs.gimomesh.data.store.SettingsStore
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

    private var serverProcess: Process? = null
    private var monitorJob: Job? = null

    suspend fun start(settings: SettingsStore.Settings): Boolean = withContext(Dispatchers.IO) {
        if (serverProcess?.isAlive == true && isReady()) {
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
        terminalBuffer.append(LogSource.SYS, "starting embedded GIMO Core")

        try {
            val process = ProcessBuilder(
                runtime.pythonBinary.absolutePath,
                "-m",
                "uvicorn",
                "tools.gimo_server.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                LOCAL_CORE_PORT.toString(),
            )
                .directory(runtime.repoRoot)
                .also { builder ->
                    builder.environment().clear()
                    builder.environment().putAll(buildRuntimeEnvironment(settings, runtime))
                    builder.redirectErrorStream(true)
                }
                .start()

            serverProcess = process
            startOutputPump(process)

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

    suspend fun stop(forceOnly: Boolean = false) {
        monitorJob?.cancel()
        monitorJob = null

        if (!forceOnly) {
            requestGracefulShutdown()
        }

        val process = serverProcess
        if (process != null) {
            if (!process.waitFor(5, TimeUnit.SECONDS)) {
                process.destroy()
                if (!process.waitFor(5, TimeUnit.SECONDS)) {
                    process.destroyForcibly()
                }
            }
        }
        serverProcess = null
        reporter.reset()
    }

    suspend fun isHealthy(): Boolean = withContext(Dispatchers.IO) {
        if (serverProcess?.isAlive != true) return@withContext false
        try {
            val request = Request.Builder().url("$LOCAL_CORE_URL/health").get().build()
            healthClient.newCall(request).execute().use { it.isSuccessful }
        } catch (_: Exception) {
            false
        }
    }

    suspend fun isReady(): Boolean = withContext(Dispatchers.IO) {
        if (serverProcess?.isAlive != true) return@withContext false
        try {
            val request = Request.Builder().url("$LOCAL_CORE_URL/ready").get().build()
            healthClient.newCall(request).execute().use { it.isSuccessful }
        } catch (_: Exception) {
            false
        }
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

    private fun startOutputPump(process: Process) {
        runnerScope.launch {
            process.inputStream.bufferedReader().useLines { lines ->
                lines.forEach { line ->
                    terminalBuffer.append(LogSource.SYS, line)
                }
            }
        }
    }

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
