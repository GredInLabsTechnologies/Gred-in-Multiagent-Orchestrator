package com.gredinlabs.gimomesh.data.api

import com.gredinlabs.gimomesh.data.model.CoreDiscovery
import com.gredinlabs.gimomesh.data.model.ModelInfo
import com.gredinlabs.gimomesh.data.model.OnboardResult
import com.gredinlabs.gimomesh.data.model.PendingCode
import com.gredinlabs.gimomesh.data.model.RedeemRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.TimeUnit

sealed interface OnboardingApiResult<out T> {
    data class Success<T>(val value: T) : OnboardingApiResult<T>
    data class Error(
        val message: String,
        val code: Int? = null,
    ) : OnboardingApiResult<Nothing>
}

@Serializable
private data class ErrorPayload(val detail: String = "")

/**
 * HTTP client for zero-ADB onboarding endpoints.
 * The setup wizard owns this path; authenticated runtime traffic stays in GimoCoreClient.
 */
class OnboardingClient(coreUrl: String) {

    private val baseUrl = coreUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }
    private val jsonMediaType = "application/json".toMediaType()

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    private val downloadClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES)
        .build()

    suspend fun discoverCore(): OnboardingApiResult<CoreDiscovery> = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$baseUrl/ops/mesh/onboard/discover")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext response.toError("Core discovery failed")
                val body = response.body?.string()
                    ?: return@withContext OnboardingApiResult.Error("Core discovery returned an empty response")
                val discovery = json.decodeFromString<CoreDiscovery>(body)
                if (!discovery.meshEnabled) {
                    return@withContext OnboardingApiResult.Error(
                        message = "Core is reachable, but mesh onboarding is disabled",
                        code = response.code,
                    )
                }
                OnboardingApiResult.Success(discovery)
            }
        } catch (e: Exception) {
            OnboardingApiResult.Error(e.message ?: "Unable to reach the Core")
        }
    }

    suspend fun redeemCode(
        code: String,
        deviceId: String,
        name: String,
        deviceMode: String = "inference",
        deviceClass: String = "smartphone",
    ): OnboardingApiResult<OnboardResult> = withContext(Dispatchers.IO) {
        try {
            val payload = json.encodeToString(
                RedeemRequest(
                    code = code,
                    deviceId = deviceId,
                    name = name,
                    deviceMode = deviceMode,
                    deviceClass = deviceClass,
                )
            )
            val request = Request.Builder()
                .url("$baseUrl/ops/mesh/onboard/redeem")
                .post(payload.toRequestBody(jsonMediaType))
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext response.toError("Code redemption failed")
                val body = response.body?.string()
                    ?: return@withContext OnboardingApiResult.Error("Onboarding response was empty")
                OnboardingApiResult.Success(json.decodeFromString<OnboardResult>(body))
            }
        } catch (e: Exception) {
            OnboardingApiResult.Error(e.message ?: "Failed to redeem onboarding code")
        }
    }

    /**
     * GET /ops/mesh/onboard/pending — fetch the most recent pending code.
     * Used for auto-enrollment: app opens → discovers Core → gets code → redeems → done.
     */
    suspend fun fetchPendingCode(): OnboardingApiResult<PendingCode> = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$baseUrl/ops/mesh/onboard/pending")
                .get()
                .build()
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext response.toError("No pending code")
                val body = response.body?.string()
                    ?: return@withContext OnboardingApiResult.Error("Empty response")
                OnboardingApiResult.Success(json.decodeFromString<PendingCode>(body))
            }
        } catch (e: Exception) {
            OnboardingApiResult.Error(e.message ?: "Failed to fetch pending code")
        }
    }

    suspend fun listModels(bearerToken: String, deviceId: String = ""): OnboardingApiResult<List<ModelInfo>> =
        withContext(Dispatchers.IO) {
            try {
                val url = if (deviceId.isNotBlank()) "$baseUrl/ops/mesh/models?device_id=$deviceId" else "$baseUrl/ops/mesh/models"
                val request = Request.Builder()
                    .url(url)
                    .header("Authorization", "Bearer $bearerToken")
                    .get()
                    .build()
                client.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) return@withContext response.toError("Model catalog request failed")
                    val body = response.body?.string()
                        ?: return@withContext OnboardingApiResult.Success(emptyList())
                    OnboardingApiResult.Success(json.decodeFromString<List<ModelInfo>>(body))
                }
            } catch (e: Exception) {
                OnboardingApiResult.Error(e.message ?: "Failed to load model catalog")
            }
        }

    suspend fun downloadModel(
        bearerToken: String,
        modelId: String,
        targetFile: File,
        onProgress: (downloaded: Long, total: Long) -> Unit = { _, _ -> },
    ): OnboardingApiResult<Unit> = withContext(Dispatchers.IO) {
        try {
            targetFile.parentFile?.mkdirs()

            var resumeOffset = if (targetFile.exists()) targetFile.length() else 0L

            val buildRequest: (Long) -> Request = { offset ->
                Request.Builder()
                    .url("$baseUrl/ops/mesh/models/$modelId/download")
                    .header("Authorization", "Bearer $bearerToken")
                    .apply { if (offset > 0L) header("Range", "bytes=$offset-") }
                    .get()
                    .build()
            }

            var response = downloadClient.newCall(buildRequest(resumeOffset)).execute()

            // 416 Range Not Satisfiable: stale partial on disk — wipe and restart from 0
            if (response.code == 416) {
                response.close()
                targetFile.delete()
                resumeOffset = 0L
                response = downloadClient.newCall(buildRequest(0L)).execute()
            }

            response.use { resp ->
                if (!resp.isSuccessful && resp.code != 206) {
                    return@withContext resp.toError("Model download failed")
                }

                val body = resp.body
                    ?: return@withContext OnboardingApiResult.Error("Model download returned no file data")
                val append = resumeOffset > 0L && resp.code == 206
                val contentLength = body.contentLength()
                val totalBytes = when {
                    resp.code == 206 -> resp.header("Content-Range")
                        ?.substringAfter("/")
                        ?.toLongOrNull()
                        ?: if (contentLength >= 0) resumeOffset + contentLength else -1L
                    contentLength >= 0 -> contentLength
                    else -> -1L
                }

                FileOutputStream(targetFile, append).use { output ->
                    body.byteStream().use { input ->
                        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                        var downloaded = if (append) resumeOffset else 0L
                        onProgress(downloaded, totalBytes)
                        while (true) {
                            val read = input.read(buffer)
                            if (read == -1) break
                            output.write(buffer, 0, read)
                            downloaded += read
                            onProgress(downloaded, totalBytes)
                        }
                        output.fd.sync()
                    }
                }
                OnboardingApiResult.Success(Unit)
            }
        } catch (e: Exception) {
            OnboardingApiResult.Error(e.message ?: "Model download interrupted")
        }
    }

    fun shutdown() {
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
        downloadClient.dispatcher.executorService.shutdown()
        downloadClient.connectionPool.evictAll()
    }

    private fun Response.toError(defaultMessage: String): OnboardingApiResult.Error {
        val detail = runCatching {
            body?.string()
                ?.takeIf { it.isNotBlank() }
                ?.let { json.decodeFromString<ErrorPayload>(it).detail }
        }.getOrNull().orEmpty()
        return OnboardingApiResult.Error(
            message = detail.ifBlank { "$defaultMessage (HTTP $code)" },
            code = code,
        )
    }
}
