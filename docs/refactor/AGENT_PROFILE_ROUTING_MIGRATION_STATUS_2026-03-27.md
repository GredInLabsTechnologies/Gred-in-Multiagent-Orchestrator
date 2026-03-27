# Agent Profile + Routing Migration Status (2026-03-27)

## Purpose

This document records the implementation slice completed for the "Plan Oficial De
Migracion: Perfil De Agente + Routing De Nodos + Learning GICS", what changed in
the repository, what was verified, and what still remains before the plan can be
considered complete.

This is a status document, not a replacement for the master plan.

## What Was Implemented

The repository now has a real first migration slice covering:

- canonical plan/node models outside the service layer
- canonical routing/profile models
- behavior-only moods
- execution-policy authority for filesystem/network/shell/tool gating and budget
- normalized plan materialization for both structured and conversational plan shapes
- explicit per-node routing metadata and binding metadata
- conversation approval flow modeled with `workflow_phase` instead of `mood_transition`

## Files Added

- `tools/gimo_server/models/agent_routing.py`
- `tools/gimo_server/models/plan.py`
- `tools/gimo_server/services/agent_catalog_service.py`
- `tools/gimo_server/services/execution_policy_service.py`
- `tools/gimo_server/services/task_descriptor_service.py`
- `tools/gimo_server/services/task_fingerprint_service.py`
- `tools/gimo_server/services/constraint_compiler_service.py`
- `tools/gimo_server/services/profile_router_service.py`
- `tools/gimo_server/services/profile_binding_service.py`
- `tests/unit/test_task_descriptor_service.py`
- `tests/unit/test_profile_router_service.py`

## Existing Files Changed

- `tools/gimo_server/engine/moods.py`
- `tools/gimo_server/engine/tools/chat_tools_schema.py`
- `tools/gimo_server/engine/tools/executor.py`
- `tools/gimo_server/mcp_bridge/native_tools.py`
- `tools/gimo_server/models/__init__.py`
- `tools/gimo_server/models/conversation.py`
- `tools/gimo_server/ops_models.py`
- `tools/gimo_server/routers/ops/conversation_router.py`
- `tools/gimo_server/services/agentic_loop_service.py`
- `tools/gimo_server/services/custom_plan_service.py`
- `tools/gimo_server/services/role_profiles.py`
- `tools/gimo_server/services/sandbox_service.py`
- targeted tests updated around moods, plan approval, plan DAGs, and gate behavior

## Delivered Behavior

### 1. Canonical plan/node ownership moved out of the service

`PlanNode`, `PlanEdge`, `CustomPlan`, and related request/binding/routing helper
models now live in `tools/gimo_server/models/plan.py`.

`custom_plan_service.py` no longer defines those models.

### 2. Canonical routing/profile types now exist

The repo now has typed internal models for:

- `TaskDescriptor`
- `TaskConstraints`
- `ResolvedAgentProfile`
- `RoutingDecision`
- `RoutingDecisionSummary`
- `TaskFingerprintParts`

These live in `tools/gimo_server/models/agent_routing.py`.

### 3. `mood` no longer acts as the permission authority

`tools/gimo_server/engine/moods.py` was reduced to behavior-only mood data:

- prompt prefix
- temperature
- max turns
- response style

The old permission semantics moved into
`tools/gimo_server/services/execution_policy_service.py`.

`ToolExecutor` now enforces:

- filesystem mode
- network mode
- domain allowlists
- tool allowlists
- confirmation requirements
- shell command patterns
- per-turn budget
- post-write auto-checks

from `execution_policy`, not from `mood`.

### 4. Structured and conversational plans now materialize through a common path

`tools/gimo_server/services/task_descriptor_service.py` normalizes:

- structured plan shape using `agent_assignee` + `depends`
- conversational plan shape using `agent_mood` + `depends_on` + top-level `model`

This prevents the previous loss of:

- `depends_on`
- mood hints
- model hints
- rationale text

### 5. Plan nodes now persist explicit routing metadata

When a plan is materialized, each node now gets persisted fields such as:

- `agent_preset`
- `binding_mode`
- `execution_policy`
- `workflow_phase`
- `task_fingerprint`
- `task_descriptor`
- `resolved_profile`
- `routing_decision_summary`
- `routing_reason`
- `routing_schema_version`
- `profile_schema_version`

### 6. Node execution now uses per-node profile/binding metadata

`CustomPlanService._execute_node()` now passes:

- mood
- execution policy
- provider
- model
- task role
- workflow phase

into `AgenticLoopService.run_node()` from the node's resolved profile/binding
instead of defaulting to `mood="executor"` as the normal behavior.

### 7. Conversational approval flow now uses `workflow_phase`

Approving a proposed plan now moves the thread to:

- `workflow_phase="executing"`

Rejecting a proposed plan now moves the thread to:

- `workflow_phase="planning"`

The MCP/native surface summary was updated accordingly.

## Phase Status Against The Official Plan

### Phase 0 — Canon Del Nodo Y Del Routing

Status: effectively complete for the backend slice implemented here.

Delivered:

- canonical node/plan schema extracted into `models/plan.py`
- canonical routing schema introduced in `models/agent_routing.py`
- exports wired through `models/__init__.py` and `ops_models.py`
- `custom_plan_service.py` no longer owns productive model definitions

Remaining:

- no further work required for this phase before moving on

### Phase 1 — Separar `mood` De Permisos

Status: partial, not 100%.

Delivered:

- behavior-only moods
- `execution_policy_service.py`
- `ToolExecutor` permission enforcement from policy
- policy-derived budgeting inside `AgenticLoopService._run_loop()`
- `role_profiles.py` reduced to shim behavior

Still missing:

- all productive call sites should receive explicit `execution_policy` directly,
  rather than deriving it from legacy mood when absent
- compatibility should be confined strictly to input edges
- `role_profiles.py` should be removed entirely after callers are migrated

### Phase 2 — Descriptor De Tarea Y Fingerprint

Status: partial, not 100%.

Delivered:

- `TaskDescriptorService`
- `TaskFingerprintService`
- common normalization for structured and conversational tasks
- `custom_plan_service.py` now uses descriptor/fingerprint during materialization

Still missing:

- descriptor/fingerprint are not yet the universal canonical path across every
  runtime entrypoint and graph workflow path
- broader adoption outside `CustomPlanService` is still pending

### Phase 3 — Compilador De Constraints

Status: partial, not 100%.

Delivered:

- `ConstraintCompilerService`
- basic allowed-policy envelope per task semantic
- `binding_mode` defaults to `plan_time`

Still missing:

- full integration with `RuntimePolicyService`
- full integration with `IntentClassificationService`
- full integration with `WorkspacePolicyService`
- full integration with `ProviderTopologyService`
- strict runtime allowlist semantics for real `binding_mode="runtime"`

### Phase 4 — `ProfileRouter` Y Binding Real

Status: partial.

Delivered:

- deterministic preset routing via `ProfileRouterService`
- deterministic provider/model binding via `ProfileBindingService`
- routing summary + routing reason persisted on nodes

Still missing:

- proper integration with `ModelRouterService` as subordinate binding logic
- GICS-assisted score adjustment
- explicit objective ordering implementation:
  security -> success -> quality -> latency -> cost

### Phase 5 — Materializacion Correcta De Planes Y Threads

Status: partial.

Delivered:

- `propose_plan` now supports `agent_preset`
- conversation approval passes the full proposed plan to materialization
- thread model now includes `agent_preset`, `workflow_phase`, `profile_summary`

Still missing:

- thread service lazy hydration for old thread objects
- stricter write-new/read-old handling for every thread persistence path
- full removal of legacy phase semantics from all surfaces

### Phase 6 — `CustomPlanService` Ejecuta Perfiles Reales

Status: partial.

Delivered:

- node prompt composition now includes execution profile context
- node execution uses per-node resolved profile and binding metadata
- node execution no longer relies on `node.config.get("mood", "executor")` as
  the normal control path

Still missing:

- complete removal of fallback dependence on the orchestrator adapter for every
  plan-node runtime path
- broader observability proofing of the resolved profile during execution

### Phase 7 — GraphEngine Y WorkflowGraph

Status: not started.

Still missing:

- `models/workflow.py`
- `services/graph/engine.py`
- `services/graph/node_executor.py`
- `services/graph/agent_patterns.py`

These still need to consume the same routing/profile canon.

### Phase 8 — Learning GICS Por Fingerprint Y Perfil

Status: not started.

Still missing:

- `tools/gimo_server/services/profile_learning_service.py`
- new GICS routing namespaces
- routing outcome persistence in `run_worker.py`
- aggregate profile learning in capability/GICS services
- telemetry and observability updates for profile-based learning

### Phase 9 — Surface Parity Y Catalogo Canonico

Status: not started, except for a small MCP/native text update.

Still missing:

- `tools/gimo_server/routers/ops/agent_profiles_router.py`
- catalog exposure via backend
- cross-surface parity for web/CLI/TUI/MCP/App
- backend-sourced catalog/resolve views for clients

### Phase 10 — Compatibilidad De Datos Legacy

Status: not started in the full sense.

Still missing:

- explicit lazy hydration for legacy threads, plans, and runs
- read-old/write-new strategy enforcement across persistence boundaries
- `legacy_backfill` routing reasons for old nodes

### Phase 11 — Limpieza Final

Status: not started.

Still missing:

- remove `role_profiles.py` shim
- remove remaining legacy mood-only phase assumptions
- update system/docs files to the new truth

## Verification Executed

The following focused suite was run after the migration slice:

```powershell
python -m pytest -q `
  tests/test_moods.py `
  tests/test_mood_contracts.py `
  tests/test_meta_tools.py `
  tests/test_plan_approval.py `
  tests/test_plan_dag.py `
  tests/test_custom_plan_router.py `
  tests/unit/test_agentic_loop.py `
  tests/unit/test_phase_5b_gate.py `
  tests/unit/test_mastery_plan_economy_routes.py `
  tests/unit/test_task_descriptor_service.py `
  tests/unit/test_profile_router_service.py
```

Result:

- `87 passed`

## Recommended Next Implementation Order

To complete the plan cleanly, the next work should proceed in this order:

1. Finish Phase 7
   - port `WorkflowGraph` and graph runtime to the new profile/routing canon

2. Finish Phase 8
   - add `profile_learning_service.py`
   - connect GICS routing namespaces and learning loops

3. Finish Phase 9
   - expose backend catalog/resolve routes
   - enforce cross-surface parity

4. Finish Phases 10-11
   - explicit legacy hydration
   - docs update
   - remove shims and forbidden shortcuts

## Current Verdict

This migration is no longer speculative. The repository now has the first real
architectural slice in place.

But the official plan is not complete.

The current state should be treated as:

- foundational migration completed
- full-system rollout still pending
