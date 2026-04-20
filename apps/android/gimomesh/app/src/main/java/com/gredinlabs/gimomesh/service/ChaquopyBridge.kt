package com.gredinlabs.gimomesh.service

import android.content.Context
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/**
 * Thin wrapper around Chaquopy's [Python] singleton.
 *
 * Chaquopy embeds a bionic-compatible CPython build into the APK
 * ([`PEP 738`](https://peps.python.org/pep-0738/) Tier 3 — arm64-v8a + x86_64)
 * and exposes it through JNI. The interpreter is a **singleton per JVM
 * process** — there is no public API to restart or fork it. Any "restart"
 * requires killing the Android Service (which restarts the JVM). This is a
 * known Chaquopy design constraint; see [chaquo/chaquopy#484](https://github.com/chaquo/chaquopy/issues/484).
 *
 * Lifecycle:
 *   - [ensureStarted] is idempotent. First caller initialises the interpreter;
 *     subsequent callers see the already-initialised singleton.
 *   - [runSmokeTest] invokes `gimo_smoke.smoke()` in the Python side and
 *     returns a string dump suitable for logcat / terminal buffers.
 *   - Fase B adds `bootServerCore()` that invokes the real
 *     `tools.gimo_server.main:app` via uvicorn.
 *
 * Thread-safety: all public methods are safe to call from any thread.
 * Chaquopy's JNI layer serialises access to the GIL internally.
 */
object ChaquopyBridge {
    private const val TAG = "ChaquopyBridge"
    private const val SMOKE_MODULE = "gimo_smoke"

    @Volatile
    private var started: Boolean = false

    /**
     * Initialise the embedded CPython runtime. Safe to call multiple times —
     * only the first call has an effect (underlying [Python.isStarted] guards
     * the native init path).
     */
    fun ensureStarted(context: Context) {
        if (started) return
        synchronized(this) {
            if (started) return
            if (!Python.isStarted()) {
                Python.start(AndroidPlatform(context.applicationContext))
            }
            started = true
            Log.i(TAG, "chaquopy python runtime initialised")
        }
    }

    /**
     * Runs the smoke test module and returns a one-line summary:
     * ``cpython 3.13.x on aarch64 / six=true``. Throws on any failure —
     * caller logs to terminal buffer + reporter.
     */
    fun runSmokeTest(context: Context): String {
        ensureStarted(context)
        val py = Python.getInstance()
        val module = py.getModule(SMOKE_MODULE)
        val result = module.callAttr("smoke").asMap()
        val version = result[py.builtins.callAttr("str", "python_version")]?.toString() ?: "?"
        val machine = result[py.builtins.callAttr("str", "machine")]?.toString() ?: "?"
        val six = result[py.builtins.callAttr("str", "six_imported")]?.toString() ?: "?"
        return "cpython $version on $machine / six=$six"
    }

    /**
     * Quick yes/no probe — cheaper than [runSmokeTest] because the Python side
     * only touches `sys` + `platform`, skipping the pip-installed `six`.
     */
    fun ping(context: Context): String {
        ensureStarted(context)
        return Python.getInstance()
            .getModule(SMOKE_MODULE)
            .callAttr("ping")
            .toString()
    }

    val isStarted: Boolean
        get() = started
}
