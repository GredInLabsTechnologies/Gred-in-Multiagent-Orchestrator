package com.gredinlabs.gimomesh.service

import android.content.Context
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

        if (!shell.isReady) {
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
            val ready = waitForHealth(port, timeoutMs = 60_000)
            if (!ready) {
                stop()
                _status.value = Status.ERROR
                return@withContext false
            }

            _status.value = Status.RUNNING
            startHealthMonitor(port)
            true
        } catch (_: Exception) {
            _status.value = Status.ERROR
            false
        }
    }

    fun stop() {
        healthJob?.cancel()
        healthJob = null
        serverProcess?.destroyForcibly()
        serverProcess = null
        _status.value = Status.STOPPED
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

    suspend fun readOutput(onLine: (String) -> Unit) = withContext(Dispatchers.IO) {
        serverProcess?.inputStream?.bufferedReader()?.use { reader ->
            try {
                reader.forEachLine(onLine)
            } catch (_: Exception) {
                // Process terminated or stream closed.
            }
        }
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
