package com.gredinlabs.gimomesh.service

import com.gredinlabs.gimomesh.data.model.LogLevel
import com.gredinlabs.gimomesh.data.model.LogSource
import com.gredinlabs.gimomesh.data.model.MeshTask
import com.gredinlabs.gimomesh.data.model.TaskResultPayload
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.io.File
import java.security.MessageDigest

/**
 * Sandboxed executor for utility-mode tasks.
 * Each task type runs with strict security constraints:
 * - shell_exec: command allowlist only
 * - file_read/file_hash: restricted to app filesDir
 * - All tasks: hard timeout via coroutine withTimeout
 */
class TaskExecutor(
    private val filesDir: File,
    private val terminalBuffer: TerminalBuffer,
    private val shellEnv: ShellEnvironment? = null,
) {
    companion object {
        // Strict allowlist for shell_exec — busybox applets safe for reporting
        // and hashing. No network, no filesystem mutation, no privilege ops.
        private val SHELL_ALLOWLIST = setOf(
            "ls", "cat", "df", "free", "uname", "date", "echo", "wc", "stat",
            "uptime", "sha256sum", "md5sum", "nproc", "seq", "head", "tail",
            "sort", "uniq", "printf", "basename", "dirname", "true", "false",
        )
        // Dangerous patterns that reject immediately
        private val SHELL_DENY_PATTERNS = listOf(
            ";", "&&", "||", "`", "$(", "rm ", "su ", "chmod ", "chown ",
            "mkfs", "dd ", "reboot", "shutdown",
            // Note: "|" removed from deny — pipe between allowlisted commands
            // is safe and a hard requirement for any realistic shell task.
        )
    }

    suspend fun execute(
        task: MeshTask,
        deviceId: String,
        deviceSecret: String,
    ): TaskResultPayload {
        val startTime = System.currentTimeMillis()
        return try {
            withTimeout(task.timeoutSeconds * 1000L) {
                val result = when (task.taskType) {
                    "ping" -> executePing()
                    "text_validate" -> executeTextValidate(task.payload)
                    "text_transform" -> executeTextTransform(task.payload)
                    "json_validate" -> executeJsonValidate(task.payload)
                    "shell_exec" -> executeShellExec(task.payload)
                    "file_read" -> executeFileRead(task.payload)
                    "file_hash" -> executeFileHash(task.payload)
                    else -> mapOf("error" to "unknown task type: ${task.taskType}")
                }
                val elapsed = (System.currentTimeMillis() - startTime).toInt()
                TaskResultPayload(
                    taskId = task.taskId,
                    deviceId = deviceId,
                    deviceSecret = deviceSecret,
                    status = "completed",
                    result = result,
                    durationMs = elapsed,
                )
            }
        } catch (e: Exception) {
            val elapsed = (System.currentTimeMillis() - startTime).toInt()
            terminalBuffer.append(
                LogSource.TASK,
                "FAILED ${task.taskId.take(8)}: ${e.message}",
                LogLevel.ERROR,
            )
            TaskResultPayload(
                taskId = task.taskId,
                deviceId = deviceId,
                deviceSecret = deviceSecret,
                status = "failed",
                error = e.message ?: "unknown error",
                durationMs = elapsed,
            )
        }
    }

    private fun executePing(): Map<String, String> {
        return mapOf(
            "pong" to "true",
            "timestamp" to System.currentTimeMillis().toString(),
        )
    }

    private fun executeTextValidate(payload: Map<String, String>): Map<String, String> {
        val text = payload["text"] ?: return mapOf("error" to "missing 'text'")
        val pattern = payload["pattern"] ?: return mapOf("error" to "missing 'pattern'")
        return try {
            val regex = Regex(pattern)
            val matches = regex.findAll(text).map { it.value }.toList()
            mapOf(
                "valid" to matches.isNotEmpty().toString(),
                "match_count" to matches.size.toString(),
                "matches" to matches.joinToString(","),
            )
        } catch (e: Exception) {
            mapOf("error" to "invalid regex: ${e.message}")
        }
    }

    private fun executeTextTransform(payload: Map<String, String>): Map<String, String> {
        val text = payload["text"] ?: return mapOf("error" to "missing 'text'")
        val operation = payload["operation"] ?: return mapOf("error" to "missing 'operation'")
        val result = when (operation) {
            "lowercase" -> text.lowercase()
            "uppercase" -> text.uppercase()
            "trim" -> text.trim()
            "reverse" -> text.reversed()
            "length" -> text.length.toString()
            else -> return mapOf("error" to "unknown operation: $operation")
        }
        return mapOf("result" to result)
    }

    private fun executeJsonValidate(payload: Map<String, String>): Map<String, String> {
        val jsonString = payload["json_string"] ?: return mapOf("error" to "missing 'json_string'")
        return try {
            // Use kotlinx.serialization to validate JSON
            kotlinx.serialization.json.Json.parseToJsonElement(jsonString)
            mapOf("valid" to "true")
        } catch (e: Exception) {
            mapOf("valid" to "false", "error" to (e.message ?: "invalid JSON"))
        }
    }

    private suspend fun executeShellExec(payload: Map<String, String>): Map<String, String> =
        withContext(Dispatchers.IO) {
            val command = payload["command"] ?: return@withContext mapOf("error" to "missing 'command'")

            // Security: deny dangerous patterns
            for (pattern in SHELL_DENY_PATTERNS) {
                if (pattern in command) {
                    return@withContext mapOf("error" to "DENIED: command contains '$pattern'")
                }
            }

            // Security: every pipe segment's head executable must be allowlisted.
            // Splits on "|" only for allowlist validation; the sh subshell
            // still evaluates the full command including the pipe semantics.
            val segments = command.split("|").map { it.trim() }.filter { it.isNotEmpty() }
            for (segment in segments) {
                val head = segment.split("\\s+".toRegex()).firstOrNull() ?: ""
                if (head !in SHELL_ALLOWLIST) {
                    return@withContext mapOf("error" to "DENIED: '$head' not in allowlist")
                }
            }

            // Resolve sh from the shell environment so the PATH includes binDir
            // (busybox symlinks). Falls back to /system/bin/sh which lacks the
            // utility applets but won't crash the executor.
            val shPath = shellEnv?.getBinaryPath("sh")?.takeIf { it.exists() }?.absolutePath
                ?: "/system/bin/sh"
            val env = shellEnv?.buildEnvironment() ?: emptyMap()
            try {
                val builder = ProcessBuilder(shPath, "-c", command)
                    .also { b ->
                        if (env.isNotEmpty()) {
                            b.environment().clear()
                            b.environment().putAll(env)
                        }
                    }
                val process = builder.start()
                val stdout = process.inputStream.bufferedReader().readText()
                val stderr = process.errorStream.bufferedReader().readText()
                val exitCode = process.waitFor()
                mapOf(
                    "exit_code" to exitCode.toString(),
                    "stdout" to stdout.take(4096),
                    "stderr" to stderr.take(1024),
                )
            } catch (e: Exception) {
                mapOf("error" to "exec failed: ${e.message}")
            }
        }

    private suspend fun executeFileRead(payload: Map<String, String>): Map<String, String> =
        withContext(Dispatchers.IO) {
            val path = payload["path"] ?: return@withContext mapOf("error" to "missing 'path'")
            val file = File(filesDir, path)

            // Security: path traversal check
            if (!file.canonicalPath.startsWith(filesDir.canonicalPath)) {
                return@withContext mapOf("error" to "DENIED: path traversal detected")
            }
            if (!file.exists()) {
                return@withContext mapOf("error" to "file not found: $path")
            }

            try {
                val content = file.readText(Charsets.UTF_8)
                mapOf(
                    "content" to content.take(8192),
                    "size" to file.length().toString(),
                )
            } catch (e: Exception) {
                mapOf("error" to "read failed: ${e.message}")
            }
        }

    private suspend fun executeFileHash(payload: Map<String, String>): Map<String, String> =
        withContext(Dispatchers.IO) {
            val path = payload["path"] ?: return@withContext mapOf("error" to "missing 'path'")
            val file = File(filesDir, path)

            // Security: path traversal check
            if (!file.canonicalPath.startsWith(filesDir.canonicalPath)) {
                return@withContext mapOf("error" to "DENIED: path traversal detected")
            }
            if (!file.exists()) {
                return@withContext mapOf("error" to "file not found: $path")
            }

            try {
                val digest = MessageDigest.getInstance("SHA-256")
                file.inputStream().use { input ->
                    val buffer = ByteArray(8192)
                    var read: Int
                    while (input.read(buffer).also { read = it } != -1) {
                        digest.update(buffer, 0, read)
                    }
                }
                val hash = digest.digest().joinToString("") { "%02x".format(it) }
                mapOf(
                    "sha256" to hash,
                    "size" to file.length().toString(),
                )
            } catch (e: Exception) {
                mapOf("error" to "hash failed: ${e.message}")
            }
        }
}
