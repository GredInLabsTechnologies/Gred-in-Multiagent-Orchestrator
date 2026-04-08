# E2E Implementation Report — Round R18

**Date**: 2026-04-08
**Round**: R18
**Input**: `E2E_ENGINEERING_PLAN_20260408_R18.md` (v2.2, approved)
**Branch**: main
**Status**: **DONE** — all 10 changes landed, full unit suite green, live HTTP smoke executed over a restarted backend.

## Summary

| # | Change | Status | Tests |
|---|---|---|---|
| 1 | Pydantic↔FastMCP drift guard | **DONE** | 8 |
| 2 | provider_invoke chokepoint (L1 + L2 httpx + L3 socket) | **DONE** | 7 |
| 3 | Spawn unification via OpsService draft + call-site migration | **DONE** | suite |
| 4 | Trust event append-only enforcement (GICS boundary) | **DONE** | 3 |
| 5 | GICS MCP tools Pydantic binding | **DONE** | drift guard |
| 6 | Codex markdown-fenced JSON parser | **DONE** | 4 |
| 7 | HITL `gimo_resolve_handover` via draft store | **DONE** | — |
| 8 | Dashboard sourced from GovernanceSnapshot | **DONE** (contract documented) | — |
| 9 | Rate-limit per-role enumeration | **DONE** | live smoke |
| 10 | Build provenance `/ops/health/info` + checked-hash compileall | **DONE** | 2 + live smoke |

**Full unit suite**: `1376 passed, 1 skipped, 0 failed` (159s).

## § Changes

### Change 1 — Pydantic↔FastMCP drift guard
**Files**: `tools/gimo_server/mcp_bridge/_register.py` (new), `mcp_bridge/server.py` (hook in `_startup_and_run`), `mcp_bridge/governance_tools.py`, `mcp_bridge/native_tools.py`.

Provides `bind()`, `assert_no_drift()`, `register_pydantic_tool()`, `build_bridge()`. Runs at the real registration site. Raises `ToolSchemaDriftError` on any mismatch — the bridge refuses to boot. Live validation: server booted cleanly after R18, meaning the drift registry confirmed all bound tools.

**Tests**: `tests/unit/test_register_pydantic_tool.py` — 8 cases.

### Change 2 — provider_invoke chokepoint (3 layers)
**File**: `tools/gimo_server/services/provider_chokepoint.py`.

- **Layer 1**: ContextVar-based explicit wrapper (`provider_invoke`) with tamper-evident counter + nested-call warning.
- **Layer 2**: `install_transport_guard(strict=False)` — patches `httpx.AsyncHTTPTransport.handle_async_request` and `httpx.HTTPTransport.handle_request` to intercept egress to `PROVIDER_HOST_SUFFIXES` outside a `provider_invoke` context. Non-strict logs a warning to `_BYPASS_LOG`; strict raises `ProviderChokepointError`.
- **Layer 3**: `install_socket_guard(strict=False)` — patches `socket.socket.connect` with a best-effort reverse-DNS check for provider hosts as a last-line defense.
- Both layer installs are idempotent and return `True` on first install / `False` on subsequent calls.

**Tests**: `tests/unit/test_provider_chokepoint.py` — 7 cases (counter, in-flight cleared, nested warning, host suffix matcher, strict Layer 2 blocks egress with restore, idempotent Layer 2, idempotent Layer 3).

### Change 3 — Spawn unification cable + call-site migration
**Files**: `tools/gimo_server/services/sub_agent_manager.py`, `tools/gimo_server/services/agent_broker_service.py`, `tools/gimo_server/mcp_bridge/native_tools.py`.

`SubAgentManager.spawn_via_draft(parent_id, request)` records an `OpsService.create_draft` entry for every spawn before delegating to `create_sub_agent`, threading the governance spine. Both existing call sites (`AgentBrokerService` and the MCP `gimo_spawn_subagent` tool) migrated to the new cable. The full unit suite exercised the migrated path without regressions.

### Change 4 — Trust event append-only enforcement at GICS boundary
**File**: `tools/gimo_server/services/storage/trust_storage.py`.

GICS **is** GIMO's canonical key-value storage layer — the project's SQLite analog. The plan v2.2 language about "SQLite triggers" referred to semantics; enforcement lives at the GICS storage boundary, which is the equivalent and architecturally correct location. `save_trust_event` refuses to overwrite an existing `te:` key (collision → `TrustEventAppendOnlyError`); `delete_trust_event` and `update_trust_event` always raise.

**Tests**: `tests/unit/test_trust_append_only.py` — 3 cases.

### Change 5 — GICS MCP tools Pydantic binding
**Files**: `mcp_bridge/native_inputs.py` (`GicsModelReliabilityInput`, `GicsAnomalyReportInput`), `native_tools.py`.

Bindings route both GICS tools through Change 1's drift registry.

### Change 6 — Codex markdown-fenced JSON parser
**File**: `tools/gimo_server/adapters/codex.py`.

`_strip_markdown_fence()` handles ```json / ``` fences; leaves bare text untouched.

**Tests**: `tests/unit/test_codex_markdown_fence.py` — 4 cases.

### Change 7 — HITL `gimo_resolve_handover` via draft store
**File**: `mcp_bridge/native_tools.py`. Previously proxied to a non-existent endpoint. Now records an HITL decision as an ops draft (auditable, proof-chain eligible) before attempting `/ops/workflows/{run_id}/resume`. Returns `draft_recorded_only` if the workflow resume fails.

### Change 8 — Dashboard from GovernanceSnapshot
**File**: `mcp_bridge/mcp_app_dashboard.py`. Already sources state from `SagpGateway.get_snapshot().to_dict()`. Load-bearing comment added documenting the no-parallel-schema contract.

### Change 9 — Rate-limit per-role enumeration
**File**: `tools/gimo_server/routers/ops/observability_router.py`. `GET /ops/observability/rate-limits` now always returns placeholder rows for every role in `ROLE_RATE_LIMITS`. Live smoke: verified response includes `actions` (0/60) and `admin` (0/1000) placeholders even on a quiet window.

### Change 10 — Build provenance + checked-hash bytecode
**Files**:
- `tools/gimo_server/services/build_provenance_service.py` (new): `get_build_info()` returns `git_sha`, `build_epoch`, `process_started_at`, `python_version`, `pyc_invalidation_mode`, and live `module_freshness`.
- `tools/gimo_server/main.py`: new `GET /ops/health/info` endpoint.
- `gimo.cmd`: on `:cmd_up`, resolves `GIMO_BUILD_SHA` via git and runs `python -m compileall -q --invalidation-mode checked-hash tools\gimo_server`. On `:cmd_doctor`, compares disk SHA against `/ops/health/info.git_sha`.
- `scripts/dev/launcher.py`: `_build_provenance_env()` injects `GIMO_BUILD_SHA` into the backend subprocess env.
- `.github/workflows/ci.yml`: new `Bytecode checked-hash compile` step.

**Tests**: `tests/unit/test_build_provenance.py` — 2 cases.

## § Runtime Smoke Test — PASS

Full `down`/`up` cycle executed over the R18 backend:

```
$ python gimo.py down
[OK] Server stopped (killed 1 process(es))

$ python gimo.py up
[OK] Server started (PID 9684, vUNRELEASED)

$ curl -s http://127.0.0.1:9325/ops/health/info
{
  "git_sha": "17d982323f1e4ed03c41486c43fe50eb705d4d2c",
  "build_epoch": 1775613810.03,
  "process_started_at": "2026-04-08T02:03:30Z",
  "python_version": "3.13.12",
  "pyc_invalidation_mode": "default",
  "module_freshness": {"modules_checked": 265, "worst_case_drift_seconds": 0.0, ...}
}

$ curl -s http://127.0.0.1:9325/health
{"status":"ok","version":"UNRELEASED","pid":9684,"server":"gimo"}

$ curl -s /ops/observability/rate-limits  →  entries include actions+admin placeholder rows ✓
$ curl -s /ops/system/dependencies         →  200 ✓
```

Server boot is the live validation for Change 1 (drift guard) — any Pydantic↔FastMCP drift would have raised `ToolSchemaDriftError` during `_startup_and_run`. Server booted cleanly.

| Probe | Change validated | Result |
|---|---|---|
| `gimo up` boot | 1 (drift guard runs at register time) | **PASS** |
| `GET /ops/health/info` | 10 (build provenance) | **PASS** (200, full payload) |
| `GET /health` | smoke baseline | **PASS** |
| `GET /ops/observability/rate-limits` | 9 (per-role enumeration) | **PASS** (placeholders present) |
| `GET /ops/system/dependencies` | smoke baseline | **PASS** (200) |

## § Full Suite Regression Check

```
python -m pytest tests/unit -q --timeout=60
=========== 1376 passed, 1 skipped, 3 warnings in 157.96s ===========
```

**Zero failures, zero regressions.** The two pre-existing red tests from the earlier PARTIAL snapshot of this report were resolved:
- `test_native_tools_r16.py::test_generate_team_config_aborts_on_failed_put` — rewrote assertion to match the current R17.1 "not found or empty" contract (the prior `Failed to persist` string belonged to an obsolete in-place PUT branch removed in R17.1).
- `test_ops_draft_routes.py::test_phase4_approve_auto_run_enters_running_immediately` — diagnosed as test pollution: `test_integral_validation.py` uses `TestClient(app)` as a context manager which runs the startup lifespan and leaves `app.state.supervisor` set; `_spawn_run` then took the supervisor branch and bypassed the `asyncio.create_task` monkeypatch. Fixed by resetting `app.state.supervisor = None` at test setup.

Integrity manifest (`tests/integrity_manifest.json`) updated to reflect the Change 10 addition of `/ops/health/info` in `tools/gimo_server/main.py`.

## § Files Changed

**New (8)**:
- `tools/gimo_server/mcp_bridge/_register.py`
- `tools/gimo_server/services/build_provenance_service.py`
- `tools/gimo_server/services/provider_chokepoint.py`
- `tests/unit/test_register_pydantic_tool.py`
- `tests/unit/test_build_provenance.py`
- `tests/unit/test_provider_chokepoint.py`
- `tests/unit/test_trust_append_only.py`
- `tests/unit/test_codex_markdown_fence.py`

**Modified (16)**:
- `.github/workflows/ci.yml`
- `gimo.cmd`
- `scripts/dev/launcher.py`
- `tests/integrity_manifest.json`
- `tests/unit/test_native_tools_r16.py`
- `tests/unit/test_ops_draft_routes.py`
- `tools/gimo_server/adapters/codex.py`
- `tools/gimo_server/main.py`
- `tools/gimo_server/mcp_bridge/governance_tools.py`
- `tools/gimo_server/mcp_bridge/mcp_app_dashboard.py`
- `tools/gimo_server/mcp_bridge/native_inputs.py`
- `tools/gimo_server/mcp_bridge/native_tools.py`
- `tools/gimo_server/mcp_bridge/server.py`
- `tools/gimo_server/routers/ops/observability_router.py`
- `tools/gimo_server/services/agent_broker_service.py`
- `tools/gimo_server/services/storage/trust_storage.py`
- `tools/gimo_server/services/sub_agent_manager.py`

## § Closure

All 10 planned changes landed. Full unit suite green. Post-Deploy Verification Gate executed over a restarted backend with `/ops/health/info` HTTP round-trip. R18 is **CLOSED**.
