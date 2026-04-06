# E2E Root-Cause Analysis — R14

**Date**: 2026-04-06
**Round**: 14
**Input document**: `E2E_AUDIT_LOG_20260406_R14.md`

---

## Issue Map

| ID | Category | Root Cause Location | Confidence |
|----|----------|---------------------|------------|
| #1 | Execution | `engine_service.py:381` — halt returns without terminal status | HIGH |
| #2 | CLI | `plan.py:83-87` — SSE protocol mismatch with server | HIGH |
| #3 | Infrastructure | `gics_service.py:109` — Node.js not on PATH or daemon bind failure | HIGH |
| #4 | MCP Bridge | `native_tools.py:256` — unbounded LLM call exceeds MCP timeout | HIGH |
| #5 | MCP Bridge | `native_tools.py:531` — `params=` instead of `json=` | HIGH |
| #6 | MCP Bridge | `native_tools.py:422` — `workspace_path` missing from schema | HIGH |
| #7 | Execution | Consequence of #1 — no LLM calls = no cost data | HIGH |
| #8 | MCP Bridge | `native_tools.py:684` — reads `.orch_data/ops/drafts/`, not `.gimo/plans/` | HIGH |
| #9 | Trust | `sagp_gateway.py:217` + `trust_engine.py:235` — three different default paths | HIGH |
| #10 | API | `config_router.py:99` — only per-connector health, no aggregate | HIGH |
| #11 | API | `child_run_router.py` — no GET listing route defined | HIGH |
| #12 | API | `conversation_router.py:59` — workspace_root as required query param | HIGH |
| #13 | CLI | FALSE POSITIVE — `--yes` flag exists at `trust.py:36` | HIGH |
| #14 | API | Design choice — GET with query params, not a bug | MEDIUM |
| #15 | Infra | psutil thresholds — cosmetic, not functional | LOW |

---

## Detailed Traces

### #1 — Run Execution Never Progresses

**Reported symptom**: Run stays at `status:running, stage:null, heartbeat_at:null` with 0 tokens forever.

**Entry point**: `POST /ops/drafts/{id}/approve?auto_run=true`

**Trace**:
```
POST /ops/drafts/{id}/approve?auto_run=true
  → run_router.py:118   approve_draft()
  → run_router.py:173   OpsService.create_run(approved.id) → status="pending"
  → run_router.py:179   OpsService.update_run_status(run.id, "running")
  → run_router.py:180   _spawn_run(request, run.id)
  → run_router.py:37    supervisor.spawn(EngineService.execute_run(run_id))
  → engine_service.py:237  execute_run()
  → engine_service.py:365  run_composition(composition, run_id, context)
  → pipeline.py:35       Pipeline.run(initial_context)
    Stage 1: PolicyGate.execute()
    → policy_gate.py:39  if policy_decision == "review" → StageOutput(status="halt")
    → pipeline.py:76     if output.status == "halt": break  ← BREAKS HERE
  → engine_service.py:381  if stage_output.status == "halt": return results
                            ← RETURNS WITHOUT UPDATING RUN STATUS
```

**Root cause**: **Double-gating with silent halt.** The pipeline re-evaluates PolicyGate and RiskGate during execution, even though the draft was already approved. The draft's `execution_decision` was `HUMAN_APPROVAL_REQUIRED` (already satisfied by manual approve), but PolicyGate re-evaluates from scratch and halts. When halt occurs, `engine_service.py:381` returns without updating the run to a terminal state. The run stays `running` forever.

Three compounding failures:
1. `engine_service.py:381-383` — `halt` returns without setting terminal status (run stuck forever)
2. `policy_gate.py:39-40` — Re-evaluates policy redundantly on already-approved drafts
3. `pipeline.py:76-77` — `halt` break has no logging

**Blast radius**: Every run via approve+auto_run is affected. No run can ever complete via this path. Child runs also stuck. Cost tracking, trust recording, GICS telemetry — all downstream systems starved of data because no LLM call ever fires.

**Error-swallowing points**:
- `run_router.py:181-187` — If `_spawn_run` raises, falls back to `worker.notify()`, both wrapped in `except Exception: pass`
- `run_router.py:198-201` — `except RuntimeError` only handles `RUN_ALREADY_ACTIVE`, rest pass-through
- `run_worker.py:97` — `except Exception: logger.exception("RunWorker tick error")` logs but continues

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `engine_service.py:381` | On `halt`, update run status to `"awaiting_review"` or `"halted"` | Low — adds terminal state |
| B (recommended) | `policy_gate.py:39` + `risk_gate.py:32` | Skip gates when draft is already `approved` (check `context.get("approved_id")`) | Low — removes redundant re-evaluation |
| C | Both A + B | Skip gates for approved drafts AND handle halt gracefully | Lowest risk — defense in depth |

**Confidence**: HIGH

---

### #2 — CLI plan/chat Silent Failure

**Reported symptom**: `gimo plan "..." --no-confirm` produces zero visible output, exits with "Plan generation failed: no draft received."

**Entry point**: `gimo plan` → `gimo_cli/commands/plan.py:22`

**Trace**:
```
plan.py:68    client.stream("POST", url, params={"prompt": description})
              → /ops/generate-plan-stream

plan_router.py:358  generate_plan_stream() → StreamingResponse(event_generator())
plan_router.py:402  emit_sse(event_type, data) → "event: {type}\ndata: {json}\n\n"

Server emits:
  event: progress\n
  data: {"stage": "analyzing_prompt", "progress": 0.1, ...}\n\n
  event: completed\n
  data: {"result": {"draft_id":...}, "duration":..., "status":"success"}\n\n

plan.py:73-90  CLI parses with resp.iter_lines():
  Line: "event: progress"     → skipped (doesn't start with "data:")
  Line: "data: {...}"         → parsed as JSON
  Line: event.get("stage","") → gets "analyzing_prompt"
  Checks: stage == "progress" → FALSE (it's "analyzing_prompt")
          stage == "done"     → FALSE
          stage == "error"    → FALSE
  → Falls through, payload stays None

plan.py:98    payload is None → "Plan generation failed: no draft received."
plan.py:100   raise typer.Exit(1)
```

**Root cause**: **SSE protocol mismatch.** The server sends stage values like `"analyzing_prompt"`, `"building_context"`, `"calling_llm"`, `"parsing_response"`, `"validating_plan"`. The CLI checks for literal strings `"progress"`, `"done"`, `"error"`. None match. The completion event uses event type `"completed"` with a `"result"` dict; the CLI expects `stage == "done"` with a `"draft"` field.

Three specific mismatches:
1. **Progress stage names**: Server sends `"analyzing_prompt"` etc., CLI expects `"progress"`
2. **Completion**: Server sends `stage: absent, result: {...}`, CLI expects `stage: "done", draft: {...}`
3. **Error**: Server sends `stage: absent, error: "..."`, CLI expects `stage: "error"`

**Blast radius**: All CLI plan generation is completely non-functional. The `gimo chat` command likely has a similar protocol mismatch (not verified in detail but same streaming pattern).

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `plan.py:83-87` | Match server's actual protocol: check for `result` key (completion), `error` key (error), any `stage` key (progress) | Low — CLI-only change |
| B | `plan_router.py:418-423` | Change server to emit `stage: "progress"/"done"/"error"` | Medium — may break other consumers |
| C | Both | Align both sides to a documented SSE protocol | Best long-term |

**Confidence**: HIGH

---

### #3 — GICS Daemon Not Initialized

**Reported symptom**: `daemon_alive: false`, `error: "GICS not initialized"` across all GICS tools.

**Entry point**: Server startup → `GicsService.start_daemon()`

**Trace**:
```
gics_service.py:82    start_daemon()
gics_service.py:88    guard: self._cli_path check → PASS (file exists)
gics_service.py:99    GICSDaemonSupervisor(cli_path=self._cli_path, ...)
                      node_executable not passed → defaults to 'node'

gics_client.py:714    supervisor.start()
gics_client.py:724    subprocess.Popen(['node', '<cli_path>', 'daemon', 'start', ...])
                      ← FAILS HERE: 'node' not on PATH → FileNotFoundError
                      OR: node starts but daemon fails to bind on Windows named pipe

gics_client.py:729    wait_until_ready(timeout=15.0)
                      → polls ping() for 15s → TimeoutError

gics_service.py:109   except Exception as exc:
gics_service.py:110       logger.error("Failed to start GICS daemon: %s", exc)
gics_service.py:111       self._supervisor = None
                      ← ERROR SWALLOWED, _last_alive stays False
```

**Root cause**: Most likely **Node.js (`node`) is not installed or not on the system PATH**. The `GICSDaemonSupervisor` defaults `node_executable='node'` (`gics_client.py:695`) and `GicsService` never overrides it. There is no pre-flight check for Node.js availability. The `Popen` call either raises `FileNotFoundError` (caught) or starts a process that fails to bind (TimeoutError caught). Either way, the error is logged and swallowed.

Secondary: Even if Node is available, `Popen` does not capture stdout/stderr (`gics_client.py:724`), so daemon crash diagnostics are lost.

**Blast radius**: Without GICS, the entire telemetry pipeline is dead:
- `record_model_outcome()` via TelemetryMixin early-returns when `_gics` is None
- Trust recording depends on GICS events
- Model reliability data never collected
- Anomaly detection disabled

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `gics_service.py:82` | Pre-check: `shutil.which('node')`, log clear warning if missing | None |
| B | `gics_client.py:724` | Capture stderr from Popen, log daemon output on failure | None |
| C (recommended) | A + B + `gics_service.py:99` | Also allow configuring node path via `ORCH_NODE_PATH` env | None |

**Confidence**: HIGH

---

### #4 — All LLM-Dependent MCP Tools Timeout

**Reported symptom**: `gimo_create_draft`, `gimo_run_task`, `gimo_propose_structured_plan` all return `-32001`.

**Entry point**: MCP tool call via stdio

**Trace**:
```
MCP client (Claude Code) → stdio → server.py:273 mcp.run_stdio_async()

native_tools.py:296  gimo_create_draft(task_instructions)
native_tools.py:280  _generate_plan_for_task(task_instructions)
native_tools.py:256  ProviderService.static_generate(prompt, context)
                     ← UNBOUNDED WAIT (30-120s for LLM inference)

MCP client hits 60s timeout → sends cancellation → surfaces -32001
```

**Root cause**: `_generate_plan_for_task()` calls `ProviderService.static_generate()` which has **no timeout**. The LLM inference routinely takes 30-120 seconds. The MCP stdio transport has a client-side timeout of ~60 seconds. Combined with the `proxy_to_api` 30s httpx timeout, total tool execution easily exceeds the MCP limit.

**Blast radius**: All MCP tools that invoke LLM generation are non-functional: `gimo_create_draft`, `gimo_run_task`, `gimo_propose_structured_plan`. This means Claude (the operator) cannot create plans or run tasks through MCP — only through direct HTTP.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `native_tools.py:256` | Wrap in `asyncio.wait_for(static_generate(...), timeout=50)` | Low |
| B | `native_tools.py:280-321` | Use async streaming instead of blocking generate | Medium |
| C | MCP config | Increase `requestTimeout` in `.mcp.json` to 120s | Low (client-side) |

**Confidence**: HIGH

---

### #5 — gimo_chat MCP Tool Sends Malformed Body (422)

**Reported symptom**: `gimo_chat(message="Hello")` returns `HTTP 422: Field required`.

**Entry point**: MCP tool call

**Trace**:
```
native_tools.py:530  gimo_chat(message, thread_id, workspace_root)
native_tools.py:531  resp = await client.post(
                         f"{BACKEND_URL}/ops/threads/{thread_id}/chat",
                         params={"content": message},   ← WRONG
                         headers=headers,
                     )

conversation_router.py:179  chat_message(thread_id, body: ChatMessageBody, ...)
conversation_router.py:20   class ChatMessageBody(BaseModel):
                                content: str  # REQUIRED in JSON body
```

**Root cause**: **`params=` instead of `json=`.** The bridge sends `content` as a query parameter (`?content=Hello`), but the endpoint expects it as a JSON body (`{"content": "Hello"}`). FastAPI's Pydantic validation fails because no body is provided.

**Fix**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `native_tools.py:531` | Change `params={"content": message}` to `json={"content": message}` | None |

**Confidence**: HIGH

---

### #6 — gimo_spawn_subagent Missing workspace_path

**Reported symptom**: "workspace_path is required to spawn a sub-agent"

**Entry point**: MCP tool call

**Trace**:
```
native_tools.py:422  gimo_spawn_subagent(name, task, role, provider, model, execution_policy)
                     ← NO workspace_path parameter in signature

native_tools.py:442  req = {"modelPreference": ..., "constraints": {...}}
                     ← workspace_path NOT set in req dict

sub_agent_manager.py:98  workspace_path_str = request.get('workspace_path')
sub_agent_manager.py:100 if not workspace_path_str: raise ValueError(...)
```

**Root cause**: The MCP tool schema declares 6 parameters but not `workspace_path`. The `SubAgentManager.create_sub_agent()` requires it. The parameter was likely intentionally omitted during SAGP refactor when "direct source-repo worktree creation" was removed, but the requirement in `sub_agent_manager.py` was not updated.

**Fix**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `native_tools.py:422` | Add `workspace_path: str = ""`, default to `os.environ.get("ORCH_REPO_ROOT", ".")` | Low |

**Confidence**: HIGH

---

### #7 — Zero Cost Tracking

**Reported symptom**: `tokens_total: 0, cost_total_usd: 0.0` across all metrics.

**Root cause**: **Direct consequence of #1.** No LLM calls are ever made because the pipeline halts at PolicyGate. Cost tracking hooks (`CostService.record_usage()`, `TelemetryMixin.record_model_outcome()`) only fire after a successful LLM call. Since no call completes, no cost data is generated.

**Blast radius**: All cost-related features are empty: budget tracking, forecast, burn rate, model analytics, mastery recommendations.

**Fix**: Fix #1. Cost tracking will automatically populate once LLM calls succeed.

**Confidence**: HIGH

---

### #8 — gimo_generate_team_config Cannot Find Drafts

**Reported symptom**: `"Plan not found: d_1775485552683_a6fef6"` for an existing draft.

**Trace**:
```
native_tools.py:682  gimo_generate_team_config(plan_id)
native_tools.py:684  result = await proxy_to_api("GET", f"/ops/drafts/{plan_id}")
                     → reads from .orch_data/ops/drafts/{id}.json

                     CLI stores plans in: .gimo/plans/{id}.json
                     HTTP API stores drafts in: .orch_data/ops/drafts/{id}.json
```

**Root cause**: **Two separate storage locations, no sync.** The HTTP API's `OpsServiceBase.DRAFTS_DIR` is `.orch_data/ops/drafts/`. The CLI's plan store is `.gimo/plans/`. When a draft is created via HTTP (which we did), it IS in `.orch_data/ops/drafts/`. BUT: `gimo_generate_team_config` calls `proxy_to_api("GET", "/ops/drafts/{id}")` which returns the draft data — the issue is that the draft has `content: null` (no Mermaid plan was generated because the LLM call timed out). With `content` being null, the tool reports "Plan not found" even though the draft exists.

**Fix**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `native_tools.py:688` | Differentiate "draft not found" from "draft has no plan content" in error message | None |
| B | `native_tools.py:682-689` | Also check draft.prompt as fallback when content is null | Low |

**Confidence**: HIGH

---

### #9 — Trust Profile Inconsistency

**Reported symptom**: Three tools return three different trust values.

**Trace**:

| Surface | Code Path | Returns |
|---------|-----------|---------|
| `gimo_get_trust_profile` | `governance_tools.py:109` → `engine.dashboard()` → raw events | `[]` (empty, no events) |
| `governance_snapshot` | `sagp_gateway.py:217` → `engine.query_dimension()` → `score > 0 ? score : 0.85` | `{provider:0.85, model:0.85, tool:0.85}` |
| `/ops/trust/query` | `trust_router.py:27-30` → `engine.query_dimension()` + inline default | `{score:0.0, effective_score:0.85}` |

**Root cause**: The 0.85 default is applied in three different ways:
1. `gimo_get_trust_profile` — does NOT apply any default (raw empty list)
2. `governance_snapshot` — applies default inside `_get_trust_score()` (returns only defaulted value)
3. `trust/query` — exposes BOTH raw and defaulted as separate fields

The `_empty_record()` in `trust_engine.py:235` returns `score: 0.0`, and then each consumer applies (or not) the 0.85 fallback differently.

**Fix**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `trust_engine.py:235` | `_empty_record` returns `score: 0.85` (default) | Low — unifies all surfaces |
| B | `governance_tools.py:109` | Apply same default in MCP tool | Low |

**Confidence**: HIGH

---

### #10 — /ops/connectors/health 404

**Trace**: `config_router.py:99` defines `GET /connectors/{connector_id}/health` (per-connector). No aggregate `GET /connectors/health` exists.

**Root cause**: Route not defined. When calling `/ops/connectors/health`, FastAPI matches `connector_id="health"` which is not a valid connector ID → 404.

**Fix**: Add `GET /connectors/health` aggregate route that iterates all connectors.

**Confidence**: HIGH

---

### #11 — /ops/child-runs Listing 404

**Trace**: `child_run_router.py` defines `POST /spawn`, `POST /{id}/pause`, `GET /{id}/children`. No `GET /` index.

**Root cause**: Index/listing route never implemented.

**Fix**: Add `GET /child-runs` route delegating to `ChildRunService`.

**Confidence**: HIGH

---

### #12 — POST /ops/threads Requires Undocumented Query Param

**Trace**: `conversation_router.py:58-59` declares `workspace_root: str` as a bare parameter → FastAPI interprets as required query param.

**Root cause**: API design — `workspace_root` should be optional or in the request body.

**Fix**: Add `workspace_root: Optional[str] = Query(default=None)` or move to `CreateThreadRequest` body.

**Confidence**: HIGH

---

### #13 — trust reset No --yes Flag (FALSE POSITIVE)

**Trace**: `trust.py:36` defines `yes: bool = typer.Option(False, "--yes", ...)`. The flag exists.

**Root cause**: Audit error. In the Probe C test, the command was run in a piped context where `sys.stdin.isatty()` returns False. The confirmation prompt at line 40 checks `if not yes and sys.stdin.isatty()`, so in a pipe it prompts (since stdin appears to be a TTY in the test shell).

**Fix**: None needed. Flag works correctly.

**Confidence**: HIGH

---

### #14 — /ops/cost/compare GET-Only (Design Choice)

**Root cause**: Intentional GET endpoint with query params. Not a bug, just non-standard API design.

**Fix**: Optional — add POST alternative for API ergonomics.

**Confidence**: MEDIUM

---

### #15 — hardware_state "critical" (Cosmetic)

**Root cause**: psutil reports high resource usage on dev machine with multiple processes running. Thresholds may be too aggressive for development environments.

**Fix**: Optional — adjust thresholds or add a "dev mode" tolerance.

**Confidence**: LOW

---

## Systemic Patterns

### Pattern 1: Pipeline Re-Gating (Issues #1, #7)

The execution pipeline (PolicyGate → RiskGate → LlmExecute) re-evaluates governance gates that already passed during draft approval. This creates a **double-gating trap** where approved drafts are halted during execution. The `halt` status is not handled as a terminal state, leaving runs in limbo.

**Future risk**: Any new gate added to the pipeline will compound this problem. If a new gate halts, the same silent-stuck behavior occurs.

**What would make this impossible**: Make gates context-aware — if `context.approved_id` exists, gates should pass through or validate only conditions that could have changed since approval.

### Pattern 2: Protocol Drift Between Surfaces (Issues #2, #5, #6, #8, #9, #12)

Six issues trace to the same root: **different surfaces speak different protocols to the same backend**. The SSE event format differs between server and CLI. The MCP bridge serializes request bodies incorrectly. Trust data is defaulted differently per surface. Thread creation requires params the MCP surface can't provide.

**Future risk**: Every new feature added will need to be verified across 3 surfaces (MCP, CLI, HTTP) with 3 different serialization paths. Without a shared contract, drift is inevitable.

**What would make this impossible**: A single API contract definition (OpenAPI spec) that generates both server endpoints AND client stubs. All surfaces derive their serialization from the spec, not from manual coding.

### Pattern 3: Silent Error Swallowing (Issues #1, #3, #4)

Multiple critical failure points have `except Exception: pass` or `except Exception: logger.error(...)` patterns that swallow errors without updating system state. Runs stuck forever, daemons dead, MCP timeouts — all share the pattern of an error being caught and the system continuing as if nothing happened.

**Future risk**: New error modes will be equally invisible. Production incidents will be difficult to diagnose because failures leave no trace in the observable state.

**What would make this impossible**: Every `except` block that catches a broad exception must either (a) transition the associated resource to an error state, or (b) re-raise. No silent continuation.

### Pattern 4: GICS as Single Point of Intelligence (Issue #3)

GICS is required for trust recording, model reliability, anomaly detection, and telemetry. When it fails (Node.js not available), ALL of these capabilities are disabled. There is no graceful degradation — the system continues operating but with zero intelligence.

**Future risk**: GICS daemon is a Node.js process managed by Python. This cross-runtime dependency is fragile on Windows and will break whenever the environment changes.

**What would make this impossible**: Either (a) implement critical GICS features natively in Python as a fallback, or (b) make the Node.js dependency optional with clear user-facing warnings when missing.

---

## Dependency Graph

```
#1 (run execution halt) ──→ #7 (zero cost tracking)
                          ──→ #9 (trust never updated, empty data)

#3 (GICS dead) ──→ #9 (trust inconsistency, no telemetry)

#2 (CLI SSE mismatch) ←──── Pattern 2 (protocol drift)
#5 (chat params/json) ←──── Pattern 2
#6 (spawn workspace) ←──── Pattern 2
#8 (team_config stores) ←── Pattern 2
#12 (threads query param) ← Pattern 2

#1 (halt not terminal) ←──── Pattern 3 (silent error swallowing)
#3 (GICS error caught) ←──── Pattern 3
#4 (MCP no timeout) ←─────── Pattern 3
```

---

## Preventive Findings

1. **No integration test for draft→approve→execute→complete flow**: Unit tests pass (1378 green) but no test validates the full lifecycle. The PolicyGate double-gating would have been caught by a single integration test that creates a draft, approves it, and asserts `status: done`.

2. **No SSE contract test**: The CLI parser and server emitter have no shared schema or contract test. Drift is guaranteed whenever either side changes independently.

3. **No MCP bridge serialization test**: The bridge forwards parameters to HTTP but there's no test verifying the serialization matches what endpoints expect. Issues #5, #6, #8 would all be caught by tests that call the MCP tool and assert the HTTP request body.

---

## Recommended Fix Priority

| Priority | Issues | Rationale |
|----------|--------|-----------|
| P0 | #1 (halt handling) | Unblocks all execution — fixes #7 transitively |
| P0 | #2 (SSE protocol) | Unblocks CLI plan/chat — core user-facing commands |
| P1 | #5 (chat params→json) | One-line fix, unblocks MCP chat |
| P1 | #6 (spawn workspace_path) | Small fix, unblocks MCP agent spawning |
| P1 | #4 (MCP timeout) | Wrap LLM calls, unblocks MCP plan/draft tools |
| P2 | #3 (GICS pre-check) | Add Node.js check + better error surfacing |
| P2 | #9 (trust default) | Unify 0.85 default in TrustEngine |
| P2 | #8 (team_config content check) | Better error message + fallback |
| P3 | #10, #11, #12 | API completeness — missing routes and param fixes |
