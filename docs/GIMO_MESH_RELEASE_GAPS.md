# GIMO Mesh — Release Gaps & Frictions

Inventario de lo que debe resolverse antes de shippear el APK del GIMO Mesh como
producto de usuario final. Empezó 2026-04-19 durante la sesión de KISI auto-start
fix + cross-compile llama-server. Cada entrada describe: **qué es**, **por qué
impacta**, y **el fix** propuesto o aplicado.

Ordenado por criticidad descendente dentro de cada sección.

---

## BLOQUEANTES (ship-stoppers)

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

### G3. ABIs no cubiertas: armv7 y x86_64
- **Síntoma**: actualmente solo cross-compilamos arm64-v8a. Devices armv7
  (Samsung Galaxy S8 y anteriores) no pueden arrancar inferencia. Emuladores
  x86_64 tampoco.
- **Fix**: replicar el build para `armeabi-v7a` (API 28) y `x86_64` (API 28).
  La APK multi-ABI incrementará ~45 MB en total.
- **Prioridad**: media — el 70% del parque Android arm64 cubre el uso real;
  armv7 puede quedar como follow-up "legacy support".

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

### G8. Heartbeat scheduler del mesh agent no arranca post-enrollment
- **Síntoma**: server-side `last_heartbeat == enrolled_at` incluso minutos
  después de que el device está en Dashboard y operando. El device no reporta
  métricas al Core.
- **Causa raíz**: no investigada a fondo — el `heartbeatJob` dentro de
  `startMesh()` debería correr cada 30s, pero server no ve las llamadas.
  Posiblemente `heartbeatSecret` blank por `syncLocalDeviceSecret` que
  solo corre en serve mode, no en inference mode.
- **Fix**: auditar `MeshAgentService.heartbeatJob` con `Log.i` para ver si
  corre; si corre pero falla el POST, inspeccionar headers/body.

### G9. Stale device records en el registry del Core
- **Síntoma**: después de múltiples ciclos de enroll, el registry acumula
  13+ `sm-g973f-*` devices en `pending_approval` perpetuo. Se mezclan con
  devices reales y causan ruido.
- **Fix**: ejecutar prune periódico server-side o UI admin en el dashboard
  web para bulk-delete. O auto-prune devices que nunca completan approve en
  N minutos.

---

## FRICCIONES (calidad de vida)

### G10. Compilación debug-not-stripped → APK 156 MB → 16 MB stripped
- **Síntoma**: el binary con `debug_info` ocupa 156 MB. El Gradle packaging
  no stripea `.so` de jniLibs por default en algunos setups.
- **Fix aplicado**: `llvm-strip --strip-all` manual post-build. Automatizar
  en el script de cross-compile o via Gradle task `stripDebugSymbols`.

### G11. Bottom nav no está en el accessibility tree
- **Síntoma**: `mobile_list_elements_on_screen` no reporta los 4 tabs del
  bottom nav. Para un tester automatizado o screen reader, los tabs son
  invisibles.
- **Causa raíz**: los Compose `NavItem` no tienen `contentDescription` ni
  `Modifier.semantics`.
- **Fix**: añadir `Modifier.semantics { role = Role.Tab }` a cada NavItem
  + contentDescription visible.

### G12. KillSwitch long-press mal descubrible
- **Síntoma**: el único feedback durante el hold-2s es un progress ring.
  Sin práctica previa, el user asume que es un botón normal que no responde.
- **Fix**: añadir vibration al onPress + haptic tick al llegar a 50%/100%.
  O reemplazar por slide-to-confirm más estándar.

### G13. Nombre del modelo en dashboard muestra "qwen2.5:3b" (placeholder) hasta primera interacción
- **Síntoma**: tras enrollment, el ModelCard muestra "qwen2.5:3b" (el default
  de `SettingsStore.Settings`) no el nombre real del modelo descargado
  ("qwen2.5-coder_3b_q4_k_m") hasta que el user navega por la app.
- **Causa raíz**: `state.modelLoaded` se queda en el default del settings
  store; el SetupWizard al terminar descarga debería hacer `settingsStore.updateModel`.
- **Fix**: auditar la transición `SetupStep.Downloading` → `Done` en
  SetupWizardScreen para persistir el model id correcto.

### G14. Screenshot del wizard completo excede límite de 2000px
- **Síntoma**: `mobile_take_screenshot` de Claude MCP explotó en la sesión
  anterior (S10 tiene 2280px de alto).
- **Fix** (testing only): usar `mobile_list_elements_on_screen` preferentemente,
  o screenshots post-resize si son necesarios.

### G15. Audit log no captura redeem
- **Síntoma**: `/ops/mesh/audit.jsonl` no tiene entries para
  `/ops/mesh/onboard/redeem`. Imposible auditar quién enroló qué device.
- **Causa raíz**: el handler `redeem_onboard_code` omite la llamada a
  `audit_log(...)`. Es NO-auth por diseño (el código es la credential), pero
  sigue siendo un evento auditable con IP origen y device_id asignado.
- **Fix**: añadir `audit_log("OPS", "/ops/mesh/onboard/redeem", device_id,
  operation="WRITE", actor=f"ip:{client_ip}")`.

### G16. Binarios `busybox` siguen siendo 0-byte placeholder
- **Síntoma**: utility tasks fail. `assets/bin/busybox` = 0 bytes → shell
  sub-resource disabled.
- **Fix**: cross-compile busybox para android-arm64 (mismo toolchain) o
  empaquetar un static build pre-hecho. Menos crítico porque solo afecta
  utility mode, no inference.

### G17. Token de admin vive en `.gimo_credentials` pero `.orch_token` apunta al operator
- **Síntoma**: quien hace debugging via curl con `.orch_token` obtiene 403
  en endpoints admin (ej. `/ops/mesh/onboard/code`) porque es operator token.
- **Fix**: documentar en README la jerarquía, o añadir helper CLI que
  imprima el admin token (con confirmación explícita del user).

---

## DEUDA TÉCNICA (no bloquea pero vale anotar)

### G18. `InferenceRunner.start()` swallowed exceptions en `catch(_: Exception)`
- **Síntoma**: el G1 tardó horas en diagnosticarse porque el catch silenciaba
  la `IOException: error=13`. 
- **Fix aplicado** (temporal, debug): logs con `Log.i/e` + stacktrace. Dejar
  al menos el `Log.e(TAG, "start() failed", e)` en producción.

### G19. Redirect de error stream en InferenceRunner bloqueante
- **Síntoma potencial**: `redirectErrorStream(true)` + nadie lee el
  inputStream → si `--log-disable` falla y llama-server escribe mucho stdout,
  el pipe buffer (64KB) se llena y llama-server se bloquea.
- **Fix**: lanzar una coroutine que drene `inputStream` y la dirija al
  terminalBuffer con `LogSource.INFER`. Adicionalmente: los primeros ~100
  lines son útiles para diagnosticar fallos de modelo.

### G20. Contexto reducido `2048` no diferencia por modelo
- **Síntoma**: `settings.contextSize = 2048` es hardcoded. Modelos de código
  se benefician de 8K+. Modelos chat 4K es suficiente.
- **Fix**: leer context size del manifest del modelo o config server-side
  cuando approve el device.

### G21. No hay rate limiting en taps de START
- **Síntoma potencial**: si el user hace tap frenético, se disparan N
  `ACTION_START_INFERENCE` consecutivos. El primer `stop()` en `InferenceRunner`
  puede matar el process que el segundo intent intenta crear.
- **Fix**: debounce 500ms en el ModelCard onClick, o gate en el service
  que ignore el intent si ya hay una `STARTING` en vuelo.

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

### G22. `SettingsStore.inferenceRunning` persistente no sincroniza al boot
- **Síntoma**: tras relanzar la app (sin mesh running), el ModelCard muestra
  "RUNNING" porque `settings.inferenceRunning=true` quedó persistido del
  último run donde llama-server sí corría. Como el mesh service no está
  activo, nadie corre `watchInferenceStatus` y el flag queda stale — el
  user tap "running" intentando ver el endpoint y dispara `STOP_INFERENCE`
  sin querer.
- **Fix**: al boot de la app (MeshViewModel.init), resetear a false si no
  hay runner vivo, o borrar el flag persistente completamente (es un campo
  derivado de la realidad del runtime, no una preferencia del user).
- **Workaround actual**: clear data o tap mesh para activar el watcher.

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
