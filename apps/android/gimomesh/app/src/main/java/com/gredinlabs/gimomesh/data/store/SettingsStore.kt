package com.gredinlabs.gimomesh.data.store

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "gimo_mesh_settings")

/**
 * Persistent settings via DataStore.
 * No Room, no SQLite — this app is minimal.
 */
class SettingsStore(private val context: Context) {

    // Keys
    private object Keys {
        val CORE_URL = stringPreferencesKey("core_url")
        val TOKEN = stringPreferencesKey("token")
        val LOCAL_CORE_TOKEN = stringPreferencesKey("local_core_token")
        val LOCAL_DEVICE_SECRET = stringPreferencesKey("local_device_secret")
        val MESH_SERVICE_RUNNING = booleanPreferencesKey("mesh_service_running")
        val DEVICE_ID = stringPreferencesKey("device_id")
        val DEVICE_NAME = stringPreferencesKey("device_name")
        val DEVICE_MODE = stringPreferencesKey("device_mode")
        val MODEL = stringPreferencesKey("model")
        val DOWNLOADED_MODEL_PATH = stringPreferencesKey("downloaded_model_path")
        val INFERENCE_RUNNING = booleanPreferencesKey("inference_running")
        val INFERENCE_PORT = intPreferencesKey("inference_port")
        val THREADS = intPreferencesKey("threads")
        val CONTEXT_SIZE = intPreferencesKey("context_size")
        val BLE_WAKE_ENABLED = booleanPreferencesKey("ble_wake_enabled")
        val BLE_WAKE_KEY = stringPreferencesKey("ble_wake_key")
        val CPU_WARNING_TEMP = intPreferencesKey("cpu_warning_temp")
        val CPU_LOCKOUT_TEMP = intPreferencesKey("cpu_lockout_temp")
        val BATTERY_WARNING_TEMP = intPreferencesKey("battery_warning_temp")
        val BATTERY_LOCKOUT_TEMP = intPreferencesKey("battery_lockout_temp")
        val MIN_BATTERY_PERCENT = intPreferencesKey("min_battery_percent")
        val MODE_LOCKED = booleanPreferencesKey("mode_locked")
        val HYBRID_AUTO = booleanPreferencesKey("hybrid_auto")
        val HYBRID_INFERENCE = booleanPreferencesKey("hybrid_inference")
        val HYBRID_UTILITY = booleanPreferencesKey("hybrid_utility")
        val HYBRID_SERVE = booleanPreferencesKey("hybrid_serve")
        val ACTIVE_WORKSPACE_ID = stringPreferencesKey("active_workspace_id")
        val ACTIVE_WORKSPACE_NAME = stringPreferencesKey("active_workspace_name")
        val INFERENCE_AUTO_START_ALLOWED = booleanPreferencesKey("inference_auto_start_allowed")
        // Fase D2-b — opt-in model retention policy.
        // 0 = never delete (default). 30/60/90 = days of workspace-contact
        // inactivity after which ModelRetentionWorker wipes the models dir.
        val MODEL_RETENTION_DAYS = intPreferencesKey("model_retention_days")
        // Epoch millis of the last successful heartbeat to the workspace
        // Core. Updated by MeshAgentService on every successful heartbeat.
        // Used by ModelRetentionWorker to compute elapsed inactivity.
        val LAST_WORKSPACE_CONTACT_AT = longPreferencesKey("last_workspace_contact_at")
    }

    // Defaults
    data class Settings(
        // coreUrl: empty by default. The wizard auto-discovers via mDNS or
        // takes the URL from the QR payload. User never needs to type it
        // unless corporate WiFi blocks discovery.
        val coreUrl: String = "",
        val token: String = "",
        val localCoreToken: String = "",
        val localDeviceSecret: String = "",
        val meshServiceRunning: Boolean = false,
        val deviceId: String = "",
        val deviceName: String = "",
        val deviceMode: String = "inference",
        val model: String = "qwen2.5:3b",
        val downloadedModelPath: String = "",
        val inferenceRunning: Boolean = false,
        val inferencePort: Int = 8080,
        val threads: Int = 4,
        val contextSize: Int = 2048,
        val bleWakeEnabled: Boolean = true,
        val bleWakeKey: String = "",
        val cpuWarningTemp: Int = 65,
        val cpuLockoutTemp: Int = 75,
        val batteryWarningTemp: Int = 38,
        val batteryLockoutTemp: Int = 42,
        val minBatteryPercent: Int = 20,
        val modeLocked: Boolean = false,
        val hybridAuto: Boolean = true,        // default: Core decides
        val hybridInference: Boolean = true,   // default: inference ON
        val hybridUtility: Boolean = true,     // default: utility ON
        val hybridServe: Boolean = false,      // default: serve OFF
        val activeWorkspaceId: String = "default",
        val activeWorkspaceName: String = "Default",
        // KISI invariant: llama-server never auto-starts on boot/relaunch unless
        // the human has explicitly opted in (and hardware is healthy). Default OFF.
        val inferenceAutoStartAllowed: Boolean = false,
        // Fase D2-b — opt-in model retention. 0 = never delete (default).
        // Values 30/60/90 enable ModelRetentionWorker.
        val modelRetentionDays: Int = 0,
        // Epoch millis of last successful heartbeat. 0 = never contacted.
        val lastWorkspaceContactAt: Long = 0L,
    )

    val settings: Flow<Settings> = context.dataStore.data.map { prefs ->
        Settings(
            coreUrl = prefs[Keys.CORE_URL] ?: Settings().coreUrl,
            token = prefs[Keys.TOKEN] ?: "",
            localCoreToken = prefs[Keys.LOCAL_CORE_TOKEN] ?: "",
            localDeviceSecret = prefs[Keys.LOCAL_DEVICE_SECRET] ?: "",
            meshServiceRunning = prefs[Keys.MESH_SERVICE_RUNNING] ?: false,
            deviceId = prefs[Keys.DEVICE_ID] ?: "",
            deviceName = prefs[Keys.DEVICE_NAME] ?: "",
            deviceMode = prefs[Keys.DEVICE_MODE] ?: "inference",
            model = prefs[Keys.MODEL] ?: "qwen2.5:3b",
            downloadedModelPath = prefs[Keys.DOWNLOADED_MODEL_PATH] ?: "",
            inferenceRunning = prefs[Keys.INFERENCE_RUNNING] ?: false,
            inferencePort = prefs[Keys.INFERENCE_PORT] ?: 8080,
            threads = prefs[Keys.THREADS] ?: 4,
            contextSize = prefs[Keys.CONTEXT_SIZE] ?: 2048,
            bleWakeEnabled = prefs[Keys.BLE_WAKE_ENABLED] ?: true,
            bleWakeKey = prefs[Keys.BLE_WAKE_KEY] ?: "",
            cpuWarningTemp = prefs[Keys.CPU_WARNING_TEMP] ?: 65,
            cpuLockoutTemp = prefs[Keys.CPU_LOCKOUT_TEMP] ?: 75,
            batteryWarningTemp = prefs[Keys.BATTERY_WARNING_TEMP] ?: 38,
            batteryLockoutTemp = prefs[Keys.BATTERY_LOCKOUT_TEMP] ?: 42,
            minBatteryPercent = prefs[Keys.MIN_BATTERY_PERCENT] ?: 20,
            modeLocked = prefs[Keys.MODE_LOCKED] ?: false,
            hybridAuto = prefs[Keys.HYBRID_AUTO] ?: true,
            hybridInference = prefs[Keys.HYBRID_INFERENCE] ?: true,
            hybridUtility = prefs[Keys.HYBRID_UTILITY] ?: true,
            hybridServe = prefs[Keys.HYBRID_SERVE] ?: false,
            activeWorkspaceId = prefs[Keys.ACTIVE_WORKSPACE_ID] ?: "default",
            activeWorkspaceName = prefs[Keys.ACTIVE_WORKSPACE_NAME] ?: "Default",
            inferenceAutoStartAllowed = prefs[Keys.INFERENCE_AUTO_START_ALLOWED] ?: false,
            modelRetentionDays = prefs[Keys.MODEL_RETENTION_DAYS] ?: 0,
            lastWorkspaceContactAt = prefs[Keys.LAST_WORKSPACE_CONTACT_AT] ?: 0L,
        )
    }

    suspend fun updateCoreUrl(url: String) {
        context.dataStore.edit { it[Keys.CORE_URL] = url }
    }

    suspend fun updateToken(token: String) {
        context.dataStore.edit { it[Keys.TOKEN] = token }
    }

    suspend fun updateLocalCoreToken(token: String) {
        context.dataStore.edit { it[Keys.LOCAL_CORE_TOKEN] = token }
    }

    suspend fun updateLocalDeviceSecret(secret: String) {
        context.dataStore.edit { it[Keys.LOCAL_DEVICE_SECRET] = secret }
    }

    suspend fun updateMeshServiceRunning(running: Boolean) {
        context.dataStore.edit { it[Keys.MESH_SERVICE_RUNNING] = running }
    }

    suspend fun updateDeviceId(id: String) {
        context.dataStore.edit { it[Keys.DEVICE_ID] = id }
    }

    suspend fun updateDeviceName(name: String) {
        context.dataStore.edit { it[Keys.DEVICE_NAME] = name }
    }

    suspend fun updateDeviceMode(mode: String) {
        context.dataStore.edit { it[Keys.DEVICE_MODE] = mode }
    }

    suspend fun updateModel(model: String) {
        context.dataStore.edit { it[Keys.MODEL] = model }
    }

    suspend fun updateDownloadedModelPath(path: String) {
        context.dataStore.edit { it[Keys.DOWNLOADED_MODEL_PATH] = path }
    }

    suspend fun updateInferenceRunning(running: Boolean) {
        context.dataStore.edit { it[Keys.INFERENCE_RUNNING] = running }
    }

    suspend fun updateInferencePort(port: Int) {
        context.dataStore.edit { it[Keys.INFERENCE_PORT] = port }
    }

    suspend fun updateThreads(threads: Int) {
        context.dataStore.edit { it[Keys.THREADS] = threads }
    }

    suspend fun updateContextSize(size: Int) {
        context.dataStore.edit { it[Keys.CONTEXT_SIZE] = size }
    }

    suspend fun updateBleWakeEnabled(enabled: Boolean) {
        context.dataStore.edit { it[Keys.BLE_WAKE_ENABLED] = enabled }
    }

    suspend fun updateBleWakeKey(key: String) {
        context.dataStore.edit { it[Keys.BLE_WAKE_KEY] = key }
    }

    suspend fun updateModeLocked(locked: Boolean) {
        context.dataStore.edit { it[Keys.MODE_LOCKED] = locked }
    }

    suspend fun updateHybridAuto(enabled: Boolean) {
        context.dataStore.edit { it[Keys.HYBRID_AUTO] = enabled }
    }

    suspend fun updateHybridInference(enabled: Boolean) {
        context.dataStore.edit { it[Keys.HYBRID_INFERENCE] = enabled }
    }

    suspend fun updateHybridUtility(enabled: Boolean) {
        context.dataStore.edit { it[Keys.HYBRID_UTILITY] = enabled }
    }

    suspend fun updateHybridServe(enabled: Boolean) {
        context.dataStore.edit { it[Keys.HYBRID_SERVE] = enabled }
    }

    suspend fun updateInferenceAutoStartAllowed(allowed: Boolean) {
        context.dataStore.edit { it[Keys.INFERENCE_AUTO_START_ALLOWED] = allowed }
    }

    /**
     * Fase D2-b — opt-in model retention policy.
     * Accepts 0 (never), 30, 60, or 90. Any other value is clamped to 0.
     */
    suspend fun updateModelRetentionDays(days: Int) {
        val sanitized = if (days in setOf(0, 30, 60, 90)) days else 0
        context.dataStore.edit { it[Keys.MODEL_RETENTION_DAYS] = sanitized }
    }

    /**
     * Mark the moment of a successful heartbeat to the workspace Core.
     * ModelRetentionWorker uses this to compute elapsed inactivity.
     * Called from MeshAgentService on every 2xx heartbeat response.
     */
    suspend fun touchWorkspaceContact(atMillis: Long = System.currentTimeMillis()) {
        context.dataStore.edit { it[Keys.LAST_WORKSPACE_CONTACT_AT] = atMillis }
    }

    suspend fun updateActiveWorkspace(id: String, name: String) {
        context.dataStore.edit {
            it[Keys.ACTIVE_WORKSPACE_ID] = id
            it[Keys.ACTIVE_WORKSPACE_NAME] = name
        }
    }

    suspend fun updateThermalLimits(
        cpuWarning: Int? = null,
        cpuLockout: Int? = null,
        batteryWarning: Int? = null,
        batteryLockout: Int? = null,
        minBattery: Int? = null,
    ) {
        context.dataStore.edit { prefs ->
            cpuWarning?.let { prefs[Keys.CPU_WARNING_TEMP] = it }
            cpuLockout?.let { prefs[Keys.CPU_LOCKOUT_TEMP] = it }
            batteryWarning?.let { prefs[Keys.BATTERY_WARNING_TEMP] = it }
            batteryLockout?.let { prefs[Keys.BATTERY_LOCKOUT_TEMP] = it }
            minBattery?.let { prefs[Keys.MIN_BATTERY_PERCENT] = it }
        }
    }
}
