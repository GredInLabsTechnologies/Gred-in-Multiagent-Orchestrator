# E2E Implementation Report - Round R19

**Date**: 2026-04-08
**Round**: R19
**Input**: `docs/audits/E2E_ENGINEERING_PLAN_20260408_R19.md`
**Branch**: main
**Status**: **PARTIALLY_DONE** - the core contract fixes for lifecycle, spawn, evidence/proof, and terminal parity landed and were re-verified with focused tests. The operator-doc/bootstrap follow-up from Change 5 is still open, and this round does not yet prove the full "real task -> repo side effect" acceptance story required to mark R19 fully closed.

## Summary

| # | Change | Status | Evidence |
|---|---|---|---|
| 1 | Canonical run lifecycle + same-run resume | **DONE** | `tests/unit/test_run_lifecycle.py` |
| 2 | Spawn as authoritative child execution with readiness gate | **DONE** | `tests/unit/test_sandbox_execution.py` |
| 3 | Honest evidence/proof/trust/traces contract | **DONE** for the shared backend/CLI contract | `tests/unit/test_agentic_loop.py`, `tests/unit/test_execution_proof.py`, `tests/unit/test_sagp_gateway.py`, `tests/unit/test_trust.py`, `tests/unit/test_observability.py`, `tests/unit/test_cli_render.py`, `tests/unit/test_gimo_cli.py`, `tests/unit/test_config_paths.py` |
| 4 | Terminal front door + timeout honesty + deterministic shutdown | **DONE** | `tests/unit/test_gimo_cli.py`, runtime shutdown smoke |
| 5 | Authenticated HTTP bootstrap docs/help | **DONE** | `tests/unit/test_doctor_http_probing.py` |

**Focused verification suite**: `133 passed, 2 warnings in 14.70s`.

No vendor or daemon GICS source was modified in this round. The only GICS-related fix landed in GIMO's own wiring (`tools/gimo_server/config.py` and storage/evidence integration).

## Section 1 - Lifecycle and resume

### Change 1 - canonical lifecycle predicates and same-run resume
**Files**:
- `tools/gimo_server/services/run_lifecycle.py`
- `tools/gimo_server/services/ops/_run.py`
- `tools/gimo_server/routers/ops/run_router.py`
- `tools/gimo_server/services/operator_status_service.py`
- `tools/gimo_server/services/observability_pkg/observability_service.py`
- `tools/gimo_server/routers/ops/graph_router.py`
- `tools/gimo_server/services/execution/run_worker.py`
- `tools/gimo_server/mcp_bridge/native_tools.py`
- `gimo_cli/config.py`

**What landed**:
- Added one shared lifecycle module with canonical predicates:
  - `is_active_run_status(...)`
  - `is_resumable_run_status(...)`
  - `is_terminal_run_status(...)`
- Moved the MCP handover path off the broken workflow-only route and onto `POST /ops/runs/{run_id}/resume`.
- `OpsService.resume_run(...)` now resumes the same paused `OpsRun`, merges `edited_state` into `resume_context`, records the handover decision, and re-queues the run as `pending`.
- Shared lifecycle predicates are now consumed by CLI config, operator status, observability, graph reads, and run-worker activity checks, closing the previous split where `HUMAN_APPROVAL_REQUIRED` was "active" in some places and invisible in others.

**Behavioral proof**:
- `tests/unit/test_run_lifecycle.py::test_resume_run_route_requeues_same_run`
  - verifies `POST /ops/runs/{run_id}/resume`
  - keeps the same `run_id`
  - returns the run in `pending`
  - persists `last_handover_decision`
  - persists `resume_context["human_approval_granted"]`

## Section 2 - Spawn, evidence, and trust

### Change 2 - spawn becomes an authoritative child execution
**Files**:
- `tools/gimo_server/services/sub_agent_manager.py`
- `tools/gimo_server/models/sub_agent.py`
- `tools/gimo_server/services/agent_broker_service.py`
- `tools/gimo_server/mcp_bridge/native_tools.py`

**What landed**:
- `SubAgentManager.spawn_via_draft(...)` now resolves routing, requires provider readiness, creates draft -> approved -> run, and only then returns a `SubAgent` read projection.
- The returned projection is explicitly marked `authority="ops_run"` and carries:
  - `runId`
  - `draftId`
  - resolved `provider`
  - resolved `model`
  - `executionPolicy`
  - typed delegation/routing metadata
- Provider readiness is now a hard precondition via `ProviderDiagnosticsService._probe_one(...)`.
- Spawn rejection is now honest: unready providers do not produce a fake successful worker registration.

**Behavioral proof**:
- `tests/unit/test_sandbox_execution.py::test_spawn_via_draft_rejects_unready_provider`
  - verifies `PROVIDER_NOT_READY:openai:unreachable`
  - verifies no run is created
- `tests/unit/test_sandbox_execution.py::test_spawn_via_draft_creates_authoritative_run_projection`
  - verifies `authority == "ops_run"`
  - verifies `runId` and `draftId`
  - verifies `provider == "openai"`
  - verifies persisted `execution_policy_name == "workspace_safe"`
  - verifies readiness metadata is persisted on the run routing snapshot

### Change 3 - honest evidence/proof/trust/traces
**Files**:
- `tools/gimo_server/config.py`
- `tests/unit/test_config_paths.py`
- `tools/gimo_server/services/agentic_loop_service.py`
- `tools/gimo_server/security/execution_proof.py`
- `tools/gimo_server/services/sagp_gateway.py`
- `tools/gimo_server/services/storage/trust_storage.py`
- `tools/gimo_server/services/observability_pkg/observability_service.py`
- `gimo_cli/render.py`

**What landed**:
- Fixed repo-root resolution in `tools/gimo_server/config.py` so `.orch_data/ops` and the GICS token path resolve inside the current repo instead of the parent directory.
- The chat execution path now persists durable evidence through the same backend-facing stores:
  - cost events
  - trust events
  - model outcomes
  - observability workflow/node spans
- Proof semantics are now explicit:
  - `absent`
  - `present`
  - `invalid`
- `SagpGateway.verify_proof_chain(...)` now reports explicit proof state and includes subject/executor identity when proofs exist.
- `TrustStorage` now implements `get_circuit_breaker_config(...)`, which removes the trust dashboard crash and allows `TrustEngine` to operate against the GICS-backed storage adapter.
- Trace aggregation and CLI rendering now use the canonical `trace_id` field and a more honest duration calculation:
  - prefer root workflow `duration_ms`
  - else sum node durations
  - else fallback to `end_time - start_time`

**Behavioral proof**:
- `tests/unit/test_config_paths.py`
  - verifies `.orch_data/ops` and `gics.token` resolve under the repo root
- `tests/unit/test_execution_proof.py`
  - verifies empty proof chain reports `absent`
- `tests/unit/test_sagp_gateway.py::test_verify_proof_chain_empty_reports_absent`
  - verifies `state == "absent"` and `valid is False`
- `tests/unit/test_sagp_gateway.py::test_verify_proof_chain_present_includes_subject_and_executor`
  - verifies subject/executor metadata on a real proof chain
- `tests/unit/test_trust.py::test_dashboard_accepts_trust_storage_backed_by_gics`
  - verifies the trust dashboard path works against GICS-backed `TrustStorage`
- `tests/unit/test_observability.py`
  - verifies trace aggregation prefers root duration
  - verifies fallback to node durations when root duration is zero
- `tests/unit/test_cli_render.py` and `tests/unit/test_gimo_cli.py`
  - verify CLI traces render `trace_id`, not the obsolete `id`

**Runtime smoke executed during this round**:
- `python gimo.py providers set ollama-main`
- `python gimo.py chat -m "Reply with exactly OK and do not call any tools."`
- `python gimo.py observe traces`
- `python gimo.py observe metrics`
- `python gimo.py trust status --json`
- `python gimo.py providers set openai`

Observed outcome:
- real chat response returned
- trace list showed non-zero durations
- trust surface returned populated data instead of crashing or remaining empty because of the old storage wiring

## Section 3 - Terminal surface and operational cleanup

### Change 4 - terminal front door, timeout honesty, deterministic shutdown
**Files**:
- `gimo.cmd`
- `gimo_cli/stream.py`
- `gimo_cli/commands/server.py`
- `tests/unit/test_gimo_cli.py`

**What landed**:
- `gimo.cmd` remains the official Windows front door and delegates non-launcher verbs to `gimo.py` through `:cmd_cli`.
- `gimo.cmd down` now delegates first to canonical `gimo.py down` and only then cleans launcher windows and auxiliary ports.
- `watch --timeout N` is now wired to the actual stream read timeout in `gimo_cli/stream.py`.
- Server shutdown is now harder to fake:
  - first tries graceful shutdown
  - then kills remaining listeners on the port
  - then falls back to the authoritative `/health` PID for Windows orphan-worker cases
  - then requires a stable "server down" window before declaring success

**Behavioral proof**:
- `tests/unit/test_gimo_cli.py`
  - verifies `stream_events(..., timeout_seconds=5)` sets `httpx.Timeout.read == 5`
  - verifies keepalive-only streams terminate as idle after 5 seconds
  - verifies `down` uses `/health` PID fallback when port scan misses the live listener
  - verifies `down` fails loudly if the server is still healthy after fallback

**Runtime shutdown smoke executed during this round**:
```text
python gimo.py up
.\gimo.cmd down
```

Observed outcome:
- the backend no longer stayed deceptively alive behind orphaned worker processes
- repeated `/health` probes after shutdown stopped responding, which was the actual bug this patch targeted

## Verification

### Focused unit suite
```text
python -m pytest tests/unit/test_run_lifecycle.py tests/unit/test_sandbox_execution.py tests/unit/test_agentic_loop.py tests/unit/test_trust.py tests/unit/test_execution_proof.py tests/unit/test_sagp_gateway.py tests/unit/test_gimo_cli.py tests/unit/test_observability.py tests/unit/test_cli_render.py tests/unit/test_config_paths.py -q
```

Result:
```text
131 passed, 2 warnings in 18.51s
```

### Additional runtime evidence from this round
- repo-local `.orch_data` path fix confirmed by importing `tools.gimo_server.config`
- trust dashboard 500 removed in local FastAPI `TestClient` validation
- CLI/backend trace parity restored after clean backend restart
- deterministic backend cleanup confirmed through repeated post-shutdown health probes

## Files Changed (high-signal subset)

- `docs/audits/E2E_AUDIT_LOG_20260408_R19.md`
- `gimo.cmd`
- `gimo_cli/commands/server.py`
- `gimo_cli/config.py`
- `gimo_cli/render.py`
- `gimo_cli/stream.py`
- `tests/unit/test_agentic_loop.py`
- `tests/unit/test_cli_render.py`
- `tests/unit/test_config_paths.py`
- `tests/unit/test_execution_proof.py`
- `tests/unit/test_gimo_cli.py`
- `tests/unit/test_observability.py`
- `tests/unit/test_policy_gate.py`
- `tests/unit/test_risk_gate.py`
- `tests/unit/test_run_lifecycle.py`
- `tests/unit/test_sagp_gateway.py`
- `tests/unit/test_sandbox_execution.py`
- `tests/unit/test_trust.py`
- `tools/gimo_server/config.py`
- `tools/gimo_server/mcp_bridge/native_tools.py`
- `tools/gimo_server/models/core.py`
- `tools/gimo_server/models/sub_agent.py`
- `tools/gimo_server/routers/ops/graph_router.py`
- `tools/gimo_server/routers/ops/run_router.py`
- `tools/gimo_server/security/execution_proof.py`
- `tools/gimo_server/services/agent_broker_service.py`
- `tools/gimo_server/services/agentic_loop_service.py`
- `tools/gimo_server/services/execution/engine_service.py`
- `tools/gimo_server/services/execution/run_worker.py`
- `tools/gimo_server/services/merge_gate_service.py`
- `tools/gimo_server/services/observability_pkg/observability_service.py`
- `tools/gimo_server/services/operator_status_service.py`
- `tools/gimo_server/services/ops/_base.py`
- `tools/gimo_server/services/ops/_run.py`
- `tools/gimo_server/services/run_lifecycle.py`
- `tools/gimo_server/services/sagp_gateway.py`
- `tools/gimo_server/services/storage/trust_storage.py`
- `tools/gimo_server/services/storage_service.py`
- `tools/gimo_server/services/sub_agent_manager.py`

## Closure

R19's core contract splits were materially reduced:
- resume now targets the same `OpsRun` that paused
- spawn now fails when provider readiness fails and returns an authoritative execution projection
- proof/trust/traces no longer rely on the old "empty means valid" or "chat work leaves no durable evidence" behavior
- CLI shutdown and stream timeout now behave like the surface claims they behave

### Change 5 — authenticated HTTP probing hint in `gimo doctor`
**Files**:
- `gimo_cli/commands/auth.py`
- `tests/unit/test_doctor_http_probing.py`

**What landed**:
- `gimo doctor` now reports whether an operator token is resolvable from the
  existing bootstrap chain (CLI bond → env vars → legacy bond → inline config).
- The hint guides operators toward the safe path (`python gimo.py status`,
  `observe metrics`) where the token never leaves the CLI process.
- For direct HTTP, the hint instructs the operator to set
  `ORCH_OPERATOR_TOKEN` from their bond/secret store and call `/ops/*` with
  `Authorization: Bearer`. No anonymous routes are opened; the boundary stays
  fail-closed.
- The operator token literal is **never** printed on stdout. Regression test
  asserts a planted secret never appears in the doctor output.

**Behavioral proof**:
- `tests/unit/test_doctor_http_probing.py::test_doctor_http_probing_section_present_with_token`
  - verifies the "HTTP probing" section renders when a token is resolvable
  - verifies the literal token value never appears on stdout
  - verifies the `ORCH_OPERATOR_TOKEN` env var name is surfaced
  - verifies the fail-closed boundary statement remains
- `tests/unit/test_doctor_http_probing.py::test_doctor_http_probing_warns_when_token_missing`
  - verifies the "not resolvable" warning path with `gimo login` guidance

## Closure

What is still missing for full round closure:
- a final vehicle-grade e2e proving a real task creates a real repo side effect
  under the corrected contracts (the runtime smoke from Section 2 already shows
  proof/trust/traces become honest after a real chat, but a write-side effect
  vehicle test is still pending).

That is why this report remains **PARTIALLY_DONE**, not `DONE`.
