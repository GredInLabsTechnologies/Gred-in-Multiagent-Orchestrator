# E2E Engineering Plan — Runtime Cross-Compile (android-arm64 real)

- **Fecha**: 2026-04-16
- **Estado**: APROBADO — en implementación
- **Rama**: `feature/gimo-mesh`
- **Ámbito**: Cerrar el residual risk #1 del plan RUNTIME_PACKAGING — producir bundles reales del Core GIMO para `android-arm64` (y `linux-x86_64` oficial), integrando `python-build-standalone` + wheels nativas.
- **Plan hermano**: `E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING.md` (MVP, DONE 2026-04-16) — este plan reemplaza el "host Python" por una cadena cross-compile real.
- **Motivación**: el runbook S10 del plan `SERVER_MODE_FULL` está bloqueado en Phase 1 ("embedded GIMO Core runtime missing") porque ningún bundle generable hoy es ejecutable en aarch64/Linux-Android. El MVP empaqueta host Python (Windows/Linux x86_64) — incompatible con la ISA del S10.

## 1. Diagnóstico

Evidencia directa (Dashboard S10 tras activar SERVE):

```
LOCAL HOST: UNAVAILABLE
ERROR: embedded GIMO Core runtime missing
LAN: not published
```

Evidencia repo:
- `scripts/package_core_runtime.py::cmd_build` aborta con `SystemExit` si `--target` ≠ host.
- `_bundle_host_python()` copia `sysconfig.prefix` del intérprete actual. Resultado: Python Windows-x86_64 dentro del bundle.
- `_install_wheels()` invoca `pip install --requirement requirements.txt` sin `--platform`. En Windows dev box falla por conflict `fastmcp>=3.1.0` vs `httpx>=0.27.0` en el resolver.
- `.github/workflows/ci.yml` job `runtime-packaging` tiene matrix `android-arm64` pero `package_target: host` — el bundle producido es `linux-x86_64` etiquetado como `android-arm64` (un bug estructural, no solo una limitación).

## 2. Principios

1. **Superficie idéntica en todos los targets** (usuario 2026-04-15): mismo `tools/gimo_server/` en `repo/`, solo varía `python/` nativo y wheels `site-packages/`.
2. **Cross-compile real via standalone**: `python-build-standalone` es la ruta canónica (misma que usa Anthropic/astral-sh). Proyecto maduro, publishes bundles pre-construidos para `aarch64-unknown-linux-gnu`.
3. **Sin compilar C local**: `pip install --platform ... --only-binary=:all:` — descarga wheels pre-compiladas de PyPI. Aborto duro si una dep no tiene wheel aarch64.
4. **Opt-in backward compatible**: por default `--python-source=host` (comportamiento actual). Nuevo `--python-source=standalone` para cross-compile. El MVP DONE sigue funcionando.
5. **Resolver tolerante a drift**: el productor documenta que `linux-aarch64` glibc ≠ Android Bionic. El bundle corre en Termux/proot hoy; el follow-up Chaquopy (para Android stock nativo) queda fuera de scope.
6. **Trusted pubkey embedded** (finalización Cambio 5 del plan PACKAGING): una sola `EMBEDDED_RUNTIME_PUBLIC_KEY` constante en el código; Android valida firma antes de extraer.

## 3. Lista de cambios

### Change 1 — Fetcher `python-build-standalone` en productor

- **Qué**: nuevos helpers `_fetch_standalone_python(target, python_version)` + catálogo de URLs astral-sh canónicas por target. Cache local en `~/.cache/gimo/runtime-python/`.
- **Dónde**: `scripts/package_core_runtime.py` — nueva función ~80 LOC.
- **Targets soportados**: `android_arm64` → `cpython-3.13.x+aarch64-unknown-linux-gnu-install_only.tar.gz`; `linux_x86_64` → `x86_64-unknown-linux-gnu`; `linux_arm64` idem; `darwin_arm64` → `aarch64-apple-darwin`; `windows_x86_64` → `x86_64-pc-windows-msvc-shared`.
- **Verificación**: sha256 contra el `.sha256` del release asset.

### Change 2 — `pip install --platform` para wheels nativas

- **Qué**: `_install_wheels_cross(site_packages, pip_platform, python_version, requirements)` invoca `pip install --platform={tag} --only-binary=:all: --python-version={ver} --target=... -r requirements.txt`. Default del `--python-source=host` sigue siendo el behavior actual.
- **Dónde**: `scripts/package_core_runtime.py` — extensión `_install_wheels` + nuevo helper.
- **Platform tags**: `android_arm64` → `manylinux2014_aarch64`; `linux_x86_64` → `manylinux2014_x86_64`; etc.
- **Beneficio lateral**: el resolver de PyPI con platform tag explícito a menudo resuelve donde el resolver de host falla — esquivando el conflicto `fastmcp vs httpx` en Windows dev box.

### Change 3 — CI matrix actualizada: cross-compile real android-arm64

- **Qué**: `runtime-packaging` job matrix:
  - `android-arm64` → ubuntu-latest + `--python-source standalone --pip-platform manylinux2014_aarch64` → bundle real aarch64
  - `linux-x86_64` → ubuntu-latest + `--python-source host` → bundle real (sirve desktop Linux)
  - `windows-x86_64` → windows-latest + `--python-source host` → bundle real (sirve desktop Windows)
  - `darwin-arm64` → macos-14 + `--python-source host` → bundle real (sirve desktop macOS M-series)
- **Dónde**: `.github/workflows/ci.yml`.
- **Artifact naming**: `gimo-core-runtime-{target}` tras upload. El consumer Android baja el asset `android-arm64`.

### Change 4 — Android gradle: `fetchRuntimeBundle` opcional

- **Qué**: nueva tarea `:app:fetchRuntimeBundle` que, si `runtime-assets/` está vacío o si `GIMO_RUNTIME_BUNDLE_URL` env var está set, descarga los 3 artefactos (`.json`, `.tar.xz`, `.sig`) del release asset CI. `packageCoreRuntime` existente no cambia. `mergeAssets` depende primero de `fetchRuntimeBundle`, luego de `packageCoreRuntime`.
- **Dónde**: `apps/android/gimomesh/app/build.gradle.kts`.
- **Fallback de error**: si no hay bundle local ni URL, el mensaje de `packageCoreRuntime` sigue dirigiendo al operator a correr el productor local — no regresión.

### Change 5 — Trusted pubkey embedded

- **Qué**: constante `EMBEDDED_RUNTIME_PUBLIC_KEY` en `tools/gimo_server/security/runtime_signature.py` pasa de string vacío a la clave pública del keypair productivo. Android copia `runtime-assets/trusted-pubkey.pem` a `src/main/assets/runtime/trusted-pubkey.pem` via el gradle task; `ShellEnvironment` lo lee y pasa a `runtime_bootstrap.ensure_extracted(public_key_pem=...)` para validar firma **antes** de extraer.
- **Dónde**:
  - `tools/gimo_server/security/runtime_signature.py` — valor `EMBEDDED_RUNTIME_PUBLIC_KEY`.
  - `scripts/generate_runtime_keys.py` (nuevo, 40 LOC) — helper para generar keypair inicial y printear el PEM público.
  - `apps/android/gimomesh/app/build.gradle.kts` — copiar `trusted-pubkey.pem` a assets.
  - `apps/android/gimomesh/.../ShellEnvironment.kt` — leer `assets/runtime/trusted-pubkey.pem`.
- **Nota**: Android validator Kotlin pattern se mantiene mínimo — el MVP no verifica firma en Kotlin; lo hace Python en runtime_bootstrap cuando se recibe pubkey. El Change 5 meramente provee la pubkey al bootstrap. Android firma-ante-de-extraer queda como follow-up low-pri.

### Change 6 — Tests

- **Nuevo**: `tests/unit/test_runtime_cross_compile.py` (40 LOC) — valida mapeo target→URL, target→platform tag, y el argparse de los nuevos flags.
- **Actualizado**: `tests/unit/test_ci_runtime_matrix.py` — añade aserciones para `package_target: standalone` en `android-arm64`, presencia de targets `linux-x86_64` y `darwin-arm64`.
- **Actualizado**: `tests/unit/test_android_gradle_runtime_wiring.py` — valida `fetchRuntimeBundle` task + copia de `trusted-pubkey.pem`.
- **Nuevo**: `tests/unit/test_embedded_pubkey.py` — verifica que `EMBEDDED_RUNTIME_PUBLIC_KEY` no esté vacío (o lo esté con warning) y que `get_runtime_public_key_pem()` devuelva algo parseable.

### Change 7 — Documentación

- **Actualizado**: `docs/DEV_MESH_ARCHITECTURE.md` §2.4 "Runtime Packaging" — cerrar la sección de "residual risks → cross-compile follow-up" ahora que el plan la cubre.
- **Actualizado**: `docs/MESH_SERVER_RUNBOOK.md` — referencia rápida al CI artifact para instalar Android.
- **Nuevo**: sección "Bionic vs glibc" documentando que el MVP requiere Termux/proot para ejecutar en Android stock; Chaquopy queda como follow-up.

## 4. Orden de ejecución

1. Change 1 + 2 (fetcher + pip platform) — bloque coherente en el productor.
2. Change 6 test nuevo `test_runtime_cross_compile.py` (red → green).
3. Change 3 (CI matrix actualizada).
4. Change 6 actualizado `test_ci_runtime_matrix.py` (los tests existentes siguen verdes + nuevas aserciones verdes).
5. Change 5 (pubkey) — mínimo invasivo, solo añade una constante y propaga.
6. Change 4 (gradle fetch) — depende del pubkey estar en `runtime-assets/` como output del productor.
7. Change 6 actualizado `test_android_gradle_runtime_wiring.py`.
8. Change 7 (docs).
9. Smoke local: producir bundle `linux-x86_64` (fácil) + bundle `android-arm64` (si la red permite download de python-build-standalone).
10. Update integrity manifest para `package_core_runtime.py` y `main.py` si tocamos.

## 5. Unification check

| Superficie | Cómo consume el cambio |
|---|---|
| CI | Genera 4 bundles firmados por target. Upload artifact por cada uno. |
| Android APK | Dev: productor local; Release: `fetchRuntimeBundle` baja del CI artifact. |
| Desktop (Win/macOS/Linux) | `gimo_cli/commands/runtime.py upgrade` baja del peer vía HTTP + verifica firma. Sin cambios. |
| MCP bridge | No cambia — `/ops/mesh/runtime-{manifest,payload}` sirve el mismo bundle. |
| Web UI | Sin cambios — ve el mismo `/ops/mesh/host` con `runtime_version` actualizado. |

## 6. Verificación

- Unit: `test_runtime_cross_compile.py` (nuevo) + `test_ci_runtime_matrix.py` (actualizado) + `test_android_gradle_runtime_wiring.py` (actualizado).
- Smoke local (Windows dev box, disponible): build `--target linux-x86_64 --python-source standalone --pip-platform manylinux2014_x86_64` debe producir bundle `.tar.xz` verificable.
- Smoke CI: workflow completo pasa en los 4 targets.
- Broad regression: `pytest tests/unit -m "not integration" -q` debe seguir verde (1743+ tests).

## 7. Riesgos residuales

1. **Bionic vs glibc en Android stock**: el bundle aarch64-glibc no corre en Android stock sin Termux/proot/chroot. Documentado; Chaquopy es follow-up.
2. **`python-build-standalone` versión drift**: URL hardcodeada por versión. Si astral-sh rota URLs (poco probable — son tags estables), el fetcher falla con mensaje accionable.
3. **Wheels no-disponibles**: si una dep crítica (`fastmcp`, `cryptography`) deja de publicar wheel aarch64 en una versión futura, `pip install --only-binary=:all:` aborta. Mitigación: pin específicos en requirements.txt + CI detection.
4. **Tamaño del bundle aarch64**: python-build-standalone completo puede ser 30-40 MiB vs 13 MiB del MVP Windows. Aceptable.
5. **Keypair productivo rotativo**: la constante embedded es inmutable por build. Rotación = nuevo release del Core. Está OK para MVP.

## 8. Out of scope

- Chaquopy (Python nativo Android Bionic) — follow-up plan separado.
- Termux launcher adapter (app que hace el bridge S10 stock → Termux) — fuera.
- Firma-antes-de-extraer en Kotlin (ShellEnvironment verifica pubkey antes de copiar assets) — follow-up low-pri; Python runtime_bootstrap ya valida.
- Download on-demand del bundle desde la app Android en tiempo de uso (vs empaquetado en APK) — plan aparte.

## 9. Compliance

| Gate | Respuesta |
|---|---|
| Aligned (AGENTS/SYSTEM/CLIENT_SURFACES/SECURITY) | YES — backend authority, multi-surface parity, firma antes de extraer. |
| Honest | YES — Bionic limitation documentada; aborto duro si wheel falta. |
| Potent | YES — desbloquea S10 runbook + Pekín server. |
| Minimal | YES — 1 script (~100 LOC), 1 YAML (~40 LOC), 1 gradle task (~30 LOC), 4 tests. |
| Unified | YES — misma productora sirve a Android, Linux, macOS, Windows. |
| Verifiable | YES — smoke local Windows + CI 4 targets + tests estáticos. |
| Operational | YES — fallback a host si standalone no disponible. |
| Durable | YES — `python-build-standalone` es infra externa canónica, firma Ed25519 estable. |
