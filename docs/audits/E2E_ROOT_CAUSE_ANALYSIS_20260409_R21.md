# GIMO E2E Forensic Audit - Round 21 (Phase 2)

**Date**: 2026-04-09  
**Round**: R21  
**Phase**: 2 - Root Cause Analysis (Read-Only Deep Trace)  
**Auditor**: Codex GPT-5  
**Input**: `docs/audits/E2E_AUDIT_LOG_20260409_R21.md`  
**Supplemental evidence**: MCP smoke run for "create a simple app via GIMO" (`d_1775747333494_b1f037`, `r_1775747350708_7e5c93`, `r_1775747419610_c6dba5`)  
**Constraint**: Read-only analysis. No code modified.  

---

## 1 - Executive Summary

R21 contains two different realities:

1. Several Phase 1 findings were real at probe time but are not reproducible on the current checkout (`R21-001`, `R21-005`, `R21-006`). They should not be carried forward as live defects without runtime re-validation.
2. The active defect family is still serious: provider selection and status surfaces use configured topology as truth, while execution paths still lack a mandatory readiness gate (`R21-003`, `R21-008`, `R21-013`).
3. The supplemental "build a simple app with GIMO" smoke exposed a new blocker not listed in Phase 1: prompt-based runs can end `done` after writing heuristic garbage to the wrong path (`R21-015`).

The highest-leverage fix is not a UI patch. It is a single execution invariant:

> No adapter invocation and no write-producing pipeline may proceed unless the resolved binding is readiness-checked and the artifact contract is explicit.

Today GIMO still allows:
- top-level chat/run execution against an unready provider
- prompt-only artifact creation through `legacy_run`
- heuristic file writes from raw prose
- green completion without validating requested side effects

That is the architectural center of gravity for R21.

---

## 2 - Issue Map

| ID | Current state | Title | Root cause anchor | Confidence |
|---|---|---|---|---|
| R21-001 | FIXED_SINCE_PROBE | MCP draft path no longer defaults to `human_ui` | `tools/gimo_server/mcp_bridge/native_tools.py::gimo_create_draft`, `::gimo_run_task` now force `operator_class="cognitive_agent"` | HIGH |
| R21-002 | ACTIVE | `providers list` and `providers auth-status` describe different objects | `gimo_cli/commands/providers.py::providers_list`, `::providers_auth_status` | HIGH |
| R21-003 | ACTIVE | `chat` path bypasses provider readiness gate | `routers/ops/conversation_router.py::chat_message`, `services/agentic_loop_service.py::_resolve_orchestrator_adapter`, `services/providers/service_impl.py::static_generate` | HIGH |
| R21-004 | ACTIVE | `surface list` reports config presence, not live MCP connectivity | `gimo_cli/commands/surface.py::list_surfaces` | HIGH |
| R21-005 | STALE_ON_CURRENT_CHECKOUT | `gimo ps` cannot detect running server | Current `gimo_cli/commands/server.py::ps` probes `/health`; symptom no longer reproduces | HIGH |
| R21-006 | STALE_ON_CURRENT_CHECKOUT | `gimo.cmd doctor` broken | Current `gimo.cmd` + CLI path no longer reproduces | HIGH |
| R21-007 | ACTIVE_MINOR | `gimo_dashboard` always shows `proof_chain_length=0` unless explicitly scoped elsewhere | `tools/gimo_server/mcp_bridge/mcp_app_dashboard.py::gimo_dashboard`, `services/sagp_gateway.py::get_snapshot` | HIGH |
| R21-008 | ACTIVE | Active provider/model snapshot ignores trust/readiness reality | `services/operator_status_service.py::_provider_snapshot`, `services/constraint_compiler_service.py::apply_trust_authority`, `services/providers/service_impl.py::static_generate` | HIGH |
| R21-009 | ACTIVE_FRICTION | `gimo_list_agents` returns discovery inventory, not configured providers | `mcp_bridge/native_tools.py::gimo_list_agents`, `services/sub_agent_manager.py::sync_with_ollama`, `::get_sub_agents` | HIGH |
| R21-010 | ACTIVE_CONTRACT_DIVERGENCE | HTTP proofs route and MCP proof tool are not the same contract | `routers/ops/conversation_router.py::get_thread_proofs`, `mcp_bridge/governance_tools.py::gimo_verify_proof_chain` | HIGH |
| R21-011 | ACTIVE_GAP | `/ops/providers` does not exist; canonical route is singular `/ops/provider` | `routers/ops/config_router.py`, `routers/ops/provider_auth_router.py` | HIGH |
| R21-012 | ACTIVE | `gimo_spawn_subagent(provider=ollama_local)` can fail even when Ollama models are discoverable | `services/agent_broker_service.py::select_provider_for_task`, `services/sub_agent_manager.py::sync_with_ollama` | MEDIUM-HIGH |
| R21-013 | ACTIVE | `auto/auto` chooses configured-active provider, not a ready provider | `services/agent_broker_service.py::select_provider_for_task`, `services/sub_agent_manager.py::_require_provider_readiness` | HIGH |
| R21-014 | DEFERRED_ENV | External provider reachability/auth remains environment-bound | Runtime environment | HIGH |
| R21-015 | NEW_BLOCKER | Prompt-based app creation can end `done` after heuristic wrong-path writes | `services/execution/engine_service.py::execute_run`, `engine/stages/critic.py`, `engine/stages/file_write.py`, `engine/tools/executor.py` | HIGH |

---

## 3 - Detailed Traces

### R21-001 - Fixed since probe

**Phase 1 symptom**: `gimo_create_draft` returned `operator_class: "human_ui"`.

**Current code**:
- `tools/gimo_server/mcp_bridge/native_tools.py::gimo_create_draft` posts `/ops/drafts` with context `{"operator_class": "cognitive_agent", "surface_type": "mcp"}`.
- `tools/gimo_server/mcp_bridge/native_tools.py::gimo_run_task` does the same for the bypass path.

**Supplemental runtime evidence**:
- MCP `gimo_create_draft(...)` returned draft `d_1775747333494_b1f037` with `operator_class="cognitive_agent"`.

**Root cause assessment**:
- The Phase 1 symptom is not present in the analyzed checkout.
- This should be treated as fixed since probe, not as an active runtime defect.

**Action**:
- Do not spend Phase 3 effort re-fixing `R21-001` unless it reproduces again against the live bridge.

**Confidence**: HIGH.

---

### R21-002 - Provider list vs auth status mismatch

**Reported symptom**:
- `python gimo.py providers list` shows configured provider IDs (`openai`, `codex-account`).
- `python gimo.py providers auth-status` shows connector families (`codex`, `claude`).

**Trace**:
- `gimo_cli/commands/providers.py::providers_list` renders `payload["providers"]` from the canonical provider config response.
- `gimo_cli/commands/providers.py::providers_auth_status` hardcodes `providers_to_check = ["codex", "claude"]`.
- `routers/ops/provider_auth_router.py` exposes `/ops/connectors/{provider}/auth-status`, which is connector-family oriented.

**Root cause**:
- The CLI presents two different namespaces as if they were one:
  - configured provider IDs (`openai`, `codex-account`)
  - connector/auth families (`codex`, `claude`)
- The mismatch is structural, not incidental.

**Blast radius**:
- Operators cannot infer whether a configured provider is actually authenticated from `auth-status`.
- `openai` auth state is invisible in the auth table while still being the active provider.

**Fix options**:
- Replace `providers auth-status` with a thin client of `/ops/providers/diagnostics`.
- Or rename the command/output explicitly to `connector-auth-status` so it stops pretending to describe configured providers.

**Confidence**: HIGH.

---

### R21-003 - Top-level execution bypasses readiness gate

**Reported symptom**:
- `chat` and prompt-based runs can hit upstream `401 Unauthorized` instead of failing closed before invocation.

**Trace**:
- `routers/ops/conversation_router.py::chat_message` calls `AgenticLoopService.run(...)`.
- `services/agentic_loop_service.py::_run_reserved` resolves the orchestrator binding through `_resolve_orchestrator_adapter()`.
- `_resolve_orchestrator_adapter()` reads provider config and builds the adapter directly. It performs no readiness probe.
- `services/providers/service_impl.py::static_generate` resolves `effective_provider` and calls `adapter.generate(...)` directly. It also performs no readiness/auth preflight.
- By contrast, `services/sub_agent_manager.py::spawn_via_draft` does call `_require_provider_readiness(provider_id)` before creating a governed execution.

**Root cause**:
- Provider readiness is enforced only on the spawn/sub-agent path.
- Top-level chat, MCP prompt runs, and other prompt-based executions use a parallel path that trusts config and only discovers failure after the upstream call.

**Blast radius**:
- CLI chat
- MCP `gimo_run_task`
- prompt-based engine executions
- any surface wired through `AgenticLoopService` or `ProviderService.static_generate`

**Fix options**:
- Introduce a single readiness gate at binding-resolution time and require all execution paths to pass through it.
- The correct choke point is not the router; it is the provider binding resolver used by both agentic loop and run worker.

**Confidence**: HIGH.

---

### R21-004 - `surface list` is config inspection, not connectivity detection

**Reported symptom**:
- `python gimo.py surface list` still prints `Claude Code: Not connected` while this audit session is using the MCP bridge from Codex/Claude-code-like workflow.

**Trace**:
- `gimo_cli/commands/surface.py::list_surfaces` resolves static config file locations from `SURFACE_CONFIGS`.
- It loads JSON and checks only whether `"gimo"` exists under the configured MCP server key.
- No runtime bridge ping, no session detection, no connection handshake inspection.

**Root cause**:
- The command conflates "configured in a settings file" with "currently connected".

**Blast radius**:
- False negatives for live MCP sessions.
- False positives for stale config entries.

**Fix options**:
- Rename the command/output to `Configured Surfaces`.
- Or add an explicit runtime probe column separate from config presence.

**Confidence**: HIGH.

---

### R21-005 / R21-006 - Stale on current checkout

**Phase 1 symptoms**:
- `gimo ps` reported no server while backend was healthy.
- `gimo.cmd doctor` was broken on Windows shell.

**Current runtime evidence**:
- `python gimo.py ps` -> healthy server detected on port `9325`
- `.\gimo.cmd ps` -> healthy server detected on port `9325`
- `.\gimo.cmd doctor` -> successful doctor report

**Assessment**:
- These are not live defects on the analyzed checkout/runtime.
- They should be removed from the active fix queue unless someone can reproduce them against the current launcher and backend.

**Confidence**: HIGH.

---

### R21-007 - Dashboard uses a threadless governance snapshot

**Reported symptom**:
- `gimo_dashboard` shows `proof_chain_length=0` while thread-scoped governance reads can show non-zero proof state.

**Trace**:
- `tools/gimo_server/mcp_bridge/mcp_app_dashboard.py::gimo_dashboard` calls `SagpGateway.get_snapshot(surface=surface)` with no `thread_id`.
- `services/sagp_gateway.py::get_snapshot` computes proof length through `_get_proof_chain_length(thread_id)`.
- `services/sagp_gateway.py::_get_proof_chain_length` returns `0` when `thread_id` is empty.

**Root cause**:
- The dashboard is global/threadless by implementation, but users read it as a thread sanity panel.

**Blast radius**:
- Misleading dashboard output.
- Low severity, but directly confusing during audits.

**Fix options**:
- Accept an optional `thread_id` on `gimo_dashboard`.
- Or label the output explicitly as "global snapshot (no thread scope)".

**Confidence**: HIGH.

---

### R21-008 and R21-013 - Configured binding is treated as operational truth

**Reported symptom family**:
- `openai / gpt-4o` remains the active provider/model even when runtime diagnostics say unreachable/auth-missing.
- `auto/auto` selection can still choose the not-ready active provider.

**Trace**:
- `services/operator_status_service.py::_provider_snapshot` reports the primary orchestrator binding or active config directly.
- `services/constraint_compiler_service.py::apply_trust_authority` can clamp execution policy on anomaly, but it does not reroute or block the provider/model binding.
- `services/providers/service_impl.py::static_generate` resolves the effective provider/model from config and ranking logic, then invokes the adapter directly.
- `services/agent_broker_service.py::select_provider_for_task` uses `ModelRouterService.resolve_tier_routing(...)` or falls back to `config.active`.
- Only after selection does `services/sub_agent_manager.py::_require_provider_readiness(...)` validate the chosen provider.

**Supplemental runtime evidence**:
- `python gimo.py providers test openai` -> `reachable=False`, `auth=missing`
- `python gimo.py providers test codex-account` -> authenticated
- `gimo_get_status` still reports active provider/model from config snapshot, not from readiness/trust state.

**Root cause**:
- GIMO has trust and diagnostics signals, but they are advisory in the top-level selection path.
- Selection is topology/config-first, readiness-second.
- Status surfaces expose configured truth, not executable truth.

**Blast radius**:
- repeated 401/unreachable failures
- misleading "active provider" UI/status
- `auto` routing choosing dead bindings
- GICS anomaly counts can be inflated by repeated avoidable failures

**Fix options**:
- Filter candidate bindings by readiness before ranking and before adapter construction.
- Refuse to advertise a provider/model as active when diagnostics or trust make it non-executable.
- Retire or wire in `ProviderService._select_runtime_binding_with_reliability(...)`; today it is dead code.

**Confidence**: HIGH.

---

### R21-009 - `gimo_list_agents` is inventory discovery, not provider listing

**Reported symptom**:
- `gimo_list_agents` shows Ollama agents only.

**Trace**:
- `mcp_bridge/native_tools.py::gimo_list_agents` calls `SubAgentManager.sync_with_ollama()` and then `SubAgentManager.get_sub_agents()`.
- `services/sub_agent_manager.py::sync_with_ollama` registers auto-discovered Ollama models as `SubAgent` inventory entries.
- `get_sub_agents()` returns discovery entries plus spawn projections. It does not list configured providers.

**Root cause**:
- The tool contract is about "agent inventory", not "configured providers", but the naming encourages operators to read it as the latter.

**Blast radius**:
- user confusion
- audit friction
- false assumption that remote configured providers are missing from the system

**Fix options**:
- Split output into two sections: `auto_discovery` and `spawn`.
- Or rename the tool to `gimo_list_agent_inventory`.

**Confidence**: HIGH.

---

### R21-010 - HTTP proofs route and MCP proof tool are semantically different

**Reported symptom**:
- Phase 1 treated `GET /ops/threads/<id>/proofs` and `gimo_verify_proof_chain(thread_id=<id>)` as parity surfaces and observed divergence.

**Trace**:
- `routers/ops/conversation_router.py::get_thread_proofs` first calls `ConversationService.get_thread(thread_id)` and returns `404` if the thread file does not exist.
- `mcp_bridge/governance_tools.py::gimo_verify_proof_chain` accepts any `thread_id` (or infers the most recent one) and then calls `SagpGateway.verify_proof_chain(thread_id=resolved_id)`.
- `services/sagp_gateway.py::verify_proof_chain` reads proof records directly through `StorageService.list_proofs(thread_id)` and does not require a persisted thread object.

**Root cause**:
- These are not equivalent APIs:
  - HTTP route: "proofs for an existing conversation thread"
  - MCP tool: "verify whatever proof bucket exists under this id"

**Blast radius**:
- parity claims are invalid
- audits can report a false contradiction when the supplied ID is not a persisted thread object

**Fix options**:
- Make the MCP tool enforce thread existence too.
- Or add an HTTP raw-proof verification route with the same semantics as the MCP tool.
- But stop calling the current pair "parity" until they share a subject model.

**Confidence**: HIGH.

---

### R21-011 - `/ops/providers` is a route-gap / naming-drift issue

**Reported symptom**:
- `GET /ops/providers` returns `404`.

**Trace**:
- `routers/ops/config_router.py` exposes canonical singular routes:
  - `/ops/provider`
  - `/ops/provider/select`
  - `/ops/provider/capabilities`
- `routers/ops/provider_auth_router.py` exposes `/ops/providers/diagnostics`
- No `/ops/providers` route exists in the current router set.

**Root cause**:
- Route naming drift between expectation/documentation and actual backend contract.

**Blast radius**:
- direct HTTP consumers hit `404`
- audit confusion about whether the backend route is missing or misregistered

**Fix options**:
- Add `/ops/providers` as an alias to the canonical provider-config response.
- Or update docs and clients to use `/ops/provider`.

**Confidence**: HIGH.

---

### R21-012 - Ollama discovery and provider topology are separate systems

**Reported symptom**:
- `gimo_spawn_subagent(provider=ollama_local)` can fail with `SPAWN_RESOLUTION_FAILED:none:none` even when Ollama models are discoverable.

**Trace**:
- `services/sub_agent_manager.py::sync_with_ollama` creates inventory entries for models discovered from Ollama.
- `services/agent_broker_service.py::select_provider_for_task` explicit-provider branch requires `task.preferred_provider` to exist in `config.providers`.
- If `ollama_local` is discoverable but not configured in provider topology, the broker returns `provider_id="none", model_id="none"`.

**Root cause**:
- GIMO treats:
  - model discovery inventory
  - configured provider topology
  as separate truths.
- Seeing a model in `gimo_list_agents` does not mean that provider ID is spawnable.

**Blast radius**:
- confusing spawn failures
- false operator expectation that discovery implies configured execution readiness

**Fix options**:
- Auto-inject/configure `ollama_local` when local discovery is healthy.
- Or return an explicit error that distinguishes "discovered but not configured" from "provider missing".

**Confidence**: MEDIUM-HIGH.

---

### R21-015 - False-green prompt run during simple app creation

**Supplemental symptom**:
- MCP `gimo_run_task` using `codex-account` finished `done` for run `r_1775747419610_c6dba5`.
- Requested app directory `tmp/gimo-mcp-smoketest-app-codex` was not created.
- GIMO instead wrote:
  - `` `tmp/gimo-mcp-smoketest-app-codex/README.md``
  - `` `tmp/gimo-mcp-smoketest-app-codex/index.html``
- written content was a status report about a read-only session, not a web app
- `commit_after` remained `null`

**Trace**:
- `services/execution/engine_service.py::execute_run` inferred composition `legacy_run` because the prompt carried no explicit task spec, `target_path`, or structured plan marker.
- `engine/stages/llm_execute.py::execute` called `ProviderService.static_generate(...)` and accepted raw prose output as stage success.
- The run journal records `llm_execute` content describing a blocked/read-only environment, not app assets.
- `engine/stages/critic.py::execute` calls `CriticService.review_output(content)`.
- `services/critic_service.py` has no `review_output`; it only exposes `evaluate(...)`.
- The resulting `AttributeError` is swallowed by `critic.py`, which returns `StageOutput(status="continue", artifacts={"critic_error": ...})`.
- `engine/stages/file_write.py::execute` saw no tool calls and no `FileTaskSpec`, so it fell back to `_extract_fallback_path(...)` regex extraction from raw prose.
- The journal shows two successful writes to heuristic paths with a leading backtick:
  - `` `tmp/gimo-mcp-smoketest-app-codex/README.md``
  - `` `tmp/gimo-mcp-smoketest-app-codex/index.html``
- `engine/tools/executor.py::handle_write_file` returns `status="success"` even when post-write lint checks fail; lint/test results are recorded only as nested `checks`.
- `services/execution/engine_service.py::execute_run` marks the run `done` because every stage returned `continue`; there is no postcondition asserting that the requested artifact set exists or that the written content matches the requested task.

**Why this is a blocker**:
- This is not merely "the model answered badly".
- The governed pipeline converted a blocked textual report into filesystem side effects and then certified the run as successful.
- The supposed guardrail (`Critic`) was disconnected by an API mismatch.

**Blast radius**:
- Any prompt-based artifact creation path using `legacy_run`
- any run whose LLM response contains incidental file-like strings
- false-green execution telemetry (`status=done`, routing snapshot present, no real requested side effect)

**Fix options**:
- Remove `FileWrite` heuristic path extraction for `legacy_run`; require explicit tool calls or `FileTaskSpec`.
- Fix `engine/stages/critic.py` to call `CriticService.evaluate(...)` and to fail closed when review infrastructure is broken.
- Add an artifact postcondition for write-producing runs; `done` must require the requested target set to exist or an explicit structured success artifact.

**Confidence**: HIGH.

---

## 4 - Systemic Patterns

### S1 - Configured truth is still winning over operational truth

Issues: `R21-003`, `R21-008`, `R21-013`

GIMO knows how to probe provider readiness and it knows how to score trust/anomaly, but top-level execution still resolves and advertises bindings from config first. The system is still asking "what is configured?" before it asks "what is executable right now?"

This pattern will keep producing:
- 401s and upstream failures instead of fail-closed denials
- misleading active-provider dashboards
- bad auto-routing decisions

### S2 - Surface contracts are still semantically divergent

Issues: `R21-002`, `R21-004`, `R21-007`, `R21-009`, `R21-010`, `R21-011`

Several surfaces are not wrong in isolation; they are describing different subjects:
- providers vs connectors
- configured surfaces vs connected surfaces
- global governance snapshot vs thread-scoped proof state
- agent inventory vs provider topology
- proof bucket scan vs existing conversation thread

This is classic multi-surface drift.

### S3 - Legacy heuristic execution remains in a governed path

Issue: `R21-015`, partial `R21-012`

`legacy_run` still allows:
- prose-only generation
- heuristic file target extraction
- write success despite lint failure
- green completion without semantic artifact validation

That is the opposite of a sharply bounded governed execution model.

### S4 - Audit findings can drift when runtime and checkout are not re-aligned

Issues: `R21-001`, `R21-005`, `R21-006`

At least three Phase 1 findings are not live on the analyzed checkout/runtime. Future audits need a mandatory "revalidate against current checkout" step before Phase 2 turns probe symptoms into engineering work.

---

## 5 - Preventive Findings

1. **Selection invariant**: no adapter may be constructed or invoked until readiness has been checked for the resolved binding. Today this is true only for sub-agent spawn.

2. **Artifact invariant**: no pipeline may write files from raw prose unless the target path is explicit and the content contract is explicit. Heuristic prose-to-file fallback is not acceptable in a governed system.

3. **Surface naming invariant**: CLI/MCP/HTTP commands that describe different subject types must not share misleading names. "Providers", "agents", "surfaces", and "proofs" are overloaded today.

4. **Guardrail integrity invariant**: a review/critic stage must fail closed if its service contract breaks. `critic_error -> continue` is too permissive for write-producing paths.

5. **Phase 2 discipline**: stale findings should be demoted immediately once current-checkout verification disproves them. Phase 3 should not chase ghosts.

---

## 6 - Recommended Fix Priority

1. **R21-003 + R21-008 + R21-013** - Introduce a single readiness-aware binding resolver used by chat, MCP runs, and spawn. This is the biggest leverage change.

2. **R21-015** - Remove heuristic file-write fallback from `legacy_run`, repair the critic stage contract, and require explicit artifact success conditions before `done`.

3. **R21-010 + R21-007** - Unify thread/proof semantics across MCP and HTTP; stop mixing global and thread-scoped governance output.

4. **R21-002 + R21-004 + R21-009 + R21-011** - Clean up surface contracts and names so operators stop reading different truths as one truth.

5. **R21-012** - Decide whether discovery should auto-configure local provider topology or remain informational only; make the contract explicit either way.

6. **STRUCTURAL** - Add cross-surface conformance tests for:
   - provider readiness gating
   - proof verification semantics
   - prompt-based file creation
   - CLI status surface consistency

---

## 7 - Commands and Evidence

Read-only verification commands executed during Phase 2:

```powershell
python gimo.py ps
.\gimo.cmd ps
.\gimo.cmd doctor
python gimo.py providers list
python gimo.py providers auth-status
python gimo.py providers test openai
python gimo.py providers test codex-account
git status --short
```

Supplemental evidence consumed from the earlier MCP smoke:

- draft `d_1775747333494_b1f037`
- failing run `r_1775747350708_7e5c93`
- false-green run `r_1775747419610_c6dba5`
- `.orch_data/ops/run_journals/r_1775747419610_c6dba5.jsonl`
- `.orch_data/ops/run_logs/r_1775747419610_c6dba5.jsonl`
- `.orch_data/ops/runs/r_1775747419610_c6dba5.json`

---

## 8 - Audit Trail

- **This document**: `docs/audits/E2E_ROOT_CAUSE_ANALYSIS_20260409_R21.md`
- **Phase 1 input**: `docs/audits/E2E_AUDIT_LOG_20260409_R21.md`
- **Supplemental smoke summary**: simple app creation via MCP/GIMO from this same audit session
- **Code modified**: none
