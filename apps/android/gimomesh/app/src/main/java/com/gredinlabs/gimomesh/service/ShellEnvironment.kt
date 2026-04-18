package com.gredinlabs.gimomesh.service

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Manages the embedded shell environment extracted from APK assets.
 *
 * Three independent sub-resources (BUGS_LATENTES §H1 fix 2026-04-17):
 *   - [isShellReady]: busybox static + symlinks (sh, wget, curl, ls, …). Needed
 *     by utility tasks that shell-out to coreutils.
 *   - [isInferenceReady]: llama-server binary. Needed by InferenceRunner.
 *   - [isCoreRuntimeReady]: embedded GIMO Core (Python bundle). Needed by
 *     EmbeddedCoreRunner / server mode.
 *
 * The three are decoupled: a device can have Core runtime available but
 * no inference binary (server mode without local inference), or vice-versa.
 * Each sub-resource extracts independently and its own flag gates its runner.
 * [isReady] is kept for backward-compat and is `true` if the shell sub-resource
 * is usable (the most permissive historical meaning).
 */
class ShellEnvironment(private val context: Context) {

    private val binDir = File(context.filesDir, "bin")
    private val modelsDir = File(context.filesDir, "models")
    private val runtimeDir = File(context.filesDir, "runtime")
    private val tmpDir = File(context.cacheDir, "tmp")
    private val runtimeJson = Json { ignoreUnknownKeys = true; isLenient = true }

    private var embeddedCoreRuntime: EmbeddedCoreRuntime? = null

    /**
     * Busybox + coreutils symlinks were extracted and the shell binary is
     * executable. This alone is enough for utility tasks that shell-out.
     */
    var isShellReady: Boolean = false
        private set

    /** llama-server binary was extracted and is executable. */
    var isInferenceReady: Boolean = false
        private set

    /** Embedded GIMO Core (Python bundle) manifest + layout is valid. */
    var isCoreRuntimeReady: Boolean = false
        private set

    /**
     * Backward-compatible flag. `true` when at least the shell sub-resource
     * is operational. Prefer [isShellReady] / [isInferenceReady] /
     * [isCoreRuntimeReady] in new code so callers gate on what they actually
     * need.
     */
    val isReady: Boolean
        get() = isShellReady

    suspend fun init(): Boolean = withContext(Dispatchers.IO) {
        binDir.mkdirs()
        modelsDir.mkdirs()
        runtimeDir.mkdirs()
        tmpDir.mkdirs()

        // 1. Shell sub-resource (busybox + symlinks) — independent.
        isShellReady = try {
            initShell()
        } catch (_: Exception) {
            false
        }

        // 2. Inference sub-resource (llama-server) — independent.
        isInferenceReady = try {
            initInference()
        } catch (_: Exception) {
            false
        }

        // 3. Core runtime sub-resource (embedded Python) — independent.
        isCoreRuntimeReady = try {
            embeddedCoreRuntime = prepareEmbeddedCoreRuntime()
            embeddedCoreRuntime != null
        } catch (_: Exception) {
            embeddedCoreRuntime = null
            false
        }

        // Boot succeeds if any sub-resource is operational; caller inspects
        // the individual flags to decide what runners to launch.
        isShellReady || isInferenceReady || isCoreRuntimeReady
    }

    /**
     * Attempts to extract busybox and wire its coreutils symlinks. Returns
     * `true` only if the shell binary `sh` is present and executable.
     */
    private fun initShell(): Boolean {
        val busybox = File(binDir, "busybox")
        val ok = extractAsset("bin/busybox", busybox)
        if (!ok) return false

        val commands = listOf(
            "sh", "wget", "curl", "ls", "cat", "grep", "sed", "awk",
            "tar", "gzip", "gunzip", "cp", "mv", "rm", "mkdir",
            "chmod", "kill", "ps", "top", "df", "du", "head", "tail",
            "wc", "sort", "uniq", "find", "xargs", "tee", "nohup",
        )
        for (command in commands) {
            ensureBusyboxLink(command, busybox)
        }
        return File(binDir, "sh").exists()
    }

    /**
     * Attempts to extract llama-server. Returns `true` if the binary is
     * present and executable (does NOT validate that a model is loaded —
     * that's InferenceRunner's responsibility).
     */
    private fun initInference(): Boolean {
        val llamaServer = File(binDir, "llama-server")
        val ok = extractAsset("bin/llama-server", llamaServer)
        return ok && llamaServer.canExecute()
    }

    suspend fun exec(
        command: String,
        env: Map<String, String> = emptyMap(),
        timeoutMs: Long = 30_000,
    ): ShellResult = withContext(Dispatchers.IO) {
        if (!isReady) {
            return@withContext ShellResult(
                stdout = "",
                stderr = "shell environment not ready",
                exitCode = -1,
            )
        }

        val shell = getBinaryPath("sh")
        if (!shell.exists()) {
            return@withContext ShellResult(
                stdout = "",
                stderr = "shell binary not available",
                exitCode = -1,
            )
        }

        coroutineScope {
            try {
                val process = ProcessBuilder(shell.absolutePath, "-c", command)
                    .directory(context.filesDir)
                    .also { builder ->
                        builder.environment().clear()
                        builder.environment().putAll(buildEnvironment(env))
                    }
                    .redirectErrorStream(false)
                    .start()

                val stdoutTask = async {
                    process.inputStream.bufferedReader().use { it.readText().trim() }
                }
                val stderrTask = async {
                    process.errorStream.bufferedReader().use { it.readText().trim() }
                }

                val finished = process.waitFor(timeoutMs, TimeUnit.MILLISECONDS)
                if (!finished) {
                    process.destroyForcibly()
                    process.waitFor(2, TimeUnit.SECONDS)
                    val outputs = awaitAll(stdoutTask, stderrTask)
                    return@coroutineScope ShellResult(
                        stdout = outputs[0],
                        stderr = "TIMEOUT after ${timeoutMs}ms".trim(),
                        exitCode = -1,
                    )
                }

                val outputs = awaitAll(stdoutTask, stderrTask)
                ShellResult(
                    stdout = outputs[0],
                    stderr = outputs[1],
                    exitCode = process.exitValue(),
                )
            } catch (e: Exception) {
                ShellResult(
                    stdout = "",
                    stderr = e.message ?: "exec failed",
                    exitCode = -1,
                )
            }
        }
    }

    fun getModelsDir(): File = modelsDir

    fun getBinaryPath(name: String): File = File(binDir, name)

    fun getEmbeddedCoreRuntime(): EmbeddedCoreRuntime? = embeddedCoreRuntime

    fun buildEnvironment(extra: Map<String, String> = emptyMap()): Map<String, String> = buildMap {
        put("PATH", "${binDir.absolutePath}:/system/bin:/system/xbin")
        put("HOME", context.filesDir.absolutePath)
        put("TMPDIR", tmpDir.absolutePath)
        put("LD_LIBRARY_PATH", "/system/lib64:/system/lib")
        put("MODELS_DIR", modelsDir.absolutePath)
        putAll(extra)
    }

    private fun extractAsset(assetPath: String, target: File): Boolean {
        if (target.exists() && target.length() > 0L) {
            target.setExecutable(true, false)
            return true
        }

        context.assets.open(assetPath).use { input ->
            target.outputStream().use { output -> input.copyTo(output) }
        }
        target.setExecutable(true, false)
        return target.exists() && target.length() > 0L
    }

    private fun prepareEmbeddedCoreRuntime(): EmbeddedCoreRuntime? {
        val manifest = readRuntimeManifest() ?: return null
        for (relativePath in manifest.files.distinct()) {
            val normalized = relativePath.trim().removePrefix("/")
            if (normalized.isBlank()) continue
            val target = File(runtimeDir, normalized)
            target.parentFile?.mkdirs()
            extractAsset("runtime/$normalized", target)
        }

        val pythonBinary = File(runtimeDir, manifest.pythonRelPath)
        val repoRoot = File(runtimeDir, manifest.projectRootRelPath)
        if (!pythonBinary.exists() || !repoRoot.exists()) {
            return null
        }

        pythonBinary.setExecutable(true, false)
        val pythonPath = manifest.pythonPathEntries
            .map { File(runtimeDir, it).absolutePath }
            .filter { it.isNotBlank() }
            .joinToString(":")

        return EmbeddedCoreRuntime(
            rootDir = runtimeDir,
            pythonBinary = pythonBinary,
            repoRoot = repoRoot,
            pythonPath = pythonPath,
            extraEnv = manifest.extraEnv,
        )
    }

    private fun readRuntimeManifest(): EmbeddedCoreRuntimeManifest? {
        return try {
            val raw = context.assets.open("runtime/gimo-core-runtime.json")
                .bufferedReader()
                .use { it.readText() }
            runtimeJson.decodeFromString<EmbeddedCoreRuntimeManifest>(raw)
        } catch (_: Exception) {
            null
        }
    }

    private fun ensureBusyboxLink(command: String, busybox: File) {
        val target = File(binDir, command)
        if (target.exists()) return

        val process = ProcessBuilder(
            busybox.absolutePath,
            "ln",
            "-sf",
            busybox.absolutePath,
            target.absolutePath,
        )
            .directory(binDir)
            .start()
        process.waitFor(5, TimeUnit.SECONDS)
    }
}

/**
 * Espejo Kotlin del subset del [rove.manifest.WheelhouseManifest] (rove 1.0.0)
 * que el runtime Android necesita a extract-time.
 *
 * NOTA — el campo `repo_root_rel_path` fue renombrado a `project_root_rel_path`
 * cuando GIMO migró al schema canónico de rove (2026-04-18). Tolerar ambos
 * nombres sería una regresión de seguridad (dos fuentes de verdad sobre qué
 * path ejecutar), así que sólo se acepta el nuevo nombre — el packaging step
 * (`scripts/package_core_runtime.py`) emite sólo este nombre tras la migración.
 *
 * Campos ignorados del manifest canónico (project_name, tarball_sha256,
 * signature, etc.) son redundantes en Android porque la confianza se deriva
 * del signing del APK, no de verificación Ed25519 in-device. Si en el futuro
 * se añade verificación peer-to-peer de bundles descargados, el signing
 * payload canónico es 4-tupla `<sha>|<target>|<runtime_version>|<project_name>`
 * (ver `rove.manifest.WheelhouseManifest.signing_payload()`).
 */
@Serializable
data class EmbeddedCoreRuntimeManifest(
    val files: List<String> = emptyList(),
    @SerialName("python_rel_path") val pythonRelPath: String,
    @SerialName("project_root_rel_path") val projectRootRelPath: String,
    @SerialName("python_path_entries") val pythonPathEntries: List<String> = emptyList(),
    @SerialName("extra_env") val extraEnv: Map<String, String> = emptyMap(),
)

data class EmbeddedCoreRuntime(
    val rootDir: File,
    val pythonBinary: File,
    val repoRoot: File,
    val pythonPath: String,
    val extraEnv: Map<String, String>,
)

data class ShellResult(
    val stdout: String,
    val stderr: String,
    val exitCode: Int,
) {
    val isSuccess: Boolean get() = exitCode == 0
}
