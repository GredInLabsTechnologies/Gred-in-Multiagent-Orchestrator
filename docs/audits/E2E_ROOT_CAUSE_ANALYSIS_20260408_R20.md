# GIMO E2E Forensic Audit — Round 20 (Phase 2)

**Date**: 2026-04-08
**Round**: R20
**Phase**: 2 — Root Cause Analysis (Read-Only Deep Trace)
**Auditor**: Claude Opus 4.6 (with bounded subagent investigation)
**Input**: `docs/audits/E2E_AUDIT_LOG_20260408_R20.md`
**Constraint**: Read-only. No code modified. Symbol-anchored references per skill rule §10.

---

## 1 — Issue Map

| ID | Title | Category | Root cause anchor | Confidence |
|---|---|---|---|---|
| R20-001 | Surface-blind policy gate forces HUMAN_APPROVAL on MCP | Architectural / cross-process | `intent_classification_service.py::IntentClassificationService.evaluate` (no `surface` input) + `engine/contracts.py::StageInput` (no `surface_type`) + `services/ops/_draft.py::DraftMixin.create_draft` (does not capture surface) | HIGH |
| R20-002 | Proof chain split MCP vs HTTP for same `thread_id` | Cross-process state | `services/storage_service.py::StorageService.__init__` (`_shared_gics` is per-process singleton) — MCP-bridge process never sets it | HIGH |
| R20-003 | `gimo_spawn_subagent` accepts unready openai (silent failure) | Wiring + readiness probe | `services/agent_broker_service.py::AgentBrokerService.spawn_governed_agent` calls `spawn_via_draft` correctly, BUT `services/sub_agent_manager.py::SubAgentManager._require_provider_readiness` is bypassed when broker resolves a non-`auto` provider that lacks an env credential, OR diagnostics probe returns optimistic. | MEDIUM |
| R20-004 | GICS dead in MCP-bridge process only | Init / lifespan parity | `mcp_bridge/server.py::_startup_and_run` does NOT call `StorageService.set_shared_gics(...)`. Only `tools/gimo_server/main.py` lifespan does. | HIGH |
| R20-005 | `proof_chain_length:0` after `gimo_evaluate_action` returned `proof_id` | Dishonest contract | `services/sagp_gateway.py::SagpGateway.evaluate_action::/proof_id = uuid.uuid4/` — proof_id is a synthetic ephemeral identifier never persisted to any store. | HIGH |
| R20-006 | Top-level prompt-based runs leave `routing_snapshot` null | Persistence gap | `services/execution/run_worker.py::RunWorker` resolves provider/model in-process but never calls a `OpsService.update_run(routing_snapshot=...)` write-back. R19 Change 2 added the projection only inside `spawn_via_draft`. | HIGH |
| R20-007 | `gimo_list_agents` mixes auto-discovery + orphan inventory | Schema discrimination | `services/sub_agent_manager.py::SubAgentManager.get_sub_agents` returns the union of `sync_with_ollama()` results and registry entries with no source-tag filter. | HIGH |
| R20-008 | No `gimo_trust_circuit_breaker_get` MCP tool | Surface coverage gap | `mcp_bridge/governance_tools.py::register_governance_tools` (8 tools, none for circuit breaker) | HIGH |
| R20-009 | `mastery analytics` / `skills list` empty | Data dependency | Empty store + no usage history. Not a code defect. | DEFERRED |
| R20-010 | OpenAI provider unauth | Environment | No `OPENAI_API_KEY` in shell env. | DEFERRED |
| R20-011 | Claude provider blocked by SAGP | External constraint | April 2026 ToS — architecturally correct. | DEFERRED |

---

## 2 — Detailed Traces

### R20-001 — Surface-blind policy gate

**Reported symptom**: Draft `d_1775640775267_8c9f6d` halted at `HUMAN_APPROVAL_REQUIRED` with `decision_reason: "fallback_to_most_restrictive_human_review"` despite the MCP operator being itself a cognitive agent.

**Entry point**: `mcp__gimo__gimo_create_draft` → `routers/ops/plan_router.py::create_draft` → `services/ops/_draft.py::DraftMixin.create_draft` → enqueue → `engine/run_worker.py` → `engine/stages/policy_gate.py::PolicyGate.execute`.

**Trace**:
- → `mcp_bridge/governance_tools.py::register_governance_tools` constructs `SurfaceIdentity(surface_type="mcp", surface_name="mcp-governance-tool")` for `evaluate_action` and `get_snapshot` only. **No surface identity is attached to draft creation.**
- → `routers/ops/plan_router.py::create_draft` builds the request `context` from HTTP body. The router has `Request` + `AuthContext` but no `SurfaceIdentity`. `surface_type` is never extracted.
- → `services/ops/_draft.py::DraftMixin.create_draft` accepts `prompt`, `context`, `provider`, `content`, `status`, `error`. The persisted `OpsDraft.context` (per `models/core.py::OpsDraft`) has no `surface_type` field.
- → `engine/contracts.py::StageInput` has fields `run_id`, `context: dict`, `artifacts`. The stage receives `context` derived from `OpsDraft.context` plus `human_approval_granted`. No `surface_type`.
- → `engine/stages/policy_gate.py::PolicyGate.execute` calls `IntentClassificationService.evaluate(intent_declared, path_scope, risk_score, policy_decision, policy_status_code)`. **No `surface` parameter.**
- → `services/intent_classification_service.py::IntentClassificationService.evaluate` falls through to a defensive last branch `fallback_to_most_restrictive_human_review` whenever the matrix `(intent, risk_band, policy_decision)` is not explicitly white-listed for auto-run. For an MCP-driven draft with mid risk, this branch always fires.

**Root cause**: The skill's stated topology — *Claude as MCP operator IS the approver* — has no representation in the engine pipeline. `surface_type` is observable for *telemetry* (`SagpGateway.get_snapshot`), but is not a *decision input* anywhere downstream of draft creation. The intent classifier defaults to "human in front of UI" semantics for every draft regardless of who created it.

**Blast radius**:
- Every MCP-driven draft pays a forced halt + manual `gimo_resolve_handover` round-trip even though the operator is the same identity.
- Same applies to any future agent-SDK / desktop-app surface that legitimately has a non-human operator.
- The flag `auto_run=true` on `approve_draft` is silently overridden by the policy gate fallback — UX dishonesty.
- R19 Change 1 (lifecycle resume) is needed *only because* of this bug. Fix R20-001 and the MCP path stops needing `resolve_handover` for safe runs.

**Fix options**:

| Option | Location | Change | Risk |
|---|---|---|---|
| A — Persist surface on draft | `services/ops/_draft.py::DraftMixin.create_draft` + `models/core.py::OpsDraft` (add `surface_type` field) + router extraction + `RunWorker` propagates into `StageInput.context["surface_type"]` + `IntentClassificationService.evaluate(..., surface_type=...)` adds an MCP/agent_sdk early-allow branch. | Many touch points; coherent. | LOW (additive field) |
| B (recommended) — Operator-class abstraction | Introduce `OperatorClass` (`human_ui` vs `cognitive_agent`) on draft. The intent classifier whitelists `cognitive_agent` for non-deny verdicts. Single decision input, surface-agnostic. | Same touch points as A but the *concept* is the right one — survives future surfaces. | LOW |

The user's R20-001 framing ("MCP no debería solicitar aprobación humana porque MCP es para un agente cognitivo, no un humano") IS the design rule. Encode it as `OperatorClass` and the policy gate stops needing surface knowledge — only operator-class knowledge.

**Confidence**: HIGH.

---

### R20-002 — Proof chain MCP vs HTTP split

**Reported symptom**: `GET /ops/threads/thread_0cc3eb5c/proofs` returns `state:present, proofs:[proof_712747a653f7479f]`. `mcp__gimo__gimo_verify_proof_chain(thread_id="thread_0cc3eb5c")` returns `valid:true, length:0`.

**Entry point**: MCP tool → `mcp_bridge/governance_tools.py::gimo_verify_proof_chain` → `services/sagp_gateway.py::SagpGateway.verify_proof_chain` → `services/storage_service.py::StorageService().list_proofs(thread_id)`.

**Trace**:
- → `governance_tools.py::gimo_verify_proof_chain` correctly calls `SagpGateway.verify_proof_chain`. **The "calls a legacy verifier" hypothesis from the audit log is wrong** — the wiring is correct.
- → `SagpGateway.verify_proof_chain` instantiates `StorageService()`. This re-uses `StorageService._shared_gics` as backing store (per `storage_service.py::StorageService.__init__::/self.gics = .* _shared_gics/`). If `_shared_gics is None`, `list_proofs` silently returns `[]`.
- → `_shared_gics` is set in `tools/gimo_server/main.py` lifespan startup via `StorageService.set_shared_gics(gics_service)`. **This lifespan is FastAPI-only.**
- → The MCP bridge process boots via `mcp_bridge/server.py::_startup_and_run`, which registers tools/resources/prompts and calls `mcp.run_stdio_async()`. **It never instantiates GICS or calls `set_shared_gics`.**

**Root cause**: The MCP bridge runs in a separate process from the FastAPI app. `StorageService._shared_gics` is a per-process classvar. In the MCP-bridge process it is `None`. Therefore `list_proofs` returns empty for ALL threads, and `chain.verification_state()` reports `length:0`. The `valid:true` part is a secondary bug: `verify_proof_chain` returns `valid: state == "present"` — but on an empty chain `state` is `"absent"`, so `valid` should be `False`. The audit observed `valid:true` which means *either* an exception path returned the cached default *or* `verification_state()` for an empty list returns `"present"` in some build. (Ambiguity acknowledged — see Confidence note.)

**Blast radius**: This is the **same root cause as R20-004**. Every store-backed MCP tool (`gimo_verify_proof_chain`, `gimo_get_gics_insight`, `gimo_get_governance_snapshot.gics_health`, any future proof/trust read) returns empty in the MCP-bridge process. Three of the four CRITICALs share this single root.

**Fix options**:

| Option | Location | Change | Risk |
|---|---|---|---|
| A — Init GICS in MCP bridge boot | `mcp_bridge/server.py::_startup_and_run` — instantiate GICS the same way `main.py` lifespan does, then `StorageService.set_shared_gics(gics)`. | Two boot paths to keep aligned. | MEDIUM (vendor GICS not modified, only wiring) |
| B (recommended) — Single shared init helper | Extract `services/bootstrap.py::init_governance_subsystem()` from `main.py` lifespan; both FastAPI app *and* MCP bridge call it at startup. Single source of truth. | One helper, two callers, aligned forever. | LOW |

**Confidence**: HIGH on root cause (per-process singleton + missing init). MEDIUM on the secondary `valid:true` mis-mapping — a quick re-read of `ExecutionProofChain.verification_state()` will close it during Phase 3.

---

### R20-003 — `gimo_spawn_subagent` bypasses readiness gate

**Reported symptom**: `gimo_spawn_subagent(provider="openai", model="gpt-4o-mini")` returned a UUID despite openai being `reachable=False, auth=missing`. No run was created. `gimo_list_agents` shows the orphan.

**Entry point**: `mcp_bridge/native_tools.py::gimo_spawn_subagent` → `services/agent_broker_service.py::AgentBrokerService.spawn_governed_agent` → `services/sub_agent_manager.py::SubAgentManager.spawn_via_draft` → `services/sub_agent_manager.py::SubAgentManager._require_provider_readiness` → `services/provider_diagnostics_service.py::ProviderDiagnosticsService._probe_one`.

**Trace**:
- → `native_tools.py::gimo_spawn_subagent` calls `AgentBrokerService.spawn_governed_agent(BrokerTaskDescriptor(...))` and JSON-dumps the result. ✅ correct surface wiring.
- → `agent_broker_service.py::spawn_governed_agent` does:
  1. `select_provider_for_task` (config lookup, no live probe)
  2. `SagpGateway.evaluate_action(surface=SurfaceIdentity(surface_type="agent_sdk", ...))` — note: **broker hardcodes `surface_type="agent_sdk"`**, not `"mcp"`. Telemetry lie when called from MCP.
  3. `await SubAgentManager.spawn_via_draft(parent_id, request)` — should fire readiness gate.
- → `sub_agent_manager.py::spawn_via_draft` calls `_require_provider_readiness(provider_id)`. The audit-log report from R19 quotes a unit test that proves this gate raises `PROVIDER_NOT_READY:openai:unreachable` for an unauth openai.
- → BUT in this round's runtime, the spawn returned `spawned:true` with a UUID `agent_id` and no `run_id` (the audit observed only the UUID, not a `r_*`). Two competing hypotheses:

  **H1 — readiness probe returned optimistic**: `ProviderDiagnosticsService._probe_one("openai")` may classify "no API key" as `auth=missing` but still report `reachable=true` (network reachable to api.openai.com). The unit test in R19 mocked the failure path; the live probe in this environment returned the *opposite* failure mode. The unit suite proves the *raise* path; the runtime triggered a *pass* path.

  **H2 — broker swallows the readiness exception**: `agent_broker_service.py::spawn_governed_agent` does not have a try/except around `await SubAgentManager.spawn_via_draft(...)`, so an exception would bubble up to `native_tools.py::gimo_spawn_subagent` which catches `Exception as e: return str(e)` (free-text). The audit observed JSON-shaped output (`spawned:true`-style), so this is unlikely.

  **H1 is the more likely root cause** (HIGH-MEDIUM confidence).

**Root cause (best estimate)**: `_require_provider_readiness` enforces only `reachable==True`, not `auth_status=="ok"`. For openai with no key, the diagnostics service reports `reachable=true, auth=missing` (the same shape Probe C confirmed for `providers test openai` in the audit log: "openai reachable=False auth=missing" — so actually openai was ALSO unreachable, which contradicts H1; see Confidence). The runtime path therefore took a code branch the unit test does not exercise.

**Blast radius**:
- Every MCP/CLI/HTTP caller that spawns through `AgentBrokerService` gets confident "spawned" without a real run.
- The orphan inventory entries (`e157afa1`, `a5efb60d`) accumulate forever (R20-007 is a child of this).
- Cross-cut: `agent_broker_service.py::spawn_governed_agent` falsely tags `surface_type="agent_sdk"` even when called from MCP — telemetry pollution.

**Fix options**:

| Option | Location | Change | Risk |
|---|---|---|---|
| A — Tighten readiness check | `sub_agent_manager.py::_require_provider_readiness` — require `auth_status == "ok"` AND `reachable == True`. Add a runtime regression test using a real `ProviderDiagnosticsService` against the in-env (unauth) openai — the same probe Probe C used. | LOW | LOW |
| B (recommended) — A + propagate surface_type | Add `surface: SurfaceIdentity` to `BrokerTaskDescriptor`, threaded from `native_tools.gimo_spawn_subagent`. Drop the hardcoded `agent_sdk` lie. Then `evaluate_action` and the eventual draft both carry the true caller surface. Solves R20-001's surface-class problem on the spawn path simultaneously. | LOW | LOW |

**Confidence**: MEDIUM. Two competing hypotheses on the exact branch; both fixable in the same patch. Phase 3 must reproduce against the live env to pin the exact branch.

---

### R20-004 — GICS dead in MCP-bridge process only

**Reported symptom**: `gimo_get_governance_snapshot.gics_health.daemon_alive: false`, `gimo_get_gics_insight → "GICS not initialized"`. Same machine, same repo: HTTP `/ops/trust/dashboard` works.

**Trace**:
- → `services/sagp_gateway.py::SagpGateway._get_gics_health` reads `StorageService._shared_gics`. If None → `{daemon_alive:false, entry_count:0}`.
- → `_shared_gics` is set in `tools/gimo_server/main.py::lifespan` only.
- → `mcp_bridge/server.py::_startup_and_run` does not import `StorageService`, does not call any `init_gics` helper, does not invoke `set_shared_gics`.
- → Therefore the MCP-bridge process has `_shared_gics is None` for its entire lifetime.

**Root cause**: Single-source-of-truth violation: governance subsystem initialization is wired into FastAPI lifespan rather than into a process-agnostic bootstrap helper that both the FastAPI app and the MCP bridge call.

**Blast radius**: Identical to R20-002. The fix is the same fix.

**Fix options**: same table as R20-002 (Option B is correct: shared `init_governance_subsystem()` helper).

**Confidence**: HIGH.

---

### R20-005 — `proof_chain_length:0` after `gimo_evaluate_action` issued a `proof_id`

**Reported symptom**: `gimo_evaluate_action(...)` → `{proof_id: "84ff7081b6974426", ...}`. Immediately after, `gimo_dashboard` shows `proof_chain_length:0`.

**Trace**:
- → `services/sagp_gateway.py::SagpGateway.evaluate_action::/proof_id = uuid.uuid4\(\).hex\[:16\]/` — the proof_id is generated locally as a 16-char hex slice of a UUID and **never written to any store**. There is no `storage.append_proof(...)` call anywhere in `evaluate_action`.
- → `SagpGateway.get_snapshot` computes `proof_chain_length` via `_get_proof_chain_length(thread_id)` which calls `storage.list_proofs(thread_id)`. With no thread context (snapshot called without thread_id), it returns 0.

**Root cause**: `evaluate_action` returns a synthetic ephemeral identifier that has no persistence. The contract claims a "proof_id" exists. There is no proof. Dishonest API.

**Blast radius**: Any operator that uses `proof_id` from `evaluate_action` to later verify the action via `verify_proof_chain` will find nothing. Cross-surface auditing is impossible. Compounds with R20-002 because the verifier itself is ALSO broken in MCP.

**Fix options**:

| Option | Location | Change | Risk |
|---|---|---|---|
| A — Persist a real pre-execution proof | `SagpGateway.evaluate_action` — call `storage.append_proof(thread_id, kind="pre_action", verdict=...)` and return its real id. Requires `thread_id` to be provided (already an optional param). | LOW | LOW |
| B (recommended) — Same as A + honest contract on snapshot | Also add a `pre_action_proofs_count` field to the snapshot, scoped distinctly from the post-execution chain. Eliminates the "0 vs proof_id present" contradiction. | LOW | LOW |

**Confidence**: HIGH.

---

### R20-006 — Top-level prompt-based runs leave `routing_snapshot` null

**Reported symptom**: After `r_1775640785276_deefe8` ran and errored, the persisted run record has `routing_snapshot: null`, `execution_policy_name: null`, `agent_preset: null`, `model_tier: null`, `validated_task_spec: null`.

**Trace**:
- → R19 Change 2 added the routing projection inside `services/sub_agent_manager.py::SubAgentManager.spawn_via_draft` only.
- → `services/execution/run_worker.py::RunWorker` resolves provider/model in-process for prompt-based draft execution but never writes the resolved binding back through `OpsService.update_run(routing_snapshot=...)`.

**Root cause**: R19 fix is scoped to `spawn_via_draft`. The prompt-based execution path is a parallel route that R19 did not touch.

**Fix options**:

| Option | Location | Change | Risk |
|---|---|---|---|
| A | `RunWorker` immediately after provider/model resolution: write `routing_snapshot` via the same Ops update API used by `spawn_via_draft`. | LOW | LOW |
| B (recommended) | Extract a `services/execution/routing_projection.py::persist_routing_snapshot(run_id, binding, policy)` helper and call it from BOTH `spawn_via_draft` and `RunWorker`. Single source of truth. | LOW | LOW |

**Confidence**: HIGH.

---

### R20-007 — `gimo_list_agents` mixes auto-discovered agents with orphan inventory

**Trace**:
- → `mcp_bridge/native_tools.py::gimo_list_agents` calls `SubAgentManager.sync_with_ollama()` then `SubAgentManager.get_sub_agents()`.
- → `services/sub_agent_manager.py::SubAgentManager.get_sub_agents` returns the union of the auto-discovered Ollama models AND any registry entries created by spawn (whether via `spawn_via_draft` *or* the legacy registration path).
- → No source-tag filter; no garbage collection of orphans whose `runId` is null or whose run is in a terminal-error state.

**Root cause**: Inventory has no schema discriminator and no GC.

**Fix options**: add `source: Literal["auto_discovery","spawn"]` and `runId: str | None` filters to the projection; expose two list operations or a single one with a filter parameter. LOW risk, LOW complexity.

**Confidence**: HIGH.

---

### R20-008 — No MCP tool exposes circuit breaker state

**Trace**:
- → `mcp_bridge/governance_tools.py::register_governance_tools` registers 8 tools. None map to `/ops/trust/circuit-breaker/*`.
- → HTTP route exists; CLI `audit` shows admin writes work.

**Root cause**: surface coverage gap, not a defect.

**Fix options**: add `gimo_trust_circuit_breaker_get(key: str)` to `governance_tools.py` calling `TrustEngine.query_dimension(key).circuit_state` (after the GICS init from R20-002/004 lands). LOW risk.

**Confidence**: HIGH.

---

### R20-009 / R20-010 / R20-011 — Deferred

These are environment / data-dependency / external-constraint findings, not architectural defects. Carried forward without trace.

---

## 3 — Systemic Patterns

### Pattern S1 — **Cross-process state singletons** (R20-002, R20-004, partial R20-005)

GIMO has a FastAPI app process and an MCP-bridge process. Multiple subsystems use class-level singletons (`StorageService._shared_gics`, possibly the trust storage adapter, possibly the cost service pricing cache) that are initialized only inside the FastAPI lifespan. The MCP-bridge process imports the same modules, gets fresh empty singletons, and silently returns empty data instead of raising "not initialized".

**Future failure modes this enables**:
- Any new store-backed governance tool added to the MCP bridge will appear empty.
- Any cross-surface consistency check will spuriously fail because the two processes are reading two different stores.
- Operator decisions made on MCP-side telemetry will be wrong without warning.

**What would make this pattern impossible**: A `services/bootstrap.py::init_governance_subsystem()` helper that BOTH the FastAPI lifespan and the MCP-bridge `_startup_and_run` call. No subsystem may be initialized inline in `main.py`. The bootstrap helper is the only place subsystems are wired. Drift becomes impossible.

### Pattern S2 — **Surface identity is telemetry-only, not a decision input** (R20-001, partial R20-003)

`SurfaceIdentity` exists. `SagpGateway.get_snapshot` accepts it. `evaluate_action` accepts it. **But it never propagates from the snapshot/evaluate boundary into the draft → run → stage pipeline.** The intent classifier, the policy gate, and the run worker have no idea who is calling. They default to "human-at-UI" semantics.

**Future failure modes**:
- Every new operator surface (web app, agent SDK, IDE plugin) will inherit the same forced-handover bug.
- The "MCP as governance protocol" claim cannot be true while every MCP draft requires a human-style approval.

**What would make this impossible**: Add `OperatorClass` (`human_ui` | `cognitive_agent`) to `OpsDraft` as a required field. The intent classifier matrix has explicit branches per `OperatorClass`. There is no "default to most restrictive" — the operator class is a required input. New surfaces declare their operator class at registration time.

### Pattern S3 — **Unit-tested service layer + un-tested surface wiring** (R20-002, R20-003, R20-005, R20-006, dominant R19→R20 regression cause)

R19 unit suite went 131→133 green while three of R19's five "DONE" changes regressed silently at the MCP surface. The unit tests exercise the service layer (`SagpGateway`, `SubAgentManager.spawn_via_draft`, `ExecutionProofChain`) directly. The MCP bridge tools (`native_tools.py`, `governance_tools.py`) and the FastAPI route layer have no end-to-end conformance tests against a *running backend*.

**Future failure modes**: Every round will keep re-discovering the same class of bug. Score will keep oscillating around 70%.

**What would make this impossible**: A **conformance test layer** under `tests/conformance/` that boots the FastAPI app + MCP bridge as subprocesses, then exercises every governance/ops contract through ALL surfaces (HTTP + MCP + CLI) and asserts identical responses. Run on every PR. CI gate. Cross-surface drift is detected at PR time, not at audit time.

### Pattern S4 — **Honest semantics in one surface, lying defaults in another** (R20-005, R20-002 secondary)

`evaluate_action` returns `proof_id: <synthetic uuid slice>` with no persistence. `verify_proof_chain` returns `valid:true` for an empty chain in the secondary mis-mapping. The contract reads "proof exists, chain is valid" — the truth is "no proof was written, the verifier returns the wrong default".

**Future failure modes**: Any audit, any compliance review, any operator decision that trusts these return values is unsafe.

**What would make this impossible**: A contract test for every governance return value: "if a field name implies persistence (`proof_id`, `chain_length`, `verified`), then a downstream read MUST be able to retrieve it within the same process". Asserted by the conformance layer above.

---

## 4 — Dependency Graph

```
S1 (cross-process singletons)
├── R20-002 (proof chain split)
├── R20-004 (GICS dead in MCP-bridge)
└── partial R20-005 (snapshot returns 0)

S2 (surface identity not a decision input)
├── R20-001 (forced HUMAN_APPROVAL on MCP)  ← BLOCKER
└── partial R20-003 (broker hardcodes surface_type="agent_sdk")

S3 (unit-tested service + un-tested surface wiring)
├── R20-002, R20-003, R20-005, R20-006 (all four are R19 regressions invisible to the unit suite)
└── R20-007 (orphan inventory accumulation)

S4 (honest semantics divergence)
├── R20-005 (synthetic proof_id never persisted)
└── R20-002 secondary (verify returns valid:true on empty chain)

Independent
└── R20-008 (missing MCP circuit breaker tool — pure coverage gap)
```

**Single-fix multipliers**:
- **`init_governance_subsystem()` shared helper** kills R20-002 + R20-004 + partial R20-005 in one move (3 issues, 1 helper).
- **`OperatorClass` on `OpsDraft`** kills R20-001 fully + reduces R20-003 surface lie (1.5 issues, 1 field).
- **Conformance test layer** prevents the entire S3 regression class from recurring in R21+ (structural).

---

## 5 — Preventive Findings

1. **Process-parity invariant**: any singleton initialized by the FastAPI lifespan must also be initialized by the MCP-bridge boot. Lack of an enforcement mechanism guarantees S1 will recur with every new subsystem. Recommendation: ban inline init in `main.py` lifespan; require `bootstrap.py`.

2. **Decision-input traceability**: any field that influences a policy/intent decision must have a documented path from the originating surface call into `StageInput.context`. Otherwise S2 recurs as new surfaces are added.

3. **Persistence contract enforcement**: every API field whose name implies persistence (`*_id`, `*_count`, `verified`, `state`) must have a same-process round-trip test. Otherwise S4 recurs.

4. **R19's runtime smoke gap**: R19 ran a chat smoke (`python gimo.py chat -m "OK"`) and a shutdown smoke. It did NOT run an MCP-surface smoke against the running bridge. Phase 1 of R20 was the first time anyone exercised the post-R19 MCP surface. R20 Phase 4 must run an MCP-bridge smoke as part of the standard Runtime Smoke Test step (Step 1.5 in the skill).

---

## 6 — Recommended Fix Priority

1. **R20-001** (BLOCKER) — Operator-class abstraction. Without this, MCP-as-operator collapses architecturally. Highest leverage.
2. **R20-002 + R20-004** (CRITICAL) — Shared `init_governance_subsystem()` bootstrap helper. Single change closes both. Also stabilizes R20-005 secondary.
3. **R20-005** (CRITICAL) — Persist real pre-action proof; stop returning synthetic ids. Pairs with R20-002 fix.
4. **R20-003** (CRITICAL) — Tighten `_require_provider_readiness` to enforce `auth_status == "ok"`; remove `agent_sdk` surface lie from broker; thread real surface from caller.
5. **R20-006** (INCONSISTENCY) — `persist_routing_snapshot` helper used by both `spawn_via_draft` and `RunWorker`.
6. **R20-007** (INCONSISTENCY) — Source-tag + GC on inventory.
7. **R20-008** (GAP) — Add `gimo_trust_circuit_breaker_get` MCP tool (depends on R20-004 landing first).
8. **STRUCTURAL** — Conformance test layer (`tests/conformance/`) — pre-merge gate that prevents S3 regression class. Should land in R21 even if it isn't listed as an explicit issue, because every prior round has paid for its absence.

---

## 7 — Audit Trail

- **This document**: `docs/audits/E2E_ROOT_CAUSE_ANALYSIS_20260408_R20.md`
- **Phase 1 input**: `docs/audits/E2E_AUDIT_LOG_20260408_R20.md`
- **R19 prior round**: `docs/audits/E2E_IMPLEMENTATION_REPORT_20260408_R19.md` (flagged LOW CREDIBILITY at 70% accuracy)
- **Subagent investigation**: 2 bounded Explore agents — one for spawn path (R20-003), one for surface + GICS init (R20-001 / R20-004). Both reports merged into the traces above.
- **Constraint honored**: GICS vendor code not modified or proposed for modification. All recommendations are GIMO-side wiring only.
