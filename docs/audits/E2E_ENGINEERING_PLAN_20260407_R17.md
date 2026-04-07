# GIMO E2E R17 — Engineering Plan (revised after static audit)

## Context

R17 forensic audit (Phase 1 + Phase 2) catalogued **13 issues**. Root-cause analysis collapses them into **5 clusters** sharing **3 systemic patterns**: silent success gates, two sources of truth, and cascade from a dead data plane. A static audit of the first draft surfaced 6 corrections (Clusters A/C/D/E mis-scoped or invented authority). This revision incorporates all of them.

The intended outcome is to **close every silent gate and unify every duplicated source of truth using existing backend authorities** — without inventing parallel registries, breaking degraded-mode startup, or introducing false-negative invariants.

## Diagnosis

Cluster A is the highest-leverage single change but it must be framed around the **existing transition authority**, not an invented one. Cluster D must converge native and dynamic MCP registration onto a single path **without losing tools that have no `/ops/*` HTTP equivalent today**. Cluster C must preserve degraded-mode startup. Cluster E.1 is not a one-word fix — the row shape itself diverges. Cluster E.2's clean fix is a shared diagnostics helper, not cross-command reuse. The OTel `output_tokens>0` invariant from the first draft is **wrong** for merge-gate runs and is removed.

## Authoritative References (verified to exist before planning)

- `tools/gimo_server/services/ops/_run.py::OpsService.update_run_status` — **the** transition authority for run lifecycle.
- `tools/gimo_server/routers/ops/run_router.py` — three entry points: `approve_draft` (~L171), `POST /ops/runs` (~L268), `POST /ops/runs/{id}/rerun` (~L442). All three follow the optimistic `pending→running→spawn` anti-pattern.
- `tools/gimo_server/main.py::lifespan` (~L274–279) — explicit degraded-mode contract when GICS is not alive.
- `tools/gimo_server/services/gics_service.py::GicsService.start_daemon` (~L89) — current contract: log + return on missing CLI/Node.
- `tools/gimo_server/mcp_bridge/server.py` (~L160, L251) — dynamic registration only exposes `/ops/*` HTTP routes; native tools (`gimo_evaluate_action`, `gimo_estimate_cost`, `gimo_generate_team_config`, etc.) have no HTTP equivalent.
- `tools/gimo_server/mcp_bridge/governance_tools.py::gimo_evaluate_action` (~L21), `mcp_bridge/native_tools.py::gimo_generate_team_config` (~L662).
- `tests/.../test_native_tools_r16.py` (~L41) — regression coverage for native-only tools.
- `tools/gimo_server/services/trust/trust_engine.py::dashboard` (~L51, L235) — emits rows keyed by `dimension_key`, `policy`, `circuit_state`.
- `gimo_cli/render.py::TRUST_STATUS` (~L116) — expects rows with `dimension`, `score`, `state`.
- `gimo_cli/commands/auth.py::doctor` (~L375) — inlines its own provider fetch + health probe.
- `gimo_cli/commands/providers.py::providers_test` (~L145) — performs normalized auth-status check.
- `tools/gimo_server/services/observability_pkg/observability.py` (~L54) — already models estimated/imprecise token usage; treating exact-zero as failure would conflict.
- `tools/gimo_server/services/execution/engine_service.py` (~L158) — `merge_gate` runs have no `llm_execute` stage; zero output tokens is legitimate.

## Cluster A — Dead Pipeline Worker (revised)

**Resolves**: #1, #5, #6, #11, #12; partial #4.

**Files**:
- `tools/gimo_server/routers/ops/run_router.py` — `approve_draft` (~L171), `create_run` (~L268), `rerun_run` (~L442), `_spawn_run`.
- `tools/gimo_server/services/ops/_run.py::OpsService.update_run_status` (canonical authority).
- `tools/gimo_server/services/run_worker.py::_tick`.
- `tools/gimo_server/engine/stages/policy_gate.py`, `risk_gate.py`.
- `tools/gimo_server/services/execution/engine_service.py::execute_run`.
- `tools/gimo_server/resilience.py::SupervisedTask.spawn`.

**Changes**:

1. **Status-after-ack across ALL three entry points**. `_spawn_run` becomes a synchronous helper that creates the `SupervisedTask`, verifies it is not done-with-exception, and returns it. `approve_draft`, `create_run`, and `rerun_run` keep `status="pending"` until the spawn helper returns successfully, then transition to `running` **only via `OpsService.update_run_status`** — the existing authority. No router writes status directly.

2. **Heartbeat + reclamation (Sidekiq SuperFetch / Celery acks_late pattern)**. `engine_service.execute_run` writes a monotonic heartbeat on each stage transition through `OpsService.update_run_status` (or an adjacent `OpsService.heartbeat_run` if cleaner, defined in `_run.py`). `run_worker._tick` reclaims `running` runs whose heartbeat is older than `RECLAIM_TIMEOUT` (default 60s, configurable) by transitioning them back to `pending` with an audit entry. Reclamation also flows through `OpsService.update_run_status` — no direct DB writes.

3. **SupervisedTask is the only spawn path**. `SupervisedTask.spawn` registers the task in a process-wide registry; lifespan shutdown awaits drain. All three entry points spawn through it. No bare `asyncio.create_task` in execution paths.

4. **Kill the silent gate-skip**. `policy_gate.execute` and `risk_gate.execute` MUST run regardless of `approved_id`. R14.1's `gate_skipped:true` short-circuit is removed. Approval is recorded in the verdict, not used as a license to bypass evaluation. If a future "trusted replay" optimization is needed, it lives in the gateway as an explicit policy mode, never as an implicit skip.

5. **Honest-run invariant (replaces the wrong token-count invariant)**. `engine_service.execute_run` finalization asserts that **every stage that was scheduled actually executed** — i.e. no stage was silently skipped via the `approved_id` short-circuit, and the recorded `stages_executed` set equals the planned set for the run's stage profile. Merge-gate runs continue to have no `llm_execute` stage and remain valid. Violations record a `silent_skip_error` audit entry and mark the run failed. This is the structural guarantee that replaces the discarded `output_tokens>0` check, and it does not depend on token counts.

**SOTA context**: Temporal "started=acked", Argo owner-reference reclamation, Sidekiq SuperFetch visibility timeout, Google SRE fail-loudly. The honest-run invariant is structural (planned vs executed stages), not statistical (token presence).

**Verification**:
- Unit: `test_spawn_run_returns_task_and_acks`, `test_approve_draft_uses_ops_service_for_status`, `test_create_run_uses_ops_service_for_status`, `test_rerun_run_uses_ops_service_for_status`, `test_run_worker_reclaims_stale_running`, `test_policy_gate_runs_under_approved_id`, `test_engine_service_asserts_planned_stages_executed`, `test_merge_gate_run_passes_invariant_with_zero_tokens`.
- Integration: end-to-end through each of the three entry points; transitions `pending → running → done`; OTel spans non-empty for `llm_execute`-bearing runs; merge-gate run succeeds without LLM stages.
- Smoke (post-restart): re-run Phase 1 probes #1, #5, #6, #12.

## Cluster B — Silent Empty-Content Gate (unchanged)

**Resolves**: #2, #4.

**File**: `tools/gimo_server/services/agentic_loop_service.py::_run_loop` (~L803).

**Change**: Replace `if content:` silent gate with explicit hollow detection that emits a `hollow_completion_error` event, sets `finish_reason="error"`, and returns a diagnostic message. No silent skip.

**Verification**: `test_agentic_loop_hollow_completion_raises`; smoke probes #2, #4 via CLI `gimo chat` and MCP `gimo_chat`.

## Cluster C — GICS Daemon Failure Visibility (revised)

**Resolves**: #3.

**Constraint preserved**: `main.py::lifespan` (~L274, L279) is allowed to continue in degraded mode. The contract change in the first draft (raise on missing dependency) would have broken environments that currently start successfully without GICS.

**Files**:
- `tools/gimo_server/services/gics_service.py::GicsService.start_daemon`
- `tools/gimo_server/main.py::lifespan` (read-only check; no contract change)
- `tools/gimo_server/routers/ops/system_router.py` (or wherever `system/dependencies` lives — verify before edit)

**Change**:
1. `start_daemon` continues to **return** (degraded mode preserved) but **records a structured failure reason** on `self._last_start_failure: GicsStartFailure` (typed) — `cli_not_found`, `node_not_found`, `spawn_error`, etc., each with a human-readable message.
2. `system/dependencies` (and `gimo doctor`) read this field and surface the **real reason** instead of a generic "GICS offline." This converts the existing silent-but-degraded path into a loud-but-degraded path. No startup failure introduced.
3. Logging on the early-return path is upgraded from `info` to `warning` with the structured reason embedded — no behavior change for callers that don't read it.

**SOTA context**: Istio `holdApplicationUntilProxyStarts` is the strict variant; this is the **degraded-mode** variant — the OpenTelemetry "fail loud, degrade gracefully" pattern. Honest visibility, no startup regression.

**Verification**: `test_gics_start_daemon_records_cli_not_found`, `test_gics_start_daemon_records_node_not_found`, `test_system_dependencies_surfaces_gics_failure_reason`, `test_lifespan_continues_when_gics_unavailable` (regression). Smoke `gimo doctor` reports the real reason.

## Cluster D — MCP Schema Drift (revised — convergent, not destructive)

**Resolves**: #7, #9, #10, #11.

**Constraint preserved**: native-only MCP tools (`gimo_evaluate_action`, `gimo_estimate_cost`, `gimo_generate_team_config`, etc.) have **no `/ops/*` HTTP equivalent today**, and `test_native_tools_r16.py` (~L41) regression-covers them. Deleting `_register_native` before equivalents exist is a regression.

**Files**:
- `tools/gimo_server/mcp_bridge/server.py` (~L160 dynamic, ~L251 native registration)
- `tools/gimo_server/mcp_bridge/native_tools.py`
- `tools/gimo_server/mcp_bridge/governance_tools.py`

**Change** — **Convergent fix; both registries kept; one schema definition per tool**:

1. **Pydantic input models become the single schema source for each native tool**. For every native tool in `native_tools.py` and `governance_tools.py`, define an explicit `*Input` Pydantic model (e.g. `EstimateCostInput(tokens_in: int, tokens_out: int, model: str)`). The native registration uses `model_json_schema()` from this model — eliminating the hand-crafted JSONSchema that caused #9's int→string drift and the rejected param names in #7.
2. **Canonical parameter names are aligned to the names Phase 1 demonstrated to work** (`task_instructions`, `tool_name`, `plan_id`, `model_id`, `thread_id`, `run_id`). Where the previous native tools used different names, they accept both the new canonical name and a deprecated alias for one round, with a `DeprecationWarning` logged. No external breakage.
3. **#10 — `gimo_generate_team_config` regains `objective` mode** that was lost in commit f70c6e1. The Pydantic input model declares `plan_id: str | None` and `objective: str | None` with a validator requiring exactly one. Regression test added.
4. **#11 — `gimo_verify_proof_chain.thread_id` becomes optional** with server-side fallback to "most recent verified chain"; documented in the input model.
5. **`_register_dynamic` and `_register_native` are NOT merged in this round**. They remain side-by-side. Native tools whose functionality is later promoted to `/ops/*` will migrate to dynamic on a per-tool basis in a follow-up round, behind a feature flag. The R17 plan only **closes the schema-drift bug**, it does not consolidate the two registries — that is a separate, larger refactor that needs its own approval.

**SOTA context**: Pydantic `model_json_schema()` is the FastMCP idiomatic pattern; aligning native tool schemas to Pydantic models gives single-source-of-truth per tool without inventing a new registry layer.

**Verification**: per-tool contract tests for the 8 governance tools and the impacted native tools; existing `test_native_tools_r16.py` MUST still pass unchanged; new `test_estimate_cost_accepts_int_params`, `test_generate_team_config_objective_mode`, `test_verify_proof_chain_optional_thread_id`. Phase 1 Probe A re-runs clean.

## Cluster E.1 — Trust Dashboard Contract (revised — full row shape, not one word)

**Resolves**: #8.

**Root cause (corrected)**: Two mismatches, not one.
- Envelope: `trust_router.py::trust_dashboard` (~L46) returns `{"items": [...]}`; renderer expects `entries`.
- **Row shape**: `TrustEngine.dashboard()` (`trust_engine.py` ~L51, ~L235) emits rows with `dimension_key`, `policy`, `circuit_state`; `render.py::TRUST_STATUS` (~L116) reads `dimension`, `score`, `state`. Renaming the envelope alone leaves blank columns.

**Files**:
- `tools/gimo_server/services/trust/trust_engine.py::dashboard`
- `tools/gimo_server/routers/ops/trust_router.py::trust_dashboard`
- `tools/gimo_server/ops_models.py` (or wherever `TrustDashboardEntry` is defined)

**Change**:
1. Define a canonical `TrustDashboardEntry` Pydantic model with the renderer-facing fields: `dimension: str`, `score: float`, `state: str` (plus any additional fields the web UI consumes — verify before edit). The renderer is the single contract.
2. `TrustEngine.dashboard()` produces `list[TrustDashboardEntry]` — fields are renamed at the source: `dimension_key → dimension`, `circuit_state → state`, and `score` is computed from the existing trust value (already present, just under a different key — verify exact field name in `trust_engine.py` before edit).
3. `trust_router.trust_dashboard` returns `{"entries": list[TrustDashboardEntry]}`.
4. Any TUI / web consumer reading `items`, `dimension_key`, or `circuit_state` is updated to the canonical names. (Verify list of consumers before edit; included in scope.)

**Verification**: `test_trust_engine_dashboard_returns_canonical_entries`, `test_trust_dashboard_router_envelope_uses_entries`, `test_cli_trust_status_renders_non_empty_columns`. Smoke `gimo trust status`.

## Cluster E.2 — Doctor / Providers Test Divergence (revised — shared diagnostics, not cross-command call)

**Resolves**: #13.

**Root cause (corrected)**: `auth.py::doctor` (~L375) inlines its own provider fetch and health probe; `providers.py::providers_test` (~L145) calls a normalized auth-status check. Refactoring `doctor` to call `providers_test` (a CLI command) is the wrong abstraction.

**Files**:
- `gimo_cli/commands/auth.py::doctor`
- `gimo_cli/commands/providers.py::providers_test`
- New: `gimo_cli/diagnostics/provider_diagnostics.py` (small shared module) **OR** new backend endpoint `/ops/providers/diagnostics` consumed by both CLI commands.

**Change** (default: shared CLI helper; backend endpoint if review prefers backend authority):

1. Extract the normalized auth-status + health probe logic from `providers_test` into `gimo_cli/diagnostics/provider_diagnostics.py::run_provider_diagnostics(provider_id) -> ProviderDiagnosticReport` (a small typed function).
2. Both `doctor` and `providers_test` consume this helper. `doctor` no longer inlines provider probing.
3. The helper consults the backend through the existing normalized auth-status route — no new client-side inference.

**Alternative (preferred if review escalates this to backend authority)**: add `GET /ops/providers/diagnostics` that returns the structured diagnostic report; both CLI commands consume it. This conforms more strictly to "backend authority first." **This decision should be confirmed in approval.**

**Verification**: `test_run_provider_diagnostics_returns_report`, `test_doctor_uses_shared_diagnostics_helper`, `test_providers_test_uses_shared_diagnostics_helper`. Smoke `gimo doctor` reports the same auth state as `gimo providers test`.

## Removed from the first draft

- ❌ **OTel `gen_ai.usage.output_tokens > 0` invariant** — incompatible with merge-gate runs (no `llm_execute` stage) and conflicts with existing imprecise/estimated usage modeling. Replaced by the structural "planned stages executed" invariant in Cluster A.5.
- ❌ **Deletion of `_register_native`** — would regress native-only MCP tools that have no `/ops/*` equivalent. Replaced by per-tool Pydantic schema unification in Cluster D.
- ❌ **GICS startup raise** — would break degraded-mode environments. Replaced by structured failure reason + diagnostics surfacing in Cluster C.
- ❌ **`doctor` calls `providers_test` directly** — wrong abstraction. Replaced by shared diagnostics helper (or backend endpoint) in Cluster E.2.
- ❌ **Trust dashboard one-word fix** — insufficient; row shape diverges. Replaced by canonical `TrustDashboardEntry` model in Cluster E.1.

## Execution Order

1. **Cluster A** first (highest leverage, foundational). Sequential within: status-after-ack across all three entry points → SupervisedTask spawn path → reclamation → kill silent gate-skip → planned-stages-executed invariant.
2. **Cluster D**, **Cluster B**, **Cluster C**, **Cluster E.1**, **Cluster E.2** in parallel with each other (independent files).
3. After each cluster: `python -m pytest -x -q`.
4. After all clusters: smoke gate — restart server, re-run top-5 failed Phase 1 probes.
5. Full pytest suite green.

## Unification Check

| Concern | Single Source of Truth | Enforced By |
|---|---|---|
| Run lifecycle transitions | `OpsService.update_run_status` | Cluster A.1 |
| Run spawn supervision | `SupervisedTask.spawn` | Cluster A.3 |
| Governance verdict (gates always run) | `SagpGateway` + Pipeline gates | Cluster A.4 |
| Per-tool MCP schema | Per-tool Pydantic input model | Cluster D |
| Trust dashboard row shape | `TrustDashboardEntry` model | Cluster E.1 |
| Provider diagnostics | `run_provider_diagnostics` helper (or backend endpoint) | Cluster E.2 |
| Daemon health visibility | `GicsStartFailure` + `system/dependencies` | Cluster C |
| Loop completion | Explicit hollow detection | Cluster B |
| Run honesty invariant | Planned stages executed (not token count) | Cluster A.5 |

All surfaces (Web, CLI/TUI, MCP, App, SDK) traverse the same backend authority. No client-side state inference introduced. No invented authorities.

## 8-Criterion Compliance Matrix (revised)

| Criterion | Verdict | Justification |
|---|---|---|
| Aligned | YES | Uses existing `OpsService.update_run_status`, existing `SagpGateway`, existing degraded-mode lifespan contract, existing FastMCP Pydantic idiom. No invented authorities. |
| Potent | YES | Cluster A still resolves 6 issues with one structural change covering all three run entry points. |
| Lightweight | YES | Cluster D no longer deletes `_register_native`; net code change is small per cluster. Cluster C is additive (new typed failure field). |
| Multi-solving | YES | A=6, D=4, B=2, C=1, E=2 → 15 effects from 5 changes. |
| Innovative | YES | Planned-stages-executed invariant is rare; structured GICS failure reason surfaced through diagnostics is uncommon among orchestrators. |
| Disruptive | YES | Closes the silent-gate class via three independent enforcement points without breaking degraded-mode environments. |
| Safe | YES | No new authority invented; merge-gate runs preserved; degraded GICS startup preserved; native MCP tools preserved; aliases for renamed MCP params for one round. |
| Elegant | YES | Each cluster names its anti-pattern, names the existing authority that resolves it, and removes the divergence. |

## Open Approval Question

**Cluster E.2 abstraction choice**: shared CLI helper (`provider_diagnostics.py`) **or** new backend endpoint (`/ops/providers/diagnostics`)? The latter is stricter "backend authority first" (per CLIENT_SURFACES.md) but adds a new route. Recommendation: **backend endpoint**, because diagnostics is shared across surfaces (CLI, TUI, future Web). Awaiting confirmation.

## Residual Risks

- Heartbeat clock skew → mitigated by monotonic clock and conservative `RECLAIM_TIMEOUT` >> heartbeat interval.
- Removing the silent gate-skip may surface previously masked policy violations on legitimate approvals — expected and audited via verdict logs.
- MCP parameter aliasing for one round needs a deprecation tracking entry in `docs/deprecations.md` (verify file exists before edit).
- Trust dashboard row-shape change touches any web/TUI consumer — full consumer list must be enumerated before edit (added to Cluster E.1 scope).
- GICS structured failure surfacing depends on `system/dependencies` route shape — verified before edit.
- Smoke gate is enforced by Phase 4 protocol (skill mandates it).

## Critical Files Reference

- `tools/gimo_server/routers/ops/run_router.py`
- `tools/gimo_server/services/ops/_run.py`
- `tools/gimo_server/services/run_worker.py`
- `tools/gimo_server/services/execution/engine_service.py`
- `tools/gimo_server/engine/stages/policy_gate.py`
- `tools/gimo_server/engine/stages/risk_gate.py`
- `tools/gimo_server/resilience.py`
- `tools/gimo_server/services/agentic_loop_service.py`
- `tools/gimo_server/services/gics_service.py`
- `tools/gimo_server/main.py` (read-only verification)
- `tools/gimo_server/mcp_bridge/server.py`
- `tools/gimo_server/mcp_bridge/native_tools.py`
- `tools/gimo_server/mcp_bridge/governance_tools.py`
- `tools/gimo_server/services/trust/trust_engine.py`
- `tools/gimo_server/routers/ops/trust_router.py`
- `tools/gimo_server/ops_models.py`
- `gimo_cli/commands/auth.py`
- `gimo_cli/commands/providers.py`
- `gimo_cli/render.py`
- New: `gimo_cli/diagnostics/provider_diagnostics.py` OR new route in providers router

## Status

`PLAN_REVISED` — awaiting user approval (and Cluster E.2 abstraction choice).
