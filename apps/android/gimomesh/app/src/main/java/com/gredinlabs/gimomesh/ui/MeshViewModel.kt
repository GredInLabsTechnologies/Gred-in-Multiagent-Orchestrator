package com.gredinlabs.gimomesh.ui

import android.app.Application
import android.content.Intent
import android.os.Build
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.gredinlabs.gimomesh.GimoMeshApp
import com.gredinlabs.gimomesh.data.api.GimoCoreClient
import com.gredinlabs.gimomesh.data.model.*
import com.gredinlabs.gimomesh.data.store.SettingsStore
import com.gredinlabs.gimomesh.service.MeshAgentService
import com.gredinlabs.gimomesh.service.MetricsCollector
import com.gredinlabs.gimomesh.service.TerminalBuffer
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class MeshViewModel(application: Application) : AndroidViewModel(application) {

    private val app = application as GimoMeshApp
    private val terminalBuffer: TerminalBuffer = app.terminalBuffer
    val settingsStore: SettingsStore = app.settingsStore
    private val metricsCollector = MetricsCollector(application)

    private var coreClient: GimoCoreClient? = null
    private var metricsJob: Job? = null
    private var heartbeatJob: Job? = null

    private val _state = MutableStateFlow(MeshState())
    val state: StateFlow<MeshState> = _state.asStateFlow()

    // Current settings snapshot (updated reactively)
    private var currentSettings = SettingsStore.Settings()

    init {
        // Observe settings and rebuild client when they change
        viewModelScope.launch {
            settingsStore.settings.collect { settings ->
                currentSettings = settings
                rebuildClient(settings)
                _state.update {
                    it.copy(
                        coreUrl = settings.coreUrl.removePrefix("http://").removePrefix("https://"),
                        deviceId = settings.deviceId.ifEmpty { Build.MODEL.lowercase().replace(" ", "-") },
                        deviceName = settings.deviceName.ifEmpty { "${Build.MANUFACTURER} ${Build.MODEL}" },
                        modelLoaded = settings.model,
                        inferenceRunning = settings.inferenceRunning,
                        inferencePort = settings.inferencePort,
                        inferenceEndpoint = if (settings.inferenceRunning) {
                            buildInferenceEndpoint(settings.inferencePort).orEmpty()
                        } else {
                            ""
                        },
                        deviceMode = parseDeviceMode(settings.deviceMode),
                    )
                }
            }
        }

        // Observe terminal buffer → state
        viewModelScope.launch {
            terminalBuffer.lines.collect { lines ->
                _state.update { it.copy(terminalLines = lines) }
            }
        }
    }

    private fun rebuildClient(settings: SettingsStore.Settings) {
        coreClient?.shutdown()
        val baseUrl = settings.coreUrl.let {
            if (it.startsWith("http")) it else "http://$it"
        }
        coreClient = if (settings.token.isNotEmpty()) {
            GimoCoreClient(baseUrl, settings.token)
        } else null
    }

    fun toggleMesh() {
        val running = _state.value.isMeshRunning
        if (running) {
            stopMesh()
        } else {
            startMesh()
        }
    }

    private fun startMesh() {
        _state.update {
            it.copy(
                isMeshRunning = true,
                connectionState = ConnectionState.CONNECTED,
                isLinked = true,
            )
        }

        terminalBuffer.append(
            LogSource.AGENT,
            "mesh agent started — device=${_state.value.deviceId}",
        )
        terminalBuffer.append(
            LogSource.SYS,
            "soc=${Build.HARDWARE} model=${Build.MODEL}",
        )

        // Start foreground service
        val ctx = getApplication<Application>()
        val intent = Intent(ctx, MeshAgentService::class.java).apply {
            action = MeshAgentService.ACTION_START
        }
        ctx.startForegroundService(intent)

        // Start local metrics collection loop
        metricsJob = viewModelScope.launch {
            while (isActive) {
                try {
                    val snapshot = metricsCollector.collect()
                    val settings = currentSettings

                    // Thermal protection
                    val throttled = snapshot.cpuTempC > settings.cpuWarningTemp ||
                            snapshot.batteryTempC > settings.batteryWarningTemp
                    val lockedOut = snapshot.cpuTempC > settings.cpuLockoutTemp ||
                            snapshot.batteryTempC > settings.batteryLockoutTemp
                    val lowBattery = snapshot.batteryPercent in 0f..settings.minBatteryPercent.toFloat()

                    _state.update {
                        it.copy(
                            cpuPercent = snapshot.cpuPercent,
                            ramPercent = snapshot.ramPercent,
                            batteryPercent = snapshot.batteryPercent,
                            cpuTempC = snapshot.cpuTempC,
                            gpuTempC = snapshot.gpuTempC,
                            batteryTempC = snapshot.batteryTempC,
                            thermalThrottled = throttled,
                            thermalLockedOut = lockedOut,
                            healthScore = computeHealthScore(snapshot, throttled, lockedOut),
                        )
                    }

                    if (lockedOut || lowBattery) {
                        val reason = if (lockedOut) "thermal lockout" else "low battery"
                        terminalBuffer.append(LogSource.SYS, "⚠ $reason — stopping mesh", LogLevel.WARN)
                        stopMesh()
                        return@launch
                    }
                } catch (e: Exception) {
                    terminalBuffer.append(LogSource.SYS, "metrics error: ${e.message}", LogLevel.ERROR)
                }
                delay(METRICS_INTERVAL_MS)
            }
        }

        // Start heartbeat loop
        heartbeatJob = viewModelScope.launch {
            while (isActive) {
                delay(HEARTBEAT_INTERVAL_MS)
                sendHeartbeat()
            }
        }
    }

    private fun stopMesh() {
        metricsJob?.cancel()
        metricsJob = null
        heartbeatJob?.cancel()
        heartbeatJob = null

        _state.update {
            it.copy(
                isMeshRunning = false,
                connectionState = ConnectionState.OFFLINE,
                isLinked = false,
                operationalState = OperationalState.IDLE,
                inferenceRunning = false,
                inferenceEndpoint = "",
            )
        }

        terminalBuffer.append(LogSource.AGENT, "mesh agent stopped")

        // Stop foreground service
        val ctx = getApplication<Application>()
        val intent = Intent(ctx, MeshAgentService::class.java).apply {
            action = MeshAgentService.ACTION_STOP
        }
        ctx.startService(intent)
    }

    private suspend fun sendHeartbeat() {
        val client = coreClient ?: run {
            _state.update { it.copy(isLinked = false) }
            return
        }
        val s = _state.value

        val inferenceEndpoint = if (currentSettings.inferenceRunning) {
            buildInferenceEndpoint(currentSettings.inferencePort)
        } else {
            null
        }
        val payload = HeartbeatPayload(
            deviceId = s.deviceId,
            deviceSecret = currentSettings.token,
            deviceMode = currentSettings.deviceMode,
            cpuPercent = s.cpuPercent,
            ramPercent = s.ramPercent,
            batteryPercent = s.batteryPercent,
            cpuTempC = s.cpuTempC,
            gpuTempC = s.gpuTempC,
            batteryTempC = s.batteryTempC,
            modelLoaded = if (currentSettings.inferenceRunning) s.modelLoaded else null,
            inferenceEndpoint = inferenceEndpoint,
            modeLocked = currentSettings.modeLocked,
        )

        try {
            val device = client.sendHeartbeat(payload)
            if (device != null) {
                terminalBuffer.append(
                    LogSource.AGENT,
                    "heartbeat OK — cpu=${s.cpuPercent.toInt()}% ram=${s.ramPercent.toInt()}% bat=${s.batteryPercent.toInt()}%",
                )
                _state.update {
                    it.copy(
                        isLinked = true,
                        connectionState = device.connectionState,
                        operationalState = device.operationalState,
                        healthScore = device.healthScore,
                    )
                }
            } else {
                terminalBuffer.append(LogSource.AGENT, "heartbeat failed — no response", LogLevel.WARN)
                _state.update { it.copy(connectionState = ConnectionState.RECONNECTING) }
            }
        } catch (e: Exception) {
            terminalBuffer.append(LogSource.AGENT, "heartbeat error: ${e.message}", LogLevel.ERROR)
            _state.update { it.copy(connectionState = ConnectionState.RECONNECTING, isLinked = false) }
        }
    }

    fun changeMode(mode: String) {
        viewModelScope.launch {
            settingsStore.updateDeviceMode(mode)
            terminalBuffer.append(LogSource.AGENT, "mode changed → $mode")
        }
    }

    fun toggleModeLock(locked: Boolean) {
        viewModelScope.launch {
            settingsStore.updateModeLocked(locked)
            terminalBuffer.append(
                LogSource.AGENT,
                if (locked) "mode LOCKED by user" else "mode UNLOCKED",
            )
        }
    }

    fun clearTerminal() {
        terminalBuffer.clear()
    }

    private fun computeHealthScore(
        snapshot: MetricsCollector.Snapshot,
        throttled: Boolean,
        lockedOut: Boolean,
    ): Float {
        if (lockedOut) return 0f
        var score = 100f
        // CPU penalty
        if (snapshot.cpuPercent > 80f) score -= (snapshot.cpuPercent - 80f) * 1.5f
        // RAM penalty
        if (snapshot.ramPercent > 85f) score -= (snapshot.ramPercent - 85f) * 2f
        // Battery penalty
        if (snapshot.batteryPercent in 0f..30f) score -= (30f - snapshot.batteryPercent)
        // Thermal penalty
        if (throttled) score -= 20f
        return score.coerceIn(0f, 100f)
    }

    private fun getLocalIp(): String {
        return try {
            java.net.NetworkInterface.getNetworkInterfaces()?.toList()
                ?.flatMap { it.inetAddresses.toList() }
                ?.firstOrNull { !it.isLoopbackAddress && it is java.net.Inet4Address }
                ?.hostAddress ?: "0.0.0.0"
        } catch (_: Exception) { "0.0.0.0" }
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
        coreClient?.shutdown()
    }

    companion object {
        const val METRICS_INTERVAL_MS = 5_000L
        const val HEARTBEAT_INTERVAL_MS = 30_000L
    }
}
