package com.gredinlabs.gimomesh.service

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.BatteryManager
import android.os.Build
import android.os.StatFs
import com.gredinlabs.gimomesh.data.model.DeviceCapabilities
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Collects device metrics: CPU, RAM, battery, thermals.
 * Port of android_metrics.py to Kotlin.
 * Always active (even in Blackout) for thermal protection.
 */
class MetricsCollector(private val context: Context) {

    data class Snapshot(
        val cpuPercent: Float = 0f,
        val ramPercent: Float = 0f,
        val batteryPercent: Float = -1f,
        val cpuTempC: Float = -1f,
        val gpuTempC: Float = -1f,
        val batteryTempC: Float = -1f,
        val isCharging: Boolean = false,
    )

    // Previous /proc/stat reading for delta-based CPU%
    private var prevTotal = 0L
    private var prevIdle = 0L

    suspend fun collect(): Snapshot = withContext(Dispatchers.IO) {
        // Read battery sticky intent once for temp + charging
        val batteryIntent = try {
            context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        } catch (_: Exception) { null }

        Snapshot(
            cpuPercent = readCpuPercent(),
            ramPercent = readRamPercent(),
            batteryPercent = readBatteryPercent(),
            cpuTempC = readThermalZone("cpu"),
            batteryTempC = readBatteryTemp(batteryIntent),
            isCharging = isCharging(batteryIntent),
        )
    }

    private fun readCpuPercent(): Float {
        return try {
            val stat = File("/proc/stat").readLines().first()
            val parts = stat.split("\\s+".toRegex())
            if (parts.size < 8) return 0f
            val user = parts[1].toLong()
            val nice = parts[2].toLong()
            val system = parts[3].toLong()
            val idle = parts[4].toLong()
            val iowait = parts[5].toLongOrNull() ?: 0L
            val irq = parts[6].toLongOrNull() ?: 0L
            val softirq = parts[7].toLongOrNull() ?: 0L
            val total = user + nice + system + idle + iowait + irq + softirq

            val deltaTotal = total - prevTotal
            val deltaIdle = idle - prevIdle
            prevTotal = total
            prevIdle = idle

            if (deltaTotal <= 0L) 0f else ((deltaTotal - deltaIdle).toFloat() / deltaTotal * 100f)
        } catch (_: Exception) { 0f }
    }

    private fun readRamPercent(): Float {
        return try {
            val memInfo = File("/proc/meminfo").readLines()
            val total = memInfo.find { it.startsWith("MemTotal:") }
                ?.split("\\s+".toRegex())?.get(1)?.toLong() ?: return 0f
            val available = memInfo.find { it.startsWith("MemAvailable:") }
                ?.split("\\s+".toRegex())?.get(1)?.toLong() ?: return 0f
            ((total - available).toFloat() / total * 100f)
        } catch (_: Exception) { 0f }
    }

    private fun readBatteryPercent(): Float {
        val bm = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        return bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY).toFloat()
    }

    private fun readBatteryTemp(batteryIntent: Intent?): Float {
        val temp = batteryIntent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) ?: -1
        return if (temp > 0) temp / 10f else -1f
    }

    private fun isCharging(batteryIntent: Intent?): Boolean {
        val status = batteryIntent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        return status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
    }

    // Cached — collected once, never changes during runtime
    private val _capabilities: DeviceCapabilities by lazy {
        val ramTotalMb = try {
            val memInfo = File("/proc/meminfo").readLines()
            val totalKb = memInfo.find { it.startsWith("MemTotal:") }
                ?.split("\\s+".toRegex())?.get(1)?.toLong() ?: 0L
            (totalKb / 1024).toInt()
        } catch (_: Exception) { 0 }

        val storageFremMb = try {
            val stat = StatFs(context.filesDir.absolutePath)
            (stat.availableBytes / (1024 * 1024)).toInt()
        } catch (_: Exception) { 0 }

        val socModel = try {
            if (Build.VERSION.SDK_INT >= 31) Build.SOC_MODEL
            else {
                File("/proc/cpuinfo").readLines()
                    .find { it.startsWith("Hardware") }
                    ?.substringAfter(":")?.trim() ?: ""
            }
        } catch (_: Exception) { "" }

        val hasVulkan = context.packageManager
            .hasSystemFeature(PackageManager.FEATURE_VULKAN_HARDWARE_LEVEL)

        val maxFd = try {
            File("/proc/sys/fs/file-max").readText().trim().toInt()
        } catch (_: Exception) { 1024 }

        DeviceCapabilities(
            arch = Build.SUPPORTED_ABIS.firstOrNull() ?: "unknown",
            cpuCores = Runtime.getRuntime().availableProcessors(),
            ramTotalMb = ramTotalMb,
            storageFremMb = storageFremMb,
            apiLevel = Build.VERSION.SDK_INT,
            socModel = socModel,
            hasGpuCompute = hasVulkan,
            maxFileDescriptors = maxFd,
        )
    }

    fun getDeviceCapabilities(): DeviceCapabilities = _capabilities

    private fun readThermalZone(type: String): Float {
        return try {
            // Try thermal zones
            val thermalDir = File("/sys/class/thermal/")
            if (!thermalDir.exists()) return -1f
            thermalDir.listFiles()?.filter { it.name.startsWith("thermal_zone") }?.forEach { zone ->
                val zoneType = File(zone, "type").readText().trim()
                if (zoneType.contains(type, ignoreCase = true)) {
                    val temp = File(zone, "temp").readText().trim().toIntOrNull() ?: return@forEach
                    return temp / 1000f
                }
            }
            -1f
        } catch (_: Exception) { -1f }
    }
}
