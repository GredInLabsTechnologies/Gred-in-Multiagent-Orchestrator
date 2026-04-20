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
    private const val SERVER_MODULE = "gimo_server_entry"

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
        val fastapi = result[py.builtins.callAttr("str", "fastapi")]?.toString() ?: "?"
        val starlette = result[py.builtins.callAttr("str", "starlette")]?.toString() ?: "?"
        val uvicorn = result[py.builtins.callAttr("str", "uvicorn")]?.toString() ?: "?"
        val anyio = result[py.builtins.callAttr("str", "anyio")]?.toString() ?: "?"
        return "cpython $version on $machine / fastapi=$fastapi starlette=$starlette uvicorn=$uvicorn anyio=$anyio"
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

    // -------------------------------------------------------------------------
    // GIMO Core server lifecycle (Fase B)
    // -------------------------------------------------------------------------
    //
    // `gimo_server_entry.py` owns the in-process uvicorn daemon. These wrappers
    // are thin shims — no state lives here, so EmbeddedCoreRunner can freely
    // start/stop without worrying about a second layer of bookkeeping.

    /**
     * Asynchronously starts uvicorn on a daemon thread inside the embedded
     * CPython. Returns immediately; the caller polls `/health` or `/ready`
     * via HTTP to know when the server accepts connections.
     *
     * The [args] map must contain:
     *   - `rove_site_packages` (String): absolute path to the rove-extracted
     *     site-packages dir providing pydantic_core, cryptography, psutil, …
     *   - `rove_repo_root` (String): absolute path to the dir that contains
     *     the `tools/gimo_server/` tree.
     *   - `rove_extra_paths` (String): `:`-joined extra sys.path entries.
     *   - `host` (String): bind host, typically "0.0.0.0".
     *   - `port` (Int): bind port.
     *   - `env` (Map<String, String>): ORCH_* environment variables to publish.
     */
    fun startServer(args: Map<String, Any>) {
        val py = Python.getInstance()
        py.getModule(SERVER_MODULE).callAttr("start_server", args)
    }

    /** Signals uvicorn to exit. Non-blocking. */
    fun stopServer() {
        if (!started) return
        try {
            Python.getInstance().getModule(SERVER_MODULE).callAttr("stop_server")
        } catch (t: Throwable) {
            // Entrypoint module may not be loaded if start_server was never
            // called. Safe to ignore — nothing to stop.
        }
    }

    /**
     * Blocks (on the Python side) until the uvicorn daemon thread exits or
     * [timeoutSeconds] elapses. Returns true on clean shutdown, false on
     * timeout. Safe to call even if the server was never started.
     */
    fun waitForServerShutdown(timeoutSeconds: Double): Boolean {
        if (!started) return true
        return try {
            Python.getInstance()
                .getModule(SERVER_MODULE)
                .callAttr("wait_for_shutdown", timeoutSeconds)
                .toBoolean()
        } catch (_: Throwable) {
            false
        }
    }

    /** Cheap pre-flight probe — invokes `runtime_probe(args)` on the Python side. */
    fun runRuntimeProbe(context: Context, args: Map<String, Any>): String {
        ensureStarted(context)
        val result = Python.getInstance()
            .getModule(SERVER_MODULE)
            .callAttr("runtime_probe", args)
            .asMap()
        return result.entries.joinToString(prefix = "{", postfix = "}") { (k, v) ->
            "$k=$v"
        }
    }
}
