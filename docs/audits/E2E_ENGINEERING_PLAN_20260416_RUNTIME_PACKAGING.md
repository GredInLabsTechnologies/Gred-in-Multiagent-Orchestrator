# E2E Engineering Plan — GIMO Core Runtime Packaging (hardware-agnóstico)

- **Fecha**: 2026-04-16
- **Ronda**: R1 (RUNTIME_PACKAGING)
- **Rama**: `feature/gimo-mesh`
- **Estado**: APROBADO 2026-04-16 — iniciando Phase 4
- **Decisiones de aprobación (usuario, 2026-04-16)**:
  1. Alcance de 10 + 1 changes: APROBADO tal cual
  2. python-build-standalone como fuente CPython: APROBADO
  3. Reutilizar keypair de licensing para firma del runtime: APROBADO
  4. **CI matrix inicial**: `android-arm64` + `windows-x86_64` (user-first: Android y Windows cubren el 99% del target de usuario final). `linux-x86_64`, `linux-arm64` y `darwin-arm64` pasan a follow-up.
  5. Branch: continuar en `feature/gimo-mesh` (no crear sub-branch)
- **Inputs**:
  - `AGENTS.md` (doctrine operativa, Plan Quality Standard, legacy hunting)
  - `docs/SYSTEM.md`, `docs/CLIENT_SURFACES.md`, `docs/SECURITY.md`
  - `docs/DEV_MESH_ARCHITECTURE.md` §2.3 (Server Node), §11.2 (Phone as Server)
  - `.github/workflows/ci.yml`
  - [E2E_ROOT_CAUSE_ANALYSIS_20260416_ANDROID_RUNTIME_PACKAGING.md](./E2E_ROOT_CAUSE_ANALYSIS_20260416_ANDROID_RUNTIME_PACKAGING.md) (Phase 2 hermana)
  - [E2E_ENGINEERING_PLAN_20260415_SERVER_MODE_RUNTIMES.md](./E2E_ENGINEERING_PLAN_20260415_SERVER_MODE_RUNTIMES.md) (plan vecino del selector mode×runtime; §8.4 defiere el packaging a esta ronda)
  - Decisiones del usuario 2026-04-16 (4 constraints, literales más abajo)

---

## 1. Diagnóstico (condensado de Phase 2)

El RCA identifica cuatro issues con raíz común (*consumer-sin-productor*):

- **PKG-1**: No existe productor del manifest `assets/runtime/gimo-core-runtime.json` que `ShellEnvironment.prepareEmbeddedCoreRuntime()` consume → server mode Android nunca arranca.
- **PKG-2**: No hay origen canónico del Core en el escenario seed (primer device de una mesh) → el diseño "descarga on-demand" del plan vecino es incompleto.
- **PKG-3**: No hay protocolo de sync de upgrades entre peers → la mesh transporta cómputo, no su propio código.
- **PKG-4**: Dos caminos de arranque distintos (desktop asume `python` en PATH, Android asume runtime bundled) → asimetría multi-plataforma.

Todo converge en una decisión arquitectónica: **el runtime de GIMO Core es un artefacto firmado y versionado, producido por el CI del repo y distribuido o bien en el instalador inicial o bien peer-to-peer entre nodos de la mesh**.

---

## 2. Constraints del usuario (decisiones inamovibles 2026-04-16)

1. **APK self-contained como origen canónico**; el mesh sync es para upgrades posteriores, no para bootstrap.
2. **Empaquetado artesanal, 100% OSS**, cero licencias pagadas. *"Me ves cara de pagar 1000 euros al año? Aquí todo gratis, y si no existe gratis lo creo yo"* — rechazo explícito de Chaquopy.
3. **Una sola invariante de ejecución de Core**, no dobles caminos. *"Si arreglamos 1 sistema, por consiguiente el resto tambien noten esa mejora"*.
4. **Scope MVP mergeable a main**: todos los sistemas funcionan aunque no sean perfectos. *"Nuestro scope es terminar al menos un mvp de la app"*.

Adicional (2026-04-16, nota en vivo): el plan debe ser **hardware-agnóstico**. *"Espero que gimo sea capaz de funcionar en cualquier hardware, sea una raspberry, una tablet, un portatil, un pc de sobremesa, o un frigorifico"*. → El Android es el caso hostil más restrictivo (no pip, sin user-Python), pero no el único target.

---

## 3. Principios de diseño

Derivados de AGENTS.md Plan Quality Standard + las 4 constraints del usuario:

1. **Un productor, N consumidores** — un solo script de empaquetado (`scripts/package_core_runtime.py`) produce bundles para todos los targets; Android + desktop + Raspberry los consumen idénticamente.
2. **Bundle autocontenido por defecto, incluso en desktop** — el desktop moderno no debería depender de que el usuario tenga Python. El `gimo.cmd` que ya existe se extiende para desempaquetar el bundle si no lo está. Esto cierra PKG-4 sin cambiar la ergonomía del usuario.
3. **Firmado canónico con Ed25519** — reutilizar la infra de `docs/SECURITY.md` (clave pública bundled + JWT offline). Un payload no firmado correctamente se rechaza.
4. **Versión monótona declarativa** — el bundle lleva `runtime_version` SemVer; el TXT record mDNS lo anuncia; peers con versión superior se marcan como *upgrade source*.
5. **Mesh sync opcional y opt-in** — un device nunca descarga un runtime nuevo sin confirmación del operator. *Inform, don't block*.
6. **Cero doble camino** — el `EmbeddedCoreRunner` de Android y el launcher de desktop llaman al mismo ProcessBuilder contra el mismo `pythonBinary` resuelto por el bundle. El CLI `gimo.cmd` se refactoriza para consumir el bundle.
7. **MVP merge-to-main** — lo mínimo funcional: (a) pipeline de empaquetado Android + desktop x86_64 + desktop ARM64 (Raspberry Pi 4 cubre a los demás ARM Linux); (b) endpoint HTTP de upgrade; (c) mDNS runtime_version; (d) Android UI muestra versión. Sin UI compleja de upgrades, sin Windows installer sofisticado — commit-line-worthy sólo lo core.

---

## 4. Lista de cambios

> **Nota sobre compresión (2026-04-16 feedback en vivo del usuario)**: el bundle se comprime por default (XZ, ratio ~3.5×) y se descomprime *lazy* sólo si el device activa server mode. APK liviana por diseño; zero coste de extracción para usuarios inference-only. Integrado en Changes 2 + 2b + 7.

### Change 1 — Especificación canónica del manifest del runtime

- **Resuelve**: PKG-1, PKG-4
- **Qué**: formalizar `gimo-core-runtime.json` como schema Pydantic vivo en `tools/gimo_server/models/runtime.py`. Añadir campo `runtime_version: str` (SemVer), `signature: str` (Ed25519 sobre sha256 del tree), `target: str` (ej `android-arm64`, `linux-x86_64`, `linux-arm64`, `darwin-arm64`, `windows-x86_64`).
- **Dónde**:
  - `tools/gimo_server/models/runtime.py` (nuevo, ~80 LOC)
  - `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/ShellEnvironment.kt:223-230` — extender `EmbeddedCoreRuntimeManifest` con los campos nuevos (tolerante a missing para backward compat).
- **Por qué**: el contrato pasa a ser una sola fuente de verdad (Pydantic canonical + Kotlin espejo). Android y Python leen del mismo schema — cero drift.
- **Riesgo**: bajo. Nuevos campos opcionales no rompen al consumer actual.
- **Verificación**: test Pydantic round-trip + test de que `ShellEnvironment` acepta manifests nuevos y legacy.

### Change 2 — Productor `scripts/package_core_runtime.py` (bundle comprimido)

- **Resuelve**: PKG-1 (raíz), PKG-4
- **Qué**: script maestro hardware-agnóstico que produce un **bundle comprimido firmado** para un `--target`. Subcommands:
  - `detect-target` → imprime el target actual (para uso en desktop cuando arranca por primera vez).
  - `build --target <t> --output <dir> [--compression xz|zstd|none]` → produce:
    - Un único archivo **`gimo-core-runtime.tar.<ext>`** conteniendo:
      - `python/` — CPython 3.11 redistribuible (fuente: **python-build-standalone** OSS, licencia Apache 2.0 / Python, https://github.com/astral-sh/python-build-standalone).
      - `site-packages/` — wheels de `requirements.txt` instalados con `pip install --target=... --platform=<abi> --only-binary=:all:`.
      - `repo/tools/gimo_server/` — tree del servidor.
    - `gimo-core-runtime.json` — manifest firmado, **fuera del tarball** (para poder decidir si extraer sin tocar el payload). Contiene: versión, target, firma Ed25519 sobre sha256 del tarball, `compression` (xz/zstd/none), `uncompressed_size_bytes`, `compressed_size_bytes`, lista de archivos internos, `python_rel_path`, etc.
    - `gimo-core-runtime.sig` — firma Ed25519 independiente, redundante para validación offline aislada.
  - `verify <dir>` → valida firma del manifest + sha256 del tarball + compatibilidad de versión.
- **Compresión**:
  - **Default XZ/LMZA** (`tar.xz`, preset 9e, threads auto). Ratio esperado ~3.5× sobre un tree de CPython+stdlib+wheels: un tree de ~45 MB baja a ~13 MB.
  - Alternativa `zstd --long=27 -19` — ratio ~3× pero descompresión 3-4× más rápida (útil si el startup es crítico en hardware lento como Raspberry Pi Zero).
  - `--compression none` para debug / targets donde el bundle ya es payload fino.
- **Dónde**: `scripts/package_core_runtime.py` (~400 LOC estimadas, split en submódulos si crece).
- **Por qué**: un script único, un artefacto único por target, comprimido por default. Minimiza tamaño del APK (~13 MB vs ~45 MB) y del installer desktop. Descompresión es lazy (Change 2b).
- **Riesgo**: medio. Dependencia de que el target tenga XZ/zstd disponible para descomprimir. Python 3.11 stdlib incluye `lzma` y `zstandard` (este último vía wheel); ambos embebidos en el bundle, por lo que el bootstrap sólo necesita **el descompresor del primer payload**. El launcher Kotlin/shell usa un descompresor nativo externo (ver Change 2b).
- **Verificación**: test que produce bundle comprimido, verifica ratio esperado, valida firma sobre el tarball comprimido, expande y corre `python -c "import tools.gimo_server.main"`.

### Change 2b — Descompresión lazy y atomic swap

- **Resuelve**: requisito del usuario "APK liviana, descomprimir sólo si hace falta"
- **Qué**: lógica de extracción perezosa en ambos consumers (Android + desktop launcher):
  1. **Al boot de server mode** (no antes): el consumer lee `gimo-core-runtime.json` del filesystem.
  2. Si `<dataDir>/runtime/.extracted-version` contiene la misma `runtime_version` que el manifest → skip extracción (ya hecho en un boot previo).
  3. Si no coincide: extraer `gimo-core-runtime.tar.xz` a `<dataDir>/runtime-extracting/`, al terminar `rename(runtime-extracting/, runtime/)` atómico, escribir `.extracted-version`.
  4. Si el tarball no existe localmente (modo "APK ultra liviana", follow-up), pedirlo a un peer vía Change 4 antes de intentar extraer.
- **Descompresor**:
  - **Android**: añadir wheel `python-zstandard` + uso de `lzma` stdlib en un helper Kotlin que lanza una invocación de `busybox` con `tar xJ` (busybox trae XZ). Para `zstd` se incluye el binario estático `zstd` en `assets/bin/` (~400 KB, licencia BSD).
  - **Desktop Linux/macOS**: `tar` del sistema soporta XZ y zstd nativamente (glibc ≥ 2.31, tar ≥ 1.32).
  - **Desktop Windows**: incluir `tar.exe` de MSYS o usar `lzma` nativo de Python 3.11 que viene en el propio bundle (bootstrap paradox: se necesita un pre-bundle mínimo de Python estático; en Windows se usa `tar.exe` de System32 que soporta XZ desde Windows 10 1803). Alternativa 100% OSS: `7zip` en `PATH` si está disponible, si no warning actionable.
- **Dónde**:
  - `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/ShellEnvironment.kt:164-204` — reemplazar `prepareEmbeddedCoreRuntime()` para expandir tarball antes de leer `manifest.files`.
  - `gimo.cmd` / `gimo.sh` — añadir paso de extracción previo al arranque.
  - `tools/gimo_server/services/runtime_bootstrap.py` (nuevo, ~120 LOC) — helper Python reusable para desktop que también sirve como fallback.
- **Atomicidad**:
  - Extracción va a `runtime-extracting/`, swap con `rename()` atómico cuando acaba.
  - Si el proceso se mata a mitad, al próximo boot se detecta `runtime-extracting/` presente y se limpia antes de reintentar.
  - `.extracted-version` se escribe *después* del rename, por lo que nunca queda stale.
- **Por qué**: cumple la pauta del usuario exactamente. APK baja de ~50 MB a ~15 MB; la extracción ocurre sólo cuando el operator activa server mode; si nunca lo activa (es un device pure-inference), el runtime nunca se decomprime y ocupa cero en filesystem adicional al del tarball comprimido en assets. Un device inference-only con APK liviana = experiencia óptima.
- **Riesgo**: medio — la extracción es I/O intensiva; en Android puede tardar 5-20 s según hardware. Mitigación:
  - UI muestra progress *"Preparando GIMO Core por primera vez…"* durante la extracción.
  - Extracción corre en `Dispatchers.IO`, no bloquea UI thread.
  - Si falla por espacio en disco, error actionable que pide ≥200 MB libres.
  - Hash sha256 del tarball se compara antes y después de extracción (detecta corrupción en I/O).
- **Verificación**: tests unitarios del extractor (Python + Kotlin mockeado), test de integración que simula boot frío y verifica `.extracted-version` tras el primer arranque, test de idempotencia (2º boot no re-extrae), test de recovery (`runtime-extracting/` residual se limpia).

### Change 3 — Firma Ed25519 reusando la infra de license

- **Resuelve**: PKG-3 (preparación), requisito de seguridad multi-target
- **Qué**: reusar el keypair de licensing (`tools/gimo_server/security/` + `scripts/generate_license_keys.py`) como firma del runtime. La clave privada vive en GitHub Actions secrets (CI-only). La clave pública viaja en el APK / bundle como hoy la licencia.
- **Dónde**:
  - `tools/gimo_server/security/runtime_signature.py` (nuevo, reusa primitivas `cryptography`) — ~60 LOC.
  - `tools/gimo_server/models/runtime.py` — incluye `signature` en el manifest.
  - `scripts/package_core_runtime.py` — firma al final del build.
  - Kotlin espejo en `apps/android/gimomesh/.../security/RuntimeSignatureVerifier.kt` (nuevo) — valida la firma al arrancar. Rechaza runtimes no firmados o firmados con clave distinta.
- **Por qué**: cero criptografía nueva, cero decisiones nuevas. Reutiliza lo que ya pasó review en R18.
- **Riesgo**: bajo. La librería `cryptography` ya es dep obligatoria.
- **Verificación**: test unit que firma un bundle dummy y lo verifica; test que rechaza un bundle tampered (un byte flipped).

### Change 4 — Endpoint `GET /ops/mesh/runtime-manifest` y `GET /ops/mesh/runtime-payload`

- **Resuelve**: PKG-3
- **Qué**:
  - `GET /ops/mesh/runtime-manifest` → devuelve el manifest actual del Core corriendo (incluye `runtime_version`, `target`, `signature`, `size_bytes`). Auth operator.
  - `GET /ops/mesh/runtime-payload?chunk=N` → devuelve el tarball firmado del runtime (streaming por chunks de 1 MiB). Auth operator + rate limit estricto (1 req / 10 s por IP).
  - Ambos en `tools/gimo_server/routers/ops/mesh_router.py`.
- **Por qué**: la misma superficie HTTP que todo lo demás. Permite que un peer pida upgrade sin inventar protocolo nuevo.
- **Riesgo**: **medio-alto** — servir binarios ejecutables es un vector crítico. Mitigaciones:
  - auth obligatoria operator + rate limit
  - payload firmado Ed25519, el consumer valida antes de extraer
  - hash sha256 en el manifest, consumer compara antes de ejecutar
  - validación de versión: sólo se acepta un `runtime_version` ≥ al actual
  - endpoint opt-in: desactivado por default, habilitado con `ORCH_MESH_RUNTIME_SYNC=true`
- **Verificación**: tests de integración con TestClient que verifican auth, rate limit, firma válida/inválida, payload corrupto detectado.

### Change 5 — mDNS TXT extendido con `runtime_version`

- **Resuelve**: PKG-3 (gossip layer)
- **Qué**: añadir key `runtime_version` al TXT record existente en `mdns_advertiser.py`. El HMAC ya firma todo el record, así que el gossip de versión queda autenticado al mismo coste.
- **Dónde**:
  - `tools/gimo_server/services/mesh/mdns_advertiser.py` — extender `_encode_properties()` y el string del HMAC a `hostname:port:mode:health:load:runtime_version`.
  - `tools/gimo_server/services/mesh/mdns_discovery.py` — expone `runtime_version` en `DiscoveredPeer`.
  - `gimo_cli/commands/discover.py` — columna opcional `RUNTIME` (detrás de flag `--show-runtime`).
- **Por qué**: permite que `gimo discover` muestre peers y sus versiones, y que un device con versión vieja pueda elegir un peer con versión nueva para upgrade.
- **Riesgo**: bajo. Backward-compatible: peers sin la key muestran `—` en la columna.
- **Verificación**: extender `tests/integration/test_server_mode_boot.py::TestMdnsTxtRecordSignals` para cubrir el nuevo campo.

### Change 6 — Desktop launcher consume el bundle (unificación PKG-4)

- **Resuelve**: PKG-4 (doble camino)
- **Qué**: `gimo.cmd` / `gimo.sh` se refactoriza para:
  1. Detectar si existe `<install>/runtime/gimo-core-runtime.json` junto al launcher.
  2. Si existe, lanzar `<install>/runtime/python/bin/python -m uvicorn tools.gimo_server.main:app --host <bind>` con `PYTHONPATH` apuntando al bundle (mismo esquema que Android).
  3. Si no existe, fallback al comportamiento actual (`python -m tools.gimo_server.main`) con WARN log.
- **Dónde**: `gimo.cmd`, `gimo.sh`, `scripts/dev/launcher.py` si aplica.
- **Por qué**: el desktop deja de depender de que el usuario tenga Python. Mismo bundle que Android. Cero doble camino en el happy path.
- **Riesgo**: medio — romper el launcher es visible inmediatamente. Mitigación: el fallback al comportamiento actual mantiene backward compat mientras se distribuye el bundle.
- **Verificación**: test de smoke del launcher contra ambos escenarios (bundle presente / ausente) en un runner Linux en CI.

### Change 7 — Android build integra el packaging (APK liviana)

- **Resuelve**: PKG-1 (consumer-side), PKG-2
- **Qué**: añadir gradle task `:app:packageCoreRuntime` que:
  1. Invoca `python scripts/package_core_runtime.py build --target android-arm64 --compression xz --output app/src/main/assets/runtime/`.
  2. Produce dentro de `assets/runtime/` únicamente: `gimo-core-runtime.tar.xz` + `gimo-core-runtime.json` + `gimo-core-runtime.sig`. **No** se desempaqueta en el APK.
  3. Corre antes de `mergeDebugAssets` / `mergeReleaseAssets`.
  4. Falla el build si el script falla (no fallback silencioso).
  5. Registra el tamaño comprimido en `build/reports/runtime-size.txt` y emite WARN si supera 25 MB (indicador de drift).
  6. Configurar `aaptOptions { noCompress "xz" }` en `build.gradle.kts` para que el APK no re-comprima el tarball (ya está óptimo).
- **Dónde**: `apps/android/gimomesh/app/build.gradle.kts` — añadir `exec` task + dependencia + `aaptOptions`.
- **Por qué**: el APK sigue siendo liviana (~15 MB del runtime vs ~45 MB uncompressed), el consumer `ShellEnvironment` siempre encuentra el tarball, y la extracción ocurre sólo si se activa server mode (Change 2b). Cierra PKG-2: un móvil recién instalado es seed autosuficiente sin penalizar a usuarios inference-only.
- **Riesgo**: medio — requiere Python 3.11 en la máquina de build y `xz`/`zstd` disponibles. Mitigación: documentar el requisito en `apps/android/README.md` y fallar con mensaje actionable.
- **Verificación**: `./gradlew :app:assembleDebug` en CI verifica que el APK contiene `assets/runtime/gimo-core-runtime.tar.xz` + manifest, y que el APK final pesa menos de X MB (threshold configurable).

### Change 8 — Upgrade flow opt-in (Android UI + endpoint consumer)

- **Resuelve**: PKG-3 (consumer side)
- **Qué**: funcionalidad MVP mínima:
  - `tools/gimo_server/services/mesh/runtime_upgrader.py` (nuevo, ~200 LOC) — cliente HTTP que dado un peer URL descarga manifest, valida firma, descarga payload en `filesDir/runtime-pending/`, valida hash, mueve atomic a `filesDir/runtime-next/`, marca para swap al próximo restart.
  - En Android: pantalla minimal *"Upgrade disponible"* en `SettingsScreen` con botón **Instalar**. Sin rollback automatizado, sin progress fancy — MVP.
  - En desktop: comando `gimo runtime upgrade --from <peer-url>` (sync, informativo).
- **Dónde**: backend service + 1-2 archivos Kotlin en `apps/android/gimomesh/.../ui/settings/` + 1 comando en `gimo_cli/commands/`.
- **Por qué**: es la capa consumer de Changes 3+4+5. Sin esto, el gossip de versión es decorativo.
- **Riesgo**: alto — es código que **reemplaza un binario del Core en caliente**. Mitigación MVP:
  - upgrade requiere confirmación explícita del operator.
  - nunca se sobreescribe `filesDir/runtime/` directamente; se prepara en `runtime-next/` y se swapea al próximo restart.
  - si el swap falla al arranque (runtime nuevo no boot), se rolla back a `runtime/` automáticamente (symlink o rename inverso).
  - rate limit server-side + auth operator evita abuso.
  - telemetría obligatoria: cada upgrade deja un record en el audit log (`tools/gimo_server/security/audit.py`).
- **Verificación**: test unit del upgrader con server mockeado; test manual del happy path (2 devices) documentado en runbook; test del rollback (corromper el runtime-next y verificar que al restart el viejo sigue funcionando).

### Change 9 — CI matrix multi-target (MVP: Android + Windows)

- **Resuelve**: PKG-4 (multi-plataforma real)
- **Qué**: añadir job `runtime-bundles` en `.github/workflows/ci.yml`:
  - matriz MVP **`target: [android-arm64, windows-x86_64]`** — cubre al usuario final (móvil + PC Windows) primero.
  - cada job corre `python scripts/package_core_runtime.py build --target $TARGET --compression xz` y sube el artefacto firmado con `actions/upload-artifact@v4`.
  - el job firma con la clave privada de GitHub Actions secrets (reutilizando `ORCH_RUNTIME_SIGNING_KEY`).
  - en push a `main` y tags, publica los bundles como release asset.
- **Dónde**: `.github/workflows/ci.yml`.
- **Por qué**: decisión del usuario 2026-04-16 — priorizar experiencia del usuario final sobre el developer. Android + Windows = caso real. Linux x86_64/ARM64 y macOS se añaden como follow-up cuando un operador los demande; el producto ya soporta esos targets técnicamente (mismo script), sólo no vienen pre-builteados en el CI.
- **Riesgo**: medio — CI Windows es más lento (runners compartidos GH Free). Mitigación: jobs paralelos + caché de wheels agresiva.
- **Verificación**: CI verde en primer merge-to-main con el plan; ambos bundles (`gimo-core-runtime-android-arm64.tar.xz` + `gimo-core-runtime-windows-x86_64.tar.xz`) adjuntos como artifact.
- **Follow-up**: añadir `linux-x86_64`, `linux-arm64`, `darwin-arm64` a la matriz cuando haya demanda documentada.

### Change 10 — Documentación hardware-agnóstica

- **Resuelve**: expectativa del usuario ("raspberry, tablet, portatil, frigorifico")
- **Qué**:
  - Nueva sección `docs/DEV_MESH_ARCHITECTURE.md §2.4 Runtime Packaging` — cómo funciona el bundle, qué garantiza, cómo se distribuye. ~60-80 líneas.
  - Nueva sección en `docs/MESH_SERVER_RUNBOOK.md §8 Upgrade Procedure` — pasos manuales de upgrade (mvp), rollback, verificación de firma.
  - Mención explícita de targets soportados y una tabla de "qué hardware ha sido validado" (S10 en el primer commit; Raspberry Pi 4, laptop x86_64 y desktop Windows como follow-ups cuando el operador los valide).
- **Dónde**: dos archivos en `docs/`. Cero archivos nuevos.
- **Por qué**: una sola fuente de verdad doc (memoria: *"cero documento markdown repetido"*).
- **Riesgo**: ninguno.
- **Verificación**: revisión editorial + links internos.

---

## 5. Orden de ejecución

Cada paso debe pasar su verificación narrowest antes de avanzar.

1. **Contratos Pydantic + tests failing** (Change 1 schema + Change 3 stubs).
   - `tools/gimo_server/models/runtime.py` con schema completo (incluyendo `compression`, `compressed_size_bytes`, `uncompressed_size_bytes`).
   - `tools/gimo_server/security/runtime_signature.py` con stubs `raise NotImplementedError`.
   - Tests en `tests/unit/test_runtime_manifest.py` y `tests/unit/test_runtime_signature.py`.
   - CI: `pytest tests/unit/test_runtime_manifest.py tests/unit/test_runtime_signature.py -v` → N failures esperados.

2. **Implementación firma + verificación** (Change 3 real).
   - Tests del paso 1 pasan.
   - CI: mismo comando, 100% verde.

3. **Productor `package_core_runtime.py`** (Change 2) en su forma más reducida: sólo target `host` (el target actual de la máquina donde corre), compresión XZ por default.
   - Test: produce un bundle de `host`, valida firma, descomprime a tmpdir, valida que `python -c "import tools.gimo_server.main"` funciona desde el bundle descomprimido.
   - CI: `pytest tests/integration/test_core_packaging.py -v`.

3b. **Helper de extracción lazy + atomic swap** (Change 2b).
   - `tools/gimo_server/services/runtime_bootstrap.py` con API `ensure_extracted(assets_dir, target_dir, expected_version) -> Path`.
   - Tests: extracción fresca, skip si ya extraído, recovery tras `runtime-extracting/` residual, rechazo si hash sha256 no coincide.
   - CI: `pytest tests/unit/test_runtime_bootstrap.py -v`.

4. **Endpoints HTTP** (Change 4).
   - `GET /ops/mesh/runtime-manifest` y `GET /ops/mesh/runtime-payload` con auth + rate limit.
   - CI: tests de integración TestClient.

5. **mDNS TXT extendido** (Change 5).
   - Extender HMAC y advertiser + discovery.
   - CI: tests existentes + nuevo test de `runtime_version` en TXT.

6. **Desktop launcher consume el bundle** (Change 6).
   - `gimo.cmd` + `gimo.sh` con fallback.
   - CI: smoke job que arranca bundle en Linux runner.

7. **Android gradle task de packaging** (Change 7).
   - `:app:packageCoreRuntime` integrado antes de `mergeAssets`.
   - CI: `./gradlew assembleDebug` verifica assets presentes.

8. **Upgrade flow MVP** (Change 8).
   - Backend service + UI mínima + CLI.
   - Tests mockeados del upgrader + test manual documentado.

9. **CI matrix multi-target** (Change 9).
   - Matriz de targets, artifacts uploaded.
   - CI: primer run debe producir los bundles y adjuntarlos.

10. **Documentación** (Change 10).
    - `docs/DEV_MESH_ARCHITECTURE.md §2.4` + `docs/MESH_SERVER_RUNBOOK.md §8`.

11. **Verificación broad final** (gate merge-to-main).
    - `python -m pytest -x -q` (suite completa, debe seguir verde).
    - `./gradlew assembleDebug` limpio.
    - `gimo up` smoke con bundle.
    - APK instalado en device real (S10 o cualquier Android ARM64 disponible) arranca server mode sin `null manifest`.
    - `test_boot_mesh_disabled.py` verde (invariante mesh-off preservada).

---

## 6. Unification check

| Superficie | Consume el runtime canónico | Cómo |
|---|---|---|
| Backend Python (`tools/gimo_server/main.py`) | ✅ corre desde `<bundle>/python` con `<bundle>/repo` en PYTHONPATH | ProcessBuilder |
| Desktop launcher (`gimo.cmd` / `gimo.sh`) | ✅ detecta bundle adyacente, lanza desde ahí | shell |
| Android `EmbeddedCoreRunner` | ✅ ya usa `<filesDir>/runtime/python -m uvicorn ...` | ProcessBuilder |
| CI pipeline | ✅ produce bundles firmados por target | GH Actions matrix |
| mDNS advertiser | ✅ anuncia `runtime_version` en TXT firmado | HMAC |
| HTTP (`/ops/mesh/runtime-*`) | ✅ sirve manifest + payload firmado | REST |
| CLI (`gimo discover`, `gimo runtime upgrade`) | ✅ consume los mismos endpoints | typer |
| Android UI | ✅ muestra versión + botón upgrade | Compose |
| Web UI | 🔜 follow-up — panel "runtime status" trivial sobre el mismo endpoint | React |
| MCP bridge | ✅ auto-expuesto vía OpenAPI sync | dinámico |
| Docs | ✅ §2.4 en DEV_MESH + §8 en MESH_SERVER | markdown único |

**Cero caminos paralelos**. La invariante constraint 3 del usuario queda preservada: si alguien mejora el bundle, todas las superficies se benefician automáticamente.

---

## 7. Estrategia de verificación

### Contract tests (narrowest, Changes 1+3)

```python
# tests/unit/test_runtime_manifest.py
def test_manifest_round_trip():
    m = RuntimeManifest(
        runtime_version="0.1.0",
        target="android-arm64",
        python_rel_path="python/bin/python",
        repo_root_rel_path="repo",
        python_path_entries=["repo", "site-packages"],
        files=["python/bin/python", "..."],
        extra_env={},
        signature="<ed25519-hex>",
    )
    assert RuntimeManifest.model_validate_json(m.model_dump_json()) == m

# tests/unit/test_runtime_signature.py
def test_sign_and_verify():
    priv, pub = generate_keypair()
    payload = b"dummy tree hash"
    sig = sign_runtime(payload, priv)
    assert verify_runtime(payload, sig, pub) is True

def test_tampered_runtime_rejected():
    priv, pub = generate_keypair()
    sig = sign_runtime(b"original", priv)
    assert verify_runtime(b"tampered", sig, pub) is False
```

### Packaging tests (boundary, Change 2)

```python
# tests/integration/test_core_packaging.py
def test_build_host_bundle(tmp_path):
    out = tmp_path / "bundle"
    result = subprocess.run(
        ["python", "scripts/package_core_runtime.py", "build", "--target", "host", "--output", str(out)],
        capture_output=True,
    )
    assert result.returncode == 0
    assert (out / "runtime" / "gimo-core-runtime.json").exists()
    # Validar firma
    manifest = RuntimeManifest.model_validate_json((out / "runtime" / "gimo-core-runtime.json").read_text())
    assert verify_bundle_signature(out, manifest.signature) is True
```

### Endpoint tests (boundary, Change 4)

- `GET /ops/mesh/runtime-manifest` sin auth → 401.
- Con auth operator → 200 + manifest válido.
- `GET /ops/mesh/runtime-payload?chunk=0` → 200 + primer chunk.
- Rate limit: 2ª request en < 10s → 429.
- Payload hash mismatch simulado → consumer rechaza.

### Runtime smoke (gate merge-to-main)

1. `python scripts/package_core_runtime.py build --target $(detect-target)` → bundle producido.
2. `./gimo.cmd` (con bundle adyacente) → health check verde.
3. `curl /ops/mesh/runtime-manifest` con token → 200 + manifest.
4. APK build con `./gradlew :app:assembleDebug` → verifica assets/runtime presentes.
5. Android físico (el hardware que tengas a mano): instalar APK, activar Serve pill, notificación muestra LAN URL, `/health` responde.
6. `test_boot_mesh_disabled.py` verde.
7. Desde segundo device (puede ser el propio desktop): `gimo discover --show-runtime` → detecta el device con versión.

---

## 8. Matriz de compliance

### AGENTS.md Plan Quality Standard (9 gates)

| # | Gate | Cumple | Justificación |
|---|---|---|---|
| 1 | Permanence | ✅ | Bundle firmado + manifest canónico es infraestructura de largo plazo, no patch temporal |
| 2 | Completeness | ✅ | Cubre PKG-1/2/3/4 con un productor único y superficies consumer unificadas |
| 3 | Foresight | ✅ | Hardware-agnóstico por diseño; añadir target = añadir fila a la matriz CI |
| 4 | Potency | ✅ | Resuelve el bootstrap seed, el sync peer-to-peer, y cierra el doble camino desktop/móvil a la vez |
| 5 | Innovation | ✅ | No hay proyecto OSS comparable que empaquete un servidor Python firmado + peer upgrade sin cloud — GICS-style |
| 6 | Elegance | ✅ | Reutiliza Ed25519 existente, HMAC mDNS existente, ProcessBuilder existente; sólo añade 1 schema + 1 script + 2 endpoints |
| 7 | Lightness | ✅ | ~10 archivos nuevos/tocados en backend, ~5 en Android, ~2 en docs, 1 CI job extendido |
| 8 | Multiplicity | ✅ | Mismo bundle sirve Android + desktop + Raspberry + futuros targets |
| 9 | Unification | ✅ | Un productor, un schema, un verificador, un endpoint de sync |

### E2E skill gates

| Gate | Cumple |
|---|---|
| Aligned (SYSTEM/CLIENT_SURFACES/SECURITY/AGENTS) | ✅ backend authority, multi-surface parity, Ed25519 reutilizado |
| Honest | ✅ stubs con NotImplementedError; tests que fallan antes de implementar |
| Potent | ✅ resuelve 4 issues con un productor único |
| Minimal | ✅ no creamos `RuntimeBundleManager` paralelo ni nuevo sistema crypto |
| Unified | ✅ todas las superficies convergen |
| Verifiable | ✅ tests contractuales + integración + runtime smoke definido paso a paso |
| Operational | ✅ mesh-off invariant preservada; upgrade flow es opt-in con `ORCH_MESH_RUNTIME_SYNC=true` |
| Durable | ✅ schema extensible (nuevos targets sin cambio de contrato) |

---

## 9. Riesgos residuales

1. **Wheels no disponibles para todos los targets**. `cryptography`, `pydantic-core`, `psutil` tienen wheels pre-built para Linux x86_64 y ARM64, macOS, Windows. Para Android ARM64 se usan recipes p4a o se compila en el runner Android NDK. **Mitigación**: en el MVP acotamos a targets con wheels directos; Android usa p4a recipes conocidos; si un wheel no existe, el script falla con mensaje explícito (no silencioso).

2. **Tamaño del APK aumenta ~13-18 MB (XZ) vs ~45 MB uncompressed**. Con compresión + extracción lazy (Change 2b), el usuario inference-only paga sólo el coste en assets del tarball. La extracción a filesystem sólo ocurre al activar server mode — un device que nunca lo activa nunca descomprime, nunca ocupa los 45 MB uncompressed en `filesDir/`. Si algún día se necesita una APK ultra-liviana (hipótesis: device con memoria muy limitada), follow-up: build variant `noruntime` que omite el tarball y lo descarga on-demand de un peer (requiere Change 8 operativo).

3. **Swap del runtime en Android requiere kill del proceso**. El upgrade no es hot-swap; requiere restart de `MeshAgentService`. MVP: documentado, manual. Follow-up: orchestrator que pausa dispatch, completa upgrade, reanuda.

4. **Primer runtime bootstrap no tiene autoridad**. La primera vez que un device arranca, confía en el APK que instaló. Esto es equivalente a TOFU (trust on first use). **Mitigación**: el APK vino firmado por Play Store / sideload verificado, y el runtime embebido fue firmado en CI con clave de Gred In Labs. Cadena de confianza: Play Store → APK → Ed25519 pública bundled → verificación del runtime. Correcto para MVP.

5. **Upgrade endpoint es vector**. Mitigado en Change 4 pero sigue siendo delicado. Follow-up post-MVP: añadir verificación de fingerprint del peer antes de aceptar upgrade; rate limit por device_id, no sólo por IP.

6. **Calibración de targets en CI**. El primer merge-to-main puede tardar más en CI por la matriz. **Mitigación**: targets no-Linux corren en jobs paralelos; caché de wheels agresiva; Windows/macOS se pueden dropear si no hay runner y se marcan como "supported but not CI-built".

7. **Interacción con el plan RUNTIMES vecino**. Este plan es el productor; el plan vecino (2026-04-15) es el consumer del enum mode×runtime. Orden sugerido: **primero merge este plan** (produce artefacto); después el RUNTIMES (lo consume en el selector). Alternativa: ejecutar ambos en paralelo si hay capacidad — no hay colisión de archivos.

8. **Follow-ups explícitamente fuera de MVP**:
   - Web UI panel "runtime status".
   - Installer Windows MSI que incluya el bundle (hoy: zip o tar).
   - Delta-updates (hoy: payload completo).
   - Rollback UI (hoy: rollback automático al boot fallido, pero sin botón explícito).
   - Federación GICS del aprendizaje de qué targets funcionan mejor.
   - Validación en hardware exótico (frigorífico conectado, NAS Synology, etc.) — cualquier Linux ARM64 con glibc ≥ 2.31 debería funcionar out-of-the-box.

---

## 10. Pausa obligatoria

Siguiendo el protocolo /e2e, el plan queda aquí. **No se inicia Phase 4 sin aprobación explícita.**

Preguntas abiertas que bloquean implementación:

1. **¿Aprobado el alcance de 10 changes tal como está?** ¿Recortamos (ej: diferir Change 8 upgrade flow para un segundo round — el bundle solo ya cierra el bootstrap) o extendemos (ej: meter Windows installer real en el mismo round)?
2. **¿Aprobado python-build-standalone como fuente de CPython?** Alternativa: compilar CPython desde fuentes con NDK para Android y `Python.org` releases para desktop. python-build-standalone es más pragmático (un tarball por target, listo), pero añade una dep externa.
3. **¿Aprobado reutilizar la keypair de licensing para firma del runtime?** Alternativa: generar un keypair dedicado `runtime_signing_key.pem` con su propia rotación. Ventaja: segregación de roles. Desventaja: dos keypairs que gestionar.
4. **¿Matriz CI inicial mínima?** Propuesta: `linux-x86_64`, `linux-arm64`, `android-arm64`. Windows y macOS como follow-up. ¿De acuerdo o querés Windows en el primer cut?
5. **¿Abrimos este plan en un branch aparte o sobre `feature/gimo-mesh`?** La rama actual ya tiene R22 rev 2 merged. Un sub-branch `feature/gimo-mesh-runtime-packaging` sería más limpio; alternativa: seguir en `feature/gimo-mesh` y acumular.

Este plan está listo para aprobar tal como está. Esperando decisión antes de tocar código.
