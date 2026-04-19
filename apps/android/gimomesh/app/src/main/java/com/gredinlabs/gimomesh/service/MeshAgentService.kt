package com.gredinlabs.gimomesh.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.net.Uri
import android.os.Build
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
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking

/**
 * Foreground service that owns the Android mesh node lifecycle.
 * It composes serve/inference/utility capabilities from a single runtime owner.
 */
class MeshAgentService : Service() {

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var heartbeatJob: Job? = null
    private var inferenceStatusJob: Job? = null
    private var taskPollJob: Job? = null
    private var settingsObserverJob: Job? = null

    private lateinit var terminalBuffer: TerminalBuffer
    private lateinit var hostRuntimeReporter: HostRuntimeReporter
    private lateinit var settingsStore: SettingsStore
    private lateinit var metricsCollector: MetricsCollector
    private lateinit var shell: ShellEnvironment
    private lateinit var inferenceRunner: InferenceRunner
    private lateinit var coreRunner: EmbeddedCoreRunner

    private var coreClient: GimoCoreClient? = null
    private var coreClientKey: String = ""

    override fun onCreate() {
        super.onCreate()
        val app = application as GimoMeshApp
        terminalBuffer = app.terminalBuffer
        hostRuntimeReporter = app.hostRuntimeReporter
        settingsStore = app.settingsStore
        metricsCollector = MetricsCollector(applicationContext)
        shell = ShellEnvironment(applicationContext)
        inferenceRunner = InferenceRunner(applicationContext, shell)
        coreRunner = EmbeddedCoreRunner(
            context = applicationContext,
            shell = shell,
            terminalBuffer = terminalBuffer,
            reporter = hostRuntimeReporter,
        )
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startMesh()
            ACTION_STOP -> stopMesh()
            ACTION_START_INFERENCE -> scope.launch { requestStartInferenceNow() }
            ACTION_STOP_INFERENCE -> scope.launch { requestStopInference() }
        }
        return START_NOT_STICKY
    }

    private fun startMesh() {
        startForeground(NOTIFICATION_ID, buildNotification("Mesh active - idle"))
        scope.launch { settingsStore.updateMeshServiceRunning(true) }

        settingsObserverJob?.cancel()
        settingsObserverJob = scope.launch {
            // BUGS_LATENTES §H1 fix: ShellEnvironment.init() now boots the three
            // sub-resources (shell / inference / core runtime) independently and
            // surfaces a flag per sub-resource. Log each one honestly instead of
            // the old coupled "shell unavailable" catch-all.
            shell.init()
            val binParent = shell.getBinaryPath("busybox").parent
            if (shell.isShellReady) {
                terminalBuffer.append(LogSource.SYS, "shell sub-resource ready - $binParent")
            } else {
                terminalBuffer.append(
                    LogSource.SYS,
                    "shell sub-resource unavailable (busybox placeholder empty or extraction failure) " +
                        "- utility tasks disabled",
                    LogLevel.WARN,
                )
            }
            if (shell.isInferenceReady) {
                terminalBuffer.append(LogSource.SYS, "inference sub-resource ready (llama-server)")
            } else {
                terminalBuffer.append(
                    LogSource.SYS,
                    "inference sub-resource unavailable (llama-server placeholder empty or not executable) " +
                        "- local inference disabled",
                    LogLevel.WARN,
                )
            }
            if (shell.isCoreRuntimeReady) {
                terminalBuffer.append(LogSource.SYS, "core runtime sub-resource ready (embedded GIMO Core)")
            } else {
                terminalBuffer.append(
                    LogSource.SYS,
                    "core runtime sub-resource unavailable (runtime/gimo-core-runtime.json missing or invalid) " +
                        "- serve mode disabled",
                    LogLevel.WARN,
                )
            }

            watchInferenceStatus()

            settingsStore.settings.collect { rawSettings ->
                val settings = ensureRuntimeIdentity(rawSettings)
                rebuildCoreClient(settings)
                applyRuntimeComposition(settings)
            }
        }

        heartbeatJob?.cancel()
        heartbeatJob = scope.launch {
            while (isActive) {
                try {
                    val settings = ensureRuntimeIdentity(settingsStore.settings.first())
                    rebuildCoreClient(settings)

                    val snapshot = metricsCollector.collect()
                    val statusText = "CPU ${snapshot.cpuPercent.toInt()}% | " +
                        "${snapshot.cpuTempC.toInt()}C | BAT ${snapshot.batteryPercent.toInt()}%"
                    // rev 2 Cambio 5 — include LAN URL in the notification when
                    // the embedded Core is serving, so the operator can tap the
                    // notification to open the web UI on this device.
                    val lanUrl = hostRuntimeReporter.snapshot.value.lanUrl
                    val serveLanUrl = if (isServeMode(settings)) lanUrl else ""
                    updateNotification("Mesh active - $statusText", serveLanUrl)

                    val inferenceRunning = inferenceRunner.status.value == InferenceRunner.Status.RUNNING
                    val inferenceEndpoint = if (inferenceRunning) {
                        buildInferenceEndpoint(settings.inferencePort)
                    } else {
                        null
                    }

                    val deviceSecret = resolveHeartbeatSecret(settings)
                    if (isServeMode(settings) && deviceSecret.isBlank()) {
                        syncLocalDeviceSecret(settings)
                    }

                    val heartbeatSecret = resolveHeartbeatSecret(settingsStore.settings.first())
                    if (heartbeatSecret.isNotBlank()) {
                        coreClient?.let { client ->
                            try {
                                val payload = HeartbeatPayload(
                                    deviceId = resolveDeviceId(settings),
                                    deviceSecret = heartbeatSecret,
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
                    }

                    if (snapshot.cpuTempC > settings.cpuLockoutTemp ||
                        snapshot.batteryTempC > settings.batteryLockoutTemp
                    ) {
                        terminalBuffer.append(
                            LogSource.SYS,
                            "thermal lockout - stopping local runtimes",
                            LogLevel.ERROR,
                        )
                        inferenceRunner.stop()
                        coreRunner.stop()
                        settingsStore.updateInferenceRunning(false)
                    }
                } catch (_: Exception) {
                    // Keep the loop alive; detailed errors already reach the terminal buffer.
                }

                delay(HEARTBEAT_INTERVAL_MS)
            }
        }
    }

    private suspend fun ensureRuntimeIdentity(settings: SettingsStore.Settings): SettingsStore.Settings {
        var changed = false
        if (settings.deviceId.isBlank()) {
            settingsStore.updateDeviceId(resolveDeviceId(settings))
            changed = true
        }
        if (settings.deviceName.isBlank()) {
            settingsStore.updateDeviceName(resolveDeviceName(settings))
            changed = true
        }
        if (isServeMode(settings) && settings.localCoreToken.isBlank()) {
            settingsStore.updateLocalCoreToken(UUID.randomUUID().toString().replace("-", ""))
            terminalBuffer.append(LogSource.SYS, "generated local control token for embedded Core")
            changed = true
        }
        return if (changed) settingsStore.settings.first() else settings
    }

    private fun resolveDeviceId(settings: SettingsStore.Settings): String =
        settings.deviceId.ifBlank { Build.MODEL.lowercase().replace(" ", "-") }

    private fun resolveDeviceName(settings: SettingsStore.Settings): String =
        settings.deviceName.ifBlank { "${Build.MANUFACTURER} ${Build.MODEL}" }

    private suspend fun rebuildCoreClient(settings: SettingsStore.Settings) {
        val baseUrl = resolveControlPlaneBaseUrl(settings)
        val token = resolveControlPlaneToken(settings)
        val newKey = "$baseUrl|$token"
        if (newKey == coreClientKey) return

        coreClient?.shutdown()
        coreClient = if (token.isNotBlank()) GimoCoreClient(baseUrl, token) else null
        coreClientKey = newKey
    }

    private suspend fun applyRuntimeComposition(settings: SettingsStore.Settings) {
        if (isServeMode(settings)) {
            if (coreRunner.start(settings)) {
                syncLocalDeviceSecret(settings)
            }
        } else {
            coreRunner.stop()
        }

        syncInferenceRuntime(settings)

        if (allowsUtility(settings)) {
            startTaskPolling(settings)
        } else {
            stopTaskPolling()
        }
    }

    private suspend fun syncLocalDeviceSecret(settings: SettingsStore.Settings) {
        if (!isServeMode(settings)) return
        val device = coreClient?.getDevice(resolveDeviceId(settings)) ?: return
        if (device.deviceSecret.isNotBlank() && device.deviceSecret != settings.localDeviceSecret) {
            settingsStore.updateLocalDeviceSecret(device.deviceSecret)
        }
    }

    private suspend fun syncInferenceRuntime(settings: SettingsStore.Settings) {
        // Always enforce the stop path — if the mode no longer permits inference,
        // tear down the runner regardless of consent state.
        if (!allowsInference(settings)) {
            if (inferenceRunner.status.value != InferenceRunner.Status.STOPPED) {
                inferenceRunner.stop()
            }
            return
        }

        // KISI invariant: never auto-start llama-server without explicit human
        // consent. If the runner is already RUNNING (because the user tapped
        // START via ACTION_START_INFERENCE), leave it alone.
        if (inferenceRunner.status.value == InferenceRunner.Status.RUNNING) return
        if (!settings.inferenceAutoStartAllowed) return

        val modelFile = resolveModelFile(settings)
        if (!modelFile.exists()) {
            terminalBuffer.append(
                LogSource.INFER,
                "auto-start deferred: no local model available yet",
                LogLevel.WARN,
            )
            return
        }

        // Hardware safety gate: user has authorised auto-start, but the device
        // still vetoes when running inference would harm it.
        val safety = currentSafety()
        if (safety is SafetyResult.Unsafe) {
            terminalBuffer.append(
                LogSource.INFER,
                "auto-start deferred: ${safety.reason}",
                LogLevel.WARN,
            )
            return
        }

        inferenceRunner.start(
            modelPath = modelFile.absolutePath,
            port = settings.inferencePort,
            threads = settings.threads,
            contextSize = settings.contextSize,
        )
    }

    private suspend fun currentSafety(): SafetyResult {
        val snapshot = try {
            metricsCollector.collect()
        } catch (_: Exception) {
            return SafetyResult.Safe // can't measure → don't block; user already authorised
        }
        return isInferenceSafeNow(
            batteryPercent = snapshot.batteryPercent,
            cpuTempC = snapshot.cpuTempC,
            thermalThrottled = snapshot.cpuTempC > 0f && snapshot.cpuTempC > 65f,
            ramPercent = snapshot.ramPercent,
        )
    }

    /**
     * User explicitly tapped START in the ModelCard. Gate on safety but ignore
     * the auto-start consent flag — the tap *is* the consent for this moment.
     */
    private suspend fun requestStartInferenceNow() {
        val settings = settingsStore.settings.first()
        if (!allowsInference(settings)) {
            terminalBuffer.append(LogSource.INFER, "start refused: device mode does not allow inference", LogLevel.WARN)
            return
        }
        if (inferenceRunner.status.value == InferenceRunner.Status.RUNNING) return

        // Ensure shell/inference binaries are resolved. startMesh normally does
        // this, but a user may tap START on the badge before activating the
        // mesh node — initialise on-demand so the path works either way.
        if (!shell.isInferenceReady) {
            try { shell.init() } catch (_: Exception) { /* keep flow going */ }
        }
        if (!shell.isInferenceReady) {
            terminalBuffer.append(
                LogSource.INFER,
                "start refused: llama-server binary missing or not executable",
                LogLevel.ERROR,
            )
            return
        }

        val modelFile = resolveModelFile(settings)
        if (!modelFile.exists()) {
            terminalBuffer.append(LogSource.INFER, "start refused: no model downloaded yet", LogLevel.WARN)
            return
        }

        val safety = currentSafety()
        if (safety is SafetyResult.Unsafe) {
            terminalBuffer.append(LogSource.INFER, "start deferred: ${safety.reason}", LogLevel.WARN)
            return
        }

        terminalBuffer.append(LogSource.INFER, "user requested llama-server start")
        inferenceRunner.start(
            modelPath = modelFile.absolutePath,
            port = settings.inferencePort,
            threads = settings.threads,
            contextSize = settings.contextSize,
        )
    }

    private suspend fun requestStopInference() {
        if (inferenceRunner.status.value == InferenceRunner.Status.STOPPED) return
        terminalBuffer.append(LogSource.INFER, "user requested llama-server stop")
        inferenceRunner.stop()
    }

    private fun startTaskPolling(settings: SettingsStore.Settings) {
        val deviceId = resolveDeviceId(settings)
        val deviceSecret = resolveHeartbeatSecret(settings)
        if (deviceSecret.isBlank()) return
        if (taskPollJob?.isActive == true) return

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
                        val result = executor.execute(task, deviceId, deviceSecret)
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

    private fun stopTaskPolling() {
        taskPollJob?.cancel()
        taskPollJob = null
    }

    private fun stopMesh() {
        heartbeatJob?.cancel()
        heartbeatJob = null
        settingsObserverJob?.cancel()
        settingsObserverJob = null
        inferenceStatusJob?.cancel()
        inferenceStatusJob = null
        stopTaskPolling()
        runBlocking {
            coreRunner.stop()
            inferenceRunner.stop()
            settingsStore.updateInferenceRunning(false)
            settingsStore.updateMeshServiceRunning(false)
        }
        coreClient?.shutdown()
        coreClient = null
        coreClientKey = ""
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

    private fun buildNotification(text: String, lanUrl: String = ""): Notification {
        val builder = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(
                if (lanUrl.isNotBlank()) "GIMO Mesh — serving on LAN" else "GIMO Mesh",
            )
            .setContentText(text)
            .setOngoing(true)
            .setSilent(true)

        // rev 2 Cambio 5 — when the host is serving on the LAN, surface a deep
        // link to the web UI so an operator tapping the notification lands
        // directly on the dashboard of the just-started Core. Falls back to
        // plain text when there is no reachable LAN URL.
        if (lanUrl.isNotBlank()) {
            val viewIntent = Intent(Intent.ACTION_VIEW, Uri.parse(lanUrl)).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
            }
            val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            } else {
                PendingIntent.FLAG_UPDATE_CURRENT
            }
            val pendingIntent = PendingIntent.getActivity(this, 0, viewIntent, flags)
            builder.setContentIntent(pendingIntent)
            builder.setStyle(
                NotificationCompat.BigTextStyle().bigText("$text\nOpen $lanUrl"),
            )
        }

        return builder.build()
    }

    private fun updateNotification(text: String, lanUrl: String = "") {
        getSystemService(NotificationManager::class.java).notify(
            NOTIFICATION_ID,
            buildNotification(text, lanUrl),
        )
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        scope.cancel()
        runBlocking {
            settingsStore.updateInferenceRunning(false)
            settingsStore.updateMeshServiceRunning(false)
            coreRunner.stop()
        }
        hostRuntimeReporter.reset()
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
        const val ACTION_START_INFERENCE = "com.gredinlabs.gimomesh.START_INFERENCE"
        const val ACTION_STOP_INFERENCE = "com.gredinlabs.gimomesh.STOP_INFERENCE"
        const val CHANNEL_ID = "gimo_mesh_agent"
        const val NOTIFICATION_ID = 1
        const val HEARTBEAT_INTERVAL_MS = 30_000L
        const val TASK_POLL_INTERVAL_MS = 5_000L
    }
}
