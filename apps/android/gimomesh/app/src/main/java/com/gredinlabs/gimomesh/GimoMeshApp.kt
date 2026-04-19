package com.gredinlabs.gimomesh

import android.app.Application
import com.gredinlabs.gimomesh.data.store.SettingsStore
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
    }
}
