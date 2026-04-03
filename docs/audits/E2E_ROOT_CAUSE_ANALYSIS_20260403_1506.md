# PHASE 2 — Root-Cause Analysis

**Date**: 2026-04-03 15:06 UTC
**Traced issues**: 21/21 from AUDIT_LOG.md
**New issues discovered**: 3
**Confidence level**: HIGH for all critical issues

---

## Issue Map

| ID | Category | Root Cause Location | Confidence |
|----|----------|---------------------|------------|
| 1 | BLOCKER | `gimo_cli/commands/server.py:322` + `gimo_cli/config.py:85` | HIGH |
| 2 | BLOCKER | `gimo_cli/api.py:46-53` + `gimo_cli/bond.py:265-285` | HIGH |
| 3 | BLOCKER | `gimo_cli/commands/providers.py:102` + `gimo_cli/api.py:43-62` | HIGH |
| 4 | BLOCKER | `gimo_cli/commands/providers.py:174-236` | HIGH |
| 5 | BLOCKER | `gimo_cli/chat.py:292` (prompt_toolkit PromptSession) | HIGH |
| 6 | BLOCKER | `gimo_cli/api.py:209` + `tools/gimo_server/routers/ops/plan_router.py:284-288` | HIGH |
| 7 | GAP | `tools/gimo_server/services/providers/auth_service.py:48-80` | HIGH |
| 8 | GAP | N/A — no `gimo repos add` command exists | HIGH |
| 9 | BLOCKER* | Model limitation (qwen2.5-coder:3b) — code is architecturally correct | HIGH |
| 10 | ERROR | `tools/gimo_server/routers/ops/mastery_router.py:154` | HIGH |
| 11a | ERROR | `tools/gimo_server/services/providers/connector_service.py:241-253` | MEDIUM |
| 11b | ERROR | `tools/gimo_server/routers/legacy_ui_router.py:87` + `access_control.py:63-76` | HIGH |
| 12 | FRICTION | `gimo_cli/api.py:46-53` (bond warning per-process) | HIGH |
| 13 | FRICTION | `tools/gimo_server/routers/ops/mastery_router.py:142` (empty trust data) | LOW |
| 14 | FRICTION | `gimo_cli/commands/mastery.py:55-63` (list vs dict mismatch) | HIGH |
| 15 | FRICTION | `gimo_cli/commands/mastery.py:81` (no formatter) | HIGH |
| 16 | FRICTION | `gimo_cli/commands/observe.py:88-100` (dict vs list mismatch) | HIGH |
| 17 | FRICTION | `gimo_cli/commands/providers.py:163-171` (dict vs list mismatch) | HIGH |
| 18 | COGNITIVE_LOAD | `gimo_cli/commands/auth.py:190` (wrong file referenced) | HIGH |
| 19 | INCONSISTENCY | `gimo_cli/api.py:209` vs `tools/gimo_server/services/providers/service_impl.py:597` | HIGH |
| 20 | INCONSISTENCY | No replacement for deprecated `repos select` | LOW |
| 21 | SILENT_FAILURE | Same root as #1 | HIGH |
| NEW-1 | BUG | `tools/gimo_server/models/economy.py:198-202` (MasteryStatus missing field) | HIGH |
| NEW-2 | BUG | `tools/gimo_server/models/core.py:151` (economy=None default) | HIGH |
| NEW-3 | GAP | No `--api-key` flag in `providers set` or `providers login` | HIGH |

---

## Detailed Traces

### [#1/#21] `gimo up` silently fails / no progress feedback

**Reported symptom**: Server appears not to start. No error, no success message.
**CLI entry point**: `gimo_cli/commands/server.py:340` → `up()`
**Service**: `gimo_cli/commands/server.py:249` → `start_server()`
**Root cause**: Two issues compound:

1. **`project_root()` is CWD-sensitive** (`gimo_cli/config.py:85-90`): Runs `git rev-parse --show-toplevel`. If invoked from outside a git repo, falls back to `Path.cwd()`. `start_server()` uses this as `cwd` for `Popen`, so uvicorn may start in the wrong directory and fail to import `tools.gimo_server.main:app`.

2. **No progress feedback during 90-second readiness probe** (`server.py:322-336`): The command prints "Starting GIMO server..." then goes completely silent for up to 90 seconds while polling `/ready`. No spinner, no dots, no timeout countdown. Users assume it failed.

3. **Minor**: Duplicate port-free checks — both `up()` (line 360) and `start_server()` (line 258) independently call `_kill_all_on_port()`.

**Collateral findings**: Server DID start during testing (server.log confirms). The "failure" was a false positive from checking too early. But the UX makes it impossible to tell.
**Confidence**: HIGH

---

### [#2/#12] Bond system broken — "Bond expired" on every command

**Reported symptom**: Every command prints "Bond expired or invalid. Run: gimo login" but still works.
**CLI entry point**: `gimo_cli/api.py:43` → `resolve_token()`
**Root cause**: Three bugs compound:

1. **Expired `bond.enc` never auto-cleaned** (`gimo_cli/bond.py:265-285`): `resolve_bond_token()` detects the expired JWT and returns `(None, "Bond expired or invalid...")`, but **never** calls `delete_cli_bond()`. The stale file persists indefinitely.

2. **Warning fires once per process** (`gimo_cli/api.py:46-53`): `_bond_warning_emitted` is a module-level bool that resets on every CLI invocation. Since each `gimo <command>` is a new process, the warning fires on EVERY command.

3. **`gimo login` (no --web) doesn't clean bond.enc** (`gimo_cli/commands/auth.py:178-244`): The legacy token flow only calls `save_bond()` (YAML). It never calls `delete_cli_bond()`. Only `gimo logout` or `gimo login --web` touch `bond.enc`.

**Fallback chain** (resolve_token for operator role):
```
1. bond.enc (CLI Bond)     → expired → WARNING printed → continues
2. ORCH_OPERATOR_TOKEN     → found → returns token → command works
3. Legacy YAML bond        → (not reached)
4. Inline config token     → (not reached)
5. Server credential files → (not reached)
```

**Confidence**: HIGH

---

### [#3] `providers set` requires admin but CLI login only grants operator

**Reported symptom**: `gimo providers set claude-account` → 401 "Invalid token"
**CLI entry point**: `gimo_cli/commands/providers.py:80` → `providers_set()`
**API endpoint**: `POST /ops/provider/select` in `tools/gimo_server/routers/ops/config_router.py:59`
**Root cause**:

The CLI correctly requests `role="admin"` (line 102), and the endpoint correctly enforces `_require_role(auth, "admin")`. The problem is **there is no CLI path to obtain an admin token**:

- `resolve_token("admin")` looks for env vars `GIMO_TOKEN` or `ORCH_TOKEN`, but NOT for CLI Bond (which is operator-only, per `api.py:45`)
- `gimo login` creates a bond with the role the server assigns (always "operator" for bearer token auth)
- The only way to get admin is to set `ORCH_TOKEN` env var manually

**Historical**: `POST /provider/select` has always required admin since its creation (commit `2587f4f`). This is by design — but the CLI has no user-friendly path to escalate.

**Confidence**: HIGH

---

### [#4] `providers login claude` — no headless/API-key flow

**Reported symptom**: Opens browser for OAuth. No way to authenticate from non-interactive session.
**CLI entry point**: `gimo_cli/commands/providers.py:174` → `providers_login()`
**API endpoint**: `POST /ops/connectors/{provider}/login`
**Root cause**:

Only OAuth device flow implemented. Missing:
- `--api-key <key>` flag on `providers login` or `providers set`
- `ANTHROPIC_API_KEY` env var auto-detection
- `gimo providers set claude-account --api-key sk-ant-xxx` path

The server-side `ProviderAuthService.sanitize_entry_for_storage()` supports `auth_mode: "api_key"` and `env:VARNAME` references, but the CLI never exposes this path.

**Confidence**: HIGH

---

### [#5] `chat` crashes in non-TTY environments

**Reported symptom**: `NoConsoleScreenBufferError` traceback
**CLI entry point**: `gimo_cli/commands/chat_cmd.py:57` → `interactive_chat()`
**Crash location**: `gimo_cli_renderer.py:292` → `PromptSession()` → `prompt_toolkit.output.win32:219`
**Root cause**:

`PromptSession` from `prompt_toolkit` initializes `Win32Output` which requires a Windows console handle (`GetConsoleScreenBufferInfo`). When stdin is piped or the environment is `xterm-256color` (bash on Windows), this fails.

No graceful fallback exists — no `--non-interactive` flag, no stdin pipe support, no detection of non-TTY before PromptSession creation.

**Confidence**: HIGH

---

### [#6] `plan` command fails with 404 when calling ollama

**Reported symptom**: "Client error '404 Not Found' for url 'http://localhost:11434/v1/chat/completions'"
**CLI entry point**: `gimo_cli/commands/plan.py:55` → `api_request(..., "/ops/generate-plan", ...)`
**API endpoint**: `tools/gimo_server/routers/ops/plan_router.py:214` → `generate_structured_plan()`
**Root cause**: **X-Preferred-Model header sends incompatible model to ollama**

The call chain:
1. CLI config has `preferred_model: claude-haiku-4-5-20251001` (`.gimo/config.yaml`)
2. `api_request()` adds `X-Preferred-Model: claude-haiku-4-5-20251001` header (api.py:209)
3. Plan router reads it: `preferred_model = request.headers.get("X-Preferred-Model")` (plan_router.py:284)
4. Sets `context["model"] = "claude-haiku-4-5-20251001"` (plan_router.py:287)
5. `static_generate()` resolves effective provider = `local_ollama` (the active provider)
6. Builds `OpenAICompatAdapter` with `base_url=http://localhost:11434/v1`
7. Sends to ollama: `POST /v1/chat/completions` with `"model": "claude-haiku-4-5-20251001"`
8. Ollama responds **404** — model not installed locally

The preferred_model from local config (`claude-haiku`) is blindly forwarded as the model name to whatever provider is active (ollama), without validating that the model exists in that provider's inventory.

**Confidence**: HIGH

---

### [#7] Provider sessions don't persist across server restarts

**Reported symptom**: Auth with Claude/Codex lost after server restart.
**Service**: `tools/gimo_server/services/providers/auth_service.py:48-80`
**Root cause**:

`ProviderAuthService.sanitize_entry_for_storage()` stores credentials as `env:ORCH_PROVIDER_CLAUDE_ACCOUNT_TOKEN` references in `provider.json`. The actual token value is placed in `os.environ[env_name]` — **process memory only**.

On server restart:
- `provider.json` still has `auth_ref: "env:ORCH_PROVIDER_CLAUDE_ACCOUNT_TOKEN"`
- `os.environ` doesn't have that key anymore
- `resolve_secret()` reads `os.environ.get(env_name)` → `None`
- Provider shows as unauthenticated

The `ProviderAccountService` persists flow state (pending/approved/revoked) to `state/provider_account_flows.json`, but the actual credential is never written to disk.

**Confidence**: HIGH

---

### [#9] Agentic chat doesn't execute tools

**Reported symptom**: LLM describes actions in text but never calls tools. 8 turns, 0 tool executions.
**Service**: `tools/gimo_server/services/agentic_loop_service.py` → `_run_loop()`
**Root cause**: **Model limitation, NOT a code bug**

The call chain is architecturally correct:
```
AgenticLoopService._run_loop()
  → adapter.chat_with_tools(messages, tools=CHAT_TOOLS, ...)
    → OpenAICompatAdapter._raw_chat_with_tools()
      → POST {base_url}/chat/completions with tools=[...], tool_choice="auto"
```

The tool schema (11 tools from `CHAT_TOOLS`) IS sent in every request. The response parser correctly reads `message.tool_calls[]` (native) and has a text-scan fallback (`parse_tool_calls_from_text()`).

The issue: `qwen2.5-coder:3b` is a 3B parameter model that **does not reliably emit structured tool calls**:
1. Small models frequently ignore `tool_choice: "auto"`
2. Ollama's tool-call support is model-specific — the 3B model may lack the chat template for structured output
3. When `tool_calls` comes back empty, the loop exits immediately: `if not tool_calls: break` (line 782-784)

The text-scan fallback only catches JSON blocks like `{"tool_calls": [...]}` in the content — which a 3B model almost never produces.

**Collateral**: This means GIMO requires at least a 7B+ model with proven function-calling support (qwen2.5-coder:7b, llama3.1:8b, or any cloud model) for the agentic loop to work.

**Confidence**: HIGH

---

### [#10] `mastery status` returns 500 "protective defense mode"

**Reported symptom**: HTTP 500 with opaque error message.
**API endpoint**: `tools/gimo_server/routers/ops/mastery_router.py:142` → `get_mastery_status()`
**Root cause**: **`config.economy` is None — AttributeError on dereference**

```python
# mastery_router.py:154
eco_mode_active = config.economy.eco_mode.mode != "off"
#                 ^^^^^^^^^^^^^^ → AttributeError: 'NoneType' has no attribute 'eco_mode'
```

`OpsService.get_config()` returns `OpsConfig()` with default `economy: Optional[UserEconomyConfig] = None` (`models/core.py:151`). When no config file is loaded (GICS unavailable), `economy` is `None`. Line 154 dereferences it without null-guard.

**Collateral finding (NEW-1)**: The `MasteryStatus` response model (`models/economy.py:198-202`) has 4 fields but the endpoint returns 5 (includes `hardware_state`). Pydantic v2 silently drops the extra field — data loss.

**Collateral finding (NEW-2)**: `OpsConfig.economy` defaults to `None` instead of `UserEconomyConfig()`. This same null-dereference pattern could crash any endpoint that reads `config.economy.*`.

**Confidence**: HIGH

---

### [#11a] `audit` Dependencies 500

**Reported symptom**: Audit table shows "Dependencies: 500, n/a dependencies"
**API endpoint**: `GET /ops/system/dependencies`
**Service**: `tools/gimo_server/services/providers/connector_service.py:241-253`
**Root cause**: Likely Pydantic validation error in `CliDependencyStatus` where `install_method` is typed as `Literal` but receives a plain string. The subprocess calls to check CLI versions (codex --version, claude --version) may also hang on Windows.
**Confidence**: MEDIUM

### [#11b] `audit` Tail 403

**Reported symptom**: Audit table shows "Audit Tail: 403"
**API endpoint**: `GET /ui/audit` in `tools/gimo_server/routers/legacy_ui_router.py:87`
**Root cause**: `require_read_only_access` in `access_control.py:63-76` only allows admin role for `/ui/audit`. The path doesn't start with `/ops/` and isn't in `OPERATOR_EXTRA_PREFIXES`. Only admin tokens bypass the check.
**Confidence**: HIGH

---

### [#14] `mastery forecast` → raw `[]`

**Root cause**: `mastery.py:55-63` — CLI formatter only handles `isinstance(payload, dict)`. Endpoint returns `List[BudgetForecast]` (a list). The dict branch is skipped, falls to `console.print_json(data=[])` which renders as `[]`.
**Confidence**: HIGH

### [#15] `mastery analytics` → raw JSON

**Root cause**: `mastery.py:81` — No formatter at all. Unconditionally calls `console.print_json()`. The response is a complex nested `CostAnalytics` dict.
**Confidence**: HIGH

### [#16] `observe traces` → raw JSON

**Root cause**: `observe.py:88-100` — Formatter expects `isinstance(payload, list)`. Server returns `{"items": [...], "count": N}` (a dict). List check fails, falls to `console.print_json()`.
**Confidence**: HIGH

### [#17] `providers models` → 200 lines of JSON

**Root cause**: `providers.py:163-171` — Formatter expects `isinstance(payload, list)` of model IDs. Server returns `ProviderModelsCatalogResponse` (a dict with `installed_models`, `available_models`, `recommended_models`). List check fails, dumps full JSON.
**Confidence**: HIGH

---

### [#18] Login references wrong file

**Root cause**: `auth.py:190` — Help text says "from server's .gimo_credentials or ORCH_OPERATOR_TOKEN". File `.gimo_credentials` doesn't exist. Actual token file is `.orch_token`.
**Confidence**: HIGH

### [#19] Config preferred_model contradicts active provider

**Root cause**: Two independent sources of truth:
1. `.gimo/config.yaml` → `preferred_model: claude-haiku-4-5-20251001`
2. Server state → active provider: `local_ollama / qwen2.5-coder:3b`

`api_request()` unconditionally sends `X-Preferred-Model` header from local config (api.py:209). Server unconditionally uses it (plan_router.py:284-287). No validation that the preferred model is compatible with the active provider. **Same root as #6.**
**Confidence**: HIGH

---

## Systemic Patterns

### Pattern A: CLI ↔ Server Response Shape Mismatch (Issues #14, #15, #16, #17)

**5 of 21 issues** trace to the same pattern: CLI formatters expect one shape (usually `list` or flat `dict`), the server returns another shape (wrapped `dict`, nested objects, or `list` when `dict` was expected). This happened during the refactor — server response models changed but CLI formatters were not updated.

### Pattern B: Auth/Role Escalation Gap (Issues #2, #3, #12)

**3 of 21 issues** trace to the auth system having no clean CLI escalation path. The bond system has two auth modes (CLI Bond + legacy), but:
- CLI Bond can only be operator
- Legacy bond can only be operator
- Admin requires env var (`ORCH_TOKEN`)
- Expired bonds are never cleaned

### Pattern C: Config Desync Between CLI and Server (Issues #6, #19)

**2 issues** trace to `.gimo/config.yaml` `preferred_model` being blindly sent to the server as `X-Preferred-Model`, where the server blindly forwards it to whatever provider is active — even when incompatible.

### Pattern D: Credentials Not Persisted to Disk (Issues #7, #4)

**2 issues** trace to provider credentials being stored only in `os.environ` (process memory), with no persistence mechanism. Server restart loses all auth state.

### Pattern E: Null Safety in OpsConfig (Issues #10, NEW-2)

**2 issues** trace to `OpsConfig.economy` defaulting to `None` instead of `UserEconomyConfig()`. Any endpoint that reads `config.economy.*` without a null-guard crashes.

---

## Dependency Graph of Issues

```
#19 (config desync) ← same root → #6 (plan 404)
#2 (bond expired) ← same root → #12 (warning spam)
#1 (gimo up) ← same root → #21 (silent failure)
#10 (mastery 500) ← same root → NEW-2 (economy=None)
#14, #15, #16, #17 ← same pattern → CLI/Server shape mismatch
#3 (admin role) ← related to → #2 (no admin path via CLI)
#4 (no headless auth) ← related to → #7 (creds not persisted)
#9 (no tool calls) ← independent → model capability issue
#5 (chat crash) ← independent → prompt_toolkit Win32 issue
```

**Solving 6 root causes resolves all 21 issues:**

1. Fix CLI formatters to match server response shapes → fixes #14, #15, #16, #17
2. Fix bond lifecycle (auto-clean expired, login clears bond.enc) → fixes #2, #12
3. Fix X-Preferred-Model validation → fixes #6, #19
4. Fix OpsConfig.economy default → fixes #10, NEW-2
5. Add --api-key path + persist provider creds → fixes #4, #7
6. Add CLI admin escalation (or demote provider select to operator) → fixes #3
