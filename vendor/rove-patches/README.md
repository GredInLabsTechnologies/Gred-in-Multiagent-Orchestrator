# rove-patches — vendored patch registry

Vendored copy of [rove-patches](https://github.com/GredInLabsTechnologies/rove-patches)
(private repo). Snapshot del contenido del `main` al 2026-04-18.

## Qué es

Registry de patches para deps Python que fallan al compilar en targets
no-mainstream (Android/Termux, embedded ARM, musl/bionic). Cada entry
tiene metadata `(pkg, version_range, target, kind, sha256)`.

Consumido por `rove.patches.loader.load_patch_set()` + `resolve_patches()`.

## Archivos

| File | Purpose |
|---|---|
| `manifest.json` | Índice canónico — lista de entries con sha256 |
| `patches/psutil/android-platform-allow.patch` | Unified diff (`kind: patch`) |
| `patches/maturin/android-api-level.env` | KEY=VALUE env vars (`kind: env`) |
| `patches/cryptography/pkg-fallback.toml` | Pip constraints (`kind: toml`) |
| `README.upstream.md` | README original del repo upstream |

## Integración actual

`scripts/package_core_runtime.py` (`_apply_rove_patches`) consume el set
durante `_install_wheels_cross` para builds cross-compile:

1. Parsea `requirements.txt` → lista de package names
2. Llama `resolve_patches(patch_set, packages, target)` filtrando por el
   target del bundle (android-arm64, android-armv7, …)
3. Para patches `kind=env`: inyecta KEY=VALUE en la env de la subprocess
   de pip (ej. `ANDROID_API_LEVEL=24` para maturin sdist compiles)
4. Para patches `kind=toml`: parsea el TOML (los consumidores pueden
   interpretarlo como constraints adicionales)
5. Para patches `kind=patch` (unified diff): reporta el ID pero NO aplica
   — requieren sdist unpacking, fuera de scope del path `--only-binary :all:`.
   Si en el futuro se relaja esa restricción (builds de fallback con
   compile source), la aplicación se habilita vía `rove.builder.patches.apply_unified_diff`.

## Targets cubiertos hoy

| Patch | Packages | Targets |
|---|---|---|
| psutil/android-platform-allow | psutil >=6.0.0 | android-arm64, android-armv7 |
| maturin/android-api-level | maturin >=1.10 | android-arm64, android-armv7 |
| cryptography/pkg-fallback | cryptography >=43 | android-arm64, android-armv7 |

Para Windows/Linux/macOS desktop: 0 patches (wheels mainstream ya están
disponibles).

## Upgrade procedure

1. `gh api repos/GredInLabsTechnologies/rove-patches/contents/manifest.json --jq '.content' | base64 -d > vendor/rove-patches/manifest.json`
2. Descargar cada patch referenciado en el nuevo manifest
3. Verificar sha256 local con el que aparece en el manifest
4. Run `pytest tests/unit/test_runtime_cross_compile.py` para validar
   que resolve_patches sigue funcionando contra el schema de la nueva
   versión (rove sigue pinned a v1.0.0 mientras el loader API sea estable).
