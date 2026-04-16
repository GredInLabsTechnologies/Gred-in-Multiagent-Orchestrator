import org.gradle.api.tasks.Exec
import org.gradle.api.tasks.Copy
import java.net.URI

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
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
// Runtime Packaging — Plan E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING §7
// -----------------------------------------------------------------------------
//
// El Core GIMO se empaqueta como bundle Ed25519-firmado (tarball XZ + manifest
// JSON + .sig) dentro de src/main/assets/runtime/. La APK se mantiene liviana
// porque el Python host no se incluye en repo: el productor (scripts/
// package_core_runtime.py) lo genera en CI con python-build-standalone y
// lo deja en runtime-assets/ a la raíz del repo.
//
// Esta tarea copia ese bundle pre-construido a los assets de la APK. No
// reconstruye — si runtime-assets/ está vacío, falla con mensaje accionable.
val repoRoot: File = rootDir.parentFile.parentFile.parentFile  // apps/android/gimomesh -> repo root
val runtimeAssetsDir: File = file("${repoRoot}/runtime-assets")
val apkRuntimeDir: File = file("src/main/assets/runtime")

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
        val manifest = File(runtimeAssetsDir, "gimo-core-runtime.json")
        if (manifest.exists() && manifest.length() > 0) {
            logger.info("runtime-assets/ ya tiene manifest; skip fetch")
            return@doLast
        }
        runtimeAssetsDir.mkdirs()
        val suffixes = listOf("json", "tar.xz", "sig")
        suffixes.forEach { suffix ->
            val dest = File(runtimeAssetsDir, "gimo-core-runtime.$suffix")
            val url = URI.create("$baseUrl/gimo-core-runtime.$suffix").toURL()
            logger.lifecycle("fetching $url -> $dest")
            url.openStream().use { input ->
                dest.outputStream().use { output -> input.copyTo(output) }
            }
        }
    }
}

val packageCoreRuntime = tasks.register<Copy>("packageCoreRuntime") {
    description = "Copia el bundle GIMO Core (producido por scripts/package_core_runtime.py) a src/main/assets/runtime/."
    group = "gimo"
    dependsOn(fetchRuntimeBundle)

    // El gradle no invoca el productor por sí mismo — CI/operador lo debe correr
    // antes. Así separamos toolchain Python (CI matrix) del build Android.
    doFirst {
        val manifest = File(runtimeAssetsDir, "gimo-core-runtime.json")
        if (!manifest.exists()) {
            throw GradleException(
                "runtime-assets/gimo-core-runtime.json no existe.\n" +
                "Opciones para producirlo:\n" +
                "  (a) Local — cross-compile real:\n" +
                "      python scripts/package_core_runtime.py build \\\n" +
                "        --target android-arm64 --python-source standalone \\\n" +
                "        --compression xz --runtime-version <ver> \\\n" +
                "        --signing-key secrets/runtime-signing.pem \\\n" +
                "        --output runtime-assets/\n" +
                "  (b) CI — matrix runtime-packaging produce artifact\n" +
                "      gimo-core-runtime-android-arm64; descarga y extrae a\n" +
                "      runtime-assets/ (o set GIMO_RUNTIME_BUNDLE_URL)."
            )
        }
    }

    from(runtimeAssetsDir) {
        include("gimo-core-runtime.json")
        include("gimo-core-runtime.tar.xz")
        include("gimo-core-runtime.sig")
        // Plan CROSS_COMPILE §Change 5 — trusted pubkey del productor, usado
        // por runtime_bootstrap para validar firma antes de extraer.
        include("trusted-pubkey.pem")
    }
    into(apkRuntimeDir)
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
}
