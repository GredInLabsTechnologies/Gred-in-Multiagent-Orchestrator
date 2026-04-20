package com.gredinlabs.gimomesh.service

import android.content.Context
import android.os.Build
import com.gredinlabs.gimomesh.data.store.ModelStorage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.io.IOException
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
    // Fase D2 — models live in externalMediaDirs so they survive app reinstall
    // (combined with hasFragileUserData=true the user decides on uninstall).
    // Resolved on every call so a device remounting /storage doesn't leave us
    // with a stale File reference.
    private val modelsDir: File get() = ModelStorage.resolveModelsDir(context)
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
     * Locates busybox (shipped as libbusybox.so in jniLibs). Wires coreutils
     * symlinks in binDir that point into nativeLibraryDir — execve follows
     * the symlink and lands on the permitted native dir, bypassing the
     * Android 10+ untrusted_app exec restriction on filesDir.
     *
     * Returns `true` only if the shell binary `sh` is present and executable.
     */
    private fun initShell(): Boolean {
        val nativeDir = File(context.applicationInfo.nativeLibraryDir)
        val busybox = File(nativeDir, "libbusybox.so")
        if (!busybox.exists() || !busybox.canExecute()) return false

        // Symlink busybox under binDir/<command> → nativeDir/libbusybox.so
        val commands = listOf(
            "sh", "wget", "ls", "cat", "grep", "sed", "awk",
            "tar", "gzip", "gunzip", "cp", "mv", "rm", "mkdir",
            "chmod", "kill", "ps", "top", "df", "du", "head", "tail",
            "wc", "sort", "uniq", "find", "xargs", "tee", "nohup",
            "sha256sum", "md5sum", "sleep", "echo", "printf", "dd",
            "basename", "dirname", "seq", "stat", "date", "uname",
            "true", "false", "uptime", "nproc", "free",
        )
        for (command in commands) {
            ensureBusyboxLink(command, busybox)
        }
        return File(binDir, "sh").exists()
    }

    /**
     * Locates llama-server. Since Android 10 blocks execve of binaries in
     * /data/data/<pkg>/files/ (untrusted_app SELinux context), we ship the
     * binary as a JNI library (libllama-server.so under jniLibs/<abi>/) so
     * it lands in applicationInfo.nativeLibraryDir, which is labeled for
     * native exec. Returns `true` if the binary is present and executable.
     */
    private fun initInference(): Boolean {
        val nativeDir = File(context.applicationInfo.nativeLibraryDir)
        val nativeBin = File(nativeDir, "libllama-server.so")
        if (nativeBin.exists() && nativeBin.canExecute()) {
            // Keep a stable path under binDir for any legacy caller — but
            // prefer getBinaryPath("llama-server") which resolves to the
            // native dir directly (see below).
            return true
        }
        return false
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

    fun getBinaryPath(name: String): File {
        // Binaries shipped via jniLibs live in applicationInfo.nativeLibraryDir
        // (labeled for exec). Binaries extracted to filesDir/bin are legacy.
        if (name == "llama-server") {
            val nativeBin = File(context.applicationInfo.nativeLibraryDir, "libllama-server.so")
            if (nativeBin.exists()) return nativeBin
        }
        return File(binDir, name)
    }

    fun getEmbeddedCoreRuntime(): EmbeddedCoreRuntime? = embeddedCoreRuntime

    fun buildEnvironment(extra: Map<String, String> = emptyMap()): Map<String, String> = buildMap {
        // Priority: /system/bin first so applets present in Android's toybox
        // (sh, uname, seq, sha256sum, cat, ls, echo, …) are resolved there —
        // those pass the Android seccomp filter natively. Our bundled busybox
        // (GNU/Linux static) is second-tier: only used for applets absent from
        // the system (awk, find, xargs, …). SIGSYS (exit 159) happens if the
        // GNU-syscall busybox is resolved for syscalls Android blocks.
        put("PATH", "/system/bin:/system/xbin:${binDir.absolutePath}")
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

    /**
     * ABI del device mapped al path asset que contiene el wheelhouse rove
     * correspondiente. La APK multi-ABI empaqueta un directorio por arch:
     *   assets/runtime/arm64-v8a/       (android-arm64 wheelhouse)
     *   assets/runtime/x86_64/          (android-x86_64 wheelhouse)
     *   assets/runtime/armeabi-v7a/     (android-armv7 wheelhouse)
     *
     * `Build.SUPPORTED_ABIS` devuelve ABIs soportadas en preferencia descending.
     * El primer match con nuestro catálogo gana; si ninguno match, retorna null
     * (device no soportado — el consumer mostrará UI apropiada).
     */
    private fun resolveRuntimeAbi(): String? {
        val supported = Build.SUPPORTED_ABIS.orEmpty()
        val available = setOf("arm64-v8a", "x86_64", "armeabi-v7a")
        return supported.firstOrNull { it in available }
    }

    private fun prepareEmbeddedCoreRuntime(): EmbeddedCoreRuntime? {
        val abi = resolveRuntimeAbi() ?: return null
        val manifest = readRuntimeManifest(abi) ?: return null

        // Layout after this method:
        //   runtimeDir/gimo-core-runtime.tar.xz      (the raw bundle, for
        //                                             upgrade-peer sharing)
        //   runtimeDir/extracted/.unpacked.marker    (sentinel: extraction OK)
        //   runtimeDir/extracted/python/             (standalone CPython)
        //   runtimeDir/extracted/site-packages/      (wheels)
        //   runtimeDir/extracted/repo/               (tools/gimo_server, …)
        val tarballAsset = "runtime/$abi/${manifest.tarballName}"
        val tarballDest = File(runtimeDir, manifest.tarballName)
        val extractedRoot = File(runtimeDir, "extracted")
        val unpackedMarker = File(extractedRoot, ".unpacked.v${manifest.runtimeVersion.ifBlank { "unknown" }}")

        runtimeDir.mkdirs()

        // 1. Always ensure the tarball is on disk (size-matches manifest).
        if (!tarballDest.exists() || tarballDest.length() != manifest.compressedSizeBytes) {
            try {
                extractAsset(tarballAsset, tarballDest)
            } catch (ex: IOException) {
                return null
            }
        }

        // 2. Unpack the tar.xz into extracted/ if the version marker doesn't
        // match (re-install/upgrade path). Uses Apache Commons Compress +
        // tukaani XZ — both pure-Java, work under untrusted_app sandbox.
        if (!unpackedMarker.exists()) {
            if (extractedRoot.exists()) extractedRoot.deleteRecursively()
            extractedRoot.mkdirs()
            try {
                extractTarXz(tarballDest, extractedRoot)
                unpackedMarker.parentFile.mkdirs()
                unpackedMarker.writeText("ok\n", Charsets.UTF_8)
            } catch (ex: Exception) {
                // Leave the partial extraction for diagnostics; return null so
                // isCoreRuntimeReady stays false.
                return null
            }
        }

        val pythonBinary = File(extractedRoot, manifest.pythonRelPath)
        val repoRoot = File(extractedRoot, manifest.projectRootRelPath)
        val pythonPath = manifest.pythonPathEntries
            .map { File(extractedRoot, it).absolutePath }
            .filter { it.isNotBlank() }
            .joinToString(":")

        // Sanity: pythonBinary must be executable after unpack.
        if (pythonBinary.exists()) {
            pythonBinary.setExecutable(true, false)
        } else {
            return null
        }

        return EmbeddedCoreRuntime(
            rootDir = runtimeDir,
            pythonBinary = pythonBinary,
            repoRoot = repoRoot,
            pythonPath = pythonPath,
            extraEnv = manifest.extraEnv,
        )
    }

    /** Parse rove manifest for the ABI-scoped bundle. */
    private fun readRuntimeManifest(abi: String): EmbeddedCoreRuntimeManifest? {
        return try {
            val raw = context.assets.open("runtime/$abi/gimo-core-runtime.manifest.json")
                .bufferedReader()
                .use { it.readText() }
            runtimeJson.decodeFromString<EmbeddedCoreRuntimeManifest>(raw)
        } catch (_: Exception) {
            null
        }
    }

    /**
     * Extract a .tar.xz archive to a destination directory using pure-Java
     * streams (commons-compress + tukaani-xz). Designed for the embedded Core
     * runtime bundle: preserves executable bits, resolves "./xxx" entries,
     * skips absolute or traversal paths defensively, and re-creates parent
     * dirs on the fly. Throws on any I/O or malformed-tar failure — the
     * caller handles the isCoreRuntimeReady=false path.
     */
    private fun extractTarXz(src: File, destRoot: File) {
        destRoot.mkdirs()
        val destCanonical = destRoot.canonicalFile
        src.inputStream().buffered().use { fis ->
            org.tukaani.xz.XZInputStream(fis).use { xz ->
                org.apache.commons.compress.archivers.tar.TarArchiveInputStream(xz).use { tar ->
                    while (true) {
                        val entry = tar.nextEntry ?: break
                        val name = entry.name
                        if (name.startsWith("/") || name.contains("..")) continue
                        val target = File(destRoot, name)
                        val targetCanonical = target.canonicalFile
                        if (!targetCanonical.path.startsWith(destCanonical.path)) continue
                        if (entry.isDirectory) {
                            target.mkdirs()
                            continue
                        }
                        if (entry.isSymbolicLink) {
                            target.parentFile?.mkdirs()
                            try {
                                java.nio.file.Files.createSymbolicLink(
                                    target.toPath(),
                                    java.nio.file.Paths.get(entry.linkName),
                                )
                            } catch (_: Exception) {
                                // fall through — missing symlinks are not fatal
                                // for our use (CPython standalone uses symlinks
                                // in share/terminfo that aren't needed to run
                                // uvicorn).
                            }
                            continue
                        }
                        target.parentFile?.mkdirs()
                        target.outputStream().use { out -> tar.copyTo(out) }
                        // Preserve exec bit: tar mode bits include 0o111.
                        if ((entry.mode and 0b001_001_001) != 0) {
                            target.setExecutable(true, false)
                        }
                    }
                }
            }
        }
    }

    private fun ensureBusyboxLink(command: String, busybox: File) {
        val target = File(binDir, command)
        if (target.exists()) return
        // Use Java NIO to create the symlink — bootstrapping busybox via its
        // own `ln` applet doesn't work because when invoked as "libbusybox.so"
        // busybox treats the basename as the applet name ("applet not found").
        // Symlinks under binDir named after the applet ("sh", "ls", …) DO
        // resolve to the correct applet when exec'd later, because argv[0] =
        // the symlink's basename.
        try {
            java.nio.file.Files.createSymbolicLink(
                target.toPath(),
                busybox.toPath(),
            )
        } catch (_: Exception) {
            // If symlink creation fails (filesystem restriction, pre-existing
            // file we couldn't stat), fall back silently — caller checks for
            // target existence afterwards.
        }
    }
}

/**
 * Espejo Kotlin del subset del [rove.manifest.WheelhouseManifest] (rove 1.0.1)
 * que el runtime Android necesita para localizar y extraer el wheelhouse.
 *
 * La APK empaqueta un bundle rove por ABI (arm64-v8a, x86_64, armeabi-v7a)
 * bajo `assets/runtime/<abi>/`. Cada bundle tiene:
 *   - ``gimo-core-runtime.tar.xz`` — wheelhouse firmado
 *   - ``gimo-core-runtime.manifest.json`` — este schema, firmado
 *
 * Campos que leemos (subset del WheelhouseManifest completo):
 *   - tarballName / compressedSizeBytes — para verificar integridad al copy
 *   - tarballSha256 / signature — para verificación Ed25519 si se añade
 *     verificación in-device en el futuro
 *   - pythonRelPath / projectRootRelPath / pythonPathEntries — paths dentro
 *     del wheelhouse extraído (usados por el runner/Termux al arrancar Core)
 *   - extraEnv — env vars opcionales para el proceso Core
 *
 * Payload firmado por rove: 4-tupla canónica
 * ``<tarball_sha256>|<target>|<runtime_version>|<project_name>`` en UTF-8.
 * Si Android implementa verificación Ed25519 local, derivar el payload con
 * los fields de este data class.
 */
@Serializable
data class EmbeddedCoreRuntimeManifest(
    @SerialName("project_name") val projectName: String = "gimo-core",
    @SerialName("runtime_version") val runtimeVersion: String = "",
    val target: String = "",
    @SerialName("tarball_name") val tarballName: String,
    @SerialName("tarball_sha256") val tarballSha256: String = "",
    @SerialName("compressed_size_bytes") val compressedSizeBytes: Long = 0L,
    val signature: String = "",
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
