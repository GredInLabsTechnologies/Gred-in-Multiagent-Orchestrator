package com.gredinlabs.gimomesh.service

import com.gredinlabs.gimomesh.data.store.SettingsStore

const val LOCAL_CORE_PORT: Int = 9325
const val LOCAL_CORE_URL: String = "http://127.0.0.1:$LOCAL_CORE_PORT"

fun isServeMode(settings: SettingsStore.Settings): Boolean =
    when (settings.deviceMode.lowercase()) {
        "server" -> true
        "hybrid" -> settings.hybridAuto || settings.hybridServe
        else -> false
    }

fun allowsInference(settings: SettingsStore.Settings): Boolean =
    when (settings.deviceMode.lowercase()) {
        "inference" -> true
        "hybrid" -> settings.hybridAuto || settings.hybridInference
        else -> false
    }

fun allowsUtility(settings: SettingsStore.Settings): Boolean =
    when (settings.deviceMode.lowercase()) {
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
