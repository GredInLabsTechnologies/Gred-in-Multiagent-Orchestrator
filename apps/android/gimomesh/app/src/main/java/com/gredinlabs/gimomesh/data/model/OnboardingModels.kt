package com.gredinlabs.gimomesh.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class RedeemRequest(
    val code: String,
    @SerialName("device_id") val deviceId: String,
    val name: String,
    @SerialName("device_mode") val deviceMode: String = "inference",
    @SerialName("device_class") val deviceClass: String = "smartphone",
)

@Serializable
data class OnboardResult(
    @SerialName("device_id") val deviceId: String,
    @SerialName("bearer_token") val bearerToken: String,
    @SerialName("workspace_id") val workspaceId: String,
    @SerialName("workspace_name") val workspaceName: String,
    val status: String = "pending_approval",
)

@Serializable
data class CoreDiscovery(
    @SerialName("mesh_enabled") val meshEnabled: Boolean,
    val version: String,
    @SerialName("core_id") val coreId: String = "",
)

@Serializable
data class PendingCode(
    val code: String,
    @SerialName("workspace_id") val workspaceId: String = "default",
    @SerialName("core_url") val coreUrl: String = "",
    @SerialName("expires_at") val expiresAt: String = "",
)

@Serializable
data class ModelRecommendation(
    @SerialName("fit_level") val fitLevel: String = "comfortable",
    val recommended: Boolean = false,
    @SerialName("recommended_mode") val recommendedMode: String = "inference",
    val score: Int = 0,
    @SerialName("quality_tier") val qualityTier: Int = 0,
    @SerialName("estimated_ram_gb") val estimatedRamGb: Float = 0f,
    @SerialName("device_ram_gb") val deviceRamGb: Float = 0f,
    @SerialName("ram_headroom_pct") val ramHeadroomPct: Float = 0f,
    @SerialName("estimated_tokens_per_sec") val estimatedTokensPerSec: Float = 0f,
    @SerialName("estimated_battery_drain_pct_hr") val estimatedBatteryDrainPctHr: Float = 0f,
    @SerialName("storage_required_gb") val storageRequiredGb: Float = 0f,
    @SerialName("device_storage_free_gb") val deviceStorageFreeGb: Float = 0f,
    val impact: String = "",
    val warnings: List<String> = emptyList(),
    @SerialName("recommendation_reason") val recommendationReason: String = "",
)

@Serializable
data class ModelInfo(
    @SerialName("model_id") val modelId: String,
    val filename: String,
    val name: String,
    val params: String = "",
    val quantization: String = "",
    @SerialName("size_bytes") val sizeBytes: Long = 0,
    val sha256: String = "",
    val recommendation: ModelRecommendation? = null,
)
