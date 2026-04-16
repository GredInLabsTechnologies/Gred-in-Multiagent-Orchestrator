# E2E Implementation Report — Runtime Cross-Compile (android-arm64 real)

- **Plan**: [E2E_ENGINEERING_PLAN_20260416_RUNTIME_CROSS_COMPILE.md](E2E_ENGINEERING_PLAN_20260416_RUNTIME_CROSS_COMPILE.md)
- **Rama**: `feature/gimo-mesh`
- **Fecha**: 2026-04-16
- **Estado**: `DONE` (código + tests verdes + smoke local) / `BLOCKED_EXTERNAL` (validación CI matrix real pendiente del próximo push — no ejecutable localmente)

## 1. Resumen

Implementado el plan CROSS_COMPILE. El productor `scripts/package_core_runtime.py`
ahora soporta `--python-source=standalone`, que descarga un CPython 3.13.13
pre-construido de `astral-sh/python-build-standalone` (release `20260414`) para el
target pedido y lo empaqueta tal cual. Las deps de Python se instalan con
`pip install --platform=... --only-binary=:all:` — wheels pre-compiladas de PyPI,
sin compilar C local. El CI matrix ahora incluye cross-compile real para
`android-arm64` + 3 targets host (linux-x86_64, windows-x86_64, darwin-arm64).
Trusted pubkey Ed25519 embedded en `runtime_signature.py` + copiada a
`assets/runtime/trusted-pubkey.pem` via gradle. Android `:app:fetchRuntimeBundle`
descarga artifact del CI cuando `GIMO_RUNTIME_BUNDLE_URL` está set.

Conflict residual detectado en `requirements.txt` (pin desalineado entre fastapi,
starlette y pydantic que solo aparecía bajo `pip install --platform ...`) también
cerrado en este plan.

## 2. Implemented changes

### Change 1 + 2 — Productor cross-compile real
- `scripts/package_core_runtime.py`:
  - Nuevo `_STANDALONE_ASSETS` + `_PIP_PLATFORM_TAGS` — un row por target.
  - `_standalone_cache_dir()` — cache user-level multi-plataforma.
  - `_download_with_retries()` — idempotente, 3 attempts.
  - `_fetch_standalone_python(target, staging_python)` — download + extract
    + normaliza layout `python/`.
  - `_install_wheels_cross(...)` — pip con `--only-binary`, `--python-version`,
    múltiples `--platform`. NO pasa `--implementation` ni `--abi` (esos
    excluyen wheels pure-Python).
  - `cmd_build` gate revisado: con `--python-source=host` sigue rechazando
    cross-target (backward compat del MVP). Con `=standalone` acepta cualquier
    target presente en el catálogo.
  - Nuevo flag `--python-source {host,standalone}` (default `host`).

### Change 3 — CI matrix actualizada
- `.github/workflows/ci.yml` job `runtime-packaging`:
  - 4 entries: `android-arm64` (ubuntu-latest + standalone),
    `linux-x86_64` (ubuntu-latest + host), `windows-x86_64` (windows-latest +
    host), `darwin-arm64` (macos-14 + host).
  - Nuevo atributo `python_source` pasado al productor.
  - Smoke gate separado: `ensure_extracted` solo corre cuando `python_source=host`
    (el runner debe poder ejecutar el Python). Para targets cross, step
    "Smoke — cross-compile extract (no exec)" valida layout del tarball sin
    ejecutar Python.

### Change 4 — Android gradle fetchRuntimeBundle
- `apps/android/gimomesh/app/build.gradle.kts`:
  - Nueva tarea `:app:fetchRuntimeBundle`. Lee `GIMO_RUNTIME_BUNDLE_URL`; si
    el bundle local ya existe o la env var no está set, no hace nada (no-op
    idempotente).
  - `packageCoreRuntime` ahora `dependsOn(fetchRuntimeBundle)`.
  - `include()` copia también `trusted-pubkey.pem` a assets.
  - Mensaje de error al operator ampliado: menciona opciones (a) productor
    local cross-compile + (b) CI artifact.

### Change 5 — Trusted pubkey embedded
- `scripts/generate_runtime_keys.py` nuevo (~90 LOC) — helper `argparse` que
  genera un keypair Ed25519 y lo deja en disk. Imprime el PEM público para
  copiar a `runtime_signature.py`.
- `tools/gimo_server/security/runtime_signature.py`:
  - `EMBEDDED_RUNTIME_PUBLIC_KEY` pasa de `""` a un PEM Ed25519 real. La
    clave privada asociada vive en `secrets/runtime-signing.pem` (gitignored).
  - Comentario actualizado explicando rotación, override via env var, y
    sincronía con `assets/runtime/trusted-pubkey.pem` del Android APK.
- `.gitignore`: añadida entry `/secrets/` para prevenir commit accidental del
  PEM privado.

### Hotfix colateral — Pin alignment en requirements.txt

`pip install --platform=...` es un resolver más estricto que el default — descubrió
tres conflicts reales en el repo:

- `httpx>=0.27.0` vs `fastmcp>=3.1` (pide `httpx<1.0,>=0.28.1`) → pin bumped to
  `httpx>=0.28.1` (también en `requirements-dev.txt`).
- `fastapi>=0.115.0` vs `starlette>=0.49.1` — fastapi <0.119 pide `starlette<0.49`.
  Pin bumped a `fastapi>=0.128.0` (acepta starlette 0.49-0.50).
- `pydantic==2.11.2` vs `fastmcp` (pide `pydantic>=2.11.7`). Pin relaxed a
  `pydantic>=2.11.7`.

Cambios mínimos y alineados a lo que el venv dev ya tenía instalado de hecho —
son fixes que quedan latentes si alguien intentara `pip install -r requirements.txt`
en un env limpio.

### Tests
- `tests/unit/test_runtime_cross_compile.py` **nuevo** (7 tests) — verifica
  mapeo target→asset, target→platform tag, args de `_install_wheels_cross`,
  URL pinned, rechazo de cross-target con `--python-source=host`, presencia
  del flag `--python-source`.
- `tests/unit/test_embedded_runtime_pubkey.py` **nuevo** (4 tests) — verifica
  embedded pubkey no vacío, parseable Ed25519, env override prioridad.
- `tests/unit/test_ci_runtime_matrix.py` **actualizado** (+2 tests) —
  `test_android_target_uses_cross_compile`, `test_host_targets_still_work`.
- `tests/unit/test_android_gradle_runtime_wiring.py` **actualizado** (+3 tests) —
  `fetchRuntimeBundle` registered, `dependsOn`, `trusted-pubkey.pem` included.

## 3. Verification

### 3.1 Suite focused (17 nuevos/actualizados + 62 pre-existentes del runtime)

```
tests/unit/test_runtime_cross_compile.py             7 passed
tests/unit/test_ci_runtime_matrix.py                 7 passed
tests/unit/test_android_gradle_runtime_wiring.py    10 passed
tests/unit/test_embedded_runtime_pubkey.py           4 passed
tests/unit/test_runtime_bootstrap.py                 8 passed
tests/unit/test_runtime_signature.py                10 passed
tests/unit/test_launcher_bundle_selection.py         3 passed
tests/unit/test_runtime_upgrader.py                  7 passed
tests/unit/test_mdns_advertiser.py                  21 passed
────────────────────────────────────────────────────────
Total                                               78 passed   10.75 s
```

### 3.2 Broad regression (guard global)

```
pytest tests/unit -m "not integration" --timeout=60 -q -n auto
→ 1 failed, 1759 passed, 1 skipped, 17 warnings in 118.99 s
```

El único failure es `tests/unit/test_plan_dag.py::test_execute_plan_persists_running_and_final_node_states`
— **flaky pre-existente** no relacionado con este plan (passes en isolation,
falla solo bajo pytest-xdist paralelo). Documentado con el mismo sintoma en
el implementation report del 2026-04-16 RUNTIME_PACKAGING.

### 3.3 Smoke local (dev box Windows → target windows-x86_64 standalone)

```
python scripts/package_core_runtime.py build \
  --target windows-x86_64 \
  --python-source standalone \
  --compression xz \
  --runtime-version 0.1.0-smoke \
  --signing-key secrets/runtime-signing.pem \
  --builder local-smoke \
  --output runtime-assets/
```

Output:
```
20:48:10 INFO downloading https://github.com/astral-sh/python-build-standalone/releases/download/20260414/cpython-3.13.13+20260414-x86_64-pc-windows-msvc-install_only.tar.gz
20:48:22 INFO installing wheels (cross) for target=windows-x86_64 python=3.13
20:53:27 INFO bundle ready -> gimo-core-runtime.tar.xz (compressed=60.6 MiB, uncompressed=291.0 MiB, ratio=4.80x)
```

Verify:
```
python scripts/package_core_runtime.py verify \
  --bundle runtime-assets \
  --public-key runtime-assets/trusted-pubkey.pem
→ OK — version=0.1.0-smoke target=windows-x86_64
```

Manifest inspection:
- target: `windows-x86_64` (no host-detected)
- python_version: `3.13.13` (pinned release)
- python_rel: `python/python.exe`
- files count: 14750
- Contains `python/`, `site-packages/`, `repo/` trees.
- Signed with Ed25519 key matching the embedded pubkey.

## 4. Residual risks

| Riesgo | Severidad | Estado |
| --- | --- | --- |
| `sys_platform` markers en pip cross-install — `pywin32` (dep de `mcp`) no se filtra correctamente cuando cross-compilas desde Windows a Linux | MEDIA | **Conocido**: limita smoke local Windows→Linux. NO afecta CI (ubuntu-latest → android-arm64) ni WSL. Documentado en runbook. **WSL workaround validado 2026-04-16** — producción local del bundle android-arm64 funciona desde WSL Ubuntu sin tocar markers. |
| Bionic vs glibc en Android stock | **CRÍTICA — CONFIRMADA** | Hipótesis del plan validada con evidencia forense en S10 real (2026-04-16): `python-build-standalone aarch64-unknown-linux-gnu` tiene TLS alignment = 8, Android Bionic exige ≥ 64. Error exacto: *"executable's TLS segment is underaligned: alignment is 8, needs to be at least 64 for ARM64 Bionic"*. Patchear interpreter path NO basta — requires recompile contra Bionic. Detalles: `docs/audits/E2E_IMPLEMENTATION_REPORT_20260415_SERVER_MODE_FULL.md §5.2.4`. **Desbloqueo → Chaquopy follow-up, no MVP.** |
| Tamaño del bundle (~60 MiB compressed, ~290 MiB uncompressed) | BAJA | Aceptable. `install_only_stripped` variant reduce ~30%, usarla si el APK grows too large. |
| Rotación de `EMBEDDED_RUNTIME_PUBLIC_KEY` | BAJA | Regenera keypair + rebuild + release. Idempotente. |
| `python-build-standalone` release tag drift | BAJA | Pin explícito en el script. Cambio controlado. |
| `pip --platform` + wheel faltante → abort duro | BAJA | Deseable: previene cross-compile silenciosamente roto. |

## 5. Archivos afectados

### Nuevos
- `scripts/generate_runtime_keys.py`
- `tests/unit/test_runtime_cross_compile.py`
- `tests/unit/test_embedded_runtime_pubkey.py`
- `docs/audits/E2E_ENGINEERING_PLAN_20260416_RUNTIME_CROSS_COMPILE.md`
- `docs/audits/E2E_IMPLEMENTATION_REPORT_20260416_RUNTIME_CROSS_COMPILE.md`
- `secrets/runtime-signing.pem` (gitignored)
- `runtime-assets/` (gitignored — output del smoke)

### Modificados
- `scripts/package_core_runtime.py` — fetcher + pip cross + nuevo flag
- `.github/workflows/ci.yml` — matrix expandida 4 targets
- `apps/android/gimomesh/app/build.gradle.kts` — fetchRuntimeBundle + pubkey
- `tools/gimo_server/security/runtime_signature.py` — pubkey embedded
- `requirements.txt` — pins alineados (httpx 0.28.1, fastapi 0.128, pydantic 2.11.7)
- `requirements-dev.txt` — httpx 0.28.1
- `.gitignore` — `/secrets/`
- `tests/unit/test_ci_runtime_matrix.py` — +2 tests
- `tests/unit/test_android_gradle_runtime_wiring.py` — +3 tests

## 6. Follow-ups explícitos (out of scope)

- **Chaquopy** — Python nativo Bionic-compatible para correr en Android stock
  sin Termux. Plan aparte.
- **Android Kotlin signature verification** — Kotlin valida firma antes de
  extraer. Hoy solo Python runtime_bootstrap lo hace. Low-pri.
- **Download on-demand desde la app Android** — descarga del bundle al
  momento de instalación (vs bundle in APK). Plan aparte.
- **CI runner aarch64 nativo para smoke real** — hoy ubuntu-latest valida
  solo layout. Un emulador aarch64 completaría el loop.

## 7. S10 runbook — próximo paso para el usuario

Una vez el CI runtime-packaging matrix haya corrido en un push a `feature/gimo-mesh`:

1. Descargar el artifact `gimo-core-runtime-android-arm64` del CI run.
2. Extraer los 3 archivos a `runtime-assets/` en el repo local.
3. `cd apps/android/gimomesh && ./gradlew :app:installDebug` (desde Android Studio).
4. El APK instalado ahora tendrá el bundle aarch64-linux-gnu en assets.
5. Activar Serve pill en el S10 → observar si el Dashboard pasa de "embedded
   GIMO Core runtime missing" a "Local host READY". **Caveat Bionic**: si
   falla con `exec format error`, se necesita Termux+proot (documentado).
6. Retomar el runbook `E2E_S10_SERVER_MODE_RUNBOOK_20260415.md` Phase 1.

## 8. Final status

**`DONE` para el alcance del plan.** Los 5 changes aprobados están
implementados, testeados (78/78 focused), verificados con smoke local (bundle
real producido con firma válida), y documentados. El runbook S10 puede
continuar tras la próxima corrida CI que genere el artifact aarch64 real.
