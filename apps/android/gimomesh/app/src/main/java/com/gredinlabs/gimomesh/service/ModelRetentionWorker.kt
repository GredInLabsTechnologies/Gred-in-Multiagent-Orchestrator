package com.gredinlabs.gimomesh.service

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.gredinlabs.gimomesh.GimoMeshApp
import com.gredinlabs.gimomesh.data.model.LogLevel
import com.gredinlabs.gimomesh.data.model.LogSource
import com.gredinlabs.gimomesh.data.store.ModelStorage
import com.gredinlabs.gimomesh.data.store.SettingsStore
import kotlinx.coroutines.flow.first
import java.util.concurrent.TimeUnit

/**
 * Opt-in periodic housekeeping for downloaded GGUF models (Fase D2-b).
 *
 * SOTA survey result (PocketPal AI, MLC LLM, ChatterUI, Ollama, LM Studio):
 * **nobody auto-deletes by default**. Auto-delete is perceived as
 * paternalistic — the user opens the app one day and their models are gone.
 * So this worker **runs only when the user explicitly chose a retention
 * window in Settings** (`modelRetentionDays` ∈ {30, 60, 90}). Default is
 * 0 = never delete, and the worker is not enrolled.
 *
 * Policy (runs every 24 h once enabled):
 *   - Read `modelRetentionDays` and `lastWorkspaceContactAt` from DataStore.
 *   - If `retentionDays == 0` → [Result.success] (no-op; keeps WorkManager
 *     book-keeping tidy even if scheduler raced the opt-out).
 *   - If `now - lastContact < retentionDays` → [Result.success] (still
 *     active).
 *   - Else → [ModelStorage.deleteAllModels]. Log to terminalBuffer for
 *     audit trail.
 *
 * Constraints: [Constraints.Builder.setRequiresStorageNotLow] — we don't
 * want the worker to run right when the device is already tight on space
 * (wasted CPU on a retry).
 */
class ModelRetentionWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val ctx = applicationContext
        val app = ctx as? GimoMeshApp
        val settings = (app?.settingsStore ?: SettingsStore(ctx)).settings.first()
        val retentionDays = settings.modelRetentionDays
        if (retentionDays <= 0) {
            // User disabled / never opted in. Self-cancel so WorkManager
            // stops waking us up until the user opts in again.
            WorkManager.getInstance(ctx).cancelUniqueWork(UNIQUE_NAME)
            return Result.success()
        }

        val retentionMillis = TimeUnit.DAYS.toMillis(retentionDays.toLong())
        val lastContact = settings.lastWorkspaceContactAt
        if (lastContact == 0L) {
            // Never contacted the workspace since opt-in. Don't delete yet
            // — avoid a false-positive on a user who just enrolled and is
            // waiting for their first heartbeat to succeed.
            Log.i(TAG, "retention worker: no contact recorded yet, skipping")
            return Result.success()
        }

        val now = System.currentTimeMillis()
        val elapsed = now - lastContact
        if (elapsed < retentionMillis) {
            Log.i(TAG, "retention worker: active (${elapsed / 1000 / 60} min since contact)")
            return Result.success()
        }

        // Elapsed > threshold → delete.
        val deleted = ModelStorage.deleteAllModels(ctx)
        val freedMb = runCatching { ModelStorage.totalBytes(ctx) / 1024 / 1024 }.getOrNull()
        val summary = "model retention: deleted $deleted file(s) after " +
            "$retentionDays d inactivity (freed ~$freedMb MiB)"
        Log.i(TAG, summary)
        app?.terminalBuffer?.append(LogSource.SYS, summary, LogLevel.WARN)
        return Result.success()
    }

    companion object {
        private const val TAG = "ModelRetentionWorker"
        private const val UNIQUE_NAME = "gimo.mesh.model_retention"

        /**
         * Enrols or cancels the worker based on [retentionDays]. Idempotent:
         * when retentionDays==0 cancels any enrolled schedule; otherwise
         * replaces any existing schedule with a 24 h PeriodicWorkRequest.
         *
         * Call after the user changes the retention setting, and also on
         * app boot so a reinstall of the APK re-enrols the schedule if the
         * user had opted in pre-reinstall.
         */
        fun applySchedule(context: Context, retentionDays: Int) {
            val wm = WorkManager.getInstance(context)
            if (retentionDays <= 0) {
                wm.cancelUniqueWork(UNIQUE_NAME)
                return
            }
            val constraints = Constraints.Builder()
                .setRequiresStorageNotLow(true)
                .build()
            val request = PeriodicWorkRequestBuilder<ModelRetentionWorker>(
                repeatInterval = 24,
                repeatIntervalTimeUnit = TimeUnit.HOURS,
            )
                .setConstraints(constraints)
                .setInitialDelay(6, TimeUnit.HOURS)
                .build()
            wm.enqueueUniquePeriodicWork(
                UNIQUE_NAME,
                ExistingPeriodicWorkPolicy.UPDATE,
                request,
            )
        }
    }
}
