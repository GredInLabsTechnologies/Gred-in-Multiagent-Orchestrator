import org.gradle.api.tasks.Exec
import org.gradle.api.tasks.Copy
import java.net.URI

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
    // Chaquopy embedded CPython — only needed for Server Node role.
    // Inference + Utility Nodes don't execute Python on-device.
    id("com.chaquo.python")
}

android {
    namespace = "com.gredinlabs.gimomesh"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.gredinlabs.gimomesh"
        minSdk = 28
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"

        // Chaquopy requires explicit ABI filters. We support the same two ABIs
        // the llama-server binary already ships for (jniLibs/arm64-v8a/ and
        // jniLibs/x86_64/). armeabi-v7a intentionally excluded — Chaquopy 17
        // supports it but Python-Android-Tier-3 (PEP 738) is arm64+x86_64 only.
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
        // El tarball ya es XZ — que aapt no lo re-comprima.
        resources {
            excludes += setOf()
        }
    }

    // Plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING §Change 7 — no comprimir XZ.
    androidResources {
        noCompress += listOf("xz", "tar")
    }
}

// -----------------------------------------------------------------------------
// Chaquopy — embedded CPython bionic-compatible (Fase A, smoke test only)
// -----------------------------------------------------------------------------
//
// Fase A scope: plugin wire-up + Python 3.13 pick + 1 trivial pip dep (six)
// to validate the Chaquopy build toolchain produces a working APK. Real
// runtime deps (fastapi, uvicorn, pydantic, ...) land in Fase B when we
// rewrite EmbeddedCoreRunner to call Chaquopy's Python.getInstance() API
// instead of ProcessBuilder("python", "-m", "uvicorn", ...).
//
// Python 3.13 aligns with PEP 738 official Android Tier 3 support (arm64-v8a
// + x86_64). Chaquopy 17.0 builds CPython 3.13 with Android's NDK toolchain
// and ships bionic-compatible libpython3.13.so to Maven Central — no glibc
// issue (G27 resolved).
//
// Docs: https://chaquo.com/chaquopy/doc/current/android.html
chaquopy {
    defaultConfig {
        version = "3.13"
        pip {
            // Smoke test only — validates pip resolution + bionic wheel install.
            // Fase B replaces this with the real GIMO Core requirements subset.
            install("six")
        }
        // Extract all installed packages at startup so importlib sees them as
        // regular file-system modules (required for packages that introspect
        // __file__ / __path__ — e.g. pydantic plugins, uvicorn workers).
        extractPackages.add("*")
    }
}

// -----------------------------------------------------------------------------
// Runtime Packaging — Rev 2 multi-ABI (post-rove 2026-04-18)
// -----------------------------------------------------------------------------
//
// La APK agnóstica por ABI empaqueta un wheelhouse rove por cada arch Android
// soportada (arm64-v8a, x86_64, armeabi-v7a). En runtime, ShellEnvironment
// lee `Build.SUPPORTED_ABIS[0]` y extrae el bundle correspondiente.
//
// Productor upstream: rove build (via scripts/build_rove_wheelhouse.py) emite
// a `dist/gimo-core-android-<arch>-<version>.tar.xz` + `.manifest.json`.
// El gradle los copia a `src/main/assets/runtime/<android_abi>/` donde
// `<android_abi>` es el nombre NDK (arm64-v8a, x86_64, armeabi-v7a).
//
// Mapping rove-target → Android ABI:
//   android-arm64  → arm64-v8a
//   android-x86_64 → x86_64
//   android-armv7  → armeabi-v7a
val repoRoot: File = rootDir.parentFile.parentFile.parentFile  // apps/android/gimomesh -> repo root
val roveDistDir: File = file("${repoRoot}/dist")
val apkRuntimeDir: File = file("src/main/assets/runtime")
val abiMap: Map<String, String> = mapOf(
    "android-arm64"  to "arm64-v8a",
    "android-x86_64" to "x86_64",
    "android-armv7"  to "armeabi-v7a",
)
// Legacy runtime-assets/ (pre-rove, single-ABI) — conservado para fallback.
val legacyRuntimeAssetsDir: File = file("${repoRoot}/runtime-assets")

// Plan CROSS_COMPILE §Change 4 — Download del bundle desde release asset de CI.
// Si runtime-assets/ está vacío y el env var GIMO_RUNTIME_BUNDLE_URL está set,
// esta tarea baja los 3 artefactos del artifact URL (base sin extension — la
// tarea añade ".json", ".tar.xz", ".sig"). Ejemplo:
//   GIMO_RUNTIME_BUNDLE_URL=https://github.com/.../actions/runs/NNN/artifacts/gimo-core-runtime-android-arm64
// En local sin URL set, si runtime-assets/ ya tiene bundle, skipea. Si está
// vacío sin URL, el :app:packageCoreRuntime subsecuente falla con mensaje
// operator-ergonomic — no se pierde la safety net.
val fetchRuntimeBundle = tasks.register("fetchRuntimeBundle") {
    description = "Descarga el bundle GIMO Core desde CI artifact (si GIMO_RUNTIME_BUNDLE_URL está set)."
    group = "gimo"
    doLast {
        val baseUrl = System.getenv("GIMO_RUNTIME_BUNDLE_URL")
        if (baseUrl.isNullOrBlank()) {
            logger.info("GIMO_RUNTIME_BUNDLE_URL no set — skipping fetch (usa productor local)")
            return@doLast
        }
        val manifest = File(legacyRuntimeAssetsDir, "gimo-core-runtime.json")
        if (manifest.exists() && manifest.length() > 0) {
            logger.info("runtime-assets/ ya tiene manifest; skip fetch")
            return@doLast
        }
        legacyRuntimeAssetsDir.mkdirs()
        val suffixes = listOf("json", "tar.xz", "sig")
        suffixes.forEach { suffix ->
            val dest = File(legacyRuntimeAssetsDir, "gimo-core-runtime.$suffix")
            val url = URI.create("$baseUrl/gimo-core-runtime.$suffix").toURL()
            logger.lifecycle("fetching $url -> $dest")
            url.openStream().use { input ->
                dest.outputStream().use { output -> input.copyTo(output) }
            }
        }
    }
}

val packageCoreRuntime = tasks.register("packageCoreRuntime") {
    description = "Copia los wheelhouses rove (uno por ABI Android) a src/main/assets/runtime/<abi>/."
    group = "gimo"
    dependsOn(fetchRuntimeBundle)

    doFirst {
        // 1. Descubrir qué targets rove tienen bundle en dist/
        if (!roveDistDir.exists()) {
            throw GradleException(
                "dist/ no existe. Producir wheelhouses rove antes del build:\n" +
                "  python scripts/build_rove_wheelhouse.py --target android-arm64\n" +
                "  python scripts/build_rove_wheelhouse.py --target android-x86_64\n" +
                "  python scripts/build_rove_wheelhouse.py --target android-armv7  # opcional\n" +
                "La APK agnostica por ABI requiere al menos arm64 + x86_64 para cubrir\n" +
                "hardware real (S10, Pixel, etc.) + emuladores Google Play."
            )
        }
        val found = mutableListOf<String>()
        apkRuntimeDir.deleteRecursively()
        apkRuntimeDir.mkdirs()

        for ((roveTarget, androidAbi) in abiMap) {
            val bundleFile = roveDistDir.listFiles()
                ?.firstOrNull { it.name.startsWith("gimo-core-$roveTarget-") && it.name.endsWith(".tar.xz") }
            if (bundleFile == null) {
                logger.lifecycle("  skip $roveTarget (no bundle in dist/)")
                continue
            }
            val manifestFile = File(roveDistDir, "${bundleFile.name}.manifest.json")
            if (!manifestFile.exists()) {
                throw GradleException(
                    "Bundle ${bundleFile.name} no tiene manifest firmado adjacent " +
                    "(${manifestFile.name}). Regenerar con build_rove_wheelhouse.py."
                )
            }
            val targetDir = File(apkRuntimeDir, androidAbi)
            targetDir.mkdirs()
            bundleFile.copyTo(File(targetDir, "gimo-core-runtime.tar.xz"), overwrite = true)
            manifestFile.copyTo(File(targetDir, "gimo-core-runtime.manifest.json"), overwrite = true)
            logger.lifecycle("  $roveTarget → assets/runtime/$androidAbi/ (${bundleFile.length() / 1024 / 1024} MiB)")
            found.add(androidAbi)
        }

        if (found.isEmpty()) {
            throw GradleException(
                "No rove bundles found in dist/ for any Android ABI " +
                "(${abiMap.keys.joinToString(", ")}). Produce them with " +
                "scripts/build_rove_wheelhouse.py --target <android-*>."
            )
        }

        // 2. Trusted pubkey (una sola, compartida por todos los targets — la
        //    firma es por-bundle pero usa la misma keypair del productor).
        val trustedPubkey = File(legacyRuntimeAssetsDir, "trusted-pubkey.pem")
        if (trustedPubkey.exists()) {
            trustedPubkey.copyTo(File(apkRuntimeDir, "trusted-pubkey.pem"), overwrite = true)
        } else {
            logger.warn("trusted-pubkey.pem no encontrado en runtime-assets/; el " +
                       "verificador in-device caerá al EMBEDDED_RUNTIME_PUBLIC_KEY del código.")
        }

        logger.lifecycle("runtime assets packaged for ABIs: ${found.joinToString(", ")}")
    }
}

// Wire antes de mergeAssets — todas las variantes (Debug/Release).
// `afterEvaluate` porque las tareas de merge las registra el plugin Android
// recién al final de la configuración.
afterEvaluate {
    listOf("mergeDebugAssets", "mergeReleaseAssets").forEach { taskName ->
        tasks.findByName(taskName)?.dependsOn(packageCoreRuntime)
    }
}

dependencies {
    // Compose BOM
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")

    // Activity
    implementation("androidx.activity:activity-compose:1.9.3")

    // Navigation
    implementation("androidx.navigation:navigation-compose:2.8.5")

    // Networking
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")

    // DataStore
    implementation("androidx.datastore:datastore-preferences:1.1.1")

    // QR Scanning (ML Kit + CameraX)
    implementation("com.google.mlkit:barcode-scanning:17.3.0")
    implementation("androidx.camera:camera-camera2:1.4.1")
    implementation("androidx.camera:camera-lifecycle:1.4.1")
    implementation("androidx.camera:camera-view:1.4.1")

    // Lifecycle
    implementation("androidx.lifecycle:lifecycle-service:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")

    // Core
    implementation("androidx.core:core-ktx:1.15.0")

    // Device identity persistence — EncryptedSharedPreferences with Keystore-
    // backed master key. The master key lives in Android's TEE/StrongBox and
    // survives APK reinstall on modern devices, so the cached device_secret /
    // device_id / coreUrl are recovered on first boot post-reinstall without
    // the user having to re-run the enrollment wizard.
    implementation("androidx.security:security-crypto:1.1.0-alpha06")

    // WorkManager — drives the opt-in model retention housekeeping worker
    // (Fase D2-b). PeriodicWorkRequest with 24 h interval + storage-low
    // constraint. Default is "never delete" — the user opts in from Settings.
    implementation("androidx.work:work-runtime-ktx:2.10.0")

    // Server mode: embedded Core runtime bundle extraction
    // - apache commons-compress gives us tar readers (tar.xz layer is streamed
    //   on top of the XZ decoder from tukaani). Both are small pure-Java libs.
    implementation("org.apache.commons:commons-compress:1.26.2")
    implementation("org.tukaani:xz:1.9")
}
