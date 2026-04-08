# R18 — Engineering Plan (v2.2, SOTA-informed, attachment-corrected)

**Date**: 2026-04-08
**Round**: R18 / Phase 3
**Inputs**:
- `E2E_AUDIT_LOG_20260408_R18.md`
- `E2E_ROOT_CAUSE_ANALYSIS_20260408_R18.md`
- Design law: `docs/SYSTEM.md`, `AGENTS.md`, `docs/CLIENT_SURFACES.md`
- SOTA research (4 parallel agents, 2026-04-08; ~25 sources surveyed)

> **v2 note**: v1 of this plan was rejected — it had not done real SOTA research and therefore could not credibly claim to surpass the state of the art. v2 is built directly on top of surveyed evidence; every change names the SOTA pattern it is informed by and the specific way GIMO surpasses it.
>
> **v2.1 note**: v2 was approvable but had loose joints. v2.1 tightens six concrete points raised in review: (1) Change 1 boot assertion is a production check, not a pytest hook; (2) Change 2's "no bypass" claim is scoped strictly to in-process — subprocess/egress hardening is named as a deploy-time boundary, not a Python guarantee; (3) Change 4 commits to SQLite as the canonical event store; (4) Change 10 separates "verifiable provenance" (load-bearing) from "stale-bytecode detection" (operational signal, not proof); (5) the audit-skill amendment is moved to a separate operational annex, not core plan; (6) verification cadence uses focused tests per change and full suite at phase boundaries, per repo principle "narrowest valid check first".
>
> **v2.2 note**: v2.1 still had four attachment-point and contract-honesty defects (P1×2, P2×2). v2.2 fixes them: (1) Change 1 invariant moves from `mcp_bridge/__init__.py` to the actual registration site `server.py::_startup_and_run` after `_register_dynamic()`/`_register_native()`; (2) Change 4 promotes append-only enforcement to the storage boundary via SQLite `BEFORE UPDATE`/`BEFORE DELETE` triggers raising `RAISE(ABORT, ...)`, so the structural claim is now actually structural; (3) absolute language about "no bypass" / "stale impossible" / "divergence impossible" in §0/§1/§6 is harmonized with the scoped guarantees from Changes 2/4/10; (4) Change 10's launcher hardening retargets from `gimo.py` to the official `gimo.cmd` + `scripts/dev/launcher.py` path per repo contract.

---

## 0. Diagnosis

R18's 11 symptoms collapse into **four systemic patterns**: (A) runtime verification gate failure, (B) bridge↔service drift, (C) parallel paths around the governance core, (D) governance-as-opt-in. The plan eradicates the patterns at their actual surface, with scope-honest guarantees: schema drift caught at the live registration site (boot fails), in-process provider bypass closed by a 3-layer guard (subprocess/network bypass remains a deploy-boundary concern), bytecode staleness gated by `git_sha` equality at the audit boundary (with sys.modules walk as operational signal, not proof), and trust divergence prevented at the SQLite storage boundary by `BEFORE UPDATE`/`BEFORE DELETE` triggers. Every guarantee is named with its scope; absolute claims have been removed.

---

## 1. SOTA landscape (compressed, sourced)

| Concern | Closest SOTA | What they do | Where they still fail | GIMO's structural surpass |
|---|---|---|---|---|
| Tool schema drift | **FastMCP** `func_metadata` ([gofastmcp.com/servers/tools](https://gofastmcp.com/servers/tools)); **OpenAI Agents SDK** `pydantic_function_tool`; **PydanticAI** signature-derived | Schema generated from a Pydantic model OR signature, validated at registration / first call | Validation happens at *call* or *registration*, never at module *import*. Drift can ship to prod. FastMCP issue [#1784](https://github.com/jlowin/fastmcp/issues/1784): single-Pydantic-arg nesting bug. | **Import-time `assert published_schema == Model.model_json_schema()`** raising `ToolSchemaDriftError`. Process refuses to boot on drift. None of the surveyed frameworks does this. |
| Provider call observability / governance | **OpenHands EventStream** ([arXiv 2511.03690](https://arxiv.org/html/2511.03690v1)); **LangGraph + LangSmith** checkpointer; **OpenLLMetry/Langfuse** import-time monkey-patch; **Helicone/LiteLLM/Portkey** HTTP proxy | Single observability path via wrapper, callback, monkey-patch, or proxy | **Every** SOTA option has a trivial bypass: raw `httpx.post`, hardcoded `base_url`, untraced node, second SDK version. OWASP Agentic 2026 ASI02 explicitly says "no single control suffices — defense in depth required." | **Hybrid 3-layer chokepoint**: explicit `provider_invoke()` + import-time monkey-patch of `httpx`/`openai`/`anthropic` that raises outside a `provider_invoke` contextvar + egress denylist for provider domains. Bypass requires defeating all three. |
| Stale bytecode in long-running server | **Argo Rollouts AnalysisTemplate** ([docs](https://argo-rollouts.readthedocs.io/en/stable/features/analysis/)) with SHA-match curl gate; **PEP 3147** CHECKED_HASH invalidation | Post-deploy job verifies `/health/info.git_sha == $DEPLOY_SHA`; abort + auto-rollback on mismatch | Most Python deployments still default to TIMESTAMP invalidation ([bpo-31772](https://bugs.python.org/issue31772): same-second mtime → silent stale `.pyc`). FastAPI templates rarely expose build provenance. | `/ops/health/info` exposes `git_sha`, `build_epoch`, `process_started_at`, `pyc_invalidation_mode`, **per-module `bytecode_drift_seconds`** computed live by walking `sys.modules`. `gimo doctor` and the audit skill *both* gate on this. Boot uses `compileall --invalidation-mode checked-hash`. |
| Multi-source trust / reputation | **CrewAI process_metrics**; **AutoGen group chat reputation**; classical MAS **FIRE model** ([Springer](https://link.springer.com/article/10.1007/s10458-005-6825-4)); **event sourcing** ([Confluent](https://www.confluent.io/blog/messaging-single-source-truth/)) | Per-run metrics or centralized registry | CrewAI/AutoGen have no cross-run reputation → exactly the trifurcation GIMO suffers. Centralized registries still allow divergent caches. | **Append-only event log** (`TrustEngine` becomes the only writer). SagpGateway seeds and CLI snapshot become **read-only projections** materialized on demand. Divergence impossible by construction. |
| HITL pause/resume | **LangGraph `interrupt()` + `Command(resume=...)`** ([docs](https://docs.langchain.com/oss/python/langgraph/interrupts)); **CrewAI Enterprise webhook resume**; **Anthropic computer-use inbox** | Persist to checkpointer under `thread_id`, expose external resume endpoint | LangGraph requires checkpointer infra; CrewAI requires re-passing webhook URLs each resume; both keep state in memory only for CLI mode. | Adopt LangGraph's pattern *over the unified draft store from Change 3* — `awaiting_user` drafts persist in `OpsService`, `gimo_resolve_handover(draft_id, resolution)` injects the resume. One store, one resume API, MCP-native. |

GIMO's distinctive position after this plan, scope-honest: **schema drift fails the live boot (in-process); provider-call bypass blocked at three in-process layers (subprocess/egress is deploy-boundary); bytecode staleness blocked at the `git_sha` audit gate (operational signal additionally surfaces drift); trust divergence blocked at the SQLite storage boundary by triggers**. Every competitor surveyed addresses at most one of these with comparable rigor; none addresses all four.

---

## 2. Design principles

1. **One door per concern.** Drafts, provider calls, trust events, dashboard rendering: each has exactly one entry point. Parallel paths are deleted, not deprecated.
2. **Schema-from-model, drift-checked at import.** A tool's published interface is *derived* from its Pydantic model AND asserted equal at module load.
3. **Defense in depth per OWASP ASI02/ASI03.** No single control protects the chokepoint — explicit invoke + import-time guard + egress denylist together.
4. **Event sourcing for any "single source of truth" claim.** If multiple surfaces read the same fact, the fact is an append-only log + projections.
5. **Build provenance is observable.** `git_sha`, `build_epoch`, `bytecode_drift_seconds` in `/health`. Stale = visible = audit-failing.
6. **Minimal diff, maximum collapse.** Every change must close ≥2 issues or eradicate a pattern.

---

## 3. The plan (changes)

### Change 1 — `register_pydantic_tool()` + import-time drift assertion (eradicates Pattern B)

- **Solves**: #R18-2b (Cluster D regression class — `verify_proof_chain`, `generate_team_config`, future regressions). Closes the entire drift class.
- **SOTA basis**: FastMCP `func_metadata`, OpenAI `pydantic_function_tool()`, PydanticAI signature derivation.
- **Where SOTA fails**: all validate at registration or first call; none asserts at module import. FastMCP #1784 also nests Pydantic single-args.
- **What**:
  1. NEW `tools/gimo_server/mcp_bridge/_register.py` exposing `register_pydantic_tool(mcp, *, input_model, name, description, handler)`. Internally:
     - Reads `input_model.model_fields` (Pydantic v2).
     - Builds a wrapper function whose `inspect.Signature` mirrors the model's fields (correct names, types, defaults) — flattens the FastMCP #1784 nesting bug by construction.
     - Registers it with `@mcp.tool()` so FastMCP introspection sees the canonical schema.
     - The wrapper re-validates with `input_model(**kwargs)` before calling `handler(params)` (PydanticAI-style call-time second line).
  2. **Production boot assertion at the actual registration site (not a pytest hook, not the empty `__init__.py`)**: in `tools/gimo_server/mcp_bridge/server.py::_startup_and_run`, immediately after the existing `_register_dynamic(mcp, ...)` and `_register_native(mcp, ...)` calls (currently around `server.py:240`), add a single call to `_register.assert_no_drift(mcp)`. The helper iterates the live FastMCP tool registry and asserts, for each tool registered via `register_pydantic_tool`, that its published `inputSchema` (canonicalized) equals `Model.model_json_schema()`. On mismatch raises `ToolSchemaDriftError` before the bridge accepts any client — server refuses to come up. To cover *every* in-process bridge instance (not just `_startup_and_run`), the assertion is also wrapped in a small canonical builder `mcp_bridge/_register.py::build_bridge(mcp_factory) → mcp` that any future call site must use; tests cover the builder, the registration site uses it. This is a runtime invariant on the real registration path, not on package import.
  3. NEW `tests/unit/test_register_pydantic_tool.py` — focused unit test for the helper itself (signature construction, validation, drift detection on a synthetic drifted tool). Belongs in pytest, not in the boot path.
  4. MIGRATE `gimo_verify_proof_chain`, `gimo_generate_team_config`, `gimo_estimate_cost`, `gimo_get_governance_snapshot` and any other tool with a `*Input` model to use the helper.
- **Risk**: dynamic signature construction is unusual. **Mitigation**: ~80 LOC, focused unit test, fallback path uses explicit `Annotated[...]` per field.
- **Verification**: integration test enumerates every bridge tool; bridge import fails if any tool drifts; smoke calls `gimo_verify_proof_chain()` and `gimo_verify_proof_chain(thread_id="...")`.
- **Surpasses SOTA**: FastMCP/LangChain/Agents-SDK/PydanticAI all let drift ship to prod; GIMO breaks the build.

---

### Change 2 — `provider_invoke` 3-layer chokepoint (eradicates Pattern C, half of D)

- **Solves**: #R18-5 (chat path bare), #R18-9 (rate-limit per-role for `mcp` invisible), structurally prevents all future bare provider calls. Foundation for #R18-10 dashboard parity.
- **SOTA basis**: OpenHands EventStream (explicit invoke), Langfuse/OpenLLMetry (monkey-patch), Helicone/LiteLLM (proxy).
- **Where SOTA fails**: every option has a trivial bypass — raw `httpx.post`, untraced node, hardcoded base_url, second SDK version. OWASP ASI02 says "single control insufficient."
- **Scope of the "no bypass" claim**: this change provides a **strong in-process guarantee** for the `gimo_server` Python process. CLI subprocess workers, external adapters that shell out, and anything outside the process boundary are NOT covered by Layers 2-3 alone — they must be covered by deploy-time egress firewall rules. The plan delivers the in-process guarantee and *names* the deploy boundary; it does not pretend Python can solve subprocess containment.
- **What** — three layers, in-process scope:
  1. **Layer 1 (load-bearing): explicit invoke.** NEW `services/provider_invoke.py` exporting one async function `invoke(*, surface, model, prompt, tool_args, thread_id, policy) → ProviderResult`. Internally:
     - `SagpGateway.evaluate_action()` — verdict required.
     - Pre-call cost estimate.
     - Dispatch via `ProviderService.get_adapter()` inside a `contextvars.ContextVar("inside_provider_invoke", default=False)` set to `True`.
     - Post-call: real cost via `CostService`, model outcome via `GicsService.record_model_outcome`, trust event via `TrustEngine.append` (see Change 4), proof entry via `ProofChainService`.
     - Emits one typed event into a unified `EventStream` (OpenHands-style) with `trace_id`, `agent_id`, cost, trust delta, risk band.
  2. **Layer 2 (in-process hardening): startup guard.** At lifespan startup, monkey-patch `httpx.AsyncClient.post`, `httpx.Client.post`, and the `openai` / `anthropic` SDK clients to **raise `ProviderBypassError`** if called while `inside_provider_invoke` contextvar is `False` AND the target host matches a provider domain. Closes the in-process raw-HTTP bypass. **Caveat**: a malicious or careless caller using `socket` directly still escapes Layer 2 — Layer 3 catches that case in-process; subprocesses need deploy boundary.
  3. **Layer 3 (in-process socket guard): egress denylist.** NEW `services/egress_guard.py` builds the provider-domain set from the live catalog and installs a `socket.getaddrinfo` wrapper that refuses resolution of those domains from threads where `inside_provider_invoke` is `False`. Covers raw `socket`, raw `urllib`, custom HTTP clients — anything in-process. **Out of scope**: child processes spawned by adapters; for those, document the required iptables/nftables/Cloud egress rule in `docs/SECURITY.md` as a deploy-time boundary.
- **Where**:
  - NEW: `services/provider_invoke.py` (~150 LOC).
  - NEW: `services/egress_guard.py` (~40 LOC, in-process; prod hardening is config).
  - MODIFY: `services/agentic_loop_service.py::AgenticLoopService.chat` — replace direct adapter call with `provider_invoke.invoke(...)`. Delete duplicated cost/trust bookkeeping.
  - MODIFY: `engine/pipeline.py::LlmExecuteStage` — same migration; pipeline-specific telemetry travels in `ProviderResult.extra_telemetry`.
  - MODIFY: `services/sub_agent_manager.py::SubAgentManager.spawn` — worker calls go through the chokepoint.
  - MODIFY: `tools/gimo_server/main.py` — install Layer 2 monkey-patches at lifespan startup.
- **Risk**: monkey-patching `httpx` may surprise unrelated code paths (e.g., webhook callers). **Mitigation**: contextvar default is permissive for non-provider domains; Layer 3 only denies provider domains. Pipeline tests must still pass; add `test_provider_invoke_three_layer_defense.py` asserting (a) explicit invoke works, (b) raw `httpx.post` to a provider domain raises outside the contextvar, (c) the same call inside `invoke()` succeeds.
- **Verification**: pipeline + chat + spawn each emit identical event shapes; bypass attempt raises.
- **Surpasses SOTA (scoped honestly)**: in-process, every surveyed framework has at least one bypass GIMO closes (raw httpx → Layer 2; raw socket → Layer 3). At the subprocess boundary GIMO matches SOTA — the deploy egress firewall is the only honest answer, and the plan names it as such instead of claiming Python solved it.

---

### Change 3 — Spawn unification via OpsService (closes the rest of Pattern D)

- **Solves**: #R18-4 (spawn black hole). Foundation for #R18-8 (HITL drafts share the same store).
- **SOTA basis**: Aider `Coder.run_subprocess` (subagents are first-class records in parent history); LangGraph subgraphs share the same checkpointer.
- **What**: Delete `SubAgentManager`'s private draft store. `spawn()` becomes a thin wrapper:
  1. Build the worker spec.
  2. Call `OpsService.create_draft(...)`.
  3. Auto-approve under the spawning policy.
  4. `RunWorker` picks it up via the standard pipeline.
- **Where**:
  - MODIFY: `services/sub_agent_manager.py` — remove private storage; thin wrapper over OpsService.
  - MODIFY: `mcp_bridge/native_tools.py::gimo_spawn_subagent` — return the OpsService draft id.
  - DELETE: any private "subagent_drafts" directory or in-memory dict.
  - NEW TEST: `tests/integration/test_spawn_uses_ops_drafts.py`.
- **Risk**: existing tests may assume the private store; grep + migrate.
- **Surpasses SOTA**: Aider's subagents are records but live in a separate "session log"; LangGraph subgraphs need the parent to manually wire the checkpointer. GIMO's spawned drafts are *indistinguishable* from any other draft — same store, same lifecycle, same governance.

---

### Change 4 — TrustEngine as event-sourced single source of truth (fixes #R18-6)

- **Solves**: #R18-6 (trust trifurcation). Removes the dishonest "fake seeded scores" from SagpGateway.
- **SOTA basis**: classical MAS FIRE model + event sourcing (Confluent's "messaging is the SoT" pattern).
- **Where SOTA fails**: CrewAI / AutoGen have no cross-run reputation; centralized registries still allow divergent caches.
- **What**:
  1. `TrustEngine` becomes the **only writer** to a **SQLite append-only table** at `.orch_data/trust_events.db`. Schema:
     ```sql
     CREATE TABLE trust_events (
       event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
       ts            REAL    NOT NULL,
       dimension_key TEXT    NOT NULL,
       delta         REAL    NOT NULL,
       reason        TEXT,
       source        TEXT,
       proof_id      TEXT
     );
     CREATE INDEX ix_dim_ts ON trust_events (dimension_key, ts);

     -- Storage-boundary append-only enforcement (the actual structural guarantee):
     CREATE TRIGGER trust_events_no_update
       BEFORE UPDATE ON trust_events
       BEGIN SELECT RAISE(ABORT, 'trust_events is append-only'); END;
     CREATE TRIGGER trust_events_no_delete
       BEFORE DELETE ON trust_events
       BEGIN SELECT RAISE(ABORT, 'trust_events is append-only'); END;
     ```
     SQLite chosen over JSONL because: (a) GIMO already uses SQLite for cost/eval storage per `SYSTEM.md` Appendix B — no new dep, no new operational shape; (b) indexed projections are O(log n) instead of O(n) full-file scans; (c) **the append-only invariant lives at the storage boundary, not at the application boundary** — any code path, helper, migration, or alternate connection that issues `UPDATE`/`DELETE` will be rejected by SQLite itself with `RAISE(ABORT)`. This is the structural guarantee. A unit test verifies the triggers exist and reject non-INSERT statements; that test guards the *trigger creation*, not the absence of bad SQL elsewhere.
  2. `TrustEngine.project(view: str)` materializes read-only projections on demand: `view="raw_score"`, `view="gateway_seeds"`, `view="cli_snapshot"`, `view="dashboard"`. All projections are pure functions of the log.
  3. `SagpGateway._get_trust_score(dim)` and `_seed_defaults` are **deleted**. The gateway calls `TrustEngine.project("gateway_seeds")[dim]`.
  4. CLI `trust status` reads via `/ops/trust/dashboard`, which reads via `TrustEngine.project("dashboard")`. CLI's private path is deleted.
- **Where**:
  - MODIFY: `services/trust_engine.py` — add append-only log + `project()` method.
  - MODIFY: `services/sagp_gateway.py` — delete seeds + private store.
  - MODIFY: CLI `commands/trust.py`.
  - NEW TEST: `tests/integration/test_trust_event_sourced.py` — append an event, assert all 3 projections (gateway, dashboard, CLI) reflect it identically.
- **Risk**: removing the seeds means a fresh deploy shows empty trust. **Mitigation**: that is the honest answer for a fresh deploy. The skill audit must accept empty as valid initial state.
- **Surpasses SOTA**: divergence is rejected at the storage boundary by SQLite triggers — not by application discipline. Single writer + derived views + DB-level append-only triggers together. FIRE model's centralized registry still has caches; event sourcing has no caches because views are computed from the log; the triggers ensure the log itself cannot be retroactively edited.

---

### Change 5 — GICS MCP path via the Change-1 helper (fixes #R18-3b)

- **Solves**: #R18-3b (GICS reachable via HTTP, not MCP).
- **SOTA basis**: parity invariant from `AGENTS.md` §"Multi-surface parity".
- **What**: Add `gimo_gics_record_outcome`, `gimo_gics_get_reliability`, `gimo_gics_anomaly_report` using `register_pydantic_tool` from Change 1. Thin wrappers over `GicsService`.
- **Where**: MODIFY `mcp_bridge/governance_tools.py` (or new `gics_tools.py`); add `*Input` models to `native_inputs.py`.
- **Risk**: minimal — additive, inherits Change 1's drift guard.

---

### Change 6 — Codex tool-call parser fix (#R18-7)

- **Solves**: #R18-7 (Codex CLI fails on markdown-fenced JSON).
- **SOTA basis**: Cline / Continue.dev strip ```json fences canonically.
- **What**: Update `adapters/codex.py::parse_tool_calls` to strip ```json … ``` fences before parsing. Add fixture-based test with three real Codex transcripts (fenced, unfenced, nested).
- **Where**:
  - MODIFY: `adapters/codex.py::parse_tool_calls`.
  - NEW: `tests/fixtures/codex_transcripts/*.txt`.
  - NEW TEST: `tests/unit/test_codex_parser.py`.

---

### Change 7 — HITL `gimo_resolve_handover` via LangGraph-style resume (#R18-8)

- **Solves**: #R18-8 (HITL drafts left dangling).
- **SOTA basis**: LangGraph `interrupt()` + `Command(resume=...)` over a checkpointer.
- **Where SOTA fails**: LangGraph requires its own checkpointer infra; CrewAI Enterprise needs webhook URLs re-passed each resume.
- **What**:
  1. When `ToolExecutor` runs `ask_user`, it persists an `awaiting_user` draft (via `OpsService` — same store as Change 3) carrying the agentic loop's resume token.
  2. `gimo_resolve_handover(draft_id, resolution)` (registered via Change 1 helper) loads the draft, writes `resolution` into it, transitions `awaiting_user → approved`, and signals `RunWorker` to resume the parent run from the persisted resume token.
  3. The agentic loop reads the resolution as if it were a `Command(resume=resolution)` injection and continues the turn.
- **Where**:
  - MODIFY: `engine/tools/executor.py::_handle_ask_user`.
  - MODIFY: `services/agentic_loop_service.py` — accept resume tokens.
  - MODIFY: `mcp_bridge/governance_tools.py::gimo_resolve_handover`.
  - NEW TEST: `tests/integration/test_hitl_resume.py` — full pause→external resolve→resume cycle.
- **Surpasses SOTA**: one store (Change 3), one resume API, MCP-native. LangGraph needs a separate checkpointer; GIMO reuses the draft store it already has.

---

### Change 8 — Dashboard renders from `GovernanceSnapshot.to_dict()` (fixes #R18-10)

- **Solves**: #R18-10 (HTML dashboard fields drift from JSON snapshot fields).
- **What**: HTML dashboard handler currently composes its own dict for the template. Replace with: render a single Jinja template that consumes the exact `GovernanceSnapshot.to_dict()` payload. One source, two encodings (HTML / JSON).
- **Where**:
  - MODIFY: `mcp_bridge/governance_tools.py::gimo_dashboard` and/or `routers/ops/dashboard_router.py`.
  - MODIFY: the Jinja template.
  - NEW TEST: `tests/integration/test_dashboard_snapshot_parity.py` — both endpoints expose the same field set.

---

### Change 9 — Rate-limit per-role observability includes `mcp` (#R18-9)

- **Solves**: #R18-9 (per-role buckets for `mcp` not exposed).
- **What**: `GET /ops/observability/rate-limits` enumerates role buckets dynamically from `RateLimitStore.known_roles()` instead of a hardcoded list.
- **Where**:
  - MODIFY: `security/rate_limit.py` (add `known_roles()`).
  - MODIFY: `routers/ops/observability_router.py::rate_limits`.
  - NEW TEST: `tests/unit/test_rate_limit_observability.py`.

---

### Change 10 — Build provenance + bytecode freshness gate (eradicates Pattern A)

- **Solves**: #R18-1 / #R18-2a / #R18-3a (R17 staleness class). Prevents the same false-DONE failure mode in R19+.
- **SOTA basis**: Argo Rollouts AnalysisTemplate SHA-match curl gate; PEP 3147 CHECKED_HASH; FastAPI best-practices `/health/info` build provenance pattern.
- **Where SOTA fails**: most Python deploys default to TIMESTAMP invalidation (bpo-31772 same-second mtime trap); FastAPI templates rarely walk `sys.modules` to expose per-module drift.
- **What** — split into LOAD-BEARING provenance and OPERATIONAL detection:

  **LOAD-BEARING (the actual gate)** — these are the contracts the rest of the system trusts:
  1. **Boot under hash invalidation**. The official launcher contract per `AGENTS.md` §Repo Map is `gimo.cmd`, which delegates to `scripts/dev/launcher.py`. The pre-compile step lands in **both** of those — `gimo.cmd` runs `python -m compileall --invalidation-mode checked-hash tools/gimo_server` before invoking the launcher, and `scripts/dev/launcher.py` re-runs it as a safety net before spawning uvicorn. CI workflow (`.github/workflows/ci.yml`) gets the same step. Eliminates the bpo-31772 same-second-mtime stale class on the actual `gimo up` path.
  2. **`/ops/health/info.git_sha`** read once at startup from `GIMO_BUILD_SHA` env (set by launcher to `git rev-parse HEAD`), exposed verbatim. Plus `build_epoch`, `process_started_at`, `python_version`, `pyc_invalidation_mode`. This is the auditable provenance.
  3. **`gimo doctor` gate (load-bearing check)**: `git rev-parse HEAD` == `/ops/health/info.git_sha`. Mismatch = "edited code, forgot to restart" → fail. This is the only check that can be claimed as proof.

  **OPERATIONAL SIGNAL (informational, not proof)** — useful detection but explicitly not a guarantee:
  4. **`/ops/health/info.module_freshness`** block computed live by walking `sys.modules` for modules under `tools/gimo_server/` and comparing `getattr(module, "__file__")` mtime vs source mtime → worst-case `bytecode_drift_seconds`. **Caveat documented in the field**: this catches the common case (file edited after import) but is not a proof of freshness — `__file__` mtime can lie under layered filesystems, container overlays, and editor atomic-write patterns. It is a *signal*, not a verdict. `gimo doctor` surfaces it as WARN, never as the gate itself.
  5. **`PYTHONDONTWRITEBYTECODE` / invalidation-mode WARN**: surfaced in doctor output but does not block.

> The audit-skill amendment (pre-edit SHA precheck, post-edit forced reload) is NOT part of this change. It is the operator's tooling, not the product's contract. Moved to Annex A below.
- **Where**:
  - MODIFY: `tools/gimo_server/main.py` (record boot epoch, expose `/ops/health/info`).
  - NEW: `services/build_provenance_service.py` (~70 LOC — sys.modules walk + git_sha resolution).
  - MODIFY: `gimo.cmd` (official launcher per AGENTS.md §Repo Map) — pre-compile step before delegating.
  - MODIFY: `scripts/dev/launcher.py` (the Python half of the launcher) — pre-compile step before uvicorn spawn.
  - MODIFY: `.github/workflows/ci.yml` — same compileall step in CI.
  - MODIFY: `cli/commands/doctor.py`.
  - NEW TEST: `tests/unit/test_build_provenance.py` — gates on `git_sha` match (load-bearing); `module_freshness` fields present (signal only, no equality assertion).
- **Risk**: false positives if a deploy process touches files post-import. **Mitigation**: the load-bearing gate compares `git_sha`, not mtimes; mtime block is signal-only.
- **Surpasses SOTA (scoped honestly)**: load-bearing parts (checked-hash compileall + `git_sha` gate) match Argo Rollouts' rigor and apply at the *editor boundary* via Annex A, which Argo does not address. The `sys.modules` walk is a useful operational signal not standard in surveyed FastAPI templates, but is not claimed as proof.

---

## 4. Execution order

```
P0 ─── Change 1  (registration helper + import-time drift assertion)
   └── Change 10 (build provenance + bytecode gate)

P1 ─── Change 2  (provider_invoke 3-layer chokepoint)
   └── Change 3  (spawn unification via OpsService)
   └── Change 4  (trust event sourcing)

P2 ─── Change 5  (GICS MCP)             ── needs Change 1
   └── Change 7  (HITL resume)          ── needs Change 3
   └── Change 8  (dashboard from snapshot)
   └── Change 9  (rate-limit roles)
   └── Change 6  (Codex parser)
```

**Verification cadence** (per AGENTS.md "narrowest valid check first"):
- After each change: run the **focused tests touching that change only** (`pytest tests/unit/test_register_pydantic_tool.py`, etc.).
- At each phase boundary (end of P0, end of P1, end of P2): run the **full suite** `python -m pytest -x -q`.
- After P0+P1: restart server, hit `/ops/health/info`, refuse to proceed if `git_sha != HEAD`.

---

## 5. Unification check

| Concern | Before | After | Mechanism |
|---|---|---|---|
| Tool schema authority | Decorator signature; Pydantic inside function body invisible | Pydantic model only | Schema-from-model + import-time `==` assertion |
| Provider call | 3 paths (chat / pipeline / spawn) + bypass via raw httpx | 1 path: `provider_invoke.invoke` | Explicit invoke + monkey-patch guard + egress denylist |
| Draft store | OpsService + private SubAgentManager store | OpsService only | Wrapper deletion |
| Trust score | Seeds + TrustEngine + CLI snapshot (3 stores) | Append-only log + projections | Event sourcing + SQLite `BEFORE UPDATE/DELETE` triggers |
| Dashboard fields | Handler dict + template + JSON snapshot | `GovernanceSnapshot.to_dict()` only | Single template input |
| Runtime freshness | "I restarted, trust me" | `bytecode_drift_seconds`, gated 3 ways | Hash invalidation + sys.modules walk + audit gate |
| HITL resume | Dangling `awaiting_user` drafts, no resume API | OpsService draft + `gimo_resolve_handover` | Reuse draft store, LangGraph-style resume token |

Every row collapses N→1.

---

## 6. 8-criterion compliance matrix (with SOTA evidence)

| Criterion | Yes? | Why + SOTA reference |
|---|---|---|
| Aligned (SYSTEM/AGENTS/SURFACES) | YES | Every change strengthens "one backend truth, multiple thin clients" (AGENTS.md §Multi-surface parity, §Architectural Rules). |
| Potent | YES | Eradicates 4 systemic patterns, not 11 symptoms. Each pattern is closed by a single concept (helper, chokepoint, event log, freshness probe). |
| Lightweight | YES | NEW: helper ~80, chokepoint ~150, egress ~40, build provenance ~70. DELETED: SubAgentManager private store, SagpGateway seeds, CLI trust snapshot, dashboard handler dict. Net LOC likely negative. |
| Multi-solving | YES | Change 1 → #R18-2b + entire Cluster D regression class. Change 2 → #R18-5/9 + structural prevention of all future bare calls. Change 3 → #R18-4 + enables #R18-7. Change 4 → #R18-6 + dashboard parity foundation. Change 10 → #R18-1/2a/3a + R19+ prevention. |
| Innovative | YES | (1) **Import-time schema-drift assertion** — none of FastMCP, LangChain, Agents-SDK, PydanticAI does this. (2) **3-layer chokepoint with monkey-patch guard + egress denylist** — every surveyed observability tool has a bypass; GIMO requires defeating all three. (3) **`bytecode_drift_seconds` via sys.modules walk in `/health`** — not standard in any surveyed FastAPI template. (4) **Event-sourced TrustEngine with on-demand projections** — CrewAI/AutoGen have neither cross-run reputation nor projection model. |
| Disruptive | YES | A governance authority where: schema drift fails live boot (Change 1, in-process); provider bypass is blocked at three in-process layers and the deploy boundary is named explicitly (Change 2); bytecode staleness is gated by `git_sha` equality at the audit boundary (Change 10); trust divergence is rejected at the SQLite storage boundary by triggers (Change 4). The combination is a concrete moat; most agent frameworks treat governance as decoration. OWASP ASI02/ASI03's "defense in depth" requirement is *structurally* satisfied within process scope, with the deploy boundary explicitly named. |
| Safe | YES | Helper isolated; chokepoint preserves telemetry shapes via `extra_telemetry`; monkey-patch is contextvar-scoped and reversible; event log is append-only (no destructive writes); freshness gate fails loud. No new attack surface. |
| Elegant | YES | One concept per change. Plan spine = "collapse parallel paths and observe everything." |

All YES.

---

## 7. Residual risks

1. **#R18-11 (skills naming/scope)** — deferred; architectural decision pending.
2. **OpenAI provider for Probe B** — operational, not code. The plan does not add an OpenAI key.
3. **R17 published-schema clients** — Change 1 will re-register R17 tools; if any external client depends on a wrong-but-published schema, it will see a corrected (breaking) schema. **Mitigation**: enumerate in implementation report; coordinate before merging.
4. **Layer 3 egress denylist in subprocess agents** — in-process socket hook covers the gimo_server process; subprocess workers (CLI adapters) need OS-level firewall rules in prod. Documented as deploy-time config; in-process tests cover the in-process path.
5. **Hash invalidation slowdown** — CHECKED_HASH adds ~5% to import time. Acceptable for a server that boots once per session.

---

## 8. Phase 4 mandate

- Land in §4 order.
- Verification cadence per §4 (focused tests per change, full suite at phase boundaries).
- After P0+P1: restart server, hit `/ops/health/info`, refuse if `git_sha != HEAD`.
- Re-run top 5 failing R18 probes (Annex A operator gate amendment applies if installed).
- Multi-agent code review per skill §Phase 4 Step 2.
- Implementation report at `docs/audits/E2E_IMPLEMENTATION_REPORT_20260408_R18.md`.

---

## Annex A — Operator-side audit-skill amendment (NOT part of core repo plan)

This annex describes a recommended modification to the local auditor's tooling at `~/.claude/skills/e2e/skill.md`. It is **operator tooling, not product contract** — it lives outside the repo and ships with the audit harness, not the product. The product's load-bearing freshness contract is Change 10's `git_sha` gate; this annex is the operator's *workflow* for not tripping that gate.

Recommended skill-file additions (Phase 4 §1.5 — Runtime Smoke Test):
1. **Pre-edit precheck**: before any `Edit`/`Write` against `tools/gimo_server/`, call `/ops/health/info` and assert `git_sha == git rev-parse HEAD`. If not, restart first.
2. **Post-edit hook**: after a batch of edits, force `gimo_reload_worker` (existing MCP tool) and re-verify `git_sha`.
3. **Smoke gate**: refuse to mark any issue resolved if `git_sha != HEAD` at smoke time.

Why annex and not core: amending operator tooling from inside the product plan blurs the line between "what GIMO is" and "how this auditor works". Future auditors may use a different harness; the contract they consume is `/ops/health/info`, not the skill file.

---

## 9. STATUS

`PLAN_READY_AWAITING_APPROVAL` (v2.2)
