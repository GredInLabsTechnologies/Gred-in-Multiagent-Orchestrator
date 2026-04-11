package com.gredinlabs.gimomesh.ble

import android.content.Context
import com.gredinlabs.gimomesh.GimoMeshApp
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import java.nio.ByteBuffer
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Verifies HMAC-signed BLE wake advertisements.
 *
 * Payload format (24 bytes):
 *   [0..3]   timestamp (uint32, seconds since epoch)
 *   [4..7]   counter   (uint32, monotonic)
 *   [8..23]  HMAC-SHA256-128 (first 16 bytes of HMAC-SHA256)
 *
 * Verification:
 *   1. Reject if timestamp is more than 60s old (replay protection)
 *   2. Reject if counter <= last seen counter (replay protection)
 *   3. Verify HMAC-SHA256(PSK, timestamp || counter) truncated to 16 bytes
 */
class WakeTokenVerifier(private val context: Context) {

    fun verify(payload: ByteArray): Boolean {
        if (payload.size != 24) return false

        val buf = ByteBuffer.wrap(payload)
        val timestamp = buf.int.toLong() and 0xFFFFFFFFL
        val counter = buf.int.toLong() and 0xFFFFFFFFL
        val receivedHmac = ByteArray(16)
        buf.get(receivedHmac)

        // 1. Timestamp freshness (60s window)
        val now = System.currentTimeMillis() / 1000
        if (kotlin.math.abs(now - timestamp) > MAX_AGE_SECONDS) return false

        // 2. Counter monotonicity (persisted to survive process death)
        val lastSeenCounter = loadLastSeenCounter()
        if (counter <= lastSeenCounter) return false

        // 3. HMAC verification
        val psk = loadPsk() ?: return false
        val message = ByteBuffer.allocate(8)
            .putInt(timestamp.toInt())
            .putInt(counter.toInt())
            .array()

        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(psk, "HmacSHA256"))
        val fullHmac = mac.doFinal(message)
        val expectedHmac = fullHmac.copyOfRange(0, 16)

        if (!expectedHmac.contentEquals(receivedHmac)) return false

        // Accept — persist counter
        saveLastSeenCounter(counter)
        return true
    }

    private fun loadPsk(): ByteArray? {
        val app = context.applicationContext as? GimoMeshApp ?: return null
        val hex = runBlocking { app.settingsStore.settings.first().bleWakeKey }
        if (hex.isEmpty() || hex.length % 2 != 0) return null
        return hexToBytes(hex)
    }

    private fun loadLastSeenCounter(): Long {
        val prefs = context.getSharedPreferences(COUNTER_PREFS, Context.MODE_PRIVATE)
        return prefs.getLong(KEY_LAST_COUNTER, 0L)
    }

    private fun saveLastSeenCounter(counter: Long) {
        context.getSharedPreferences(COUNTER_PREFS, Context.MODE_PRIVATE)
            .edit().putLong(KEY_LAST_COUNTER, counter).apply()
    }

    private fun hexToBytes(hex: String): ByteArray? {
        val len = hex.length
        val data = ByteArray(len / 2)
        for (i in 0 until len step 2) {
            val hi = Character.digit(hex[i], 16)
            val lo = Character.digit(hex[i + 1], 16)
            if (hi == -1 || lo == -1) return null
            data[i / 2] = ((hi shl 4) + lo).toByte()
        }
        return data
    }

    companion object {
        const val MAX_AGE_SECONDS = 60L
        private const val COUNTER_PREFS = "gimo_ble_counter"
        private const val KEY_LAST_COUNTER = "last_seen_counter"
    }
}
