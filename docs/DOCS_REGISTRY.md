# Documentation Registry

**Purpose**: Track which documents are VALIDATED vs NEEDS_REVIEW vs INVALID (deprecated), with timestamps, commit hashes and evidence links.

## Status Legend

- **INVALID (LEGACY)**: Archived snapshot from a previous state. Do not trust.
- **NEEDS_REVIEW**: Draft or partially verified.
- **VALIDATED**: Verified against the current repo/system state with reproducible evidence.

## Current docs (authoritative set)

> At the moment, the authoritative set is being rebuilt from zero.

| Doc | Status | Last Verified | Commit | Evidence | Notes |
|---|---|---:|---|---|---|
| `README.md` | NEEDS_REVIEW | 2026-02-10 | N/A | N/A | Entry point; points to source of truth |
| `docs/GIMO_SYSTEM.md` | VALIDATED | 2026-02-10 | N/A | N/A | **AUTHORITATIVE source of truth** |
| `docs/STATUS.md` | NEEDS_REVIEW | 2026-02-06 04:56 CET | d670a320 | N/A | Current state + blockers |
| `docs/SETUP.md` | NEEDS_REVIEW | 2026-02-06 04:56 CET | d670a320 | N/A | Setup (to be verified) |
| `docs/OPERATIONS.md` | NEEDS_REVIEW | 2026-02-06 04:56 CET | d670a320 | N/A | Ops (to be verified) |
| `docs/SECURITY.md` | NEEDS_REVIEW | 2026-02-06 04:56 CET | d670a320 | N/A | Security verification plan |
| `docs/RELEASE.md` | NEEDS_REVIEW | 2026-02-06 04:56 CET | d670a320 | N/A | Release workflow (to be verified) |
| `docs/TROUBLESHOOTING.md` | NEEDS_REVIEW | 2026-02-06 04:56 CET | d670a320 | N/A | Troubleshooting (to be filled) |

## History (non-authoritative)

These documents are preserved for project history and **must not be used as current system specification**.

- `docs/history/` (see `docs/history/README.md`)

## Notes (current)

The following documents have been expanded to reflect the current codebase but are still marked NEEDS_REVIEW until we attach evidence under `docs/evidence/`:

- `README.md`
- `docs/SETUP.md`
- `docs/OPERATIONS.md`
- `docs/SECURITY.md`
- `docs/RELEASE.md`
- `docs/TROUBLESHOOTING.md`

Key known mismatches to resolve before declaring 1.0:

1) ports/entrypoints inconsistencies (historical: 9325 vs 6834 vs 8001)
2) OpenAPI contract incomplete vs implemented routes
3) allowlist format mismatch (`allowed_paths.json` vs `get_allowed_paths()`)

## Deprecated snapshots (legacy)

| Snapshot | Status | Notes |
|---|---|---|
| `docs/deprecated/2026-02-06_0433_CET/` | INVALID (LEGACY) | Full archive of previous documentation set |
