# E2E Root-Cause Analysis — R17

**Date**: 2026-04-07
**Round**: 17
**Input document**: `docs/audits/E2E_AUDIT_LOG_20260407_R17.md` (13 issues)
**Method**: 5 parallel Explore subagents, one per cluster (A/B/C/D/E), each tracing issues through the codebase with symbol-anchored references.
**Working tree state**: commit `dc2395c` (R16 fixes); no modifications.

---

## Issue Map

| ID | Sev | Cluster | Root cause location (file::symbol) | Confidence |
|---|---|---|---|---|
| #1 | BLOCKER | A — dead data plane | `run_router.py::approve_draft` (status-before-dispatch) + `run_router.py::_spawn_run` (fire-and-forget) + `run_worker.py::_tick` (pending-only) | HIGH |
| #5 | CRITICAL | A | same as #1 (no task → no heartbeat, no stage) | HIGH |
| #6 | CRITICAL | A | same as #1 (no task → no LLM call → no usage) | HIGH |
| #12 | GAP | A (downstream) | `observability_service.py::UISpanProcessor.on_end` never invoked because `engine._execute_step` never runs | HIGH |
| #2 | BLOCKER | B — hollow agentic loop | `agentic_loop_service.py::_run_loop` silent-content-gate at `if content:` + provider returning empty | MEDIUM-HIGH |
| #4 | BLOCKER | B | same silent gate, observable as empty orchestrator turn | MEDIUM-HIGH |
| #3 | BLOCKER | C — GICS start | `gics_service.py::GicsService.start_daemon` silent early-return when Node/CLI missing | HIGH |
| #7 | CRITICAL | D — MCP schema drift | `mcp_bridge/server.py::_register_dynamic` + `_register_native` (two uncoordinated schema sources) | HIGH |
| #9 | CRITICAL | D | `mcp_bridge` (OpenAPIProvider query-param coercion stringifies ints for `gimo_estimate_cost`) | MEDIUM |
| #10 | GAP | D | `native_tools.py::gimo_generate_team_config` narrowed from objective→plan_id in commit `f70c6e1` | HIGH |
| #11 | GAP | D | `governance_tools.py::gimo_verify_proof_chain` locked to required `thread_id`; evaluate_action proof orphaned | HIGH |
| #8 | CRITICAL | E — cross-surface drift | `trust_router.py::trust_dashboard` returns `{"items":...}` but `gimo_cli/render.py::TRUST_STATUS` uses `unwrap="entries"` | HIGH (99%) |
| #13 | FRICTION | E | `gimo_cli/commands/auth.py::doctor` uses conditional `/ops/provider`→`/ops/connectors/{id}/health` chain; `providers.py::providers_test` uses direct single-step call | HIGH |

---

## Cluster A — Dead Data Plane (#1, #5, #6, #12)

### Entry point
`tools/gimo_server/routers/ops/run_router.py::approve_draft` (POST `/ops/drafts/{id}/approve?auto_run=true`)

### Full call chain

```
approve_draft (run_router.py::approve_draft)
  └─ OpsService.create_run(approved.id)                         # status=pending
  └─ OpsService.update_run_status(run.id, "running",
         msg="Execution started via draft approval auto-run")   # ← status=running BEFORE dispatch
  └─ _spawn_run(request, run.id, composition=...)               # fire-and-forget
        └─ supervisor = request.app.state.supervisor
        └─ supervisor.spawn(
               EngineService.execute_run(run_id, composition),
               name=f"run:{run_id}",
               on_failure=_on_failure,
               timeout=3600)
              └─ resilience.py::SupervisedTask.spawn
                    └─ asyncio.create_task(_supervised_wrapper())
                         └─ (task scheduled — may or may not actually run)
                               └─ engine_service.py::EngineService.execute_run
                                    └─ engine_service.py::run_composition
                                         └─ pipeline.py::Pipeline.run
                                              └─ stage.execute(input)  # per stage
```

### Where it breaks

**File**: `tools/gimo_server/routers/ops/run_router.py::approve_draft`
**Failing region** (quoted from subagent trace):

```python
if run.status == "pending":
    try:
        run = OpsService.update_run_status(
            run.id, "running",
            msg="Execution started via draft approval auto-run")   # ← point of no return
        _spawn_run(request, run.id, composition=composition)       # ← fire-and-forget, no ack
    except Exception as exc:
        logger.error("Spawn failed for draft %s, falling back to worker: %s", draft_id, exc)
        worker = getattr(request.app.state, "run_worker", None)
        if worker is not None:
            worker.notify()
```

The comment above this block in the source reads:
> *"Deterministic immediate start from any channel (UI/MCP) when run is pending. We intentionally start merge-gate directly and set status to running to avoid pending limbo and worker race on the same run."*

And `_spawn_run` itself returns `None`:

```python
def _spawn_run(request, run_id, composition=None) -> None:
    supervisor = getattr(request.app.state, "supervisor", None)
    if supervisor:
        supervisor.spawn(
            EngineService.execute_run(run_id, composition=composition),
            name=f"run:{run_id}", on_failure=_on_failure, timeout=3600)
    else:
        asyncio.create_task(_fallback())
    # no return value, no ack, no validation the task actually started
```

And `run_worker.py::_tick` (subagent-verified): only processes `status == "pending"` runs.

### Root cause (1–2 sentences)

`approve_draft` transitions the run to `"running"` **before** verifying that `_spawn_run` actually scheduled an executable task, and the only recovery path (`worker.notify()`) fires **only when `_spawn_run` raises an exception**. When `supervisor.spawn` silently succeeds at creating an `asyncio.Task` that is never actually executed (wrong loop, stalled executor, or a task body that exits immediately on a dead pre-check), the run is permanently stranded in `running` while `run_worker._tick` — which only picks up `pending` runs — can never reclaim it. Eventually a reconcile/cleanup sweep or server restart marks it `done` with zero work performed, producing the hollow-completion pattern observed.

### Secondary contributor: approved_id gate skip

Introduced by commit **154acd2** (R14.1 — "inject approved_id into pipeline context"). In `engine_service.py::execute_run`:

```python
if run.approved_id:
    context["approved_id"] = run.approved_id
```

Then in `engine/stages/policy_gate.py::PolicyGate.execute`:

```python
if input.context.get("approved_id"):
    return StageOutput(
        status="continue",
        artifacts={"gate_skipped": True, "reason": "draft already approved"})
```

(And the same shape in `risk_gate.py::RiskGate.execute`.) When both gates short-circuit, `intent_effective` is never classified, which affects composition inference in `engine_service.py::execute_run`:

```python
elif context.get("intent_effective") in {"MERGE_REQUEST","CORE_RUNTIME_CHANGE","SECURITY_CHANGE"}:
    composition = "merge_gate"
```

If `intent_effective` is absent, composition falls back to `legacy_run`. This is **not** the primary failure (legacy_run still has stages), but it is a correctness hazard that should be fixed alongside the main wire.

### Blast radius

All of these symptoms collapse under the single primary wire:

- #1 hollow runs (MCP auto_run path)
- #5 no heartbeat / no stage (pipeline never actually executes)
- #6 zero cost/tokens (LLM never called)
- #12 empty traces (the `UISpanProcessor.on_end` hook in `observability_service.py` never fires because `engine._execute_step` — which calls `record_node_span` — is never reached)
- HTTP-originated auto_run paths (same code path)
- Any future surface that approves via `run_router.approve_draft`

### Fix options

| Option | Location | Change | Risk |
|---|---|---|---|
| A (recommended) | `run_router.py::approve_draft` + `_spawn_run` | Keep the run in `pending` until dispatch is acknowledged. Make `_spawn_run` return `bool` (True if the task was successfully created). On `False`, call `worker.notify()` immediately. The executor (or run_worker) is responsible for the `pending → running` transition. | LOW |
| B | `run_worker.py::_tick` | Add orphan detection: after listing pending runs, also list runs with `status=running` + `heartbeat_at is None` + `age > 60s` and transition them back to `pending` or directly to `error`. | MEDIUM (masks root cause; risks double-running legitimate slow starts) |
| C | `engine/stages/policy_gate.py::execute` + `risk_gate.py::execute` | Don't short-circuit on `approved_id`; instead, record the pre-approval and still run classification so `intent_effective` is populated, then honor approval at the decision step. | MEDIUM (reverts part of R14.1, needs careful re-test) |

### Confidence: **HIGH**

- `approve_draft` status-before-dispatch pattern directly visible in code.
- `_spawn_run` has no return value / no ack.
- `run_worker._tick` pending-only filter verified.
- No exception logs in audit (fallback never fires).
- 6-minute delay is consistent with a cleanup sweep or restart reconcile path.

---

## Cluster B — Hollow Agentic Loop (#2, #4)

### Entry points

- CLI: `gimo_cli/commands/chat_cmd.py::chat` → POST `/ops/threads/{id}/chat`
- CLI: `gimo_cli/commands/plan.py::plan` → POST `/ops/generate-plan-stream`
- MCP: `mcp_bridge/native_tools.py::gimo_chat` → background POST `/ops/threads/{id}/chat`
- HTTP handler: `routers/ops/conversation_router.py::chat_message` → `services/agentic_loop_service.py::AgenticLoopService.run`

### Call chain to LLM

```
AgenticLoopService._run_loop (agentic_loop_service.py::_run_loop)
  └─ adapter = _resolve_orchestrator_adapter()          # providers/openai_compat.py::OpenAICompatAdapter for local_ollama
  └─ llm_result = await adapter.chat_with_tools(...)    # → POST {base_url}/chat/completions
       └─ openai_compat.py::_raw_chat_with_tools
            ├─ resp = await client.post(...)
            ├─ data = resp.json()
            └─ message = data["choices"][0]["message"]
                  └─ content = message.get("content")   # ← may be None
  └─ content = llm_result.get("content")                # ← may be None
  └─ tool_calls = list(llm_result.get("tool_calls", []) or [])
  └─ if not tool_calls:
         final_response = content or ""                 # ← "" if content was None
         break
  └─ # turn persistence
     if persist_conversation and thread_id:
         orch_turn = ConversationService.add_turn(thread_id, agent_id="orchestrator")
         if content:                                    # ← SILENT GATE
             ConversationService.append_item(
                 thread_id, orch_turn.id,
                 GimoItem(type="text", content=content, status="completed"))
         # else: turn is HOLLOW
```

### Silent-fail location (quoted from subagent trace)

**File**: `tools/gimo_server/services/agentic_loop_service.py::AgenticLoopService._run_loop`

```python
llm_result = await adapter.chat_with_tools(...)   # succeeds with content=None
...
content = llm_result.get("content")               # None
tool_calls = list(llm_result.get("tool_calls", []) or [])
...
if not tool_calls:
    final_response = content or ""                # ""
    break
...
if persist_conversation and thread_id:
    orch_turn = ConversationService.add_turn(thread_id, agent_id="orchestrator")
    ...
    if content:                                   # ← False → block skipped
        ConversationService.append_item(thread_id, orch_turn.id,
            GimoItem(type="text", content=content, status="completed"))
    # Turn is now hollow (no items)
```

Later in the same function:
```python
if persist_conversation and thread_id and final_response:   # ← final_response == "" → False
    final_turn = ConversationService.add_turn(...)
    ...
```

So the "final turn" block is also skipped, and the CLI SSE stream never gets a "completed" frame.

### Root cause (1–2 sentences)

The provider adapter round-trip returns a dict whose `content` field is `None` (or empty string) **without raising**, and the agentic loop's `if content:` gate treats that as "append nothing" rather than as an error. Both observable symptoms — empty CLI stdout (#2) and hollow orchestrator turn (#4) — are the same event seen from two surfaces: the renderer has no SSE frame to display, and the persisted thread has a turn row with zero items.

### Why is `content` empty?

This is the part the subagent could **not** fully verify statically. Possible causes, in order of likelihood:
1. **Ollama endpoint returning a valid 200 response with `message.content = null`** — happens when a model returns only tool_calls with no text, or when the chat template produces an empty assistant turn. Since `tool_calls` is also empty in the observed failure, this is consistent with the model returning a truly empty response.
2. **Wrong endpoint shape** — `openai_compat.py::_raw_chat_with_tools` POSTs to `{base_url}/chat/completions`; if `base_url` is Ollama native (`:11434/api`) instead of the OpenAI-compat shim (`:11434/v1`), the response schema won't match and `message.get("content")` silently returns None.
3. **Adapter is not being used at all** — a code path that returns a stub `{"content": None, "tool_calls": []}` without making any network call. This would be consistent with the metrics showing zero tokens/cost AND the fact that Ollama was reported reachable by `providers test` but had `Auth status: unknown`.

The subagent's MEDIUM-HIGH confidence rating reflects the fact that the silent-gate is definitively the propagation mechanism, but pinpointing the exact empty-content source requires runtime instrumentation (already listed as fix option 4 below).

### Blast radius

- CLI `chat` / `plan` / `interactive chat` — all dead
- MCP `gimo_chat` — structurally returns but semantically hollow
- Any future surface that uses `AgenticLoopService`
- Cost/token metrics (#6) — partially: chat path never records usage because `content` path never returns
- Streaming plan generation — same root pattern in `plan_router.py::generate_plan_stream` uses `ProviderService.static_generate` which has its own but similar code path

### Fix options

| Option | Location | Change | Risk |
|---|---|---|---|
| A (recommended) | `agentic_loop_service.py::_run_loop` right after `content = llm_result.get("content")` | Treat `content is None` or `content.strip() == ""` as a provider error: log full `llm_result`, set `final_response` to a descriptive error, emit `error` SSE event, break. | LOW |
| B | `providers/openai_compat.py::_raw_chat_with_tools` | After `data = resp.json()`, assert the response shape: `choices[0].message.content` must exist as a string, else raise `ProviderContractError`. | LOW-MEDIUM |
| C | `agentic_loop_service.py::_resolve_orchestrator_adapter` | Add a health-check before the first tool-capable call. | MEDIUM (adds latency) |
| D (diagnostic) | Temporarily add `logger.info("llm_result=%s", llm_result)` at the call site | To capture what Ollama is actually returning at runtime during R17 verification. | LOW, temporary |

Recommended combination: **A + D**. Land A permanently, D for R17 smoke-test only.

### Confidence: **MEDIUM-HIGH**

The silent-gate propagation is HIGH-confidence. The exact reason `content` arrives empty is MEDIUM because it was not reproduced under instrumentation in Phase 2.

---

## Cluster C — GICS Daemon Never Initialized (#3)

### Entry point

`tools/gimo_server/main.py::lifespan` (FastAPI startup), roughly:

```python
gics_service = GicsService()
gics_service.start_daemon()
gics_service.start_health_check()
app.state.gics = gics_service
```

### Where it breaks

**File**: `tools/gimo_server/services/gics_service.py::GicsService.start_daemon`

The subagent identified **two silent early-return paths**:

```python
def start_daemon(self) -> None:
    if self._cli_path is None or not self._cli_path.exists():
        logger.error("GICS CLI not found at %s", self._cli_path)
        return                                    # ← early return, no raise
    node = shutil.which("node")
    if node is None:
        logger.warning("Node.js not found on PATH; GICS daemon disabled")
        return                                    # ← early return, no raise
    # ... only now is self._supervisor actually created
```

Both branches return without setting any flag that the lifespan startup could check, and without raising. The subsequent `start_health_check()` call builds a health-check task that will always see `_last_alive = False` because `_rpc.aping()` fails (no daemon listening on IPC).

### Root cause (1–2 sentences)

`GicsService.start_daemon` degrades silently to a no-op when either the GICS CLI file or the `node` binary is missing, leaving `self._supervisor = None` and `self._last_alive = False` without raising or setting any "degraded" flag. The lifespan startup in `main.py` proceeds as if GICS is alive, and all downstream tools (`gimo_get_gics_insight`, `gimo_gics_anomaly_report`, `gimo_get_governance_snapshot.gics_health`) permanently report `"not initialized"`.

R16's claimed fix ("token path + pre-check") did not address these two pre-existing early-return branches.

### Blast radius

- GICS insight / anomaly / model-reliability MCP tools — all dead
- `governance_snapshot.gics_health.daemon_alive` always `false`
- Cost telemetry and model-outcome tracking via GICS
- Session revocation falls back to in-memory only
- Audit trail integrity proofs that depend on GICS

### Fix options

| Option | Location | Change | Risk |
|---|---|---|---|
| A (recommended) | `gics_service.py::start_daemon` | Raise `GicsStartupError` instead of returning silently; catch it in `main.py::lifespan` and set `app.state.gics_degraded = True` with clear log at ERROR level. | LOW |
| B | `main.py::lifespan` | Add explicit pre-check for `node` and the CLI path; log and set a degraded-mode flag if either is missing. Include the flag in `/health` and in `governance_snapshot`. | LOW |
| C | `gics_service.py` | Provide an in-process Python fallback "GICS-lite" that can record entries in SQLite when the Node daemon is unavailable. | HIGH (new code) |

Recommended: **A + B**. Solves the silence and surfaces the degradation. C is a future enhancement, not R17 scope.

### Confidence: **HIGH (~99%)**

Code path is unambiguous; the two early-return branches are directly quoted and match the observed `daemon_alive: false` in audit.

---

## Cluster D — MCP Schema Drift (#7, #9, #10, #11)

### Single architectural root cause

**File**: `tools/gimo_server/mcp_bridge/server.py::_register_dynamic` and `_register_native`

The bridge registers tools through **two uncoordinated code paths**:

```python
# server.py::_register_dynamic  (line region)
provider = OpenAPIProvider(
    spec, client=client, mcp_names=mcp_names,
    route_map_fn=_ops_only, validate_output=False)
mcp.add_provider(provider)
_register_static_aliases()

# server.py::_register_native
from tools.gimo_server.mcp_bridge.native_tools import register_native_tools
from tools.gimo_server.mcp_bridge.governance_tools import register_governance_tools
register_native_tools(mcp)
register_governance_tools(mcp)
```

- `_register_dynamic` derives tool schemas automatically from the FastAPI OpenAPI spec.
- `_register_native` registers hand-written schemas in `native_tools.py` and `governance_tools.py`, many of which **proxy back through HTTP** via `proxy_to_api()` with parameter-name translation that is undocumented.

Commit `f70c6e1` (SAGP) moved native tools from direct `OpsService` calls to `proxy_to_api` without updating the documented MCP contract names. The audit checklist (and `SAGP.md` / `CLIENT_SURFACES.md`) still reference the pre-refactor names.

### Per-tool drift (subagent-verified)

| Tool | File::symbol | Current MCP param | Audit-expected param | Notes |
|---|---|---|---|---|
| `gimo_evaluate_action` | `governance_tools.py::gimo_evaluate_action` | `tool_name` | `action_type` | Drift |
| `gimo_create_draft` | `native_tools.py::gimo_create_draft` | `task_instructions` | `description` | Proxied to HTTP `POST /ops/drafts` body key `prompt` (undocumented translation) |
| `gimo_run_task` | `native_tools.py::gimo_run_task` | `task_instructions` | `task` | Same proxy, same translation |
| `gimo_get_task_status` | `native_tools.py::gimo_get_task_status` | `run_id` | `task_id` | Naming vs HTTP path param |
| `gimo_generate_team_config` | `native_tools.py::gimo_generate_team_config` | `plan_id` (required) | `objective` (string) | Feature regression — see #10 |
| `gimo_verify_proof_chain` | `governance_tools.py::gimo_verify_proof_chain` | `thread_id` (required) | optional `thread_id` | No global mode — see #11 |
| `gimo_gics_model_reliability` | `native_tools.py::gimo_gics_model_reliability` | `model_id` (required) | optional `model_id` | No list-all mode |
| `gimo_estimate_cost` | `governance_tools.py::gimo_estimate_cost` | `input_tokens: int`, `output_tokens: int` (correct in signature) | int | Serializer bug — see #9 |

### Issue #9 — `gimo_estimate_cost` int→string coercion

**File**: `governance_tools.py::gimo_estimate_cost` — the signature is correct (`input_tokens: int = 1000`). The subagent's most likely explanation: the MCP JSON-RPC request reaches the bridge as numbers, but somewhere in the bridge plumbing (most plausibly `OpenAPIProvider`'s query-parameter handling, or an intermediate schema cast), the values are coerced to strings before Pydantic validation. Because `estimate_cost` is a native tool, not an OpenAPI-derived one, the coercion is more likely to be in a shared MCP-to-Python JSON-schema path. Runtime instrumentation is needed to pinpoint the exact line.

**Confidence**: MEDIUM. We know the error surface and the tool signature is correct; we don't have a definitive line for the coercion.

### Issue #10 — `generate_team_config` lost "from objective" mode

**File**: `native_tools.py::gimo_generate_team_config` (current):
```python
async def gimo_generate_team_config(plan_id: str) -> str:
    """Args: plan_id: Plan/draft ID to generate team config from"""
```

The function contains a fallback that attempts to re-synthesize a plan if the draft has no content — evidence that the original design was "accept an objective, materialize a plan on-demand, produce a team config". Commit `f70c6e1` narrowed the surface to require a pre-existing plan_id. Docs still describe the original mode.

### Issue #11 — `verify_proof_chain` has no global scope

**File**: `governance_tools.py::gimo_verify_proof_chain`:
```python
async def gimo_verify_proof_chain(thread_id: str) -> str:
    """Args: thread_id: Thread ID whose proof chain to verify"""
```

`gimo_evaluate_action` returns a per-call `proof_id` (e.g., `0966cd383a234047` in the R17 audit) that is not attached to any thread at the moment it's produced. There is **no way** to verify that proof after the fact, because `verify_proof_chain` requires a `thread_id` scope.

### Root cause (1–2 sentences)

The MCP bridge has no canonical source of truth for tool parameter contracts — native tools (`native_tools.py` + `governance_tools.py`) declare their own schemas independently from `OpenAPIProvider`-derived tools, and the SAGP refactor (commit `f70c6e1`) introduced HTTP proxying through `proxy_to_api` with undocumented parameter-name translations. Documentation (`SAGP.md`, `CLIENT_SURFACES.md`) was not kept in sync, so the audit-checklist-expected names drifted from the actual names in four tools, one tool lost a feature (`generate_team_config`), and two tools have overly restrictive required-parameter signatures (`verify_proof_chain`, `gics_model_reliability`).

### Fix options

| Option | Change | Risk |
|---|---|---|
| A (recommended, minimal for R17) | Per-tool fixes: rename params to match `SAGP.md` / align HTTP bodies / make `thread_id` and `model_id` optional with sensible defaults / restore `objective` mode to `generate_team_config` via a keyword-union signature. | LOW (isolated, each tool testable) |
| B (architectural, defer) | Introduce canonical Pydantic contract models in `ops_models.py` and have both `_register_native` and `_register_dynamic` derive schemas from them. Eliminates drift by construction. | HIGH (bridge rewrite) |
| C | Document the current contracts exactly as implemented and update the audit checklist to match. (Surface parity by documentation fiat, not by code.) | LOW but misses feature regressions |

Recommended for R17: **A**. Defer B to a later round as a proper refactor.

### Confidence: **HIGH for #7/#10/#11, MEDIUM for #9**

---

## Cluster E — Cross-Surface Drift (#8, #12, #13)

### Issue #8 — Trust divergence CLI vs MCP

**Divergence point** (subagent-verified, one-line mismatch):

- **HTTP**: `tools/gimo_server/routers/ops/trust_router.py::trust_dashboard`
  ```python
  return {"items": result, "count": len(result)}
  ```

- **CLI renderer**: `gimo_cli/render.py::TRUST_STATUS`
  ```python
  TRUST_STATUS = TableSpec(
      title="Trust Dimensions",
      columns=["dimension", "score", "state"],
      unwrap="entries",                                 # ← expects "entries", gets "items"
      empty_msg="No trust data yet. Trust builds as you use GIMO.",
  )
  ```

- **MCP**: `governance_tools.py::gimo_get_trust_profile` → `SagpGateway._get_trust_score(dim)` for each of provider/model/tool → returns the R16 unified 0.85 default.

Two separate read paths: the CLI reads the real `TrustEngine.dashboard()` via `/ops/trust/dashboard` but can't parse the wrapper key; the MCP reads from `SagpGateway._get_trust_score` which is essentially a static 0.85. Both paths are "working" but they answer different questions, and the CLI one is broken by a one-word schema mismatch.

**Root cause**: Response wrapper key `items` vs renderer `unwrap="entries"`. Single-word bug.

**Fix**: Change `trust_router.py::trust_dashboard` to return `{"entries": result, "count": len(result)}`. Or change the renderer to `unwrap="items"`. **Prefer the router fix** because multiple other responses (per R17 audit Probe D) already use `items` and may need renderer-side support — but CLAUDE.md indicates other render specs already use `entries`. Check one convention and apply consistently.

**Confidence**: HIGH (~99%).

### Issue #12 — `observe traces` always empty

**Data flow** (subagent-verified):

```
services/graph/engine.py::_execute_step
    └─ observability_service.py::record_node_span   # creates OTel span
         └─ UISpanProcessor.on_end (observability_service.py::UISpanProcessor.on_end)
              └─ cls._ui_spans.append(span)         # deque, maxlen=5000
...
observability_router.py::observability_traces
    └─ observability_service.py::list_traces
         └─ return list(cls._ui_spans)[:limit]
```

The read path is healthy. The write path is **never invoked** because `engine._execute_step` is never called (cluster A's primary failure — the pipeline never actually runs).

**Root cause**: Downstream symptom of cluster A, not an independent bug.

**Fix**: Automatic once #1/#5 are fixed. No dedicated fix needed. **If** after cluster A fixes land the traces are still empty, then `UISpanProcessor` is not wired into the OTel tracer provider — investigate then.

**Confidence**: HIGH (~95%). Trace code is present and wired; the upstream is dead.

### Issue #13 — `doctor` reports connectivity `unknown`

**Code comparison** (subagent-verified):

- **`providers test <id>`** (`gimo_cli/commands/providers.py::providers_test`, works):
  ```python
  status_code, payload = api_request(config, "GET", f"/ops/connectors/{provider_id}/health")
  if status_code == 200: ...
  ```
  Single direct call.

- **`doctor`** (`gimo_cli/commands/auth.py::doctor`, broken):
  ```python
  with httpx.Client(timeout=5.0) as client:
      prov_resp = client.get(f"{server_url}/ops/provider",
          headers={"Authorization": f"Bearer {token_for_check}"})
      if prov_resp.status_code == 200:
          prov_data = prov_resp.json()
          active = prov_data.get("active") or prov_data.get("orchestrator_provider", "unknown")
          providers = prov_data.get("providers", {})
          if active and active in providers:
              # only NOW does the health check happen
              health_resp = client.get(
                  f"{server_url}/ops/connectors/{active}/health", ...)
  ```
  Multi-step conditional: requires `/ops/provider` to 200 AND return a dict with an `active` key whose value is in the `providers` dict — if any step fails, the nested health check never runs and the outer exception handler prints generic "check failed" or the section remains unpopulated.

**Root cause**: `doctor` implements its own connectivity probe with a brittle multi-step conditional chain, different from the single-step probe already known to work in `providers_test`.

**Fix**: Reuse the same call that `providers test` uses. Specifically, once `active` is known (from `/ops/provider` or directly from CLI config / bond), call `/ops/connectors/{active}/health` unconditionally and report its result.

**Confidence**: HIGH (~90%).

---

## Systemic Patterns

Looking across all 13 issues, three meta-patterns emerge.

### Pattern 1 — "Silent success gate"

Multiple failures are masked by a happy-path check that does not distinguish "no work needed" from "work failed silently":

- `approve_draft::_spawn_run` has no return value; no-exception is treated as "dispatch succeeded" (#1, #5, #6, #12)
- `_run_loop::if content:` treats empty content as "nothing to append" rather than as an error (#2, #4)
- `GicsService.start_daemon` returns silently on missing dependency (#3)

**Invariant violation**: any operation that can silently produce a no-op should either:
1. Return an explicit acknowledgement that work was actually done, OR
2. Raise when the precondition is not met.

**Preventive fix**: a lint-level rule or code-review checklist item: "Functions that dispatch work MUST return an ack; functions that skip work MUST log at WARNING or higher and flag the degraded state."

### Pattern 2 — "Two sources of truth"

Several bugs come from two code paths that answer the same question diverging:

- MCP bridge native schemas vs OpenAPIProvider schemas (#7, #9, #10, #11)
- CLI trust-read (HTTP) vs MCP trust-read (SagpGateway) (#8)
- CLI `doctor` connectivity probe vs `providers test` probe (#13)
- Trust engine default (0.85) vs TrustEngine.dashboard() (empty) (#8 subcomponent)

**Invariant violation**: a canonical fact about the system (what is the trust score, what is this tool's contract, is this provider up) should have exactly one implementation, with other call sites delegating.

**Preventive fix**: centralize the read paths. Trust dashboard should be one function used by both CLI and MCP; MCP tool contracts should derive from Pydantic models in `ops_models.py`; connectivity probe should be a single function used by `doctor` and `providers test`.

### Pattern 3 — "Cascade from the dead data plane"

Six issues (#1, #5, #6, #12, and partially #4) collapse under a single fix in cluster A. The "hollow run" pathology dominates the issue surface. This is the same observation as R16 and R14. The repeated pattern suggests that:

- Each round adds a patch near the symptom (heartbeat, SSE, materialization) without actually verifying that the pipeline worker is running.
- The R16 accuracy score (50%) is almost entirely driven by this cluster being repeatedly claimed-fixed but not runtime-verified.

**Preventive fix** (Phase 4 already encodes this): the Runtime Smoke Test gate in Phase 4 must include a mandatory "create draft → approve auto_run → assert file exists on disk" test. Any R18+ round that cannot produce this assertion is not complete.

---

## Preventive Findings

Future failure modes enabled by the current architecture but not yet manifested in R17:

1. **Any future tool that uses `proxy_to_api` inherits the translation risk** — a future addition will likely add another silent parameter-name drift unless pattern 2 is fixed.

2. **The `if content:` pattern likely exists elsewhere in the agentic loop or in plan_router** — a grep for `if content:` across `services/` is advisable; any other occurrence is a latent version of #2/#4.

3. **Any lifespan startup step that can silently degrade creates invisible dependencies** — the `main.py::lifespan` should be audited for other silent early-returns (redis, storage, journal, audit).

4. **`run_worker._tick` pending-only filter is fragile** — any future channel that creates runs in non-pending status will hit the same orphan problem cluster A fixes.

5. **The `proof_id` returned from `evaluate_action` is structurally orphaned** — issue #11 is a symptom of a missing "per-action proof log" that is separate from the thread-scoped chain. This is a latent architectural gap.

---

## Dependency Graph

```
cluster A (#1, #5, #6, #12)  ────┬─► affects observe traces (#12) by starvation
                                 │
                                 └─► affects cost tracking (#6) by starvation

cluster B (#2, #4)           ────┬─► shares silent-gate pattern with cluster A
                                 │
                                 └─► affects chat UX independently from run pipeline

cluster C (#3)               ────► independent; affects GICS telemetry only

cluster D (#7, #9, #10, #11) ────► independent; affects MCP surface contracts only

cluster E:
  #8 (trust)                 ────► independent; one-line schema fix
  #12 (traces)               ────► downstream of cluster A
  #13 (doctor)               ────► independent; refactor to reuse probe
```

**Key observation**: clusters A, B, C, D are structurally independent and can be fixed in parallel. Within cluster E, #12 collapses under cluster A.

---

## Recommended Fix Priority

1. **Cluster A fix (Option A) — `run_router::approve_draft` + `_spawn_run` return ack + run_worker reclamation** — single highest-leverage change, resolves #1/#5/#6/#12 simultaneously.
2. **Cluster B fix (Option A + D) — `_run_loop` content validation + runtime instrumentation to identify the empty-content source** — resolves #2/#4.
3. **Cluster C fix (Option A + B) — `GicsService.start_daemon` raises on missing dependency + lifespan degraded-mode flag** — resolves #3.
4. **Cluster D fix (Option A) — per-tool parameter corrections + restore `generate_team_config` objective mode + make `verify_proof_chain` / `gics_model_reliability` params optional** — resolves #7/#10/#11, partially #9.
5. **#9 runtime investigation** — instrumentation round needed; deferred to Phase 3 plan.
6. **#8 one-line fix** — change `trust_router.trust_dashboard` wrapper key to `entries`, or verify renderer convention and align both sides.
7. **#13 refactor** — `doctor` reuses the `providers_test` connectivity probe helper.

---

## Audit Trail

- Phase 1 input: `docs/audits/E2E_AUDIT_LOG_20260407_R17.md`
- Phase 2 output: **this document** (`docs/audits/E2E_ROOT_CAUSE_ANALYSIS_20260407_R17.md`)
- Method: 5 parallel Explore subagents, symbol-anchored traces, read-only.
- Working tree: commit `dc2395c` (R16 fixes in place, unmodified).

Next step: Phase 3 — `/e2e fase 3` — SOTA research + engineering plan in Plan Mode, 8-criterion compliance matrix, MANDATORY user approval before Phase 4.
