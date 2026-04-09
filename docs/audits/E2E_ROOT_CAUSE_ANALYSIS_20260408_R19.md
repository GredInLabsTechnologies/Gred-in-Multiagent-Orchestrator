# GIMO E2E R19 - Root Cause Analysis (Phase 2)

**Date**: 2026-04-08
**Round**: R19
**Phase**: 2 (Root-cause analysis)
**Input**: [`E2E_AUDIT_LOG_20260408_R19.md`](./E2E_AUDIT_LOG_20260408_R19.md)
**Investigation method**: read-only source trace in the main session against the validated R19 issue list and addenda

---

## 0. Meta-finding

R19 is not one broken flow. It is the interaction of four separate contract splits:

1. **Run pause/resume vs workflow resume are different systems.**
2. **Sub-agent spawn is an inventory-registration path, not an execution-readiness path.**
3. **Persistent telemetry exists on the graph/pipeline path, but not on the agentic chat path.**
4. **"Active run" is defined independently by multiple services and surfaces.**

Those four splits explain the highest-signal R19 findings without requiring a single exotic race or environment-only explanation.

---

## 1. Issue Map

| ID | Phase 1 issue | Root cause type | Root cause symbol(s) | Disposition | Confidence |
|---|---|---|---|---|---|
| #R19-1 | Draft/run execution halts and cannot resume | Surface-to-backend contract mismatch | `tools/gimo_server/mcp_bridge/native_tools.py::gimo_resolve_handover`, `tools/gimo_server/routers/ops/run_router.py::resume_workflow`, `tools/gimo_server/models/core.py::OpsRun` | Real product defect | HIGH |
| #R19-2 | OpenAI worker spawn bypasses provider readiness checks | Registration-only spawn path; provider readiness not enforced | `tools/gimo_server/mcp_bridge/native_tools.py::gimo_spawn_subagent`, `tools/gimo_server/services/sub_agent_manager.py::spawn_via_draft`, `tools/gimo_server/services/sub_agent_manager.py::create_sub_agent`, `tools/gimo_server/services/providers/provider_diagnostics_service.py::ProviderDiagnosticsService.report` | Real product defect | HIGH |
| #R19-3 | Cost, trust, and traces remain empty after apparent work | Chat path bypasses persistent telemetry writers; spawn path is metadata-only | `tools/gimo_server/routers/ops/conversation_router.py::chat_message`, `tools/gimo_server/services/agentic_loop_service.py::_run_loop`, `tools/gimo_server/services/graph/engine.py`, `tools/gimo_server/services/providers/service_impl.py::static_generate` | Real product defect with one expectation mismatch | HIGH |
| #R19-4 | Proof chain verifies an empty chain as valid | Vacuous-success proof semantics + narrow proof write trigger | `tools/gimo_server/services/agentic_loop_service.py::_run_loop`, `tools/gimo_server/security/execution_proof.py::ExecutionProofChain.verify`, `tools/gimo_server/services/sagp_gateway.py::verify_proof_chain` | Real product defect / misleading contract | HIGH |
| #R19-5 | Active-run status disagrees with observability metrics | Duplicated active-status taxonomies | `tools/gimo_server/services/operator_status_service.py::_active_run_snapshot`, `tools/gimo_server/services/ops/_base.py::_ACTIVE_RUN_STATUSES`, `tools/gimo_server/services/observability_pkg/observability_service.py::_compute_run_health_metrics`, `gimo_cli/config.py::ACTIVE_RUN_STATUSES` | Real product defect | HIGH |
| #R19-6 | Launcher split is operator-confusing | Two terminal contracts with no canonical delegation | `gimo.cmd`, `gimo_cli/commands/core.py::status` | Real product defect | HIGH |
| #R19-7 | `watch --timeout 5` did not honor the operator timeout | CLI flag not wired to stream read timeout | `gimo_cli/commands/run.py::watch`, `gimo_cli/stream.py::stream_events` | Real product defect | HIGH |
| #R19-8 | Raw HTTP feature matrix is auth-blocked for a local black-box operator | Expected auth boundary; operator bootstrap/docs gap | `tools/gimo_server/security/auth.py::verify_token`, `tools/gimo_server/routers/ops/common.py::_require_role`, `gimo_cli/api.py::resolve_token` | Mostly by design; docs/operator-path gap | HIGH |

---

## 2. Detailed Traces

### #R19-1 - Draft/run execution halts and cannot resume

**Reported symptom**: a real run reaches `HUMAN_APPROVAL_REQUIRED`, and `gimo_resolve_handover(run_id=...)` returns `404 Workflow not found`.

**Entry point**: `tools/gimo_server/mcp_bridge/native_tools.py::gimo_resolve_handover`

**Trace**:

- `tools/gimo_server/mcp_bridge/native_tools.py::gimo_resolve_handover`
  - first records an ops draft with `kind=hitl_decision`
  - then POSTs `/ops/workflows/{run_id}/resume`
- `tools/gimo_server/services/execution/engine_service.py`
  - on pipeline halt, writes `OpsService.update_run_status(run_id, "HUMAN_APPROVAL_REQUIRED", ...)`
- `tools/gimo_server/models/core.py::OpsRun`
  - stores run metadata, logs, lineage, policy routing
  - does **not** store a `workflow_id`
- `tools/gimo_server/routers/ops/run_router.py::resume_workflow`
  - expects `workflow_id`
  - looks up `_WORKFLOW_ENGINES[workflow_id]` or persisted workflow checkpoints
  - raises `404 Workflow not found` when no workflow exists for that ID

**Root cause**:

The MCP handover tool bridges two different execution models:

- the failing object in R19 is an **OpsRun**
- the resume endpoint it calls belongs to the **GraphEngine workflow** subsystem

The tool reuses `run_id` as `workflow_id`, but `OpsRun` and `WorkflowGraph` are not the same namespace and are not linked by a canonical ID bridge. The failure is therefore structural, not incidental.

**Blast radius**:

- Any auto-run created from `draft -> approve -> run` can halt in `HUMAN_APPROVAL_REQUIRED` without a working MCP resume path.
- The R18 claim that handover was "via draft store" is only half true: the audit entry is recorded, but the actual resume target is still the wrong subsystem.
- External surfaces calling `gimo_resolve_handover` cannot recover a halted ops run honestly.

**Fix options**:

- Add a canonical `/ops/runs/{run_id}/resume` path that resumes the paused run contract directly.
- If workflow resume is intended, persist a real `workflow_id` on the run and use that mapping explicitly rather than overloading `run_id`.
- Do not expose `gimo_resolve_handover` as a generic run-resume tool until it targets the same authoritative execution object that sets `HUMAN_APPROVAL_REQUIRED`.

**Confidence**: HIGH

### #R19-2 - OpenAI worker spawn bypasses provider readiness checks

**Reported symptom**: `python gimo.py providers test openai` reports unreachable and unauthenticated, but `gimo_spawn_subagent(provider="openai")` still returns `Spawned: ...`.

**Entry point**: `tools/gimo_server/mcp_bridge/native_tools.py::gimo_spawn_subagent`

**Trace**:

- `tools/gimo_server/mcp_bridge/native_tools.py::gimo_spawn_subagent`
  - builds `req = {"workspace_path", "modelPreference", "constraints": {... provider, model, execution_policy, task ...}}`
  - calls `SubAgentManager.spawn_via_draft(parent_id="mcp", request=req)`
  - returns a formatted string echoing the caller's requested `provider`, `model`, and `policy`
- `tools/gimo_server/services/sub_agent_manager.py::spawn_via_draft`
  - records an `OpsService.create_draft(...)`
  - swallows draft-record failures as non-fatal
  - immediately calls `create_sub_agent(...)`
- `tools/gimo_server/services/sub_agent_manager.py::create_sub_agent`
  - extracts `modelPreference`
  - ignores `constraints.provider`, `constraints.task`, and `constraints.execution_policy` for persisted runtime state
  - only persists `id`, `model`, `status`, `config`, and `worktreePath`
- `tools/gimo_server/models/sub_agent.py::SubAgent`
  - has no provider field
  - has no policy field
- `tools/gimo_server/services/providers/provider_diagnostics_service.py::ProviderDiagnosticsService.report`
  - is a separate diagnostics path used by `/ops/providers/diagnostics`
  - probes connector reachability and auth status
  - is never consulted by `gimo_spawn_subagent`
- `tools/gimo_server/services/agent_broker_service.py::spawn_governed_agent`
  - performs governance evaluation
  - still does not call diagnostics or auth probing before spawning

**Root cause**:

Sub-agent spawn is currently an **inventory-registration path**, not an **execution-readiness path**. The provider name is accepted as input but is not validated and is not even part of the persisted `SubAgent` runtime record. The MCP return string therefore overstates what actually happened.

**Blast radius**:

- Operators can believe an `openai` worker exists when only a generic sub-agent record was created.
- Governance and diagnostics are split: diagnostics can fail while spawn still succeeds.
- Any future surface using `AgentBrokerService` still inherits the same live-readiness gap unless readiness is moved into the canonical spawn path.

**Fix options**:

- Make provider diagnostics or adapter construction a hard precondition for spawn acceptance.
- Persist the authoritative chosen provider/model/policy on the spawned object instead of echoing caller input.
- Stronger design: collapse "sub-agent" into a child-run contract so spawn traverses the same provider, proof, telemetry, and status machinery as normal execution.

**Confidence**: HIGH

### #R19-3 - Cost, trust, and traces remain empty after apparent work

**Reported symptom**: after `gimo_chat` and `gimo_spawn_subagent`, cost/budget/trust/traces remain empty or zero.

**Entry point**: `tools/gimo_server/routers/ops/conversation_router.py::chat_message`

**Trace**:

- `tools/gimo_server/mcp_bridge/native_tools.py::gimo_chat`
  - POSTs `/ops/threads/{thread_id}/chat`
- `tools/gimo_server/routers/ops/conversation_router.py::chat_message`
  - calls `AgenticLoopService.run(...)`
- `tools/gimo_server/services/agentic_loop_service.py::_run_loop`
  - accumulates `total_usage` and `total_cost` locally in memory
  - executes tools through `ToolExecutor`
  - persists execution proofs only for successful tool results
  - does **not** call:
    - `StorageService.cost.save_cost_event(...)`
    - `OpsService.record_model_outcome(...)`
    - `ObservabilityService.record_node_span(...)`
    - `ObservabilityService.record_structured_event(...)`
- `tools/gimo_server/services/graph/engine.py`
  - is the path that **does** call `ObservabilityService.record_node_span(...)`
  - is the path that **does** persist `CostEvent` via `self.storage.cost.save_cost_event(...)`
- `tools/gimo_server/services/providers/service_impl.py::static_generate`
  - records model outcomes via `OpsService.record_model_outcome(...)`
  - but the chat loop does not route through this path for persistent telemetry
- `tools/gimo_server/services/ops/_telemetry.py::TelemetryMixin.record_model_outcome`
  - is best-effort and returns `None` when GICS is unavailable

**Root cause**:

R19 mixes two very different kinds of "activity":

- `gimo_spawn_subagent` is currently metadata-only, so zero cost/trust/traces after spawn is structurally expected in the current implementation.
- `gimo_chat` performs real LLM/tool work, but that path keeps usage/cost mostly local and bypasses the persistent telemetry writers that the graph/pipeline path uses.

So the empty reads are partly an expectation mismatch and partly a real instrumentation gap. The current product contract does not make that distinction explicit.

**Blast radius**:

- `/ops/observability/metrics`, `/ops/observability/traces`, `/ops/trust/dashboard`, and `gimo_get_budget_status` under-report or entirely miss chat-path activity.
- The system looks governable at the control plane while leaving little durable evidence of what actually happened.
- Surfaces using the graph engine see richer telemetry than surfaces using threads/chat, violating the "one backend truth" doctrine.

**Fix options**:

- Extract one canonical telemetry wrapper for provider/tool execution and use it from both graph/pipeline and agentic chat loops.
- Treat spawn acceptance as telemetry-neutral only if the API contract explicitly says "registered, not executed".
- Fail loud when persistent telemetry cannot be recorded for a path that claims authoritative execution.

**Confidence**: HIGH

### #R19-4 - Proof chain verifies an empty chain as valid

**Reported symptom**: `gimo_verify_proof_chain(thread_id=...)` returns `valid=true` with `length=0`.

**Entry point**: `tools/gimo_server/mcp_bridge/governance_tools.py::gimo_verify_proof_chain`

**Trace**:

- `tools/gimo_server/mcp_bridge/governance_tools.py::gimo_verify_proof_chain`
  - delegates to `SagpGateway.verify_proof_chain(thread_id=...)`
- `tools/gimo_server/services/sagp_gateway.py::verify_proof_chain`
  - loads raw proofs from storage
  - if none exist, returns `{"thread_id": ..., "valid": True, "length": 0}`
- `tools/gimo_server/services/agentic_loop_service.py::_run_loop`
  - calls `_persist_execution_proof(...)` only when `result_status == "success"` for a tool call
- `tools/gimo_server/security/execution_proof.py::ExecutionProofChain.verify`
  - iterates over `self._proofs`
  - returns `True` if the list is empty

**Root cause**:

The implementation defines proof chains as a hash chain over **successful tool executions**, not over threads or agent turns generally. The verifier then treats "no proofs recorded" as vacuous validity. The surface contract is therefore misleading: it sounds like a thread-execution proof, but it is actually a tool-success proof with empty-chain success semantics.

**Blast radius**:

- Governance snapshot can show `proof_chain_length=0` while the verifier still says valid.
- Operators may infer successful attestation where there is only absence of evidence.
- Any thread whose useful work is descriptive text, denied HITL, or halted pre-tool will look "verified" despite having no proof entries.

**Fix options**:

- Return an explicit `"no_proofs": true` or `valid=false` when length is zero.
- Rename the exposed concept to something narrower like `tool_proof_chain` if empty success is intentionally retained.
- Persist proofs for a broader execution unit if the product wants to attest thread/run execution rather than only successful tool calls.

**Confidence**: HIGH

### #R19-5 - Active-run status disagrees with observability metrics

**Reported symptom**: `python gimo.py status` reports an active run in `HUMAN_APPROVAL_REQUIRED`, while `python gimo.py observe metrics` reports `active_runs=0`.

**Entry point**: `tools/gimo_server/services/operator_status_service.py::get_status_snapshot`

**Trace**:

- `tools/gimo_server/services/operator_status_service.py::_active_run_snapshot`
  - iterates `OpsService.list_runs()`
  - returns the first run whose status is not terminal
  - therefore treats `HUMAN_APPROVAL_REQUIRED` as active
- `gimo_cli/config.py::ACTIVE_RUN_STATUSES`
  - includes `HUMAN_APPROVAL_REQUIRED`
- `tools/gimo_server/services/execution/run_worker.py::_is_still_active`
  - includes `HUMAN_APPROVAL_REQUIRED`
- `tools/gimo_server/services/ops/_base.py::_ACTIVE_RUN_STATUSES`
  - excludes `HUMAN_APPROVAL_REQUIRED`
- `tools/gimo_server/services/observability_pkg/observability_service.py::_compute_run_health_metrics`
  - hardcodes `active_statuses = {"pending", "running", "awaiting_subagents"}`
  - excludes `HUMAN_APPROVAL_REQUIRED`
- `tools/gimo_server/routers/ops/graph_router.py::_get_graph_for_active_runs`
  - also hardcodes an active set that excludes `HUMAN_APPROVAL_REQUIRED`

**Root cause**:

There is no single canonical "run is active" predicate. Different parts of the system use:

- non-terminal status
- a local hardcoded active set
- a different local hardcoded active set

Approval-paused runs land exactly in the gap between those definitions.

**Blast radius**:

- status snapshots, metrics, graph views, completion ratios, and stale-run logic can disagree for the same run
- anything downstream using `active_runs` for alerting or SLOs undercounts paused but unresolved executions
- the system violates the one-backend-truth invariant for a core lifecycle concept

**Fix options**:

- Define one canonical `is_active_run_status()` in the authoritative ops layer and consume it everywhere.
- Treat `HUMAN_APPROVAL_REQUIRED` explicitly as active-or-paused, but do so uniformly across status, metrics, graph, and worker reconciliation.
- Remove hardcoded status subsets from surfaces and helper services.

**Confidence**: HIGH

### #R19-6 - Launcher split is operator-confusing

**Reported symptom**: `gimo.cmd status` fails as unknown, while `python gimo.py status` is a valid authoritative command.

**Entry point**: `gimo.cmd`

**Trace**:

- `gimo.cmd`
  - dispatches only `up/start/down/stop/doctor/bootstrap/mcp/claude/help`
  - sends unknown commands directly to an error/help path
  - does not delegate unknown verbs to the Typer CLI
- `gimo_cli/commands/core.py::status`
  - implements the authoritative status command for the Python CLI
- `gimo_cli/commands/*`
  - implement the richer operator surface (`status`, `providers`, `observe`, `trust`, `threads`, `run`, `skills`, etc.)

**Root cause**:

The repo exposes two different terminal contracts:

- `gimo.cmd` as a narrow batch launcher
- `python gimo.py` as the real Typer operator CLI

The wrapper does not forward or unify with the richer CLI, yet the repo docs and launcher rules still present `gimo.cmd` as the official entry point.

**Blast radius**:

- operator confusion about which commands are canonical
- inconsistent ergonomics between docs, batch wrapper, and Python CLI
- additional room for drift whenever one surface evolves and the other does not

**Fix options**:

- Make `gimo.cmd` a true delegating front door for the Typer CLI after handling its launch-only shortcuts.
- Or explicitly narrow the docs so `gimo.cmd` is only the process launcher and `python gimo.py` is the operator CLI.
- Do not keep both as peer user-facing contracts.

**Confidence**: HIGH

### #R19-7 - `watch --timeout 5` does not honor the operator timeout

**Reported symptom**: `python gimo.py watch --timeout 5` did not return within roughly 5 seconds.

**Entry point**: `gimo_cli/commands/run.py::watch`

**Trace**:

- `gimo_cli/commands/run.py::watch`
  - accepts `timeout_seconds`
  - passes it to `stream_events(config, timeout_seconds=timeout_seconds)`
- `gimo_cli/stream.py::stream_events`
  - defines `SSE_IDLE_TIMEOUT_SECONDS = 120`
  - builds `httpx.Timeout(read=SSE_IDLE_TIMEOUT_SECONDS if timeout_seconds > 0 else None, ...)`
  - therefore ignores the numeric value of `timeout_seconds`
  - the flag only changes "finite timeout vs no timeout", not "5 seconds vs 120 seconds"

**Root cause**:

The CLI flag is wired at the call site but not at the transport layer. The implementation uses a fixed 120-second SSE idle timeout no matter what value the operator passed.

**Blast radius**:

- operator automation cannot rely on `watch --timeout N`
- the CLI advertises a control it does not actually provide
- Phase 1 timeouts become shell-timeout artifacts instead of trustworthy CLI behavior

**Fix options**:

- Use `read=timeout_seconds` in `stream_events(...)` when the caller supplies a finite timeout.
- If reconnection semantics require a different internal idle timeout, separate the public CLI timeout from the internal stream idle timeout and name them honestly.

**Confidence**: HIGH

### #R19-8 - Raw HTTP feature matrix is auth-blocked for a local black-box operator

**Reported symptom**: anonymous `/ops/*` HTTP calls return `401 Unauthorized`, leaving only `/health`, `/ops/health/info`, and `/auth/check` reachable.

**Entry point**: `tools/gimo_server/security/auth.py::verify_token`

**Trace**:

- `tools/gimo_server/security/auth.py::verify_token`
  - accepts Bearer token or session cookie
  - resolves role from token
- `tools/gimo_server/routers/ops/common.py::_require_role`
  - enforces operator/admin access on ops routes
- `docs/SECURITY.md`
  - states all API endpoints require `Authorization: Bearer <TOKEN>`
- `docs/SYSTEM.md`
  - states all endpoints require Bearer unless explicitly public
- `gimo_cli/api.py::resolve_token`
  - shows the local operator bootstrap path already exists through:
    - CLI bond
    - env vars
    - `.gimo_credentials`
    - legacy token files
    - inline config

**Root cause**:

This Phase 1 finding is mostly **not** a backend bug. The backend is intentionally protected. The real gap is that the black-box HTTP probing path did not surface the local token bootstrap that the CLI already knows how to use. In other words: the product contract and the audit expectation were misaligned.

**Blast radius**:

- direct curl-only audits without token discovery under-report the authenticated HTTP surface
- local operators may think the HTTP API is unavailable when it is merely protected
- this is primarily a docs/operator-path gap unless a truly unauthenticated local bootstrap was intended

**Fix options**:

- Do not weaken auth to make black-box probing easier.
- Improve the operator-facing docs/skill path so local HTTP probes include token bootstrap steps.
- Keep this issue out of the main product-defect fix cluster unless the intended contract changes.

**Confidence**: HIGH

---

## 3. Systemic Patterns

### Pattern A - Parallel execution domains with no canonical bridge

The repo has at least three execution-related domains:

- ops runs (`OpsRun`)
- graph workflows (`WorkflowGraph` / GraphEngine)
- sub-agent inventory (`SubAgent`)

R19-1 and R19-2 are both failures of bridging across those domains. Each domain has its own IDs, persistence, and lifecycle, but the surfaces expose them as if they were one unified control plane.

### Pattern B - Registration and diagnostics are decoupled from execution truth

Spawn registration, provider diagnostics, and actual provider execution are separate paths. That split makes it easy for the system to say:

- provider unreachable
- worker spawned

without any contradiction at the implementation level. The contradiction only appears at the operator surface.

### Pattern C - Telemetry is path-specific, not contract-specific

Graph/pipeline execution records cost events, node spans, and some structured metrics. Agentic chat does not. Sub-agent spawn does not. Proof writes are narrower still. This is why R19 sees control-plane activity without durable payload-plane evidence.

### Pattern D - Lifecycle vocabularies are duplicated

`HUMAN_APPROVAL_REQUIRED` is the clearest example:

- active in some services
- non-terminal in others
- absent from core active-status sets elsewhere

Any status model duplicated that many times will drift again.

### Pattern E - Thin-client discipline is not consistently enforced

The repo doctrine says surfaces should be thin clients of one backend truth. R19 shows multiple counterexamples:

- `gimo.cmd` and `python gimo.py` expose different terminal truths
- metrics and status compute "active" differently
- proof surfaces and chat execution disagree on what counts as attestable work

---

## 4. Preventive Risks

1. As long as `OpsRun`, `WorkflowGraph`, and `SubAgent` remain parallel execution objects, future pause/resume and status bugs will keep reappearing at the surface boundary.
2. As long as provider readiness lives only in diagnostics, any new spawn surface can regress into "accepted structurally, unproven operationally".
3. As long as persistent telemetry is attached to some execution paths but not others, product claims about trust, cost, traces, and proofs will remain path-dependent.
4. As long as active-status sets are hardcoded in multiple places, approval-paused and recoverable runs will continue to drift across surfaces.
5. As long as the batch launcher and Typer CLI are separate contracts, documentation and operator expectations will keep diverging.

---

## 5. Prioritized Fix Order

| Priority | Issue(s) | Why |
|---|---|---|
| P0 | #R19-1 | A real halted run cannot be resumed through the exposed MCP handover path. This blocks payload-plane closure. |
| P0 | #R19-2 | Spawn acceptance is not authoritative about provider readiness or even provider identity. This makes recursive-governance claims non-honest. |
| P1 | #R19-3 + #R19-4 | Telemetry/proof instrumentation must be unified before cost/trust/proof surfaces can be trusted. |
| P1 | #R19-5 | One canonical run-status predicate is required for status, metrics, graphing, and reconciliation to agree. |
| P2 | #R19-6 + #R19-7 | Terminal-surface coherence matters operationally, but these are secondary to execution honesty. |
| P3 | #R19-8 | Improve docs/operator bootstrap; do not treat protected `/ops/*` routes as a backend defect by default. |

---

## 6. Phase 3 Direction

The strongest in-scope Phase 3 plan should aim for:

- one canonical paused-run resume contract
- one canonical spawn contract that validates real provider readiness
- one shared telemetry/proof middleware for every execution path
- one shared run-status taxonomy reused by ops core, observability, and CLI
- one terminal entry contract, even if it keeps launch shortcuts

Anything weaker will likely fix symptoms while leaving the same multi-surface drift classes alive.

---

Phase 2 was read-only. No product code was modified.
