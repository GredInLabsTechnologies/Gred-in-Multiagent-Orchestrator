package com.gredinlabs.gimomesh

import android.app.Application
import android.util.Log
import com.gredinlabs.gimomesh.data.model.LogLevel
import com.gredinlabs.gimomesh.data.model.LogSource
import com.gredinlabs.gimomesh.data.store.DeviceIdentity
import com.gredinlabs.gimomesh.data.store.DeviceIdentityStore
import com.gredinlabs.gimomesh.data.store.ModelStorage
import com.gredinlabs.gimomesh.data.store.SettingsStore
import com.gredinlabs.gimomesh.service.ChaquopyBridge
import com.gredinlabs.gimomesh.service.HostRuntimeReporter
import com.gredinlabs.gimomesh.service.ModelRetentionWorker
import com.gredinlabs.gimomesh.service.TerminalBuffer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

class GimoMeshApp : Application() {

    lateinit var terminalBuffer: TerminalBuffer
        private set
    lateinit var hostRuntimeReporter: HostRuntimeReporter
        private set
    lateinit var settingsStore: SettingsStore
        private set
    lateinit var deviceIdentityStore: DeviceIdentityStore
        private set

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onCreate() {
        super.onCreate()
        terminalBuffer = TerminalBuffer()
        hostRuntimeReporter = HostRuntimeReporter()
        settingsStore = SettingsStore(this)
        deviceIdentityStore = DeviceIdentityStore(this)

        // Fase D1 — auto-recovery of enrollment after APK reinstall.
        // DataStore is wiped by Android on uninstall, so post-reinstall the
        // Settings flow emits defaults (empty deviceId/secret). If the user
        // had enrolled before, DeviceIdentityStore still holds the identity
        // (EncryptedSharedPreferences + Keystore master key survive reinstall
        // on ~99% of devices). We hydrate SettingsStore from it so the rest
        // of the app sees a non-empty enrollment and skips the wizard.
        // Fire-and-forget on a background scope — the UI can show a brief
        // "recovering…" state via the normal Settings.Flow collector.
        appScope.launch {
            try {
                recoverIdentityIfNeeded()
            } catch (t: Throwable) {
                Log.w("GimoMeshApp", "identity recovery failed (safe to ignore)", t)
            }
            // Fase D2 — one-shot migration of pre-D2 models from filesDir
            // to externalMediaDirs. Idempotent: no-op when the legacy dir
            // is empty (the common case after the migration has run once).
            try {
                val moved = ModelStorage.migrateLegacyModels(this@GimoMeshApp)
                if (moved > 0) {
                    terminalBuffer.append(
                        LogSource.SYS,
                        "migrated $moved model file(s) to external media (reinstall-safe)",
                    )
                }
            } catch (t: Throwable) {
                Log.w("GimoMeshApp", "model storage migration failed", t)
            }

            // Fase D2-b — re-apply the retention worker schedule. Needed on
            // every boot because WorkManager schedules don't survive APK
            // reinstall. No-op when user hasn't opted in (default 0 days).
            try {
                val snapshot = settingsStore.settings.first()
                ModelRetentionWorker.applySchedule(
                    this@GimoMeshApp,
                    snapshot.modelRetentionDays,
                )
            } catch (t: Throwable) {
                Log.w("GimoMeshApp", "retention scheduler apply failed", t)
            }
        }

        // Fase A — eager Chaquopy bootstrap. Starting Python during
        // Application.onCreate is the official pattern (see Chaquopy docs);
        // it takes ~150 ms on S10 and pre-warms the JVM so Server Node
        // startup (Fase B) doesn't pay that cost on first request.
        // Wrapped in try/catch: inference + utility roles must continue to
        // work even if Chaquopy init fails on some exotic ABI.
        try {
            val summary = ChaquopyBridge.runSmokeTest(this)
            terminalBuffer.append(LogSource.SYS, "chaquopy ready — $summary")
            Log.i("GimoMeshApp", "chaquopy ready — $summary")
        } catch (t: Throwable) {
            terminalBuffer.append(
                LogSource.SYS,
                "chaquopy smoke test failed: ${t.message}",
                LogLevel.WARN,
            )
            Log.w("GimoMeshApp", "chaquopy smoke test failed", t)
        }
    }

    /**
     * Hydrates [SettingsStore] from [DeviceIdentityStore] when the user has a
     * prior enrollment but DataStore is empty (typical post-reinstall state).
     * No-op when SettingsStore already has a deviceId — writing during an
     * active enrollment would race the wizard.
     */
    private suspend fun recoverIdentityIfNeeded() {
        val settings = settingsStore.settings.first()
        if (settings.deviceId.isNotBlank() && settings.token.isNotBlank()) {
            // Normal case: DataStore hot from previous boot, nothing to do.
            return
        }
        val identity: DeviceIdentity = deviceIdentityStore.read()
        if (!identity.isEnrolled) {
            // No prior enrollment — user goes through the wizard as usual.
            return
        }

        // Hydrate the minimum set of fields the wizard would have set on a
        // successful redeem. Model selection stays empty intentionally so the
        // user is offered the model picker on first Dashboard open — the
        // previous .gguf file (if any, Fase D2) will be detected and reused.
        settingsStore.updateCoreUrl(identity.coreUrl)
        settingsStore.updateToken(identity.deviceSecret)
        settingsStore.updateDeviceId(identity.deviceId)
        if (identity.workspaceId.isNotBlank()) {
            settingsStore.updateActiveWorkspace(identity.workspaceId, identity.workspaceName)
        }
        if (identity.localCoreToken.isNotBlank()) {
            settingsStore.updateLocalCoreToken(identity.localCoreToken)
        }
        terminalBuffer.append(
            LogSource.SYS,
            "enrollment restored from keystore — device=${identity.deviceId.take(12)}…",
        )
        Log.i("GimoMeshApp", "enrollment recovered from Keystore for device ${identity.deviceId}")
    }
}
