package com.gredinlabs.gimomesh.data.network

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Handler
import android.os.Looper
import java.util.Collections
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Discovers GIMO Core servers on the LAN via mDNS.
 *
 * Pre-enrollment the device cannot verify the TXT-record HMAC because it does
 * not yet have a bearer token. Post-enrollment callers can pass the token and
 * mark discovered cores as verified.
 */
class CoreDiscoveryManager(context: Context) {

    data class DiscoveredCore(
        val host: String,
        val port: Int,
        val version: String = "",
        val coreId: String = "",
        val hmac: String = "",
        val verified: Boolean = false,
    ) {
        val url: String get() = "http://$host:$port"
    }

    private val nsdManager = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private val mainHandler = Handler(Looper.getMainLooper())
    private var discoveryListener: NsdManager.DiscoveryListener? = null
    private var timeoutRunnable: Runnable? = null

    fun startDiscovery(
        token: String = "",
        onFound: (DiscoveredCore) -> Unit,
        timeoutMs: Long = 10_000,
    ) {
        stopDiscovery()

        val seen = Collections.synchronizedSet(mutableSetOf<String>())
        discoveryListener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) = Unit

            override fun onDiscoveryStopped(serviceType: String) = Unit

            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                stopDiscovery()
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                stopDiscovery()
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                resolveService(token, serviceInfo, seen, onFound)
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) = Unit
        }

        try {
            nsdManager.discoverServices(
                SERVICE_TYPE,
                NsdManager.PROTOCOL_DNS_SD,
                discoveryListener,
            )
        } catch (_: Exception) {
            stopDiscovery()
            return
        }

        timeoutRunnable = Runnable { stopDiscovery() }.also {
            mainHandler.postDelayed(it, timeoutMs)
        }
    }

    fun stopDiscovery() {
        timeoutRunnable?.let(mainHandler::removeCallbacks)
        timeoutRunnable = null
        discoveryListener?.let { listener ->
            try {
                nsdManager.stopServiceDiscovery(listener)
            } catch (_: Exception) {
                // Discovery might have already stopped or never started.
            }
        }
        discoveryListener = null
    }

    @Suppress("DEPRECATION")
    private fun resolveService(
        token: String,
        serviceInfo: NsdServiceInfo,
        seen: MutableSet<String>,
        onFound: (DiscoveredCore) -> Unit,
    ) {
        try {
            nsdManager.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) = Unit

                override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
                    val host = serviceInfo.host?.hostAddress?.takeIf(String::isNotBlank) ?: return
                    val port = serviceInfo.port
                    val identity = "$host:$port"
                    if (!seen.add(identity)) return

                    val attrs = serviceInfo.attributes
                    val version = attrs["version"]?.decodeToString().orEmpty()
                    val coreId = attrs["core_id"]?.decodeToString().orEmpty()
                    val hmac = attrs["hmac"]?.decodeToString().orEmpty()
                    val verified = token.isNotBlank() && hmac.isNotBlank() && verifyHmac(token, identity, hmac)

                    onFound(
                        DiscoveredCore(
                            host = host,
                            port = port,
                            version = version,
                            coreId = coreId,
                            hmac = hmac,
                            verified = verified,
                        ),
                    )
                }
            })
        } catch (_: Exception) {
            // Ignore individual resolution failures and keep discovery running.
        }
    }

    companion object {
        private const val SERVICE_TYPE = "_gimo._tcp."

        fun verifyHmac(token: String, payload: String, sig: String): Boolean {
            val mac = Mac.getInstance("HmacSHA256")
            mac.init(SecretKeySpec(token.toByteArray(), "HmacSHA256"))
            val expected = mac.doFinal(payload.toByteArray())
                .joinToString("") { "%02x".format(it) }
                .take(16)
            return expected.equals(sig, ignoreCase = true)
        }
    }
}
