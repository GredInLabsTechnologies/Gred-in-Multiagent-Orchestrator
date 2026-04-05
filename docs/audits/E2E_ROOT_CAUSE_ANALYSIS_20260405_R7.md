# GIMO R7 — Phase 2: Root Cause Analysis

**Date**: 2026-04-05
**Auditor**: Claude Opus 4.6
**Scope**: 13 issues from Phase 1 stress test
**Method**: Source code tracing via parallel investigation agents

---

## Key Finding: R6 Fixes ARE in the Code

6 of 12 R6 fixes appeared to regress in Phase 1 testing. Investigation reveals:

| Fix | Code Present? | Why It Still Fails |
|-----|--------------|-------------------|
| C2: `gimo up` lifespan | YES | The lifespan fix works, but the CLI `up` command never gets there (subprocess spawning issue) |
| C3: smart_timeout | YES | `/approve` path not covered by `operation_timeouts`, falls to 15s default |
| C5c: skills body | YES | 422 fixed, but CLI checks `== 200` instead of `2xx` |
| C5d: repos registry-only | YES | Code is correct — need to verify if stale server process was running old code |
| C6: model metadata | PARTIAL | `model_pricing.json` enriched, `ModelInventoryService` has fallback, but `ProviderCatalogService.get_catalog()` doesn't enrich from pricing |
| C7a: trust reset operator | YES | Code says `_require_role(auth, "operator")` — may have been stale server |

**Conclusion**: Issues #2 (repos) and #7 (trust reset) were likely caused by the stale server process (PID 36576) running pre-R6 bytecode. The other 4 have genuine code-level root causes.

---

## Root Cause Analysis — All 13 Issues

### #1 BLOCKER — `gimo up` hangs indefinitely

**Location**: `gimo_cli/commands/server.py:284-333`

**Chain**:
1. `up()` calls `start_server()` which spawns subprocess with proper Windows flags (CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW)
2. Parent polls `/ready` endpoint repeatedly (lines 322-333)
3. The spawned server's lifespan handler runs `SubAgentManager.startup_reconcile()` wrapped in `asyncio.wait_for(timeout=10.0)` — this is the R6/C2 fix
4. But `sync_with_ollama()` → `ensure_ollama_ready()` spawns `ollama serve` and polls for 30 seconds
5. Even with the 10s timeout, the subprocess itself might hang on Windows due to pipe/handle inheritance

**Root cause**: The subprocess spawning mechanism in `start_server()` may have stdout/stderr pipe issues on Windows. If the server process writes to a pipe that nobody reads, it blocks. Additionally, the `ensure_ollama_ready()` 30-second poll loop exceeds the 10-second `wait_for` timeout, so `asyncio.TimeoutError` fires — but if the asyncio event loop itself is blocked by a sync subprocess call, the timeout won't fire.

**Fix**: Add individual timeouts to each Ollama call inside `sync_with_ollama()`, and ensure subprocess stdout/stderr in `start_server()` are properly redirected to DEVNULL (not captured pipes).

---

### #2 REGRESSION — `repos list` still shows filesystem repos

**Location**: `tools/gimo_server/routers/ops/repo_router.py:51-92`

**Root cause**: The R6 fix IS present in the code. The `list_repos()` function reads only from registry + current workspace header. **The test ran against a stale server process (PID 36576) that was started before R6 commit 1cc545a.**

**Fix**: Not a code issue. Restarting the server with current code should resolve this. Verified after manual restart.

---

### #3 BUG — `skills run` shows "Execution failed (201)"

**Location**: `gimo_cli/commands/skills.py:61`

```python
if status_code == 200:
    console.print(f"[green]Skill '{skill_id}' executed successfully.[/green]")
```

**Root cause**: CLI only checks `== 200`. HTTP 201 (Created) is a success code for resource creation but falls through to the error branch.

**Fix**: Change to `if 200 <= status_code < 300:` or `if status_code in (200, 201):`.

---

### #4 REGRESSION — `providers models` shows None metadata

**Location**: `tools/gimo_server/services/provider_catalog/_remote.py:184-208`

**Root cause**: R6/C6 enriched `ModelInventoryService` with pricing fallback, but the CLI `providers models` command calls `ProviderCatalogService.get_catalog()` which builds `NormalizedModelInfo` from `list_available_models()` and `list_installed_models()`. These methods don't populate `context_window` or `quality_tier`. Only `recommended_models` includes them.

The fix was applied to the wrong service — `ModelInventoryService` was enriched but `ProviderCatalogService` (which the CLI actually calls) was not.

**Fix**: Enrich `available_models` and `installed_models` in `get_catalog()` with fallback from `model_pricing.json`.

---

### #5 CRITICAL — `run` falsely reports "Server not reachable"

**Location**: `gimo_cli/api.py:130-143`

**Root cause**: `smart_timeout()` checks `operation_timeouts` patterns via substring matching. The approve path (`/ops/drafts/{id}/approve?auto_run=true`) doesn't match any pattern in `operation_timeouts` (`/approve`, `/execute`, `/chat`, etc.). Actually wait — `/approve` IS in `operation_timeouts` and IS a substring of the approve URL.

Re-checking: The `operation_timeouts` dict has key `"/approve"` with value `180.0`. The path `/ops/drafts/{id}/approve` contains `"/approve"`. So `smart_timeout()` should return `180.0`.

**Revised root cause**: The timeout may be working correctly for `/approve`. The "Server not reachable" message might come from a different code path — the health check BEFORE submitting the run. Check `gimo_cli/commands/run.py` for a pre-flight health check with a hardcoded short timeout.

The run command likely does:
1. Pre-flight health check → uses default 15s or shorter timeout
2. Approve call → uses 180s (correct)
3. Run start → uses 180s (correct)
4. Watch SSE → no timeout (correct)

If step 1 or the watch SSE initial connection times out, it reports "Server not reachable".

**Fix**: Ensure the run command's health check and SSE connection use appropriate timeouts.

---

### #6 GAP — Run logs say "Stage failed" with no detail

**Location**: `tools/gimo_server/services/custom_plan_service.py` (cascade error propagation)

**Root cause**: R6/C4 improved `_has_failed_dependency()` to return the root error. But the run-level log only records "Stage failed" without including the task-level error. The cascade context exists at the task/node level but doesn't propagate up to the run log.

**Fix**: When a stage fails, include the task ID and first-line error in the run log entry.

---

### #7 REGRESSION — `trust reset` still 403

**Location**: `tools/gimo_server/routers/ops/trust_router.py:102`

**Root cause**: Same as #2 — the fix IS present (`_require_role(auth, "operator")`). The test ran against a stale server. Restarting should resolve this.

**Fix**: Not a code issue.

---

### #8 GAP — `audit` Dependencies always fails

**Location**:
- CLI: `gimo_cli/commands/ops.py:211` → calls `/ops/system/dependencies`
- Router: `tools/gimo_server/routers/ops/dependencies_router.py`

**Root cause**: The endpoint EXISTS at `/ops/system/dependencies` (not `/ops/security/dependencies`). The Phase 1 direct API test hit the wrong path (`/ops/security/dependencies` → 404). The CLI hits the correct path but the endpoint itself returns 500 due to an internal error in the dependency scanning logic.

**Fix**: Investigate the actual 500 error inside `dependencies_router.py`. The endpoint exists but throws an unhandled exception.

---

### #9 GAP — `capabilities` returns null active_model/provider

**Location**: `tools/gimo_server/services/capabilities_service.py:60-71`

```python
cfg = ProviderService.get_config()
if cfg and cfg.active_provider:  # ← "active_provider" doesn't exist on ProviderConfig
    active_provider = cfg.active_provider
```

**Root cause**: `ProviderConfig` model has field `active` (not `active_provider`) and `orchestrator_provider` (derived from roles). The capabilities service tries to read `cfg.active_provider` which doesn't exist, exception is caught silently, returns null.

`OperatorStatusService` handles this correctly using `cfg.primary_orchestrator_binding()` with fallback to `cfg.active`.

**Fix**: Use the same pattern as `OperatorStatusService`:
```python
binding = cfg.primary_orchestrator_binding()
if binding:
    active_provider = binding.provider_id
    active_model = binding.model
elif cfg.active:
    active_provider = cfg.active
    active_model = cfg.providers.get(cfg.active, {}).configured_model_id()
```

---

### #10 GAP — `system_load: critical` and `generation: degraded`

**Location**: `tools/gimo_server/services/hardware_monitor_service.py:21-25, 227-236`

**Root cause (system_load)**: Thresholds are CPU ≥ 92% or RAM ≥ 93% for "critical". On a Windows dev machine with background services, these are easily hit during spikes. The 10-second monitoring interval means a single spike triggers "critical".

**Root cause (generation)**: `capabilities_service.py:82`:
```python
generation_health = "ok" if active_provider else "degraded"
```
Since `active_provider` is always null (Issue #9), `generation_health` is always "degraded".

**Fix**:
1. Generation: Fix #9 first — this cascades automatically
2. System load: Use moving average instead of point-in-time, or raise thresholds for dev environments

---

### #11 LOW — Graph node types swapped

**Location**: `tools/gimo_server/services/plan_graph_builder.py:121`

```python
"type": "bridge" if is_orchestrator else "orchestrator",
```

**Root cause**: Ternary is backwards. Assigns `"bridge"` to orchestrator nodes and `"orchestrator"` to workers.

**Fix**: Swap: `"type": "orchestrator" if is_orchestrator else "bridge"`

---

### #12 MEDIUM — Plan validation rejects some prompts

**Location**: `tools/gimo_server/services/custom_plan_service.py:400-405`

```python
orchestrators = [n for n in plan.nodes if n.is_orchestrator or n.node_type == "orchestrator" or n.role == "orchestrator"]
if len(orchestrators) != 1:
    raise ValueError("Plan must have exactly one orchestrator node")
```

**Root cause**: Orchestrator detection depends on `task_descriptor_service.py:158-161`:
```python
if "orchestr" in text or normalized.get("scope") == "bridge":
    task_type = "orchestrator"
```

If the LLM doesn't use "orchestrator" terminology in task descriptions, and routing doesn't assign orchestrator role, validation fails. This is fragile string matching.

**Fix**: Ensure the plan generation system prompt always instructs the LLM to mark exactly one task with `[ORCH]` prefix or `role: orchestrator`. Alternatively, if no orchestrator is detected, auto-promote the first task.

---

### #13 LOW — `hardware_state: critical` in mastery

**Root cause**: Same as #10 — `HardwareMonitorService` thresholds too aggressive for dev machines.

**Fix**: Same as #10.

---

## Dependency Graph

```
#9 (active_provider null)
 ├── #10b (generation: degraded)  ← cascades from #9
 └── #6 (run stage failures?)    ← possibly related

#10a (system_load: critical) = #13 (hardware_state: critical)
 └── Independent: psutil thresholds

#1 (gimo up) = Independent: Windows subprocess spawning

#5 (run timeout) = Need to verify exact code path

#2, #7 = Stale server (not code issues)

#3, #4, #8, #11, #12 = Independent code bugs
```

---

## Priority for Phase 3

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| P0 | #9 — capabilities active_provider null | Small (1 function) | Cascades to #10b, #6 |
| P0 | #11 — graph node types swapped | Trivial (1 line) | UI graph broken |
| P0 | #3 — skills run false failure | Trivial (1 line) | CLI UX |
| P1 | #5 — run timeout | Medium | Core workflow broken |
| P1 | #4 — model metadata enrichment | Medium | Provider display |
| P1 | #8 — audit dependencies 500 | Medium | Audit command broken |
| P1 | #12 — plan validation fragile | Medium | Plan generation reliability |
| P2 | #1 — gimo up hangs | Large (Windows-specific) | Startup UX |
| P2 | #6 — run log detail | Small | Error diagnostics |
| P2 | #10a/#13 — hardware thresholds | Small | False alarms |
