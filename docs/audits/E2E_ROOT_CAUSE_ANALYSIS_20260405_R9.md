# GIMO Forensic Audit — Phase 2: Root-Cause Analysis (Round 9)

**Date**: 2026-04-05 05:00 UTC
**Auditor**: Claude Opus 4.6
**Input**: `docs/audits/E2E_AUDIT_LOG_20260405_R9.md` (8 issues)
**Scope**: R9 audit issues + CLI/TUI unification analysis

---

## Traced Issues: 8/8 from audit log + 1 systemic finding

---

## CRITICAL

### [R9-#1] Run execution fails with WinError 206

**Reported symptom**: `gimo run` starts but orchestrator node fails immediately. Run status: error. Log: "Stage failed [stage_2]: unknown". Watch reveals: `[WinError 206] El nombre del archivo o la extensión es demasiado largo`.

**CLI entry point**: `gimo_cli/commands/run.py:67` → `api_request(config, "POST", f"/ops/drafts/{plan_id}/approve")`

**API endpoint**: `POST /ops/drafts/{plan_id}/approve?auto_run=true`

**Router**: `tools/gimo_server/routers/ops/custom_plan_router.py`

**Service chain**:
1. `EngineService.execute_run()` → `engine_service.py:365`
2. `Pipeline.execute()` → `pipeline.py` runs stages sequentially
3. `PlanStage.execute()` → `plan_stage.py:39` calls `CustomPlanService.execute_plan()`
4. `CustomPlanService._execute_node()` → calls `AgenticLoopService.run_node()` for orchestrator
5. `AgenticLoopService._run_loop()` → `agentic_loop_service.py:760` calls `adapter.chat_with_tools()`
6. `CliAccountAdapter._raw_chat_with_tools()` → `cli_account.py:250-271` flattens ALL messages into single prompt string
7. `CliAccountAdapter.generate()` → `cli_account.py:163-195` decides subprocess mode

**Root cause**: `cli_account.py:163` — threshold too high for Windows safety margin.

```python
use_stdin = sys.platform == "win32" and len(prompt) > 6000
```

On Windows, `claude` is a `.cmd` shim. Python routes `.cmd` through `cmd.exe /c`, which has an 8,191-char limit. The 6,000-char threshold leaves only 2,191 chars of margin, but:
- `list2cmdline()` escaping adds ~10-20% overhead for JSON-heavy prompts
- Binary path resolution adds ~50 chars
- `cmd.exe /c` prefix adds ~12 chars
- The orchestrator prompt (system + 12 tool schemas + role_definition + dependency outputs) easily reaches 5,000-7,000 chars on first call

A 5,500-char prompt with 300 double quotes → ~6,100 chars after escape → exceeds margin but not threshold → non-stdin path → WinError 206.

**Fix (immediate)**: Always use stdin on Windows:
```python
use_stdin = sys.platform == "win32"  # always stdin — cmd.exe 8191 limit is too fragile
```

**Fix (proper)**: Replace subprocess invocation with direct HTTP API call via `anthropic` SDK. This eliminates all Windows path/command-line limits entirely.

**Confidence**: HIGH

---

## MEDIUM

### [R9-#2] Watch shows stale events from previous runs

**Reported symptom**: `gimo watch` with no active run shows events from last completed/failed run.

**CLI entry point**: `gimo_cli/commands/run.py:183` → `stream_events(config)`

**API endpoint**: `GET /ops/events/stream` (SSE)

**Root cause**: The SSE endpoint maintains an in-memory event buffer that replays all events on new connections. No cursor, no `Last-Event-ID` header support, no indication whether events are historical or live.

**Fix**: Add `Last-Event-ID` support or a `historical: true` field to replayed events. Or clear the buffer when a run reaches terminal status.

**Confidence**: HIGH

### [R9-#3] `gimo up` provides no success confirmation

**Reported symptom**: Prints "Starting GIMO server..." and returns without confirming success.

**CLI entry point**: `gimo_cli/commands/` (up command)

**Root cause**: The `up` command spawns the server as a background process and returns immediately without polling `/health` to confirm startup.

**Fix**: After spawn, poll `/health` with 1s intervals for up to 15s. Print `[OK] Server started at http://...` on success or `[WARN] Server started but health check timed out` on timeout.

**Confidence**: HIGH

---

## LOW

### [R9-#4] `trust reset` has no `--yes` bypass flag

**Root cause**: `gimo_cli/commands/trust.py` uses `typer.confirm()` without a `--yes` option. Compare: `rollback` command correctly has `--yes` flag.

**Fix**: Add `yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt.")` and pass to `typer.confirm(abort=not yes)`.

**Confidence**: HIGH

### [R9-#5] Config preferred_model is ignored by server

**Root cause**: `.gimo/config.yaml` `preferred_model` is read only by CLI display code. The server reads provider configuration from its own `provider.json` state. The config field is decorative — no server endpoint reads it.

**Fix**: Either wire `preferred_model` to `POST /ops/provider/set` on startup, or remove the field from config to avoid confusion.

**Confidence**: HIGH

### [R9-#6] Model metadata gaps for some models

**Root cause**: `tools/gimo_server/data/model_pricing.json` has no entries for `claude-opus-4-5`, `claude-3-7-sonnet-latest`, or `claude-3-5-haiku-latest`. The `CostService.get_provider()` substring match doesn't help because these model IDs don't match existing pricing entries.

**Fix**: Add pricing entries for these models to `model_pricing.json`.

**Confidence**: HIGH

### [R9-#7] No `repos create` or `repos register` command

**Root cause**: By design — repos auto-register when `gimo init` is run in a directory. However, there's no way to register a remote repo or a repo you haven't `cd`'d into.

**Fix**: Add `repos add <path>` command that calls `POST /ops/repos` with the given path.

**Confidence**: MEDIUM (may be intentionally absent)

### [R9-#8] Thread list is noisy and unfilterable

**Root cause**: Thread titles default to "New Conversation" (only updated when first user message arrives). Rich table column width truncates long titles. No search/filter params passed to `GET /ops/threads`.

**Fix**: Auto-title from first message content (server-side, already partially implemented). Add `--search` and `--limit` flags to CLI.

**Confidence**: HIGH

---

## SYSTEMIC FINDING: CLI/TUI Duplication and Divergence

### Context

The user conceived CLI and TUI as one thing. They are currently two separate implementations:
- `gimo chat` → `gimo_cli/chat.py` → Rich + prompt_toolkit (synchronous)
- `gimo tui` → `gimo_tui.py` → Textual (async widgets, dashboard)

### What's shared (works well)

| Module | Purpose |
|--------|---------|
| `terminal_command_executor.py` | `TerminalSurfaceAdapter` protocol + all slash command logic |
| `cli_commands.py` | Command dispatch and routing |

Both surfaces implement `TerminalSurfaceAdapter` and share all slash command behavior through `build_terminal_command_callbacks()`. This is well-designed.

### What's duplicated (diverges)

| Aspect | CLI (`gimo_cli/chat.py`) | TUI (`gimo_tui.py`) |
|--------|--------------------------|---------------------|
| SSE event types | 10 types handled | 5 types (missing: `user_question`, `plan_proposed`, `confirmation_required`, `session_start`) |
| Thread creation | Creates real thread via `POST /ops/threads` | Hardcoded `thread_id="tui_default"` — never creates real threads |
| Chat body format | `json={"content": user_input}` (correct) | `params={"content": user_input}` (BUG — query param, can truncate) |
| Surface header | Sends `X-GIMO-Surface: cli` | Does not send surface header |
| Preflight check | Yes (health + provider validation) | No |
| Streaming fallback | Falls back to non-streaming `POST /chat` | No fallback |
| History logging | Writes to `history_dir/{thread_id}.log` | No |
| Dead code | None | 138 lines (485-622) — vestigial slash command handler |
| Import path | `from gimo_cli.api import ...` (canonical) | `from gimo import _api_request, ...` (legacy shim) |

### Bugs found in TUI

1. **`gimo_tui.py:654`**: Chat sent as `params={"content": ...}` instead of `json={"content": ...}` — messages with special chars or long content will be truncated or rejected
2. **`gimo_tui.py` line 35 in `chat_cmd.py`**: `thread_id="tui_default"` hardcoded — never creates real backend threads
3. **Missing SSE events**: TUI cannot handle plan proposals, user questions, or confirmation requests from the agentic loop
4. **No `X-GIMO-Surface` header**: Backend cannot distinguish TUI traffic

### Root cause of the separation

1. **Framework mismatch**: Rich/prompt_toolkit (sync) vs Textual (async). Different control flow models — the main input/render loop cannot be shared.
2. **Copy-paste evolution**: The TUI was built by copying CLI patterns and adapting. Evidence: dead code block with Spanish comments, legacy imports.
3. **Shared abstraction was retrofitted**: `TerminalSurfaceAdapter` was extracted after both existed. It covers slash commands (~30% of surface area) but not the primary chat/streaming flow.

### Unification plan (user's intent: TUI becomes the only interactive surface)

**What to do:**
1. `gimo chat` (interactive mode, no `--message`) launches the TUI directly
2. `gimo chat --message` (single-turn) stays as-is — no UI needed
3. Extract SSE event parser into shared module `gimo_cli/sse.py`
4. Fix TUI bugs: real threads, JSON body, surface header, missing events
5. Delete dead code (lines 485-622 of `gimo_tui.py`)
6. Move TUI imports from `gimo.py` to `gimo_cli/`
7. Remove `gimo tui` as separate command — `gimo chat` IS the TUI

**What cannot be unified** (and doesn't need to be):
- Widget rendering (Textual-specific)
- Dashboard sidebar (TUI-only feature, that's the point)
- Keyboard bindings (Textual-specific)

---

## Dependency Graph of Issues

```
WinError 206 (#1)
  └── Root: cli_account.py subprocess + cmd.exe limit
  └── Proper fix: replace subprocess with HTTP API SDK

CLI/TUI divergence (systemic)
  ├── TUI missing events → user can't approve plans or answer questions
  ├── TUI hardcoded thread → no thread history/continuity
  ├── TUI query param bug → messages can truncate
  └── Root: copy-paste evolution without shared streaming abstraction

Watch stale (#2) → independent (SSE buffer management)
gimo up feedback (#3) → independent (missing health poll)
trust reset (#4) → independent (missing --yes flag)
config dead (#5) → independent (decorative field)
model metadata (#6) → independent (missing pricing entries)
repos create (#7) → independent (design decision)
thread noise (#8) → independent (UI/filtering)
```

### Solving #1 also fixes:
- Chat WinError on very long threads (preemptive)
- Any future Windows subprocess limit issues

### Solving CLI/TUI unification also fixes:
- TUI missing SSE events
- TUI hardcoded thread ID
- TUI query param bug
- Dead code in gimo_tui.py
- Legacy import paths
