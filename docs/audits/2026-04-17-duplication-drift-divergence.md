# Daily Repository Audit: Duplication, Contract Drift, and Multi-Surface Divergence

**Date**: 2026-04-17
**Auditor**: Automated (Claude Code)
**System of Record**: AGENTS.md, docs/SYSTEM.md, docs/CLIENT_SURFACES.md, docs/SECURITY.md
**Owner**: @Shiloren

---

## Executive Summary

Eight confirmed findings clustered under four root causes. The most severe is a
19-value-vs-5-value status enum split between the Python backend `OpsRunStatus`
and the TypeScript `OpsRun.status` type, which means 14 backend run states are
invisible to the Orchestrator UI. The second most severe is a MoodName/MoodType
fork where 6 moods exist in the execution engine but cannot be assigned through
the routing contract. All findings trace to two systemic gaps: (1) no automated
schema generation from backend Pydantic models to frontend TypeScript types, and
(2) no compile-time or boot-time contract parity assertion between Python Literals
and TypeScript union types.

No findings required GitHub issue triage. All conclusions are grounded in direct
code inspection.

---

## Confirmed Duplicate Implementations

### Finding 1 — ProviderHealth Dual Definition (Same Name, Different Shape)

| Field | Value |
|---|---|
| **Severity** | P1 — silent type collision |
| **Duplicated capability** | Provider health representation |
| **Affected surfaces** | Orchestrator UI |
| **Affected subsystem** | Provider health monitoring |
| **Affected paths** | `tools/orchestrator_ui/src/types.ts:269-275`, `tools/orchestrator_ui/src/hooks/useProviderHealth.ts:5-11` |
| **Evidence** | `types.ts` defines `ProviderHealth` as `{provider_id, available, latency_ms, error, last_check}`. `useProviderHealth.ts` defines a **different** `ProviderHealth` as `{connected, health, providerName, model, loading}`. Both are exported. Consumers import from different locations and get different shapes under the same name. |
| **Rule violated** | One backend truth, no duplicated contracts (AGENTS.md §Product Truth) |
| **Current canonical source** | None — two competing definitions |
| **Missing canonical source** | A single `ProviderHealth` type in `types.ts` that covers both use cases |
| **Smallest unifying fix** | Merge into one interface in `types.ts`. The hook should consume `types.ts`'s definition and map the backend response into it. |
| **Priority** | P1 — any consumer importing the wrong one gets silent type mismatch |
| **Labels** | `contract-drift`, `orchestrator-ui`, `provider` |

### Finding 2 — Client-Side Terminal Status Hardcoding

| Field | Value |
|---|---|
| **Severity** | P1 — execution progress bar lies |
| **Duplicated capability** | Terminal run status classification |
| **Affected surfaces** | Orchestrator UI (graph progress), backend (run lifecycle) |
| **Affected subsystem** | Run lifecycle, graph visualization |
| **Affected paths** | `tools/orchestrator_ui/src/components/Graph/useGraphStore.ts:216`, `tools/gimo_server/services/run_lifecycle.py:18-31` |
| **Evidence** | Frontend hardcodes terminal statuses as `['done', 'failed', 'error', 'doubt', 'skipped']` (5 values). Backend `TERMINAL_RUN_STATUSES` has 11 values: `done, error, cancelled, MERGE_CONFLICT, VALIDATION_FAILED_TESTS, VALIDATION_FAILED_LINT, RISK_SCORE_TOO_HIGH, BASELINE_TAMPER_DETECTED, PIPELINE_TIMEOUT, WORKTREE_CORRUPTED, ROLLBACK_EXECUTED`. Frontend misses 6 true terminal statuses and includes 2 statuses (`doubt`, `skipped`) that don't exist in the backend lifecycle at all. |
| **Rule violated** | No surface may compute status truth the backend already knows (AGENTS.md §Architectural Rules: Backend authority first) |
| **Current canonical source** | `run_lifecycle.py:TERMINAL_RUN_STATUSES` |
| **Missing canonical source** | Frontend should consume a backend-supplied terminal status set or derive from the same source |
| **Smallest unifying fix** | Add a `GET /ops/meta/status-vocabulary` endpoint (or embed in `/ops/config`) that returns `{terminal: [...], active: [...]}`. Frontend imports from there instead of hardcoding. |
| **Priority** | P1 — progress bar shows wrong completion % for 6 terminal states |
| **Labels** | `contract-drift`, `client-truth-violation`, `orchestrator-ui`, `run-lifecycle` |

---

## Confirmed Duplicate Contracts

### Finding 3 — OpsRun Status Enum: 19 Backend Values vs 5 Frontend Values

| Field | Value |
|---|---|
| **Severity** | P0 — multi-surface parity blocker |
| **Duplicated capability** | Run status vocabulary |
| **Affected surfaces** | All (backend defines 19, Orchestrator UI consumes 5) |
| **Affected subsystem** | Run lifecycle |
| **Affected paths** | `tools/gimo_server/models/core.py:13-33` (19 values), `tools/orchestrator_ui/src/types.ts:467` (5 values: `'pending' \| 'running' \| 'done' \| 'error' \| 'cancelled'`) |
| **Evidence** | Backend `OpsRunStatus` Literal defines: pending, running, done, error, cancelled, awaiting_subagents, awaiting_review, MERGE_LOCKED, MERGE_CONFLICT, VALIDATION_FAILED_TESTS, VALIDATION_FAILED_LINT, RISK_SCORE_TOO_HIGH, BASELINE_TAMPER_DETECTED, PIPELINE_TIMEOUT, WORKTREE_CORRUPTED, ROLLBACK_EXECUTED, WORKER_CRASHED_RECOVERABLE, HUMAN_APPROVAL_REQUIRED, AWAITING_MERGE. Frontend `OpsRun.status` only knows 5. The other 14 are silently dropped or rendered as if they don't exist. |
| **Rule violated** | One backend truth; no surface-specific lie or drift (AGENTS.md §Product Truth); all surfaces must converge on canonical backend contracts (CLIENT_SURFACES.md §Parity Closure) |
| **Current canonical source** | `models/core.py:OpsRunStatus` |
| **Missing canonical source** | Frontend type that matches all 19 values |
| **Smallest unifying fix** | Update `types.ts:OpsRun.status` to include all 19 backend values. Ideally auto-generate from OpenAPI spec. |
| **Priority** | P0 — UI cannot display or act on 14 of 19 possible run states |
| **Labels** | `contract-drift`, `parity-blocker`, `orchestrator-ui`, `run-lifecycle` |

### Finding 4 — OpsRun Model Field Drift (28+ Backend Fields vs 6 Frontend Fields)

| Field | Value |
|---|---|
| **Severity** | P1 — data loss at the UI boundary |
| **Duplicated capability** | OpsRun data contract |
| **Affected surfaces** | Orchestrator UI |
| **Affected subsystem** | Run display, run inspection |
| **Affected paths** | `tools/gimo_server/models/core.py:100-136` (28+ fields), `tools/orchestrator_ui/src/types.ts:464-471` (6 fields: id, approved_id, status, log, started_at, created_at) |
| **Evidence** | Backend `OpsRun` includes: risk_score, stage, run_key, lock_id, heartbeat_at, parent_run_id, child_run_ids, spawn_depth, model_tier, agent_preset, execution_policy_name, routing_snapshot, resume_context, attempt, rerun_of, and more. None of these exist in the frontend type. |
| **Rule violated** | Contracts must be honest (AGENTS.md §Completion Standard); surfaces consume the same backend contracts (CLIENT_SURFACES.md) |
| **Current canonical source** | `models/core.py:OpsRun` |
| **Missing canonical source** | Frontend `OpsRun` that mirrors backend fields |
| **Smallest unifying fix** | Extend `types.ts:OpsRun` with all backend fields (most as optional). Generate from OpenAPI spec to prevent future drift. |
| **Priority** | P1 — InspectPanel, OpsFlow, BackgroundRunner cannot show fractal runs, risk scores, or stage information |
| **Labels** | `contract-drift`, `orchestrator-ui` |

### Finding 5 — MoodName vs MoodType Fork (8 vs 14 Moods)

| Field | Value |
|---|---|
| **Severity** | P1 — 6 moods unreachable through routing |
| **Duplicated capability** | Agent mood vocabulary |
| **Affected surfaces** | Backend (routing vs execution) |
| **Affected subsystem** | Agent routing, mood engine |
| **Affected paths** | `tools/gimo_server/models/agent_routing.py:11` (`MoodName`: 8 moods), `tools/gimo_server/engine/moods.py:18-33` (`MoodType`: 14 moods) |
| **Evidence** | `MoodName` = neutral, assertive, calm, analytical, exploratory, cautious, collaborative, didactic. `MoodType` adds: forensic, executor, dialoger, creative, guardian, mentor. `ResolvedAgentProfile.mood` and `RoutingDecision` use `MoodName`, so the routing system can never assign the 6 extra moods even though the engine supports them. `LEGACY_MOOD_TO_CANONICAL` in `agent_catalog_service.py:106` maps some legacy names but does not bridge MoodType→MoodName. |
| **Rule violated** | No duplicated business logic unless explicitly justified (AGENTS.md §Product Truth) |
| **Current canonical source** | Split — routing uses `MoodName`, engine uses `MoodType` |
| **Missing canonical source** | One canonical mood vocabulary that both routing and engine share |
| **Smallest unifying fix** | Extend `MoodName` to include all 14 moods from `MoodType`, or make `MoodType` the single Literal imported everywhere. Remove the separate `MoodType` definition. |
| **Priority** | P1 — 6 moods are dead code in practice because routing can't assign them |
| **Labels** | `contract-drift`, `agent-routing`, `mood-engine` |

### Finding 6 — Circuit Breaker State Naming: "half-open" vs "half_open"

| Field | Value |
|---|---|
| **Severity** | P2 — string mismatch between trust and governance subsystems |
| **Duplicated capability** | Circuit breaker state representation |
| **Affected surfaces** | Backend (governance evaluation, trust dashboards) |
| **Affected subsystem** | Trust engine, governance verdicts |
| **Affected paths** | `tools/gimo_server/models/policy.py:80` (`circuit_state: Literal["open", "closed", "half-open"]`), `tools/gimo_server/models/governance.py:28` (`circuit_breaker_state: str` with comment `"closed" \| "open" \| "half_open"`) |
| **Evidence** | `TrustRecord` uses `"half-open"` (hyphenated). `GovernanceVerdict` uses `"half_open"` (underscored) and is typed as bare `str` instead of a Literal, so the mismatch is not caught at compile time. Any equality check between the two will silently fail. |
| **Rule violated** | Explicit contracts over ambient magic (AGENTS.md §Quality Standard); no heuristic lies (AGENTS.md §Product Truth) |
| **Current canonical source** | `policy.py:TrustRecord.circuit_state` (Literal-typed, stronger) |
| **Missing canonical source** | A shared `CircuitBreakerState` Literal type imported by both models |
| **Smallest unifying fix** | Define `CircuitBreakerState = Literal["open", "closed", "half_open"]` once, import in both models. Normalize `TrustRecord` to use underscore. Type `GovernanceVerdict.circuit_breaker_state` as this Literal. |
| **Priority** | P2 — string mismatch causes silent comparison failure |
| **Labels** | `contract-drift`, `trust-engine`, `governance` |

---

## Cross-Surface Drift

### Finding 7 — Legacy `/ui/status` Computes Status from Filesystem (Not Canonical Service)

| Field | Value |
|---|---|
| **Severity** | P2 — parallel status truth |
| **Duplicated capability** | System status computation |
| **Affected surfaces** | Orchestrator UI (frontend calls `/ui/status`) |
| **Affected subsystem** | Status reporting |
| **Affected paths** | `tools/gimo_server/routers/legacy_ui_router.py:46-65` (probes filesystem → `"RUNNING"/"DEGRADED"`), canonical path: `OperatorStatusService.get_status_snapshot()` used by `/ops/operator/status` and MCP `gimo_get_status` |
| **Evidence** | Line 55-56: `is_healthy = base_dir.exists() and os.access(base_dir, os.R_OK)` then `status_str = "RUNNING" if is_healthy else "DEGRADED"`. This is a filesystem heuristic, not the canonical `OperatorStatusService`. MCP and CLI use the canonical service. Web UI uses this legacy endpoint. Two different status truth paths for the same capability. The file header says "will be migrated to /ops/* equivalents in a future iteration." |
| **Rule violated** | No surface may compute state the backend already knows (CLIENT_SURFACES.md §GIMO Core); prefer authoritative backend services (AGENTS.md §Architectural Rules) |
| **Current canonical source** | `OperatorStatusService.get_status_snapshot()` |
| **Missing canonical source** | Frontend migration to use `/ops/operator/status` |
| **Smallest unifying fix** | Replace `/ui/status` implementation with a call to `OperatorStatusService.get_status_snapshot()`, or redirect frontend to `/ops/operator/status`. |
| **Priority** | P2 — two status paths live simultaneously; documented as legacy but still serving live traffic |
| **Labels** | `legacy-parallel-path`, `status`, `orchestrator-ui` |

---

## Client-Side Truth Violations

### Finding 8 — Client-Side Node Type and Role Inference in useGraphStore

| Field | Value |
|---|---|
| **Severity** | P2 — client invents node classification the backend should supply |
| **Duplicated capability** | Node type/role classification |
| **Affected surfaces** | Orchestrator UI |
| **Affected subsystem** | Graph visualization |
| **Affected paths** | `tools/orchestrator_ui/src/components/Graph/useGraphStore.ts:127-156` |
| **Evidence** | `normalizeServerNodes()` infers `node_type`, `role`, `model`, `provider`, `is_orchestrator` from raw server data using client-side heuristics: `serverType === 'bridge' ? 'orchestrator' : serverType === 'orchestrator' ? 'orchestrator' : 'worker'`. Defaults missing status to `'pending'`, missing model to `'auto'`, missing trustLevel to `'autonomous'`. These are business-domain classifications that the backend should supply authoritatively in the graph response. |
| **Rule violated** | UI must not invent backend truth (AGENTS.md §TypeScript / Frontend); no client-side inferred truth (AGENTS.md §Architectural Rules) |
| **Current canonical source** | Backend graph service (supplies raw data without explicit node_type/role) |
| **Missing canonical source** | Backend graph response should include canonical `node_type`, `role`, `is_orchestrator` fields |
| **Smallest unifying fix** | Extend backend graph node response to include `node_type`, `role`, `is_orchestrator`, `trust_level` fields. Remove inference logic from `normalizeServerNodes()`. |
| **Priority** | P2 — heuristic guesses about orchestrator vs worker identity |
| **Labels** | `client-truth-violation`, `orchestrator-ui`, `graph` |

---

## Legacy Parallel Paths

- **Deprecated launcher scripts** (`scripts/ops/start_orch.cmd`, `scripts/ops/mcp_server.cmd`, `scripts/ops/launch_full.cmd`): All properly marked `DEPRECATED` and redirect to canonical `gimo.cmd`. Low risk but should be deleted when migration period ends.
- **`scripts/ops/start_orch.sh`**: Launches uvicorn directly instead of going through `gimo_cli/commands/server.py:start_server()`. Functionally equivalent but a second launcher path.
- **`gimo.py`** (repo root): Backwards-compatible re-export shim. Does not duplicate logic — delegates to `gimo_cli` package. Acceptable.
- **Router-level status mutation** in `custom_plan_router.py:136` (`status: "running"`) and `conversation_router.py:176` (`status: "completed"`): These assign status at the HTTP handler level rather than delegating to service-layer FSM. Low blast radius but violates the pattern that status transitions flow through `OpsService.update_run_status()`.

---

## Docs / Tests / Runtime Mismatches

- **CLIENT_SURFACES.md Parity Table** (line 92): Documents Web status as `/ui/status` with note "legacy — migrate to `/ops/operator/status`". This accurately reflects the current state but confirms the legacy path is still the live path for Web.
- **No contract parity tests exist**: There is no test that asserts TypeScript type definitions match Python Pydantic models. The MCP bridge has a boot-time `assert_no_drift()` guard for MCP tool schemas (good), but no equivalent exists for REST→UI type contracts.

---

## Top Root Causes

| # | Root Cause | Findings Affected |
|---|---|---|
| **RC-1** | **No automated schema generation from Python Pydantic to TypeScript types.** All frontend types are manually maintained in `types.ts`. Every backend model change silently drifts from frontend. | F3, F4 (OpsRun status + fields), F1 (ProviderHealth), F2 (terminal statuses) |
| **RC-2** | **Status vocabulary is defined as Python Literals with no cross-surface contract test.** Backend can add statuses freely; frontend never knows. Terminal/active classification lives in `run_lifecycle.py` but is re-hardcoded in JS. | F2, F3 |
| **RC-3** | **Mood system forked into two Literal types during iterative growth.** `MoodName` was the routing contract; `MoodType` was the engine contract. New moods were added to the engine but not the router. | F5 |
| **RC-4** | **Legacy `/ui/*` router not migrated.** Documented as transitional but still serves live traffic with non-canonical status computation. | F7 |

---

## Next 1-3 Canonicalization Moves

### Move 1: Unify OpsRunStatus Across Backend and Frontend (Fixes F2, F3, F4)

**What**: Generate `types.ts` OpsRun types from the backend OpenAPI spec (`GET /ops/openapi.json`), or at minimum manually sync `OpsRun.status` to all 19 values and `OpsRun` fields to match `core.py:OpsRun`. Replace the hardcoded terminal status list in `useGraphStore.ts:216` with a set derived from the backend (either via a new `/ops/meta/status-vocabulary` endpoint or by importing the full status union and marking terminal ones explicitly).

**Why highest leverage**: This single change fixes the P0 parity blocker (F3), eliminates the progress bar lie (F2), and opens the path to showing fractal run depth, risk scores, and stage in the UI (F4).

**Affected files**:
- `tools/orchestrator_ui/src/types.ts` (extend OpsRun)
- `tools/orchestrator_ui/src/components/Graph/useGraphStore.ts:216` (remove hardcoded terminal list)

### Move 2: Merge MoodName and MoodType into One Literal (Fixes F5)

**What**: Replace `MoodType` in `engine/moods.py` with an import of `MoodName` from `models/agent_routing.py`, after extending `MoodName` to include all 14 moods. Delete the separate `MoodType` definition.

**Why**: 6 moods are currently dead code — they exist in the engine but are unreachable through routing. One Literal type eliminates the fork.

**Affected files**:
- `tools/gimo_server/models/agent_routing.py:11` (extend MoodName)
- `tools/gimo_server/engine/moods.py:18-33` (delete MoodType, import MoodName)

### Move 3: Normalize Circuit Breaker State + Type GovernanceVerdict Field (Fixes F6)

**What**: Define `CircuitBreakerState = Literal["open", "closed", "half_open"]` in `models/policy.py`. Import it in both `TrustRecord` and `GovernanceVerdict`. Normalize `TrustRecord` from `"half-open"` to `"half_open"`. Type `GovernanceVerdict.circuit_breaker_state` as the Literal instead of bare `str`.

**Why**: Smallest possible change (3 lines) that eliminates a silent string comparison failure between two core security subsystems.

**Affected files**:
- `tools/gimo_server/models/policy.py:80`
- `tools/gimo_server/models/governance.py:28`
