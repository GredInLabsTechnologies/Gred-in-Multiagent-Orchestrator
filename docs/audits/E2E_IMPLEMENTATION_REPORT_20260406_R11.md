# GIMO Forensic Audit — Phase 4: Implementation Report (Round 11)

**Date**: 2026-04-06
**Auditor**: Claude Opus 4.6
**Input**: `E2E_ENGINEERING_PLAN_20260406_R11.md` (approved plan)
**Verification**: `python -m pytest -x -q` — 1377 passed, 0 failures (3:20)

---

## Session Summary

This session executed a full 4-phase forensic audit of GIMO:

1. **Phase 1** — Black-box stress test: 70+ probes across 3 surfaces (MCP, CLI, HTTP), discovered 13 issues (4 BLOCKER, 2 CRITICAL, 3 GAP, 2 INCONSISTENCY, 2 FRICTION).
2. **Phase 2** — Root-cause tracing with parallel subagents: traced all 13 issues through codebase, identified 4 systemic patterns.
3. **Phase 3** — SOTA research with 4 parallel agents + engineering plan with 8 changes.
4. **Phase 4** — Implementation of all 8 changes + 4-agent parallel code review (all GREEN).

---

## Changes Implemented

### Change 1: Regenerate MCP Manifest from OpenAPI [BLOCKER FIX ×3]

| File | Lines | Description |
|------|-------|-------------|
| `scripts/generate_manifest.py` | +7 | Added `anyOf` resolution for Optional params (e.g., `Optional[bool]` → `boolean` instead of falling back to `string`). |
| `tools/gimo_server/mcp_bridge/manifest.py` | ~regenerated | 232 tools auto-generated from live OpenAPI spec. Fixes: `/ops/provider` (singular), `auto_run` as `boolean`, `/ops/connectors/{id}/health` as GET. |

**Result**: All 3 manifest drift issues resolved by derivation, not manual editing.

---

### Change 2: Fix sagp_gateway — imports, attribute, shared GICS [BLOCKER FIX ×3]

| File | Lines | Description |
|------|-------|-------------|
| `tools/gimo_server/services/sagp_gateway.py` | ~20 | 6 surgical fixes: (1) All imports changed from `..services.storage.storage_service` to `.storage_service`; (2) `_daemon` → `_supervisor` in health check; (3) `GicsService()` → `StorageService._shared_gics` in 4 methods; (4) `TrustStorage()` → `TrustStorage(gics_service=StorageService._shared_gics)` in 2 methods. |

**Result**: Proof chain verification, governance snapshot, trust scores, and GICS health all use the shared singleton wired at startup.

---

### Change 3: Fix governance_tools — shared GICS for trust

| File | Lines | Description |
|------|-------|-------------|
| `tools/gimo_server/mcp_bridge/governance_tools.py` | +2 | `TrustStorage()` → `TrustStorage(gics_service=StorageService._shared_gics)` in `gimo_get_trust_profile`. |

**Result**: MCP trust profile tool returns real trust data instead of synthetic 0.85 fallback.

---

### Change 4: Windows `shell=True` for CliAccountAdapter

| File | Lines | Description |
|------|-------|-------------|
| `tools/gimo_server/providers/cli_account.py` | +4 | Both Windows `subprocess.run` paths now use `" ".join(cmd)` (string form) + `shell=True` for npm `.cmd` shim compatibility. `# nosec B602` justified: cmd is hardcoded, prompt goes via stdin file handle. |
| `tests/unit/test_account_mode_windows.py` | +1 -1 | Updated assertion to handle string cmd (was list). |

**Result**: Codex CLI execution unblocked on Windows.

---

### Change 5: Unify ALL native tools via proxy_to_api [GOVERNANCE FIX]

| File | Lines | Description |
|------|-------|-------------|
| `tools/gimo_server/mcp_bridge/native_tools.py` | ~+80 -60 | **ALL** functions that called `OpsService` directly now route through `proxy_to_api`. Affected: `gimo_approve_draft`, `gimo_run_task`, `gimo_propose_structured_plan`, `gimo_create_draft`, `gimo_resolve_handover`, `gimo_get_draft`, `gimo_get_task_status`, `gimo_get_plan_graph`, `gimo_generate_team_config`. Zero `OpsService` imports remain. |

**Result**: Every native MCP tool now traverses the full HTTP governance chain: auth → rate limit → audit log. Mutative operations (approve, run, create) additionally pass through risk gate → intent gate → auto_run gate. **Zero governance escape hatches remain in `native_tools.py`.**

---

### Change 6: Structured error envelope for governance tools

| File | Lines | Description |
|------|-------|-------------|
| `tools/gimo_server/mcp_bridge/governance_tools.py` | +2 | `json.JSONDecodeError` catch before generic `except` in `gimo_evaluate_action`. Returns `{"error": "INVALID_TOOL_ARGS", "detail": "..."}`. |

**Result**: Malformed JSON tool args return structured error instead of generic exception string.

---

### Change 7: Expand agent_id validation

| File | Lines | Description |
|------|-------|-------------|
| `tools/gimo_server/services/conversation_service.py` | +4 -4 | Replaced hardcoded `frozenset({"user", "User", "system", "orchestrator"})` with regex `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`. Normalizes to lowercase. |
| `tests/unit/test_conversation_service.py` | +1 -1 | Updated test: `"worker-rogue"` → `"123-invalid"` (starts with digit, triggers rejection). |
| `tests/unit/test_routes.py` | +2 -2 | Updated route-level test with same pattern. |

**Result**: `claude-operator`, `web-operator`, `assistant`, etc. now accepted. Only truly invalid IDs rejected.

---

### Change 8: Add CLI `graph` and `capabilities` commands

| File | Lines | Description |
|------|-------|-------------|
| `gimo_cli/commands/ops.py` | +28 | Two new `@app.command()` functions: `graph` (GET `/ops/graph`) and `capabilities` (GET `/ops/capabilities`). Follow exact pattern of `diff`/`audit`. |

**Result**: `gimo graph --json` and `gimo capabilities --json` now work from CLI.

---

## Diff Summary

```
 scripts/generate_manifest.py                              |  +7
 tools/gimo_server/mcp_bridge/manifest.py                  |  ~regenerated (232 tools)
 tools/gimo_server/services/sagp_gateway.py                |  ~20
 tools/gimo_server/mcp_bridge/governance_tools.py          |  +4
 tools/gimo_server/mcp_bridge/native_tools.py              |  ~+80 -60 (full proxy_to_api unification)
 tools/gimo_server/providers/cli_account.py                |  +4
 tools/gimo_server/services/conversation_service.py        |  +4 -4
 gimo_cli/commands/ops.py                                  |  +28
 tests/unit/test_account_mode_windows.py                   |  +1 -1
 tests/unit/test_conversation_service.py                   |  +1 -1
 tests/unit/test_routes.py                                 |  +2 -2
 ──────────────────────────────────────────────────────────
 11 files changed, 8 changes for 11 issues resolved
```

---

## Verification

```bash
$ python -m pytest -x -q
1377 passed, 9 skipped, 11 deselected, 4 warnings in 200.74s (0:03:20)
```

All 1377 tests pass. Zero failures. 3 tests updated to reflect new behavior.

### Code Review — 4 Parallel Agents

| Agent | Files Reviewed | Verdict | Gaps |
|-------|---------------|---------|------|
| 1 | `sagp_gateway.py` (281 lines) | GREEN | 0 |
| 2 | `governance_tools.py` + `native_tools.py` | GREEN | 0 |
| 3 | `cli_account.py` + `ops.py` + `conversation_service.py` + 3 tests | GREEN | 0 |
| 4 | `generate_manifest.py` + `manifest.py` (232 tools) | GREEN | 0 |

**4/4 agents GREEN. Zero gaps found.**

---

## Issues Resolved (Traceability)

| Issue ID | Description | Severity | Change | Status |
|----------|-------------|----------|--------|--------|
| R11-#1 | MCP `gimo_providers_list` → `/ops/providers` (should be singular) | BLOCKER | Change 1 | RESOLVED |
| R11-#2 | `verify_proof_chain` import error | BLOCKER | Change 2 | RESOLVED |
| R11-#3 | `gimo_connectors_health` POST (should be GET) | BLOCKER | Change 1 | RESOLVED |
| R11-#4 | `gimo_approve_draft` governance escape hatch | CRITICAL | Change 5 | RESOLVED |
| R11-#5 | `auto_run` type string (should be boolean) | BLOCKER | Change 1 | RESOLVED |
| R11-#6 | `gics_health.daemon_alive` always false | CRITICAL | Change 2 | RESOLVED |
| R11-#7 | CLI `graph`/`capabilities` missing | GAP | Change 8 | RESOLVED |
| R11-#8 | `/ops/trust/query` 404 on GET | INCONSISTENCY | — | DEFERRED (POST-only by design) |
| R11-#9 | Trust profile returns synthetic 0.85 | GAP | Changes 2+3 | RESOLVED |
| R11-#10 | `/auth/check` false for Bearer | INCONSISTENCY | — | DEFERRED (cookie-only by design) |
| R11-#11 | `agent_id` rejects valid MCP identifiers | FRICTION | Change 7 | RESOLVED |
| R11-#12 | Governance tools return unstructured errors | FRICTION | Change 6 | RESOLVED |
| R11-#13 | Windows `[WinError 2]` for Codex CLI | GAP | Change 4 | RESOLVED |

**11 of 13 issues resolved. 2 intentionally deferred (by-design behavior).**

---

## Residual Risks

1. **Manifest re-drift**: `manifest.py` will drift again unless `generate_manifest.py` is run as part of CI or a pre-commit hook.
2. **Frontend rendering**: CLI/TUI don't yet render `iteration_cost`/`cumulative_cost` SSE fields (R10 residual).
3. **25 `/ui/` routes in manifest**: The generator includes `/ui/` prefix routes. These are UI bridge endpoints and intentional, but could be filtered if MCP clients don't need them.
4. **`proxy_to_api` response parsing**: `gimo_run_task` and `gimo_get_plan_graph` parse `proxy_to_api` string responses to extract IDs. If `proxy_to_api` output format changes, these parsers need updating. A structured return type would be more robust.

---

## Audit Trail

| Phase | Document | Date |
|-------|----------|------|
| 1. Black-box stress test | `E2E_AUDIT_LOG_20260406_R11.md` | 2026-04-06 |
| 2. Root-cause analysis | `E2E_ROOT_CAUSE_ANALYSIS_20260406_R11.md` | 2026-04-06 |
| 3. Engineering plan | `E2E_ENGINEERING_PLAN_20260406_R11.md` | 2026-04-06 |
| 4. Implementation report | `E2E_IMPLEMENTATION_REPORT_20260406_R11.md` | 2026-04-06 |

---

## Round Trajectory

| Round | Issues Found | Resolved | Tests | Net Lines |
|-------|-------------|----------|-------|-----------|
| R1 | 14 | 12 | 778 | +320 |
| R2 | 11 | 9 | 845 | +180 |
| R3 | 9 | 8 | 912 | +150 |
| R4 | 8 | 7 | 978 | +120 |
| R5 | 7 | 6 | 1024 | +100 |
| R6 | 6 | 5 | 1089 | +90 |
| R7 | 6 | 5 | 1134 | +80 |
| R8 | 5 | 4 | 1198 | +70 |
| R9 | 5 | 4 | 1267 | +60 |
| R10 | 4 | 4 | 1341 | +40 |
| **R11** | **13** | **11** | **1377** | **~80** |

R11 had a spike in issues (13 vs R10's 4) because this was the first round to systematically test the MCP surface, exposing manifest drift that had accumulated over multiple rounds.

---

## AGENTS.md Completion Standard

| Criterion | Pass | Evidence |
|-----------|------|----------|
| Correct | YES | 1377 tests pass, 11 issues resolved, 4-agent code review all GREEN |
| Honest | YES | 2 issues deferred with justification, residual risks declared |
| Smaller than alternatives | YES | 8 changes across 11 files; manifest regenerated by existing script |
| Easy to audit | YES | Each change traceable to issue ID, code review verdicts documented |
| Preserves system coherence | YES | All changes follow existing patterns (`StorageService._shared_gics`, `proxy_to_api`, `@app.command()`) |
| No unnecessary complexity | YES | Zero new files, zero new dependencies, zero new abstractions |
| Proud to keep | YES | Governance escape hatch closed, manifest derived not declared, shared singletons enforced |
| Strongest design in scope | YES | Root-cause driven: fix the generator, fix the singleton, fix the shell flag, close the escape hatch |
