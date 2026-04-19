# rove — vendored wheelhouse forge

Vendored copy of [rove-toolkit](https://github.com/GredInLabsTechnologies/rove)
from release [v1.0.0](https://github.com/GredInLabsTechnologies/rove/releases/tag/v1.0.0)
(published 2026-04-18 by Gred In Labs Technologies).

## Why vendored

`rove-toolkit` is GIMO's upstream dependency for packaging, signing, and
distributing the Core runtime bundle. The source repository is private, so
the release assets are pinned here so the GIMO mesh builds are reproducible
without network access to the private repo.

## Files

| File | Purpose |
|---|---|
| `rove_toolkit-1.0.0-py3-none-any.whl` | Installable wheel. Pip-installable directly. |
| `rove_toolkit-1.0.0.tar.gz` | Source distribution (identical contents). |

## Install

The wheel is referenced from `requirements.txt` by path, so the standard
`pip install -r requirements.txt` pulls it in without hitting a network index.

Manual install:

```bash
pip install ./vendor/rove/rove_toolkit-1.0.0-py3-none-any.whl
```

## Surface used by GIMO

- `rove.manifest.WheelhouseManifest` — canonical signed payload (4-tuple:
  `sha256|target|runtime_version|project_name`).
- `rove.signing.ed25519` — Ed25519 sign + verify (replaces
  `tools/gimo_server/security/runtime_signature.py` internals).
- `rove.builder.*` — wheelhouse producer (replaces
  `scripts/package_core_runtime.py` + ad-hoc producer glue).
- `rove.distribution.http_fetcher` / `http_server` — P2P distribution
  plumbing used by the mesh upgrader.
- `rove.patches.loader` — pulls Android/Termux long-tail fixes from the
  companion [`rove-patches`](https://github.com/GredInLabsTechnologies/rove-patches)
  registry.

## Upgrade procedure

1. Download the new release assets from the rove GitHub releases.
2. Replace both files here (wheel + sdist).
3. Bump the pinned version in `requirements.txt`.
4. Bump the pinned version in `vendor/rove/README.md` (this file).
5. Run `pytest tests/unit/test_runtime_*` to confirm the manifest / signing
   contracts still hold.
6. **Wire-protocol break to watch**: `WheelhouseManifest.signing_payload()`
   changed from a 3-tuple to a 4-tuple in 1.0.0. Any consumer not using
   `WheelhouseManifest.signing_payload()` directly (notably the Kotlin
   launcher) must be updated in lockstep.
