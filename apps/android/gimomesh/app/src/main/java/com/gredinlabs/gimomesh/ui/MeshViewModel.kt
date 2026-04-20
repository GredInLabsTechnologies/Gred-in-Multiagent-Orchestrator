package com.gredinlabs.gimomesh.ui

import android.app.Application
import android.content.Intent
import android.os.Build
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.gredinlabs.gimomesh.GimoMeshApp
import com.gredinlabs.gimomesh.data.api.GimoCoreClient
import com.gredinlabs.gimomesh.data.model.ConnectionState
import com.gredinlabs.gimomesh.data.model.DeviceMode
import com.gredinlabs.gimomesh.data.model.MeshDevice
import com.gredinlabs.gimomesh.data.model.MeshState
import com.gredinlabs.gimomesh.data.model.OperationalState
import com.gredinlabs.gimomesh.data.store.SettingsStore
import com.gredinlabs.gimomesh.service.HostRuntimeStatus
import com.gredinlabs.gimomesh.service.MeshAgentService
import com.gredinlabs.gimomesh.service.MetricsCollector
import com.gredinlabs.gimomesh.service.SafetyResult
import com.gredinlabs.gimomesh.service.TerminalBuffer
import com.gredinlabs.gimomesh.service.isInferenceSafeNow
import com.gredinlabs.gimomesh.service.isServeMode
import com.gredinlabs.gimomesh.service.resolveControlPlaneBaseUrl
import com.gredinlabs.gimomesh.service.resolveControlPlaneToken
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class MeshViewModel(application: Application) : AndroidViewModel(application) {

    private val app = application as GimoMeshApp
    private val terminalBuffer: TerminalBuffer = app.terminalBuffer
    private val hostRuntimeReporter = app.hostRuntimeReporter
    val settingsStore: SettingsStore = app.settingsStore
    val deviceIdentityStore = app.deviceIdentityStore
    private val metricsCollector = MetricsCollector(application)

    private var coreClient: GimoCoreClient? = null
    private var coreClientKey: String = ""
    private var metricsJob: Job? = null
    private var devicePollJob: Job? = null

    private val _state = MutableStateFlow(MeshState())
    val state: StateFlow<MeshState> = _state.asStateFlow()

    private var currentSettings = SettingsStore.Settings()

    init {
        // G22 fix: runtime-derived flags (inferenceRunning, meshServiceRunning)
        // persisted in DataStore from the last run of the process are stale
        // the moment the JVM comes up — the service and the llama-server child
        // don't survive a process kill. If the user had "RUNNING" before the
        // relaunch, the UI would lie until the service corrected it on its
        // next observer cycle (which, without a running service, never comes).
        //
        // Reset both to false at boot. If the service IS alive (unusual —
        // app kept in background without process kill), its watchInferenceStatus
        // and startMesh paths will re-assert the correct value within one
        // settings-observer tick.
        viewModelScope.launch {
            settingsStore.updateInferenceRunning(false)
            settingsStore.updateMeshServiceRunning(false)
        }
        observeSettings()
        observeTerminal()
        observeHostRuntime()
        startMetricsLoop()
        startDevicePollLoop()
    }

    private fun observeSettings() {
        viewModelScope.launch {
            settingsStore.settings.collect { settings ->
                currentSettings = settings
                rebuildClient(settings)
                _state.update { state ->
                    state.copy(
                        coreUrl = resolveDisplayCoreUrl(settings),
                        deviceId = resolveDeviceId(settings),
                        deviceName = resolveDeviceName(settings),
                        // G13 fix: settings.model is the source of truth. The
                        // previous `.ifBlank` guard froze the default placeholder
                        // "qwen2.5:3b" into state.modelLoaded at boot and the
                        // observer never updated it when the wizard finished a
                        // download and persisted the real model id. Server-
                        // authoritative updates come from applyAuthoritativeDeviceState,
                        // which layers on top and wins when the server has a value.
                        modelLoaded = settings.model,
                        inferenceRunning = settings.inferenceRunning,
                        inferenceAutoStartAllowed = settings.inferenceAutoStartAllowed,
                        inferencePort = settings.inferencePort,
                        inferenceEndpoint = state.inferenceEndpoint.ifBlank {
                            if (settings.inferenceRunning) {
                                buildInferenceEndpoint(settings.inferencePort).orEmpty()
                            } else {
                                ""
                            }
                        },
                        deviceMode = parseDeviceMode(settings.deviceMode),
                        isMeshRunning = settings.meshServiceRunning,
                        isLinked = if (settings.meshServiceRunning) state.isLinked else false,
                        connectionState = if (settings.meshServiceRunning) {
                            state.connectionState
                        } else {
                            ConnectionState.OFFLINE
                        },
                        operationalState = if (settings.meshServiceRunning) {
                            state.operationalState
                        } else {
                            OperationalState.IDLE
                        },
                    )
                }
            }
        }
    }

    private fun observeTerminal() {
        viewModelScope.launch {
            terminalBuffer.lines.collect { lines ->
                _state.update { it.copy(terminalLines = lines) }
            }
        }
    }

    private fun observeHostRuntime() {
        viewModelScope.launch {
            hostRuntimeReporter.snapshot.collect { snapshot ->
                _state.update { state ->
                    val serveMode = isServeMode(currentSettings)
                    val connectionState = when {
                        !serveMode -> state.connectionState
                        !currentSettings.meshServiceRunning -> ConnectionState.OFFLINE
                        snapshot.status == HostRuntimeStatus.STARTING -> ConnectionState.RECONNECTING
                        snapshot.status == HostRuntimeStatus.ERROR ||
                            snapshot.status == HostRuntimeStatus.UNAVAILABLE -> ConnectionState.REFUSED
                        else -> state.connectionState
                    }

                    state.copy(
                        hostRuntimeStatus = snapshot.status.name.lowercase(),
                        hostRuntimeAvailable = snapshot.available,
                        hostLanUrl = snapshot.lanUrl,
                        hostWebUrl = snapshot.webUrl,
                        hostMcpUrl = snapshot.mcpUrl,
                        hostRuntimeError = snapshot.error,
                        connectionState = connectionState,
                    )
                }
            }
        }
    }

    private fun startMetricsLoop() {
        metricsJob?.cancel()
        metricsJob = viewModelScope.launch {
            while (isActive) {
                try {
                    val snapshot = metricsCollector.collect()
                    val settings = currentSettings
                    val throttled = snapshot.cpuTempC > settings.cpuWarningTemp ||
                        snapshot.batteryTempC > settings.batteryWarningTemp
                    val lockedOut = snapshot.cpuTempC > settings.cpuLockoutTemp ||
                        snapshot.batteryTempC > settings.batteryLockoutTemp

                    val deferredReason = computeDeferredReason(
                        autoStartAllowed = settings.inferenceAutoStartAllowed,
                        running = settings.inferenceRunning,
                        batteryPercent = snapshot.batteryPercent,
                        cpuTempC = snapshot.cpuTempC,
                        thermalThrottled = throttled,
                        ramPercent = snapshot.ramPercent,
                    )

                    _state.update { state ->
                        state.copy(
                            cpuPercent = snapshot.cpuPercent,
                            ramPercent = snapshot.ramPercent,
                            batteryPercent = snapshot.batteryPercent,
                            cpuTempC = snapshot.cpuTempC,
                            gpuTempC = snapshot.gpuTempC,
                            batteryTempC = snapshot.batteryTempC,
                            thermalThrottled = throttled,
                            thermalLockedOut = lockedOut,
                            inferenceDeferredReason = deferredReason,
                        )
                    }
                } catch (_: Exception) {
                    // Metrics are observational only; keep the UI loop alive.
                }
                delay(METRICS_INTERVAL_MS)
            }
        }
    }

    private fun startDevicePollLoop() {
        devicePollJob?.cancel()
        devicePollJob = viewModelScope.launch {
            while (isActive) {
                val settings = currentSettings
                val client = coreClient

                if (!settings.meshServiceRunning || client == null) {
                    delay(DEVICE_POLL_INTERVAL_MS)
                    continue
                }

                try {
                    val device = client.getDevice(resolveDeviceId(settings))
                    if (device != null) {
                        applyAuthoritativeDeviceState(device)
                    } else if (isServeMode(settings)) {
                        _state.update { state ->
                            state.copy(
                                isLinked = false,
                                operationalState = OperationalState.IDLE,
                                connectionState = if (state.hostRuntimeAvailable) {
                                    ConnectionState.RECONNECTING
                                } else {
                                    ConnectionState.REFUSED
                                },
                            )
                        }
                    } else {
                        _state.update {
                            it.copy(
                                isLinked = false,
                                operationalState = OperationalState.IDLE,
                                connectionState = ConnectionState.OFFLINE,
                            )
                        }
                    }
                } catch (_: Exception) {
                    _state.update { state ->
                        state.copy(
                            isLinked = false,
                            connectionState = if (isServeMode(settings)) {
                                ConnectionState.RECONNECTING
                            } else {
                                ConnectionState.OFFLINE
                            },
                        )
                    }
                }

                delay(DEVICE_POLL_INTERVAL_MS)
            }
        }
    }

    private fun applyAuthoritativeDeviceState(device: MeshDevice) {
        _state.update { state ->
            state.copy(
                isLinked = device.connectionState != ConnectionState.OFFLINE &&
                    device.connectionState != ConnectionState.REFUSED,
                connectionState = device.connectionState,
                operationalState = device.operationalState,
                deviceMode = device.deviceMode,
                healthScore = device.healthScore,
                cpuPercent = device.cpuPercent.takeIf { it >= 0f } ?: state.cpuPercent,
                ramPercent = device.ramPercent.takeIf { it >= 0f } ?: state.ramPercent,
                batteryPercent = device.batteryPercent.takeIf { it >= 0f } ?: state.batteryPercent,
                cpuTempC = device.cpuTempC.takeIf { it >= 0f } ?: state.cpuTempC,
                gpuTempC = device.gpuTempC.takeIf { it >= 0f } ?: state.gpuTempC,
                batteryTempC = device.batteryTempC.takeIf { it >= 0f } ?: state.batteryTempC,
                thermalThrottled = device.thermalThrottled,
                thermalLockedOut = device.thermalLockedOut,
                modelLoaded = device.modelLoaded?.takeIf { it.isNotBlank() } ?: state.modelLoaded,
                inferenceEndpoint = device.inferenceEndpoint.ifBlank { state.inferenceEndpoint },
                activeTaskId = device.activeTaskId,
            )
        }
    }

    private fun rebuildClient(settings: SettingsStore.Settings) {
        val baseUrl = resolveControlPlaneBaseUrl(settings)
        val token = resolveControlPlaneToken(settings)
        val newKey = "$baseUrl|$token"
        if (newKey == coreClientKey) return

        coreClient?.shutdown()
        coreClient = if (token.isNotBlank()) GimoCoreClient(baseUrl, token) else null
        coreClientKey = newKey
    }

    fun toggleMesh() {
        if (currentSettings.meshServiceRunning) {
            stopMesh()
        } else {
            startMesh()
        }
    }

    /**
     * User tapped START on the ModelCard. Sends an intent to the service,
     * which gates on hardware safety before actually launching llama-server.
     */
    fun onStartInference() {
        val context = getApplication<Application>()
        val intent = Intent(context, MeshAgentService::class.java).apply {
            action = MeshAgentService.ACTION_START_INFERENCE
        }
        context.startService(intent)
    }

    fun onStopInference() {
        val context = getApplication<Application>()
        val intent = Intent(context, MeshAgentService::class.java).apply {
            action = MeshAgentService.ACTION_STOP_INFERENCE
        }
        context.startService(intent)
    }

    fun onToggleInferenceAutoStart(allowed: Boolean) {
        viewModelScope.launch {
            settingsStore.updateInferenceAutoStartAllowed(allowed)
        }
    }

    private fun computeDeferredReason(
        autoStartAllowed: Boolean,
        running: Boolean,
        batteryPercent: Float,
        cpuTempC: Float,
        thermalThrottled: Boolean,
        ramPercent: Float,
    ): String {
        if (!autoStartAllowed || running) return ""
        return when (val r = isInferenceSafeNow(batteryPercent, cpuTempC, thermalThrottled, ramPercent)) {
            is SafetyResult.Safe -> ""
            is SafetyResult.Unsafe -> r.reason
        }
    }

    private fun startMesh() {
        val context = getApplication<Application>()
        val intent = Intent(context, MeshAgentService::class.java).apply {
            action = MeshAgentService.ACTION_START
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent)
        } else {
            context.startService(intent)
        }
    }

    private fun stopMesh() {
        val context = getApplication<Application>()
        val intent = Intent(context, MeshAgentService::class.java).apply {
            action = MeshAgentService.ACTION_STOP
        }
        context.startService(intent)
    }

    fun changeMode(mode: String) {
        viewModelScope.launch {
            settingsStore.updateDeviceMode(mode)
        }
    }

    fun toggleModeLock(locked: Boolean) {
        viewModelScope.launch {
            settingsStore.updateModeLocked(locked)
        }
    }

    fun clearTerminal() {
        terminalBuffer.clear()
    }

    // Fase D2-b — opt-in model retention handle exposed to the Settings
    // screen. Valid values: 0 (never), 30, 60, 90. Applies the worker
    // schedule atomically on the same scope so the UI can reflect the
    // change immediately.
    fun setModelRetentionDays(days: Int) {
        viewModelScope.launch {
            settingsStore.updateModelRetentionDays(days)
            com.gredinlabs.gimomesh.service.ModelRetentionWorker.applySchedule(
                getApplication(),
                days,
            )
        }
    }

    // Fase D2-b — one-tap wipe for the "Delete downloaded models" button.
    // Doesn't touch enrollment / settings / keystore. Returns the count
    // of deleted files via the terminal buffer for audit trail.
    fun deleteDownloadedModels() {
        viewModelScope.launch {
            val count = com.gredinlabs.gimomesh.data.store.ModelStorage
                .deleteAllModels(getApplication())
            val message = "deleted $count downloaded model file(s) via Settings"
            terminalBuffer.append(
                com.gredinlabs.gimomesh.data.model.LogSource.SYS,
                message,
            )
            // Clear the stale downloadedModelPath so the wizard re-prompts.
            settingsStore.updateDownloadedModelPath("")
        }
    }

    // Fase D2-b — nuclear reset for the "Delete all GIMO Mesh data" button.
    // Wipes models + DataStore enrollment + Keystore device identity. The
    // next boot lands on the welcome wizard as a fresh install.
    fun deleteAllData() {
        viewModelScope.launch {
            com.gredinlabs.gimomesh.data.store.ModelStorage.deleteAllModels(getApplication())
            deviceIdentityStore.clear()
            // Blank out the enrollment fields in DataStore. We intentionally
            // don't clear UI prefs (thermal limits, theme) to avoid wiping
            // harmless customisations.
            settingsStore.updateCoreUrl("")
            settingsStore.updateToken("")
            settingsStore.updateDeviceId("")
            settingsStore.updateDeviceName("")
            settingsStore.updateLocalDeviceSecret("")
            settingsStore.updateLocalCoreToken("")
            settingsStore.updateDownloadedModelPath("")
            settingsStore.updateActiveWorkspace("default", "Default")
        }
    }

    private fun resolveDisplayCoreUrl(settings: SettingsStore.Settings): String =
        resolveControlPlaneBaseUrl(settings)
            .removePrefix("http://")
            .removePrefix("https://")

    private fun resolveDeviceId(settings: SettingsStore.Settings): String =
        settings.deviceId.ifBlank { Build.MODEL.lowercase().replace(" ", "-") }

    private fun resolveDeviceName(settings: SettingsStore.Settings): String =
        settings.deviceName.ifBlank { "${Build.MANUFACTURER} ${Build.MODEL}" }

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

    private fun buildInferenceEndpoint(port: Int): String? {
        val ip = getLocalIp()
        return if (ip == "0.0.0.0") null else "http://$ip:$port"
    }

    private fun parseDeviceMode(mode: String): DeviceMode = try {
        DeviceMode.valueOf(mode.uppercase())
    } catch (_: Exception) {
        DeviceMode.INFERENCE
    }

    override fun onCleared() {
        super.onCleared()
        metricsJob?.cancel()
        devicePollJob?.cancel()
        coreClient?.shutdown()
    }

    companion object {
        const val METRICS_INTERVAL_MS = 5_000L
        const val DEVICE_POLL_INTERVAL_MS = 5_000L
    }
}
