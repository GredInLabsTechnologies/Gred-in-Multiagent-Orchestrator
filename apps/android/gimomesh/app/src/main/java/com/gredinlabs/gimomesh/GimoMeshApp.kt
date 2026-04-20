package com.gredinlabs.gimomesh

import android.app.Application
import android.util.Log
import com.gredinlabs.gimomesh.data.model.LogLevel
import com.gredinlabs.gimomesh.data.model.LogSource
import com.gredinlabs.gimomesh.data.store.SettingsStore
import com.gredinlabs.gimomesh.service.ChaquopyBridge
import com.gredinlabs.gimomesh.service.HostRuntimeReporter
import com.gredinlabs.gimomesh.service.TerminalBuffer

class GimoMeshApp : Application() {

    lateinit var terminalBuffer: TerminalBuffer
        private set
    lateinit var hostRuntimeReporter: HostRuntimeReporter
        private set
    lateinit var settingsStore: SettingsStore
        private set

    override fun onCreate() {
        super.onCreate()
        terminalBuffer = TerminalBuffer()
        hostRuntimeReporter = HostRuntimeReporter()
        settingsStore = SettingsStore(this)

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
}
