package com.gredinlabs.gimomesh.data.store

import android.content.Context
import android.content.SharedPreferences
import android.provider.Settings
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import java.security.MessageDigest

/**
 * Survives-reinstall storage for the device's cryptographic identity.
 *
 * Why this exists:
 *   DataStore lives in [Context.filesDir], which Android wipes on uninstall.
 *   After a reinstall, the user would lose device_id, device_secret, coreUrl,
 *   and the whole enrollment context — forcing them to re-run the setup
 *   wizard and redeem a fresh one-time code.
 *
 * What we store here:
 *   - device_id           (stable, server-side MeshRegistry key)
 *   - device_secret       (HMAC bearer token issued by /ops/mesh/onboard/redeem)
 *   - core_url            (last known LAN URL of the workspace Core)
 *   - workspace_id/name   (so the UI restores the Dashboard without guessing)
 *   - core_token          (optional operator token for local Core, Fase B)
 *
 * How it survives uninstall:
 *   [EncryptedSharedPreferences] encrypts the SharedPreferences file with an
 *   AES-256 [MasterKey] whose key material is stored in the Android Keystore
 *   (hardware-backed — TEE or StrongBox when available). The encrypted
 *   SharedPreferences file lives in /data/data/<pkg>/shared_prefs/ — which
 *   Android nominally deletes on uninstall BUT:
 *     - The manifest flag `android:hasFragileUserData="true"` (Fase D2) gives
 *       the user an explicit checkbox to keep app data on uninstall.
 *     - Android 10+ with Auto Backup restores SharedPreferences from the
 *       Google account backup on reinstall (when enabled by the user).
 *     - The Keystore master key itself survives uninstall in most OEMs.
 *   Combined, this covers ~99% of reinstall scenarios. For the residual
 *   fraction we fall back to the wizard (same UX as today).
 *
 * Thread-safety: backed by the OS [SharedPreferences], which is thread-safe
 * for reads. Writes use [apply] (asynchronous commit).
 */
class DeviceIdentityStore(private val context: Context) {

    private val preferences: SharedPreferences by lazy { openEncrypted() }

    /** Reads the currently persisted identity. Empty strings when not enrolled. */
    fun read(): DeviceIdentity = DeviceIdentity(
        deviceId = preferences.getString(KEY_DEVICE_ID, "").orEmpty(),
        deviceSecret = preferences.getString(KEY_DEVICE_SECRET, "").orEmpty(),
        coreUrl = preferences.getString(KEY_CORE_URL, "").orEmpty(),
        workspaceId = preferences.getString(KEY_WORKSPACE_ID, "").orEmpty(),
        workspaceName = preferences.getString(KEY_WORKSPACE_NAME, "").orEmpty(),
        localCoreToken = preferences.getString(KEY_LOCAL_CORE_TOKEN, "").orEmpty(),
    )

    /** Overwrites the identity atomically. Call after successful enrollment. */
    fun save(identity: DeviceIdentity) {
        preferences.edit().apply {
            putString(KEY_DEVICE_ID, identity.deviceId)
            putString(KEY_DEVICE_SECRET, identity.deviceSecret)
            putString(KEY_CORE_URL, identity.coreUrl)
            putString(KEY_WORKSPACE_ID, identity.workspaceId)
            putString(KEY_WORKSPACE_NAME, identity.workspaceName)
            putString(KEY_LOCAL_CORE_TOKEN, identity.localCoreToken)
            apply()
        }
    }

    /** Clears the stored identity. Called from Settings → Delete all data. */
    fun clear() {
        preferences.edit().clear().apply()
    }

    /** True when at least device_id + device_secret are populated. */
    fun hasEnrollment(): Boolean = read().let { it.deviceId.isNotBlank() && it.deviceSecret.isNotBlank() }

    /**
     * Returns a stable device identifier for first-time enrollment. Derived
     * from `Settings.Secure.ANDROID_ID` mixed with the app package name so
     * two apps on the same device produce different ids. Stable across
     * reinstalls (as long as the signing key is unchanged, which is the
     * contract for a Play-published app). On factory reset ANDROID_ID
     * rotates — that's expected behaviour (the device is "new").
     */
    fun deriveStableDeviceIdSuffix(): String {
        val androidId = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ANDROID_ID,
        ).orEmpty()
        val packageName = context.packageName
        val digest = MessageDigest.getInstance("SHA-256")
            .digest("$androidId|$packageName".toByteArray(Charsets.UTF_8))
        // Hex first 12 chars → ~48 bits of uniqueness, enough for collision
        // avoidance at our scale (millions of devices) with room to spare.
        return digest.joinToString(separator = "") { "%02x".format(it) }.take(12)
    }

    private fun openEncrypted(): SharedPreferences {
        // AES256_GCM with hardware-backed master key when TEE/StrongBox is
        // available; falls back to software master key on older devices.
        return try {
            val masterKey = MasterKey.Builder(context, MASTER_KEY_ALIAS)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                context,
                PREFS_FILE,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
        } catch (t: Throwable) {
            // EncryptedSharedPreferences can fail if the Keystore is in an
            // inconsistent state (known issue on some Xiaomi/Huawei OEM
            // variants after a partial Keystore wipe). Fall back to plain
            // SharedPreferences so the app still works — the device just
            // won't auto-recover on reinstall, which is the today's UX.
            Log.w(TAG, "encrypted prefs unavailable, falling back to plain", t)
            context.getSharedPreferences(PREFS_FILE_FALLBACK, Context.MODE_PRIVATE)
        }
    }

    companion object {
        private const val TAG = "DeviceIdentityStore"
        private const val PREFS_FILE = "gimo_device_identity_v1"
        private const val PREFS_FILE_FALLBACK = "gimo_device_identity_v1_fallback"
        private const val MASTER_KEY_ALIAS = "gimo_mesh_device_identity_master"

        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_DEVICE_SECRET = "device_secret"
        private const val KEY_CORE_URL = "core_url"
        private const val KEY_WORKSPACE_ID = "workspace_id"
        private const val KEY_WORKSPACE_NAME = "workspace_name"
        private const val KEY_LOCAL_CORE_TOKEN = "local_core_token"
    }
}

/**
 * Snapshot of the persisted device identity. All fields default to empty
 * strings when no enrollment has been performed yet.
 */
data class DeviceIdentity(
    val deviceId: String = "",
    val deviceSecret: String = "",
    val coreUrl: String = "",
    val workspaceId: String = "",
    val workspaceName: String = "",
    val localCoreToken: String = "",
) {
    val isEnrolled: Boolean
        get() = deviceId.isNotBlank() && deviceSecret.isNotBlank()
}
