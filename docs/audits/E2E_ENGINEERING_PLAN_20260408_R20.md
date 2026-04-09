# GIMO E2E Forensic Audit — Round 20 (Phase 3)

**Date**: 2026-04-08
**Round**: R20
**Phase**: 3 — SOTA Research & Engineering Plan
**Author**: Claude Opus 4.6
**Inputs**:
- `docs/audits/E2E_AUDIT_LOG_20260408_R20.md` (Phase 1)
- `docs/audits/E2E_ROOT_CAUSE_ANALYSIS_20260408_R20.md` (Phase 2)
**Design philosophy** (LAW for this plan):
- `docs/SYSTEM.md`
- `AGENTS.md`
- `docs/CLIENT_SURFACES.md`

---

## 1 — Diagnosis Summary (3 sentences)

GIMO has the right architecture on paper — *single backend, SAGP gateway, all surfaces are thin clients* — but the implementation has two structural cracks that R20 exposed: (a) governance subsystem state lives in per-process class singletons initialized only by the FastAPI lifespan, so the MCP-bridge process is silently empty; (b) `SurfaceIdentity` is captured as telemetry but never propagates into the policy/intent decision pipeline, so every cognitive-agent caller is treated as a human at a UI and forced through `HUMAN_APPROVAL_REQUIRED`. Both cracks were invisible to R19's unit suite because the unit tests exercise the service layer directly while the MCP bridge boots a separate process and the policy gate is tested without surface inputs.

The plan is one strong concept: **a single `governance_bootstrap` module + an `OperatorClass` field threaded through the draft → run → policy pipeline**. Everything else is corollary.

---

## 2 — Design Philosophy Alignment

| Doctrine (`CLIENT_SURFACES.md`, `AGENTS.md`) | R20 violation | Plan response |
|---|---|---|
| "All domain logic, execution authority, and state persistence lives strictly in the backend services" | MCP-bridge process has divergent (empty) state from FastAPI process | Single `governance_bootstrap.init()` called by both processes |
| "All surfaces — without exception — traverse the SagpGateway before any action" | MCP traverses `SagpGateway.evaluate_action`, but the *result* is correct while the *downstream pipeline* (PolicyGate → IntentClassifier) is surface-blind | `OperatorClass` becomes a first-class input to the intent classifier matrix |
| "no surface-specific lie, drift, fake status, or duplicated business logic" | `evaluate_action` returns synthetic `proof_id` never persisted (R20-005) | Honest contract: persist a `pre_action` proof OR remove the field |
| "do not silently patch one surface while leaving others semantically broken" | R19 fixed proof/spawn on one surface (HTTP/service) and broke them on MCP | Conformance test layer that executes the same operation on all surfaces and asserts equality |
| "exactly one orchestrator authority per active session" | When MCP is the operator, GIMO forces a second human approval step — *de facto* a second authority | OperatorClass="cognitive_agent" + matching policy branch removes the second authority |

The plan does not deviate from the doctrine. Every change is the doctrine made executable.

### 2.bis — Backend lógico vs backend físico (resolución de la aparente contradicción)

La doctrina dice "todas las superficies comparten el mismo backend". La realidad observada en R20 es que el puente MCP corre en un proceso aparte del FastAPI. Esto **no** es contradictorio una vez separamos dos sentidos del término *backend*:

- **Backend lógico** (estado de verdad): el conjunto único de stores, contratos canónicos y servicios de autoridad — `.orch_data/`, GICS, `EngineService`, `RunWorker`, `MergeGateService`, `SagpGateway`. Es **conceptual**, no un proceso. La doctrina se refiere a éste.
- **Backend físico** (binario en ejecución): el proceso `uvicorn` que sirve FastAPI en :9325. Es **un proceso**, no la verdad.

El protocolo MCP via stdio **obliga** a que el cliente (Claude Desktop, VS Code, Codex) lance el servidor MCP como subproceso vía Popen sobre stdio. No es una elección de arquitectura; es el contrato del transporte. Por tanto **dos procesos físicos son inevitables** mientras GIMO exponga superficie MCP. La pregunta no es "¿cómo eliminamos el segundo proceso?" sino "¿cómo aseguramos que ambos procesos hablen con el **mismo backend lógico**?".

Hay tres opciones de implementación:

| Opción | Mecanismo | Latencia | Usado por |
|---|---|---|---|
| **A** | El puente MCP proxya cada llamada vía HTTP al backend físico | ms | Ya usado en GIMO para mutaciones de ciclo de vida (`proxy_to_api()` en `native_tools.py`) |
| **B** | Ambos procesos abren el mismo store local con el mismo `repo_root`; GICS coordina vía lockfile | µs | **Plan R20** lo adopta para estado de gobernanza de solo-lectura |
| **C (rota)** | Pretender que un classvar de Python (`StorageService._shared_gics`) es global entre procesos | n/a | **Lo que GIMO hace hoy** — origen de R20-002/004 |

**Por qué el plan usa B para estado read-only y A para mutaciones de ciclo de vida**:

1. **Latencia**: las llamadas de gobernanza (proof chain, GICS health, snapshot) ocurren en cada tool call MCP. Round-trip HTTP en cada una multiplica latencia por 100×.
2. **Disponibilidad**: el puente MCP debe poder responder `gimo_get_governance_snapshot` aunque el proceso FastAPI no esté arriba. Con B sigue funcionando degradado; con A se cae entero.
3. **Honestidad del modo de fallo**: con B, si GICS no arranca, el snapshot reporta `daemon_alive=false`. Con A, un timeout HTTP es ambiguo (¿caído? ¿lento? ¿auth?). B falla más legiblemente.

Las **mutaciones** (crear draft, aprobar, ejecutar) sí pasan por A — el puente MCP llama por HTTP al backend físico, que es la única autoridad de escritura. Esto preserva la doctrina "exactly one orchestrator authority per active session": **el backend lógico es uno**, aunque dos procesos físicos lo lean.

Cambio 1 (`init_governance_subsystem`) es exactamente esto: hace que el puente MCP y FastAPI inicialicen el mismo backend lógico (Opción B) en lugar del classvar roto (Opción C).

---

## 3 — Competitive Landscape & Verified SOTA Research

This section was rewritten after **live web research (April 2026)**. Citations are at the end.

### 3.1 — Operator-class abstraction for HITL (R20-001)

**Verified SOTA**: **Pinterest's production MCP ecosystem** [InfoQ, April 2026] is currently the most rigorous deployment of the same axis GIMO needs. Pinterest:
- Uses **end-user JWTs to control human-in-the-loop access** — the human path.
- Uses **mesh identities for service-only flows** — the cognitive/service path.
- **Implements fine-grained authorization decorators and business-group gating** at the MCP server, restricting high-privilege operations to approved teams.

**This is `OperatorClass` operating at scale in production.** The fact that Pinterest had to roll their own discriminator confirms two things: (a) the abstraction is correct, (b) the agentic-coding tools (Claude Code, Cursor, Aider, Cline) do NOT yet expose it as a first-class concept.

**OPA Rego canonical shape**: per Apache Polaris's OPA integration, the `actor` object carries `principal` + `roles` (e.g. `{"principal": "user@example.com", "roles": ["role1","role2"]}`). Resources carry a `type` field for granular RBAC/ABAC. This is the directly applicable shape for `OperatorClass`: GIMO's `infer_operator_class(surface)` is the GIMO-side equivalent of the Polaris pattern, narrowed to the policy axis that matters (`human_ui` vs `cognitive_agent` vs `service_account`).

**MCP 2026 Roadmap** [modelcontextprotocol.io, 2026]: explicitly lists "governance maturation" as a top-tier item, with Working Groups, Spec Enhancement Proposals (SEPs), and a formal governance process. This means operator-class is in scope for the protocol itself within the next year. **GIMO landing it now is "first to ship" not "ahead of standard" — when the SEP arrives, GIMO already implements it.**

**Honest delta vs my draft**: I had claimed "**none** of the agentic-coding competitors do this". The corrected statement is: **Pinterest's general MCP deployment does it**, but no *agentic-coding* product (Cursor, Aider, Cline, OpenHands, Devin, Claude Code, CrewAI, LangGraph) does. GIMO would still be first in its category, but is following Pinterest's lead in spirit. That is *less* disruptive than I claimed — but no less correct.

### 3.2 — Real-time MCP policy controls (R20-002/004/005)

**Verified SOTA**: **SurePath AI MCP Policy Controls** [PRNewswire, 2026] already ships real-time policy controls "over what MCP servers and tools are allowed to be used, helping organizations adopt MCP safely with visibility and safeguards from day one". **This is direct competition for the SAGP gateway.**

**Honest delta vs my draft**: I had implicitly framed SAGP as a unique GIMO concept. SurePath has shipped a competing offering. **GIMO's real differentiator is not "policy at the gate" — it is (a) honest persistence contracts (R20-005 fix) and (b) cross-process state coherence (R20-002/004 fix)**. Both of which SurePath does NOT yet appear to have based on the available coverage.

**Microsoft's internal MCP rollout** [Inside Track, Microsoft] confirms the pattern that **MCP clients should "pause risky actions, notify the owner, and resume automatically once reviewed"** — i.e. the resume-after-handover flow GIMO already implements (R19 Change 1). That is the canonical pattern; GIMO matches it.

### 3.3 — Cross-surface conformance testing (S3 prevention)

**Verified SOTA**: **CNCF Kubernetes AI Conformance Program v1.35** [Let's Data Science, 2026] has formal cross-platform AI conformance requirements: hardware orchestration, agentic workload validation, workload-aware scheduling. **This is the closest precedent for a cross-surface agent-orchestration conformance test suite.** Strongdm's `attractorbench` / NLSpec also targets agent instruction-following as a parity benchmark.

**No direct precedent yet exists for cross-surface (HTTP + MCP + CLI) parity tests in agent-orchestration products.** The 2026 stack reviews [The New Stack; PYMNTS] confirm the orchestration-layer battle is intensifying but the parity-by-construction angle is still open.

**Honest delta**: my draft claimed "no agent-orchestration competitor has a cross-surface conformance layer". Web research confirms this is still true at the *cross-surface* axis. The CNCF Kubernetes AI Conformance Program operates at the *cluster* axis, not the *surface* axis. So Change 5 remains a real disruptive opening, but framed accurately: GIMO is the first agent-orchestration product to apply the *Kubernetes-style conformance gate pattern* to *its own surfaces* (HTTP/MCP/CLI parity).

### 3.4 — Bootstrap helper pattern (R20-002/004)

**Verified prior art**: This is the boring / well-established part — Django's `apps.AppConfig.ready()`, Spring `@PostConstruct`, Argo CD's `cmd/util/initialize.go`, FastAPI/FastMCP integration patterns [tadata-org/fastapi_mcp; PrefectHQ/fastmcp]. The 2026 FastAPI-MCP integration guides confirm **mounting an MCP server on a FastAPI app via `FastApiMCP(app).mount()` is the canonical pattern**, but neither library prescribes how to share singleton state when the MCP bridge runs in a separate process. **GIMO must own this wiring itself.** No novelty needed; just discipline.

### 3.5 — Competitive matrix (revised after research)

| System | What they get RIGHT | What they get WRONG | What GIMO does BETTER |
|---|---|---|---|
| **Pinterest production MCP** | JWT-vs-mesh-identity discriminator (= OperatorClass in spirit); fine-grained authorization decorators; business-group gating | Internal-only; not a product; no cross-surface parity layer | GIMO ships this as an open product with cross-surface conformance |
| **SurePath AI MCP Policy Controls** | Real-time policy controls, visibility, "safe by day one" framing | No public evidence of honest persistence contracts or cross-process state coherence | GIMO closes both R20-002/004 and R20-005 with a single bootstrap + honest proof persistence |
| **Microsoft MCP rollout** | Pause-notify-resume HITL pattern (matches GIMO R19 Change 1) | Not a product; internal | GIMO implements the same pattern AND lets a cognitive operator skip the human pause via OperatorClass |
| **Apache Polaris + OPA Rego** | Canonical `actor.principal+roles` + resource `type` shape | Not LLM-aware; no cognitive-agent class | GIMO's `OperatorClass` is the LLM-aware version of Polaris's actor model |
| **CNCF Kubernetes AI Conformance v1.35** | Formal AI conformance program; agentic workload validation | Cluster-axis only; not surface-axis | GIMO applies the same gate pattern to HTTP/MCP/CLI surface parity |
| **Claude Code** | Canonical MCP cognitive operator | No persistence/governance authority — trusts every tool call | GIMO is the governance authority FOR Claude Code, not in competition |
| **Cursor / Aider / Cline / OpenHands / Devin / CrewAI / LangGraph** | Various ergonomic strengths | None expose `OperatorClass`, none have cross-surface conformance, none have honest persistence contracts | GIMO ships all three |

### 3.6 — Net SOTA delta (corrected, brutally honest)

| Plan element | Pre-research claim | Post-research truth |
|---|---|---|
| OperatorClass | "Disruptive opening, no competitor does this" | "First in category among agentic-coding tools; Pinterest already does it in general MCP at scale → GIMO is following a proven production pattern, not inventing one" |
| Honest persistence | (implied novel) | "Real differentiator vs SurePath. SurePath does policy controls but no public evidence of honest persistence contracts" |
| Cross-process bootstrap | (implied novel) | "Pure discipline, no novelty. CNCF / FastAPI-MCP integration guides do not solve this for the multi-process case" |
| Conformance layer | "Disruptive opening" | "Real disruptive opening at the *surface-parity* axis. CNCF v1.35 is precedent at cluster axis" |
| Pause-notify-resume HITL | (not claimed) | "Already in GIMO via R19 Change 1; matches Microsoft's canonical pattern" |

**Conclusion**: the plan is **stronger** after research, not weaker. Three of the four major elements have either production prior art (validating the design) or are real first-in-category for agentic-coding. The fourth (cross-process bootstrap) is pure engineering discipline and needs no SOTA defense.

---

## 4 — Design Principles for the Fix

1. **Single bootstrap, single state**: governance subsystem state lives in one initializer, called by every process that needs it. No subsystem may be initialized inline by `main.py` lifespan only.
2. **Operator class is a decision input, not telemetry**: the intent classifier matrix branches explicitly on `OperatorClass`. There is no "default to most restrictive" — the operator class is required.
3. **Honest persistence contracts**: every API field whose name implies persistence (`*_id`, `*_count`, `verified`, `state`) must round-trip in the same process. Synthetic ids are forbidden.
4. **Conformance over coverage**: the value of a test is whether it would have caught R19's regressions, not the line-count it touches. Add the smallest layer that asserts cross-surface equality.
5. **Surface parity by construction, not by audit**: the bug shape "unit test green, MCP broken" must become structurally impossible.

---

## 5 — The Plan

Five changes. Three are core fixes (Changes 1, 2, 3). One is a multi-issue cleanup (Change 4). One is the structural lock (Change 5). The dependency order matters — implement in order.

---

#### Change 1 — `governance_bootstrap` module + dual-process init

- **Solves issues**: R20-002, R20-004, partial R20-005 (snapshot reads), and the structural pattern S1.
- **What**: Extract every governance-subsystem initialization currently inline in `tools/gimo_server/main.py::lifespan` into a process-agnostic helper. Both the FastAPI lifespan and the MCP-bridge boot path call it. After the helper returns, `StorageService._shared_gics` is non-None in BOTH processes and `SagpGateway.verify_proof_chain` reads the same store as `GET /ops/threads/{id}/proofs`.
- **Where**:
  - **NEW**: `tools/gimo_server/services/governance_bootstrap.py` — a single function `init_governance_subsystem(*, repo_root: Path | None = None) -> None`. Idempotent. Initializes:
    - GICS (via the same `GicsService` factory `main.py` already uses)
    - `StorageService.set_shared_gics(gics_service)`
    - `CostService.load_pricing()` (currently lazy in MCP, eager in FastAPI)
    - Any other class-singleton currently set by `main.py` startup
  - **MODIFY**: `tools/gimo_server/main.py::lifespan` — replace inline init with `init_governance_subsystem()`.
  - **MODIFY**: `tools/gimo_server/mcp_bridge/server.py::_startup_and_run` — call `init_governance_subsystem()` before `_register_dynamic()` / `_register_native()` / `_register_governance()`.
- **Why this design**: One function, two callers. Drift is structurally impossible because there is no second init path to drift from. The helper is idempotent so test fixtures and the conformance layer can call it freely.
- **Risk + mitigation**:
  - **Risk**: GICS daemon may not boot under MCP-bridge stdio environment (different working dir, no FastAPI event loop).
  - **Mitigation**: the bootstrap helper accepts `repo_root` explicitly and the GICS factory already supports this. If GICS init raises in the bridge, log loudly and continue with `_shared_gics=None` (current degraded state). Surface it via `gimo_get_governance_snapshot.gics_health.daemon_alive=false` honestly — same shape as today, but now it's a fail-loud rather than a silent miss.
- **Verification**:
  - Unit: `tests/unit/test_governance_bootstrap.py` — call twice, assert idempotent; assert `StorageService._shared_gics is not None` after call.
  - Conformance (Change 5): same proof chain query via HTTP and via MCP must return the same `proofs[]` and the same `length` for the same `thread_id`.
- **SOTA context**: This is exactly the `apps.ready()` / `@PostConstruct` pattern. Boring, well-established, correctly applied. No novelty needed.

---

#### Change 2 — `OperatorClass` field on draft/run; intent classifier matrix branches on it

- **Solves issues**: R20-001 (BLOCKER), partial R20-003 (broker stops lying about surface), structural pattern S2.
- **What**: Add a new enum `OperatorClass = Literal["human_ui", "cognitive_agent", "service_account"]` and thread it through the create-draft → run → policy-gate → intent-classifier pipeline. The intent classifier whitelists `cognitive_agent` for the same matrix cells where `human_ui` would have been forced into `HUMAN_APPROVAL_REQUIRED`. There is no "default to most restrictive" branch — the operator class is required.
- **Where**:
  - **NEW**: `tools/gimo_server/models/operator.py` — `OperatorClass` enum + tiny helper `infer_operator_class(surface: SurfaceIdentity) -> OperatorClass`:
    - `surface_type in {"mcp", "agent_sdk"}` → `cognitive_agent`
    - `surface_type in {"web", "tui", "cli_interactive"}` → `human_ui`
    - `surface_type in {"api", "service"}` → `service_account`
    - explicit unknown → raise (no silent default)
  - **MODIFY**: `tools/gimo_server/models/core.py::OpsDraft` — add `operator_class: OperatorClass` field (required, no default at the model level; the constructor sites must always pass it).
  - **MODIFY**: `tools/gimo_server/services/ops/_draft.py::DraftMixin.create_draft` — accept `operator_class` and persist it.
  - **MODIFY** all call sites that create drafts:
    - `tools/gimo_server/routers/ops/plan_router.py::create_draft` — extract `SurfaceIdentity` from request headers (`X-Gimo-Surface`) or User-Agent inference, call `infer_operator_class`.
    - `tools/gimo_server/mcp_bridge/native_tools.py::gimo_create_draft` — pass `operator_class="cognitive_agent"` (the MCP bridge knows its own class).
    - `tools/gimo_server/services/agent_broker_service.py::spawn_governed_agent` — pass `operator_class` from a NEW `BrokerTaskDescriptor.operator_class` field; default to `cognitive_agent` when called from MCP. Also remove the hardcoded `surface_type="agent_sdk"` lie — use the surface passed by the caller.
  - **MODIFY**: `tools/gimo_server/engine/contracts.py::StageInput` — add `operator_class` to the typed context (or to `context["operator_class"]` if a non-breaking dict push is preferred for now).
  - **MODIFY**: `tools/gimo_server/engine/stages/policy_gate.py::PolicyGate.execute` — read `operator_class` from input and pass it to `IntentClassificationService.evaluate(...)`.
  - **MODIFY**: `tools/gimo_server/services/intent_classification_service.py::IntentClassificationService.evaluate` — add `operator_class` parameter. Restructure the matrix so that `cognitive_agent` + non-deny verdict + non-forbidden scope → `AUTO_RUN_ELIGIBLE` directly (no `HUMAN_APPROVAL_REQUIRED` fallback). `human_ui` keeps current behavior. `service_account` is the strictest (audit-everything).
- **Why this design**:
  - Surface-class is observable upstream (the bridge knows it's MCP, the router knows the request headers); the engine pipeline only needs to know "is this a cognitive operator or a human at a UI". That distinction is the *real* axis the policy gate cares about.
  - Once `OperatorClass` is in `OpsDraft`, the same field flows through every existing pipeline stage with no new plumbing — `StageInput.context` already carries arbitrary draft-derived fields.
  - The fallback "always require human" is removed, replaced by an explicit matrix. There is no "I forgot to set operator_class" silent hole because the field is required at construction.
  - **R20-001 fix is this and only this** — no surface-aware special-casing in PolicyGate, no `if surface_type == "mcp"` branches anywhere.
- **Risk + mitigation**:
  - **Risk**: A draft created somewhere we missed (e.g., a CLI path) without `operator_class` raises at runtime.
  - **Mitigation**: The Pydantic model requires the field. `pytest -x -q` will surface every miss before merge. The conformance layer (Change 5) executes draft creation through every surface; it will catch any miss the unit suite did not.
  - **Risk**: Removing the human-approval fallback could let a malicious or mistaken `cognitive_agent` claim auto-run. 
  - **Mitigation**: `cognitive_agent` is allowed only when `policy_decision == "allow"` AND `intent_audit.scope_check != "DRAFT_REJECTED_FORBIDDEN_SCOPE"` AND the action is within `policy.allowed_tools`. Forbidden-scope and explicit deny still halt regardless of operator class. Trust dimensions still apply. Circuit breaker still applies.
- **Verification**:
  - Unit: `tests/unit/test_intent_classifier_operator_class.py` — assert that the same draft, with the same risk_score and path_scope, returns `AUTO_RUN_ELIGIBLE` for `cognitive_agent` and `HUMAN_APPROVAL_REQUIRED` for `human_ui`.
  - Unit: `tests/unit/test_policy_gate_operator_class.py` — assert PolicyGate reads `operator_class` from `StageInput.context` and propagates it.
  - Conformance (Change 5): create a draft via MCP, assert the run reaches `running` without any `gimo_resolve_handover` call. Create the same draft via web (forced `human_ui`), assert it halts at `HUMAN_APPROVAL_REQUIRED`.
- **SOTA context**: AWS IAM `Principal.Type`, Kubernetes RBAC `Subject.Kind`, OPA Rego `input.actor.type`. None of the agentic-coding tools (Cursor, Aider, Cline, OpenHands, Devin, Claude Code, CrewAI, LangGraph) have this. **This is GIMO's disruptive opening**: it is the first agent-orchestration product where the policy gate knows the difference between a human and a cognitive operator without inventing surface-specific shortcuts.

---

#### Change 3 — Honest pre-action proof persistence

- **Solves issues**: R20-005, structural pattern S4.
- **What**: `SagpGateway.evaluate_action` either (a) actually persists a real proof entry and returns its real id, or (b) does not return a `proof_id` at all. No middle ground.
- **Where**:
  - **MODIFY**: `tools/gimo_server/services/sagp_gateway.py::SagpGateway.evaluate_action`:
    - Replace `proof_id = uuid.uuid4().hex[:16]` with a call to `ExecutionProofChain.append_pre_action(thread_id, verdict_summary)` (or the equivalent existing method on `tools/gimo_server/security/execution_proof.py`).
    - If `thread_id` is empty, do not return a `proof_id` field at all (current callers tolerate absence).
    - The persisted entry uses a new proof-kind tag `"pre_action"` so it is distinguishable from execution proofs.
  - **MODIFY**: `tools/gimo_server/services/sagp_gateway.py::SagpGateway.get_snapshot` — keep `proof_chain_length` as the post-execution count, AND add a `pre_action_proofs_count` field. Both honest, both queryable, no contradiction.
  - **MODIFY**: `tools/gimo_server/security/execution_proof.py` — confirm `verification_state()` returns `"absent"` (not `"present"`) for an empty list, and that `verify_proof_chain` returns `valid: state == "present"` so the empty case is honestly `valid:false`. (This is the secondary R20-002 mis-mapping — fix it here.)
- **Why this design**:
  - The contract becomes truthful: if the field exists, it round-trips. If the data is absent, the field is absent.
  - The fix touches three lines of `evaluate_action` and clears two findings (R20-005 + R20-002 secondary).
- **Risk + mitigation**:
  - **Risk**: Persisting a proof on every `evaluate_action` call could be high-volume.
  - **Mitigation**: The proof is one row keyed by `thread_id`. Volume = governance call rate. Acceptable. If perf becomes a concern, add a `persist=False` parameter for ephemeral checks; default `True` for honesty.
- **Verification**:
  - Unit: `tests/unit/test_sagp_proof_persistence.py` — call `evaluate_action(thread_id="t")`, assert the returned `proof_id` is then resolvable via `verify_proof_chain(thread_id="t")`.
  - Unit: assert empty chain → `verify_proof_chain` returns `valid:false, state:"absent"`.
- **SOTA context**: This is just "don't lie in your API". No novelty, but absent in most agent stacks.

---

#### Change 4 — Spawn readiness + routing snapshot persistence + inventory hygiene

- **Solves issues**: R20-003, R20-006, R20-007.
- **What**: Three small fixes bundled because they share the broker/spawn surface and Change 2 already touches them.
- **Where**:
  - **(a) R20-003 — readiness gate tightening**:
    - **MODIFY**: `tools/gimo_server/services/sub_agent_manager.py::SubAgentManager._require_provider_readiness` — require BOTH `reachable == True` AND `auth_status == "ok"`. Raise `ProviderNotReadyError` (with explicit reason `unreachable | unauth | unknown`) on failure.
    - **MODIFY**: `tools/gimo_server/services/agent_broker_service.py::AgentBrokerService.spawn_governed_agent` — wrap the `await SubAgentManager.spawn_via_draft(...)` call in a try/except `ProviderNotReadyError` that returns a structured failure dict (`spawned: false, reason: PROVIDER_NOT_READY:openai:unauth, binding: ...`). No silent UUID.
  - **(b) R20-006 — routing snapshot for prompt-based runs**:
    - **NEW**: `tools/gimo_server/services/execution/routing_projection.py::persist_routing_snapshot(run_id, binding, policy)` — single helper.
    - **MODIFY**: `tools/gimo_server/services/sub_agent_manager.py::SubAgentManager.spawn_via_draft` — replace its inline routing-snapshot write with a call to this helper.
    - **MODIFY**: `tools/gimo_server/services/execution/run_worker.py::RunWorker` — after provider/model resolution for prompt-based runs, call `persist_routing_snapshot(run_id, binding, policy)`.
  - **(c) R20-007 — inventory hygiene**:
    - **MODIFY**: `tools/gimo_server/models/sub_agent.py` — add `source: Literal["auto_discovery","spawn"]` and confirm `runId: str | None` exists.
    - **MODIFY**: `tools/gimo_server/services/sub_agent_manager.py::SubAgentManager.get_sub_agents` — accept an optional `source` filter. Default returns all but in the `gimo_list_agents` MCP path, filter `auto_discovery` separately from `spawn` and tag each section in the output.
    - **MODIFY**: `tools/gimo_server/mcp_bridge/native_tools.py::gimo_list_agents` — render two sections: "Auto-discovered models" and "Spawned sub-agents", with the latter showing `runId | provider | model | status` for each.
- **Why this design**: All three issues live on the same code surface (spawn / inventory / run worker). Bundling avoids three separate PRs touching the same files.
- **Risk + mitigation**:
  - **Risk**: Tightening `_require_provider_readiness` may break tests that mock providers as `reachable=True, auth=missing` expecting acceptance.
  - **Mitigation**: Audit test mocks during implementation; update them to the new contract.
- **Verification**:
  - Unit: extend `tests/unit/test_sandbox_execution.py` with a case where `auth_status="missing"` → spawn rejected with explicit reason.
  - Unit: `tests/unit/test_routing_projection.py` — call from both `spawn_via_draft` and a mocked `RunWorker` path, assert both write the same shape.
  - Conformance (Change 5): spawn via MCP with the dead openai → assert structured failure, no UUID, no orphan in `gimo_list_agents`.
- **SOTA context**: Provider-readiness preflight is standard practice (Argo Workflows `Workflow.spec.activeDeadlineSeconds`, Kubernetes readiness probes). Bundling routing snapshot persistence into a single helper is also standard.

---

#### Change 5 — Cross-surface conformance test layer (`tests/conformance/`)

- **Solves issues**: structural pattern S3 (prevents the R19→R20 regression class for R21+); also adds the missing MCP-side `gimo_trust_circuit_breaker_get` tool (R20-008) to the MCP surface so the conformance check covers it.
- **What**: A new test directory `tests/conformance/` that boots the FastAPI app process AND the MCP-bridge process (or, where stdio is impractical, instantiates the MCP tool registration in-process against a TestClient backend), and runs the *same* governance/ops contract through every surface, asserting equality.
- **Where**:
  - **NEW**: `tests/conformance/__init__.py`
  - **NEW**: `tests/conformance/conftest.py` — fixtures:
    - `live_backend` — boots FastAPI via TestClient with `init_governance_subsystem()` called explicitly.
    - `live_mcp_tools` — registers all MCP tools against the same in-process backend (FastMCP supports this without subprocess), so the conformance layer doesn't need a real subprocess for most checks.
  - **NEW**: `tests/conformance/test_proof_chain_parity.py` — create thread, run a chat, then assert `GET /ops/threads/{id}/proofs` and `gimo_verify_proof_chain` return identical `state`, `proofs[]`, `length` for the same `thread_id`. (Catches R20-002.)
  - **NEW**: `tests/conformance/test_gics_health_parity.py` — `GET /ops/trust/dashboard` and `gimo_get_governance_snapshot.gics_health` must agree on `daemon_alive`. (Catches R20-004.)
  - **NEW**: `tests/conformance/test_operator_class_parity.py` — create draft via MCP path (operator_class=cognitive_agent), assert run reaches `running` without `gimo_resolve_handover`. Create draft via HTTP without `X-Gimo-Surface` header (default human_ui), assert it halts at `HUMAN_APPROVAL_REQUIRED`. (Catches R20-001.)
  - **NEW**: `tests/conformance/test_spawn_readiness_parity.py` — spawn via MCP with an unauth provider, assert structured failure (no UUID). (Catches R20-003.)
  - **NEW**: `tests/conformance/test_proof_persistence_parity.py` — call `gimo_evaluate_action(thread_id="t")`, then `gimo_verify_proof_chain(thread_id="t")`, assert the returned `proof_id` is in the chain. (Catches R20-005.)
  - **MODIFY**: `tools/gimo_server/mcp_bridge/governance_tools.py::register_governance_tools` — add `gimo_trust_circuit_breaker_get(key: str)` tool wrapping `TrustEngine.query_dimension(key).circuit_state`. (Closes R20-008 + lets the conformance layer assert circuit-breaker parity in a future round.)
- **Why this design**:
  - The conformance layer is the *only* test layer that would have caught all four R19 regressions before merge. A unit test cannot, by definition, see cross-process or cross-surface drift.
  - The fixtures use in-process FastMCP registration where possible, so the suite stays fast and deterministic. Subprocess-based smoke is reserved for runtime smoke (Phase 4 Step 1.5).
  - This is the structural lock that makes "R21 will look like R20" impossible.
- **Risk + mitigation**:
  - **Risk**: New test layer may be flaky because it depends on real bootstrap.
  - **Mitigation**: Use the same `init_governance_subsystem()` from Change 1; the helper is idempotent and has no IO side effects beyond the GICS daemon, which is already a tolerated optional.
  - **Risk**: Test runtime increase.
  - **Mitigation**: Conformance layer is small (5 files, ~200 lines total). Target <5s suite addition.
- **Verification**:
  - The conformance suite IS the verification for Changes 1-4.
  - Suite must run as part of `python -m pytest tests/conformance/ -q` and be added to the focused R20 verification gate.
- **SOTA context**: This is the Argo Rollouts / Envoy / Kubernetes e2e pattern, scaled down to GIMO size. **No agent-orchestration competitor has a cross-surface conformance layer.** This is GIMO's second disruptive opening: it bakes "surface parity by construction" into CI.

---

#### Change 6 — Close R20-009 (mastery analytics + skills list empty)

- **Solves issues**: R20-009 (GAP). Mandate "todo o nada": el plan no puede dejar issues de producto fuera.
- **What**: R20-009 reporta que `gimo mastery analytics` y `gimo skills list` devuelven resultados vacíos donde no deberían. Investigar la causa real (dato vs código) y arreglar el código si está roto, o sembrar la condición mínima vía un test de conformance si es estrictamente data-dependency.
- **Where (investigación dirigida, no especulación)**:
  - **READ + GREP**: `tools/gimo_server/services/mastery_service.py`, `tools/gimo_server/routers/ops/mastery_router.py`, `tools/gimo_server/services/cost_service.py` — confirmar si `mastery analytics` agrega sobre cost events / model outcomes y si el agregador filtra a 0 cuando no hay historial.
  - **READ + GREP**: `tools/gimo_server/services/skills_service.py` (o equivalente), `tools/gimo_server/routers/ops/skills_router.py` — confirmar si el registro de skills se carga eager o lazy, y si la fuente de verdad existe pero el endpoint no la lee.
  - **MODIFY (condicional)**:
    - Si el agregador de mastery está roto (e.g. filtra por un campo que ya no existe, o lee de un store vacío en el proceso MCP debido a S1) → arreglar el filtro o canalizar la lectura por el bootstrap de Cambio 1.
    - Si la lista de skills devuelve vacío porque el registro nunca se carga al boot → registrar la carga en `init_governance_subsystem()` (Cambio 1) o en el lifespan correspondiente.
    - Si ambos son estrictamente data-dependency (no hay defecto de código) → añadir un test de conformance que siembre un cost event y un skill mínimos, y assert que ambos endpoints los reflejan. Documentar honestamente que no había bug de código.
- **Why this design**: respeta el mandato "todo o nada" sin inventar arreglos. La investigación es lo primero; el fix se ajusta a lo que la investigación revele. Si resulta ser data-dep, el test de conformance es el cierre honesto.
- **Risk + mitigation**:
  - **Risk**: la investigación revela que el problema es estructural (e.g. cross-process drift sobre el store de mastery) → ya cubierto por Cambio 1.
  - **Risk**: la investigación revela que es UI/CLI rendering, no backend → arreglar el renderer.
- **Verification**:
  - Unit o conformance según el resultado de la investigación.
  - Re-run manual de `gimo mastery analytics` y `gimo skills list` tras el fix; ambos deben devolver al menos una fila no-vacía en el smoke test runtime.
- **SOTA context**: n/a — esto es higiene de producto, no diferenciador.

---

## 6 — Execution Order (dependency-aware)

```
Change 1 (governance_bootstrap)         ← foundation; no deps
        ↓
Change 3 (honest proof persistence)     ← needs shared GICS from Change 1
        ↓
Change 2 (OperatorClass)                ← needs nothing from above, but conformance asserts come last
        ↓
Change 4 (spawn/routing/inventory)      ← shares files with Change 2; merge after
        ↓
Change 6 (mastery + skills investigation)  ← may share Cambio 1 root; lands before conformance
        ↓
Change 5 (conformance test layer)       ← asserts everything above; lands last
```

Each change is verified by its own unit test before the next begins (skill rule §Phase 4.Step 1.3). Change 5 is the global gate.

---

## 7 — Unification Check

| Capability | One canonical path? | Surfaces covered |
|---|---|---|
| Governance subsystem init | YES — `init_governance_subsystem()` | FastAPI lifespan + MCP-bridge boot |
| Operator class derivation | YES — `infer_operator_class(surface)` | Every draft constructor |
| Pre-action proof persistence | YES — `ExecutionProofChain.append_pre_action` | Single store, all surfaces read/write |
| Routing snapshot write | YES — `persist_routing_snapshot()` | `spawn_via_draft` + `RunWorker` |
| Provider readiness | YES — `_require_provider_readiness` (tightened) | `spawn_via_draft` only path |
| Cross-surface contract assertion | YES — `tests/conformance/` | All surfaces compared head-to-head |

No parallel paths. No duplicated business logic. Every surface remains a thin client.

---

## 8 — 8-Criterion Compliance Matrix

| Criterion | Verdict | Justification |
|---|---|---|
| **Aligned** | ✅ YES | Every change directly executes a doctrine from `CLIENT_SURFACES.md` ("All surfaces traverse SagpGateway", "no surface-specific lie or drift", "single backend authority"). |
| **Potent** | ✅ YES | Change 1 prevents an entire bug class (cross-process drift). Change 2 reframes the policy gate around the right axis. Change 5 makes the regression pattern structurally impossible. |
| **Lightweight** | ✅ YES | 1 new module, 1 new helper, 1 new enum, 1 new test directory (5 files). Touches ~12 existing files, mostly small additions. No new dependencies. |
| **Multi-solving** | ✅ YES | Change 1 = R20-002 + R20-004 + R20-005-secondary. Change 2 = R20-001 + R20-003-surface-lie + structural-S2. Change 4 bundles three findings. Change 5 prevents an entire future class. |
| **Innovative** | ✅ YES | `OperatorClass` as a first-class policy input is unique among agentic-coding tools. Cross-surface conformance layer is unique among agent orchestration products. |
| **Disruptive** | ✅ YES | Once GIMO can prove "this MCP operator is a cognitive agent and is therefore exempt from human-UI handover", competitors (Cursor, Cline, Aider) cannot match without a multi-week rearchitecture. The conformance layer creates a quality moat: every R(N+1) round will start with surface parity already locked. |
| **Safe** | ✅ YES | Failure modes mapped per change. The OperatorClass change does NOT relax forbidden-scope or deny verdicts — it only removes the human-approval fallback for cognitive agents on already-allowed actions. Trust + circuit breaker + cost gates remain. |
| **Elegant** | ✅ YES | One concept: *the policy gate knows who is asking and the state lives in one place*. Everything else is a corollary. No special cases per surface. |

**8/8.** Plan passes.

---

## 9 — Residual Risks (honest)

1. **GICS daemon may not boot under MCP-bridge stdio environment**. Mitigation in Change 1 is to fail loud (snapshot reports `daemon_alive=false`) rather than fail silent. The bridge will still register tools and serve everything else. This is a *known* degraded state, not a hidden one.

2. **R20-003 root cause confidence is MEDIUM**. The Phase 2 trace had two competing hypotheses for why `_require_provider_readiness` did not fire. Change 4(a) addresses both by tightening the predicate AND wrapping the call site, so either hypothesis is closed. But: if the actual root cause is something a third hypothesis (e.g., the readiness probe is async-skipped under MCP-bridge stdio context), the tightening alone may not catch it. The conformance test in Change 5 will surface that during Phase 4 smoke.

3. **Subprocess vs in-process MCP testing**. Change 5 uses in-process FastMCP registration for speed. This catches contract drift but does NOT catch process-level drift (e.g., a missing `init_governance_subsystem` call in `_startup_and_run` itself). Mitigation: Phase 4 Step 1.5 runtime smoke test re-runs the failed Phase 1 probes against the *real* MCP bridge subprocess after `gimo.cmd down && up`.

4. **`OperatorClass` surface inference depends on `X-Gimo-Surface` header or User-Agent**. If a client lies (sends `X-Gimo-Surface: mcp` from a browser), the policy gate trusts the lie. Mitigation: this is a known SAGP design — surface declaration is operator-attested, and the trust system penalizes lying surfaces over time. Out of scope for R20.

5. **R20-010/R20-011 (provider env)**: not addressed by this plan. They are external environment constraints (provider auth/reachability), classified `BLOCKED_EXTERNAL` in Phase 1. Carried forward. R20-009 IS addressed by Cambio 6.

6. **The plan does NOT yet add a bootstrap CLI flag** (`gimo bootstrap doctor --check-init-parity`) that would let an operator verify both processes are in sync without running pytest. Worth considering for R21 if the conformance layer is not enough.

---

## 10 — Audit Trail

- **This document**: `docs/audits/E2E_ENGINEERING_PLAN_20260408_R20.md`
- **Phase 1 (audit log)**: `docs/audits/E2E_AUDIT_LOG_20260408_R20.md`
- **Phase 2 (RCA)**: `docs/audits/E2E_ROOT_CAUSE_ANALYSIS_20260408_R20.md`
- **Design philosophy referenced**: `docs/SYSTEM.md`, `AGENTS.md`, `docs/CLIENT_SURFACES.md`
- **Issues addressed by this plan**: R20-001..R20-009 (9 of 11) via Changes 1–6. R20-010/011 are `BLOCKED_EXTERNAL` (provider env), out of scope for code fixes.
- **Mandatory pause**: per skill rule, Phase 4 cannot begin without explicit user approval of this plan.

### Web research sources (verified April 2026)

- [The 2026 MCP Roadmap — Model Context Protocol Blog](http://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/) — governance maturation, SEPs, formal governance process
- [Pinterest Deploys Production-Scale Model Context Protocol Ecosystem for AI Agent Workflows — InfoQ, April 2026](https://www.infoq.com/news/2026/04/pinterest-mcp-ecosystem/) — JWT vs mesh identity discriminator (operator-class in production)
- [SurePath AI Advances Real-Time MCP Policy Controls — PRNewswire, 2026](https://www.prnewswire.com/news-releases/surepath-ai-advances-real-time-model-context-protocol-mcp-policy-controls-to-govern-ai-actions-302709875.html) — competitor real-time MCP policy controls
- [Protecting AI conversations at Microsoft with MCP security and governance — Microsoft Inside Track](https://www.microsoft.com/insidetrack/blog/protecting-ai-conversations-at-microsoft-with-model-context-protocol-security-and-governance/) — pause-notify-resume HITL canonical pattern
- [Apache Polaris OPA Integration](https://polaris.apache.org/in-dev/unreleased/managing-security/external-pdp/opa/) — `actor.principal + roles` + resource `type` canonical shape
- [Open Policy Agent (OPA) docs](https://www.openpolicyagent.org/docs) — Rego policy framework
- [CNCF Updates Kubernetes AI Conformance Requirements (v1.35) — Let's Data Science, 2026](https://letsdatascience.com/news/cncf-updates-kubernetes-ai-conformance-requirements-4282771d) — precedent for AI conformance gate program
- [strongdm/attractorbench (NLSpec)](https://github.com/strongdm/attractorbench) — instruction-following parity benchmark for agents
- [tadata-org/fastapi_mcp](https://github.com/tadata-org/fastapi_mcp) — FastAPI/MCP integration patterns
- [PrefectHQ/fastmcp](https://github.com/jlowin/fastmcp) — FastMCP server framework reference
- [The Battle for the AI Orchestration Layer — PYMNTS, 2026](https://www.pymnts.com/artificial-intelligence-2/2026/the-battle-for-the-ai-orchestration-layer-heats-up/) — orchestration-layer competitive context
- [Choosing Your AI Orchestration Stack for 2026 — The New Stack](https://thenewstack.io/choosing-your-ai-orchestration-stack-for-2026/) — orchestration stack landscape
