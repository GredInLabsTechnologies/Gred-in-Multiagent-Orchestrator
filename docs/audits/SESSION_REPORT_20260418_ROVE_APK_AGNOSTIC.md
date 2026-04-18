# Session Report — Rove migration + APK agnóstico multi-ABI

**Fecha de sesión**: 2026-04-18 → 2026-04-19
**Rama**: `feature/gimo-mesh`
**HEAD**: `c87ad86`
**Commits añadidos**: 9

---

## 1. Objetivo inicial

Cerrar la migración a `rove-toolkit` como wheelhouse forge canónico y
conseguir que el APK de GIMO Mesh sea **agnóstico al ABI del device**
(arm64, x86_64, armv7), no específico al S10 del usuario.

Estado previo (commit `ed12fc9`, 2026-04-17):
- Rove vendorizado como wheel, shim en `models/runtime.py` y
  `security/runtime_signature.py` pero sin usar el wheelhouse forge real.
- APK empaquetaba un solo bundle `android-arm64` hardcoded → cualquier
  Android que no fuera arm64 fallaba silentemente al extraer runtime.
- Termux bootstrap con `pip install` genérico compilando 20+ min por
  grpcio + pydantic-core desde sdist.
- `EMBEDDED_RUNTIME_PUBLIC_KEY` desincronizada de `secrets/runtime-signing.pem`
  → toda verificación local fallaba `False` silencioso.

---

## 2. Commits de esta sesión (en orden de landing)

| Hash | Scope | Notas |
|---|---|---|
| `e2bfbb3` | Vendor rove-toolkit 1.0.0 + migrate schema/signing | Shim `models/runtime.py` + `security/runtime_signature.py` → re-export desde `rove.manifest` y `rove.signing.ed25519`. Rename `repo_root_rel_path` → `project_root_rel_path` en el schema. |
| `627fa80` | Termux bootstrap: integra rove-toolkit | Añade smoke-test `import rove.manifest, rove.signing.ed25519` post pip install. Fail-fast si el wheel no llegó. |
| `d6ea434` | Android Kotlin: migra EmbeddedCoreRuntimeManifest al schema rove | `@SerialName("repo_root_rel_path")` → `@SerialName("project_root_rel_path")`, propiedad `repoRootRelPath` → `projectRootRelPath`. |
| `2d5d5be` | Vendor rove-patches + integra patch registry en cross-compile | 3 patches (psutil, maturin, cryptography) aplicados por `scripts/package_core_runtime.py._apply_rove_patches`. Tests nuevos en `test_runtime_cross_compile.py`. |
| `9fcde9f` | Docs: DEV_MESH_ARCHITECTURE Rev 1 | Sección 2.4 actualizada con schema rove + wire-protocol de la firma 4-tupla + patch registry. |
| `cea6715` | Fix: sincroniza EMBEDDED_RUNTIME_PUBLIC_KEY con keypair activa | Bug pre-existente detectado en smoke-test: embedded pubkey (`Rb7…`) era de keypair antiguo sin private key; la activa es `OMPy…` que matchea `secrets/runtime-signing.pem`. |
| `e09eb52` | Android i18n: ModelCard strings a EN + ES | Extrae `rec_badge_recommended`, `rec_device_load`, `rec_stat_{speed,battery,mode}`, `rec_run_at_your_own_risk`, `rec_fit_{optimal,comfortable,tight,overload}` a `res/values/strings.xml` + `res/values-es/strings.xml`. |
| `2535004` | Termux bootstrap: export ANDROID_API_LEVEL=24 | Detectado en S10: pip falla compilando pydantic-core sin este env. Mismo valor que rove-patches upstream. |
| `c87ad86` | APK agnóstico por ABI + rove 1.0.1 multi-target wheelhouse forge | Commit grande. Detallado abajo. |

---

## 3. Último commit en detalle (`c87ad86`)

### Rove 1.0.1 — target `android-x86_64` (patch local, no pushed)

Fuente en `/tmp/rove-src` branch `gimo-feedback/v1.0.1-android-x86_64`
commit `635d58c`. Cambios:

- `src/rove/targets.py`: nuevo `Target.android_x86_64 = "android-x86_64"`
  + aliases (`android_x64`, `android_amd64`).
- `src/rove/builder/zig.py`: entry en `_CARGO_TARGETS`
  (`x86_64-linux-android`), `_zig_target_triple` devuelve
  `x86_64-linux-android.<api>`, incluido en set `ANDROID_API_LEVEL` env.
- `src/rove/builder/python_standalone.py`: añadido a `_ANDROID_TARGETS`
  frozenset.
- `pyproject.toml`: version `1.0.0` → `1.0.1`.
- `TODO_GIMO_FRICTIONS.md`: nuevo, 13 items priorizados P0/P1/P2 para
  trabajo upstream.

Build wheel local + re-vendorizado:
- `vendor/rove/rove_toolkit-1.0.1-py3-none-any.whl` (67 KiB)
- `vendor/rove/rove_toolkit-1.0.1.tar.gz` (134 KiB, sdist)

### Productor GIMO — `scripts/build_rove_wheelhouse.py`

Wrapper que llama `rove.builder` directamente (el CLI oficial no pasa
`--platform`, fricción P0 documentada). Hace:

1. Carga `rove.toml` + `requirements-locked.txt`.
2. Resuelve target (`parse_target` → `Target`).
3. Aplica rove-patches (env `ANDROID_API_LEVEL=24`, toml overrides).
4. Setup cross-compile env via Zig 0.14.1 en PATH.
5. Pip download con `--platform manylinux2014_<arch>` + `--only-binary=:all:`.
6. Empaqueta con `rove.builder.tarball.build_tarball`.
7. Firma con `rove.signing.ed25519.sign_manifest` (clave en
   `secrets/runtime-signing.pem`).

### `rove.toml` canónico

Nuevo archivo con `project_name="gimo-core"`, `version="0.2.0-rove"`,
`include/exclude` del subset del repo Core, `targets=[android-arm64,
android-armv7, android-x86_64, linux-x86_64, ...]`, patches
`["vendor/rove-patches"]`, sign_key con env expansion, requirements
inline.

### `requirements-locked.txt` — versiones pinneadas

Resuelve el pip `resolution-too-deep` al pasar multi-`--platform` tags.
Snapshot del venv dev con 27 pkgs. MCP deps (fastmcp/mcp/sse-starlette)
omitidos por conflicts con pydantic/fastapi pinned — no requeridos para
mesh server mode.

### OpenTelemetry: grpc → http exporter

`requirements.txt`: `opentelemetry-exporter-otlp==1.27.0` →
`opentelemetry-exporter-otlp-proto-http==1.27.0`.
`observability_service.py:21`: `from opentelemetry.exporter.otlp.proto.grpc.trace_exporter`
→ `...proto.http.trace_exporter`. Dropea grpcio transitive (~20 min
compile en Android ARM). Wire protocol semánticamente equivalente; el
endpoint debe apuntar a puerto HTTP (4318) en vez de gRPC (4317).

### rove-patches: extend a android-x86_64 + fix CRLF

- `manifest.json`: 3 patches ahora aplican a `android-x86_64` también
  (todos los targets Android comparten estas fricciones de pip).
- `.gitattributes`: `* binary` en `vendor/rove-patches/` — previene
  que git Windows autocrlf rompa los sha256 del manifest.

### Gradle `packageCoreRuntime` multi-ABI

Reemplaza Copy task single-bundle por lógica multi-ABI:

```
apps/android/gimomesh/app/build.gradle.kts:127-176
```

Descubre bundles en `dist/`, copia cada uno a `src/main/assets/runtime/<android_abi>/`:
- `android-arm64` → `arm64-v8a`
- `android-x86_64` → `x86_64`
- `android-armv7` → `armeabi-v7a`

Fail accionable si `dist/` vacío con mensaje mostrando cómo producir
los bundles.

### Kotlin `ShellEnvironment` — ABI detection + rove schema

```
apps/android/gimomesh/app/src/main/java/.../service/ShellEnvironment.kt
```

Cambios:
- `import android.os.Build` para acceder `Build.SUPPORTED_ABIS`.
- `resolveRuntimeAbi()` nuevo: devuelve `"arm64-v8a"`, `"x86_64"`, o
  `"armeabi-v7a"` según preferencia del device, o `null` si no matchea.
- `prepareEmbeddedCoreRuntime()` lee `runtime/<abi>/gimo-core-runtime.manifest.json`
  y copia el tarball `gimo-core-runtime.tar.xz` a filesystem interno.
  La descompresión xz se deja al consumer (Termux tar, rove fetch CLI
  futuro) — Kotlin no implementa decompresión xz.
- `EmbeddedCoreRuntimeManifest` ampliado al schema rove `WheelhouseManifest`:
  `projectName`, `runtimeVersion`, `target`, `tarballName`, `tarballSha256`,
  `compressedSizeBytes`, `signature`, `pythonRelPath`, `projectRootRelPath`,
  `pythonPathEntries`, `extraEnv`.

---

## 4. Lo que está validado (con evidencia)

### Unit tests Python

- **1837 tests passed, 1 skipped, 0 failed** tras la migración rove
  (post `e2bfbb3`).
- Tests relacionados a runtime/mesh/signature/manifest/launcher: **175/175**.
- Tests nuevos rove-patches en `test_runtime_cross_compile.py`: **12/12**.

### Smoke test Core localhost Windows

- `/healthz` → 200 OK.
- `/openapi.json` → 264 paths incluyendo todos los `/ops/mesh/*`.
- `verify_manifest(m)` → `True` tras fix `EMBEDDED_RUNTIME_PUBLIC_KEY`.
- Host build `scripts/package_core_runtime.py build --target host`
  produjo bundle firmado 38.8 MiB válido en 3.5 min.

### Rove wheelhouse build

- `build_rove_wheelhouse.py --target android-arm64` → 21.5 MiB en ~15s.
- `build_rove_wheelhouse.py --target android-x86_64` → 22.3 MiB en ~15s.
- Verificado por `tar -tf`: wheels `cryptography-46.0.5-cp311-abi3-manylinux2014_aarch64`
  en bundle arm64, `manylinux2014_x86_64` en bundle x86_64. ABI correcta.
- Firmas Ed25519 válidas (manifest.json firmado con clave de
  `secrets/runtime-signing.pem`).

### APK build + install

- `./gradlew :app:assembleDebug` → BUILD SUCCESSFUL 43s.
- APK size: 160 MiB. Contenido `assets/runtime/`:
  ```
  arm64-v8a/gimo-core-runtime.manifest.json  5655 B
  arm64-v8a/gimo-core-runtime.tar.xz         22,513,252 B
  x86_64/gimo-core-runtime.manifest.json     5613 B
  x86_64/gimo-core-runtime.tar.xz            23,404,264 B
  trusted-pubkey.pem                         116 B
  ```
- APK instalado en emulator Android 16 API 36 (x86_64) — arranca sin
  crash. PID 13117 vivo, UI Compose renderiza el setup wizard:
  "Join the mesh" + 4 modos + SCAN QR + ENTER CODE MANUALLY, i18n ES
  activa.

### Estado Core en S10 (previo a esta sesión, sigue vivo)

- Core PID 27892 en S10 llevaba 7 días arriba cuando audité (2026-04-18 20:44).
- Respondía `/health` con `{"status":"ok"}` desde LAN 192.168.0.244:9325.
- `/ops/mesh/devices` listó 22 devices registrados, 2 conectados.
- `/ops/inference/status` → `initialized:false` (engine no arrancado).
- llama-server no corriendo (esperado — requiere dispatch explícito).
- Este Core NO corre código de la migración rove (fue arrancado antes).
  Sigue funcional porque nada se rompió; mi trabajo no reemplazó su runtime.

---

## 5. Lo que NO está validado (honesto)

### Flow del wizard interactivo en emulador

Requiere:
1. Core arriba con admin role (para crear enrollment code vía
   `/ops/mesh/onboard/code`).
2. Enable mesh en config (`mesh_enabled:true`).
3. Tap `INFERENCE`/`UTILITY`/`SERVER`/`HYBRID` en el APK del emulator.
4. Tap `ENTER CODE MANUALLY`, input 6-digit code.
5. APK phones home → Core aprueba → device_id + secret issued.
6. `MeshAgentService.onStartCommand(START)` → `ShellEnvironment.init()` →
   `prepareEmbeddedCoreRuntime()` detecta ABI, copia tarball x86_64 a
   `/data/data/com.gredinlabs.gimomesh/files/runtime/`.

Bloqueador encontrado: el `.orch_token` local resuelve a role `operator`,
no `admin`. `/ops/mesh/onboard/code` requiere admin. Intenté crear
`.gimo_credentials` con admin role pero Core sigue resolviendo operator
(causa root-cause no identificada — probablemente caching de `_SETTINGS`
que carga antes de mi write). Decidí parar el rabbit hole de auth porque
el flow del wizard es **ortogonal al ABI** — el mismo Kotlin corre en S10
(donde sí ha funcionado históricamente) que en emulator x86_64.

### Instalación del nuevo APK en S10

El APK agnóstico producido en esta sesión (`app-debug.apk`, 160 MiB) NO
se instaló en el S10. El S10 sigue con la versión 1.0.0 (instalada
2026-04-12, updated 2026-04-17). Validación pendiente: `adb install -r`
al S10 real y ver que detecte `arm64-v8a`, use bundle arm64.

### Termux bootstrap con rove fetch (en vez de pip install)

La integración actual del Termux bootstrap (`scripts/termux_core_bootstrap.sh`)
sigue usando `pip install -r requirements.txt` — rove está disponible
vía el wheel vendorizado, pero el bootstrap no usa `rove fetch` todavía
ni extrae el wheelhouse pre-built. Sigue teniendo el compile path (más
rápido ahora sin grpcio, pero aún ~10-15 min en S10 primera vez).
Refactor pendiente: leer el tarball `assets/runtime/arm64-v8a/gimo-core-runtime.tar.xz`
(ya en el APK) + extraer vía busybox tar sin pip.

---

## 6. Fricciones detectadas en rove 1.0.0 (upstream)

Documentadas en `/tmp/rove-src/TODO_GIMO_FRICTIONS.md` (branch
`gimo-feedback/v1.0.1-android-x86_64`, no pushed). Resumen:

### P0 — críticas (silent misbehavior)

1. **`rove build` CLI no pasa `--platform` a pip download**. `PipRunOptions.extra_args`
   docstring lo sugiere pero `cli.build_cmd` nunca lo construye. En
   Windows host, `rove build --target android-arm64` baja wheels
   `win_amd64` y los firma como bundle arm64.
2. **Sin verificación de ABI real post-descarga**. Consumer puede quedar
   con bundle firmado conteniendo wheels de otra plataforma.
3. **Falta target `android-x86_64`**. Emuladores Google Play, Chromebook
   ARC, tablets Android x86. Patcheado localmente en 1.0.1.

### P1 — importantes

4. `[tool.rove].requirements` no acepta `-r file.txt` → duplicación
   entre requirements.txt y rove.toml.
5. Env expansion `${VAR:default}` en `sign_key` no se expande.
6. pip `resolution-too-deep` sin herramienta propia de lock files.
7. Patch registry sha256 se rompe con CRLF (Git Windows autocrlf).
8. Sin `rove.targets.pip_platform_tags(target)` helper público.

### P2 — nice-to-have

9-12. Var `use_target_python="termux"` declarativo, `rove lock`,
docs `<bundle>.tar.xz.manifest.json` convention, Zig fallback debería
ser error no silent.

### 13. Workaround GIMO candidato a refactor upstream

`scripts/build_rove_wheelhouse.py` (~300 líneas) implementa lo que el
CLI debería hacer nativo si se resuelven P0.1 + P0.2 + P1.4 + P1.5.

**Estimación upstream**: ~1 día trabajo para rove 1.1.0 con P0+P1.

---

## 7. Acción pendiente en rove upstream

- Decidir si pushear branch `gimo-feedback/v1.0.1-android-x86_64`
  (commit `635d58c`) al repo `GredInLabsTechnologies/rove` como PR
  con el TODO + el patch. Hoy queda local en `/tmp/rove-src`.
- Abordar los 13 items P0/P1/P2 en ciclo rove 1.1.0.

---

## 8. Próximos pasos (siguiente sesión)

Ordenados por ROI y dependencia:

### Corto plazo — cierre de validación

1. **Install APK agnóstico en S10** (`adb install -r apps/android/.../app-debug.apk`).
   Verificar que detecta `arm64-v8a`, copia el bundle correcto, no rompe
   funcionalidad existente. 5 min.
2. **Flow wizard end-to-end en emulador** — resolver el tema de auth
   (crear admin token properly via fresh `.gimo_credentials` con Core
   recién arrancado sin env vars previas), generar 6-digit code, tap
   through wizard. 30 min.
3. **Push del branch GIMO a origin**: `git push origin feature/gimo-mesh`
   con los 9 commits.

### Medio plazo — rove wheelhouse en bootstrap

4. **Refactor `scripts/termux_core_bootstrap.sh`** para extraer el
   wheelhouse pre-built (que ya está en `/data/data/com.gredinlabs.gimomesh/files/runtime/<abi>/gimo-core-runtime.tar.xz`
   después del primer boot del APK) con `busybox tar -xJf`, luego
   `pip install --no-index --find-links=wheelhouse/`. Elimina el
   compile en device → primera corrida Termux ~1-2 min en vez de 10-15.
5. **Runtime upgrader peer-to-peer con `rove.distribution.http_fetcher`**.
   Reemplazar `tools/gimo_server/services/runtime_upgrader.py` (custom)
   por delegación a rove's HTTP server/fetcher con signature verification.

### Largo plazo — rove upstream + mesh features

6. **Push del branch rove** + abrir PR al repo upstream con los P0+P1
   items implementados, ~1 día trabajo.
7. **Utility mode E2E dispatch** con mesh multi-node real (host + S10 +
   emulador en la misma LAN).
8. **Inference validation** — cargar un GGUF real en el S10 (no
   placeholder zeros) y verificar llama-server runtime con los wheels
   pre-built del runtime rove.

### Memoria y housekeeping

9. Actualizar `project_dev_mesh_experiment.md` con enlace a este report.
10. Decidir sobre el merge de `feature/gimo-mesh` → `main` (hay 22
    conflictos con refactors que entraron a main por otro lado; bloqueado
    desde el sprint anterior).

---

## 9. Archivos y comandos de referencia

### Comandos clave

```bash
# Producir wheelhouse para un target Android
export PATH="C:/Users/shilo/AppData/Local/Temp/zig-install/zig-x86_64-windows-0.14.1:$PATH"
python scripts/build_rove_wheelhouse.py --target android-arm64
python scripts/build_rove_wheelhouse.py --target android-x86_64

# Build APK con todos los wheelhouses disponibles en dist/
cd apps/android/gimomesh && ./gradlew :app:assembleDebug

# Install en emulator
adb -s emulator-5554 install -r apps/android/gimomesh/app/build/outputs/apk/debug/app-debug.apk

# Install en S10
adb -s <s10-serial> install -r apps/android/gimomesh/app/build/outputs/apk/debug/app-debug.apk

# Core local con DEBUG bypass (admin role requiere .gimo_credentials limpia)
DEBUG=true ORCH_LICENSE_ALLOW_DEBUG_BYPASS=true ORCH_OPERATOR_TOKEN= ORCH_ACTIONS_TOKEN= \
  python -m uvicorn tools.gimo_server.main:app --host 0.0.0.0 --port 9325
```

### Archivos clave añadidos/modificados

**Python**:
- `vendor/rove/rove_toolkit-1.0.1-py3-none-any.whl` (nuevo)
- `vendor/rove/rove_toolkit-1.0.1.tar.gz` (nuevo)
- `vendor/rove-patches/` (nuevo directorio)
- `rove.toml` (nuevo)
- `scripts/build_rove_wheelhouse.py` (nuevo)
- `requirements-locked.txt` (nuevo)
- `tools/gimo_server/services/observability_pkg/observability_service.py` (grpc→http)
- `tools/gimo_server/models/runtime.py` (shim rove)
- `tools/gimo_server/security/runtime_signature.py` (adapter rove)
- `scripts/package_core_runtime.py` (rove-patches integration)
- `scripts/termux_core_bootstrap.sh` (ANDROID_API_LEVEL export)

**Kotlin / Android**:
- `apps/android/gimomesh/app/build.gradle.kts` (packageCoreRuntime multi-ABI)
- `apps/android/gimomesh/app/src/main/java/.../service/ShellEnvironment.kt` (ABI detection + rove schema)
- `apps/android/gimomesh/app/src/main/res/values/strings.xml` (i18n EN)
- `apps/android/gimomesh/app/src/main/res/values-es/strings.xml` (i18n ES, nuevo)
- `apps/android/gimomesh/app/src/main/java/.../ui/setup/SetupWizardScreen.kt` (i18n strings)

**Docs**:
- `docs/DEV_MESH_ARCHITECTURE.md` (Rev 1 rove)
- `docs/audits/SESSION_REPORT_20260418_ROVE_APK_AGNOSTIC.md` (este file)

**Rove (local branch `gimo-feedback/v1.0.1-android-x86_64`, no pushed)**:
- `/tmp/rove-src/src/rove/targets.py`
- `/tmp/rove-src/src/rove/builder/zig.py`
- `/tmp/rove-src/src/rove/builder/python_standalone.py`
- `/tmp/rove-src/pyproject.toml`
- `/tmp/rove-src/TODO_GIMO_FRICTIONS.md`

### Environment setup notes

- **Zig 0.14.1** vive en `C:/Users/shilo/AppData/Local/Temp/zig-install/zig-x86_64-windows-0.14.1/`.
  Sobrevive a reinicios de sesión Claude pero no a reinicios del OS.
  Para producción: instalar via scoop (`scoop install zig`) o download
  oficial a ruta estable + añadir al PATH de Windows.
- **Python 3.13.3** en Windows Store. Dev venv no aislado — rove instalado
  en user site-packages. Para builds reproducibles sería mejor venv
  dedicado (`.venv-rove-builder/`).
- **vendor/gics/node_modules/** requiere `npm install` dentro de
  `vendor/gics/` para que el Core arranque localmente sin ERR_MODULE_NOT_FOUND.

---

## 10. Métricas

- **Tiempo de sesión**: ~6 horas (2026-04-18 tarde → noche, continuación 2026-04-19).
- **Commits GIMO**: 9.
- **Commits rove (local)**: 1.
- **Líneas diff netas en GIMO**: aprox +2000 (mayoría en el commit `c87ad86`).
- **Tests corridos**: 1837/1838 verdes (1 skip, 0 failed).
- **Tamaños de artefactos**:
  - Rove wheel 1.0.1: 67 KiB
  - Wheelhouse android-arm64: 21.5 MiB (73 wheels pre-built)
  - Wheelhouse android-x86_64: 22.3 MiB (73 wheels pre-built)
  - APK agnóstico multi-ABI: 160 MiB (ambos runtimes embebidos)

---

**Autor**: sesión conjunta Claude Opus 4.7 (1M context) + usuario shilo.
**Revisión pendiente**: push a origin + validación en S10.
