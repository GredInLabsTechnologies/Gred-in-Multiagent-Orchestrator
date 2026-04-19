package com.gredinlabs.gimomesh.data.model

/**
 * Central UI state for the entire app.
 * Populated from heartbeat responses + local metrics.
 */
data class MeshState(
    // Connection
    val coreUrl: String = "",
    val isLinked: Boolean = false,
    val deviceId: String = "",
    val deviceName: String = "",
    val hostRuntimeStatus: String = "stopped",
    val hostRuntimeAvailable: Boolean = false,
    val hostLanUrl: String = "",
    val hostWebUrl: String = "",
    val hostMcpUrl: String = "",
    val hostRuntimeError: String = "",

    // Device status
    val connectionState: ConnectionState = ConnectionState.OFFLINE,
    val operationalState: OperationalState = OperationalState.IDLE,
    val deviceMode: DeviceMode = DeviceMode.INFERENCE,
    val healthScore: Float = 0f,

    // Metrics
    val cpuPercent: Float = 0f,
    val ramPercent: Float = 0f,
    val batteryPercent: Float = -1f,

    // Thermal
    val cpuTempC: Float = -1f,
    val gpuTempC: Float = -1f,
    val batteryTempC: Float = -1f,
    val thermalThrottled: Boolean = false,
    val thermalLockedOut: Boolean = false,

    // Model
    val modelLoaded: String = "",
    val inferenceRunning: Boolean = false,
    val inferencePort: Int = 8080,
    val inferenceEndpoint: String = "",
    val modelParams: String = "",
    val quantization: String = "",
    val throughput: String = "",

    // Inference (for blackout mode)
    val tokensPerSecond: Float = 0f,
    val tokensGenerated: Int = 0,
    val activeTaskId: String = "",
    val elapsedSeconds: Float = 0f,

    // Plan graph
    val planNodes: List<PlanNode> = emptyList(),

    // Terminal
    val terminalLines: List<TerminalLine> = emptyList(),

    // Agent tasks
    val tasks: List<AgentTask> = emptyList(),

    // Mesh running
    val isMeshRunning: Boolean = false,
) {
    val thermalStatus: String
        get() = when {
            thermalLockedOut -> "LOCKOUT"
            thermalThrottled -> "WARNING"
            else -> "OK"
        }

    val elapsedFormatted: String
        get() {
            val s = elapsedSeconds.toInt()
            return if (s < 60) "${s}s" else "${s / 60}m ${s % 60}s"
        }
}
