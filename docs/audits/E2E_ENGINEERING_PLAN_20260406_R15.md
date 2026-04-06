# E2E Engineering Plan — R15

**Date**: 2026-04-06
**Round**: 15
**Input documents**: E2E_AUDIT_LOG_20260406_R14.md, E2E_ROOT_CAUSE_ANALYSIS_20260406_R14.md
**Design philosophy**: SYSTEM.md, AGENTS.md, CLIENT_SURFACES.md

## Diagnosis Summary

GIMO's governance control plane works correctly. The **data plane** (LLM execution, cost accumulation, GICS telemetry) has been broken since R11. Four BLOCKER issues were "resolved" in R12, R13, and R14, but none survived black-box verification. Root cause: fixes addressed symptoms without wiring existing infrastructure (AdaptiveTimeoutService, SupervisedTask, require_gics) that was already built for these exact problems.

## Design Principles

1. **Wire, don't write** — use existing infrastructure (AdaptiveTimeoutService, SupervisedTask, require_gics)
2. **Backend authority** — server emits complete data, clients are thin
3. **No silent degradation** — errors are logged, never swallowed
4. **Single source of truth** — defaults defined once at the source, not per-consumer

## Changes

### Change 1: Timeout-wrap `static_generate()` with AdaptiveTimeoutService
- **Solves**: BLOCKER 2 (CLI hangs), BLOCKER 4 (MCP -32001 timeout)
- **What**: Wrap `adapter.generate()` in `asyncio.wait_for()` with timeout from `AdaptiveTimeoutService.predict_timeout()` (bounded 30-600s, p95 + 20% margin)
- **Where**: `services/providers/service_impl.py::static_generate`
- **Verification**: `gimo plan "test"` without LLM → error within timeout

### Change 2: Fix HALT status + eliminate silent error swallowing
- **Solves**: BLOCKER 1 (runs stuck), Systemic Pattern 1 (silent errors)
- **What**: (a) Add `HUMAN_APPROVAL_REQUIRED` to `_is_still_active()` statuses. (b) Replace 4 `except Exception: pass` blocks with `logger.error()`. (c) Remove dead `DEFAULT_RUN_TIMEOUT` constant.
- **Where**: `services/execution/run_worker.py`, `routers/ops/run_router.py`
- **Verification**: Grep `except Exception: pass` in run_router.py → 0 matches (excluding risk rejection)

### Change 3: Unify trust default at source
- **Solves**: Systemic Pattern 4 (inconsistent trust defaults)
- **What**: Set `score: 0.85` in `_empty_record()` (both trust_engine.py and trust.py). Remove compensating fallback in `sagp_gateway.py`.
- **Where**: `services/trust_engine.py`, `services/trust.py`, `services/sagp_gateway.py`
- **Verification**: Fresh install trust query → `score: 0.85` across all surfaces

### Change 4: GICS degradation startup visibility
- **Solves**: BLOCKER 3 (GICS daemon_alive: false), Systemic Pattern 3 (GICS SPOF)
- **What**: Log startup warning when GICS daemon fails to start
- **Where**: `main.py`
- **Verification**: Start without Node.js → warning in startup log

### Change 5: SSE completed event enrichment
- **Solves**: BLOCKER 2 (CLI shows no content), Systemic Pattern 2 (protocol drift)
- **What**: Add `content` and `status` to SSE `completed` event payload
- **Where**: `routers/ops/plan_router.py`
- **Verification**: `gimo plan "test" --json` → output includes content

## 8-Criterion Compliance

| Criterion | YES/NO |
|-----------|--------|
| Aligned | YES |
| Potent | YES |
| Lightweight | YES |
| Multi-solving | YES |
| Innovative | YES |
| Disruptive | YES |
| Safe | YES |
| Elegant | YES |

## Residual Risks

1. No integration test for full draft→approve→execute→complete lifecycle (tests mock EngineService)
2. GICS daemon requires Node.js — no Python fallback for reliability data
3. Cascade/escalation system has never been tested in E2E
