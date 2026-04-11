package com.gredinlabs.gimomesh.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.gredinlabs.gimomesh.GimoMeshApp
import com.gredinlabs.gimomesh.R
import com.gredinlabs.gimomesh.data.api.GimoCoreClient
import com.gredinlabs.gimomesh.data.model.HeartbeatPayload
import com.gredinlabs.gimomesh.data.model.LogLevel
import com.gredinlabs.gimomesh.data.model.LogSource
import com.gredinlabs.gimomesh.data.store.SettingsStore
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

/**
 * Foreground service that keeps the mesh agent alive.
 * Runs heartbeat loop, task polling, and the embedded inference server.
 */
class MeshAgentService : Service() {

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var heartbeatJob: Job? = null
    private var inferenceOutputJob: Job? = null
    private var inferenceStatusJob: Job? = null
    private var taskPollJob: Job? = null

    private lateinit var terminalBuffer: TerminalBuffer
    private lateinit var settingsStore: SettingsStore
    private lateinit var metricsCollector: MetricsCollector
    private lateinit var shell: ShellEnvironment
    private lateinit var inferenceRunner: InferenceRunner
    private var coreClient: GimoCoreClient? = null

    override fun onCreate() {
        super.onCreate()
        val app = application as GimoMeshApp
        terminalBuffer = app.terminalBuffer
        settingsStore = app.settingsStore
        metricsCollector = MetricsCollector(applicationContext)
        shell = ShellEnvironment(applicationContext)
        inferenceRunner = InferenceRunner(applicationContext, shell)
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startMesh()
            ACTION_STOP -> stopMesh()
        }
        return START_NOT_STICKY
    }

    private fun startMesh() {
        startForeground(NOTIFICATION_ID, buildNotification("Mesh active - idle"))

        scope.launch {
            val settings = settingsStore.settings.first()
            val baseUrl = settings.coreUrl.let {
                if (it.startsWith("http")) it else "http://$it"
            }
            if (settings.token.isNotEmpty()) {
                coreClient = GimoCoreClient(baseUrl, settings.token)
            }

            val shellReady = shell.init()
            if (shellReady) {
                terminalBuffer.append(LogSource.SYS, "embedded shell ready - ${shell.getBinaryPath("busybox").parent}")
            } else {
                terminalBuffer.append(
                    LogSource.SYS,
                    "embedded shell unavailable - placeholders or extraction failure",
                    LogLevel.WARN,
                )
            }

            watchInferenceStatus()

            val needsInference = settings.deviceMode in listOf("inference", "hybrid")
            val modelFile = resolveModelFile(settings)
            when {
                needsInference && !shellReady -> {
                    terminalBuffer.append(
                        LogSource.INFER,
                        "inference unavailable - embedded binaries are not ready",
                        LogLevel.WARN,
                    )
                }

                needsInference && modelFile.exists() -> {
                    val started = inferenceRunner.start(
                        modelPath = modelFile.absolutePath,
                        port = settings.inferencePort,
                        threads = settings.threads,
                        contextSize = settings.contextSize,
                    )
                    if (started) {
                        terminalBuffer.append(LogSource.INFER, "llama-server started - port=${settings.inferencePort}")
                        inferenceOutputJob?.cancel()
                        inferenceOutputJob = scope.launch {
                            inferenceRunner.readOutput { line ->
                                terminalBuffer.append(LogSource.INFER, line)
                            }
                        }
                    } else {
                        terminalBuffer.append(LogSource.INFER, "llama-server failed to start", LogLevel.ERROR)
                    }
                }

                !needsInference -> {
                    terminalBuffer.append(
                        LogSource.INFER,
                        "mode=${settings.deviceMode} - inference not required",
                    )
                    startTaskPolling(settings)
                }

                else -> {
                    terminalBuffer.append(
                        LogSource.INFER,
                        "model not found at ${modelFile.path} - inference offline",
                        LogLevel.WARN,
                    )
                }
            }
        }

        heartbeatJob = scope.launch {
            while (isActive) {
                try {
                    val settings = settingsStore.settings.first()
                    val deviceId = settings.deviceId.ifEmpty {
                        android.os.Build.MODEL.lowercase().replace(" ", "-")
                    }
                    val token = settings.token
                    val snapshot = metricsCollector.collect()
                    val statusText = "CPU ${snapshot.cpuPercent.toInt()}% | " +
                        "${snapshot.cpuTempC.toInt()}C | BAT ${snapshot.batteryPercent.toInt()}%"
                    updateNotification("Mesh active - $statusText")

                    val inferenceRunning = inferenceRunner.status.value == InferenceRunner.Status.RUNNING
                    val inferenceEndpoint = if (inferenceRunning) {
                        buildInferenceEndpoint(settings.inferencePort)
                    } else {
                        null
                    }

                    coreClient?.let { client ->
                        try {
                            val payload = HeartbeatPayload(
                                deviceId = deviceId,
                                deviceSecret = token,
                                deviceMode = settings.deviceMode,
                                cpuPercent = snapshot.cpuPercent,
                                ramPercent = snapshot.ramPercent,
                                batteryPercent = snapshot.batteryPercent,
                                cpuTempC = snapshot.cpuTempC,
                                gpuTempC = snapshot.gpuTempC,
                                batteryTempC = snapshot.batteryTempC,
                                modelLoaded = if (inferenceRunning) settings.model else null,
                                inferenceEndpoint = inferenceEndpoint,
                                capabilities = metricsCollector.getDeviceCapabilities(),
                            )
                            client.sendHeartbeat(payload)
                        } catch (e: Exception) {
                            terminalBuffer.append(
                                LogSource.AGENT,
                                "service heartbeat error: ${e.message}",
                                LogLevel.WARN,
                            )
                        }
                    }

                    if (snapshot.cpuTempC > settings.cpuLockoutTemp ||
                        snapshot.batteryTempC > settings.batteryLockoutTemp
                    ) {
                        terminalBuffer.append(
                            LogSource.SYS,
                            "thermal lockout - service stopping inference",
                            LogLevel.ERROR,
                        )
                        inferenceRunner.stop()
                        settingsStore.updateInferenceRunning(false)
                    }
                } catch (_: Exception) {
                    // Keep the loop alive; detailed errors already reach the terminal buffer.
                }

                delay(HEARTBEAT_INTERVAL_MS)
            }
        }
    }

    private fun startTaskPolling(settings: SettingsStore.Settings) {
        taskPollJob?.cancel()
        val deviceId = settings.deviceId.ifEmpty {
            android.os.Build.MODEL.lowercase().replace(" ", "-")
        }
        val token = settings.token
        taskPollJob = scope.launch {
            val executor = TaskExecutor(filesDir, terminalBuffer)
            terminalBuffer.append(
                LogSource.TASK,
                "task poll loop started - ${TASK_POLL_INTERVAL_MS / 1000}s interval",
            )
            while (isActive) {
                try {
                    val tasks = coreClient?.pollTasks(deviceId) ?: emptyList()
                    for (task in tasks) {
                        terminalBuffer.append(
                            LogSource.TASK,
                            ">> ${task.taskType} [${task.taskId.take(8)}]",
                        )
                        val result = executor.execute(task, deviceId, token)
                        coreClient?.submitTaskResult(result)
                        terminalBuffer.append(
                            LogSource.TASK,
                            "<< ${task.taskId.take(8)} ${result.status} ${result.durationMs}ms",
                        )
                    }
                } catch (e: Exception) {
                    terminalBuffer.append(
                        LogSource.TASK,
                        "poll error: ${e.message}",
                        LogLevel.WARN,
                    )
                }
                delay(TASK_POLL_INTERVAL_MS)
            }
        }
    }

    private fun stopMesh() {
        heartbeatJob?.cancel()
        heartbeatJob = null
        inferenceOutputJob?.cancel()
        inferenceOutputJob = null
        inferenceStatusJob?.cancel()
        inferenceStatusJob = null
        taskPollJob?.cancel()
        taskPollJob = null
        inferenceRunner.stop()
        coreClient?.shutdown()
        coreClient = null
        scope.launch { settingsStore.updateInferenceRunning(false) }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "GIMO Mesh Agent",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "Mesh agent status"
            setShowBadge(false)
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(text: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("GIMO Mesh")
            .setContentText(text)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    private fun updateNotification(text: String) {
        getSystemService(NotificationManager::class.java).notify(
            NOTIFICATION_ID,
            buildNotification(text),
        )
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        scope.cancel()
        runBlocking { settingsStore.updateInferenceRunning(false) }
        coreClient?.shutdown()
        inferenceRunner.stop()
        super.onDestroy()
    }

    private fun resolveModelFile(settings: SettingsStore.Settings): File {
        val downloaded = settings.downloadedModelPath
            .takeIf { it.isNotBlank() }
            ?.let(::File)
        if (downloaded?.exists() == true) {
            return downloaded
        }
        return File(filesDir, "models/${settings.model.replace(":", "_")}.gguf")
    }

    private fun watchInferenceStatus() {
        inferenceStatusJob?.cancel()
        inferenceStatusJob = scope.launch {
            var lastStatus: InferenceRunner.Status? = null
            inferenceRunner.status.collect { status ->
                if (lastStatus != null && status != lastStatus) {
                    when (status) {
                        InferenceRunner.Status.STARTING -> terminalBuffer.append(LogSource.INFER, "llama-server starting")
                        InferenceRunner.Status.RUNNING -> terminalBuffer.append(LogSource.INFER, "llama-server healthy")
                        InferenceRunner.Status.ERROR -> terminalBuffer.append(LogSource.INFER, "llama-server health check failed", LogLevel.ERROR)
                        InferenceRunner.Status.STOPPED -> terminalBuffer.append(LogSource.INFER, "llama-server stopped")
                    }
                }
                settingsStore.updateInferenceRunning(status == InferenceRunner.Status.RUNNING)
                lastStatus = status
            }
        }
    }

    private fun buildInferenceEndpoint(port: Int): String? {
        val ip = getLocalIp()
        return if (ip == "0.0.0.0") null else "http://$ip:$port"
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

    companion object {
        const val ACTION_START = "com.gredinlabs.gimomesh.START"
        const val ACTION_STOP = "com.gredinlabs.gimomesh.STOP"
        const val CHANNEL_ID = "gimo_mesh_agent"
        const val NOTIFICATION_ID = 1
        const val HEARTBEAT_INTERVAL_MS = 30_000L
        const val TASK_POLL_INTERVAL_MS = 5_000L
    }
}
