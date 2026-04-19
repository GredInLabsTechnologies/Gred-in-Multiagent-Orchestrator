package com.gredinlabs.gimomesh.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
enum class ConnectionState {
    @SerialName("connected") CONNECTED,
    @SerialName("approved") APPROVED,
    @SerialName("pending_approval") PENDING_APPROVAL,
    @SerialName("reconnecting") RECONNECTING,
    @SerialName("thermal_lockout") THERMAL_LOCKOUT,
    @SerialName("refused") REFUSED,
    @SerialName("offline") OFFLINE,
    @SerialName("discoverable") DISCOVERABLE,
}

@Serializable
enum class OperationalState {
    @SerialName("idle") IDLE,
    @SerialName("busy") BUSY,
    @SerialName("paused") PAUSED,
    @SerialName("error") ERROR,
}

@Serializable
enum class DeviceMode {
    @SerialName("inference") INFERENCE,
    @SerialName("utility") UTILITY,
    @SerialName("server") SERVER,
    @SerialName("hybrid") HYBRID,
}

@Serializable
data class MeshDevice(
    @SerialName("device_id") val deviceId: String,
    val name: String = "",
    @SerialName("device_secret") val deviceSecret: String = "",
    @SerialName("device_mode") val deviceMode: DeviceMode = DeviceMode.INFERENCE,
    @SerialName("connection_state") val connectionState: ConnectionState = ConnectionState.OFFLINE,
    @SerialName("operational_state") val operationalState: OperationalState = OperationalState.IDLE,
    @SerialName("health_score") val healthScore: Float = 0f,
    @SerialName("cpu_percent") val cpuPercent: Float = 0f,
    @SerialName("ram_percent") val ramPercent: Float = 0f,
    @SerialName("battery_percent") val batteryPercent: Float = -1f,
    @SerialName("cpu_temp_c") val cpuTempC: Float = -1f,
    @SerialName("gpu_temp_c") val gpuTempC: Float = -1f,
    @SerialName("battery_temp_c") val batteryTempC: Float = -1f,
    @SerialName("thermal_throttled") val thermalThrottled: Boolean = false,
    @SerialName("thermal_locked_out") val thermalLockedOut: Boolean = false,
    @SerialName("model_loaded") val modelLoaded: String? = null,
    @SerialName("inference_endpoint") val inferenceEndpoint: String = "",
    @SerialName("active_task_id") val activeTaskId: String = "",
)

@Serializable
data class DeviceCapabilities(
    val arch: String,
    @SerialName("cpu_cores") val cpuCores: Int,
    @SerialName("ram_total_mb") val ramTotalMb: Int,
    @SerialName("storage_free_mb") val storageFremMb: Int,
    @SerialName("api_level") val apiLevel: Int,
    @SerialName("soc_model") val socModel: String,
    @SerialName("has_gpu_compute") val hasGpuCompute: Boolean = false,
    @SerialName("max_file_descriptors") val maxFileDescriptors: Int = 1024,
)

@Serializable
data class HeartbeatPayload(
    @SerialName("device_id") val deviceId: String,
    @SerialName("device_secret") val deviceSecret: String,
    @SerialName("device_mode") val deviceMode: String = "inference",
    @SerialName("operational_state") val operationalState: String = "idle",
    @SerialName("cpu_percent") val cpuPercent: Float,
    @SerialName("ram_percent") val ramPercent: Float,
    @SerialName("battery_percent") val batteryPercent: Float,
    @SerialName("cpu_temp_c") val cpuTempC: Float,
    @SerialName("gpu_temp_c") val gpuTempC: Float = -1f,
    @SerialName("battery_temp_c") val batteryTempC: Float,
    @SerialName("model_loaded") val modelLoaded: String? = null,
    @SerialName("inference_endpoint") val inferenceEndpoint: String? = null,
    @SerialName("active_task_id") val activeTaskId: String = "",
    @SerialName("mode_locked") val modeLocked: Boolean = false,
    val capabilities: DeviceCapabilities? = null,
    @SerialName("workspace_id") val workspaceId: String = "default",
)

enum class LogSource { AGENT, INFER, SYS, TASK }
enum class LogLevel { DEBUG, INFO, WARN, ERROR }

data class TerminalLine(
    val timestamp: Long = System.currentTimeMillis(),
    val source: LogSource,
    val message: String,
    val level: LogLevel = LogLevel.INFO,
)

enum class PlanNodeStatus { DONE, RUNNING, PENDING, ERROR }

data class PlanNode(
    val id: String,
    val label: String,
    val role: String,
    val description: String = "",
    val status: PlanNodeStatus = PlanNodeStatus.PENDING,
    val prompt: String = "",
    val progress: Float = 0f,
    val children: List<String> = emptyList(), // IDs of downstream nodes
)

data class AgentTask(
    val id: String,
    val actionClass: String,
    val target: String,
    val complexity: String = "moderate",
    val status: PlanNodeStatus = PlanNodeStatus.PENDING,
    val dispatchedAt: String = "",
    val duration: String = "",
    val prompt: String = "",
    val inferenceOutput: String = "",
)

@Serializable
data class MeshTask(
    @SerialName("task_id") val taskId: String,
    @SerialName("task_type") val taskType: String,
    val payload: Map<String, String> = emptyMap(),
    @SerialName("timeout_seconds") val timeoutSeconds: Int = 60,
)

// ── Workspace models ────────────────────────────────────────

@Serializable
data class MeshWorkspace(
    @SerialName("workspace_id") val workspaceId: String,
    val name: String,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("owner_device_id") val ownerDeviceId: String = "",
)

@Serializable
data class WorkspaceMembershipInfo(
    @SerialName("workspace_id") val workspaceId: String,
    @SerialName("device_id") val deviceId: String,
    val role: String = "member",
    @SerialName("device_mode") val deviceMode: String = "inference",
    @SerialName("joined_at") val joinedAt: String = "",
)

@Serializable
data class PairingCodeResponse(
    val code: String,
    @SerialName("workspace_id") val workspaceId: String,
    @SerialName("expires_at") val expiresAt: String,
)

@Serializable
data class TaskResultPayload(
    @SerialName("task_id") val taskId: String,
    @SerialName("device_id") val deviceId: String,
    @SerialName("device_secret") val deviceSecret: String = "",
    val status: String, // "completed" | "failed"
    val result: Map<String, String> = emptyMap(),
    val error: String = "",
    @SerialName("duration_ms") val durationMs: Int = 0,
)
