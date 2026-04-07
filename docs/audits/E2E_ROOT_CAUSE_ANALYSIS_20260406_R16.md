# E2E Root-Cause Analysis — R16

**Date**: 2026-04-06
**Round**: 16
**Input document**: E2E_AUDIT_LOG_20260406_R16.md
**Method**: Exhaustive code tracing with parallel subagent investigation

---

## Issue Map Table

| ID | Category | Root Cause Location | Confidence |
|----|----------|-------------------|------------|
| #1 | Pipeline Architecture | `engine_service.py::execute_run` + `cli_account.py::generate` | HIGH |
| #2 | CLI UX / Timeout | `chat_cmd.py::chat` + `plan.py::plan` + `api.py::smart_timeout` | HIGH |
| #3 | GICS Infrastructure | `vendor/gics/dist/src/cli/commands.js::daemonStart` (~L909) | HIGH |
| #4 | MCP Bridge / Timeout | `native_tools.py::gimo_chat` + MCP stdio timeout | HIGH |
| #5 | Trust Engine / Surface Parity | `sagp_gateway.py::_get_trust_score` (~L215) | HIGH |
| #6 | Adapter Design | `cli_account.py::generate` (~L202-209) | HIGH |
| #7 | MCP Bridge / Parsing | `native_tools.py::gimo_run_task` (~L311-319) | HIGH |
| #8 | Data Model Mismatch | `native_tools.py::gimo_generate_team_config` (~L667) | HIGH |
| #9 | OpenTelemetry Config | `opentelemetry.sdk.metrics` file exporter | MEDIUM |
| #10 | Pipeline Instrumentation | `engine_service.py::execute_run` + `ops_service.py::append_log` | HIGH |
| #11 | Trust Engine Logic | Same root as #5 — `sagp_gateway.py::_get_trust_score` | HIGH |

---

## Detailed Traces

### [#1] Run Pipeline Hollow Completion

**Reported symptom**: Run `r_1775511392866_da154b` transitions `running → done` in ~68s with `stage:null`, `heartbeat_at:null`, `tokens_total:0`, no files created.

**Entry point**: `gimo_approve_draft` → `POST /ops/drafts/{id}/approve?auto_run=true`

**Trace**:
```
→ run_router.py::approve_draft (~L118) — creates approval + run, calls _spawn_run()
→ run_router.py::_spawn_run (~L27) — spawns EngineService.execute_run() via SupervisedTask
→ engine_service.py::execute_run (~L237) — loads draft context, injects approved_id
→ engine_service.py::execute_run (~L322-353) — infers composition = "legacy_run"
    (no explicit execution_mode, no custom_plan, no multi_agent, no parent_run_id,
     no structured, no target_path → fallback to "legacy_run")
→ engine_service.py::_COMPOSITION_MAP["legacy_run"] (~L176-181):
    [PolicyGate, RiskGate, LlmExecute, Critic]
→ pipeline.py::run (~L35) — executes stages sequentially

  Stage 1: policy_gate.py::execute (~L13)
    → context has "approved_id" → returns status="continue", gate_skipped=True

  Stage 2: risk_gate.py::execute (~L16)
    → context has "approved_id" → returns status="continue", gate_skipped=True

  Stage 3: llm_execute.py::execute (~L13)
    → gets prompt from context.get("prompt") ✅
    → calls ProviderService.static_generate(prompt, context)
      → service_impl.py::static_generate (~L730)
        → resolves effective_provider = "codex-account"
        → _build_adapter() returns CliAccountAdapter(binary="codex")
        → adapter_registry.py::build_provider_adapter (~L23): codex + account → CliAccountAdapter
        → cli_account.py::generate (~L152)
          → builds cmd: ["codex", "exec", "", "--json"] (stdin_mode=True on Windows)
          → runs subprocess.run(" ".join(cmd), input=prompt_bytes, timeout=300, shell=True)
          → WAITS up to 300s for codex CLI to complete
          → codex runs, processes prompt via ChatGPT subscription
          → returns exit code 0 with JSONL output
          → _parse_codex_jsonl() extracts content
          → **RETURNS {content: "...", usage: {prompt_tokens: 0, completion_tokens: 0}}**
    → LlmExecute gets response with content
    → returns status="continue", artifacts={llm_response, content, usage}

  Stage 4: critic.py::execute (~L8)
    → gets content from input.artifacts["content"]
    → calls CriticService.review_output(content)
    → returns status="continue"

→ pipeline.py::run: all stages returned "continue" → no failure
→ engine_service.py::execute_run (~L375): final_status = "done"
→ OpsService.update_run_status(run_id, "done", msg="Pipeline completed successfully")
```

**Root causes (3 interlocking)**:

1. **`legacy_run` composition has NO FileWrite stage** (`engine_service.py::_COMPOSITION_MAP`, L176-181). The LLM generates content, the Critic reviews it, but nothing writes the output to disk. Compare with `file_task` (L170-174) and `agent_task` (L201-209), which include `FileWrite`. The `legacy_run` pipeline was designed for generation-only evaluation, not for code creation tasks.

2. **CliAccountAdapter returns `prompt_tokens: 0, completion_tokens: 0`** (`cli_account.py::generate`, L202-209). CLI tools (codex, claude) don't report token usage. The adapter hardcodes zeros. This makes cost tracking structurally impossible for CLI-based providers.

3. **Run status doesn't track `stage` or `heartbeat`** during execution. `execute_run()` never calls `OpsService.update_run_status()` with stage transitions during the pipeline. The `stage` and `heartbeat_at` fields remain null throughout.

**Blast radius**: Every run using a CLI adapter with `legacy_run` composition will produce this hollow completion pattern. This affects all `codex-account` and `claude-account` operations that don't explicitly set `execution_mode`.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `engine_service.py::execute_run` | Auto-detect task type: if prompt describes file creation, use `file_task` composition instead of `legacy_run` | Medium — heuristic could misclassify |
| B (recommended) | `engine_service.py::_COMPOSITION_MAP["legacy_run"]` | Add `FileWrite` stage after `Critic` | Low — FileWrite checks if there's content to write |
| C | Draft creation endpoint | Set `execution_mode: "file_task"` when draft prompt contains file-creation intent | Low — requires intent classification |

**Confidence**: HIGH

---

### [#2] CLI plan and chat Commands Produce Zero Output

**Reported symptom**: `gimo plan "..." --no-confirm` and `gimo chat -m "..."` produce zero bytes to stdout/stderr for 30+ seconds.

**Entry point**: `gimo_cli/commands/plan.py::plan` and `gimo_cli/commands/chat_cmd.py::chat`

**Trace for `gimo plan`**:
```
→ plan.py::plan (~L22) — builds request to POST /ops/generate-plan-stream
→ plan.py (~L61): url = f"{base_url}/ops/generate-plan-stream"
→ plan.py (~L62): sends request with read=180.0 timeout
→ plan.py (~L65): console.status("Planning...") spinner active
→ Server: plan_router.py::generate_plan_stream (~L358) — returns StreamingResponse(event_generator())
→ event_generator() emits 3 progress SSE events:
    "analyzing_prompt" (10%), "building_context" (20%), "calling_llm" (40%)
→ event_generator (~L486): resp = await ProviderService.static_generate(sys_prompt, context)
    → **BLOCKS HERE** waiting for LLM (codex subprocess, up to 300s)
    → NO SSE heartbeat/keep-alive emitted during the wait
→ Client side: plan.py (~L73): for line in resp.iter_lines()
    → Receives first 3 events, updates spinner
    → Then BLOCKS waiting for next line — server is stuck at LLM call
    → User sees "calling_llm (40%)" for 30-300 seconds with no further output
    → User kills with Ctrl+C (or our timeout fires at 30s)
```

**Trace for `gimo chat`**:
```
→ chat_cmd.py::chat (~L56) — single-turn mode at line 87
→ chat_cmd.py (~L113): api_request(config, "POST", f"/ops/threads/{thread_id}/chat", json_body={"content": message})
    → NOTE: calls NON-streaming endpoint /ops/threads/{id}/chat (NOT /chat/stream)
→ api.py::smart_timeout (~L142): path matches "/chat" → returns None (INFINITE timeout)
→ httpx.Client created with timeout=None → waits forever
→ Server: conversation_router.py::chat_message (~L179)
    → result = await AgenticLoopService.run(thread_id, user_message, workspace_root, token)
    → agentic_loop_service.py::_run_loop (~L686): up to MAX_TURNS=25 LLM iterations
    → Each iteration calls adapter.chat_with_tools()
    → **BLOCKS** for entire agentic loop (potentially 25 × 30-60s = 12.5-25 min)
→ Client: ZERO progress feedback — no spinner, no status, no streaming
→ User sees nothing and kills after 30s
```

**Root causes (3 separate)**:

1. **`chat -m` uses non-streaming endpoint** (`chat_cmd.py` ~L113): calls `POST /ops/threads/{id}/chat` instead of `POST /ops/threads/{id}/chat/stream`. The streaming endpoint exists (`conversation_router.py` ~L217) but isn't used.

2. **`smart_timeout` returns `None` for `/chat` paths** (`api.py::smart_timeout` ~L142): any path containing "/chat" gets infinite timeout. The client hangs indefinitely.

3. **Plan SSE generator has no heartbeat** (`plan_router.py::generate_plan_stream::event_generator` ~L486): during the `await ProviderService.static_generate()` call (30-300s), no SSE events or keep-alive comments are emitted. The client has no way to distinguish "waiting for LLM" from "connection dead".

**Blast radius**: All CLI users experience this. The plan command gives false hope (spinner + early events then silence), while chat gives nothing at all.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended for chat) | `chat_cmd.py` ~L113 | Switch single-turn to use `/chat/stream` SSE endpoint + add spinner | Low |
| B (recommended for plan) | `plan_router.py::event_generator` | Add SSE heartbeat (`:keepalive\n\n`) every 5s during LLM wait | Low |
| C | `api.py::smart_timeout` | Return 300s instead of None for `/chat` paths | Low |

**Confidence**: HIGH

---

### [#3] GICS Daemon Not Initialized

**Reported symptom**: `daemon_alive: false`, `error: "GICS not initialized"` across all GICS tools.

**Entry point**: `main.py::lifespan` → `GicsService.start_daemon()`

**Trace**:
```
→ main.py::lifespan (~L267): gics_service = GicsService(config)
→ gics_service.py::start_daemon (~L83):
    → Resolves daemon script: config.py::_resolve_gics_daemon_script (~L440)
      → path = <repo_root>/vendor/gics/dist/src/cli/index.js ✅ (exists)
    → Creates GICSDaemonSupervisor with:
        data_path = .orch_data/ops/gics_data/
        socket_path = .orch_data/ops/gics.sock
        token_path = .orch_data/ops/gics.token  ← GIMO's expected path
    → supervisor.start() at gics_client.py::GICSDaemonSupervisor.start (~L714):
      → Spawns: node <cli_path> daemon start --data-path <X> --socket-path <Y> --token-path <Z>

→ **BUG A**: vendor/gics/dist/src/cli/commands.js::daemonStart (~L909):
    const tokenPath = DEFAULT_TOKEN_PATH;  // ~/.gics/gics.token  ← IGNORES --token-path flag
    → Token is written to ~/.gics/gics.token
    → GIMO expects it at .orch_data/ops/gics.token

→ supervisor.wait_until_ready() at gics_client.py (~L729):
    → Creates GICSClient(token_path=".orch_data/ops/gics.token")
    → Reads token from .orch_data/ops/gics.token → file doesn't exist or stale
    → ping() fails authentication (wrong token)
    → Retries for 15 seconds → TimeoutError

→ **BUG B**: gics_service.py::start_daemon (~L119-130):
    except Exception as exc:
        logger.error("Failed to start GICS daemon: %s", exc)
        self._supervisor = None  ← silently swallows, continues degraded

→ main.py (~L279): if not _last_alive → logs misleading "Install Node.js >= 18" warning
    → Node.js v24.13.0 IS installed — warning is wrong
```

**Root cause**: Token path mismatch. The Node.js GICS CLI ignores `--token-path` flag and writes to the default `~/.gics/gics.token`. The Python supervisor reads from `.orch_data/ops/gics.token`. The daemon IS starting (Node.js process spawns), but the authentication handshake fails because the token files are in different locations.

**Bug C (potential)**: The Popen call at `gics_client.py` ~L724 doesn't capture `stderr`, so any Node.js startup errors (missing dependencies, import failures) are silently lost.

**Why tests don't catch this**: `tests/conftest.py::_mock_gics_daemon` (~L133-150) is `autouse=True, scope="session"` — mocks out `start_daemon`, `start_health_check`, `stop_daemon`, and all `GICSClient._call` invocations. The token mismatch is completely invisible in tests.

**Blast radius**: ALL GICS-dependent features are dead: model reliability tracking, anomaly detection, trust event persistence, cost event persistence, duration telemetry. Every GICS tool returns empty arrays with "GICS not initialized".

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `vendor/gics/dist/src/cli/commands.js` ~L909 | Parse `--token-path` flag: `const tokenPath = parseFlag(args, '--token-path') ?? DEFAULT_TOKEN_PATH` | Low |
| B (workaround) | `gics_service.py::start_daemon` | Pass token_path=`~/.gics/gics.token` (match the daemon's hardcode) | Low — fragile |
| C (defense) | `gics_client.py::GICSDaemonSupervisor.start` ~L724 | Add `stderr=subprocess.PIPE` to capture Node.js errors | Low |
| D (diagnostic) | `main.py` ~L280 | Fix warning message: instead of "Install Node.js >= 18", show actual exception | Low |

**Confidence**: HIGH

---

### [#4] gimo_chat MCP Tool Still Times Out

**Reported symptom**: `MCP error -32001: Request timed out`

**Entry point**: `native_tools.py::gimo_chat` (~L476)

**Trace**:
```
→ native_tools.py::gimo_chat (~L476):
    → Creates httpx.AsyncClient(timeout=300.0)
    → Creates thread if needed (quick, ~100ms)
    → POST /ops/threads/{thread_id}/chat with json={"content": message}

→ Server: conversation_router.py::chat_message (~L179):
    → AgenticLoopService.run(thread_id, user_message, workspace_root, token)
    → agentic_loop_service.py::_run_loop (~L686):
        → MAX_TURNS=25 iterations
        → Each calls adapter.chat_with_tools() → LLM call
        → For CLI adapters: each call = subprocess, 30-300s per turn
        → Total potential time: 25 × 300 = 7500s (2+ hours)

→ **TIMEOUT LAYER**: MCP stdio transport has its own timeout
    → Claude Desktop MCP default: ~60s per tool call
    → The httpx client has 300s timeout but MCP stdio dies first at ~60s
    → Result: MCP error -32001 at ~60s regardless of httpx timeout
```

**Root cause**: The MCP stdio transport timeout (controlled by the MCP host, e.g., Claude Desktop) is much shorter than the agentic loop execution time. Even a single-turn chat with a CLI adapter can take 30-60s, exceeding MCP's timeout.

**Blast radius**: `gimo_chat` via MCP is unusable for any LLM provider that takes >30s per call.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `native_tools.py::gimo_chat` | Use fire-and-return pattern: start agentic loop async, return immediately with thread_id + "processing" status. Let caller poll via `gimo_get_task_status`. | Medium — changes API contract |
| B | MCP server config | Increase `requestTimeout` in MCP server capabilities | Low — but depends on host support |
| C | `native_tools.py::gimo_chat` | Use SSE streaming endpoint `/chat/stream` + aggregate result | Medium — complex in MCP context |

**Confidence**: HIGH

---

### [#5] Trust Score Regression: 0.0 in MCP, 0.85 in HTTP

**Reported symptom**: MCP `get_trust_profile` returns 0.0 everywhere; HTTP `trust/query` returns 0.85.

**Entry point**: `sagp_gateway.py::_get_trust_score` (MCP) vs `trust_router.py::trust_query` (HTTP)

**Trace**:
```
MCP PATH:
→ governance_tools.py::gimo_get_trust_profile (~L91)
→ sagp_gateway.py::_get_trust_score (~L206-215):
    → Creates TrustStorage + TrustEngine
    → trust_engine.py::query_dimension (~L44):
        → If NO events: returns _empty_record with score=0.85 (R15 fix) ✅
        → If EVENTS exist: _build_records → _finalize_record (~L97-108):
            base = approvals / (approvals + rejections + failures + 1)
            → If 0 approvals: base = 0.0
    → sagp_gateway.py (~L215): return score  ← **NO guard, returns raw 0.0**

HTTP PATH:
→ trust_router.py::trust_query (~L15-30):
    → Same TrustEngine → same query_dimension → same score=0.0
    → BUT line 29-30:
        raw_score = float(result.get("score", 0.0))
        result["effective_score"] = raw_score if raw_score > 0.0 else 0.85
        ← **Guard STILL present**, maps 0.0 → 0.85
```

**Root cause**: R15 (commit `31b57ae`) removed the `score > 0.0 else 0.85` guard from `sagp_gateway.py::_get_trust_score` (~L215), assuming that setting `_empty_record.score = 0.85` was sufficient. But `_empty_record` is only the fallback when NO events exist. When events DO exist (even just failed ones), `_finalize_record` computes the score from scratch and can produce 0.0. The HTTP router still has the guard at `trust_router.py` ~L30, so HTTP shows 0.85 while MCP shows 0.0.

**Why evaluate_action varies**: `evaluate_action(write_file)` → events exist for "write_file" dimension → `_finalize_record` → score=0.0. `evaluate_action(INVALID_TOOL)` → NO events → `_empty_record` → score=0.85.

**Blast radius**: All MCP governance tools return wrong trust scores. Any governance decision that uses trust_score (risk gating, HITL thresholds) may be affected.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (quick) | `sagp_gateway.py` ~L215 | Restore guard: `return score if score > 0.0 else 0.85` | Low — bandaid |
| B (recommended) | `trust_engine.py::_finalize_record` ~L103 | Add minimum floor for low-event dimensions: `score = max(score, 0.1)` when total_events < 5 | Low |
| C (clean) | `trust_router.py` ~L29-30 | Remove the `effective_score` hack, fix at engine layer | Medium — needs surface testing |

**Confidence**: HIGH

---

### [#6] Zero Cost/Token Tracking Across All Operations

**Reported symptom**: `tokens_total: 0, cost_total_usd: 0.0` across all metrics.

**Entry point**: `cli_account.py::generate` (~L152)

**Trace**:
```
→ cli_account.py::generate (~L152):
    → Runs codex/claude subprocess
    → subprocess.run returns stdout + stderr
    → Constructs response:
        return {
            "content": content,
            "usage": {
                "prompt_tokens": 0,       ← HARDCODED ZERO
                "completion_tokens": 0,    ← HARDCODED ZERO
                "total_tokens": 0,         ← HARDCODED ZERO
            },
        }
→ service_impl.py::static_generate (~L784-789):
    usage = response.get("usage", {})
    prompt_t = usage.get("prompt_tokens", 0)   → 0
    completion_t = usage.get("completion_tokens", 0)  → 0
    cost_usd = CostService.calculate_cost(model_name, 0, 0)  → $0.00
```

**Root cause**: `CliAccountAdapter` cannot extract token usage from CLI tool output. Neither codex nor claude CLI report token counts in their output format. The adapter hardcodes all token fields to 0.

**Structural dependency on #3**: Even if token estimation were added, cost events would not be persisted because GICS is dead (Issue #3). The `_record_outcome_safe` call at `service_impl.py` ~L798 tries to write to GICS but silently fails.

**Blast radius**: All operations via `codex-account` and `claude-account` providers report zero cost. Budget alerts, burn rate forecasts, and ROI analytics are non-functional.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `cli_account.py::generate` | Estimate tokens from prompt length and response length: `prompt_tokens = len(prompt) // 4`, `completion_tokens = len(content) // 4` | Low — approximate but useful |
| B | `cli_account.py::_parse_codex_jsonl` | Parse Codex JSONL for `usage` events (if codex emits them in `--json` mode) | Medium — format may vary |
| C | `service_impl.py::static_generate` ~L784 | After adapter returns, if tokens are 0, estimate from string lengths | Low — fallback logic |

**Confidence**: HIGH

---

### [#7] gimo_run_task Reports "Draft creation failed" on Success

**Reported symptom**: `gimo_run_task` returns "Draft creation failed:\n✅ Success (201):..."

**Entry point**: `native_tools.py::gimo_run_task` (~L299)

**Trace**:
```
→ native_tools.py::gimo_run_task (~L305):
    draft_result = await proxy_to_api("POST", "/ops/drafts", ...)
    → Returns string: "✅ Success (201):\n{\n  \"id\": \"d_...\",\n  ...}"

→ Parsing loop (~L311-317):
    for line in draft_result.splitlines():
        try:
            data = json.loads(line.lstrip("✅ Success (201):").strip())
            draft_id = data.get("id")
            break
        except (json.JSONDecodeError, ValueError):
            continue

→ Problem: draft_result.splitlines() splits the multiline JSON across many lines:
    Line 0: "✅ Success (201):"  → lstrip("✅ Success (201):") → "" → json.loads("") FAILS
    Line 1: "{"                   → json.loads("{") FAILS (incomplete)
    Line 2: '  "id": "d_...",'   → json.loads('  "id": "d_...",') FAILS (incomplete)
    ... etc
    → No line contains valid complete JSON → draft_id stays None

→ Line 318-319: if not draft_id: return f"Draft creation failed:\\n{draft_result}"
```

**Root cause**: The `proxy_to_api` function returns a multi-line string with a status prefix. The parsing logic at line 311-317 tries to parse each line individually as JSON, but the JSON spans multiple lines. No single line is a complete JSON object.

**Secondary issue**: `str.lstrip()` at line 313 takes a **character set**, not a substring. `"✅ Success (201):".lstrip("✅ Success (201):")` removes all characters in the set `{'✅', ' ', 'S', 'u', 'c', 'e', 's', '(', '2', '0', '1', ')', ':'}`, which would over-strip content from JSON lines too.

**Blast radius**: `gimo_run_task` is completely broken. It always reports failure even on successful draft creation.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `native_tools.py::gimo_run_task` ~L311 | Join all lines after the first, then parse: `json_str = "\n".join(draft_result.splitlines()[1:]); data = json.loads(json_str)` | Low |
| B | `native_tools.py::gimo_run_task` | Find first `{` in result and parse from there: `json_str = draft_result[draft_result.index("{"):]` | Low |
| C | `bridge.py::proxy_to_api` | Return structured data instead of a formatted string | Medium — changes interface |

**Confidence**: HIGH

---

### [#8] gimo_generate_team_config Cannot Find Drafts

**Reported symptom**: `"Plan not found: d_1775511382404_d1bdef"` even though draft exists.

**Entry point**: `native_tools.py::gimo_generate_team_config` (~L636)

**Trace**:
```
→ native_tools.py::gimo_generate_team_config (~L664):
    result = await proxy_to_api("GET", f"/ops/drafts/{plan_id}")
    → Returns the draft JSON (status 200)

→ (~L666): data = json.loads(result.split("\n", 1)[-1])
    → Parses draft data successfully

→ (~L667): content = data.get("content")
    → Draft was created with content=null (no LLM generated the plan)
    → content is None

→ (~L671): if not content: return json.dumps({"error": f"Plan not found: {plan_id}"})
    → Returns "Plan not found" because content is null
```

**Root cause**: Drafts are created by `POST /ops/drafts` without running an LLM — the `content` field stays `null`. The `generate_team_config` tool checks for `content` in the draft, which would only be populated if plan generation (via SSE streaming) ran and stored the LLM's output. The error message "Plan not found" is misleading — the draft IS found, but it has no generated plan content.

**This is a downstream consequence of Issue #1**: If the pipeline generated content and stored it, this tool would work. The `legacy_run` composition generates content via LlmExecute but doesn't store it back to the draft.

**Blast radius**: `generate_team_config` is unusable with any draft created via MCP (which doesn't trigger SSE plan generation).

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `native_tools.py::gimo_generate_team_config` ~L671 | If content is null, use the `prompt` field to auto-generate a minimal plan structure | Medium — needs plan format knowledge |
| B | Error message | Change "Plan not found" to "Draft has no plan content. Use gimo_run_task or gimo_propose_structured_plan first." | Low — UX improvement |
| C | `engine_service.py::execute_run` | After LlmExecute, store generated content back to draft | Medium — changes pipeline |

**Confidence**: HIGH

---

### [#9] Audit Tail ValueError: I/O Operation on Closed File

**Reported symptom**: `gimo audit` shows "ValueError: I/O operation on closed file."

**Entry point**: `gimo_cli/commands/ops.py::audit` (~L204)

**Trace**:
```
→ ops.py::audit (~L212): calls GET /ui/audit?limit=20
→ legacy_ui_router.py::get_ui_audit (~L88):
    return {"lines": FileService.tail_audit_lines(limit=limit)}
→ file_service.py::tail_audit_lines (~L13):
    → Reads AUDIT_LOG_PATH, returns last N lines

→ The audit log file CONTAINS the error text:
    "ValueError: I/O operation on closed file."

→ Source of error in audit log:
    opentelemetry.sdk.metrics._internal.export.__init__.py (~L165):
        self.out.write(self.formatter(metrics_data))
    → The OpenTelemetry ConsoleMetricExporter writes to a file handle (stdout/stderr)
    → The handle was closed (possibly by the server's stdout redirect or daemon mode)
    → The traceback gets written to the audit log by the server's log handler
```

**Root cause**: OpenTelemetry's `ConsoleMetricExporter` writes to `sys.stdout` or `sys.stderr`, but when the GIMO server runs as a background daemon (via `gimo up`), stdout/stderr are closed or redirected. The exporter fails and the traceback gets captured in the audit log.

**Blast radius**: Minor — only affects audit log readability. The error is cosmetic.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | OTel configuration | Don't use `ConsoleMetricExporter` in daemon mode, or redirect to file | Low |
| B | `file_service.py::tail_audit_lines` | Filter out known OTel tracebacks from audit lines | Low — fragile |

**Confidence**: MEDIUM

---

### [#10] SSE Events Are Log-Only, No Structured Data

**Reported symptom**: SSE events for runs contain only 3 log messages: "Run created", "Execution started", "Pipeline completed". No stage transitions, cost events, or content.

**Entry point**: `run_router.py::get_run_events`

**Trace**:
```
→ run_router.py::get_run_events → returns SSE stream reading from run.log[]
→ engine_service.py::execute_run:
    → Calls OpsService.append_log(run_id, "INFO", "Execution started...") at ~L263
    → Runs pipeline
    → Calls OpsService.update_run_status(run_id, "done", "Pipeline completed") at ~L390
    → **NO intermediate log entries during pipeline execution**

→ pipeline.py::run:
    → Iterates stages
    → Creates JournalEntry for each stage
    → BUT journal entries go to self.journal[] (in-memory) and optional RunJournal file
    → **Journal entries are NOT sent to OpsService.append_log()**
    → SSE only sees the 3 log entries from execute_run
```

**Root cause**: The Pipeline writes stage results to its internal journal (`self.journal`), but this journal is NOT propagated to `OpsService.append_log()` which feeds the SSE event stream. There is a complete disconnect between pipeline instrumentation (journals) and the SSE/observability layer (run logs).

**Blast radius**: Run progress is invisible via SSE/API. All runs show only "created → started → done/error" with no intermediate state. The R15 Change 5 (SSE completed event enrichment) added `content` and `status` fields to the completed event template in `plan_router.py`, but the run events endpoint in `run_router.py` doesn't use that template — it just streams `run.log[]`.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `pipeline.py::run` ~L56 | After each stage, call `OpsService.append_log(run_id, "INFO", f"Stage {stage.name}: {output.status}")` | Low |
| B | `engine_service.py::execute_run` | After pipeline.run(), iterate results and append structured events | Low |
| C | Add cost tracking event | After `static_generate` returns, emit cost event via OpsService | Low |

**Confidence**: HIGH

---

### [#11] evaluate_action trust_score Varies by Input

**Same root cause as #5**. When trust events exist for a dimension (e.g., "write_file"), `_finalize_record` computes a real score (0.0 if no approvals). When no events exist (e.g., "INVALID_TOOL"), `_empty_record` returns 0.85 default. The removed guard in `sagp_gateway.py::_get_trust_score` means 0.0 propagates for known tools while 0.85 applies for unknown tools.

**Confidence**: HIGH — same fix as #5.

---

## Systemic Patterns

### Pattern 1: "Succeed Without Doing" — Pipeline Completes Without Observable Work

**Issues**: #1, #6, #7, #10
**Architecture flaw**: The pipeline evaluates "success" purely by stage return status (`continue`/`fail`/`halt`), without asserting that work was actually performed. A stage that returns `{status: "continue", content: ""}` is indistinguishable from one that returns `{status: "continue", content: "...1000 lines of code..."}`.

**Future risk**: Any new stage that silently returns empty results will be counted as success. No invariant check validates that the pipeline produced measurable output (files written, tokens consumed, content generated).

**Prevention**: Add a `PipelineAssertionGate` final stage that checks: (1) at least one artifact has non-empty content, (2) token count > 0 or estimation was applied, (3) if the prompt requests file creation, FileWrite stage must have been in the pipeline.

### Pattern 2: "Silent Swallow" — Exceptions Caught and Forgotten

**Issues**: #3, #6, #9
**Architecture flaw**: Multiple layers catch exceptions with `except Exception: pass` or `except Exception: logger.error(...)` without propagating failure state to the user. GICS daemon failure is swallowed in `start_daemon`. Cost recording failure is swallowed in `_record_outcome_safe`. OTel export failure is swallowed by the logging system.

**Future risk**: Any new service that follows this pattern will create invisible degradation. The system will appear healthy while critical subsystems are dead.

**Prevention**: Replace `except Exception: pass` with `except Exception: logger.error(...); self._degraded_services.add(service_name)`. Surface degraded services in `/health` and `gimo doctor`.

### Pattern 3: "Surface Parity Drift" — MCP and HTTP Return Different Results

**Issues**: #5, #11
**Architecture flaw**: The MCP bridge (`sagp_gateway.py`) and HTTP routers (`trust_router.py`) call the same underlying engine but apply different post-processing. When R15 changed one path (sagp_gateway), the other path (trust_router) retained its old behavior.

**Future risk**: Any change to the engine layer that isn't applied symmetrically to both surfaces will create inconsistencies. This is especially dangerous because tests may only test one surface.

**Prevention**: Extract the post-processing (score floor, effective_score computation) into the engine layer itself (`TrustEngine.query_dimension`), so both surfaces get identical results without per-surface patches.

### Pattern 4: "Proxy String Parsing" — MCP Bridge Parses Formatted Strings Instead of Structured Data

**Issues**: #7, #8
**Architecture flaw**: The MCP bridge uses `proxy_to_api()` which returns formatted strings like `"✅ Success (201):\n{...}"`. Individual MCP tools then parse these strings with fragile regex/split logic. This is error-prone and has already broken two tools.

**Future risk**: Any new MCP tool that calls `proxy_to_api` will face the same parsing fragility.

**Prevention**: Create `proxy_to_api_json()` that returns `(status_code, parsed_dict)` instead of a formatted string. Or refactor `proxy_to_api` to return structured data and let the caller format for display.

---

## Dependency Graph

```
#3 (GICS dead) ←── token path mismatch in vendor/gics CLI
    ↓
#6 (zero cost) ←── CliAccountAdapter returns 0 tokens (structural)
    ↓                     AND GICS can't persist cost events
#1 (hollow run) ←── legacy_run has no FileWrite stage
    ↓                     AND CliAccountAdapter returns 0 tokens
    ↓                     AND pipeline doesn't log intermediate state
#10 (SSE log-only) ←── Pipeline journal not propagated to OpsService
    ↓
#8 (team_config) ←── draft.content is null because no LLM stored content back

#2 (CLI silent) ←── chat uses non-streaming endpoint + infinite timeout
    ↓                     AND plan has no SSE heartbeat during LLM wait
#4 (MCP chat timeout) ←── MCP stdio timeout < agentic loop duration

#5 (trust regression) ←── R15 removed guard in sagp_gateway but not in trust_router
#11 (trust varies) ←── same root as #5

#7 (run_task "failed") ←── proxy_to_api returns string, fragile JSON parsing

#9 (audit ValueError) ←── OTel ConsoleExporter writes to closed stdout in daemon mode
```

---

## Preventive Findings

### 1. No Integration Test for End-to-End Pipeline Execution

The conftest mocks (`_mock_gics_daemon`, `_mock_model_inventory`) mean no test exercises the full flow: draft → approve → execute → LLM call → file write → status update. Unit tests verify individual stages but not the composition.

**Risk**: Any change to the composition map, stage ordering, or context propagation can break the pipeline silently.

### 2. CliAccountAdapter is a Black Box in Tests

No test verifies that `CliAccountAdapter.generate()` produces correct output for codex or claude CLIs. The adapter is always mocked in tests. Its JSONL parser, subprocess handling, and token reporting are untested against real CLI output.

**Risk**: Changes to codex/claude CLI output format will break the adapter without any test catching it.

### 3. MCP Bridge Shares No Code with HTTP Routers

The MCP bridge in `mcp_bridge/` reimplements HTTP calls via `proxy_to_api()`, then parses the formatted responses. This is a complete duplication of what the HTTP routers already do, with a fragile string-parsing bridge layer in between.

**Risk**: Every HTTP router change requires a corresponding MCP bridge update. The string-parsing layer adds a new failure mode that doesn't exist in direct HTTP calls.

---

## Recommended Fix Priority Ordering

| Priority | Issue(s) | Fix | Impact |
|----------|----------|-----|--------|
| P0 | #3 | Fix GICS token path pass-through in vendor CLI | Unblocks all GICS features |
| P0 | #1, #8 | Add FileWrite to legacy_run + store content back to draft | Enables actual code generation |
| P0 | #5, #11 | Restore trust score guard in sagp_gateway OR fix engine layer | Fixes governance regression |
| P1 | #2 | Switch chat -m to streaming endpoint + fix smart_timeout | Fixes CLI UX |
| P1 | #7 | Fix proxy_to_api JSON parsing in run_task | Fixes MCP auto-run |
| P1 | #6 | Add token estimation to CliAccountAdapter | Enables cost tracking |
| P2 | #4 | Implement fire-and-return pattern for MCP chat | Fixes MCP chat UX |
| P2 | #10 | Propagate pipeline journal to OpsService/SSE | Enables run observability |
| P3 | #9 | Fix OTel exporter for daemon mode | Cleans audit log |
