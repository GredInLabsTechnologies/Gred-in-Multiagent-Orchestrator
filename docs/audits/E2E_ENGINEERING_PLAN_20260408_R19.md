# R19 - Engineering Plan

**Date**: 2026-04-08
**Round**: R19 / Phase 3
**Inputs**:
- `docs/audits/E2E_AUDIT_LOG_20260408_R19.md`
- `docs/audits/E2E_ROOT_CAUSE_ANALYSIS_20260408_R19.md`
- `AGENTS.md`
- `docs/SYSTEM.md`
- `docs/CLIENT_SURFACES.md`
- `docs/SECURITY.md`
- `.github/workflows/ci.yml`

---

## 0. Diagnosis summary

R19 is the result of four contract splits, not eight unrelated bugs:

1. **Run lifecycle truth is split across `OpsRun`, workflow resume, and local status helpers.**
   This explains both the broken handover resume path and the disagreement around `HUMAN_APPROVAL_REQUIRED`.
2. **Spawn truth is weaker than execution truth.**
   The system can "spawn" a worker without proving provider readiness, persisting provider identity, or creating an executable child run.
3. **Payload-plane evidence is path-specific.**
   Graph execution persists telemetry; chat execution mostly does not; spawn is metadata-only; proof verification accepts absence of evidence.
4. **Terminal and operator entry paths are split.**
   `gimo.cmd` and `python gimo.py` expose different truths, and the direct HTTP probing path hides the authenticated operator bootstrap that the CLI already knows.

The strongest in-scope fix is to collapse those splits into one canonical run contract, one canonical execution evidence path, and one canonical terminal front door.

---

## 1. SOTA landscape (compressed, sourced)

| Concern | External pattern | What they do | Improvement for GIMO |
|---|---|---|---|
| HITL pause/resume | LangGraph `interrupt()` + `Command(resume=...)` on the same `thread_id` with persistent checkpointing; Azure Durable `wait-for-external-event` on the same orchestration instance ID ([LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), [LangGraph durable execution](https://docs.langchain.com/oss/python/langgraph/durable-execution), [Azure external events](https://learn.microsoft.com/en-us/azure/durable-task/common/durable-task-external-events)) | Persist state before waiting, resume by sending input back to the same durable execution identity | `run_id` becomes the stable resume cursor. Handover resumes the same `OpsRun` through a persisted checkpoint or resume event, not by translating into a foreign workflow namespace. |
| Child execution / delegation | Azure sub-orchestrations are first-class child orchestrations; OpenAI Agents handoffs are tool-shaped, schema-validated transfers with typed metadata ([Azure sub-orchestrations](https://learn.microsoft.com/en-us/azure/durable-task/common/durable-task-sub-orchestrations), [OpenAI handoffs](https://openai.github.io/openai-agents-js/guides/handoffs/)) | Child work is represented as an executable child unit, and routing metadata is validated before control transfers | Spawn becomes a governed child run, not inventory. Routing metadata such as `reason`, `summary`, and `priority` is schema-validated and persisted with the child execution record. |
| Execution telemetry | OpenAI Agents tracing records agent runs, generations, tool calls, handoffs, guardrails, and custom events; supports extra processors and explicit `forceFlush()` in short-lived runtimes ([OpenAI tracing JS](https://openai.github.io/openai-agents-js/guides/tracing/), [OpenAI tracing Python](https://openai.github.io/openai-agents-python/tracing/)) | One trace tree per workflow with typed spans and optional secondary exporters | GIMO should emit one root trace per run/thread group, with spans for generation, tool, handoff, and custom lifecycle events, and flush at request end where the runtime is short-lived. |
| Log/trace correlation | OpenTelemetry recommends carrying `TraceId` and `SpanId` into logs and emitting structured events under one log model ([OpenTelemetry logs](https://opentelemetry.io/docs/specs/otel/logs/)) | Correlate logs, traces, and metrics through shared execution context | GIMO evidence should stamp trace/span IDs into structured logs and observability events so chat, pipeline, and child-run activity are queryable as one execution graph. |
| Attestation / provenance semantics | SLSA provenance models attestations as explicit provenance records produced by a builder for a subject; absence of provenance is not equivalent to verified provenance ([SLSA provenance](https://slsa.dev/spec/v1.1/provenance)) | Proof/provenance is an explicit artifact with builder identity and verification semantics | GIMO proof state should become multi-state (`absent`, `present`, `invalid`) and carry executor/builder identity plus the run/thread subject instead of returning `valid=true` for an empty chain. |
| Durable state model | Azure Durable uses event sourcing and append-only history to rebuild orchestration state ([Azure durable orchestrations](https://learn.microsoft.com/en-us/azure/durable-task/common/durable-task-orchestrations)) | Persist execution history as an append-only sequence and replay from it | GIMO should prefer append-only run lifecycle and proof/evidence history over ad hoc mutable fields where pause/resume and auditability matter. |

The common SOTA pattern is consistent: durable systems do not translate pause/resume across unrelated IDs, delegation is a real child execution rather than metadata registration, and observability is recorded as one traceable execution tree.

---

## 2. Design principles

1. **One authoritative run object.**
   Pause, resume, child execution, and active-status reporting must converge on `OpsRun`, not bounce between run IDs, workflow IDs, and inventory IDs.
2. **Execution acceptance must mean executable now.**
   If a spawn call succeeds, provider readiness, routing choice, and policy binding must already be validated and persisted.
3. **Every real execution writes durable evidence through one path.**
   Cost, trust, traces, and proofs cannot stay optional or path-specific for authoritative execution surfaces.
4. **Lifecycle taxonomy is backend-authored once.**
   Surfaces and helper services consume shared predicates; they do not redefine what "active", "paused", or "resumable" means.
5. **Resume must target the same durable identity that paused.**
   `run_id` is the durable cursor for run lifecycle, mirroring the SOTA pattern of resuming the same thread/orchestration instance rather than translating into another subsystem.
6. **Delegation metadata must be typed and persisted.**
   Child execution should carry validated routing metadata, not just an echoed provider/model string.
7. **Observability needs one trace tree plus correlated logs.**
   Trace/span context must survive across chat, pipeline, handoff, and child execution paths.
8. **Attestation is multi-state.**
   Missing evidence, present evidence, and invalid evidence are different states and must not collapse into a single boolean.
9. **Keep auth fail-closed.**
   R19-8 is not a reason to widen anonymous `/ops/*`. The fix is operator bootstrap clarity, not weaker security.
10. **Use the official launcher as a delegating front door.**
   `gimo.cmd` remains the official Windows entry point, but it must forward into the same CLI contract instead of exposing a second terminal truth.

---

## 3. Change list

#### Change 1: Canonical run lifecycle contract
- **Solves**: `#R19-1`, `#R19-5`
- **What**:
  - Add one authoritative run lifecycle module in the ops core with shared predicates such as `is_active_run_status()`, `is_resumable_run_status()`, and any pause-state helpers needed for approval-gated runs.
  - Persist the data required to resume a paused `OpsRun` when execution enters `HUMAN_APPROVAL_REQUIRED`, preferably as a durable checkpoint or append-only run event instead of an opaque in-memory side channel.
  - Add a canonical `/ops/runs/{run_id}/resume` path and move `gimo_resolve_handover(...)` to that run contract.
  - Treat `/ops/workflows/{workflow_id}/resume` as workflow-internal only unless a real run-to-workflow mapping exists.
  - Replace duplicated active-status sets in operator status, observability, graph views, worker reconciliation, and CLI code with the shared lifecycle predicates.
  - Expose an explicit paused/custom status projection for external readers so the same run can report `HUMAN_APPROVAL_REQUIRED` with resumable metadata without each surface inferring it differently.
- **Where**:
  - `tools/gimo_server/models/core.py`
  - `tools/gimo_server/services/ops/`
  - `tools/gimo_server/services/execution/engine_service.py`
  - `tools/gimo_server/services/execution/run_worker.py`
  - `tools/gimo_server/services/operator_status_service.py`
  - `tools/gimo_server/services/observability_pkg/observability_service.py`
  - `tools/gimo_server/routers/ops/run_router.py`
  - `tools/gimo_server/routers/ops/graph_router.py`
  - `tools/gimo_server/mcp_bridge/native_tools.py`
  - `gimo_cli/config.py`
- **Why this design**:
  - It collapses two defects with one authoritative concept: the object that pauses is the object that resumes, and the same lifecycle predicate drives every surface.
  - It matches the durable-workflow SOTA pattern where pause/resume happens on the same durable identity (`thread_id` or orchestration instance ID), not through foreign ID translation.
  - It avoids fabricating a workflow bridge where no canonical mapping exists today.
- **Risk**:
  - Paused-run state must be persisted carefully so resume remains durable across process restarts.
  - Existing graph-workflow tests may assume the workflow resume route is user-facing.
- **Verification**:
  - Focused integration test for pause -> `HUMAN_APPROVAL_REQUIRED` -> `/ops/runs/{run_id}/resume` -> resumed completion.
  - Focused assertions that status, metrics, and graph views all classify the same paused run consistently.
  - Runtime smoke: rerun the R19 handover probe through MCP and HTTP and confirm the real run no longer sticks on the broken workflow path.

#### Change 2: Canonical child-run spawn with readiness gate
- **Solves**: `#R19-2`
- **What**:
  - Replace registration-only spawn acceptance with a governed child-run creation path under `OpsService` and the existing execution machinery.
  - Require provider readiness before spawn acceptance by resolving the real adapter or diagnostics inside the canonical spawn path.
  - Persist the authoritative chosen provider, model, and execution policy on the child execution object.
  - Persist schema-validated delegation metadata, such as `reason`, `summary`, and `priority`, alongside the child execution record instead of only echoing caller input.
  - Keep `SubAgent` only as a derived projection if the UI still needs it; it must stop being the authoritative execution record.
  - Make `gimo_spawn_subagent(...)` return the child run or draft identity plus resolved routing, not an echoed caller request.
- **Where**:
  - `tools/gimo_server/services/sub_agent_manager.py`
  - `tools/gimo_server/services/agent_broker_service.py`
  - `tools/gimo_server/services/providers/provider_diagnostics_service.py`
  - `tools/gimo_server/models/sub_agent.py`
  - `tools/gimo_server/models/core.py`
  - `tools/gimo_server/mcp_bridge/native_tools.py`
  - any UI/API reader that currently treats `SubAgent` inventory as execution truth
- **Why this design**:
  - Spawn becomes honest by construction: success means a real child execution exists and the route was actually validated.
  - It follows the stronger external pattern: Azure-style child execution objects plus OpenAI-style typed handoff metadata, rather than inventory registration with unverifiable labels.
  - It prepares a single execution object for lifecycle, telemetry, proof, and status instead of inventing more cross-domain glue.
- **Risk**:
  - Existing consumers may depend on `SubAgent` IDs or on optimistic spawn success semantics.
  - Provider readiness checks can make previously "successful" calls fail loudly, which is correct but behaviorally visible.
- **Verification**:
  - Focused regression test where provider diagnostics fail and spawn is rejected with no child run created.
  - Focused success test where spawn creates a child run with persisted provider/model/policy visible through backend status.
  - Runtime smoke: rerun `gimo_spawn_subagent(provider="openai", ...)` against a failing provider and confirm rejection instead of false success.

#### Change 3: Shared execution evidence contract with honest proof semantics
- **Solves**: `#R19-3`, `#R19-4`
- **What**:
  - Introduce one shared execution evidence writer used by the agentic chat loop, graph engine, and child-run execution path.
  - Record cost events, model outcomes, trust outcomes, observability spans/events, and proof entries from that shared path.
  - Model the evidence tree explicitly: one root trace per run, spans for agent execution, generation, tool calls, handoffs, and custom lifecycle events.
  - Correlate structured logs and observability events with `trace_id` and `span_id`.
  - Keep spawn registration explicitly telemetry-neutral until execution starts; do not let registration imply payload-plane work.
  - Change proof-chain verification so an empty chain is not reported as plain success. Return an explicit no-proof state or an equivalent non-attested result, and attach executor/builder identity plus subject/run identity to real proof records.
  - Align governance and observability readers to the same persisted evidence so chat activity and graph activity show up through the same backend truth.
  - Where the runtime is short-lived, flush buffered trace export on request shutdown so emitted evidence is not silently lost.
- **Where**:
  - `tools/gimo_server/services/agentic_loop_service.py`
  - `tools/gimo_server/services/graph/engine.py`
  - `tools/gimo_server/services/providers/service_impl.py`
  - `tools/gimo_server/services/ops/_telemetry.py`
  - `tools/gimo_server/services/observability_pkg/observability_service.py`
  - `tools/gimo_server/services/sagp_gateway.py`
  - `tools/gimo_server/security/execution_proof.py`
  - any storage layer used for cost/proof/trust/span persistence
- **Why this design**:
  - It fixes the instrumentation gap at the contract boundary instead of patching individual readers.
  - It matches the stronger external pattern of one trace tree with typed spans and optional processors/exporters, plus trace-log correlation.
  - It makes proof semantics honest without pretending that "no proof" and "verified proof" are the same state.
- **Risk**:
  - Double-writing is possible if old path-specific instrumentation is left in place during migration.
  - Proof semantics may be externally visible to clients that assumed empty-chain success.
- **Verification**:
  - Focused integration test where a chat execution emits non-zero cost/trust/trace evidence through the persistent readers.
  - Focused proof test asserting empty chain returns the new explicit non-attested state.
  - Focused observability test asserting emitted logs/events share the same `trace_id`/`span_id` lineage as the corresponding trace tree.
  - Runtime smoke: rerun `gimo_chat`, `gimo_verify_proof_chain`, `python gimo.py observe metrics`, `python gimo.py trust status`, and `python gimo.py observe traces` and confirm they now reflect the same real activity.

#### Change 4: Terminal front-door unification and timeout honesty
- **Solves**: `#R19-6`, `#R19-7`
- **What**:
  - Make `gimo.cmd` the official Windows front door that handles launcher shortcuts first and forwards all other verbs to the Typer CLI.
  - Wire `watch --timeout N` to the actual SSE read timeout instead of the current fixed 120-second idle timeout.
  - Keep help text and error messages honest about which commands are launcher-only versus general operator CLI verbs.
- **Where**:
  - `gimo.cmd`
  - `gimo.py`
  - `gimo_cli/commands/run.py`
  - `gimo_cli/stream.py`
  - any help or docs strings that describe the launcher contract
- **Why this design**:
  - It removes a needless second terminal truth without deprecating the official launcher entry point.
  - It turns a currently misleading timeout flag into a real operational control.
- **Risk**:
  - Windows quoting and exit-code propagation through the batch wrapper need careful handling.
  - Some current users may rely on the old wrapper error behavior for unsupported verbs.
- **Verification**:
  - Focused CLI tests for wrapper delegation and timeout wiring.
  - Runtime smoke: `gimo.cmd status` returns the same result shape as `python gimo.py status`.
  - Runtime smoke: `python gimo.py watch --timeout 5` and `gimo.cmd watch --timeout 5` both stop on the requested timeout order of magnitude.

#### Change 5: Authenticated HTTP bootstrap clarity without auth weakening
- **Solves**: `#R19-8`
- **What**:
  - Update operator-facing docs so local HTTP probing explicitly includes token bootstrap through the existing CLI credential resolution path.
  - Optionally add a non-secret doctor/help hint that points operators to the authenticated path instead of anonymous `/ops/*` probing.
  - Do not widen anonymous control-plane routes.
- **Where**:
  - `README.md`
  - `docs/SECURITY.md`
  - `docs/CLIENT_SURFACES.md`
  - optionally `gimo.cmd` or CLI help text, but never by printing raw secrets
- **Why this design**:
  - The bug here is expectation drift, not the auth boundary itself.
  - It keeps the system aligned with `SECURITY.md` and the fail-closed doctrine.
- **Risk**:
  - Overexplaining credential lookup in user-facing output can create unnecessary operator noise.
- **Verification**:
  - Doc audit for accuracy against `gimo_cli/api.py::resolve_token`.
  - Manual smoke: local authenticated curl against one protected `/ops/*` route using the documented bootstrap path.

---

## 4. Execution order

| Priority | Change | Why first |
|---|---|---|
| P0 | Change 1 | Resume honesty and lifecycle parity are the highest-signal execution blockers in R19. |
| P0 | Change 2 | Spawn acceptance cannot stay non-authoritative if the platform claims governed multi-agent execution. |
| P1 | Change 3 | Telemetry, trust, traces, and proofs must be unified before R19 can claim payload-plane closure honestly. |
| P2 | Change 4 | Terminal coherence matters operationally, but it should follow the core backend contract fixes. |
| P3 | Change 5 | This is an operator/docs correction and must not distract from product-truth defects. |

Recommended Phase 4 order inside the codebase:

1. Land the shared lifecycle predicates and paused-run state model.
2. Add `/ops/runs/{run_id}/resume` and rewire `gimo_resolve_handover(...)`.
3. Convert spawn into governed child-run creation with readiness checks.
4. Migrate chat and execution paths to the shared evidence writer.
5. Tighten proof verifier semantics once the evidence writer is in place.
6. Unify the Windows front door and fix timeout wiring.
7. Update the docs/bootstrap guidance last, after the runtime contract is stable.

---

## 5. Unification check

| Concern | Before | After | Mechanism |
|---|---|---|---|
| Pause/resume authority | `OpsRun` pauses, workflow endpoint resumes | `OpsRun` pauses and resumes | canonical run lifecycle module + `/ops/runs/{run_id}/resume` |
| Active-run truth | multiple hardcoded status sets | one shared backend predicate | shared lifecycle helpers consumed by all surfaces |
| Spawn truth | inventory record plus echoed caller input | real child execution with persisted routing | governed child-run path + readiness gate |
| Payload-plane evidence | graph rich, chat thin, spawn none | one evidence contract for real execution | shared execution evidence writer + root trace tree |
| Proof semantics | empty chain reports plain success | empty chain reports explicit non-attested state with subject/builder metadata on real proofs | verifier contract change |
| Windows terminal contract | `gimo.cmd` and `python gimo.py` diverge | one CLI contract behind one front door | wrapper delegation |
| Local HTTP probing | anonymous curl appears to be the feature matrix | authenticated bootstrap documented, auth unchanged | docs/help correction only |

Every row removes a parallel truth instead of adding another compatibility layer.

---

## 6. Verification strategy

### Focused verification per change

1. **Change 1**
   - Add targeted backend tests for paused-run persistence, resume routing, and shared lifecycle predicates.
   - Verify `HUMAN_APPROVAL_REQUIRED` classification through status, metrics, graph, and worker paths.
2. **Change 2**
   - Add targeted tests for spawn rejection on provider-readiness failure and spawn success on provider-readiness success.
   - Verify the authoritative provider/model/policy fields are persisted on the child execution object.
3. **Change 3**
   - Add targeted tests for chat-path evidence persistence and explicit no-proof semantics.
   - Verify that persistent readers return the same activity after a real chat/tool execution.
   - Verify that trace/log correlation fields are present and stable across the same execution.
4. **Change 4**
   - Add targeted tests for batch-wrapper delegation and exact timeout wiring.
5. **Change 5**
   - Manual doc and operator-path audit; no fake test claim for documentation-only corrections.

### Broader checks at boundaries

- After Changes 1-3: run `python -m pytest -m "not integration" -v`
- After Change 4: rerun the CLI-focused subset plus the non-integration suite if wrapper behavior touches shared startup paths
- Before Phase 4 closeout: run the quality and policy gates that match the touched files
  - `pre-commit run --all-files`
  - `python scripts/ci/check_no_artifacts.py --tracked`
  - `python scripts/ci/quality_gates.py`

### Runtime smoke gate

Use the official launcher path first:

```powershell
.\gimo.cmd status
.\gimo.cmd doctor
```

Then rerun the high-signal R19 probes affected by the plan:

```powershell
python gimo.py status --json
python gimo.py observe metrics
python gimo.py trust status
python gimo.py observe traces
python gimo.py providers test openai
python gimo.py watch --timeout 5
```

And the MCP/HTTP probes:

```text
gimo_get_task_status(...)
gimo_resolve_handover(...)
gimo_spawn_subagent(...)
gimo_verify_proof_chain(...)
gimo_get_budget_status(scope="global")
```

```powershell
curl.exe -i http://127.0.0.1:9325/health
curl.exe -i http://127.0.0.1:9325/ops/health/info
```

For protected `/ops/*` HTTP validation, use the documented local token bootstrap path; do not treat anonymous `401` as a regression.

### Vehicle/output check

- If Change 2 plus Change 3 claim real child execution, confirm a real payload-plane side effect or an honest persisted execution record exists.
- If the system still reports successful spawn or verified proof without payload-plane evidence, R19 is not closed.

---

## 7. Compliance matrix

| Gate | YES/NO | Rationale |
|---|---|---|
| Aligned | YES | The plan strengthens backend authority, thin-client discipline, and fail-closed auth exactly as required by `AGENTS.md`, `SYSTEM.md`, `CLIENT_SURFACES.md`, and `SECURITY.md`. |
| Honest | YES | Claims are scoped to the enforcing boundary: run lifecycle resumes the same durable run identity, spawn acceptance is readiness-gated and typed, proof semantics stop conflating absence of evidence with verified execution, and auth remains closed. |
| Potent | YES | Five changes cover the eight R19 findings by collapsing the underlying contract splits rather than patching symptoms one by one. |
| Minimal | YES | No broader refactor is proposed than necessary: one run contract, one evidence path, one wrapper front door, and one docs correction. |
| Unified | YES | Every affected surface is pointed back to one canonical backend contract instead of adding more surface-local logic. |
| Verifiable | YES | Each change has focused tests plus concrete runtime probes tied directly to the original R19 failures. |
| Operational | YES | The plan includes launcher-first smoke, runtime probe reruns, authenticated HTTP bootstrap, and explicit handling of short-lived trace export and provider-readiness failure modes. |
| Durable | YES | The design removes recurring drift classes: resume mismatch, false spawn success, path-specific evidence, duplicated status sets, and terminal contract split. |

All gates answer `YES`.

---

## 8. Residual risks

1. Turning spawn into a child-run contract may require a compatibility bridge for UI views that currently expect `SubAgent` inventory records.
2. Tightening proof semantics can be externally visible to any client that treated `valid=true, length=0` as acceptable.
3. Provider-readiness gating may expose operational misconfiguration that was previously masked by optimistic spawn acceptance.
4. The direct HTTP bootstrap improvement should stay documentation-first; printing or surfacing raw secrets would violate the security model.
5. This plan does not claim to fix unrelated R18 history or every archived workflow path. It is scoped to the validated R19 clusters.

---

## 9. Status

`PLAN_READY_AWAITING_APPROVAL`
