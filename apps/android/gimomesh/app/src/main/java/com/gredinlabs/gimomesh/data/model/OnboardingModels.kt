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
data class ModelInfo(
    @SerialName("model_id") val modelId: String,
    val filename: String,
    val name: String,
    val params: String = "",
    val quantization: String = "",
    @SerialName("size_bytes") val sizeBytes: Long = 0,
    val sha256: String = "",
)
