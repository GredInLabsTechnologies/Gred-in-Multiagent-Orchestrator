# GIMO Phase 2 — Root-Cause Analysis

**Date**: 2026-04-03
**Input**: `docs/audits/E2E_AUDIT_LOG_20260403_1700.md` (20 active issues)
**Method**: Read-only codebase traversal, call-chain tracing
**Scope**: All blockers, gaps, errors, and high-severity frictions

---

## Traced issues: 14/20 from audit log
## New issues discovered during tracing: 3

## Issue Map

| ID | Category | Root Cause Location | Confidence |
|----|----------|-------------------|------------|
| N1 | BLOCKER | `routers/ops/run_router.py:125-128` | HIGH |
| N2 | BLOCKER | `gimo_cli_renderer.py:292` | HIGH |
| N4 | GAP | `providers/tool_call_parser.py:27` + `providers/base.py:78` | HIGH |
| N5 | GAP | `routers/ops/plan_router.py:244-269` | HIGH |
| N6 | SILENT_FAILURE | `gimo_cli/commands/run.py:78` | HIGH |
| N12 | SILENT_FAILURE | `gimo_cli/commands/run.py:78` (same root) | HIGH |
| N3 | GAP | `routers/ops/conversation_router.py:54-57` | HIGH |
| N7 | FRICTION | `gimo_cli/commands/repos.py:42-50` | HIGH |
| N9 | INCONSISTENCY | `services/providers/connector_service.py:408-413` | HIGH |
| N10 | INCONSISTENCY | `routers/ops/provider_router.py` (inferred) | MEDIUM |
| BLOCKER#2 | BLOCKER | `gimo_cli/bond.py:265-286` + `auth.py:299-319` | HIGH |
| ERROR#11a | ERROR (deps 500) | `services/providers/connector_service.py:236-255` | MEDIUM |
| ERROR#11b | ERROR (tail 403) | `security/access_control.py:10-27` | HIGH |
| INCON#19 | INCONSISTENCY | Design gap: `.gimo/config.yaml` vs backend provider state | MEDIUM |

---

## Detailed Traces

---

### [N1] `run` approves plan but never starts execution

**Reported symptom**: `gimo run <plan_id> --no-confirm` outputs `{"approved": {...}, "run": null}`. No execution.

**CLI entry point**: `gimo_cli/commands/run.py:24` → `run()`

**API endpoint hit**: `POST /ops/drafts/{draft_id}/approve?auto_run=true`

**Router**: `tools/gimo_server/routers/ops/run_router.py:87` → `approve_draft()`

**Root cause** (HIGH confidence):

The `should_run` condition at `run_router.py:125-128`:
```python
should_run = (
    (auto_run if auto_run is not None else config.default_auto_run)
    and execution_decision == "AUTO_RUN_ELIGIBLE"
    and not auto_run_blocked_by_intent
)
```

The CLI `plan` command calls `POST /ops/generate-plan` (plan_router.py:214), which creates a draft with `context` containing `"structured": true` and `"custom_plan_id": "plan_..."`. However, this endpoint sets `execution_decision` via `_evaluate_draft_intent()` only for the `/ops/drafts` endpoint (plan_router.py:117-131).

For structured plans (`/ops/generate-plan`), the context dict IS populated with `execution_decision` at plan_router.py:130. So the value should be there. Let me re-examine...

Actually, looking more carefully at the plan_router.py generate-plan endpoint (line 214+), it does NOT call `_evaluate_draft_intent()`. It calls `ContractFactory.build()` and `OrchestratorMemorandumService.build_memorandum()` but creates the draft directly via `OpsService.create_draft()` with a context that does NOT include `execution_decision`.

The `execution_decision` key is only set when the draft goes through `_evaluate_draft_intent()` in the `/ops/drafts` endpoint. The `/ops/generate-plan` endpoint bypasses this entirely.

Therefore: `context.get("execution_decision")` returns `""` (empty), which is NOT equal to `"AUTO_RUN_ELIGIBLE"`, so `should_run` is always `False` for structured plans.

**The structured plan path never sets `execution_decision`, making auto-run impossible for CLI-generated plans.**

**Collateral findings**: The `--auto` flag is effectively dead code for all CLI-generated plans. Every `gimo plan` + `gimo run` pair will silently skip execution.

---

### [N2/BLOCKER#5] Chat crashes in non-TTY environments

**Reported symptom**: `NoConsoleScreenBufferError` traceback when stdin is piped.

**CLI entry point**: `gimo_cli/commands/chat_cmd.py:57` → `interactive_chat(config)`

**Call chain**: `chat_cmd.py:57` → `gimo_cli/chat.py:288` → `renderer.get_user_input()` → `gimo_cli_renderer.py:292` → `PromptSession()`

**Root cause** (HIGH confidence):

`gimo_cli_renderer.py:292` unconditionally creates `PromptSession()` from `prompt_toolkit`. On Windows, `prompt_toolkit` detects `xterm-256color` TERM (set by git-bash/mintty) but requires a real Win32 console buffer. When stdin is not a TTY (piped input), `Win32Output.__init__()` calls `get_win32_screen_buffer_info()` which raises `NoConsoleScreenBufferError`.

There is:
- No `sys.stdin.isatty()` guard before creating `PromptSession`
- No `--message` / `--one-shot` CLI flag for non-interactive use
- No fallback to `input()` or `sys.stdin.readline()`

The `chat_cmd.py` file does check `isatty` for `plan` command (line 30-31) but NOT for `chat`.

---

### [N4/GAP#9] Agentic loop doesn't execute tools — LLM returns JSON-as-text

**Reported symptom**: `POST /ops/threads/{id}/chat` returns `tool_calls: []` while the response text contains a JSON tool call.

**API endpoint**: `routers/ops/conversation_router.py` → chat endpoint

**Service**: `services/agentic_loop_service.py:743` → `adapter.chat_with_tools()`

**Provider chain**: `providers/base.py:42` → `_raw_chat_with_tools()` → `_normalise_tool_calls()`

**Root cause** (HIGH confidence):

The tool_call_parser (`providers/tool_call_parser.py`) **only** recognizes these patterns:
1. JSON with `"tool_calls"` key inside code blocks (line 27)
2. Bare JSON with `"tool_calls"` key (line 53)

But the LLM (qwen2.5-coder:3b via ollama) returned:
```json
{"name": "write_file", "arguments": {"path": "...", "content": "..."}}
```

This is a **single tool call object** WITHOUT wrapper `"tool_calls"` array. The parser searches for the string `"tool_calls"` (line 54) and finds nothing, so it returns `[]`.

The `base.py:_normalise_tool_calls()` then falls through to `tool_call_format = "none"`.

**Two compounding failures**:
1. The OpenAI-compat adapter (`openai_compat.py:162-163`) sends `tools` and `tool_choice: "auto"` to ollama, but qwen2.5-coder:3b doesn't support the OpenAI tool_call API format natively. Ollama returns `tool_calls: []` in the message object, and the model puts the tool call as text in `content`.
2. The fallback parser (`tool_call_parser.py`) doesn't handle the most common small-model format: a bare `{"name": "...", "arguments": {...}}` object without wrapper.

**Missing pattern**: Single tool call without `tool_calls` wrapper key.

---

### [N5] Plan quality is comically bad — 13 workers for a calculator

**Reported symptom**: 13 workers including "Deploy to production" and "Monitor in production" for a 20-line calculator.

**CLI entry point**: `gimo_cli/commands/plan.py:55` → `POST /ops/generate-plan`

**Router**: `routers/ops/plan_router.py:214` → `generate_structured_plan()`

**Root cause** (HIGH confidence):

The system prompt at `plan_router.py:244-269` has NO constraint on:
- Maximum number of tasks
- Scope proportionality (simple task = few workers)
- Forbidden task types (no "deploy to production" for local dev tasks)
- Task deduplication (separate workers for add/subtract/multiply/divide is absurd)

The prompt says "Generate a JSON execution plan" but gives no guidance on sizing. The schema example likely shows a complex plan, which the small model (3B) mimics regardless of task complexity.

Additionally, all workers depend only on `t_orch` (flat graph, no inter-worker dependencies), meaning the plan has no real DAG intelligence — it's just a flat list of tasks the model hallucinated.

**No server-side validation**: There is no post-generation pruning, task count cap, or sanity check on the generated plan.

---

### [N6/N12] `run` exits 0 with zero output when execution fails

**Reported symptom**: `gimo run <id> --no-confirm` exits silently with code 0.

**CLI entry point**: `gimo_cli/commands/run.py:78`

**Root cause** (HIGH confidence):

```python
# run.py:62-76
final_run_payload = run_payload  # None when "run": null
if auto and wait and isinstance(run_payload, dict) and run_payload.get("id"):
    # This branch NEVER executes because run_payload is None
    ...

if json_output:  # False in non-JSON mode
    ...
    return

if final_run_payload:  # None → skips entire output block
    console.print(Panel(...))
# Falls off the end — no else, no error, no exit code
```

When `run_payload` is `None`:
1. The poll loop is skipped (line 63 condition fails)
2. The non-JSON render is skipped (line 78 condition fails)
3. No `else` clause exists — function returns normally with exit code 0

**No error handling for `run: null`**. The CLI trusts the backend blindly and doesn't validate the response contract.

---

### [N3] Thread creation ignores user-provided title

**Reported symptom**: `POST /ops/threads` with `{"title": "Calculator Build"}` creates thread titled "New Conversation".

**Router**: `routers/ops/conversation_router.py:53-61`

**Root cause** (HIGH confidence):

```python
@router.post("", response_model=GimoThread, status_code=201)
async def create_thread(
    workspace_root: str,           # Query param (required)
    auth: ...,
    title: str = "New Conversation",  # Query param (default)
):
```

`title` is declared as a **query parameter** (bare function arg with default), NOT a body field. The `POST` body `{"title": "Calculator Build"}` is ignored — FastAPI reads `title` from query string only.

To pass title, user would need: `POST /ops/threads?workspace_root=gimo_prueba&title=Calculator+Build`

**API design error**: `title` should be read from request body for POST endpoints, not query string.

---

### [N7] `repos list` shows raw dicts instead of table

**Reported symptom**: Raw Python dict `{'name': 'foo', 'path': '...'}` per line.

**CLI entry point**: `gimo_cli/commands/repos.py:32-52`

**Root cause** (HIGH confidence):

The CLI has two render paths:
1. `if isinstance(payload, list):` → Rich table (line 32)
2. `elif isinstance(payload, dict):` → checks for `repos` or `repositories` key (line 43)

The API returns a `dict` with key structure like `{"repos": [...]}`, but the actual repos API (`/ops/repos`) returns a list of dict items with `name` and `path` keys. The CLI hits branch 2 (`isinstance(payload, dict)`) because the server wraps the list.

In branch 2, it looks for `payload.get("repos")` or `payload.get("repositories")`. If found, it prints each raw with a marker. But the formatting is plain `console.print(f"  {r}{marker}")` where `r` is a dict — Python's `str()` of a dict produces `{'name': '...', 'path': '...'}`.

**No Rich table rendering in the dict branch.**

---

### [N9] `providers test` says "healthy" for unauthenticated provider

**Reported symptom**: `providers test claude-account` = "healthy" but `providers auth-status` = "not connected".

**Root cause** (HIGH confidence):

`providers test` calls the connector health endpoint. For `claude-account`, the connector type is `openai_compat` (since claude-account is configured as an OpenAI-compatible provider in the config).

At `connector_service.py:415-423`, the `openai_compat` health check calls `provider_service_cls.provider_health(provider_id)` which checks if the provider's base URL is reachable — NOT whether authentication credentials are valid.

`providers auth-status` calls the device auth status endpoint, which checks for an actual OAuth session/token.

**Two different definitions of "healthy"**: endpoint reachable vs. authenticated. No CLI disambiguation.

---

### [BLOCKER#2] Bond system: login succeeds but doctor says "CLI Bond: not configured"

**Reported symptom**: `gimo login` with token succeeds, but `gimo doctor` shows "CLI Bond: not configured".

**CLI entry point**: `gimo_cli/commands/auth.py:179-251` (legacy token flow)

**Root cause** (HIGH confidence):

The legacy token flow at `auth.py:234-246` calls `save_bond()` (YAML-based legacy bond), NOT `save_cli_bond()` (AES-256-GCM bond.enc). The CLI Bond (Identity-First Auth) is only created via the `--web` OAuth flow (auth.py:104-172).

The `doctor` command at `auth.py:298-319` checks for CLI Bond via `load_cli_bond()` which reads `~/.gimo/bond.enc`. Since the token flow only creates a legacy bond at `~/.gimo/bonds/{fingerprint}.yaml`, the CLI Bond check returns None → "not configured".

**This is working as designed but creates confusion**: The doctor output shows both bond types separately, but the UX implies CLI Bond should be configured after any login. The legacy token login SHOULD either:
1. Also create a CLI Bond (wrapping the token in AES-GCM), or
2. Not show CLI Bond status when using legacy auth (avoid confusion)

---

### [ERROR#11b] `audit` tail returns 403

**Reported symptom**: `gimo audit` → Audit Tail: 403.

**CLI entry point**: `gimo_cli/commands/ops.py:212` → `api_request(cfg, "GET", "/ui/audit", params={"limit": 20})`

**Router**: `routers/legacy_ui_router.py:87-93` → `get_ui_audit()` uses `Depends(require_read_only_access)`

**Root cause** (HIGH confidence):

`security/access_control.py:10-27` — `READ_ONLY_ACTIONS_PATHS` set does NOT include `/ui/audit`.

The operator path check at `_is_operator_allowed_path()`:
1. `_is_actions_allowed_path("/ui/audit")` → False (not in set)
2. `OPERATOR_EXTRA_PREFIXES = ("/ops/",)` → `/ui/audit` does NOT start with `/ops/`
3. Result: 403

**Fix**: Either add `/ui/audit` to `READ_ONLY_ACTIONS_PATHS`, or change the CLI `audit` command to use an `/ops/` endpoint.

---

### [ERROR#11a] `audit` dependencies returns 500

**Reported symptom**: `gimo audit` → Dependencies: 500.

**CLI entry point**: `gimo_cli/commands/ops.py:211` → `api_request(cfg, "GET", "/ops/system/dependencies")`

**Router**: `routers/ops/dependencies_router.py:13-22` → `list_system_dependencies()`

**Service**: `services/providers/connector_service.py:236-255` → `list_cli_dependencies()`

**Root cause** (MEDIUM confidence):

The endpoint calls `ProviderService.list_cli_dependencies()` which iterates `_DEPENDENCIES` and calls `_resolve_cli_version()` for each binary. On Windows with `claude` CLI installed, the subprocess call `[claude, --version]` via `asyncio.create_subprocess_shell()` may fail or return unexpected output.

However, `_resolve_cli_version` has a broad `except Exception: return None` handler (line 116). If this truly catches all errors, the 500 must come from elsewhere — possibly from a model validation error in `CliDependencyStatus` if a field receives an unexpected type, or from an unhandled exception in the `list_system_dependencies` router (no try/except wrapper).

**Needs runtime testing to confirm exact exception.** Most likely candidate: `CliDependencyStatus` pydantic validation failure on an edge-case field value.

---

### [INCON#19] Config model vs active provider mismatch

**Reported symptom**: `.gimo/config.yaml` says `preferred_model: claude-haiku-4-5-20251001` but status shows `qwen2.5-coder:3b`.

**Root cause** (MEDIUM confidence):

**Design gap**: Two independent state stores:
1. `.gimo/config.yaml` (local CLI config) — `preferred_model` field
2. Backend `provider.json` (server-side) — active provider + model

`config.yaml` is a local preference file, NOT the authoritative source. The backend ignores it entirely. When a user runs `gimo providers set local_ollama`, the backend updates `provider.json`. The `preferred_model` in `config.yaml` is never synced and never consulted by the server.

**The field `preferred_model` in config.yaml is dead configuration.** It's set during `gimo init` but never read by any active code path.

---

## New Issues Discovered During Tracing

### [T1] `/ops/generate-plan` bypasses intent classification entirely

**Location**: `routers/ops/plan_router.py:214-342`

**Finding**: The structured plan endpoint does not call `_evaluate_draft_intent()`, meaning:
- No `execution_decision` is set
- No risk scoring
- No policy gate check
- No intent classification

Any plan generated via CLI bypasses ALL governance gates. This is a security gap — a malicious prompt could generate a plan with `scope: "file_write"` tasks that bypass the risk gate.

**Confidence**: HIGH

---

### [T2] Tool call parser has no test coverage for single-object format

**Location**: `providers/tool_call_parser.py`

**Finding**: The parser handles `{"tool_calls": [...]}` wrapper format but NOT the most common small-model format: `{"name": "...", "arguments": {...}}`. This means the fallback parser is ineffective for:
- qwen2.5-coder (all sizes)
- llama models
- Any model that outputs tool calls as bare JSON objects

The parser has patterns for `"tool_calls"` key only. Missing: single `{"name":..}` object, array `[{"name":...}]` without wrapper key, XML-like tool tags (`<tool_call>...</tool_call>`).

**Confidence**: HIGH

---

### [T3] `repos list` leaks test directories from pytest temp

**Location**: Server-side repo scanner (inferred from output showing `pytest-of-shilo/...dummy_repo`)

**Finding**: The repos endpoint scans all git repositories under the user's home directory without filtering out temporary/test directories. `dummy_repo` from `pytest-524/test_context_request_active_an0/` appears in production `repos list` output.

**Confidence**: HIGH

---

## Systemic Patterns

### Pattern 1: Governance bypass on structured plans (3 issues: N1, N5, T1)

The `/ops/generate-plan` endpoint is a separate code path from `/ops/drafts`. The drafts path has full governance: intent classification, risk scoring, policy gate, execution_decision. The generate-plan path has NONE of these.

This means the CLI `plan` → `run` workflow always bypasses governance, making auto-run impossible and security unenforceable.

**Root cause**: Two parallel paths to create drafts, only one has governance. Violates AGENTS.md unification principle.

### Pattern 2: CLI doesn't validate backend responses (4 issues: N1, N6, N12, N7)

Multiple CLI commands trust the backend response blindly:
- `run` doesn't check if `run` is null → silent no-op
- `repos list` doesn't handle dict-wrapped lists properly
- No command validates response schema before rendering

**Root cause**: CLI was built optimistically — no defensive parsing, no error paths for unexpected responses.

### Pattern 3: `prompt_toolkit` hard dependency without TTY detection (2 issues: N2, BLOCKER#5)

Chat is completely unusable in automated/CI/piped environments. This affects:
- Any non-interactive testing
- Scripted usage via `echo "..." | gimo chat`
- IDE terminal integrations with non-console stdout

**Root cause**: Single renderer implementation with no fallback path.

### Pattern 4: Small model incompatibility (2 issues: N4, N5)

The system was designed for large models (Claude Sonnet/Opus) that support native tool calling and can generate proportionate plans. With small local models (3B):
- Tool calls come as text, not structured API responses
- Plans are bloated and nonsensical
- No quality validation catches these failures

**Root cause**: No model capability detection. System treats all models identically.

---

## Dependency Graph of Issues

```
T1 (generate-plan bypasses governance)
  └── N1 (run never executes) — execution_decision never set
      └── N6/N12 (silent failure) — CLI doesn't handle null run

N4 (tools don't fire)
  ├── T2 (parser missing patterns) — small models use different format
  └── Pattern 4 (model incompatibility) — no capability detection

N2 (chat crash)
  └── Pattern 3 (prompt_toolkit) — no TTY fallback

N5 (bad plan quality)
  ├── Pattern 4 (model incompatibility) — 3B model can't scope
  └── T1 (no governance) — no plan validation post-generation

ERROR#11b (audit 403)
  └── access_control.py — /ui/audit not in allowed paths
```

**Solving T1 (governance unification) fixes N1 and partially fixes N5.**
**Solving T2 (parser patterns) fixes N4.**
**These two fixes would unblock the entire plan→run→tools pipeline.**
