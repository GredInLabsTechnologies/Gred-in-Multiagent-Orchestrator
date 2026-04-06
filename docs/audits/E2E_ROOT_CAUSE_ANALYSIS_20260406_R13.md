# E2E Root Cause Analysis — R13

**Date**: 2026-04-06
**Round**: 13
**Input document**: `E2E_AUDIT_LOG_20260406_R13.md`

---

## Issue Map

| ID | Category | Root Cause Location | Confidence |
|----|----------|---------------------|------------|
| #1 | MCP bridge crash | `services/storage/__init__.py` deleted in `e7b86c1` (REPO_MASTERPLAN Fase 5) + `mcp_bridge/server.py:250` no try/except | HIGH |
| #2 | Proof chain import | Same as #1 — `storage/__init__.py` was removed as "dead re-export" but later imports depend on it | HIGH |
| #3 | Run never executes | `routers/ops/run_router.py:27-51` fire-and-forget task + `services/execution/run_worker.py:387-400` Phase 5B gate | HIGH |
| #4 | CLI plan/chat silent | `providers/cli_account.py:172-176` Windows temp file locking (WinError 32) when server process is running | HIGH |
| #5 | auth/check false | `routers/auth_router.py:326-352` only checks cookies, not Bearer | HIGH |
| #6 | GICS daemon dead | `services/gics_service.py:82-112` daemon may fail to start; health loop 60s delay | MEDIUM |
| #7 | create_draft timeout | `mcp_bridge/native_tools.py:256` inline LLM call exceeds MCP protocol timeout | HIGH |
| #8 | SSE events missing | No router implements `/ops/runs/{id}/events` | HIGH |
| #9 | /ops/openapi 404 | `ops_routes.py:68-100` exists but likely auth/path mismatch | MEDIUM |
| #10 | Trust always empty | No code calls `trust_engine.record()` during operations | HIGH |
| #11 | Cost compare 405 | `legacy_ui_router.py:317` is GET at `/ui/cost/compare`, not POST at `/ops/cost/compare` | HIGH |
| #12 | Connectors/health 404 | No endpoint exists; health logic internal to provider_service | HIGH |
| #13 | Budget minimal | `governance_tools.py:202-219` only returns pricing state, not spend | HIGH |
| #14 | Mastery analytics hang | `api.py:130-146` timeout logic doesn't match `/mastery/analytics` path | HIGH |
| #15 | Watch empty | `gimo_cli/stream.py:78-79` timeout exits silently with no fallback message | HIGH |
| #16 | Surface type mismatch | `governance_tools.py:124` hardcodes `mcp_generic`, `mcp_app_dashboard.py:31` hardcodes `claude_app` | HIGH |
| #17 | Child run pending | `run_worker.py:394-400` rejects child runs without `validated_task_spec` | HIGH |

---

## Detailed Traces

### [#1] MCP Bridge Crashes and Does Not Recover

**Reported symptom**: MCP tools fail with "Server gimo unavailable" after `verify_proof_chain` call.

**Entry point**: MCP tool call → `mcp_bridge/server.py`

**Trace**:
  → `tools/gimo_server/mcp_bridge/server.py:138` — imports `from tools.gimo_server.main import app as fastapi_app`
  → `tools/gimo_server/main.py:282` — imports `from tools.gimo_server.services.storage_service import StorageService`
  → `tools/gimo_server/services/storage_service.py:7-11` — imports from `.storage` subpackage
  → `tools/gimo_server/services/storage/` — directory has 5 modules but **NO `__init__.py`**
  → Python raises `ModuleNotFoundError`
  → `tools/gimo_server/mcp_bridge/server.py:250-251` — `_register_dynamic()` has **NO try/except**
  → Unhandled exception crashes the MCP bridge process
  → `tools/gimo_server/mcp_bridge/server.py:259` — `mcp.run_stdio_async()` also has **NO try/except**

**Root cause**: Missing `__init__.py` in `tools/gimo_server/services/storage/` directory. The directory contains `config_storage.py`, `cost_storage.py`, `eval_storage.py`, `trust_storage.py`, `workflow_storage.py` but Python cannot import from a directory without `__init__.py`. Combined with zero error isolation in the MCP bridge startup.

**Blast radius**: ALL MCP tool calls fail after any import-time error. The MCP bridge is a single-process with no recovery mechanism.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `services/storage/__init__.py` | Create empty `__init__.py` | Very low |
| B (recommended) | A + `mcp_bridge/server.py:250-259` | A + wrap `_register_dynamic()`, `_register_native()`, and `run_stdio_async()` in try/except with logging | Low |

**Confidence**: HIGH

---

### [#2] verify_proof_chain ImportError

**Reported symptom**: Returns `{"valid": false, "error": "No module named 'tools.gimo_server.services.storage.storage_service'"}`

**Entry point**: MCP tool `gimo_verify_proof_chain`

**Trace**:
  → `tools/gimo_server/mcp_bridge/governance_tools.py:155-168` — `gimo_verify_proof_chain()` has try/except
  → `tools/gimo_server/mcp_bridge/governance_tools.py:162` — imports `SagpGateway`
  → `tools/gimo_server/services/sagp_gateway.py:182` — `from .storage_service import StorageService`
  → `tools/gimo_server/services/storage_service.py:7-11` — imports from `.storage` subpackage
  → **FAILS**: Missing `__init__.py` (same as #1)

**Root cause**: Same as #1 — missing `__init__.py`. The error IS caught by the try/except in governance_tools.py (it returns a JSON error instead of crashing), but the MCP bridge may crash during the import-time resolution.

**Blast radius**: All governance tools that import StorageService: `gimo_verify_proof_chain`, `gimo_get_trust_profile`, and governance snapshot internals.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `services/storage/__init__.py` | Create `__init__.py` — fixes both #1 and #2 | Very low |

**Confidence**: HIGH

---

### [#3] Run Execution Never Starts

**Reported symptom**: Run stays at `status: running, stage: null` with no LLM calls made.

**Entry point**: `POST /ops/drafts/{id}/approve?auto_run=true`

**Trace**:
  → `tools/gimo_server/routers/ops/run_router.py:173-179` — run created with status="pending"
  → `tools/gimo_server/routers/ops/run_router.py:177-189` — set to "running", `_spawn_run()` called
  → `tools/gimo_server/routers/ops/run_router.py:27-51` — `_spawn_run()`:
    - Line 39: calls `EngineService.execute_run(run_id, composition=composition)`
    - Line 51: wraps in `asyncio.create_task()` — **fire-and-forget**
  → The HTTP response returns immediately
  → The async task runs in background but may fail silently
  → No exception handling ensures the task reports errors back to the run status

**Additional gate** (for runs that reach the worker):
  → `tools/gimo_server/services/execution/run_worker.py:387-400` — Phase 5B gate:
    - Line 395: `task_spec = getattr(run, "validated_task_spec", None)`
    - Line 396-400: If `task_spec` is None → run rejected with "Missing ValidatedTaskSpec"
  → For drafts created via HTTP (no plan generation), `validated_task_spec` is null

**Root cause**: Two-layer failure:
1. `_spawn_run()` creates a fire-and-forget async task with no error propagation
2. Even if the task runs, Phase 5B in RunWorker unconditionally requires `validated_task_spec` which is never set for simple drafts

**Blast radius**: ALL draft→approve→run flows. Also affects manual `/ops/runs` POST and `/ops/runs/{id}/rerun`.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `run_router.py:27-51` | Add error callback on task + update run status on failure | Low |
| B (recommended) | A + `run_worker.py:394-400` | A + allow runs without `validated_task_spec` to use a default execution path (direct LLM call with prompt from draft) | Medium |

**Confidence**: HIGH

---

### [#4] CLI plan and chat Commands Produce No Output

**Reported symptom**: `gimo plan` and `gimo chat` hang silently with zero output.

**Entry point**: `gimo_cli/commands/plan.py:55-62`, `gimo_cli/commands/chat_cmd.py:113`

**IMPORTANT CONTEXT**: `ProviderService.static_generate()` works correctly in isolation
(returns "Hello" from codex-account in ~2 seconds). The provider is NOT broken. The issue
is specific to when the call happens from within the running server process.

**Trace**:
  → `gimo_cli/commands/plan.py:55` — calls `api_request(config, "POST", "/ops/generate-plan", ...)`
  → Server-side: `tools/gimo_server/routers/ops/plan_router.py:292` — calls `ProviderService.static_generate()`
  → `tools/gimo_server/services/providers/service_impl.py:759` — delegates to `CliAccountAdapter.generate()`
  → `tools/gimo_server/providers/cli_account.py:163-197` — Windows codepath:
    - Line 172: creates `tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)`
    - Line 176: tries to reopen the file with `open(tf_path, "rb")`
    - **FAILS with `WinError 32`: "El proceso no tiene acceso al archivo porque está siendo
      utilizado por otro proceso"**
  → The exception propagates but the endpoint catches it at line 331 and creates an error draft
  → **However**, the response may hang because the error path still tries to record telemetry
    (line 340) and the endpoint never sends the HTTP response back to the client

**Root cause**: Windows file locking race condition in `CliAccountAdapter.generate()`. The
`NamedTemporaryFile` is created and closed within a `with` block, then reopened for reading.
On Windows, the OS may not fully release the file handle immediately after the `with` block
exits, causing `WinError 32` when another open attempt follows. This worked in isolation
(no server process competing for temp directory) but fails when the server's uvicorn process
is running — likely due to antivirus or Windows Defender scanning the newly created temp file.

**Historical note**: The CLI plan/chat commands worked before because the SAGP refactor
(`f70c6e1`) changed the provider priority and adapter configuration. The Windows temp file
path was added in R9 (`47847cb`) specifically for Windows command-line length limits.
The `cli_account.py` adapter was last modified in R11 (`f915b75`).

**Blast radius**: All generation calls on Windows when using CLI account adapters (codex, claude).
Does NOT affect API-key-based adapters (Anthropic API, OpenAI API) which don't use subprocesses.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `cli_account.py:172-176` | Use `delete_on_close=False` (Python 3.12+) or write to a non-temporary path under `.orch_data/tmp/` that avoids Windows Defender scanning | Low |
| B | `cli_account.py:172-176` | Add a small `time.sleep(0.1)` between closing the tempfile and reopening it, or use `os.fdopen()` on the same fd | Very low |

**Confidence**: HIGH

---

### [#5] /auth/check Returns false With Valid Bearer Token

**Reported symptom**: Bearer token authenticates /ops/* endpoints but `/auth/check` returns false.

**Entry point**: `GET /auth/check`

**Trace**:
  → `tools/gimo_server/routers/auth_router.py:326-352` — `check_session()`:
    - Line 328: `cookie_value = request.cookies.get(SESSION_COOKIE_NAME)`
    - Line 329: If no cookie → return `{"authenticated": False}`
    - **NEVER checks Bearer token**
  → Meanwhile, `/ops/*` routes use `verify_token()` dependency:
    - `auth_router.py:253-287` — checks BOTH Bearer header AND session cookies

**Root cause**: `/auth/check` manually checks only cookies. It does not use the `verify_token()` dependency that handles both auth methods.

**Blast radius**: Any client that authenticates via Bearer token (API clients, CLI) will always see `authenticated: false` from `/auth/check`. The frontend uses cookies so it works there.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `auth_router.py:326-352` | Use `verify_token()` dependency, return role info | Very low |

**Confidence**: HIGH

---

### [#6] GICS Daemon Never Alive

**Reported symptom**: `gics_health.daemon_alive: false`, `entry_count: 0` across all checks.

**Entry point**: `gimo_get_governance_snapshot`

**Trace**:
  → `tools/gimo_server/services/gics_service.py:66` — `self._last_alive: bool = False`
  → `tools/gimo_server/services/gics_service.py:82-112` — `start_daemon()`:
    - Creates supervisor subprocess
    - Line 108: sets `_last_alive = True` on success
    - Line 110: if exception, sets supervisor to None
  → `tools/gimo_server/main.py:275-278` — startup calls `gics_service.start_daemon()` + `start_health_check()`
  → **BUT**: conftest mocks `GicsService.start_daemon` globally for tests
  → In production: health loop at `gics_service.py:179-189` polls every 60 seconds
  → First check has 60s sleep BEFORE first ping — daemon appears dead for first minute

**Root cause**: The GICS daemon requires a supervisor process. If the supervisor fails to start (no GICS binary, subprocess error), `_last_alive` stays False. Additionally, the health loop has a 60-second initial delay before first ping.

**Blast radius**: GICS telemetry, model reliability tracking, anomaly detection — all disabled.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `gics_service.py:179` | Do immediate ping before first sleep cycle | Very low |
| B (recommended) | A + `gics_service.py:82-112` | A + log clear error message when daemon fails to start + set health status to "unavailable" vs "dead" | Low |

**Confidence**: MEDIUM (need to verify if GICS binary actually exists on this system)

---

### [#7] create_draft MCP Timeout

**Reported symptom**: `MCP error -32001: Request timed out`

**Entry point**: MCP tool `gimo_create_draft`

**Trace**:
  → `tools/gimo_server/mcp_bridge/native_tools.py:296-313` — `gimo_create_draft()`:
    - Line 300: calls `_generate_plan_for_task(task_instructions)`
  → `tools/gimo_server/mcp_bridge/native_tools.py:223-272` — `_generate_plan_for_task()`:
    - Line 256: calls `ProviderService.static_generate(prompt=sys_prompt, ...)`
    - **No timeout wrapper** on this async call
  → `tools/gimo_server/services/providers/service_impl.py:759` — `adapter.generate()` takes up to 300s
  → MCP protocol has a 30-60s default request timeout
  → LLM generation exceeds MCP timeout → -32001

**Contrast with HTTP**: `POST /ops/drafts` (HTTP) does NOT do inline plan generation — returns immediately with empty draft. The MCP tool adds inline plan generation that the HTTP endpoint doesn't do.

**Root cause**: MCP tool `gimo_create_draft` does synchronous LLM plan generation inline, which exceeds the MCP protocol timeout. The HTTP equivalent returns immediately without plan generation.

**Blast radius**: MCP tool `gimo_create_draft` always times out. Claude Code users cannot create drafts with plans via MCP.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `native_tools.py:296-313` | Split into two steps: create draft (fast) + generate plan (separate tool or async) | Low |
| B | `native_tools.py:256` | Wrap in `asyncio.wait_for(timeout=25)` with fallback to draft-without-plan | Low |

**Confidence**: HIGH

---

### [#8] SSE Events Endpoint Missing

**Reported symptom**: `GET /ops/runs/{id}/events` returns 404.

**Entry point**: HTTP API

**Trace**:
  → Searched all routers in `tools/gimo_server/routers/ops/`:
    - `run_router.py` — CRUD for drafts/runs, no events endpoint
    - `plan_router.py` — has plan streaming SSE but not for runs
    - `conversation_router.py` — has conversation streaming but not for runs
  → **Endpoint simply does not exist**

**Root cause**: No router implements run execution events streaming. The plan_router has SSE for plan generation, but run execution has no equivalent.

**Blast radius**: No way to stream run progress. Clients must poll `GET /ops/runs/{id}` repeatedly.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `run_router.py` | Add `GET /ops/runs/{id}/events` SSE endpoint that streams from run log | Low |

**Confidence**: HIGH

---

### [#9] /ops/openapi Returns 404

**Reported symptom**: `GET /ops/openapi` returns 404.

**Entry point**: HTTP API

**Trace**:
  → `tools/gimo_server/ops_routes.py:68-100` — endpoint exists as `GET /openapi.json` (NOT `/ops/openapi`)
  → Requires `verify_token()` auth dependency
  → The actual FastAPI-generated spec is at `/openapi.json` (no auth required, 235 paths)
  → The MCP tool `gimo_openapi` maps to a different path than the actual endpoint

**Root cause**: Path mismatch. The endpoint is at `/openapi.json` under the ops router (so actually `/ops/openapi.json`?), not `/ops/openapi`. The MCP bridge may be calling the wrong path.

**Blast radius**: MCP tool `gimo_openapi` returns wrong data or 404.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `ops_routes.py` | Add alias route at `/ops/openapi` that returns same data | Very low |

**Confidence**: MEDIUM

---

### [#10] Trust Profile Always Empty

**Reported symptom**: `gimo_get_trust_profile` returns `[]`, no trust data ever.

**Entry point**: MCP tool `gimo_get_trust_profile`

**Trace**:
  → `tools/gimo_server/mcp_bridge/governance_tools.py:88-111` — reads from trust engine
  → `tools/gimo_server/services/trust_engine.py:44-49` — `query_dimension()` reads from storage
  → Storage has `list_trust_events()` for reading
  → **No code anywhere calls `trust_engine.record()` or writes trust events**
  → Draft approval, run execution, tool evaluation — none of these write to trust

**Root cause**: Trust engine is read-only in practice. No operation writes trust events. The `record()` method exists but is never called during normal operation flows.

**Blast radius**: Trust is completely non-functional. The `effective_score: 0.85` is a hardcoded default, not a learned value.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `run_router.py` + `sagp_gateway.py` | Record trust events on: draft approval, run completion, run failure, evaluate_action calls | Low |

**Confidence**: HIGH

---

### [#11] Cost Compare Endpoint Wrong Method

**Reported symptom**: `POST /ops/cost/compare` returns 405 Method Not Allowed.

**Entry point**: HTTP API

**Trace**:
  → `tools/gimo_server/routers/legacy_ui_router.py:317-327`:
    - Endpoint is `GET /ui/cost/compare` with query params `model_a` and `model_b`
    - NOT `POST /ops/cost/compare` with JSON body
  → MCP tool `gimo_cost_compare` calls the wrong path/method

**Root cause**: The cost compare endpoint lives at `/ui/cost/compare` (GET with query params), but MCP tool expects `/ops/cost/compare` (POST with JSON body).

**Blast radius**: MCP cost comparison tool broken. HTTP clients must know to use the legacy `/ui/` path.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | New `/ops/cost/compare` POST endpoint | Create proper /ops/ endpoint that accepts JSON body | Very low |

**Confidence**: HIGH

---

### [#12] /ops/connectors/health 404

**Reported symptom**: `GET /ops/connectors/health` returns 404.

**Entry point**: HTTP API

**Trace**:
  → Searched all routers: no `/ops/connectors/health` endpoint
  → `provider_auth_router.py` — has auth endpoints, no health
  → `provider_service.py` — has internal health logic but not exposed via HTTP

**Root cause**: Endpoint never created. Health check logic exists internally but no router exposes it.

**Blast radius**: No HTTP way to check individual connector health. MCP tool `gimo_connectors_health` also fails.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `provider_auth_router.py` or new router | Add `GET /ops/connectors/health` that queries ProviderService | Very low |

**Confidence**: HIGH

---

### [#13] Budget Status Minimal Data

**Reported symptom**: Returns only `{"status": "active", "pricing_loaded": true}`.

**Entry point**: MCP tool `gimo_get_budget_status`

**Trace**:
  → `tools/gimo_server/mcp_bridge/governance_tools.py:202-219`:
    - Line 207: `CostService.load_pricing()`
    - Lines 208-212: Returns only `status`, `pricing_loaded`, `scope`
    - **Does NOT query**: `budget_forecast_service.py`, `cost_predictor.py`, actual spend data

**Root cause**: The MCP tool implementation is a stub — it loads pricing but doesn't query the budget forecast service or actual spend accumulation.

**Blast radius**: Budget monitoring via MCP is non-functional. No spend tracking, no alerts, no forecast.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `governance_tools.py:202-219` | Query BudgetForecastService for spend, remaining, forecast, alerts | Low |

**Confidence**: HIGH

---

### [#14] Mastery Analytics CLI Hangs

**Reported symptom**: `gimo mastery analytics` hangs indefinitely.

**Entry point**: `gimo_cli/commands/mastery.py:56-67`

**Trace**:
  → `gimo_cli/commands/mastery.py:56` — calls `api_request(config, "GET", "/ops/mastery/analytics", ...)`
  → `gimo_cli/api.py:130-146` — `smart_timeout()`:
    - Path `/ops/mastery/analytics` doesn't match any special patterns
    - Falls through to line 146: `float(hints.get("default_timeout_s", 30))`
    - Returns 30 seconds default
  → Server-side: `tools/gimo_server/routers/ops/mastery_router.py:283-301`:
    - Performs 8 expensive aggregation operations
    - May exceed 30 seconds with large datasets
  → CLI httpx client times out at 30s, but exception handling may swallow the error

**Root cause**: The `/mastery/analytics` path is not in the `smart_timeout()` special cases, so it gets 30s default. The server-side endpoint does expensive aggregation that can exceed this.

**Blast radius**: Only `gimo mastery analytics` command.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `api.py:130-146` | Add `/mastery/analytics` to the longer-timeout pattern match | Very low |

**Confidence**: HIGH

---

### [#15] Watch Command Produces Empty Output

**Reported symptom**: `gimo watch --timeout 5` returns empty output.

**Entry point**: `gimo_cli/commands/run.py:173-200`

**Trace**:
  → `gimo_cli/commands/run.py:173` — `watch()` calls `stream_events(config, timeout_seconds=...)`
  → `gimo_cli/stream.py:29-80` — `stream_events()`:
    - Line 26: `SSE_IDLE_TIMEOUT_SECONDS = 120`
    - Opens SSE connection to server
    - If no events received within idle timeout → ReadTimeout
    - Line 78-79: prints yellow warning about idle timeout
    - Generator exits without yielding anything
  → Back in `run.py:184-193` — loop over events receives nothing
  → `run.py:198-199` — outputs empty events list
  → **No "watching..." or "no activity" fallback message**

**Root cause**: When no events are received, the stream generator exits silently and the watch command outputs nothing. No user-facing feedback about what happened.

**Blast radius**: `gimo watch` always appears broken when there are no active events.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `run.py:173-200` | Add "Watching for events..." message on start + "No events in {timeout}s" on empty exit | Very low |

**Confidence**: HIGH

---

### [#16] Dashboard vs Snapshot Surface Type Mismatch

**Reported symptom**: Snapshot says `mcp_generic`, dashboard says `claude_app`.

**Entry point**: MCP tools `gimo_get_governance_snapshot` and `gimo_dashboard`

**Trace**:
  → `tools/gimo_server/mcp_bridge/governance_tools.py:124-126`:
    - `SurfaceIdentity(surface_type="mcp_generic", surface_name="mcp-governance-tool")`
  → `tools/gimo_server/mcp_bridge/mcp_app_dashboard.py:31-34`:
    - `SurfaceIdentity(surface_type="claude_app", surface_name="gimo-dashboard")`
  → `tools/gimo_server/services/sagp_gateway.py:152`:
    - `surface_type=surface.surface_type` — copies directly from input
  → Both tools hardcode different surface types instead of reading from request context

**Root cause**: Each MCP tool hardcodes its own `surface_type` string instead of deriving it from the actual calling surface.

**Blast radius**: Governance snapshots have inconsistent surface attribution. Could affect surface-specific policy decisions.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | Both files | Use a shared `get_mcp_surface_identity()` that returns consistent type based on actual caller | Very low |

**Confidence**: HIGH

---

### [#17] Child Run Never Executes

**Reported symptom**: Child run stays `pending` with `started_at: null` forever.

**Entry point**: `POST /ops/child-runs/spawn`

**Trace**:
  → `tools/gimo_server/services/child_run_service.py:42-53` — creates child run:
    - `validated_task_spec` is NOT set (not part of spawn payload)
  → RunWorker picks up pending child run via `_tick()` at `run_worker.py:128-132`
  → `tools/gimo_server/services/execution/run_worker.py:387-400` — Phase 5B gate:
    - Line 395: `task_spec = getattr(run, "validated_task_spec", None)` → **always None** for child runs
    - Line 396-400: `if not task_spec` → rejects run with "Missing ValidatedTaskSpec"
    - Sets status to "error"

**Root cause**: Phase 5B in RunWorker unconditionally requires `validated_task_spec`, but child runs created dynamically via `child-runs/spawn` never have one. The gate is designed for parent runs that go through plan generation, not for spawned child tasks.

**Blast radius**: ALL child runs. Multi-agent orchestration with parent-child hierarchies is completely broken.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `child_run_service.py:42-53` | Generate a minimal `validated_task_spec` at spawn time from prompt | Low |
| B (recommended) | `run_worker.py:394-400` | If run has `parent_run_id`, skip Phase 5B gate and use `child_prompt` directly | Low |

**Confidence**: HIGH

---

## Systemic Patterns

### Pattern 1: "Post-SAGP Regression in Execution Path"

**Issues**: #1, #2, #3, #4, #7, #17

GIMO's execution path was functional before the SAGP refactor (`f70c6e1`, April 5). The
SAGP was a necessary architectural change (Anthropic's April 2026 OAuth policy ban), but
it introduced regressions in the execution path:

- **#1/#2**: The `storage/__init__.py` was removed in an earlier cleanup (`e7b86c1`, Feb 24)
  as "dead re-export". It was fine at the time, but SAGP added new code paths (governance
  tools, proof chain) that import through `storage_service.py` which needs the `__init__.py`.
- **#4**: Windows temp file locking in `cli_account.py` — added in R9, worked in isolation,
  but fails under server load after SAGP changed provider routing.
- **#3/#17**: Run execution via Phase 5B gate — may have been working with the old provider
  paths but the SAGP adapter changes altered how runs are dispatched.
- **#7**: MCP `create_draft` inline generation — added in SAGP, uses a timeout-incompatible
  pattern.

The control plane (status, threads, drafts, trust queries, observability) is solid and
working correctly. The issues are concentrated in the **execution codepath** which was
disrupted by the SAGP migration.

**Key insight**: These are regression bugs from a major refactor, not fundamental
architectural problems. The system worked before and can work again with targeted fixes.

### Pattern 2: "MCP/HTTP Asymmetry"

**Issues**: #7, #9, #11, #12, #16

MCP tools and HTTP endpoints often do different things for the same operation:
- `gimo_create_draft` (MCP) does inline plan generation; `POST /ops/drafts` (HTTP) doesn't
- Cost compare is at `/ui/cost/compare` (GET) but MCP expects `/ops/cost/compare` (POST)
- Governance tools are MCP-only with no HTTP equivalent
- Surface types are hardcoded per tool instead of derived from context

**Future risk**: Each new feature will need to maintain two implementations (MCP + HTTP), increasing drift. Without a single source of truth for operation dispatch, parity will get worse.

### Pattern 3: "Silent Failure Antipattern"

**Issues**: #1, #3, #4, #14, #15

Multiple components fail silently without user feedback:
- MCP bridge crashes with no recovery (#1)
- Runs fail in fire-and-forget tasks (#3)
- CLI commands hang without progress indicators (#4)
- Mastery analytics times out silently (#14)
- Watch exits with no message (#15)

**Future risk**: Users will lose trust in the system because they can't distinguish "working slowly" from "broken". Every async operation needs a feedback channel.

---

## Dependency Graph

```
Missing storage/__init__.py (#1, #2)
    └── MCP bridge crash (#1)
    └── Proof chain broken (#2)
    └── Trust queries may fail (#10 partial)

Run execution broken (#3)
    ├── Fire-and-forget task pattern
    ├── Phase 5B gate rejects simple runs
    └── Child runs also blocked (#17)

Provider timeout chain (#4, #7)
    ├── No server-side timeout on generate()
    ├── CLI plan/chat hangs (#4)
    ├── MCP create_draft times out (#7)
    └── Mastery analytics hangs (#14) [same timeout pattern]

Data plane never writes (#10, #13)
    ├── Trust never recorded (#10)
    └── Budget never accumulated (#13)

Endpoint gaps (#8, #9, #11, #12)
    ├── SSE events missing (#8)
    ├── /ops/openapi path mismatch (#9)
    ├── Cost compare wrong method (#11)
    └── Connectors health missing (#12)
```

---

## Preventive Findings

1. **No integration test for MCP→HTTP→Provider roundtrip**: A test that calls an MCP tool which triggers an HTTP call which calls a provider would have caught #1, #3, #4, #7.

2. **No "write-side" tests**: Tests exist for reading state but not for accumulating state over time (trust, budget, cost).

3. **No MCP bridge health check**: The bridge process has no liveness probe. If it crashes, nothing detects or recovers it.

4. **No timeout budget enforcement**: Individual timeouts exist (MCP 30s, CLI 180s, provider 300s) but there's no coordinated timeout strategy. The outermost caller should have the shortest timeout, not the longest.

---

## Recommended Fix Priority

| Priority | Issues | Rationale |
|----------|--------|-----------|
| P0 | #1 + #2 (storage `__init__.py`) | One-line fix, unblocks ALL MCP tools |
| P0 | #3 + #17 (run execution) | Core feature completely broken |
| P1 | #4 + #7 (provider timeouts) | Plan/chat are primary user flows |
| P1 | #5 (auth/check) | Simple fix, high visibility |
| P1 | #10 (trust writes) | Trust is a core governance promise |
| P2 | #8 (SSE events) | Needed for real-time monitoring |
| P2 | #13 (budget data) | Needed for cost governance |
| P2 | #11, #12 (endpoint gaps) | Surface parity |
| P3 | #6 (GICS), #9, #14, #15, #16 | Polish and consistency |
