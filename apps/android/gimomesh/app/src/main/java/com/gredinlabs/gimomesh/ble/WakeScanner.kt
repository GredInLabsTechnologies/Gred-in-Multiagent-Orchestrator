package com.gredinlabs.gimomesh.ble

import android.app.PendingIntent
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.Intent

/**
 * Registers a hardware-level BLE scan with PendingIntent.
 * This scan runs at the Bluetooth chip level with ZERO app processes.
 * Battery cost: ~0.5%/day.
 *
 * When a matching advertisement is detected, Android fires BleWakeReceiver
 * even if the app is completely dead.
 */
class WakeScanner(private val context: Context) {

    fun startScan() {
        val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        val scanner = bluetoothManager?.adapter?.bluetoothLeScanner ?: return

        val filter = ScanFilter.Builder()
            .setManufacturerData(
                BleWakeReceiver.GIMO_MANUFACTURER_ID,
                byteArrayOf(), // Match any data from this manufacturer
                byteArrayOf(), // No mask
            )
            .build()

        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_POWER)
            .setReportDelay(0)
            .build()

        val intent = Intent(context, BleWakeReceiver::class.java)
        val pendingIntent = PendingIntent.getBroadcast(
            context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
        )

        try {
            scanner.startScan(listOf(filter), settings, pendingIntent)
        } catch (_: SecurityException) {
            // BLE permission not granted
        }
    }

    fun stopScan() {
        val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        val scanner = bluetoothManager?.adapter?.bluetoothLeScanner ?: return

        val intent = Intent(context, BleWakeReceiver::class.java)
        val pendingIntent = PendingIntent.getBroadcast(
            context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
        )

        try {
            scanner.stopScan(pendingIntent)
        } catch (_: SecurityException) {}
    }
}
