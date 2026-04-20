package com.gredinlabs.gimomesh.data.store

import android.content.Context
import android.util.Log
import java.io.File

/**
 * Single source of truth for where downloaded GGUF model files live on disk.
 *
 * Storage choice (Fase D2 — SOTA alignment):
 *   - **Preferred**: [Context.getExternalMediaDirs] first entry. This maps
 *     to `/sdcard/Android/media/<pkg>/`. It does NOT require any runtime
 *     permission on API 30+ and, crucially, it **survives app uninstall**
 *     (unlike `externalFilesDir` or `filesDir`, which Android wipes with the
 *     app UID on uninstall).
 *   - **Fallback**: [Context.getFilesDir]. Used only when external media is
 *     unavailable (emulator without SD, /storage emulation in a weird state).
 *
 * Why externalMediaDirs: it is the standard Android pattern for
 * multi-GB content that benefits from surviving reinstall — WhatsApp uses
 * it for media backups, game launchers use it for downloadable assets,
 * Pokémon GO for map tiles. The pattern is documented in the official
 * Android storage use-cases guide.
 *
 * Uninstall: combined with `android:hasFragileUserData="true"` in the
 * AndroidManifest, the user gets a checkbox during uninstall to decide
 * whether to retain the models or let Android wipe them along with the
 * app data — honest UX that doesn't orphan 3 GB on devices by default.
 */
object ModelStorage {

    private const val TAG = "ModelStorage"
    private const val MODELS_SUBDIR = "models"

    /**
     * Returns the preferred models directory, creating it if it doesn't
     * exist. Falls back to `context.filesDir/models` if external media is
     * unavailable. Safe to call from any thread.
     */
    fun resolveModelsDir(context: Context): File {
        val external = context.externalMediaDirs.firstOrNull { it != null }
        val base = external ?: context.filesDir
        val dir = File(base, MODELS_SUBDIR)
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    /** Legacy path — where Fase A–D1 stored models. Used only by the migrator. */
    fun legacyModelsDir(context: Context): File = File(context.filesDir, MODELS_SUBDIR)

    /**
     * Resolves the expected path of a downloaded model by filename, under the
     * preferred storage root. Matches the naming convention used by the
     * wizard and service: `<filename>` (keep as-is) or
     * `<modelId-with-colons-replaced-by-underscores>.gguf`.
     */
    fun resolveModelFile(context: Context, filename: String): File =
        File(resolveModelsDir(context), filename)

    /**
     * Backward-compatible resolver for callers that have a DataStore `model`
     * string (e.g. `qwen2.5:3b`). Preserves the existing colon-to-underscore
     * convention and appends `.gguf`.
     */
    fun resolveModelFileForId(context: Context, modelId: String): File {
        val fname = "${modelId.replace(":", "_")}.gguf"
        return resolveModelFile(context, fname)
    }

    /**
     * One-shot migration of any pre-D2 `.gguf` files from `filesDir/models/`
     * to the external media dir. Called at app boot. Idempotent — once the
     * legacy dir is empty (or doesn't exist) the migration is a no-op.
     *
     * On failure (out-of-space, permission denied, symlink weirdness) the
     * legacy file is left in place so the inference runner can still find it
     * via the fallback lookup — no data loss.
     *
     * Returns the number of files successfully migrated.
     */
    fun migrateLegacyModels(context: Context): Int {
        val legacy = legacyModelsDir(context)
        if (!legacy.exists()) return 0
        val files = legacy.listFiles()?.filter { it.isFile } ?: emptyList()
        if (files.isEmpty()) {
            // Empty dir left over from a prior install — remove it so we
            // don't keep reporting "legacy present" on every boot.
            legacy.delete()
            return 0
        }

        val target = resolveModelsDir(context)
        if (target.canonicalPath == legacy.canonicalPath) {
            // External media unavailable; fallback resolver returned the
            // legacy path. Nothing to migrate.
            return 0
        }

        var moved = 0
        for (file in files) {
            val dest = File(target, file.name)
            if (dest.exists() && dest.length() == file.length()) {
                // Already migrated (maybe partially completed previously).
                file.delete()
                continue
            }
            try {
                file.copyTo(dest, overwrite = true)
                file.delete()
                moved += 1
                Log.i(TAG, "migrated ${file.name} (${file.length() / 1024 / 1024} MiB) to external media")
            } catch (t: Throwable) {
                Log.w(TAG, "migration failed for ${file.name}: ${t.message}")
                // Leave the legacy copy in place; inference runner will
                // look there as a fallback.
            }
        }

        // If we fully drained the legacy dir, remove it.
        if (legacy.listFiles()?.isEmpty() == true) {
            legacy.delete()
        }
        return moved
    }

    /**
     * Looks up a model file by its DataStore id with fallback to the legacy
     * location. Preferred path wins when both exist. Use this when you have
     * the `settings.model` string and need a concrete File.
     */
    fun findModelFileForId(context: Context, modelId: String): File? {
        val preferred = resolveModelFileForId(context, modelId)
        if (preferred.exists() && preferred.length() > 0) return preferred
        val legacy = File(legacyModelsDir(context), "${modelId.replace(":", "_")}.gguf")
        if (legacy.exists() && legacy.length() > 0) return legacy
        return null
    }

    /** Total bytes used by all models in the preferred dir. O(n) scan. */
    fun totalBytes(context: Context): Long =
        resolveModelsDir(context).listFiles().orEmpty().sumOf { it.length() }

    /**
     * Deletes every file under the preferred models dir. Used by the
     * Settings → Delete downloaded models button and by the opt-in
     * retention worker. Returns the number of files deleted.
     */
    fun deleteAllModels(context: Context): Int {
        val dir = resolveModelsDir(context)
        var deleted = 0
        dir.listFiles()?.forEach { file ->
            if (file.isFile && file.delete()) deleted += 1
        }
        return deleted
    }
}
