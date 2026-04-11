package com.gredinlabs.gimomesh.data.api

import com.gredinlabs.gimomesh.data.model.HeartbeatPayload
import com.gredinlabs.gimomesh.data.model.MeshDevice
import com.gredinlabs.gimomesh.data.model.MeshTask
import com.gredinlabs.gimomesh.data.model.MeshWorkspace
import com.gredinlabs.gimomesh.data.model.PairingCodeResponse
import com.gredinlabs.gimomesh.data.model.TaskResultPayload
import com.gredinlabs.gimomesh.data.model.WorkspaceMembershipInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

/**
 * HTTP client for GIMO Core server.
 * All mesh endpoints under /ops/mesh/.
 */
class GimoCoreClient(
    private val baseUrl: String,
    private val token: String,
) {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }
    private val jsonMediaType = "application/json".toMediaType()

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    /**
     * POST /ops/mesh/heartbeat — send telemetry, receive device state.
     */
    suspend fun sendHeartbeat(payload: HeartbeatPayload): MeshDevice? =
        withContext(Dispatchers.IO) {
            val body = json.encodeToString(payload).toRequestBody(jsonMediaType)
            val request = Request.Builder()
                .url("$baseUrl/ops/mesh/heartbeat")
                .header("Authorization", "Bearer $token")
                .post(body)
                .build()

            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext null
                response.body?.string()?.let { responseBody ->
                    json.decodeFromString<MeshDevice>(responseBody)
                }
            }
        }

    /**
     * GET /ops/mesh/devices — list all mesh devices.
     */
    suspend fun getDevices(): List<MeshDevice> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/ops/mesh/devices")
            .header("Authorization", "Bearer $token")
            .get()
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return@withContext emptyList()
            response.body?.string()?.let { body ->
                json.decodeFromString<List<MeshDevice>>(body)
            } ?: emptyList()
        }
    }

    /**
     * GET /ops/mesh/status — fleet overview.
     */
    suspend fun getMeshStatus(): String? = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/ops/mesh/status")
            .header("Authorization", "Bearer $token")
            .get()
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return@withContext null
            response.body?.string()
        }
    }

    /**
     * GET /ops/mesh/tasks/poll/{deviceId} — poll assigned tasks.
     */
    suspend fun pollTasks(deviceId: String): List<MeshTask> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/ops/mesh/tasks/poll/$deviceId")
            .header("Authorization", "Bearer $token")
            .get()
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return@withContext emptyList()
            response.body?.string()?.let { body ->
                json.decodeFromString<List<MeshTask>>(body)
            } ?: emptyList()
        }
    }

    /**
     * POST /ops/mesh/tasks/{taskId}/result — submit task result.
     */
    suspend fun submitTaskResult(result: TaskResultPayload): Boolean =
        withContext(Dispatchers.IO) {
            val body = json.encodeToString(result).toRequestBody(jsonMediaType)
            val request = Request.Builder()
                .url("$baseUrl/ops/mesh/tasks/${result.taskId}/result")
                .header("Authorization", "Bearer $token")
                .post(body)
                .build()

            client.newCall(request).execute().use { response ->
                response.isSuccessful
            }
        }

    // ── Workspace API ─────────────────────────────────────────

    suspend fun listWorkspaces(): List<MeshWorkspace> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/ops/mesh/workspaces")
            .header("Authorization", "Bearer $token")
            .get()
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return@withContext emptyList()
            response.body?.string()?.let { body ->
                json.decodeFromString<List<MeshWorkspace>>(body)
            } ?: emptyList()
        }
    }

    suspend fun createWorkspace(name: String, ownerDeviceId: String = ""): MeshWorkspace? =
        withContext(Dispatchers.IO) {
            val payload = """{"name":"$name","owner_device_id":"$ownerDeviceId"}"""
            val body = payload.toRequestBody(jsonMediaType)
            val request = Request.Builder()
                .url("$baseUrl/ops/mesh/workspaces")
                .header("Authorization", "Bearer $token")
                .post(body)
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext null
                response.body?.string()?.let { json.decodeFromString<MeshWorkspace>(it) }
            }
        }

    suspend fun generatePairingCode(workspaceId: String): PairingCodeResponse? =
        withContext(Dispatchers.IO) {
            val body = "".toRequestBody(jsonMediaType)
            val request = Request.Builder()
                .url("$baseUrl/ops/mesh/workspaces/$workspaceId/pair")
                .header("Authorization", "Bearer $token")
                .post(body)
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext null
                response.body?.string()?.let { json.decodeFromString<PairingCodeResponse>(it) }
            }
        }

    suspend fun joinWorkspace(
        code: String,
        deviceId: String,
        deviceMode: String = "inference",
    ): WorkspaceMembershipInfo? = withContext(Dispatchers.IO) {
        val payload = """{"code":"$code","device_id":"$deviceId","device_mode":"$deviceMode"}"""
        val body = payload.toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url("$baseUrl/ops/mesh/workspaces/join")
            .header("Authorization", "Bearer $token")
            .post(body)
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return@withContext null
            response.body?.string()?.let { json.decodeFromString<WorkspaceMembershipInfo>(it) }
        }
    }

    suspend fun activateWorkspace(deviceId: String, workspaceId: String): Boolean =
        withContext(Dispatchers.IO) {
            val payload = """{"device_id":"$deviceId","workspace_id":"$workspaceId"}"""
            val body = payload.toRequestBody(jsonMediaType)
            val request = Request.Builder()
                .url("$baseUrl/ops/mesh/workspaces/activate")
                .header("Authorization", "Bearer $token")
                .post(body)
                .build()
            client.newCall(request).execute().use { it.isSuccessful }
        }

    suspend fun getDeviceWorkspaces(deviceId: String): List<WorkspaceMembershipInfo> =
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url("$baseUrl/ops/mesh/workspaces/device/$deviceId")
                .header("Authorization", "Bearer $token")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext emptyList()
                response.body?.string()?.let { body ->
                    json.decodeFromString<List<WorkspaceMembershipInfo>>(body)
                } ?: emptyList()
            }
        }

    fun shutdown() {
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
    }
}
