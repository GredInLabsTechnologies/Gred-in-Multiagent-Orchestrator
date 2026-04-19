package com.gredinlabs.gimomesh.service

/**
 * KISI hardware gate for llama-server start.
 *
 * Philosophy: the human can authorise auto-start (SettingsStore.inferenceAutoStartAllowed)
 * but the device decides whether it is prudent *right now*. Authorisation + unsafe
 * hardware = deferred, not started. Authorisation + safe hardware = started.
 *
 * Thresholds are conservative defaults. Battery < 31% or CPU > 50°C or thermal
 * throttle active or RAM > 85% all defer the start. This is independent of the
 * harder thermal-lockout thresholds in SettingsStore (which force a stop mid-run).
 */
sealed class SafetyResult {
    object Safe : SafetyResult()
    data class Unsafe(val reason: String) : SafetyResult()
}

fun isInferenceSafeNow(
    batteryPercent: Float,
    cpuTempC: Float,
    thermalThrottled: Boolean,
    ramPercent: Float,
): SafetyResult {
    // batteryPercent == -1f means "unknown" (device didn't report yet).
    // Don't block on unknown — block only on a reading we actively distrust.
    if (batteryPercent in 0f..30f) {
        return SafetyResult.Unsafe("low battery (${batteryPercent.toInt()}%)")
    }
    if (cpuTempC in 0f..200f && cpuTempC > 50f) {
        return SafetyResult.Unsafe("CPU hot (${cpuTempC.toInt()}°C)")
    }
    if (thermalThrottled) {
        return SafetyResult.Unsafe("thermal throttle active")
    }
    if (ramPercent > 85f) {
        return SafetyResult.Unsafe("RAM pressure (${ramPercent.toInt()}%)")
    }
    return SafetyResult.Safe
}
