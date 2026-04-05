# PHASE 2 — Root-Cause Analysis (Round 6)

**Date**: 2026-04-05
**Input**: `gimo_prueba/AUDIT_LOG.md` (Phase 1, Round 6 — 16 issues)
**Method**: Full source-code tracing via CLI → API → Router → Service

---

## Traced issues: 16/16 from audit log
## New issues discovered: 2

## Issue Map

| ID | Category | Root cause location | Confidence |
|----|----------|-------------------|------------|
| 1 | BLOCKER | `services/sub_agent_manager.py:122` — Ollama sync hangs, blocks lifespan | HIGH |
| 2 | BLOCKER | `gimo_cli/api.py:131` — smart_timeout returns 15s for approve+run endpoint | HIGH |
| 3 | GAP | `services/execution/custom_plan_service.py:831` — AgenticLoopService.run_node() fails, cascade via `:566` | HIGH |
| 4 | GAP | `engine/tools/executor.py:110` — `_to_abs_path()` passes absolute paths through without workspace enforcement | HIGH |
| 5 | GAP | `gimo_cli/commands/chat_cmd.py:78` — thread creation sends no title param | HIGH |
| 6 | GAP | `services/providers/connector_service.py:236` — subprocess calls to CLI binaries fail; no try-catch in endpoint | HIGH |
| 7 | FRICTION | `gimo_cli/commands/providers.py:158` — auth-status call uses full ID `claude-account` but connector only knows `claude` | MEDIUM |
| 8 | FRICTION | Backend model inventory doesn't populate `quality_tier` or `context_window` metadata | MEDIUM |
| 9 | FRICTION | `services/git_service.py:54` — scans all dirs with `.git`, no managed/unmanaged distinction | HIGH |
| 10 | FRICTION | TUI status bar never hydrates — `tui_default` thread doesn't fetch operator status | MEDIUM |
| 11 | FRICTION | `gimo_cli/commands/run.py:161` — `stream_events` opens SSE with no idle timeout or empty-stream detection | LOW |
| 12 | FRICTION | `trust_router.py:95` — `_require_role(auth, "admin")` and no CLI path to escalate to admin | HIGH |
| 13 | ERROR | `gimo_cli/commands/skills.py:57` — sends no request body; endpoint requires `SkillExecuteRequest` | HIGH |
| 14 | INCONSISTENCY | `gimo_cli/bond.py` — dual auth path (CLI Bond vs Legacy Bond) with no user-facing explanation | LOW |
| 15 | COGNITIVE_LOAD | `chat_cmd.py` — missing `-w` flag; `plan` has it, `chat` doesn't | HIGH |
| 16 | SILENT_FAILURE | Same root as #2 — first request times out, retry works because server already processed it | HIGH |

---

## Detailed Traces

### [#1] BLOCKER — `gimo up` does not start the server

**Reported symptom**: `gimo up` prints "Starting GIMO server..." then hangs forever, server never becomes reachable.

**CLI entry point**: `gimo_cli/commands/server.py:340` → `up()` → `start_server()` (line 249)

**Readiness probe**: `start_server()` polls `GET /ready` (not `/health`) every 1 second for 90 iterations (line 322-326).

**Server endpoint**: `tools/gimo_server/main.py:522` — `/ready` checks `app.state.ready`. Returns 503 until `app.state.ready = True`.

**Where `app.state.ready` is set**: `tools/gimo_server/main.py:432` — at the END of the `lifespan()` context manager, after ALL services are initialized.

**Root cause**: `tools/gimo_server/services/sub_agent_manager.py:122-150` — `sync_with_ollama()` is called during lifespan startup (main.py:314 via `SubAgentManager.startup_reconcile()`). This method:
1. Calls `ProviderCatalogService._ollama_health()` (5s timeout) — fails silently if Ollama isn't running
2. Calls `ProviderCatalogService._ollama_list_installed()` which falls back to `ollama_cli_list()` — this uses `asyncio.create_subprocess_exec("ollama", "list")` with **NO TIMEOUT**
3. If the `ollama` binary exists but hangs (common on Windows), the subprocess blocks indefinitely
4. The lifespan never reaches `app.state.ready = True` (line 432)
5. `/ready` always returns 503
6. CLI gives up after 90 seconds

**Why it's silent**: The entire `sync_with_ollama()` is wrapped in `except Exception` that logs but doesn't propagate. Server stdout/stderr is redirected to `~/.gimo/server.log` (invisible to the user).

**Collateral findings**: If we start the server manually with `python -m uvicorn`, it works because the shell can be Ctrl+C'd and the subprocess inherits the terminal — but `gimo up` uses `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` (line 287-289) which detaches completely.

**Confidence**: HIGH

---

### [#2 + #16] BLOCKER — `gimo run` falsely reports server unreachable / silent first-attempt failure

**Reported symptom**: First `run` attempt fails with "Server not reachable / timed out", second identical attempt succeeds immediately.

**CLI entry point**: `gimo_cli/commands/run.py:45` → `api_request(config, "POST", f"/ops/drafts/{plan_id}/approve", params=query)`

**Timeout resolution**: `gimo_cli/api.py:130-137` — `smart_timeout()`:
```python
if any(p in path for p in ("/generate-plan", "/slice0", "/threads/")):
    return float(hints.get("generation_timeout_s", 180))
if "/stream" in path or "/chat" in path:
    return None
return float(hints.get("default_timeout_s", 15))
```

The path `/ops/drafts/{plan_id}/approve?auto_run=true` doesn't match any special pattern → default timeout = **15 seconds**.

**Root cause**: The approve+auto_run endpoint triggers plan approval AND run creation (which may involve LLM calls or heavy initialization). This takes >15 seconds. `httpx.TimeoutException` is caught at `api.py:225`, triggering `_try_auto_start()` which prompts "Start server? [Y/n]". If non-interactive or auto-start fails, returns 503.

**Why second attempt works**: The first request DID reach the server and triggered the approval. The client timed out but the server continued processing. By the time the second request arrives, the plan is already approved and the run is already created — so it returns instantly.

**Confidence**: HIGH

---

### [#3] GAP — Plan execution fails with cascading worker skips

**Reported symptom**: `watch` shows workers getting "skipped: upstream dependency failed", plan finishes with status "error", zero tokens consumed.

**Execution chain**:
1. `run_router.py:266` → `_spawn_run()` → `EngineService.execute_run()` (background task)
2. → `CustomPlanService.execute_plan()` → `_execute_plan_reserved()` (line 528)
3. → Layer-by-layer node execution (line 560)

**Cascade mechanism**: `custom_plan_service.py:516-517`:
```python
def _has_failed_dependency(cls, node, node_map):
    return any(node_map.get(dep) and node_map[dep].status in {"error", "skipped"} for dep in node.depends_on)
```

When any node fails, all downstream nodes are skipped (line 566-579).

**Initial failure**: `custom_plan_service.py:831-862` — `_execute_node()` calls `AgenticLoopService.run_node()` with 300s timeout. If the first node (orchestrator) fails due to LLM error, auth issue, or tool execution failure, the exception is caught and the node gets `status="error"`. All workers depending on it are immediately skipped.

**Root cause**: The orchestrator node fails silently — the error string is truncated to 500 chars and only visible in run state data, not in the SSE stream output. Zero tokens = the LLM was never successfully called, suggesting an auth/provider issue at the `AgenticLoopService` level.

**Confidence**: HIGH

---

### [#4] GAP — Chat writes files to CWD, not workspace

**CLI entry point**: `gimo_cli/commands/chat_cmd.py:78` — creates thread with `params={"workspace_root": "."}` (relative path ".")

**API layer**: `gimo_cli/api.py:213-214` sends `X-Gimo-Workspace` header set to `project_root()` (the GIMO repo root).

**Server-side**: The agentic loop receives `workspace_root` and passes it to `ToolExecutor` (`agentic_loop_service.py:713-720`).

**Path resolution**: `engine/tools/executor.py:110-113`:
```python
def _to_abs_path(self, path: str) -> str:
    if os.path.isabs(path):
        return os.path.abspath(path)
    return os.path.abspath(os.path.join(self.workspace_root, path))
```

**Root cause (dual)**:
1. `workspace_root` is resolved to the GIMO repo root (because the CLI sends `"."` which resolves to the project root). There's no concept of a "target workspace" in the chat flow.
2. Even if workspace_root were correct, `_to_abs_path()` passes absolute paths through without enforcing they're within the workspace boundary — a **security concern** (path traversal).

**Confidence**: HIGH

---

### [#5] GAP — Thread title always "New Conversation"

**CLI entry point**: `gimo_cli/commands/chat_cmd.py:78`:
```python
_, thread_data = api_request(config, "POST", "/ops/threads", params={"workspace_root": "."})
```

No title is sent — neither in the body nor as a query param.

**Server endpoint**: `conversation_router.py:72`:
```python
resolved_title = body.title or title or "New Conversation"
```

**Root cause**: The CLI doesn't send a title parameter. The server defaults to "New Conversation". There is no post-creation title inference from the first message.

**Confidence**: HIGH

---

### [#6] GAP — `audit` Dependencies returns 500

**CLI entry point**: `gimo_cli/commands/ops.py:204-238` — the `audit` command calls `GET /ops/system/dependencies`.

**Router**: `dependencies_router.py:14-22` — calls `ProviderService.list_cli_dependencies()`.

**Service chain**: `provider_service.py` → `ProviderConnectorService.list_cli_dependencies()` (`connector_service.py:236-255`).

**Root cause**: `connector_service.py:108-117` — `_resolve_cli_version()` creates async subprocesses to run CLI binaries (e.g., `ollama --version`, `git --version`). The method has `except Exception: return None` BUT the outer loop in `list_cli_dependencies()` may throw if:
1. `_create_process()` fails in a way not caught by the inner try-except
2. Model construction (`CliDependencyStatus`) fails validation
3. Any exception outside the per-dependency try-except propagates uncaught

The endpoint handler at `dependencies_router.py:20` has **no try-catch wrapper**, so any unhandled exception becomes a FastAPI 500.

**Confidence**: HIGH

---

### [#7] FRICTION — `providers test` shows "Auth status: unknown"

**CLI entry point**: `gimo_cli/commands/providers.py:158`:
```python
auth_code, auth_data = api_request(config, "GET", f"/ops/connectors/{provider_id}/auth-status")
```

When called as `providers test claude-account`, this hits `/ops/connectors/claude-account/auth-status`.

**Root cause**: The connector system uses base provider names (`claude`, `codex`) not the full account IDs (`claude-account`, `codex-account`). The auth-status endpoint returns 404 for `claude-account`, causing the CLI to fall through to `else: "Auth status: unknown"`.

Compare with `auth-status` command (line 314) which hardcodes `["codex", "claude"]` — those work.

**Confidence**: MEDIUM

---

### [#8] FRICTION — Model metadata shows None

**CLI entry point**: `gimo_cli/commands/providers.py:180` — calls `GET /ops/provider/models`.

**Root cause**: The model inventory service returns model records with `quality_tier: None` and `context_window: None`. These fields are defined in the model but never populated from the provider's catalog. The Anthropic API doesn't expose these metadata fields, and the inventory doesn't hardcode known values for standard models.

**Confidence**: MEDIUM

---

### [#9] FRICTION — `repos list` shows unmanaged repos

**CLI entry point**: `gimo_cli/commands/repos.py:19-28` → `GET /ops/repos`.

**Router**: `repo_router.py:51-117`.

**Service**: `git_service.py:54-62`:
```python
for item in root_dir.iterdir():
    if item.is_dir() and not item.name.startswith(".") and (item / ".git").exists():
        entries.append({"name": item.name, "path": str(item.resolve())})
```

**Root cause**: `GitService.list_repos()` scans `REPO_ROOT_DIR` (the parent directory of the current workspace) and returns ALL directories with a `.git` folder. The router then auto-registers these into the repo registry (lines 63-74). There is no distinction between "managed" and "discovered" repos.

**Confidence**: HIGH

---

### [#10] FRICTION — TUI status bar empty

**CLI entry point**: `gimo_cli/commands/chat_cmd.py:35-37` — creates `GimoApp(config=config, thread_id="tui_default")`.

**Root cause**: The TUI initializes with the `tui_default` thread ID but the status bar fetch likely depends on an operator status endpoint that either isn't called during initial mount or fails silently. The status bar fields (REPO, BRANCH, MODEL, etc.) are set to `-` as defaults and never updated within the startup window.

**Confidence**: MEDIUM

---

### [#11] FRICTION — `watch` hangs with no active run

**CLI entry point**: `gimo_cli/commands/run.py:161` → `stream_events(config)`.

**Root cause**: The SSE connection opens to the backend event stream. When no run is active, no events are emitted. The stream stays open indefinitely with no heartbeat, idle timeout, or "no active run" detection. The CLI has a `--limit` flag (default 10) but this counts received events — if zero events arrive, it waits forever.

**Confidence**: LOW

---

### [#12] FRICTION — Trust reset requires admin, no escalation path

**Server**: `trust_router.py:95-107` — `_require_role(auth, "admin")`.

**CLI token resolution**: `gimo_cli/api.py:42-108` — for role="operator", the CLI resolves tokens in order: CLI Bond → env vars → Legacy Bond → inline config → credential files. The token in `.orch_token` resolves as "admin" role, but the Legacy Bond (the one that works) stores role="operator".

**Root cause**: The CLI uses the Legacy Bond which has role="operator". The trust reset endpoint requires "admin". There's no `gimo` command to escalate role or re-bond as admin.

**Confidence**: HIGH

---

### [#13] ERROR — `skills run` sends no body (422)

**CLI entry point**: `gimo_cli/commands/skills.py:57`:
```python
status_code, payload = api_request(config, "POST", f"/ops/skills/{skill_id}/execute")
```

No `json_body` parameter is passed.

**Server endpoint**: `skills_router.py:179` requires `body: SkillExecuteRequest`.

**Model**: `SkillExecuteRequest` has `replace_graph: bool = False` and `context: Dict = {}` — both have defaults, but FastAPI requires the body to be present (not null).

**Root cause**: CLI sends POST with no body → FastAPI cannot parse `SkillExecuteRequest` from null body → 422.

**Fix**: CLI needs `json_body={}` to send an empty JSON object.

**Confidence**: HIGH

---

### [#14] INCONSISTENCY — Dual bond/auth display

**Root cause**: `gimo_cli/bond.py` implements two auth systems:
1. CLI Bond (new, identity-first, not yet fully implemented) — checked first by `resolve_bond_token()`
2. Legacy Bond (YAML-based, working) — fallback

`doctor` surfaces both, showing the new system as "not configured" and the legacy as "valid". No explanation is provided to the user about which matters.

**Confidence**: LOW

---

### [#15] COGNITIVE_LOAD — No `-w` flag on chat

**Root cause**: `gimo_cli/commands/chat_cmd.py:41-46` — the `chat` command defines `--message`, `--thread`, `--execute` but no `--workspace`. The `plan` command (in `plan.py`) does have `-w/--workspace`. This is a design omission — the workspace targeting feature wasn't extended to the chat flow.

**Confidence**: HIGH

---

## New Issues Discovered During Tracing

### [NEW-1] SECURITY — `_to_abs_path()` allows path traversal outside workspace

**Location**: `engine/tools/executor.py:110-113`

The `write_file` tool's `_to_abs_path()` method passes absolute paths through without validating they're within `workspace_root`. An LLM could write to any location the server process has write access to by providing an absolute path like `/etc/passwd` or `C:\Windows\System32\...`.

**Severity**: HIGH (security vulnerability)
**Confidence**: HIGH

### [NEW-2] RACE — `api_request` auto-start creates double-execution

**Location**: `gimo_cli/api.py:225-235`

When a request times out, `_try_auto_start` may attempt to start a new server. But the original server is still running (it was just slow). If auto-start succeeds, there could be two server instances. More critically, the retry (line 230-231) may hit the server after it already processed the original request (which timed out on the client side), causing double-execution of side-effectful operations like plan approval.

**Severity**: MEDIUM
**Confidence**: MEDIUM

---

## Systemic Patterns

### Pattern A: Missing timeout protection (4 issues: #1, #2, #6, #11)

Four issues trace back to missing or inadequate timeouts:
- `sync_with_ollama()` subprocess has NO timeout → blocks lifespan (#1)
- `smart_timeout()` returns 15s for long operations → false unreachable (#2)
- `_resolve_cli_version()` subprocess timeout exists but outer loop doesn't → 500 (#6)
- SSE stream has no idle timeout → infinite hang (#11)

### Pattern B: CLI-to-API contract mismatch (4 issues: #5, #7, #13, #15)

The CLI and server have inconsistent contracts:
- Thread creation sends no title (#5)
- Provider test uses full ID but connector expects base name (#7)
- Skills run sends no body but endpoint requires one (#13)
- Chat has no workspace flag but plan does (#15)

### Pattern C: Silent failure with no user feedback (4 issues: #1, #3, #6, #16)

Operations fail but the user gets no actionable information:
- `gimo up` blocks forever with no log hint (#1)
- Worker cascade failures show no root error (#3)
- Dependencies 500 with no diagnostic (#6)
- First run attempt fails silently, second works (#16)

### Pattern D: Workspace identity crisis (3 issues: #4, #9, #15)

The system has no clear concept of "which workspace am I operating on":
- Chat writes to server CWD (#4)
- Repos list shows everything on disk (#9)
- No workspace flag on chat (#15)

## Dependency Graph

```
#1 (gimo up) ← Ollama sync timeout
    └→ #2/#16 (run unreachable) ← smart_timeout too low
        └→ #3 (cascading failures) ← initial worker fails, cascade opaque

#4 (write to CWD) ← workspace not passed to chat
    ├→ #15 (no -w flag) ← design omission
    └→ #9 (repos list) ← no managed vs discovered distinction
    └→ NEW-1 (path traversal) ← _to_abs_path security hole

#5 (no title) ← CLI sends no title
#6 (deps 500) ← subprocess + no error handling
#7 (auth unknown) ← ID mismatch
#8 (None metadata) ← inventory not enriched
#10 (TUI empty) ← status fetch not wired
#11 (watch hangs) ← no idle detection
#12 (trust 403) ← no role escalation
#13 (skills 422) ← no body sent
#14 (dual bond) ← unfinished migration

Solving #1 also improves: #2, #16
Solving workspace identity: #4, #9, #15, NEW-1
Solving CLI-API contracts: #5, #7, #13
```
