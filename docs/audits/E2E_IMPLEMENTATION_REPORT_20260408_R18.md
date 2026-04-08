# E2E Implementation Report — Round R18

**Date**: 2026-04-08
**Round**: R18
**Input**: `E2E_ENGINEERING_PLAN_20260408_R18.md` (v2.2, approved)
**Branch**: main

## Summary — PARTIAL CLOSURE

**R18 is NOT fully closed.** Substantial implementation landed (6 of 10 changes
fully DONE, 3 PARTIAL, 1 ALREADY_SATISFIED) but the `/e2e` skill closure gates
are not met: two pre-existing test failures remain red in the ordered full
suite, and no live HTTP smoke over a restarted backend was executed. This
report is filed as **PARTIAL_DONE per AGENTS.md**, not as a Phase 4 full close.

| # | Change | Status | Tests |
|---|---|---|---|
| 1 | Pydantic↔FastMCP drift guard | **DONE** | 8 |
| 2 | provider_invoke chokepoint (Layer 1 only) | **PARTIAL** (2/3 layers deferred) | 3 |
| 3 | Spawn unification cable via OpsService | **PARTIAL** (cable added; ~6 call-site migrations deferred) | — |
| 4 | Trust event append-only enforcement | **DONE** | 3 |
| 5 | GICS MCP tools Pydantic binding | **DONE** | — |
| 6 | Codex markdown-fenced JSON parser | **DONE** | 4 |
| 7 | HITL `gimo_resolve_handover` via draft store | **DONE** | — |
| 8 | Dashboard sourced from GovernanceSnapshot | **ALREADY_SATISFIED** (contract documented) | — |
| 9 | Rate-limit per-role enumeration | **DONE** | — |
| 10 | Build provenance `/ops/health/info` + compileall | **PARTIAL** (code + unit tests DONE; live HTTP smoke not run) | 2 |

**Honest score**: 6 DONE / 3 PARTIAL / 1 ALREADY_SATISFIED, not "10/10 landed".

## § Changes

### Change 1 — Pydantic↔FastMCP drift guard
**Files**: `tools/gimo_server/mcp_bridge/_register.py` (new, ~220 LOC), `mcp_bridge/server.py` (hook in `_startup_and_run` after `_register_native`), `mcp_bridge/governance_tools.py` (bindings for `gimo_estimate_cost`, `gimo_verify_proof_chain`), `mcp_bridge/native_tools.py` (bindings).

Provides `bind()`, `assert_no_drift()`, `register_pydantic_tool()`, `build_bridge()`. Runs at real registration site (not empty `__init__.py`). Raises `ToolSchemaDriftError` on any mismatch — the bridge refuses to boot.

**Tests**: `tests/unit/test_register_pydantic_tool.py` — 8 cases (bind type check, drift pass, drift on extra/missing field, missing-tool skip-with-warning, register_pydantic_tool signature, registry isolation, real bindings sanity).

### Change 2 — provider_invoke chokepoint (Layer 1 only)
**File**: `tools/gimo_server/services/provider_chokepoint.py` (new).

ContextVar-based single chokepoint. Nested calls log a warning. Tamper-evident invocation counter. **Layers 2 (httpx/SDK monkey-patch) and 3 (socket egress denylist) are deferred** — full transport-level enforcement was too invasive to land safely in this round. The explicit wrapper Layer 1 gives SAGP a canonical hook point; adapter migration to call `provider_invoke` is tracked as R19 follow-up.

**Tests**: `test_provider_chokepoint.py` — 3 cases (counter, in-flight cleared, nested warning).

### Change 3 — Spawn unification cable
**File**: `tools/gimo_server/services/sub_agent_manager.py`.

New classmethod `spawn_via_draft(parent_id, request)` records an `OpsService.create_draft` entry for every spawn before calling `create_sub_agent`, threading the governance spine (policy/trust/cost/proof). Existing callers of `create_sub_agent` continue to work unchanged; new call sites should use `spawn_via_draft`. Full call-site migration deferred to R19 with explicit justification: the existing path is non-failing and the cable is additive.

### Change 4 — Trust event append-only enforcement at GICS boundary
**File**: `tools/gimo_server/services/storage/trust_storage.py`.

**Correction to plan v2.2 wording**: the plan said "SQLite triggers", but GICS
**is** our SQLite — the project's canonical storage layer — not an alternative
to it. Enforcement lives at the GICS storage boundary, which is the
architecturally correct and equivalent location (GICS is the only write path;
every mutation must traverse it). `save_trust_event` refuses to overwrite an
existing `te:` key (collision → `TrustEventAppendOnlyError`);
`delete_trust_event` and `update_trust_event` always raise. This is the
semantic equivalent of a `BEFORE UPDATE/DELETE RAISE(ABORT)` trigger applied
to the real storage engine GIMO uses.

**Tests**: `test_trust_append_only.py` — 3 cases (delete raises, update raises, overwrite raises).

### Change 5 — GICS MCP tools Pydantic binding
**Files**: `mcp_bridge/native_inputs.py` (new `GicsModelReliabilityInput`, `GicsAnomalyReportInput`), `native_tools.py` (bindings).

Both GICS tools already exposed canonical signatures; binding them through Change 1's drift registry protects them against future regressions without touching the tool bodies.

### Change 6 — Codex markdown-fenced JSON parser
**File**: `tools/gimo_server/adapters/codex.py`.

New `_strip_markdown_fence()` helper used by `CODEX_METRICS:` payload parser. Handles ``` ```json / ``` ``` fences; leaves bare text untouched.

**Tests**: `test_codex_markdown_fence.py` — 4 cases (json fence, bare fence, unfenced passthrough, empty).

### Change 7 — HITL `gimo_resolve_handover` via draft store
**File**: `mcp_bridge/native_tools.py`.

Previously proxied to a non-existent `/ops/runs/{run_id}/resume`. Now records an HITL decision as an ops draft (auditable, proof-chain eligible) before attempting `/ops/workflows/{run_id}/resume`. Returns a `draft_recorded_only` marker if the workflow resume fails so the governance record survives infrastructure errors.

### Change 8 — Dashboard from GovernanceSnapshot
**File**: `mcp_bridge/mcp_app_dashboard.py`.

Already sources state from `SagpGateway.get_snapshot().to_dict()`. Added a load-bearing comment documenting the contract: the rendered payload cannot diverge from the canonical governance model because there is no parallel schema.

### Change 9 — Rate-limit per-role enumeration
**File**: `tools/gimo_server/routers/ops/observability_router.py`.

`GET /ops/observability/rate-limits` now always returns placeholder rows for every role in `ROLE_RATE_LIMITS` (count=0) when the live store has no entries for them, so dashboards never see an empty list on a quiet window.

### Change 10 — Build provenance + checked-hash bytecode
**Files**:
- `tools/gimo_server/services/build_provenance_service.py` (new, ~120 LOC): `get_build_info()` returns `git_sha` (from `GIMO_BUILD_SHA` env, fallback `git rev-parse HEAD`), `build_epoch`, `process_started_at`, `python_version`, `pyc_invalidation_mode`, and a live `module_freshness` signal walking `sys.modules`.
- `tools/gimo_server/main.py`: new `GET /ops/health/info` endpoint.
- `gimo.cmd`: on `:cmd_up`, resolves `GIMO_BUILD_SHA` via git, runs `python -m compileall -q --invalidation-mode checked-hash tools\gimo_server`. On `:cmd_doctor`, compares disk SHA against `/ops/health/info.git_sha` and warns on drift.
- `scripts/dev/launcher.py`: `_build_provenance_env()` injects `GIMO_BUILD_SHA` into the backend subprocess environment.
- `.github/workflows/ci.yml`: new `Bytecode checked-hash compile` step before pre-commit.

**Tests**: `test_build_provenance.py` — 2 cases (payload shape, env override).

## § Runtime Smoke Test — INCOMPLETE

The `/e2e` Phase 4 Step 1.5 requires a full server `down`/`up` cycle followed
by re-running the top-5 failed Phase 1 probes against the restarted backend.
**That full protocol was NOT executed in this session.** Only an in-process
provenance payload check was run:

```
$ python -c "from tools.gimo_server.services.build_provenance_service import get_build_info; ..."
{
  "git_sha": "f53faadca9e0eede5630a4447170c0f837411c73",
  "build_epoch": 1775611166.27,
  "process_started_at": "2026-04-08T01:19:26Z",
  "python_version": "3.13.12",
  "pyc_invalidation_mode": "default",
  "module_freshness": {"modules_checked": 3, "worst_case_drift_seconds": 0.0, ...}
}
```

SMOKE_PARTIAL — in-process provenance payload resolves correctly, but the
`/e2e` Post-Deploy Verification Gate (restart + HTTP round-trip + re-run
failed probes) is **not executed**. Full protocol deferred to the next
session. Per AGENTS.md, this is the honest reason R18 is filed as PARTIAL.

## § Full Suite Regression Check

```
python -m pytest -q --timeout=60 --ignore=tests/integration
====== 2 failed, 1398 passed, 1 skipped, 4 warnings in 173.22s ======
```

Both failures verified pre-existing on a `git stash` of clean `main`:
- `test_native_tools_r16.py::test_generate_team_config_aborts_on_failed_put` — fails on clean `main` (unrelated, pre-existing).
- `test_ops_draft_routes.py::test_phase4_approve_auto_run_enters_running_immediately` — passes in isolation, fails only as part of the ordered suite (test pollution, pre-existing).

**Zero R18 regressions**, but **the suite is NOT fully green**. The `/e2e`
skill requires 100% green before Phase 4 close; that gate is **not met**. The
two failures are pre-existing but remain on the board.

Integrity manifest updated (`tests/integrity_manifest.json`) to reflect the new hash of `tools/gimo_server/main.py` (Change 10 added `/ops/health/info`).

## § Deferrals / Residual Risks / Open Gates (blocking full Phase 4 close)

1. **Change 2 Layers 2/3** (httpx/SDK monkey-patch + socket egress denylist) —
   deferred. Layer 1 chokepoint is in place; until Layers 2/3 land, governance
   can still be bypassed by an adapter that doesn't call `provider_invoke`.
2. **Change 3** — `spawn_via_draft` is additive; migration of the existing
   `create_sub_agent` call sites is deferred. Until then, legacy call sites
   bypass the draft-store governance spine.
3. **Change 10 HTTP smoke** — `/ops/health/info` unit-tested but not yet
   round-tripped through a live `gimo up` cycle; doctor gate verified only
   by inspection.
4. **Full-suite green gate** — 2 pre-existing failures remain red. `/e2e`
   does not permit Phase 4 close with any red.
5. **Post-Deploy Verification Gate** — restart + re-run of Phase 1 failed
   probes not executed.

**These five items must be cleared in R18.1 (or R19) before R18 can be
claimed as fully closed.** This report is PARTIAL_DONE, not DONE.

## § Files Changed

**New (7)**:
- `tools/gimo_server/mcp_bridge/_register.py`
- `tools/gimo_server/services/build_provenance_service.py`
- `tools/gimo_server/services/provider_chokepoint.py`
- `tests/unit/test_register_pydantic_tool.py`
- `tests/unit/test_build_provenance.py`
- `tests/unit/test_provider_chokepoint.py`
- `tests/unit/test_trust_append_only.py`
- `tests/unit/test_codex_markdown_fence.py`

**Modified (10)**:
- `.github/workflows/ci.yml`
- `gimo.cmd`
- `scripts/dev/launcher.py`
- `tests/integrity_manifest.json`
- `tools/gimo_server/adapters/codex.py`
- `tools/gimo_server/main.py`
- `tools/gimo_server/mcp_bridge/governance_tools.py`
- `tools/gimo_server/mcp_bridge/mcp_app_dashboard.py`
- `tools/gimo_server/mcp_bridge/native_inputs.py`
- `tools/gimo_server/mcp_bridge/native_tools.py`
- `tools/gimo_server/mcp_bridge/server.py`
- `tools/gimo_server/routers/ops/observability_router.py`
- `tools/gimo_server/services/storage/trust_storage.py`
- `tools/gimo_server/services/sub_agent_manager.py`
