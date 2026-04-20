# GIMO Mesh · Chaquopy Sprint — 2026-04-20

**Scope:** resolver G27 (server mode bloqueado por `python-build-standalone`
glibc-linked incompatible con Android bionic) migrando `EmbeddedCoreRunner`
a Chaquopy + endurecer persistencia post-reinstall (device identity, modelos
GGUF) usando patterns SOTA verificados.

**Commits (rango):** `caa3af3 → d69ce78` (9 commits consecutivos en `main`).

**Duración:** ~6 h de sesión continua con build verde en S10 real (Samsung
Galaxy S10, adb-TLS, Exynos 9820, Android 12).

---

## Resultado neto

- **G27 resuelto arquitecturalmente**: CPython 3.13 bionic-native ejecuta
 in-APK vía Chaquopy 17.0 (MIT, sin licencias comerciales — re-verificado
 contra `chaquo/chaquopy/LICENSE.txt`). `libpython3.13.so` arm64 + x86_64
 empaquetado, smoke test con `fastapi / starlette / uvicorn / anyio / click
 / typing_extensions` importando limpios en device.
- **`EmbeddedCoreRunner` reescrito** de `ProcessBuilder("python", "-m",
 "uvicorn")` a `Python.getInstance().getModule().callAttr(...)`. Zero
 subprocess. Daemon thread dentro de la JVM controlado por
 `ChaquopyBridge.startServer / stopServer / waitForServerShutdown`.
- **Persistencia post-reinstall**: enrollment (deviceId + bearer token +
 coreUrl + workspace) sobrevive `adb uninstall` via
 `EncryptedSharedPreferences` con master-key Keystore (TEE/StrongBox).
 Modelos GGUF migran a `externalMediaDirs` (patron SOTA WhatsApp/Pokemon
 GO) y `android:hasFragileUserData="true"` da al user checkbox nativo
 "Keep app data" al uninstall.
- **Retention opt-in**: WorkManager PeriodicWorkRequest alineado con survey
 SOTA (PocketPal AI / MLC LLM / ChatterUI / Ollama / LM Studio — ninguno
 auto-borra por defecto). Default 0 días (never), opciones 30/60/90.
- **Muro arquitectural descubierto**: el wheelhouse actual del rove pipeline
 produce `.so` glibc-linked, no bionic. Bloquea `pydantic_core` (pydantic 2.x)
 y cascada de deps C/Rust del Core real. Documentado como TODO en el
 repo upstream [rove](../../rove/TODO_ANDROID_BIONIC_WHEELHOUSE.md).

---

## CHANGELOG

### Fase A — Chaquopy infra (caa3af3, 8be111f, c5950da)

- `apps/android/gimomesh/build.gradle.kts` root: declara plugin
 `com.chaquo.python:17.0.0` (Maven Central).
- `apps/android/gimomesh/app/build.gradle.kts`:
 - Aplica plugin + `ndk.abiFilters = [arm64-v8a, x86_64]` (match jniLibs
 existentes + PEP 738 Tier 3 ABIs).
 - `chaquopy { defaultConfig { version = "3.13"; buildPython(...) } }`.
 - `resolveHostPython()` helper: detecta Microsoft Store Python vía
 PowerShell `Get-AppxPackage` + fallback a python.org classic install.
 Necesario porque los aliases `AppExecLink` en `%LOCALAPPDATA%` no pasan
 `File.exists()` del JVM (ACL quirk).
- `app/src/main/python/gimo_smoke.py`: import chain probe
 (fastapi + starlette + anyio + uvicorn + click + typing-extensions).
 Expone `smoke()` dict + `ping()` string.
- `service/ChaquopyBridge.kt`: singleton wrapper. `ensureStarted(ctx)`
 idempotente sobre `Python.isStarted()`. Thread-safe.
- `GimoMeshApp.onCreate`: eager Chaquopy bootstrap + smoke test logged
 a `TerminalBuffer` + logcat. try/catch defensivo.
- `proguard-rules.pro`: `-keep class com.chaquo.python.**`.

**Validación en device:**
```
I/ChaquopyBridge: chaquopy python runtime initialised
I/GimoMeshApp:    chaquopy ready — cpython 3.13.9 on aarch64 /
                  fastapi=0.125.0 starlette=0.50.0 uvicorn=0.44.0 anyio=?
```

### Fase D1 — Device identity via Android Keystore (4586653)

- `data/store/DeviceIdentityStore.kt`: wrapper sobre
 `EncryptedSharedPreferences` con `MasterKey(AES256_GCM)` hardware-backed
 cuando hay TEE/StrongBox. Fields: `deviceId`, `deviceSecret`, `coreUrl`,
 `workspaceId`, `workspaceName`, `localCoreToken`.
- `GimoMeshApp.recoverIdentityIfNeeded()`: si DataStore está empty pero
 Keystore tiene enrollment previo, hidrata el DataStore antes del primer
 render de UI. Resultado: post-reinstall el app abre directamente en
 Dashboard, sin wizard.
- `SetupWizardScreen`: double-write en el success del redeem — DataStore
 + Keystore.
- `NavGraph`: propaga `deviceIdentityStore` al wizard.

**Dep nueva:** `androidx.security:security-crypto:1.1.0-alpha06` (única
versión pública AGP 8.7 + compileSdk 35).

### Fase D2 — Model storage reinstall-safe + retention opt-in (cb27e3a, f301f4a)

**D2-a:**
- `data/store/ModelStorage.kt` (NEW): `resolveModelsDir(ctx)` →
 `externalMediaDirs[0]/models` con fallback a `filesDir/models`. Survive-
 reinstall por diseño Android. Sin permisos en API 30+.
- `migrateLegacyModels(ctx)`: one-shot move de `filesDir/models` →
 `externalMediaDirs`. Idempotente, safe on failure.
- `AndroidManifest.xml`: `android:hasFragileUserData="true"`. Uninstall
 desde Settings muestra checkbox "Keep app data" nativo.
- Callers actualizados: `ShellEnvironment.modelsDir`,
 `MeshAgentService.resolveModelFile`, `NavGraph.requiresOnboardingModel`,
 `SetupWizardScreen` download target.

**D2-b:**
- Dep nueva: `androidx.work:work-runtime-ktx:2.10.0`.
- `SettingsStore`: `modelRetentionDays: Int` (0/30/60/90) +
 `lastWorkspaceContactAt: Long`.
- `ModelRetentionWorker`: `CoroutineWorker` + 24h `PeriodicWorkRequest`
 con constraint `setRequiresStorageNotLow(true)`. Borra todos los `.gguf`
 si `elapsed(lastContact) > retentionDays`. Zero-contact guard (skip si
 nunca hubo heartbeat exitoso).
- `MeshAgentService.heartbeat`: tras `client.sendHeartbeat()` exitoso,
 `settingsStore.touchWorkspaceContact()`.
- `MeshViewModel`: `setModelRetentionDays(days)`, `deleteDownloadedModels()`,
 `deleteAllData()` (plumbing para Settings UI futura).

### Fase B — EmbeddedCoreRunner via Chaquopy (c1b878d)

- **`tools/gimo_server/chaquopy_entry.py`** (reemplazado en commit posterior
 con `gimo_server_entry.py` en el Android module). Owner del daemon thread
 con uvicorn dentro del JVM. `start_server / stop_server /
 wait_for_shutdown / is_running / runtime_probe`.
- `app/build.gradle.kts pip`: fastapi, starlette, uvicorn (plain, sin
 [standard] — uvloop/httptools no tienen wheels bionic), typing-extensions,
 h11, anyio, sniffio, idna, click, python-multipart.
 **Excluye** pydantic intencionalmente: pip con Chaquopy resolvería
 pydantic 1.x (pure Python) porque no hay pydantic_core bionic en su
 repo; cargarlo rompería el Core que asume pydantic 2.x.
- `EmbeddedCoreRunner.kt`: elimina `ProcessBuilder`, `serverProcess`,
 `startOutputPump`, `waitFor/destroy`. Nuevo `pythonStarted` flag +
 `ChaquopyBridge.startServer(args)` con map de `rove_*` paths + env.
 `stop()` llama `requestGracefulShutdown()` (POST /ops/shutdown) luego
 `ChaquopyBridge.stopServer()` + `waitForServerShutdown(5.0)`. El
 interpreter CPython se queda up (Chaquopy singleton per JVM); next
 `start()` spinea daemon thread nuevo.
- `ChaquopyBridge.kt`: `startServer / stopServer / waitForServerShutdown
 / runRuntimeProbe`.

**Validación parcial:** APK 128 MB (+8 MB sobre Fase A por fastapi/uvicorn
stack). Build verde en 25s.

### Fase C — Sync tools/gimo_server al Chaquopy bundle (e9bcb9c, d69ce78)

- `app/build.gradle.kts`: `syncGimoServerSources` Copy task que copia
 `${repoRoot}/tools/gimo_server/*.py` → `app/src/main/python/tools/gimo_server/`
 antes de `mergeDebugPythonSources`. Idempotente. Excluye
 `__pycache__` y `.pyc`.
- `app/src/main/python/tools/__init__.py`: package marker
 (1-line docstring, versionado en git).
- `app/src/main/python/.gitignore`: oculta el synced `tools/gimo_server/*`
 para no duplicar source-of-truth.
- `ShellEnvironment.prepareEmbeddedCoreRuntime`:
 - Auto-detección del wrapper dir dentro de `extracted/` (única top-level
 dir, sin hardcode del nombre bundle — agnóstico a producer rename).
 - Canonical tarball name `gimo-core-runtime.tar.xz` (el Gradle task
 renombra desde el producer-side name; `manifest.tarballName` queda
 obsoleto para el lookup).
 - `pythonBinary.exists()` ahora opcional (Chaquopy provee el Python).
 - `EmbeddedCoreRuntime.wheelhouseDir: File?` field nuevo.
- `gimo_server_entry.py`:
 - `_coerce_java_map(m)`: convierte LinkedHashMap proxied por Chaquopy
 a dict Python vía `keySet().toArray() + m.get(k)`. `m[k]` subscript
 no está mapeado.
 - `_unpack_wheelhouse(src, dest)`: extrae todos los `.whl` del bundle
 rove a `site-packages/` usando `zipfile`. Idempotente con marker.
 - `start_server`: sys.path layering con wheelhouse-unpacked primero;
 evict modulos cached (`pydantic`, `pydantic_core`, `fastapi`,
 `starlette`, `anyio`, `click`) tras unpack, para forzar re-import.
- `tools/gimo_server/main.py`: legacy `middlewares.py` rename →
 `core_middlewares.py` + switch a import normal (`from
 tools.gimo_server.core_middlewares import register_middlewares`).
 Elimina el uso de `importlib.util.spec_from_file_location` que chocaba
 con el Chaquopy AssetFinder cuando ambos `middlewares.py` +
 `middlewares/` coexistían en el filesystem extraído.
- `tools/gimo_server/config.py`: `_get_base_dir()` ahora honra
 `ORCH_BASE_DIR` env var antes del sentinel walk. Sin esto, en Android
 el fallback es `Path.cwd() == "/"` → OSError read-only al crear `/logs`.
- `EmbeddedCoreRunner.buildRuntimeEnvironment`: publica `ORCH_BASE_DIR`,
 `ORCH_REPO_ROOT`, `ORCH_DATA_DIR`, `ORCH_LOG_DIR` anclados a
 `filesDir/core_data/`.
- `app/build.gradle.kts pip`: +python-dotenv (tools/gimo_server/config.py
 lo usa).

### Instrumentación temporal (revert antes de ship)

- `MeshAgentService.kt`: `ACTION_TEST_SERVE` constant + onStartCommand
 branch que fuerza `hybridServe=true + deviceMode="server" + localCoreToken
 dummy` y dispara `startMesh()` para validación via `adb shell
 am start-foreground-service` sin pasar por UI.
- `AndroidManifest.xml`: `MeshAgentService android:exported="true"`
 (default sería `false` — expuesto temporalmente para que adb pueda
 invocar el ACTION_TEST_SERVE).
- `ShellEnvironment`: `android.util.Log.i("ShellEnv", …)` diagnostic
 traces.

---

## Estado al cierre del sprint

### Funcionando end-to-end en S10 real

| Check | Result |
|---|---|
| `libpython3.13.so` bionic carga en APK | ✅ |
| Chaquopy runtime init `Python.start(AndroidPlatform)` | ✅ |
| `from fastapi import FastAPI` funciona | ✅ |
| `from starlette import …` funciona | ✅ |
| `from uvicorn import …` funciona | ✅ |
| `from anyio, click, typing_extensions, python_dotenv import …` | ✅ |
| Deep link `gimo://enroll?code=X&host=IP&port=9325` enrolla | ✅ |
| `EncryptedSharedPreferences` device identity sobrevive `pm clear` | ✅ |
| `externalMediaDirs` model path resuelve | ✅ |
| `hasFragileUserData="true"` en manifest | ✅ |
| `EmbeddedCoreRunner.start()` sin ProcessBuilder | ✅ |
| `ChaquopyBridge.startServer(args)` invocado | ✅ |
| `_coerce_java_map` coerce Kotlin Map → Python dict | ✅ |
| `_unpack_wheelhouse` extrae .whl a site-packages | ✅ |
| `tools.gimo_server.main` empieza a importar | ✅ |
| `from tools.gimo_server.core_middlewares import register_middlewares` | ✅ |
| `ORCH_BASE_DIR` anclado a filesDir writable | ✅ |
| pydantic 2.x del rove wheelhouse resuelve sobre Chaquopy pydantic 1.x | ✅ |

### Bloqueado por el muro arquitectural

| Check | Result |
|---|---|
| `from pydantic_core import _pydantic_core` | ❌ `ModuleNotFoundError` |
| uvicorn binding `0.0.0.0:9325` | ❌ (tools.gimo_server.main no importa hasta el final) |
| `GET /health` → 200 | ❌ |

**Root cause:** todas las `.so` del rove wheelhouse son `cpython-313-
aarch64-linux-gnu.so` (glibc-linked). Python en Android busca por ABI
tag `android` y rechaza las glibc sin intentar dlopen.

Ver TODO upstream: `/c/Users/shilo/Documents/Github/rove/TODO_ANDROID_BIONIC_WHEELHOUSE.md`.

---

## Decisiones documentadas

1. **Chaquopy es MIT + gratis** (`chaquo/chaquopy@master LICENSE.txt`, re-
 verificado 2026-04-20 a petición del user). Ninguna licencia comercial.
2. **Rove NO se elimina**. Bundle sigue shipping el source tree del Core
 (pre-sync) y provee el paradigm de firma Ed25519 + distribución P2P que
 no cambia. Lo que falta es que produzca wheels bionic además de glibc.
3. **APK agnóstica al modelo del teléfono**: ningún hardcode de fabricante.
 El `wrapperDir` se resuelve por pattern "única subdir dentro de
 `extracted/`" en vez de prefix hardcodeado.
4. **Retention default: never**. SOTA survey no muestra auto-delete por
 defecto en PocketPal AI / MLC LLM / ChatterUI / Ollama / LM Studio.

---

## Artefactos producidos

### Código

- `apps/android/gimomesh/app/src/main/python/gimo_smoke.py` (smoke test)
- `apps/android/gimomesh/app/src/main/python/gimo_server_entry.py` (170 LOC
 — uvicorn daemon thread + wheelhouse unpack + Java Map coercion)
- `apps/android/gimomesh/app/src/main/python/tools/__init__.py` (package marker)
- `apps/android/gimomesh/app/src/main/java/…/service/ChaquopyBridge.kt`
- `apps/android/gimomesh/app/src/main/java/…/service/ModelRetentionWorker.kt`
- `apps/android/gimomesh/app/src/main/java/…/data/store/DeviceIdentityStore.kt`
- `apps/android/gimomesh/app/src/main/java/…/data/store/ModelStorage.kt`
- `apps/android/gimomesh/app/src/main/java/…/service/EmbeddedCoreRunner.kt`
 (rewrite completo)
- `tools/gimo_server/core_middlewares.py` (rename from `middlewares.py`)

### Docs / guardrails

- `docs/audits/GIMO_MESH_CHAQUOPY_SPRINT_2026-04-20.md` (este doc)
- `/c/Users/shilo/Documents/Github/rove/TODO_ANDROID_BIONIC_WHEELHOUSE.md`
 (TODO upstream)
- `apps/android/gimomesh/app/src/main/python/.gitignore` (dont-commit
 synced source)

### APK final

- `apps/android/gimomesh/app/build/outputs/apk/debug/app-debug.apk` — 131 MB
 - `lib/arm64-v8a/libpython3.13.so` (5.4 MB)
 - `lib/x86_64/libpython3.13.so` (5.3 MB)
 - `lib/arm64-v8a/libllama-server.so` (16 MB — intacto)
 - `lib/arm64-v8a/libbusybox.so` (2.7 MB — intacto)
 - `assets/chaquopy/bootstrap-native/{arm64-v8a,x86_64}/` — Python stdlib
 - `assets/chaquopy/app.imy` (2.6 MB — tools/gimo_server source + entry)
 - `assets/runtime/{arm64-v8a,x86_64}/gimo-core-runtime.tar.xz` (rove bundle,
 preserved hasta que el wheelhouse bionic exista)

---

## Próximos pasos recomendados

1. **[bloqueante para server mode real]** Esperar / impulsar el TODO
 upstream en rove: cross-compile `pydantic-core`, `cryptography`, `orjson`
 para android-aarch64. Estimado 1-2 días sprint dedicado. Ver
 `/c/Users/shilo/Documents/Github/rove/TODO_ANDROID_BIONIC_WHEELHOUSE.md`.

2. **[opcional / smoke alternative]** Crear `tools/gimo_server/minimal_app.py`
 con solo `FastAPI() + @app.get("/health")` y entrypoint Chaquopy que
 lo cargue (en vez de `tools.gimo_server.main`). Demuestra que la
 infraestructura Chaquopy → uvicorn → socket bind funciona end-to-end
 sin depender de pydantic_core.

3. **[pre-ship cleanup]** Revertir:
 - `MeshAgentService.ACTION_TEST_SERVE` + `android:exported="true"` en
 `AndroidManifest.xml` (volver a `false`).
 - Remover `Log.i`/`Log.e` diagnostic traces en `ShellEnvironment`,
 `EmbeddedCoreRunner` (o degradar a `DEBUG` level).

4. **[UI]** Settings screen que exponga los handlers
 `MeshViewModel.setModelRetentionDays / deleteDownloadedModels /
 deleteAllData` ya plumbed.

5. **[documentación continuada]** Una vez se tengan wheels bionic,
 actualizar `docs/MESH_SERVER_RUNBOOK.md` §2 (Android launcher) para
 reflejar el flow Chaquopy (ya no hay `EmbeddedCoreRunner` subprocess).

---

## Validación de hardware

- **Samsung Galaxy S10 SM-G973F** (Exynos 9820, arm64-v8a, Android 12)
 vía `adb-RF8M404ZYMN-Nj8AxI._adb-tls-connect._tcp`.
- Install / force-stop / pm clear ciclos estables a lo largo del sprint.
- Smoke test exitoso en todas las iteraciones post-hardening del resolver
 buildPython.
- Enrollment vía deep link completado, device aparece en
 `/ops/mesh/devices` con state=`approved` / device_mode=`hybrid`.
