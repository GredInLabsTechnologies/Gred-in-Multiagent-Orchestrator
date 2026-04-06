# E2E Implementation Report — R14

**Date**: 2026-04-06
**Round**: R14
**Auditor**: Claude Opus 4.6 (E2E Forensic Protocol)
**Test Vehicle**: Advanced Engineering Calculator (all functions + Windows executable + web frontend)

---

## Summary

R14 implemented **7 changes** across **10 files** to resolve 15 issues (4 BLOCKER, 3 CRITICAL,
5 GAP, 2 FRICTION, 1 INCONSISTENCY). The core fix — "approval is terminal" — unblocks the
entire execution pipeline by making PolicyGate and RiskGate skip evaluation for pre-approved drafts.

**Result**: 1378 tests passed, 0 failed, 9 skipped. All changes verified by 8 parallel code review agents.

---

## Changes Implemented

### Change 1: Approval-Aware Pipeline Gates [P0]

**Files modified**:
- `tools/gimo_server/engine/stages/policy_gate.py:13-17` — Added approval bypass
- `tools/gimo_server/engine/stages/risk_gate.py:16-20` — Added approval bypass
- `tools/gimo_server/services/execution/engine_service.py:381-384` — Halt handler updates run status to `HUMAN_APPROVAL_REQUIRED`

**What**: When `input.context.get("approved_id")` is truthy, gates return `StageOutput(status="continue")` immediately with audit artifact `gate_skipped: true`. The halt handler now transitions runs to `HUMAN_APPROVAL_REQUIRED` instead of silently returning.

**Issues resolved**: #1 (run stuck at null stage), #7 (zero cost tracking)

### Change 2: CLI SSE Protocol Alignment [P0]

**Files modified**:
- `gimo_cli/commands/plan.py:73-92` — Rewrote SSE event parser
- `tests/unit/test_gimo_cli.py:43-46,68` — Updated mock SSE data and assertion

**What**: CLI now parses `result`, `error`, and `stage` events matching the server's actual protocol (`emit_sse("completed", {"result": ...})`). Draft ID extraction uses `payload.get("draft_id") or payload.get("id")` fallback chain.

**Issues resolved**: #2 (CLI plan/chat silent)

### Change 3: MCP Bridge Serialization Fixes [P1]

**Files modified**:
- `tools/gimo_server/mcp_bridge/native_tools.py` — `gimo_chat`: `params=` to `json=`; `gimo_spawn_subagent`: added `workspace_path` param

**What**: Fixed HTTP body serialization for chat endpoint (was sending as query params, causing 422). Added `workspace_path` parameter to spawn with `ORCH_REPO_ROOT` env fallback.

**Issues resolved**: #5 (chat 422), #6 (spawn workspace_path missing)

### Change 4: MCP Draft Creation — Fire-and-Return [P1]

**Files modified**:
- `tools/gimo_server/mcp_bridge/native_tools.py` — `gimo_create_draft`, `gimo_run_task`, `gimo_propose_structured_plan`

**What**: Replaced blocking `_generate_plan_for_task()` LLM calls with instant `proxy_to_api("POST", "/ops/drafts", ...)`. MCP tools now return in <1s instead of timing out at 60s.

**Issues resolved**: #4 (MCP timeouts), #8 (team_config can't find drafts)

### Change 5: Trust Profile Unification [P2]

**Files modified**:
- `tools/gimo_server/mcp_bridge/governance_tools.py:91-106` — `gimo_get_trust_profile`

**What**: Replaced inline trust logic with `SagpGateway._get_trust_score()` as single source of truth. Returns effective scores for `["provider", "model", "tool"]` dimensions.

**Issues resolved**: #9 (trust inconsistency across 3 surfaces)

### Change 6: GICS Daemon Pre-Check [P2]

**Files modified**:
- `tools/gimo_server/services/gics_service.py:95-130` — Added node pre-check + stderr capture

**What**: `shutil.which("node")` pre-check before daemon start. Resolved node path passed to `GICSDaemonSupervisor(node_executable=node_path)`. On failure, daemon stderr is captured and logged.

**Issues resolved**: #3 (GICS not initialized — silent FileNotFoundError)

### Change 7: Missing API Routes [P3]

**Files modified**:
- `tools/gimo_server/routers/ops/config_router.py:99-120` — Added `GET /connectors/health` aggregate
- `tools/gimo_server/routers/ops/child_run_router.py:12-30` — Added `GET /child-runs` listing
- `tools/gimo_server/routers/ops/conversation_router.py:59` — Made `workspace_root` optional (default `"."`)

**Issues resolved**: #10 (connectors/health missing), #11 (child-runs list missing), #12 (threads workspace_root required)

---

## Verification

### Test Suite
```
1378 passed, 9 skipped, 11 deselected, 4 warnings in 196.66s (0:03:16)
```

### Code Review (8 parallel agents)
All 10 modified files reviewed line-by-line. Results:
- 8/8 agents: **PASS**
- 0 blocking issues found
- 1 false-positive flagged (FastAPI parameter ordering with `Annotated[Depends]` — validated by passing tests)

### Metrics
- **Lines changed**: ~120 (net additions)
- **Files modified**: 10
- **New files**: 0
- **New dependencies**: 0
- **Issues resolved**: 15/15

---

## Issue Resolution Matrix

| # | Issue | Severity | Change | Status |
|---|-------|----------|--------|--------|
| 1 | Run stuck at null stage | BLOCKER | C1 | RESOLVED |
| 2 | CLI plan/chat silent | BLOCKER | C2 | RESOLVED |
| 3 | GICS not initialized | BLOCKER | C6 | RESOLVED |
| 4 | MCP timeouts | BLOCKER | C4 | RESOLVED |
| 5 | Chat 422 error | CRITICAL | C3 | RESOLVED |
| 6 | Spawn missing workspace | CRITICAL | C3 | RESOLVED |
| 7 | Zero cost tracking | CRITICAL | C1 | RESOLVED |
| 8 | Team config draft missing | GAP | C4 | RESOLVED |
| 9 | Trust inconsistency | GAP | C5 | RESOLVED |
| 10 | Connectors health missing | GAP | C7 | RESOLVED |
| 11 | Child-runs list missing | GAP | C7 | RESOLVED |
| 12 | Threads workspace required | GAP | C7 | RESOLVED |
| 13 | Progress events ignored | FRICTION | C2 | RESOLVED |
| 14 | Halt status silent | FRICTION | C1 | RESOLVED |
| 15 | Trust default varies | INCONSISTENCY | C5 | RESOLVED |

---

## Architecture Impact

The "approval is terminal" principle is now enforced at the gate level. This means:
- **Approved runs** skip PolicyGate and RiskGate (with audit trail)
- **Unapproved runs** still receive full governance evaluation
- **Halted runs** transition to `HUMAN_APPROVAL_REQUIRED` (visible in UI/API)
- **MCP surface** uses fire-and-return pattern (no blocking LLM calls)
- **All surfaces** share the same trust scoring via `SagpGateway._get_trust_score()`

No new architectural debt introduced. Zero new files. Zero new dependencies.
