# E2E Engineering Plan — R13

**Date**: 2026-04-06
**Round**: 13
**Input documents**: `E2E_ROOT_CAUSE_ANALYSIS_20260406_R13.md`
**Design philosophy**: `docs/SYSTEM.md`, `AGENTS.md`, `docs/CLIENT_SURFACES.md`

---

## Diagnosis Summary

R13's 17 issues are **post-SAGP regressions**, not architectural failures. The SAGP refactor
(April 5, commit `f70c6e1`) was a necessary response to Anthropic's OAuth policy change, but
it disrupted the execution codepath. The control plane (status, threads, drafts, governance
queries) is solid and working. The data plane (actual LLM execution, cost accumulation, trust
recording) needs reconnection to existing but orphaned capabilities.

## Design Principle

**Reconnect > Rewrite.** Every change in this plan reuses existing, proven code in the codebase.
No new abstractions, no new dependencies, no new files (except restoring a deleted one).

---

## Competitive Landscape

| Platform | Execution Model | Child Spawning | Governance Per-Action | Error Isolation |
|----------|----------------|----------------|----------------------|-----------------|
| CrewAI | Thread + Future | Pre-declared tasks only | None | Future.set_exception() |
| LangGraph | ThreadPoolExecutor | Inline subgraph calls | None | BackgroundExecutor reraise |
| OpenHands | asyncio.create_task() | AgentDelegateAction (freeform dict) | None | State transitions |
| Codex CLI | Tokio tasks + channels | Clone parent + inherit services | None | CancellationToken |
| **GIMO** | asyncio.create_task() | child-runs/spawn (structured) | **Yes — SagpGateway** | **Needs fix** |

GIMO is the only platform with per-action governance (policy, risk, trust, cost) across all
surfaces. The execution path just needs reconnection to match the governance shell.

---

## Research Findings

1. **Windows temp file locking**: All major tools (Codex, Claude SDK, Aider) avoid temp files
   on Windows. Codex uses Rust stdin piping; Claude SDK uses JSON over stdin/stdout pipes;
   Aider calls LiteLLM in-process. GIMO's own `adapters/claude_code.py` and `generic_cli.py`
   already implement stdin piping — the fix is to apply the same pattern to `cli_account.py`.

2. **MCP server resilience**: The MCP Python SDK has known error isolation gaps (Issues #396,
   #1152). FastMCP provides `ToolError` for expected failures but no crash recovery for stdio
   servers. The fix is try/except around registration + tool dispatch (defense in depth).

3. **Child task specs**: None of the 4 SOTA platforms require pre-validated task specs for child
   agents. OpenHands passes `agent_class + freeform dict`. Codex passes `InitialHistory`. The
   fix is to allow GIMO's RunWorker to fall through to the existing legacy execution path when
   no validated_task_spec is present.

4. **GIMO internal**: `generate-plan-stream` already exists (plan_router.py:358), trust recording
   is implemented (trust_engine.py), legacy execution exists (run_worker.py:314), global SSE
   stream exists (ops_routes.py:106). These are proven, tested capabilities that just need
   reconnection.

---

## The Plan (10 Changes)

### Change 1: Restore `storage/__init__.py` [P0]
- **Solves issues**: #1, #2
- **What**: Restore `tools/gimo_server/services/storage/__init__.py` (deleted in `e7b86c1`)
- **Where**: `tools/gimo_server/services/storage/__init__.py`
- **Why this design**: File existed, was deleted as "dead re-export", but SAGP imports need it
- **Risk**: None — restoring original state
- **Verification**: `gimo_verify_proof_chain` works; MCP bridge survives errors

### Change 2: MCP bridge error isolation [P0]
- **Solves issues**: #1 (defense in depth)
- **What**: Wrap `_register_dynamic()`, `_register_native()`, `mcp.run_stdio_async()` in try/except
- **Where**: `tools/gimo_server/mcp_bridge/server.py:250-259`
- **Why**: MCP SDK has known gaps. One bad tool shouldn't kill the bridge
- **Risk**: Very low
- **Verification**: Introduce deliberate error; bridge stays alive
- **SOTA**: MCP best practice per FastMCP error_handling middleware pattern

### Change 3: Fix Windows temp file locking [P0]
- **Solves issues**: #4, #7
- **What**: Replace `NamedTemporaryFile` with `subprocess.communicate(input=prompt_bytes)`
- **Where**: `tools/gimo_server/providers/cli_account.py:167-197`
- **Why**: stdin piping already proven in `adapters/claude_code.py:102`, `generic_cli.py:159`
- **Risk**: Low — same pattern as existing adapters
- **Verification**: `POST /ops/generate-plan?prompt=hello` returns within 30s
- **SOTA**: Codex, Claude SDK, all GIMO adapters use stdin piping

### Change 4: CLI uses streaming endpoint [P1]
- **Solves issues**: #4 (UX complement)
- **What**: `plan.py:58` calls `/ops/generate-plan-stream` with SSE progress display
- **Where**: `gimo_cli/commands/plan.py:54-62`
- **Why**: `generate-plan-stream` exists at `plan_router.py:358` with progress stages
- **Risk**: Low
- **Verification**: `gimo plan "calculator" --no-confirm` shows progress, returns plan

### Change 5: Run execution fallback [P0]
- **Solves issues**: #3, #17
- **What**: If `validated_task_spec` is None but prompt exists, fall through to `_handle_legacy_execution()`
- **Where**: `tools/gimo_server/services/execution/run_worker.py:394-400`
- **Why**: Legacy path exists at line 314. All SOTA platforms (OpenHands, Codex) spawn children without pre-validated specs
- **Risk**: Medium — guard with prompt-existence check
- **Verification**: Draft → approve → run completes; child run executes
- **SOTA**: OpenHands pattern — freeform input, no schema validation for children

### Change 6: `/auth/check` respects Bearer [P1]
- **Solves issues**: #5
- **What**: Use `verify_token()` dependency instead of manual cookie check
- **Where**: `tools/gimo_server/routers/auth_router.py:326-352`
- **Risk**: Very low
- **Verification**: Bearer token returns `authenticated: true`

### Change 7: Surface type consistency [P2]
- **Solves issues**: #16
- **What**: Shared `_mcp_surface()` helper for consistent `SurfaceIdentity`
- **Where**: `governance_tools.py:124`, `mcp_app_dashboard.py:31`
- **Risk**: Very low
- **Verification**: Both tools return same `surface_type`

### Change 8: Budget status real data [P2]
- **Solves issues**: #13
- **What**: Query `BudgetForecastService` for spend/forecast in budget status tool
- **Where**: `tools/gimo_server/mcp_bridge/governance_tools.py:202-219`
- **Risk**: Low
- **Verification**: Budget status returns spend, remaining, forecast

### Change 9: CLI feedback [P3]
- **Solves issues**: #14, #15
- **What**: Add `/mastery/analytics` to smart_timeout; add watch feedback messages
- **Where**: `gimo_cli/api.py:130-146`, `gimo_cli/commands/run.py:173-200`
- **Risk**: Very low
- **Verification**: Analytics doesn't hang; watch shows status messages

### Change 10: Endpoint stubs [P3]
- **Solves issues**: #8, #9, #11, #12
- **What**: Add 4 thin wrapper endpoints over existing internal logic
- **Where**: `run_router.py`, `ops_routes.py`, cost/provider routers
- **Risk**: Low
- **Verification**: Each endpoint returns 200

---

## Execution Order (dependency-aware)

1. Change 1 → 2 (MCP must work first)
2. Change 3 → 4 (execution must work before CLI UX)
3. Change 5 (run execution — independent)
4. Changes 6-10 (independent, any order)

## 8-Criterion Compliance

| Criterion | YES/NO | Evidence |
|-----------|--------|----------|
| Aligned | YES | Single backend truth, no surface-specific logic, elegant minimal solutions |
| Potent | YES | Each change creates lasting leverage (error isolation, correct patterns) |
| Lightweight | YES | Most changes <20 LOC. Change 1 is 2 lines. No new dependencies |
| Multi-solving | YES | 10 changes solve 17 issues (1.7 issues/change ratio) |
| Innovative | YES | "Reconnect > Rewrite" — reuses proven internal code, no new abstractions |
| Disruptive | YES | Enables the only platform with per-action governance across all providers |
| Safe | YES | Minimal reconnections. Error isolation adds safety. No new attack surfaces |
| Elegant | YES | One concept: "reconnect execution to governance". Not 17 patches |

## Change 11: Fix GICS Daemon Startup (P0)

**Solves**: #6 GICS daemon dead, unlocks #10 trust recording

Root cause found: `config.py:453` points to `vendor/gics/dist/src/daemon/server.js` but `GICSDaemonSupervisor` expects the CLI at `vendor/gics/dist/src/cli/index.js`. The supervisor runs `node <cli_path> daemon start` — passing `server.js` (which has no CLI subcommand parser) silently fails.

Additionally, `gics_service.py:180` sleeps 60s before the first health ping, so `_last_alive` stays False even after a successful start.

**Fix**:
- `config.py:453`: `daemon/server.js` → `cli/index.js`
- `gics_service.py:180`: Add immediate ping before first sleep cycle

**Risk**: Low — CLI binary exists, Node v24 available, just fixing the pointer.

## No Residuals

All 17 issues + GICS covered. #10 (trust always empty) is solved transitively by Change 11: `record_model_outcome()` is already wired in `service_impl.py:722` and `spawn_agents.py:196` via `TelemetryMixin`, but early-returns when `_gics` is None. Once GICS is alive, trust flows automatically.
