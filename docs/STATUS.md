# STATUS (UNRELEASED)

**Status**: NEEDS_REVIEW

**Last verified**: 2026-02-06 04:56 CET
**Verified on commit**: d670a320cee131ea7bf0cc2edb432ab90b09ee49

## Executive summary

- The project is currently marked as **UNRELEASED** (intentionally; v1.0 must be explicitly declared by maintainer).
- **Quality gates** pass locally after portability fixes.
- Some verification steps are currently **blocked by missing local tooling** in this environment:
  - `pip-audit` is not installed.
  - `docker` CLI is not installed.

## Reality check (docs vs code)

Recent fixes applied in this repo (still pending a fresh evidence run under `docs/evidence/`):

1) **Ports / entrypoints aligned**
   - Canonical service port: **9325**.
   - `tools/gimo_server/main.py` defaults to 9325 (override via `ORCH_PORT`).
   - UI fallback uses 9325 if `VITE_API_URL` is unset.
   - `scripts/ops/launch_orchestrator.ps1` launches `tools.gimo_server.main:app` on 9325.

2) **OpenAPI expanded**
   - `tools/gimo_server/openapi.yaml` now covers the implemented `/ui/*` routes and core read-only endpoints.

3) **Allowlist parser made backward-compatible**
   - `get_allowed_paths()` accepts both legacy `{timestamp, paths:[str]}` and new `{paths:[{path, expires_at}]}` formats.

## Current blockers for “professional release readiness”

1) Documentation rebuild is in progress (all previous docs archived as legacy).
2) Evidence pack not yet completed (needs: pytest run logs + security audit + docker build + UI checks).
3) Qwen/LM Studio dependent suites must be executed last, once everything else is green.

## Next actions (recommended)

1) Produce/refresh evidence pack (pytest + quality gates + UI checks + security scans).
2) Confirm OpenAPI coverage is complete and kept in sync with `routes.py`.
3) Decide 1.0 version bump (still `UNRELEASED`).
   - `python scripts\\ci\\quality_gates.py`
   - `python scripts\quality_gates.py`
   - `python -m pytest -q`
   - `pip-audit`, `bandit`
   - UI lint/build/test
   - Docker build
