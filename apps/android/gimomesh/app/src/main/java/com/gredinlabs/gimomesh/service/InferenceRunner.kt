package com.gredinlabs.gimomesh.service

import android.content.Context
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Manages the embedded llama-server process and its health state.
 */
class InferenceRunner(
    private val context: Context,
    private val shell: ShellEnvironment,
) {
    enum class Status { STOPPED, STARTING, RUNNING, ERROR }

    private val runnerScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val _status = MutableStateFlow(Status.STOPPED)
    val status: StateFlow<Status> = _status.asStateFlow()

    private var serverProcess: Process? = null
    private var healthJob: Job? = null
    private var outputDrainJob: Job? = null

    private val healthClient = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(2, TimeUnit.SECONDS)
        .build()

    suspend fun start(
        modelPath: String,
        port: Int = 8080,
        threads: Int = 4,
        contextSize: Int = 2048,
    ): Boolean = withContext(Dispatchers.IO) {
        if (_status.value == Status.RUNNING && serverProcess?.isAlive == true) {
            return@withContext true
        }

        stop()
        _status.value = Status.STARTING

        if (!shell.isInferenceReady) {
            _status.value = Status.ERROR
            return@withContext false
        }

        val llamaServer = shell.getBinaryPath("llama-server")
        val modelFile = File(modelPath)
        if (!llamaServer.exists() || llamaServer.length() <= 0L || !modelFile.exists()) {
            _status.value = Status.ERROR
            return@withContext false
        }

        try {
            val process = ProcessBuilder(
                llamaServer.absolutePath,
                "--model", modelPath,
                "--port", port.toString(),
                "--threads", threads.toString(),
                "--ctx-size", contextSize.toString(),
                "--host", "0.0.0.0",
                "--log-disable",
            )
                .directory(context.filesDir)
                .also { builder ->
                    builder.environment().clear()
                    builder.environment().putAll(shell.buildEnvironment())
                }
                .redirectErrorStream(true)
                .start()

            serverProcess = process

            // G19 fix: drain the merged stdout/stderr stream off-thread so
            // the 64KB pipe buffer never fills. If `--log-disable` fails or
            // the model emits prelim logs (which llama-server does during
            // gguf load), the process would block otherwise and the health
            // wait would time out misleadingly. We keep the first 100 lines
            // in terminalBuffer for model-load diagnostics.
            startOutputDrain(process)

            val ready = waitForHealth(port, timeoutMs = 60_000)
            if (!ready) {
                stop()
                _status.value = Status.ERROR
                return@withContext false
            }

            _status.value = Status.RUNNING
            startHealthMonitor(port)
            true
        } catch (e: Exception) {
            // Keep a single ERROR log so future silent failures are diagnosable.
            // Previous swallowed catch hid a SELinux permission denial for hours.
            Log.e(TAG, "llama-server start() failed", e)
            _status.value = Status.ERROR
            false
        }
    }

    private companion object {
        const val TAG = "InferenceRunner"
    }

    fun stop() {
        healthJob?.cancel()
        healthJob = null
        outputDrainJob?.cancel()
        outputDrainJob = null
        serverProcess?.destroyForcibly()
        serverProcess = null
        _status.value = Status.STOPPED
    }

    /**
     * G19: read the merged stdout/stderr off-thread so the 64KB pipe buffer
     * never fills. The first ~100 lines are tagged at INFO in logcat for
     * model-load diagnostics; after that, we just drain to /dev/null.
     */
    private fun startOutputDrain(process: Process) {
        outputDrainJob?.cancel()
        outputDrainJob = runnerScope.launch {
            try {
                process.inputStream.bufferedReader().use { reader ->
                    var count = 0
                    while (isActive) {
                        val line = reader.readLine() ?: break
                        if (count < 100) {
                            Log.i(TAG, "llama-server: $line")
                        }
                        count++
                    }
                }
            } catch (_: Exception) {
                // Stream closed — expected when process exits.
            }
        }
    }

    suspend fun isHealthy(port: Int = 8080): Boolean = withContext(Dispatchers.IO) {
        if (serverProcess?.isAlive != true) return@withContext false
        try {
            val request = Request.Builder()
                .url("http://127.0.0.1:$port/health")
                .get()
                .build()
            healthClient.newCall(request).execute().use { it.isSuccessful }
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Legacy API kept for callers that expect to pull lines on demand. With
     * G19 the stdout is drained automatically in startOutputDrain — this
     * method is a no-op when the drain is active, because both would compete
     * for the same stream. Left in place so external callers still compile.
     */
    @Suppress("UNUSED_PARAMETER")
    suspend fun readOutput(onLine: (String) -> Unit) = withContext(Dispatchers.IO) {
        // Intentionally empty; see startOutputDrain.
    }

    private suspend fun waitForHealth(port: Int, timeoutMs: Long): Boolean {
        val start = System.currentTimeMillis()
        while (System.currentTimeMillis() - start < timeoutMs) {
            if (isHealthy(port)) return true
            delay(1_000)
        }
        return false
    }

    private fun startHealthMonitor(port: Int) {
        healthJob?.cancel()
        healthJob = runnerScope.launch {
            while (isActive) {
                delay(15_000)
                if (!isHealthy(port)) {
                    _status.value = Status.ERROR
                    return@launch
                }
            }
        }
    }
}
