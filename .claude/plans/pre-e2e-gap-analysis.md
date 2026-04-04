# GIMO Pre-E2E Gap Analysis

> Audit date: 2026-04-04
> Scope: Full codebase exploration across backend, frontend, storage, types, middleware, and integration points.

---

## Executive Summary

After a thorough exploration of the entire codebase (353 Python backend files, 156 frontend TS/TSX files, Next.js web app), the system is architecturally sound and most components are production-ready. However, there are **12 gaps** that could surface during E2E testing, categorized by severity.

---

## CRITICAL (3) - Will likely break E2E flows

### 1. Checkpoint Resume is a Placeholder
- **Location**: `tools/gimo_server/routers/ops/checkpoint_router.py:235,260`
- **Issue**: Both `_resume_plan_generation()` and `_resume_run_execution()` return hardcoded fake-success responses with zero logic.
- **Impact**: Any E2E scenario that checkpoints and resumes will silently "succeed" without actually resuming anything.
- **Fix**: Implement actual resume logic or mark endpoints as `501 Not Implemented` so tests fail clearly.

### 2. GICS Soft-Fail Causes Silent Data Loss
- **Location**: `tools/gimo_server/services/storage_service.py:21-26`
- **Issue**: `StorageService` accepts `gics=None` and silently no-ops all persistence:
  - `save_cost_event()` → silently skips
  - `save_eval_report()` → returns 0
  - `save_trust_event()` → returns without saving
- **Impact**: If GICS is not properly initialized at startup, cost tracking, trust events, and eval reports all disappear. Tests relying on persistence will pass but with no data stored.
- **Fix**: Fail hard if GICS is None, or at minimum expose a health check that reports GICS status.

### 3. `useAgentComms` Hook is Fully Mocked
- **Location**: `tools/orchestrator_ui/src/hooks/useAgentComms.ts`
- **Issue**: Agent messaging is entirely stubbed out:
  ```typescript
  export function useAgentComms(_agentId: string | null) {
      useEffect(() => {
          console.warn('useAgentComms: backend endpoints not implemented yet');
      }, []);
      return { messages: [], loading: false, error: null, sendMessage: async () => null, refresh: async () => {} };
  }
  ```
- **Impact**: Any E2E flow that involves inter-agent communication via the UI will show no messages.
- **Fix**: Wire to backend `/ops/{agent_id}/messages` endpoint or clearly disable the feature in the UI.

---

## HIGH (4) - Will cause incorrect data or confusing failures

### 4. Cost Event Timestamps Silently Dropped
- **Location**: `tools/gimo_server/services/storage/cost_storage.py:36-71`
- **Issue**: Events with malformed timestamps are silently dropped via `except ValueError: pass`. No logging, no counter.
- **Impact**: `get_daily_costs()`, `get_roi_leaderboard()`, `get_cascade_stats()` will have missing data with no indication why.
- **Fix**: Log dropped events at WARNING level and add a counter metric.

### 5. Trust Records Query Scans Entire Database
- **Location**: `tools/gimo_server/services/storage/trust_storage.py:110-129`
- **Issue**: `list_trust_records()` uses `prefix=""` (scans everything) and relies on a fragile heuristic (`"approvals" in fields and "dimension_key" in fields`).
- **Impact**: Records missing either field are silently excluded. In production with many GICS entries, this will be slow and incomplete.
- **Fix**: Use explicit prefix (e.g., `"tr:"`) and validate record structure.

### 6. eval_run_id vs run_id Field Mismatch
- **Location**: `tools/gimo_server/models/eval.py:44` vs `tools/gimo_server/services/storage/eval_storage.py:29`
- **Issue**: Model defines `eval_run_id`, but storage writes `run_id`. On read-back, `eval_run_id` is always `None`.
- **Impact**: Code expecting `report.eval_run_id` to match stored data will get `None`.
- **Fix**: Unify naming to use `eval_run_id` everywhere or alias properly.

### 7. Threat Level Middleware Can Cascade-Block Tests
- **Location**: `tools/gimo_server/middlewares.py:32-84`
- **Issue**: Adversarial/chaos tests that trigger errors can escalate threat level to LOCKDOWN, which then blocks ALL subsequent unauthenticated requests with 503.
- **Impact**: Test ordering matters. Early adversarial tests can break later tests.
- **Fix**: Reset threat level between test suites, or provide a test-mode override.

---

## MEDIUM (3) - Potential issues under specific conditions

### 8. CostPredictor Creates StorageService Without GICS
- **Location**: `tools/gimo_server/services/economy/cost_predictor.py`
- **Issue**: `CostPredictor(storage=None)` creates `StorageService()` with `gics=None`, silently losing all cost predictions.
- **Impact**: Cost predictions work but are never persisted. Dashboards show stale or missing data.
- **Fix**: Require explicit GICS injection or fail fast.

### 9. CheckpointService Requires Manual `set_gics()` Call
- **Location**: `tools/gimo_server/services/checkpoint_service.py:15-34`
- **Issue**: Uses class variable singleton pattern. Every handler must call `CheckpointService.set_gics()` before use or get `RuntimeError`.
- **Impact**: If any new router forgets to call `set_gics()`, it crashes mid-request.
- **Fix**: Use proper dependency injection (FastAPI `Depends()`) instead of manual singleton.

### 10. GIMO WEB URL Defaults to External Vercel URL
- **Location**: `tools/gimo_server/config.py`
- **Issue**: `GIMO_WEB_URL` defaults to `https://gimo-web.vercel.app`. In air-gapped/Cold Room mode or local E2E tests without internet, Firebase login fails.
- **Impact**: E2E tests with Firebase auth flow will fail in offline environments.
- **Fix**: Detect Cold Room mode and skip Firebase verification, or require explicit `GIMO_WEB_URL` in tests.

---

## LOW (2) - Minor or by-design issues

### 11. All Storage Operations Swallow Exceptions
- **Location**: All classes in `tools/gimo_server/services/storage/`
- **Issue**: Pattern `try: self.gics.put(...) except Exception: logger.error(...)` with no re-raise. Calling code never knows persistence failed.
- **Impact**: Data loss is invisible. E2E tests won't detect storage failures.
- **Fix**: At minimum, add a metric counter for failed operations. Consider re-raising for critical paths.

### 12. PlanNode Legacy Fields Leak During Serialization
- **Location**: `tools/gimo_server/models/plan.py:43-93`
- **Issue**: Legacy fields (`model`, `provider`, `agent_preset`, etc.) marked `exclude=True` are still in the Pydantic schema. Strict deserializers may reject them.
- **Impact**: API consumers parsing PlanNode JSON with strict validation may encounter unexpected fields.
- **Fix**: Move legacy fields to a separate migration utility or remove entirely.

---

## Missing Test Coverage for E2E

| Area | Status | Risk |
|------|--------|------|
| Frontend E2E (Playwright/Cypress) | **Zero tests** | HIGH - No automated UI flow testing |
| `apps/web` (Next.js) | **Zero tests** | HIGH - License/auth flows untested |
| Checkpoint resume flow | **Stubbed** | CRITICAL - Always returns fake success |
| Inter-agent messaging | **Mocked** | HIGH - `useAgentComms` is a no-op |
| Cold Room auth flow | **No E2E test** | MEDIUM - Air-gapped mode untested |
| Integration tests in CI | **Excluded from main CI** | MEDIUM - Only adversarial tests run |

---

## Pre-E2E Checklist

Before running E2E, ensure:

- [ ] GICS is initialized and `StorageService.gics` is not `None`
- [ ] `ORCH_TOKEN`, `ORCH_ACTIONS_TOKEN`, `ORCH_OPERATOR_TOKEN` are set (avoid auto-gen in containers)
- [ ] `GIMO_INTERNAL_KEY` matches between backend and web app (for Firebase flow)
- [ ] `DEBUG=false` to test production CORS behavior
- [ ] Threat level is reset between test suites
- [ ] Checkpoint resume endpoints are either implemented or marked 501
- [ ] `useAgentComms` feature is hidden/disabled in the UI if not wired

---

## Components Verified as Production-Ready

These areas passed the audit with no significant gaps:

- **Agents**: All 8 implementations complete with error handling (AgentCatalog, SubAgentManager, AgenticLoop, GraphPatterns)
- **Classifiers**: Intent, ModelRouter, and RuleEngine all complete with comprehensive decision matrices
- **Retrievers**: ContextIndexer and ConstraintCompiler with path traversal protection
- **Auth Flow**: Token, Firebase, and Cold Room mechanisms properly implemented
- **SSE/Streaming**: EventSource with keep-alive, proper disconnect handling
- **CORS**: Correctly configured with debug flexibility
- **Pipeline Engine**: Multi-stage execution with rollback, retries, and self-healing
- **Provider Adapters**: Anthropic and OpenAI-compat adapters complete
- **Frontend-Backend Integration**: API_BASE resolution, proxy config, and cookie auth all matching
