# GIMO Mesh — Release Gaps & Frictions

> **2026-04-20 sprint close**: 19 gaps fixed, 3 no-bug, **G27 declared
> blocker for server mode**. Ver `docs/audits/GIMO_MESH_SPRINT_2026-04-20.md`
> para el changelog consolidado.



Inventario de lo que debe resolverse antes de shippear el APK del GIMO Mesh como
producto de usuario final. Empezó 2026-04-19 durante la sesión de KISI auto-start
fix + cross-compile llama-server. Cada entrada describe: **qué es**, **por qué
impacta**, y **el fix** propuesto o aplicado.

Ordenado por criticidad descendente dentro de cada sección.

---

## BLOQUEANTES (ship-stoppers)

### G27. Server mode bloqueado: python-build-standalone no corre en Android bionic — **ACTIVE BLOCKER**
- **Descubierto**: 2026-04-20. Tras rebuild del bundle rove con `--python-source=standalone`
  (74 MB comprimido, 718 MB descomprimido, incluye CPython + wheels + repo tree),
  el binario Python embedido es **glibc-linked for GNU/Linux**, no bionic.
- **Evidencia**:
  ```
  $ file python3.13
  → ELF 64-bit LSB pie executable, ARM aarch64, ...,
    interpreter /lib/ld-linux-aarch64.so.1, for GNU/Linux 3.7.0
  ```
  Android usa bionic libc con dynamic linker en `/system/bin/linker64`.
  El `execve` del kernel falla con **"No such file or directory"** (engañoso:
  el binary sí está, pero su interpreter declarado no existe en Android).
- **Implicación**: server mode on-APK-standalone **no funciona hoy**. El diseño
  (rove bundle → ShellEnvironment extrae tar.xz → EmbeddedCoreRunner arranca
  Python + uvicorn) está completo en código pero bloqueado por el origen del
  binario Python.
- **Infraestructura lista para el fix** (committed pero inactiva):
  - `ShellEnvironment.extractTarXz()` con commons-compress + tukaani-xz
    (descomprime el bundle full-size correctamente).
  - `ShellEnvironment.prepareEmbeddedCoreRuntime()` actualizado para usar
    `extracted/` tree en vez de solo copiar el tarball.
  - `app/build.gradle.kts` con deps `org.apache.commons:commons-compress:1.26.2`
    + `org.tukaani:xz:1.9`.
- **Opciones de fix** (ordenadas por costo / feasibilidad):
  1. **Termux path** (1–2 días): requerir Termux (app con Python bionic nativo);
     escribir bootstrap que cargue el wheelhouse del APK. Rompe "zero-ADB setup"
     pero es straightforward. Uso: `pkg install python && python -m pip install
     --no-index --find-links=/path/wheelhouse fastapi uvicorn && python -m uvicorn
     tools.gimo_server.main:app`.
  2. **Chaquopy** (licencia comercial): Python embedded for Android, bionic-native.
     Integración Gradle oficial. Requiere decisión comercial.
  3. **python-for-android** (1–2 semanas): pipeline de Kivy para producir APKs
     con Python bionic. Requiere build infra Linux dedicada.
  4. **Cross-compile CPython con NDK from source** (1+ mes): custom toolchain,
     mucho trabajo propio pero zero deps externas.
  5. **Rewrite Core en Kotlin/Go/Rust** (meses): scope masivo, abandona Python
     como estándar del Core.
- **Decisión pendiente**: requiere input de producto sobre aceptabilidad de
  Termux-dep (rompe experiencia "single-APK") vs gasto de Chaquopy vs plazo
  de python-for-android.
- **Mitigación actual**: server mode queda como "arquitectura definida,
  implementación pending blocker G27" hasta que se elija camino.

### G1. Binarios nativos con `Permission denied` desde ProcessBuilder (Android 10+)
- **Síntoma**: `java.io.IOException: error=13, Permission denied` al invocar
  `ProcessBuilder.start()` desde `InferenceRunner` y `ShellEnvironment.exec`.
- **Causa raíz**: desde Android 10, SELinux bloquea `execve` de archivos en
  `/data/data/<pkg>/files/` cuando el contexto del caller es `untrusted_app`.
  El bit `+x` del filesystem no es suficiente; hace falta que el binario viva
  en un label permitido (`system_lib_file` / `nativeLibraryDir`).
- **Evidencia**: stacktrace en logcat tag `InferenceRunner` cuando el tap de
  START en ModelCard dispara `requestStartInferenceNow` en el servicio. El
  mismo binario ejecuta bien vía `adb shell run-as <pkg> ...` porque `run-as`
  transiciona al contexto `shell`.
- **Fix**: mover `llama-server` (y `busybox` a futuro) a
  `app/src/main/jniLibs/arm64-v8a/libllama-server.so` (y análogos). Android
  los extrae automáticamente a `applicationInfo.nativeLibraryDir`, que está
  labeled como sistema y permite `execve`. Requiere:
  - Renombrar binario con prefijo `lib` y sufijo `.so` para que el packager
    lo reconozca.
  - `ShellEnvironment.initInference()`: resolver path desde `nativeLibraryDir`
    en vez de extraer desde assets.
  - Gradle: revisar `android.packagingOptions.jniLibs` para garantizar no
    strip innecesario y ABI splits si se añaden más.
- **Estado**: fix pendiente de aplicar (esta sesión).

### G2. llama-server binary ausente en el APK pre-2026-04-19
- **Síntoma**: `assets/bin/llama-server` y `assets/bin/busybox` tenían 0 bytes
  en main; `ShellEnvironment.isInferenceReady` siempre false.
- **Causa raíz**: el cross-compile nunca se integró al flujo de build. La
  memoria documentaba "requiere WSL/Linux" como follow-up.
- **Fix**: cross-compile desde NDK 27.2 con cmake de Android Studio en Windows.
  Comando canónico (android-arm64 API 28):
  ```bash
  cmake -B build-android -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
    -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-28 \
    -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF \
    -DGGML_BACKEND_DL=OFF -DGGML_OPENMP=OFF -DBUILD_SHARED_LIBS=OFF
  cmake --build build-android --target llama-server -j 6
  $NDK/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-strip.exe --strip-all bin/llama-server
  ```
  Binary resultante: 16 MB stripped. Validado en Samsung Galaxy S10 (Exynos
  9820) contra `qwen2.5-coder_3b_q4_k_m.gguf` — responde /health, /v1/models,
  y genera código de calculadora Python coherente en ~165 tokens.
- **Estado**: binary compilado y puesto en `assets/bin/`. Después de G1, irá
  a `jniLibs/arm64-v8a/`.

### G3. ~~ABIs no cubiertas: armv7 y x86_64~~ — **x86_64 FIXED 2026-04-20, armv7 deferred**
- **Fix aplicado (x86_64)**: cross-compilado llama-server para x86_64 API
  28 con NDK 27.2 + cmake + ninja. Binary stripped: 17 MB. Empaquetado
  en `jniLibs/x86_64/libllama-server.so`. APK pasó de 93 MB a 102 MB.
  Emulator Android 16 API 36 ahora puede arrancar inferencia nativa.
  busybox no se empaqueta en x86_64 (no hay binary EXALAB válido), pero
  el emulator tiene toybox en `/system/bin/` que cubre los applets que
  necesitamos — `ShellEnvironment.buildEnvironment()` ya prioriza
  `/system/bin` en PATH, así que utility shell_exec funciona sin cambios.
- **armv7 diferido**: el 70% del parque Android es arm64 en 2026. S8 y
  anteriores quedarán sin inferencia local — pueden seguir siendo
  utility nodes vía toybox del sistema.

---

## IMPORTANTES (afectan UX pero no bloquean)

### G4. NavGraph nav-initial race: Dashboard persistido → Setup falso
- **Síntoma**: tras `pm clear` o reinstall con data existente, la app abría
  Welcome aunque el DataStore tuviera token, deviceId, y modelo descargado.
- **Causa raíz**: `collectAsState(initial = SettingsStore.Settings())` emite
  defaults blank en el primer render; `needsSetup` se evaluaba sobre ese
  blank y `rememberSaveable` cristalizaba `Screen.SETUP` antes de que llegara
  la primera emisión real. El `LaunchedEffect(needsSetup)` solo movía a SETUP,
  nunca a DASH.
- **Fix aplicado** (2026-04-19, commit 6a78178): `LaunchedEffect` bidireccional
  — también flechá a DASH cuando needsSetup pasa a false desde SETUP.

### G5. Badge clickable con hit-area del glyph (no del visual)
- **Síntoma**: taps en el borde del Badge ("TAP TO START") no registraban.
  El user tenía que tap el texto exacto.
- **Causa raíz**: `Modifier.clickable` aplicado antes de `.clip`/`.background`/
  `.padding` en el Badge; hit-area = Text node, no el clip+border+padding.
- **Fix aplicado** (2026-04-19, commit 6a78178): `Badge` acepta `onClick`
  como parameter y aplica `clickable` AL FINAL del modifier chain. Hit-area =
  visual completo.

### G6. Auto-start de inferencia sin consent humano
- **Síntoma**: device enrolado → modelo descargado → llama-server arrancaba
  SIN intervención del user en el phone. Viola "Device health > task
  completion, human opt-in".
- **Fix aplicado** (2026-04-19, commit 6a78178): eliminado auto-start del
  `syncInferenceRuntime`. Tap humano explícito o toggle "Auto-start when safe"
  (default OFF). Hardware gate (battery, CPU temp, RAM, thermal) en ambos
  caminos. Ver `InferenceSafety.kt`.

### G7. Redeem de código se disparaba dos veces
- **Síntoma**: re-render del OTP input cancelaba la coroutine del primer
  POST /ops/mesh/onboard/redeem y relanzaba; segundo redeem fallaba con 403
  "already used", UI rebotaba a ManualCode aunque el device ya estaba enrolado.
- **Fix aplicado** (2026-04-19, commit 3a5ee4d): `LaunchedEffect(step)` en
  vez de `LaunchedEffect(step, code, coreUrl)` — redeem se dispara exactamente
  una vez al entrar en Enrolling.

### G8. ~~Heartbeat scheduler del mesh agent no arranca post-enrollment~~ — **NO ES BUG**
- **Re-evaluación (2026-04-20)**: investigado a fondo. El `heartbeatJob`
  corre correctamente una vez que el mesh service está activo (verificado
  en el último run de la suite utility 10/10). El síntoma original —
  "server-side last_heartbeat == enrolled_at" post-setup — tiene otra causa:
  el mesh service **NO arranca automáticamente al terminar el wizard**.
  El wizard removió el `onStartMesh()` intencionalmente (ver
  SetupWizardScreen.kt:377-378: "Mesh starts OFF — user activates from
  Dashboard, or Core requests it"). Es la misma filosofía KISI aplicada
  a inferencia: human opt-in explícito (long-press START MESH NODE).
- **No-fix aplicado**: conservar el diseño. El heartbeat empieza cuando
  el humano activa el mesh. Es coherente con G6 (inferencia opt-in).

### G9. ~~Stale device records en el registry del Core~~ — **FIXED 2026-04-20**
- **Síntoma**: después de múltiples ciclos de enroll, el registry acumulaba
  13+ `sm-g973f-*` devices en `pending_approval` perpetuo. En la suite run
  de utility mode, el overhead de iterar 15+ devices stale causó que el T1
  tardara 188s en asignarse (pasando el timeout del script por 8s).
- **Fix aplicado**: nuevo `_mesh_prune_stale_loop(app)` en `main.py` que corre
  cada 1 hora y hace `registry.prune_stale_devices(delete_after_seconds=7d)`.
  Threshold configurable via `MESH_PRUNE_DAYS` env var. Primer pass a los
  5 min post-startup para no colisionar con boot overhead. Registrado en
  el lifespan startup y en el shutdown task list.

---

## FRICCIONES (calidad de vida)

### G10. ~~Compilación debug-not-stripped~~ — **FIXED 2026-04-20**
- **Fix aplicado**: `scripts/build_gimomesh_natives.sh` orquesta
  cmake + ninja + strip para todas las ABIs definidas en `ABIS`
  (default `arm64-v8a x86_64`). Uso:
  ```
  NDK=/path/to/ndk ./scripts/build_gimomesh_natives.sh
  ```
  Re-runnable, idempotente por ABI. Detecta host (windows-x86_64,
  linux-x86_64, darwin-arm64) y usa el `llvm-strip` adecuado. Placea
  el binary stripped en `jniLibs/<abi>/libllama-server.so`.

### G11. ~~Bottom nav no está en el accessibility tree~~ — **FIXED 2026-04-20**
- **Fix aplicado**: `NavItem` ahora lleva `Modifier.semantics(mergeDescendants=true)`
  con `role=Tab`, `selected` y `contentDescription="$label tab (selected)"`.
  TalkBack + automated test tools walking the semantics tree ahora ven los
  4 tabs (DASH/TERM/AGENT/CONFIG).

### G12. ~~KillSwitch long-press mal descubrible~~ — **FIXED 2026-04-20**
- **Fix aplicado**: `KillSwitch` ahora hace `HapticFeedbackType.LongPress`
  en `onPress` (reconocimiento inmediato: "tu toque fue detectado") y
  otro al `onLongPress` (confirmación: "hoy cruzaste el umbral"). El user
  ya no lo confunde con un botón que no responde.

### G13. ~~Model name placeholder en dashboard~~ — **FIXED 2026-04-20**
- **Análisis**: el wizard ya hacía `settingsStore.updateModel(model.modelId)`
  al terminar el download (SetupWizardScreen.kt:372). El bug estaba en
  `MeshViewModel.observeSettings`: el `modelLoaded = state.modelLoaded.ifBlank { settings.model }`
  congelaba el default placeholder la primera vez y nunca recogía updates
  posteriores del DataStore.
- **Fix aplicado**: remover el `.ifBlank` — `settings.model` es la fuente
  de verdad y el observer recoge los updates en cada emit. Updates
  autoritativas del server (via `applyAuthoritativeDeviceState`) layer on
  top cuando llegan. Dashboard ahora muestra el nombre real del modelo
  descargado desde el primer render post-wizard.

### G14. Screenshot del wizard completo excede límite de 2000px
- **Síntoma**: `mobile_take_screenshot` de Claude MCP explotó en la sesión
  anterior (S10 tiene 2280px de alto).
- **Fix** (testing only): usar `mobile_list_elements_on_screen` preferentemente,
  o screenshots post-resize si son necesarios.

### G15. ~~Audit log no captura redeem~~ — **ALREADY FIXED**
- **Re-inspección (2026-04-20)**: `mesh_router.py:1115` ya emite
  `audit_log("OPS", "/ops/mesh/onboard/redeem", f"device={body.device_id}
  workspace={result.workspace_id}", operation="WRITE",
  actor=f"onboard:{body.device_id}")`. El gap estaba desactualizado —
  fue arreglado en alguna sesión previa, nunca taché la entrada.

### G16. Binarios `busybox` siguen siendo 0-byte placeholder
- **Síntoma**: utility tasks fail. `assets/bin/busybox` = 0 bytes → shell
  sub-resource disabled.
- **Fix**: cross-compile busybox para android-arm64 (mismo toolchain) o
  empaquetar un static build pre-hecho. Menos crítico porque solo afecta
  utility mode, no inference.

### G17. ~~Token hierarchy no documentada~~ — **FIXED 2026-04-20**
- **Fix aplicado**: nueva sección "Jerarquía de tokens (auth)" en
  `README.md` con una tabla admin/operator/actions, el one-liner para
  extraer el admin token de `.gimo_credentials`, y un recordatorio de
  que `.orch_token` root es operator (no admin). Incluye heads-up sobre
  el 403 típico cuando se usa el token erróneo.

---

## DEUDA TÉCNICA (no bloquea pero vale anotar)

### G18. `InferenceRunner.start()` swallowed exceptions en `catch(_: Exception)`
- **Síntoma**: el G1 tardó horas en diagnosticarse porque el catch silenciaba
  la `IOException: error=13`. 
- **Fix aplicado** (temporal, debug): logs con `Log.i/e` + stacktrace. Dejar
  al menos el `Log.e(TAG, "start() failed", e)` en producción.

### G19. ~~Redirect error stream bloqueante~~ — **FIXED 2026-04-20**
- **Fix aplicado**: nuevo `startOutputDrain(process)` en `InferenceRunner`
  que lanza un `outputDrainJob` en `runnerScope` (Dispatchers.IO) que
  itera `BufferedReader.readLine()` hasta EOF. Las primeras 100 líneas
  van a logcat con tag `InferenceRunner: llama-server:` para diagnóstico
  de carga de modelo; el resto se drena silenciosamente. `stop()` cancela
  el drain job. El viejo `readOutput` queda como no-op stub para compat.

### G20. ~~Context size 2048 hardcoded~~ — **FIXED 2026-04-20**
- **Fix aplicado**: `MeshAgentService.resolveContextSize(settings)` con
  heurística por nombre de modelo: `coder`/`code` → 8192 (code models
  se benefician de contexto grande), `7b`/`8b` → 4096 (modelos medios),
  else → `settings.contextSize` (power users pueden sobrescribir).
  Aplicado en ambos paths de start: auto-start en `syncInferenceRuntime`
  y user-triggered en `requestStartInferenceNow`.

### G21. ~~No rate limiting en taps de START~~ — **FIXED 2026-04-20**
- **Fix aplicado**: `MeshAgentService.requestStartInferenceNow` ahora
  hace early-return si `InferenceRunner.status.value == STARTING`. Taps
  frenéticos no re-disparan el stop() que mataría el process en plena
  carga — el segundo intent encuentra "already starting" y se ignora.
  El status RUNNING ya tenía guard explícito desde antes.

### G23. ~~Recovery from `thermal_lockout` no transiciona~~ — **FIXED 2026-04-20**
- **Fix aplicado**: `MeshRegistry.process_heartbeat` reordenado. Thermal
  lockout es ahora una rama que toma precedencia; si el heartbeat trae
  `thermal_locked_out=false`, el auto-transition a `connected` se dispara
  incluyendo el estado `thermal_lockout` entre los que pueden recuperarse.
  Además, al salir de lockout, `operational_state` vuelve de `locked_out`
  a `idle`.
- **Validado E2E 2026-04-20** en emulador API 36 (4 pasos, 4/4 PASS):
  inject lockout → state=thermal_lockout → dispatch filtra → cooldown
  heartbeat → state=connected → task post-recovery completada.

### G23 (legacy description below, kept for history)
- **Síntoma**: cuando el device envía heartbeat con `thermal_locked_out=true`,
  el Core marca `connection_state=thermal_lockout` correctamente (thermal gate
  del dispatcher activo — validado). Pero cuando después manda heartbeat con
  `thermal_locked_out=false`, el campo `thermal_locked_out` server-side se
  actualiza a `False` pero `connection_state` queda stuck en `thermal_lockout`.
  Tasks nuevas NO se le asignan al device aunque esté sano de nuevo.
- **Causa raíz**: probablemente falta transición en
  `MeshRegistry.process_heartbeat` que haga `connection_state=connected`
  cuando el thermal anterior se despeja.
- **Impacto**: un device que tuvo un pico de temperatura queda
  permanentemente excluido del pool hasta enroll fresh. Inaceptable en prod.
- **Descubierto**: 2026-04-20 durante el thermal test en emulador API 36.
  Valida el dispatch gate (entrada a lockout PASS) pero el recovery falla.

### G24. ~~`mesh_heartbeat_timeout_loop` no marca devices offline~~ — **NO ES BUG**
- **Re-evaluación (2026-04-20)**: el loop sí funciona. El threshold es
  90s pero el loop itera cada 15s, entonces la ventana efectiva es
  90-105s. Mi test original chequeó a 95s, justo antes del siguiente tick.
  Verificado a t=599s: S10 correctamente marcado `offline`.
- **Recomendación opcional**: bajar el sleep del loop a 5s si el caso de
  uso exige reacción más rápida; pero 15s es razonable y no costoso.

### G25. ~~UX: dashboard no muestra qué está haciendo la app~~ — **FIXED 2026-04-20**
- **Fix aplicado**: `MeshState.lastActivity` property computed que lee
  el tail de `terminalLines`, formateado como `{source}: {message}`.
  El DashboardScreen renderiza esa string como una línea fina bajo el
  StatusStrip (fuente GimoMono 8sp, ellipsis si es muy larga). Empty
  cuando el mesh está off.

### G26. ~~URL Core no auto-completa en emulador~~ — **FIXED 2026-04-20**
- **Fix aplicado**: helper `isAndroidEmulator()` que mira
  `Build.FINGERPRINT`/`HARDWARE`/`PRODUCT`/`MODEL`. Si el device es
  emulador, `initialCoreUrl` se pre-populate con `http://10.0.2.2:9325`
  (convención emu → host loopback). Real hardware sigue dependiendo de
  mDNS o settings persistidos.

### G22b. busybox invocation via `libbusybox.so` fails with "applet not found"
- **Síntoma**: cuando el binary se invoca desde `nativeLibraryDir/libbusybox.so`,
  argv[0]="libbusybox.so" y busybox interpreta el basename como applet name
  ("libbusybox.so" no es applet → error). El bootstrapping de symlinks via
  `busybox ln -sf ...` fallaba por esto.
- **Fix aplicado**: `ShellEnvironment.ensureBusyboxLink` usa `Files.createSymbolicLink`
  (Java NIO) directamente, evitando el bootstrapping via busybox. Cada symlink
  en `binDir/<applet>` tiene basename válido → argv[0] resuelve applet.

### G22c. Binary busybox "GNU/Linux" static binary funciona en Android arm64
- **Observación**: EXALAB/Busybox-static binary (labeled "for GNU/Linux 3.7.0")
  ejecuta correctamente en Android 15 arm64 porque está statically linked y no
  depende de libc bionic.
- **Implicación**: para producción conviene cross-compile con NDK bionic + static
  (evitar dependencia de binaries terceros). Pendiente.

### G22. ~~`SettingsStore.inferenceRunning` persistente no sincroniza al boot~~ — **FIXED 2026-04-20**
- **Síntoma**: tras relanzar la app (sin mesh running), el ModelCard mostraba
  "RUNNING" porque `settings.inferenceRunning=true` quedaba persistido del
  último run. Como el mesh service no estaba activo, nadie corría
  `watchInferenceStatus` y el flag quedaba stale — el user tapea "running"
  intentando ver el endpoint y disparaba `STOP_INFERENCE` sin querer.
- **Fix aplicado**: `MeshViewModel.init {}` ahora resetea
  `inferenceRunning=false` Y `meshServiceRunning=false` al boot. Son
  campos runtime-derived, no preferences — su persistencia no sobrevive
  al process kill del JVM. Si el service SÍ está vivo (edge case: app
  went background sin process kill), `watchInferenceStatus` + la
  observer loop re-asertan el valor correcto en el próximo tick.

---

## OBSERVACIONES POSITIVAS

- El flujo mDNS auto-discovery funciona first-try en LAN.
- F-11 fix (redeem-once) valido E2E.
- KISI auto-start gate respetó todos sus invariantes en todas las corridas
  de test (reboot/relaunch/reinstall → siempre OFF, tap humano único trigger).
- El GGUF download stream sobre LAN es rápido (~30 MB/s) y resumible.
- La UI del dashboard es expresiva y los estados (stopped/running/deferred)
  son distinguibles.
- Hardware gate (battery >30%, CPU <50°C, RAM <85%) es conservador y
  observable sin sorpresas.

---

## PRIORIZACIÓN PARA RELEASE

**Sprint 1 (ship-blockers)**: G1, G2, G3
**Sprint 2 (UX essentials)**: G8, G12, G13
**Sprint 3 (ops hardening)**: G9, G15, G17
**Post-release**: G10, G11, G14, G16, G18-G21
