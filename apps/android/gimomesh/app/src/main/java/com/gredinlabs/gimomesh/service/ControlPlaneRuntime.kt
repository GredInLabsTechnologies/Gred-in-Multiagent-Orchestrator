package com.gredinlabs.gimomesh.service

import com.gredinlabs.gimomesh.data.store.SettingsStore

const val LOCAL_CORE_PORT: Int = 9325
const val LOCAL_CORE_URL: String = "http://127.0.0.1:$LOCAL_CORE_PORT"

// rev 2 Cambio 4 — capability helpers also honour the hybrid pills directly so
// that toggling "Serve" in Settings flips the Core into server mode without
// requiring the legacy `deviceMode` selector to be explicitly changed first.
// The pills are the modern source of truth; `deviceMode` remains a fallback
// for setup wizards and config files that still set it directly.

fun isServeMode(settings: SettingsStore.Settings): Boolean =
    settings.hybridServe || when (settings.deviceMode.lowercase()) {
        "server" -> true
        "hybrid" -> settings.hybridAuto || settings.hybridServe
        else -> false
    }

fun allowsInference(settings: SettingsStore.Settings): Boolean =
    settings.hybridInference || when (settings.deviceMode.lowercase()) {
        "inference" -> true
        "hybrid" -> settings.hybridAuto || settings.hybridInference
        else -> false
    }

fun allowsUtility(settings: SettingsStore.Settings): Boolean =
    settings.hybridUtility || when (settings.deviceMode.lowercase()) {
        "utility" -> true
        "hybrid" -> settings.hybridAuto || settings.hybridUtility
        else -> false
    }

fun resolveControlPlaneBaseUrl(settings: SettingsStore.Settings): String {
    if (isServeMode(settings)) return LOCAL_CORE_URL
    return if (settings.coreUrl.startsWith("http")) settings.coreUrl else "http://${settings.coreUrl}"
}

fun resolveControlPlaneToken(settings: SettingsStore.Settings): String =
    if (isServeMode(settings)) settings.localCoreToken else settings.token

fun resolveHeartbeatSecret(settings: SettingsStore.Settings): String =
    if (isServeMode(settings)) settings.localDeviceSecret else settings.token

fun setupRequired(settings: SettingsStore.Settings): Boolean =
    !isServeMode(settings) && settings.token.isBlank()
