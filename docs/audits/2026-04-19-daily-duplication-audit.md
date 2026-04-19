# GIMO Daily Repository Audit — 2026-04-19

**Focus**: Duplication, contract drift, multi-surface divergence
**System of record**: AGENTS.md, docs/SYSTEM.md, docs/CLIENT_SURFACES.md, docs/SECURITY.md
**Owner**: @Shiloren

---

## Executive Summary

Seven confirmed findings, clustered under four root causes. The MCP bridge layer is clean — all 36 tools are thin wrappers with a boot-time drift guard (`assert_no_drift`). The CLI/TUI surface properly delegates to backend services for all critical operations. The serious problems are concentrated in two areas:

1. **TypeScript type definitions in `tools/orchestrator_ui/src/types.ts`** independently redefine Pydantic contracts and have drifted significantly. OpsRun exposes 5 of 20 status values and 6 of 30+ fields. ProviderType exposes 9 of 33 values. SubAgent exposes 9 of 19 fields.

2. **The Orchestrator UI performs optimistic status mutations and uses hardcoded status subsets**, meaning the frontend can show stale or incomplete state that diverges from backend truth.

A secondary cluster involves the merge gate's synthetic policy fallback (diverges from canonical `RuntimePolicyService`) and the legacy `/ui/status` endpoint (parallel status computation).

No findings require emergency action. All are addressable by enforcing one canonical path without architectural changes.

---

## Confirmed Duplicate Implementations

### Finding 1: Policy Evaluation Triplicated — Merge Gate Diverges

- **Severity**: P1
- **Duplicated capability**: Runtime policy evaluation (allow/review/deny decision)
- **Affected surfaces**: Backend (all surfaces indirectly)
- **Affected subsystem**: Execution pipeline, merge gate
- **Affected paths**:
  - `tools/gimo_server/routers/ops/plan_router.py:81-104` — draft-creation-time evaluation
  - `tools/gimo_server/engine/stages/policy_gate.py:11-63` — execution-time re-evaluation
  - `tools/gimo_server/services/merge_gate_service.py:47-87` — merge-time re-evaluation from cached context
- **Evidence**:
  - `plan_router.py:82` and `policy_gate.py:24` both call `RuntimePolicyService.evaluate_draft_policy()` with identical parameter shapes. The first populates draft context; the second re-evaluates at execution time (intentional defense-in-depth per R17 Cluster A.5 comment at line 12).
  - `merge_gate_service.py:47-61` does NOT call `RuntimePolicyService`. Instead it reads `context.get("policy_decision")` and creates a synthetic `policy_fallback_*` ID when `policy_decision_id` is absent (line 55). Line 60-61: `if not policy_decision: policy_decision = "allow"` — this can produce an allow decision without any service evaluation.
  - Risk validation at merge gate (lines 66-87) uses hardcoded thresholds (`risk_score >= 60`, `31 <= risk_score < 60`) not shared with any other evaluation path.
- **Architectural rule violated**: "prefer authoritative backend services and contracts; avoid client-side inferred truth" (AGENTS.md). The merge gate infers policy from cached context rather than re-querying the canonical service.
- **Current canonical source**: `RuntimePolicyService.evaluate_draft_policy()` in `tools/gimo_server/services/runtime_policy_service.py`
- **Smallest unifying fix**: Make `merge_gate_service._validate_policy()` call `RuntimePolicyService.evaluate_draft_policy()` instead of reading from cached context. Remove the synthetic fallback. Extract risk thresholds into a shared constant or service method.
- **Priority**: P1 — the synthetic fallback can produce allow decisions without going through canonical policy evaluation, which is a governance bypass risk.
- **Labels**: `governance`, `duplication`, `merge-gate`, `security`

---

### Finding 2: Legacy `/ui/status` Endpoint — Parallel Status Computation

- **Severity**: P2
- **Duplicated capability**: System status computation
- **Affected surfaces**: Web (Orchestrator UI), any consumer of `/ui/status`
- **Affected subsystem**: Status aggregation
- **Affected paths**:
  - `tools/gimo_server/routers/legacy_ui_router.py:46-65` — `/ui/status` (legacy)
  - `tools/gimo_server/services/operator_status_service.py` — canonical `OperatorStatusService.get_status_snapshot()`
  - `tools/gimo_server/routers/ops/ops_routes.py:148-155` — `/ops/operator/status` (canonical)
- **Evidence**:
  - `/ui/status` computes its own health check (`base_dir.exists() and os.access(base_dir, os.R_OK)` at line 55), formats its own status string (`"RUNNING (ChatGPT)"` / `"RUNNING (Dashboard)"` at line 64), and returns a `UiStatusResponse` shape that differs from the canonical `OperatorStatusService` snapshot.
  - It performs user-agent sniffing (line 58: `"openai" in user_agent`) to label the caller — a client-side inference that the backend should not perform.
  - CLIENT_SURFACES.md Parity Closure table (line 92) explicitly marks this endpoint as `*(legacy — migrate to /ops/operator/status)*`.
- **Architectural rule violated**: "one backend truth; no surface-specific lie, drift, or duplicated business logic" (AGENTS.md). Legacy endpoint acknowledged in docs but still serving live traffic.
- **Current canonical source**: `OperatorStatusService.get_status_snapshot()` → `/ops/operator/status`
- **Smallest unifying fix**: Redirect `/ui/status` to `/ops/operator/status` or remove it entirely. Update any remaining Orchestrator UI code that calls `/ui/status`.
- **Priority**: P2 — docs already acknowledge this as legacy; removal is safe. No governance risk, but it is a live parallel path.
- **Labels**: `legacy`, `status`, `duplication`, `cleanup`

---

## Confirmed Duplicate Contracts

### Finding 3: TypeScript Type Definitions Independently Redefine Backend Contracts

- **Severity**: P1
- **Duplicated capability**: Data contracts (Pydantic models ↔ TypeScript interfaces)
- **Affected surfaces**: Orchestrator UI
- **Affected subsystem**: Type system, API contract boundary
- **Affected paths**:
  - `tools/orchestrator_ui/src/types.ts` — all TypeScript contract definitions
  - `tools/gimo_server/models/core.py` — Python canonical contracts
  - `tools/gimo_server/models/provider.py` — ProviderType
  - `tools/gimo_server/models/sub_agent.py` — SubAgent
- **Evidence** (verified by direct file inspection):

  | Contract | Python canonical | TypeScript shadow | Drift |
  |---|---|---|---|
  | **OpsRun** | `core.py:100-136` — 30+ fields, 20 status values (`OpsRunStatus` at line 13-33) | `types.ts:464-471` — 6 fields, 5 status values | **CRITICAL**: missing 24+ fields, 15 status values |
  | **ProviderType** | `provider.py:4-12` — 33 values | `types.ts:232-241` — 9 values (includes `'custom'` which doesn't exist in Python) | **CRITICAL**: missing 24 providers, 1 invented |
  | **SubAgent** | `sub_agent.py:17-41` — 19 fields | `types.ts:213-222` — 9 fields | Missing: `worktreePath`, `description`, `provider`, `executionPolicy`, `draftId`, `runId`, `routing`, `delegation`, `authority`, `source` |
  | **OpsTask** | `core.py:50-58` — 8 fields | `types.ts:393-400` — 7 fields | Missing: `agent_assignee` |
  | **OpsDraft** | `core.py:76-89` — 11 fields | `types.ts:412-436` — 9 fields | Missing: `operator_class`; `datetime` → `string` |

- **Architectural rule violated**: "No duplicated business logic across CLI/TUI, web, MCP, or ChatGPT App façades unless explicitly justified" (AGENTS.md). These are independent re-implementations, not generated from the canonical source.
- **Current canonical source**: Pydantic models in `tools/gimo_server/models/`
- **Missing canonical source**: No TypeScript generation pipeline from Pydantic/OpenAPI schema
- **Smallest unifying fix**: Generate TypeScript types from the FastAPI OpenAPI schema (`/ops/openapi.json`) at build time. Tools like `openapi-typescript` produce types from OpenAPI specs. The MCP bridge already uses `OpenAPIProvider` for zero-drift tool generation — the same principle should apply to the UI.
- **Priority**: P1 — OpsRun's 5-of-20 status coverage means the UI cannot render 75% of possible run states. ProviderType's 9-of-33 coverage means provider management UI is structurally incomplete.
- **Labels**: `contract-drift`, `types`, `orchestrator-ui`, `codegen`

---

## Cross-Surface Drift

### Finding 4: UI Polling Uses Hardcoded Status Subset — Misses 6 Active Statuses

- **Severity**: P1
- **Duplicated or drifting capability**: Active-run detection for polling
- **Affected surfaces**: Orchestrator UI
- **Affected subsystem**: Run lifecycle awareness
- **Affected paths**:
  - `tools/orchestrator_ui/src/hooks/useOpsService.ts:61` — UI polling logic
  - `tools/gimo_server/services/run_lifecycle.py:3-14` — canonical `ACTIVE_RUN_STATUSES`
- **Evidence**:
  - `useOpsService.ts:61`: `runs.some(r => r.status === 'pending' || r.status === 'running')` — checks 2 statuses.
  - `run_lifecycle.py:3-13`: `ACTIVE_RUN_STATUSES` contains 8 values: `pending`, `running`, `awaiting_subagents`, `awaiting_review`, `MERGE_LOCKED`, `WORKER_CRASHED_RECOVERABLE`, `HUMAN_APPROVAL_REQUIRED`, `AWAITING_MERGE`.
  - A run in `AWAITING_MERGE` or `HUMAN_APPROVAL_REQUIRED` will not trigger polling. The UI will stop refreshing and appear frozen while the run is actually active and awaiting user action.
- **Architectural rule violated**: "no surface may compute or invent state, lifecycle, or run status that the backend already knows" (audit invariant). The UI invents its own definition of "active."
- **Current canonical source**: `ACTIVE_RUN_STATUSES` in `run_lifecycle.py`
- **Smallest unifying fix**: Either (a) the UI imports the active status set from a generated type, or (b) the backend exposes a `has_active_runs` boolean in the run list response, making the UI's polling decision server-driven.
- **Priority**: P1 — runs in `HUMAN_APPROVAL_REQUIRED` or `AWAITING_MERGE` will not be polled, so the operator may not see that action is needed.
- **Labels**: `cross-surface-drift`, `lifecycle`, `orchestrator-ui`, `polling`

---

## Client-Side Truth Violations

### Finding 5: Optimistic Status Mutations Without Server Confirmation

- **Severity**: P2
- **Duplicated or drifting capability**: Draft approval/rejection status
- **Affected surfaces**: Orchestrator UI
- **Affected subsystem**: Ops lifecycle (drafts)
- **Affected paths**:
  - `tools/orchestrator_ui/src/hooks/useOpsService.ts:110-111` — approval optimistic update
  - `tools/orchestrator_ui/src/hooks/useOpsService.ts:128` — rejection optimistic update
- **Evidence**:
  - Line 110-111: After `fetchWithRetry` returns OK, the hook sets `d.status = 'approved' as const` in local state. However, the actual approved status comes from `data.approved` in the response — the local draft mutation is redundant and could diverge if the server returns a different status.
  - Line 128: `setDrafts(prev => prev.map(d => d.id === id ? { ...d, status: 'rejected' as const } : d))` — the server response is not read back. If the server-side status is different (e.g., `error`), the UI will show `rejected`.
  - This is not truly optimistic (the mutation happens AFTER the API call succeeds), but it replaces server truth with client-asserted truth.
- **Architectural rule violated**: "No surface may compute or invent state" (CLIENT_SURFACES.md line 10). "UI must not invent backend truth" (AGENTS.md TypeScript rules).
- **Current canonical source**: Backend `OpsService` response via `/ops/drafts/{id}/approve` and `/ops/drafts/{id}/reject`
- **Smallest unifying fix**: After successful API call, re-read the draft from the server response (which is already available in `data.approved`) rather than manually setting status. For rejection, read the response body to get the server-authoritative status.
- **Priority**: P2 — the mutation occurs after success so divergence is unlikely in practice, but the pattern violates the invariant and sets a bad precedent.
- **Labels**: `client-truth`, `orchestrator-ui`, `lifecycle`

---

## Legacy Parallel Paths

### Finding 6: Notice and Notification Systems Not Integrated

- **Severity**: P2
- **Duplicated capability**: Operational alerting (notices to operators)
- **Affected surfaces**: All (notices appear in `/ops/operator/status` snapshots; notifications broadcast via SSE)
- **Affected subsystem**: Alerting
- **Affected paths**:
  - `tools/gimo_server/services/notice_policy_service.py:7-56` — static context-evaluated notices (budget, context usage, merge status)
  - `tools/gimo_server/services/notification_service.py:29-199` — async event-based SSE broadcasts
- **Evidence**:
  - `NoticePolicyService.evaluate_all()` generates notices from a context snapshot (e.g., budget alerts at line 19-34, merge status at line 48-54). These are embedded in the status snapshot returned by `OperatorStatusService`.
  - `NotificationService.publish()` broadcasts events via SSE (line 107-124) for critical actions (`action_requires_approval`, `security_alert`, etc.).
  - The two systems have no integration: `AWAITING_MERGE` generates a notice but not a notification event. `action_requires_approval` generates a notification but not a notice.
  - A surface using polling gets notices; a surface using SSE gets notifications. Neither gets both.
- **Architectural rule violated**: "all surfaces must converge on canonical backend contracts" (audit invariant). Two parallel alerting paths fragment the operator's awareness.
- **Current canonical source**: Neither is canonical — both are partial.
- **Missing canonical source**: A unified alerting service that feeds both notice snapshots and SSE events.
- **Smallest unifying fix**: Make `NotificationService.publish()` the single event source. Have `NoticePolicyService` consume from `NotificationService` event history to build its snapshot, rather than independently re-evaluating context.
- **Priority**: P2 — no governance bypass risk, but operators on different surfaces get different alert sets.
- **Labels**: `parallel-paths`, `notifications`, `notices`, `alerting`

---

## Docs / Tests / Runtime Mismatches

### Finding 7: Entitlement Policy Logic Lives in apps/web Client

- **Severity**: P2
- **Duplicated or drifting capability**: License entitlement decision (allow/deny/expired)
- **Affected surfaces**: GIMO Web (apps/web)
- **Affected subsystem**: Licensing
- **Affected paths**:
  - `apps/web/src/lib/entitlement.ts:92-178` — `evaluateLicenseEntitlement()` implements full entitlement logic
  - `apps/web/src/app/api/license/validate/route.ts:79-134` — calls the entitlement function and signs JWTs
  - `tools/gimo_server/services/license_service.py` — backend license validation
- **Evidence**:
  - `evaluateLicenseEntitlement()` checks lifetime licenses (line 107), evaluates expiration (line 124), queries Stripe subscriptions (lines 133-151), and makes allow/deny decisions — all in the Next.js API route layer.
  - This is business logic that duplicates the concept of "is this user entitled?" across two separate codebases (Next.js and FastAPI).
  - The backend `license_service.py` validates licenses independently using a different code path (JWT + offline cache + Ed25519 verification).
  - The two paths may produce different entitlement decisions for the same user.
- **Architectural rule violated**: "No client (UI, CLI, App) shall compute its own state, re-implement operations, or bypass the server" (CLIENT_SURFACES.md line 10).
- **Current canonical source**: Ambiguous — both codebases implement entitlement logic. The backend is the intended authority, but apps/web runs its own evaluation.
- **Smallest unifying fix**: Move entitlement evaluation to the backend. The Next.js API route should call the backend's license validation endpoint rather than implementing its own Stripe-aware logic. Keep the Next.js route as a thin proxy.
- **Priority**: P2 — divergent entitlement decisions could cause one surface to grant access while another denies it.
- **Labels**: `client-truth`, `licensing`, `entitlement`, `apps-web`

---

## Top Root Causes

| # | Root Cause | Findings Affected | Fix Class |
|---|---|---|---|
| **RC1** | TypeScript types manually maintained instead of generated from Pydantic/OpenAPI schema | F3, F4, F5 | Codegen pipeline |
| **RC2** | Merge gate reads cached context instead of re-calling canonical policy service | F1 | Service call replacement |
| **RC3** | Two independent alerting subsystems with no integration | F6 | Service unification |
| **RC4** | License entitlement logic implemented in both Next.js and FastAPI | F7 | Proxy conversion |

RC1 is the highest-leverage root cause. Solving it eliminates three findings simultaneously and prevents future drift structurally (the MCP bridge already proves this pattern works via `OpenAPIProvider` + `assert_no_drift`).

---

## Next 1–3 Canonicalization Moves

### Move 1: Generate TypeScript types from OpenAPI schema (eliminates F3, F4, F5)

Add a build step to `tools/orchestrator_ui/` that runs `openapi-typescript` (or equivalent) against the backend's OpenAPI spec. Replace all manually-defined contract interfaces in `types.ts` with generated types. Add a CI check that fails if generated types are stale. This is the exact same principle as the MCP bridge's `OpenAPIProvider` — zero drift by construction.

- **Affected file**: `tools/orchestrator_ui/src/types.ts` (replace ~200 lines of manual interfaces)
- **Adds**: `package.json` script, CI gate
- **Evidence this works**: `mcp_bridge/server.py:128-182` already uses this pattern for MCP tools with `OpenAPIProvider`

### Move 2: Make merge gate call RuntimePolicyService (eliminates F1)

Replace `merge_gate_service._validate_policy()` lines 47-87 with a call to `RuntimePolicyService.evaluate_draft_policy()`. Remove the synthetic `policy_fallback_*` ID generation and the hardcoded risk thresholds. The merge gate should be a thin gate that queries the canonical policy service, not a parallel evaluator.

- **Affected file**: `tools/gimo_server/services/merge_gate_service.py` (~40 lines)
- **Risk**: Low — the service call is proven; only the call site changes

### Move 3: Retire `/ui/status` endpoint (eliminates F2)

Replace `/ui/status` with a redirect to `/ops/operator/status`. Update any Orchestrator UI code that still calls the legacy endpoint. This is already documented as legacy in CLIENT_SURFACES.md.

- **Affected files**: `tools/gimo_server/routers/legacy_ui_router.py`, orchestrator UI fetch calls
- **Risk**: Low — canonical endpoint already exists and is used by CLI/TUI and MCP
