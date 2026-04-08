# GIMO E2E R18 — Root Cause Analysis (Phase 2)

**Date**: 2026-04-08
**Round**: R18
**Phase**: 2 (Root Cause Analysis)
**Input**: [`E2E_AUDIT_LOG_20260408_R18.md`](./E2E_AUDIT_LOG_20260408_R18.md)
**Investigation method**: 4 parallel Explore subagents (read-only) + main session forensic verification of bytecode-vs-source mtimes against running PID.

---

## 0. Meta-finding (RUNTIME VERIFICATION GATE FAILURE)

> **The live GIMO server (PID 30472) is running pre-Cluster-D bytecode.** R17 claimed "Server restarted at 22:48 UTC" in its smoke-test section. The live `gimo_get_server_info` reports `Started : 2026-04-07T22:19:14.426183+00:00`. **The restart never happened — or restarted a different process.** Every R17 source-level fix that landed AFTER 22:19:14Z is invisible to the operator that connects to PID 30472.

| Artefact | Epoch | Δ vs server start (1775600354) |
|---|---|---|
| `gimo_server` PID 30472 boot | 1775600354 | 0 (reference) |
| `tools/gimo_server/main.py` mtime | 1775600444 | **+90 s** |
| `tools/gimo_server/services/gics_service.py` mtime | 1775600479 | **+125 s** |
| `tools/gimo_server/routers/ops/dependencies_router.py` mtime | 1775600479 | **+125 s** |
| `tools/gimo_server/services/agentic_loop_service.py` mtime | 1775600479 | **+125 s** |
| Commit `ec11c27` (Cluster A) | 1775600466 | +112 s |
| Commit `2c73e13` (Cluster B + C) | 1775600519 | +165 s |
| Commit `b8c7c22` (Cluster D — Pydantic-driven schemas) | 1775600542 | **+188 s** |
| Commit `bf0fcd5` (Cluster E.1 + E.2) | 1775600580 | +226 s |
| `tools/gimo_server/mcp_bridge/governance_tools.py` mtime | 1775603917 | **+3 563 s** |
| Commit `e7b3c68` (R17.1 peer-review) | 1775604141 | +3 787 s |
| `tools/gimo_server/mcp_bridge/native_tools.py` mtime | 1775604662 | **+4 308 s** |
| Commit `f53faad` (R17.2) | 1775604692 | +4 338 s |

**Conclusion**: every byte of R17 Cluster A/B/C/D/E and R17.1/R17.2 source-level work landed AFTER the running process loaded its modules. The .pyc cache files have been re-emitted by editor saves but the live process never re-imported them. R17's claim of `5/5 SMOKE_PASS` was tested against this same pre-fix process; the smoke test is also invalid retroactively.

This single fact alone reclassifies several R18 issues from "real bugs" to "runtime verification failures" — but it does not absolve them: a fix that requires a bounce to take effect, in a system whose primary value proposition is *ambient governance*, is a fix that ships broken. Issues #R18-1 and the schema-drift portion of #R18-2 fall in this category.

---

## 1. Issue Map

| ID | Severity | Category | Root cause type | Root cause symbol(s) | Confidence |
|---|---|---|---|---|---|
| #R18-1 | BLOCKER | bridge / runtime-stale | Stale process: source-correct, in-memory function loaded pre-Cluster-D | `mcp_bridge/governance_tools.py::gimo_estimate_cost` (source OK, runtime stale) | HIGH |
| #R18-2a | BLOCKER | bridge / runtime-stale | Same as #R18-1 for `gimo_verify_proof_chain` and `gimo_generate_team_config` | `mcp_bridge/governance_tools.py::gimo_verify_proof_chain`, `mcp_bridge/native_tools.py::gimo_generate_team_config` (source OK, runtime stale) | HIGH |
| #R18-2b | BLOCKER | bridge / source-real | R17 never added Pydantic models for `gimo_run_task` and `gimo_propose_structured_plan` — they remain pure-required `task_instructions` and the operator cannot guess the param name | `mcp_bridge/native_tools.py::gimo_run_task`, `mcp_bridge/native_tools.py::gimo_propose_structured_plan` | HIGH |
| #R18-3a | BLOCKER | observability / runtime-stale | `dependencies_router.py` enrichment exists in source but the running process loaded the pre-Cluster-C version | `routers/ops/dependencies_router.py::list_system_dependencies` (source OK, runtime stale) | HIGH |
| #R18-3b | BLOCKER | observability / source-real | `gimo_get_gics_insight` MCP tool routes through `SagpGateway.get_gics_insight` which never consults `last_start_failure`. Only the HTTP path was wired in R17 Cluster C; the MCP path was forgotten | `services/sagp_gateway.py::SagpGateway.get_gics_insight` | HIGH |
| #R18-4 | BLOCKER | governance gap / source-real | `gimo_spawn_subagent` creates a `SubAgent` in `~/.orch_data/runtime/sub_agents.json` via `SubAgentManager.create_sub_agent` and returns its `uuid4`. No `OpsRun` is created, no `gimo_evaluate_action` is invoked, no proof entry, no route at `/ops/subagents/{id}`, and the inventory namespace is invisible to `OpsService.list_runs` | `mcp_bridge/native_tools.py::gimo_spawn_subagent`, `services/sub_agent_manager.py::SubAgentManager.create_sub_agent`, `services/sub_agent_manager.py::INVENTORY_FILE` | HIGH |
| #R18-5 | CRITICAL | observability / source-real | The chat / agentic-loop path calls the provider adapter bare (no telemetry middleware) and wraps `ObservabilityService.record_llm_usage` in a `try / except Exception: logger.debug(...)` that silently swallows. R17 Cluster A only re-attached cost / OTel / heartbeat to the **pipeline-stage** path (`engine_service.py`), not to `agentic_loop_service.py` | `services/agentic_loop_service.py::AgenticLoopService._run_loop` (record_llm_usage call site + silent except), `services/agentic_loop_service.py::AgenticLoopService._calculate_usage_cost` (local-only) | HIGH |
| #R18-6 | INCONSISTENCY | governance / source-real | Three independent readers: (a) `SagpGateway._get_trust_score` returns seeded `0.85` defaults without consulting storage; (b) `TrustEngine.dashboard` builds records ONLY from persisted events and returns `[]` if none; (c) CLI `trust status` uses `unwrap="entries"` and falls into `empty_msg` when count==0. No unified state reader; the R17 Cluster E.1 unification was envelope-only | `services/sagp_gateway.py::SagpGateway._get_trust_score`, `services/trust_engine.py::TrustEngine.dashboard`, `gimo_cli/render.py::TRUST_STATUS` | HIGH |
| #R18-7 | CRITICAL | chat loop / source-real | Two compounding bugs: (1) the codex-account adapter (`providers/cli_account.py::_raw_chat_with_tools`) returns the raw model text *as well as* the parsed `tool_calls` array, and the parser `tool_call_parser.py::_parse_tool_calls_from_text` fails to strip the markdown-fenced block when `remaining_text` is whitespace-only — so `agentic_loop_service.py::_run_loop` appends BOTH a `text` item (markdown JSON) and a `tool_call` item; (2) the loop creates the tool_call item at `status="started"` and there is no code path that transitions it to `completed`/`error` for HITL tools (`ask_user`), because the loop breaks early at the HITL detection branch without calling `ConversationService.update_item_content` | `providers/cli_account.py::_raw_chat_with_tools`, `services/agentic_loop_service.py::tool_call_parser._parse_tool_calls_from_text`, `services/agentic_loop_service.py::AgenticLoopService._run_loop` (HITL break branch), `services/conversation_service.py::ConversationService.update_item_content` (never called) | HIGH |
| #R18-8 | CRITICAL | CLI / source-real | `gimo diff` CLI calls `GET /ops/files/diff?base=&head=` which runs `git diff <base> <head>` against committed state, NOT the workspace dirty tree. Help text says "Show backend diff summary for the active repository" — does not warn it is commit-based. Empty stdout from git → CLI fallback prints "[dim]No diff output.[/dim]" with zero diagnostic | `gimo_cli/commands/ops.py::diff`, `routers/ops/file_router.py::get_diff`, `services/git_service.py::GitService.get_diff` | HIGH |
| #R18-9 | FRICTION | CLI / source-real | `repo_router.py::_sanitize_path` regex `r"C:\\Users\\[^\\]+"` is broken: in Python re-syntax under a raw string, `\\Users\\` matches a literal `\Users\` ONCE, but the substitution `r"C:\\Users\\[USER]"` then re-emits `\Users\[USER]` — and the input path `C:\Users\shilo\…` is rendered with the captured prefix dropped, producing `C:\Users[USER]\Documents\…`. The regex eats the trailing backslash that should separate `[USER]` from the next path component | `routers/ops/repo_router.py::_sanitize_path` | HIGH |
| #R18-10 | FRICTION | CLI / source-real | `gimo_cli/commands/ops.py::graph` falls through to `console.print_json(data=payload)` when payload is a list, emitting raw `[[],[]]`. No graph renderer in `render.py` is registered for the graph response shape | `gimo_cli/commands/ops.py::graph`, `gimo_cli/render.py` (missing GRAPH spec) | HIGH |
| #R18-11 | FRICTION | architecture / by design | GIMO Skills is a separate API-managed subsystem persisted to `~/.orch_data/skills/*.json`. There is no bridge to `~/.claude/skills/`, `~/.cursor/extensions/`, or any OS-level skill registry. This is an architectural choice but the name collision with Claude / Cursor skills causes operator confusion | `services/skills_service.py::SkillsService.list_skills`, `services/skills_service.py::SKILLS_DIR` | MEDIUM (intent unclear — could be a feature or a gap) |

---

## 2. Detailed Traces

### #R18-1 — `gimo_estimate_cost` token args silently dropped

**Reported symptom**: every call returns `input_tokens:1000, output_tokens:500` regardless of input; response uses legacy keys instead of canonical `tokens_in`/`tokens_out`.

**Entry point**: `mcp__gimo__gimo_estimate_cost` MCP tool.

**Trace (source on disk)**:
```
mcp_bridge/server.py::_register_native
  → mcp_bridge/governance_tools.py::register_governance_tools
  → @mcp.tool() decorator on gimo_estimate_cost(model, tokens_in=1000, tokens_out=500)
  → body: EstimateCostInput(model, tokens_in, tokens_out)
  → CostService.calculate_cost(params.model, params.tokens_in, params.tokens_out)
  → returns json.dumps({..., "tokens_in": params.tokens_in, "tokens_out": params.tokens_out, ...})
```

**Trace (live runtime)**: returns `input_tokens` and `output_tokens` defaults `1000/500`. Independent re-call with `(2222, 3333)` returned `(1000, 500)` again with `total_cost_usd=0.0075` (which equals `2.5*1000/1e6 + 10.0*500/1e6` for `gpt-4o`, confirming the defaults).

**Root cause**: the running process holds the pre-Cluster-D version of `gimo_estimate_cost` which had legacy parameter names (`input_tokens` / `output_tokens`) and a different return shape. R17 Cluster D commit `b8c7c22` (epoch 1775600542) landed 188 seconds AFTER PID 30472 booted at 1775600354. The R17 smoke-test claim of "restarted at 22:48 UTC" is contradicted by `gimo_get_server_info.Started = 2026-04-07T22:19:14Z`. The fix is correct on disk but not loaded.

**Blast radius**: every R17 / R17.1 / R17.2 source change is invisible to MCP / HTTP / CLI clients. Of the 13 R17-resolved issues, **at least 6 verifications** in R18 §1 fail purely because the live process is stale: #R18-1, #R18-2a, #R18-3a (HTTP enrichment), and any test that touches `governance_tools.py` / `native_tools.py` / `dependencies_router.py` / `gics_service.py` / `agentic_loop_service.py` / `trust_router.py`.

**Fix options**:

| Option | Location | Change | Risk |
|---|---|---|---|
| A | operations | `python gimo.py down && python gimo.py up` and re-run R18 §1 against the new process | LOW (data loss only on in-memory ephemeral state) |
| B (recommended) | `tools/gimo_server/services/gics_service.py::GicsService.start_health_check` (or sibling) | Add a self-check at startup that compares the running module's bytecode hash to the on-disk source and refuses to report `healthy` if they diverge by more than N seconds — fail loud, not silent | MEDIUM (could trip on every editor save in dev mode; gate with `DEBUG=false`) |
| C | `tools/gimo_server/main.py::lifespan` | Run with `uvicorn --reload` in dev and require an explicit `python gimo.py reload` in prod that triggers a full process recycle, not a soft module re-import | LOW |

**Confidence**: HIGH.

---

### #R18-2a — `gimo_verify_proof_chain` and `gimo_generate_team_config` schema drift

Same root cause as #R18-1: the live process registered the MCP tool schemas at boot from the pre-Cluster-D function signatures. Both functions on disk now have optional parameters (`thread_id: str | None = None`, `plan_id: str | None = None`), and the FastMCP `@mcp.tool()` decorator introspects them via `inspect.signature` at decoration time. Because decoration happens during module import and import happens once at process boot, the schema is frozen at the pre-Cluster-D shape forever.

**Confidence**: HIGH. Restart resolves both.

### #R18-2b — `gimo_run_task` and `gimo_propose_structured_plan` were never given Pydantic models

**Trace**:
```
mcp_bridge/native_tools.py::gimo_propose_structured_plan(task_instructions: str)
mcp_bridge/native_tools.py::gimo_run_task(task_instructions: str, target_agent_id: str = "auto")
```

R17 Cluster D added `mcp_bridge/native_inputs.py` with three input models (`EstimateCostInput`, `VerifyProofChainInput`, `GenerateTeamConfigInput`). R17 explicitly listed those three tools as fixed. But it never added models for the `propose_structured_plan` and `run_task` siblings, so their schemas continue to expose `task_instructions` as a hard-required string with no aliasing. The operator (Claude, in this audit) tried `prompt`, `objective`, and `repo` — all rejected.

**Architectural pattern (CRITICAL)**: this is a *partial* version of the same root structural issue R17 supposedly fixed. R17 Cluster D treated three tools as the canonical examples and stopped. The remaining 19 native tools (per Agent 1's blast radius enumeration) have NO Pydantic source-of-truth and are vulnerable to identical drift the moment anyone touches their signatures.

**Fix options**:

| Option | Location | Change | Risk |
|---|---|---|---|
| A | `mcp_bridge/native_inputs.py` | Add `RunTaskInput`, `ProposeStructuredPlanInput` and update both function signatures to use canonical names + accept the operator's expected aliases via Pydantic `Field(..., alias="prompt")` | LOW |
| B (recommended) | `mcp_bridge/server.py::_register_native` | Replace per-tool hand registration with a generator that walks `native_inputs.py` and binds each `*Input` class to its tool by name. Make Pydantic the *literal* source of truth, not a parallel doc-only artefact | MEDIUM (one-time refactor; eliminates the entire drift class) |

**Confidence**: HIGH.

---

### #R18-3a — `/ops/system/dependencies` enrichment missing at runtime

**Trace (source on disk)**:
```
routers/ops/dependencies_router.py::list_system_dependencies
  → ProviderService.list_cli_dependencies() → {"items": [...], "count": N}
  → gics = getattr(request.app.state, "gics", None)
  → failure = getattr(gics, "last_start_failure", None) if gics else None
  → if failure: data["gics_failure_reason"] = failure.reason
  →            data["gics_failure_message"] = failure.message
  →            data["gics_failure_detail"] = failure.detail
```

**Trace (live runtime)**: response is `{"items":[3 cli binaries],"count":3}` with no `gics_failure_*` keys.

**Root cause**: same staleness as #R18-1. `dependencies_router.py` mtime is 125 s after server boot. The router enrichment that R17 Cluster C added is not in the loaded module.

### #R18-3b — `gimo_get_gics_insight` MCP path is independent and was never wired

**Trace**:
```
mcp_bridge/governance_tools.py::gimo_get_gics_insight
  → SagpGateway.get_gics_insight(prefix=..., limit=...)
  → services/sagp_gateway.py::SagpGateway.get_gics_insight
       gics = StorageService._shared_gics
       if gics is None:
           return {"entries": [], "count": 0, "error": "GICS not initialized"}
       ...
```

This path **never** consults `app.state.gics.last_start_failure`. R17 Cluster C wired the dependencies_router but forgot the SagpGateway path that the MCP tool actually uses. Even after a restart fixes #R18-3a, the operator's first instinct (call `gimo_get_gics_insight`) will still see `error: "GICS not initialized"` with no reason.

**Confidence**: HIGH.

**Fix**: thread `last_start_failure` through `SagpGateway.get_gics_insight` and into the response, returning `{"entries": [], "count": 0, "error": "GICS not initialized", "failure_reason": failure.reason, "failure_detail": failure.detail}`.

**Parallel observation (cosmetic)**: `tools/gimo_server/mcp_bridge/native_tools.py::gimo_get_status` returns the literal string `"Engine: RUNNING\nOllama: CONNECTED\nBackend-API: UP"`. There is no GICS line. R17 added a `_get_gics_health()` helper in `sagp_gateway.py` (per Agent 2) but only consumed it from `gimo_get_governance_snapshot`. The operator-facing status string still hides GICS entirely.

---

### #R18-4 — `gimo_spawn_subagent` is a governance black hole

**Trace**:
```
mcp_bridge/native_tools.py::gimo_spawn_subagent(name, task)
  → services/sub_agent_manager.py::SubAgentManager.create_sub_agent(name, task)
  → SubAgent(id=uuid4(), name, task, ...) persisted to
    services/sub_agent_manager.py::INVENTORY_FILE = ops_data_dir.parent / "runtime" / "sub_agents.json"
  → returns f"Spawned: {agent.id} (provider=auto, model=auto, policy=workspace_safe)"
```

**Critical absences**:
- No call to `OpsService.create_run` or any sibling.
- No call to `SagpGateway.evaluate_action` or any governance gate.
- No proof chain entry, no audit log entry, no GICS telemetry write.
- No HTTP route exposes `~/.orch_data/runtime/sub_agents.json`. There is no `/ops/subagents/{id}`. There is no `/ops/agents/{id}`. The inventory namespace is operator-invisible.
- The "policy=workspace_safe" in the return string is a string literal, not the result of any policy lookup.

**Architectural verdict**: `gimo_spawn_subagent` is a **fire-and-forget worker creator with no governance**. It violates the principal invariant of GIMO ("the operator can prove that worker actions traversed the same gates"). For Probe B, this single bug makes the recursive-governance probe **structurally impossible** to validate, regardless of which provider is configured.

**Blast radius**: any operator workflow that tries to delegate via `gimo_spawn_subagent` is operating without governance. If sub-agents themselves have execute privileges, this is a **policy bypass** by construction.

**Fix options**:

| Option | Location | Change | Risk |
|---|---|---|---|
| A | `mcp_bridge/native_tools.py::gimo_spawn_subagent` | Wrap the spawn with a `SagpGateway.evaluate_action(tool_name="spawn_subagent", payload=...)` precondition; persist a proof entry on success | LOW |
| B | `services/sub_agent_manager.py::SubAgentManager.create_sub_agent` | Additionally create an `OpsRun` row keyed by the same `uuid4` so `/ops/runs/{id}` resolves; expose `/ops/subagents/{id}` for the inventory side | MEDIUM |
| C (recommended) | both above + delete `SubAgentManager` as a separate namespace | Collapse subagents into the existing run/draft pipeline. A "subagent" becomes a child run with `parent_run_id`. Reuse all of R17 Cluster A's heartbeat / status / proof plumbing instead of running a parallel namespace | HIGH (refactor; touches sub_agent_manager, native_tools, ops_service, run_router) but ELIMINATES the entire bug class permanently |

**Confidence**: HIGH.

---

### #R18-5 — Chat-path observability bypass

**Trace**:
```
mcp_bridge/native_tools.py::gimo_chat(message, ...)
  → services/conversation_service.py creates user turn
  → services/agentic_loop_service.py::AgenticLoopService._run_loop
       → adapter = providers/cli_account.py::CliAccountAdapter
       → llm_result = await adapter.chat_with_tools(messages, tools, ...)   ## NO TELEMETRY WRAPPING
       → iteration_cost = cls._calculate_usage_cost(model, usage)            ## LOCAL-ONLY
       → total_cost += iteration_cost                                        ## LOCAL-ONLY
       → (much later)
       → try:
       →     ObservabilityService.record_llm_usage(thread_id, model, usage, cost, ...)
       → except Exception:
       →     logger.debug("record_llm_usage failed", exc_info=True)         ## SILENT
```

Compare with the pipeline path (R17 Cluster A):
```
services/execution/engine_service.py::EngineService._execute_stage
  → wraps each provider call with cost record + OTel span + heartbeat
  → SSE event emission per iteration
  → iteration_cost / cumulative_cost streamed to operator
```

**Two distinct bugs**:

1. **Silent failure of `record_llm_usage`** — the `try / except Exception: logger.debug(...)` swallows any failure. If `ObservabilityService` import fails, if the thread doesn't exist, if `ConversationService.mutate_thread` fails, the entire telemetry record is dropped with no warning to the operator and no error counter increment. Default `logger.debug` is below the default log level, so even ops-side debugging cannot find it.
2. **No telemetry middleware around the provider call** — even if `record_llm_usage` were wired correctly, OTel spans, SSE cost events, and `record_model_outcome()` (GICS reliability) are NOT emitted by the chat path. R17 Cluster A added these to `engine_service.py` only.

**Why R17 missed this**: R17 Cluster A's diagnosis was "the run pipeline was hollow" and the fix was scoped to the run pipeline. The chat / agentic-loop path is a sibling code path that produces real LLM completions but is treated as "out of band" by the observability pipeline. R17's smoke test (#1 + #5) only exercised draft → approve → run, which routes through `engine_service.py`. It never sent a chat message.

**Fix options**:

| Option | Location | Change | Risk |
|---|---|---|---|
| A | `agentic_loop_service.py::_run_loop` | Replace `try/except: logger.debug` with `try/except Exception as e: logger.error(...); raise` (loud failure) | LOW |
| B | `agentic_loop_service.py::_run_loop` | Wrap the `adapter.chat_with_tools` call with the same telemetry middleware used by the pipeline path | MEDIUM (factor out the middleware) |
| C (recommended) | new `services/observability/llm_call.py::record_llm_call` context manager | Create one `async with` decorator that records usage + emits OTel span + records GICS outcome + emits SSE. Use it from BOTH `engine_service.py` and `agentic_loop_service.py`. Then any future code path that calls a provider is required to use the wrapper | LOW + permanent |

**Confidence**: HIGH.

---

### #R18-6 — Trust trifurcation across MCP / HTTP / CLI

**Three readers, three sources of truth**:

```
A. MCP    : mcp_bridge/governance_tools.py::gimo_get_trust_profile
            → services/sagp_gateway.py::SagpGateway._get_trust_score(dimension)
            → returns SEEDED DEFAULT 0.85 if no events
            → never consults TrustEngine.dashboard

B. HTTP   : routers/ops/trust_router.py::trust_dashboard
            → services/trust_engine.py::TrustEngine(storage.trust)
            → engine.dashboard(limit=...)
            → engine._build_records() reads storage.trust.list_trust_events()
            → returns [] when no events
            → wrap envelope: {"entries": [], "items": [], "count": 0}

C. CLI    : gimo_cli/commands/trust.py::trust_status
            → calls /ops/trust/dashboard
            → render_response(payload, gimo_cli/render.py::TRUST_STATUS, ...)
            → TRUST_STATUS.unwrap = "entries"; empty_msg = "No trust data yet."
```

R17 Cluster E.1 unified the *envelope* (added `entries` alongside `items`) but did not unify the *semantics*. The MCP tool reads from a different store than the HTTP endpoint. The CLI reports "no data" while the MCP reports `0.85` defaults. There is no canonical answer to "what does GIMO think the trust state is?".

**Architectural pattern**: GIMO has two trust state stores — `SagpGateway`'s seeded defaults (from when there were no events) and `TrustEngine`'s persisted events table — and they were never reconciled. Cluster E.1 treated this as a *display* problem (envelope key) when it was a *semantic* problem (which store is canonical?).

**Fix options**:

| Option | Location | Change | Risk |
|---|---|---|---|
| A | `services/trust_engine.py::TrustEngine.dashboard` | Make `dashboard()` always return the seeded `provider/model/tool` rows with their effective scores (consulting `SagpGateway` for the default when there are no events) | LOW |
| B (recommended) | `services/sagp_gateway.py::SagpGateway._get_trust_score` | Delete the seeded-default code path and route through `TrustEngine.profile(dimension)`. There must be exactly one source of truth | MEDIUM (touches sagp_gateway, governance_tools, governance_snapshot) |
| C | `gimo_cli/render.py::TRUST_STATUS` | Treat `entries==[]` AND `count==0` AND `provider==0.85` as a special "fresh install" rendering with seeded defaults shown explicitly. UI hack for the underlying data divergence | LOW (cosmetic only — does not solve the divergence) |

**Confidence**: HIGH.

---

### #R18-7 — Chat tool-call double-emit and `started` hang

**Two compounding bugs**:

**Bug 1: codex CLI provider returns markdown-fenced JSON in `content` AND parsed `tool_calls`.**

```
providers/cli_account.py::_raw_chat_with_tools
  → raw_content = (codex CLI stdout)
  → remaining_text, tool_calls = tool_call_parser._parse_tool_calls_from_text(raw_content)
  → return {
       "content": remaining_text or raw_content,   ## << BUG: falls back to RAW
       "tool_calls": tool_calls,
       "tool_call_format": "parsed_json_in_text",
    }
```

`tool_call_parser._parse_tool_calls_from_text` extracts the markdown-fenced JSON and removes it from `remaining_text`. But for inputs where the entire model output IS the markdown block, `remaining_text` becomes whitespace-only or empty. Python truthiness then makes the `or raw_content` branch fire, restoring the markdown. Both `content` (with markdown) and `tool_calls` (parsed) are now returned.

**Bug 2: `agentic_loop_service.py::_run_loop` appends both items and never closes the tool_call.**

```
if content:
    ConversationService.append_item(thread_id, orch_turn.id,
        GimoItem(type="text", content=content, status="completed"))   ## markdown text
for call in tool_calls:
    ConversationService.append_item(thread_id, orch_turn.id,
        GimoItem(type="tool_call",
                 content=json.dumps(call.arguments),
                 status="started",                                    ## STARTED, never updated
                 metadata={"tool_name": call.name, "tool_call_id": call.id, "risk": ...}))
    if call.name == "ask_user":
        # HITL: break the loop and wait for operator response
        break    ## << BUG: tool_call item still at status=started
```

For HITL tools (`ask_user`, `human_approval`), the loop breaks at the HITL detection branch without ever calling `ConversationService.update_item_content` to transition the tool_call to `awaiting_user` / `completed_pending` / similar. The item is frozen at `started` and the operator UI cannot tell whether it succeeded, is in progress, or is waiting for them.

**Why R17 missed this**: R17 Cluster B added `hollow_completion_error` for the *empty content + no tool calls* branch, but the *content + tool_calls* branch with HITL was not in scope. The contract test added in R17 only covers the hollow case.

**Fix options**:

| Option | Location | Change | Risk |
|---|---|---|---|
| A | `providers/cli_account.py::_raw_chat_with_tools` | Replace `remaining_text or raw_content` with `remaining_text if tool_calls else raw_content`. If we successfully parsed tool calls, trust the parser and emit the (possibly empty) remaining text instead of falling back to the raw block | LOW |
| B | `services/agentic_loop_service.py::_run_loop` | At the HITL break branch, before `break`, set the tool_call item's status to `awaiting_user` via `ConversationService.update_item_content` (or a sibling that updates only the status). Add a `tool_call_lifecycle` invariant test | LOW |
| C (recommended) | both above | Both fixes are minimal and orthogonal; together they remove the double-emit AND the lifecycle bug | LOW |

**Confidence**: HIGH.

---

### #R18-8 — `gimo diff` is commit-scoped, not workspace-scoped

**Trace**:
```
gimo_cli/commands/ops.py::diff
  → api_request("GET", "/ops/files/diff", params={"base": base, "head": head})
  → routers/ops/file_router.py::get_diff
  → services/git_service.py::GitService.get_diff(base_dir, base, head)
  → subprocess git diff <base> <head>
  → if stdout empty: CLI prints "[dim]No diff output.[/dim]"
```

**Root cause**: `gimo diff` runs `git diff <base> <head>` between two commits. Workspace uncommitted changes are NOT in either commit, so they are invisible. The CLI help text reads "Show backend diff summary for the active repository" with no mention of "committed only". For an operator who just edited files, the silent "No diff output" is misleading.

**Fix options**:

| Option | Location | Change | Risk |
|---|---|---|---|
| A | `gimo_cli/commands/ops.py::diff` | Add `--workspace` flag that passes `base=HEAD&head=` (working tree). Default remains commit-based for backwards compat but the help text documents the scoping clearly | LOW |
| B (recommended) | `services/git_service.py::GitService.get_diff` + `routers/ops/file_router.py::get_diff` | Accept a `scope: Literal["commits","workspace","staged"]` parameter. The CLI surfaces all three. The default becomes `workspace` because that matches operator intuition; commit-scoped becomes opt-in | MEDIUM (contract change on the file_router) |

**Confidence**: HIGH.

---

### #R18-9 — Repos path redactor regex

**Trace**:
```
routers/ops/repo_router.py::_sanitize_path
  path_str = re.sub(r"C:\\Users\\[^\\]+", r"C:\\Users\\[USER]", path_str)
```

**Bug**: in a Python raw string, `\\` is two characters and the regex engine interprets it as one literal backslash. `\\Users\\` matches literal `\Users\`. The character class `[^\\]+` consumes everything up to the next backslash. So for input `C:\Users\shilo\Documents\…` the match is `C:\Users\shilo`. The substitution then writes `C:\Users\[USER]` — but the trailing `\Documents\…` remains, AND the closing backslash of `\Users\` was eaten by the match. Net result: `C:\Users[USER]\Documents\…` (the slash between `Users` and `[USER]` is gone).

**Fix**: `re.sub(r"C:\\Users\\([^\\]+)", r"C:\\Users\\[USER]", path_str)` — keep the trailing structure or use a non-consuming look-ahead. Trivial.

**Confidence**: HIGH.

---

### #R18-10 — `gimo graph` raw JSON

**Trace**: `gimo_cli/commands/ops.py::graph` calls `console.print_json(data=payload)` for any list/dict response. `/ops/graph` returns `[[],[]]` when there is no graph data. There is no `GRAPH` `TableSpec` or renderer in `gimo_cli/render.py`.

**Fix**: add a graph renderer (Rich tree, or a `[dim]No graph data[/dim]` empty-state message) and route the response through it.

**Confidence**: HIGH.

---

### #R18-11 — Skills concept divergence

**Trace**: `services/skills_service.py::SkillsService.list_skills` reads from `services/skills_service.py::SKILLS_DIR = OPS_DATA_DIR / "skills"` (i.e. `~/.orch_data/skills/*.json`). The R18 vehicle's `e2e` skill lives at `~/.claude/skills/e2e/skill.md`, which is the Claude Code skill registry — completely separate. GIMO has no concept of "skill installed at the operator surface".

**Verdict**: this is more an *architectural ambiguity* than a bug. GIMO Skills (API-managed) and Claude/Cursor skills (filesystem-managed) are different things that share a name. The fix is either to rename ("playbooks"?) or to bridge. The latter is much harder because Claude / Cursor / Windsurf each have different skill formats.

**Confidence**: MEDIUM (intent unclear).

---

## 3. Systemic Patterns

### Pattern A — Runtime verification gate failure (META)

> Source-correct fixes verified by tests in CI but never reloaded into the running process pass the audit only as long as the auditor reads the source code. The moment the auditor connects to the live process, the fix is invisible.

**Affected issues**: #R18-1, #R18-2a, #R18-3a, and parts of #R18-7 verification.
**Future failure mode**: every R(N) implementation report that does not include a process-restart proof + bytecode-vs-source mtime check is suspect by construction.
**Eradication**: enforce process bounce + version tag + first-call replay in Phase 4 Step 1.5 with automated assertions, not optional manual smoke tests.

### Pattern B — Bridge layer ↔ inner service drift (R17 Cluster D regression class)

> R17 introduced Pydantic models inside `mcp_bridge/native_inputs.py` as the alleged single source of truth, but `FastMCP.@mcp.tool()` introspects the function signature directly via `inspect.signature` at decoration time. The Pydantic models are runtime *validators*, not schema *generators*. Any signature change must be hand-mirrored in three places (signature, Pydantic model, callers).

**Affected issues**: #R18-2b (real source bug), conceptually present in 19 other native tools that have no Pydantic model at all.
**Future failure mode**: every signature edit on a native tool risks drift. The next contributor who renames `task_instructions` to `prompt` on `gimo_run_task` will silently break every operator that already learned the old name.
**Eradication**: Option B above — generate `@mcp.tool()` registrations from the Pydantic models, not from raw function signatures.

### Pattern C — Two parallel paths for "the same thing", one telemetry-wrapped, one bare

> #R18-3a/3b (HTTP `/ops/system/dependencies` vs MCP `gimo_get_gics_insight`) and #R18-5 (pipeline `engine_service.py` vs chat `agentic_loop_service.py`) share a topology: a feature is added to one path and the sibling path is forgotten. R17's diagnosis was always "the path I tested is broken"; the fix landed only on that path.

**Affected issues**: #R18-3, #R18-5, #R18-6 (trust three-way), parts of #R18-1 (HTTP + MCP both serve the same data).
**Future failure mode**: any new observability or governance feature added to one of the three surfaces (MCP / HTTP / CLI) is silently absent on the other two. The "single source of truth" claim in CLIENT_SURFACES.md is fictional.
**Eradication**: route all reads through one canonical service (e.g. `services/state_service.py::StateService.dependencies()`, `.gics_insight()`, `.trust()`) that all three surfaces consume verbatim. Surfaces become thin renderers, never data computers.

### Pattern D — Governance is opt-in instead of unconditional

> `gimo_spawn_subagent` (#R18-4) creates a worker entirely outside the gate. The chat path (#R18-5) emits LLM completions outside the cost recorder. The diff command (#R18-8) reads workspace state outside the policy gate. The operator can call any of these and bypass governance — by mistake, not by malice.

**Affected issues**: #R18-4, #R18-5, several lurking ones.
**Future failure mode**: a security audit will find that "GIMO governance" only applies to draft → approve → run, not to any sibling code path. The product's value proposition collapses.
**Eradication**: at the architecture level, every callsite that talks to a provider, the filesystem, or a subagent must traverse `SagpGateway.evaluate_action`. Make it impossible to call a provider without a gate by introducing a `services/providers/protected_adapter.py::ProtectedAdapter` that wraps every adapter with a mandatory gate call. Delete the unprotected adapters.

---

## 4. Issue Dependency Graph

```
META (Pattern A — runtime stale)
  ├── #R18-1 (estimate_cost)            ← restart fixes
  ├── #R18-2a (verify/team_config)      ← restart fixes
  └── #R18-3a (deps router)             ← restart fixes (HTTP path)

Pattern B (bridge drift)
  └── #R18-2b (run_task / propose)      ← real source bug, fix native_inputs.py + registration generator

Pattern C (parallel paths)
  ├── #R18-3b (gics MCP path)           ← real source bug, wire SagpGateway
  ├── #R18-5  (chat observability)      ← real source bug, ProtectedAdapter
  └── #R18-6  (trust trifurcation)      ← real source bug, single TrustEngine reader

Pattern D (opt-in governance)
  ├── #R18-4  (spawn black hole)        ← real source bug, fold into runs
  └── #R18-5  (chat bypasses cost gate) ← shares root with Pattern C

Independent
  ├── #R18-7  (chat tool-call lifecycle) ← real source bug, two-line fix
  ├── #R18-8  (diff scope)              ← real source bug or doc bug
  ├── #R18-9  (repos redactor regex)    ← real source bug, two-char fix
  ├── #R18-10 (graph renderer)          ← real source bug, missing renderer
  └── #R18-11 (skills concept)          ← architectural ambiguity, defer
```

---

## 5. Recommended Fix Priority Ordering

| Priority | Issue | Reason |
|---|---|---|
| **P0** | META (Pattern A) — restart the server, version-tag the boot, gate `healthy` on bytecode-vs-source freshness | Without this, half the R18 issues recur on every audit. Also: re-running R18 §1 against the freshly-booted process is the only way to know which issues are runtime-stale and which are real source bugs |
| **P0** | #R18-4 (spawn governance black hole) | Architectural invariant violation. Any moment the operator uses `gimo_spawn_subagent`, governance is bypassed. This is the single most damaging issue in R18 |
| **P1** | #R18-5 (chat observability bypass) | Same Pattern D problem with a slightly smaller blast radius. Makes "cost tracking" a polite fiction for any chat interaction |
| **P1** | #R18-2b + Pattern B fix (Pydantic-driven registration) | Eliminates the entire schema-drift class once and for all, retroactively fixes the runtime-stale class as a side effect |
| **P1** | #R18-3b (gics MCP path) | Operator's first-look diagnostic command lies about the system state |
| **P1** | #R18-6 (trust trifurcation) | Three answers to the same question is worse than zero answers. Operator cannot trust the trust system |
| **P2** | #R18-7 (chat tool-call lifecycle + double-emit) | Two-place fix; no architectural change needed. Quality-of-life critical for any HITL flow |
| **P2** | #R18-8 (diff scope) | Doc fix + optional `--workspace` flag |
| **P3** | #R18-9 / #R18-10 (CLI friction) | One-line fixes |
| **DEFER** | #R18-11 (skills naming) | Architectural ambiguity. Decide direction first |

---

## 6. Confidence Posture

Of the 13 issues traced above:
- **9 HIGH-confidence root causes** with concrete fix options.
- **1 MEDIUM-confidence** (#R18-11 — intent unclear).
- **0 LOW / DEFERRED** (the sub-bugs of #R18-3 split into 3a/3b and #R18-5 split into "silent except" + "no middleware" are all HIGH).

The Phase 1 trajectory (R17 → R18 accuracy = 30.8 %) is fully explained by the META finding: R17's "smoke gate 5/5 PASS" was tested against a process that did not contain the code R17 added. The accuracy score is real. The credibility tag stays on R17.

---

🤖 Phase 2 — read-only forensic. No code modified. No runtime state mutated.
