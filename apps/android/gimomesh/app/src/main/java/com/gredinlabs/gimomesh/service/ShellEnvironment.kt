package com.gredinlabs.gimomesh.service

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Manages the embedded shell environment extracted from APK assets.
 */
class ShellEnvironment(private val context: Context) {

    private val binDir = File(context.filesDir, "bin")
    private val modelsDir = File(context.filesDir, "models")
    private val tmpDir = File(context.cacheDir, "tmp")

    var isReady: Boolean = false
        private set

    suspend fun init(): Boolean = withContext(Dispatchers.IO) {
        try {
            binDir.mkdirs()
            modelsDir.mkdirs()
            tmpDir.mkdirs()

            val busybox = File(binDir, "busybox")
            val llamaServer = File(binDir, "llama-server")

            val busyboxReady = extractAsset("bin/busybox", busybox)
            val llamaReady = extractAsset("bin/llama-server", llamaServer)
            if (!busyboxReady || !llamaReady) {
                isReady = false
                return@withContext false
            }

            val commands = listOf(
                "sh", "wget", "curl", "ls", "cat", "grep", "sed", "awk",
                "tar", "gzip", "gunzip", "cp", "mv", "rm", "mkdir",
                "chmod", "kill", "ps", "top", "df", "du", "head", "tail",
                "wc", "sort", "uniq", "find", "xargs", "tee", "nohup",
            )
            for (command in commands) {
                ensureBusyboxLink(command, busybox)
            }

            isReady = File(binDir, "sh").exists() && llamaServer.canExecute()
            isReady
        } catch (_: Exception) {
            isReady = false
            false
        }
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

data class ShellResult(
    val stdout: String,
    val stderr: String,
    val exitCode: Int,
) {
    val isSuccess: Boolean get() = exitCode == 0
}
