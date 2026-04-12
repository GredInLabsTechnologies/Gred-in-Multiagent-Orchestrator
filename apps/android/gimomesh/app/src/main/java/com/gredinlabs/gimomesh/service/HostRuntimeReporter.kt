package com.gredinlabs.gimomesh.service

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class HostRuntimeStatus {
    STOPPED,
    STARTING,
    READY,
    DEGRADED,
    UNAVAILABLE,
    ERROR,
}

data class HostRuntimeSnapshot(
    val status: HostRuntimeStatus = HostRuntimeStatus.STOPPED,
    val available: Boolean = false,
    val controlUrl: String = LOCAL_CORE_URL,
    val lanUrl: String = "",
    val webUrl: String = "",
    val mcpUrl: String = "",
    val error: String = "",
)

class HostRuntimeReporter {
    private val _snapshot = MutableStateFlow(HostRuntimeSnapshot())
    val snapshot: StateFlow<HostRuntimeSnapshot> = _snapshot.asStateFlow()

    fun update(snapshot: HostRuntimeSnapshot) {
        _snapshot.value = snapshot
    }

    fun setStatus(
        status: HostRuntimeStatus,
        available: Boolean = snapshot.value.available,
        lanUrl: String = snapshot.value.lanUrl,
        error: String = "",
    ) {
        _snapshot.value = HostRuntimeSnapshot(
            status = status,
            available = available,
            controlUrl = LOCAL_CORE_URL,
            lanUrl = lanUrl,
            webUrl = lanUrl,
            mcpUrl = if (lanUrl.isNotBlank()) "$lanUrl/mcp/app" else "",
            error = error,
        )
    }

    fun reset() {
        _snapshot.value = HostRuntimeSnapshot()
    }
}
