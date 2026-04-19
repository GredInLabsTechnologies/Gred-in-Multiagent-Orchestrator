package com.gredinlabs.gimomesh.ble

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.bluetooth.le.ScanResult
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import com.gredinlabs.gimomesh.MainActivity
import com.gredinlabs.gimomesh.R

/**
 * Receives BLE scan results via PendingIntent.
 * This fires with ZERO app processes running — Android's BLE HW scanner
 * detects the advertisement and wakes this receiver.
 *
 * Payload: [timestamp(4B) + counter(4B) + HMAC-SHA256-128(16B)] = 24 bytes
 */
class BleWakeReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val results = intent.getParcelableArrayListExtra<ScanResult>(
            "android.bluetooth.le.extra.LIST_SCAN_RESULT"
        ) ?: return

        for (result in results) {
            val manufacturerData = result.scanRecord
                ?.getManufacturerSpecificData(GIMO_MANUFACTURER_ID)
                ?: continue

            if (manufacturerData.size != 24) continue

            // Verify HMAC token
            val verifier = WakeTokenVerifier(context)
            if (!verifier.verify(manufacturerData)) continue

            // Valid wake — show notification
            showWakeNotification(context)
            return
        }
    }

    private fun showWakeNotification(context: Context) {
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        // Create channel
        val channel = NotificationChannel(
            CHANNEL_ID, "GIMO Mesh Wake",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Wake requests from GIMO Core"
        }
        nm.createNotificationChannel(channel)

        // Launch intent
        val launchIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("auto_start_mesh", true)
        }
        val pendingLaunch = PendingIntent.getActivity(
            context, 0, launchIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("GIMO Mesh")
            .setContentText("Your device is needed for inference work.")
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .addAction(0, "Start Mesh", pendingLaunch)
            .build()

        nm.notify(WAKE_NOTIFICATION_ID, notification)
    }

    companion object {
        const val GIMO_MANUFACTURER_ID = 0x4749 // "GI" — placeholder, replace with registered ID
        const val CHANNEL_ID = "gimo_mesh_wake"
        const val WAKE_NOTIFICATION_ID = 100
    }
}
