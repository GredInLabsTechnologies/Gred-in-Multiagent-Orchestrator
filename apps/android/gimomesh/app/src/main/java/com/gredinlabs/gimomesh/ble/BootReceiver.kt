package com.gredinlabs.gimomesh.ble

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.gredinlabs.gimomesh.GimoMeshApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Re-registers BLE PendingIntent scan after device reboot.
 * BLE HW scans are lost on reboot — this receiver re-starts them.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return

        val app = context.applicationContext as? GimoMeshApp ?: return
        val pendingResult = goAsync()

        CoroutineScope(Dispatchers.IO).launch {
            try {
                val settings = app.settingsStore.settings.first()
                if (settings.bleWakeEnabled) {
                    WakeScanner(context).startScan()
                }
            } finally {
                pendingResult.finish()
            }
        }
    }
}
