# rove-patches

> Community patch registry for [Rove](https://github.com/GredInLabsTechnologies/rove) — long-tail fixes for Python deps that fail on Android, embedded ARM, musl/bionic.

This repository carries the *one-off patches every Python+native project keeps re-discovering*: `psutil` rejecting Android in `setup.py`, `maturin` failing on missing `ANDROID_API_LEVEL`, `cryptography` fighting Termux's libc. Rather than each project shipping its own copy, we keep them here, signed and versioned, with declarative metadata so Rove (or any other consumer) can resolve and apply them automatically.

## Format

A patch entry is described in `manifest.json`:

```json
{
  "id": "psutil/android-platform-allow",
  "package": "psutil",
  "version_spec": ">=6.0.0",
  "targets": ["android-arm64", "android-armv7"],
  "kind": "patch",
  "path": "patches/psutil/android-platform-allow.patch",
  "sha256": "...",
  "description": "Skip the platform=='android' refusal in setup.py."
}
```

Three `kind`s are supported:

| Kind | Format | Apply mechanism |
|---|---|---|
| `patch` | Unified diff (`diff -u`) | `patch -p1 -i FILE` against unpacked sdist |
| `env` | `KEY=VALUE` lines (one per line, `#` comments) | Merged into the build subprocess env |
| `toml` | TOML | Surfaced to consumer; semantics defined per package |

## Layout

```
rove-patches/
├── manifest.json          # canonical index — required
└── patches/
    ├── <package>/
    │   ├── <id>.patch
    │   ├── <id>.env
    │   └── <id>.toml
```

## Contributing a patch

1. Reproduce the failure on the target platform.
2. Write the minimal change (preferably an `.env` or `.toml` if the upstream build accepts env-vars; only fall back to `.patch` when source modification is unavoidable).
3. Add an entry to `manifest.json` with `version_spec`, `targets`, `sha256` (lowercase hex of the patch file), and a one-line `description`.
4. Open a PR. CI runs `python -m rove_patches.lint` (script in `tools/`) which validates: schema, sha256 match, file exists, target tuples valid.
5. Maintainers review for security, scope, and maintainability before merge.

## Trust

Patches are signed by the maintainer release key (separate from any project's bundle-signing key). Consumers should verify `manifest.json.sig` before applying patches.

## Current contents

| Patch | Package | Targets | Why |
|---|---|---|---|
| `psutil/android-platform-allow` | `psutil>=6.0.0` | `android-*` | psutil's `setup.py` raises `RuntimeError("platform android is not supported")`. Patch removes the check. |
| `maturin/android-api-level` | `maturin>=1.10` | `android-*` | maturin needs `ANDROID_API_LEVEL` env to cross-compile pydantic-core etc. for Android. Patch sets a sane default of 24. |
| `cryptography/pkg-fallback` | `cryptography>=43` | `android-*` | Forces `--prefer-binary` so Termux's pre-built `python-cryptography` wheel is preferred over a 15+ min Rust build. |

## License

[MIT](LICENSE) © Gred In Labs Technologies
