# GIMO Forensic Audit — Phase 1: Black-Box CLI Stress Test (Round 9)

**Date**: 2026-04-05 04:27 UTC
**Tester**: Claude Opus 4.6 (independent auditor, ninth audit round)
**Objective**: Build a calculator app using only GIMO CLI, verify R8 fixes, discover new issues
**Server version**: UNRELEASED (PID 14668, port 9325, healthy)
**Provider**: claude-account / claude-sonnet-4-6
**Prior audit**: Round 8 — 11 issues (2 critical, 2 high, 3 medium, 4 low)

---

## R8 Fix Verification

| R8 Issue | Description | R9 Verdict |
|----------|-------------|------------|
| #1 | `gimo run` plan execution fails — orch never invokes LLM | **NOT FIXED** — same error, now traced to WinError 206 (see #1 below) |
| #2 | Chat thread continuation crashes WinError 206 | **FIXED** — thread continuation works on short threads |
| #3 | Chat hangs on second invocation | **FIXED** — second and third invocations complete normally |
| #4 | `mastery analytics` CLI reports "server unreachable" | **FIXED** — returns "No analytics data yet. Total savings: $0.0000" |
| #5 | `trust reset` no `--yes` flag | **NOT FIXED** — still aborts in non-TTY |
| #6 | `providers models` shows None for some models | **NOT FIXED** — opus-4-5, claude-3-* still show `Quality Tier: None` |
| #7 | Config preferred_model vs active provider mismatch | **NOT FIXED** — config shows haiku, active is sonnet |
| #8 | No `repos create` or `repos register` command | **NOT FIXED** — still only `list` and `select` |
| #9 | `gimo up` gives no success confirmation | **NOT FIXED** — still just "Starting GIMO server..." with no feedback |
| #10 | Thread titles truncated, many "New Conversation" | **NOT FIXED** — still truncated, still many identical titles |
| #11 | `watch` SSE only shows partial node events | **PARTIALLY FIXED** — watch now shows events but only for failed/completed nodes |

**R8 fix rate: 3/11 fully fixed, 1 partially fixed, 7 still present.**

---

## Issues

### [BLOCKER] #1 — `gimo run` plan execution fails: WinError 206 in LLM invocation

- **Command**: `python gimo.py run d_1775363253230_e5b2c7 --no-confirm --auto --timeout 120`
- **Expected**: Plan executes — orchestrator delegates to workers, files created
- **Actual**: Run starts (`r_1775363277094_c918b8 -> running`), status quickly becomes `error`. Run log: "Stage failed [stage_2]: unknown". Watch reveals root cause: `[WinError 206] El nombre del archivo o la extensión es demasiado largo` in orchestrator node's agentic loop. Worker `t_worker_2` cascades to skipped.
- **Severity**: critical
- **Suspicion**: The execution engine serializes the plan context (role_definition, task_descriptor, etc.) into a file path or subprocess argument that exceeds Windows MAX_PATH (260 chars). This is the same root cause as R8 #2 — WinError 206 — but now confirmed to also break the plan-run pipeline. Chat fixed this for its path but the pipeline uses a different code path.

### [GAP] #2 — `watch` shows stale events from previous runs

- **Command**: `python gimo.py watch` (no active run)
- **Expected**: "No active run" or empty stream
- **Actual**: Shows events from the last completed/failed run (including `custom_node_economy`, `custom_session_economy`, `custom_node_status`, `custom_plan_finished`). A user who opens `watch` expecting live data would see events from hours ago with no indication they're historical.
- **Severity**: medium
- **Suspicion**: SSE endpoint replays the full event buffer without marking historical events vs live ones.

### [FRICTION] #3 — `gimo up` provides no success confirmation

- **Command**: `python gimo.py up`
- **Expected**: "Server started successfully at http://127.0.0.1:9325" or similar
- **Actual**: Prints "Starting GIMO server on http://127.0.0.1:9325..." and returns. No health check confirmation. User must manually run `gimo ps` to verify. Second invocation correctly shows `[OK] Server already running`.
- **Severity**: medium
- **Suspicion**: Subprocess spawns the server in background but doesn't wait for health check before returning.

### [FRICTION] #4 — `trust reset` has no `--yes` bypass flag

- **Command**: `python gimo.py trust reset`
- **Expected**: Either resets or has `--yes`/`--force` flag
- **Actual**: `Reset trust engine? This clears all trust scores. [y/N]: Aborted.`
- **Severity**: low
- **Suspicion**: Uses `typer.confirm()` without bypass. Compare: `rollback` correctly has `--yes` flag.

### [INCONSISTENCY] #5 — Config preferred_model is ignored by server

- **Command**: `python gimo.py config --show` vs `python gimo.py providers list`
- **Expected**: Config preferred_model influences which model the server uses
- **Actual**: Config says `preferred_model: claude-haiku-4-5-20251001` but active provider uses `claude-sonnet-4-6`. Config model is decorative.
- **Severity**: low
- **Suspicion**: Server reads provider config from its own state, never reads `.gimo/config.yaml` preferred_model.

### [GAP] #6 — Model metadata gaps for some models

- **Command**: `python gimo.py providers models`
- **Expected**: All models show quality tier
- **Actual**: `claude-opus-4-5`, `claude-3-7-sonnet-latest`, `claude-3-5-haiku-latest` all show `Quality Tier: None`
- **Severity**: low
- **Suspicion**: `model_pricing.json` missing entries for these models.

### [GAP] #7 — No `repos create` or `repos register` command

- **Command**: `python gimo.py repos --help`
- **Expected**: Ability to register a new repo
- **Actual**: Only `list` and `select` (deprecated). Repo discovery is implicit.
- **Severity**: low
- **Suspicion**: By design — repos auto-register on `init`. But no way to manually add a remote repo.

### [COGNITIVE_LOAD] #8 — Thread list is noisy and unfilterable

- **Command**: `python gimo.py threads list`
- **Expected**: Distinguishable threads with search/filter
- **Actual**: 20 threads, 12 titled "New Conversation", titles truncated to ~30 chars. No search, no filter by date, no pagination control beyond the default 20.
- **Severity**: low
- **Suspicion**: Rich table truncation + auto-title only uses first message.

---

## Positive Observations

| Feature | Status | Notes |
|---------|--------|-------|
| `doctor` | WORKS | All checks pass, clean output |
| `status` | WORKS | Informative, clean |
| `ps` | WORKS | Correct PID detection |
| `up` / `down` | WORKS | Server lifecycle correct (feedback issue only) |
| `providers list/test/models/auth-status` | WORKS | All working, test confirms connectivity |
| `skills list/run` | WORKS | Skill execution returns proper JSON |
| `repos list` | WORKS | Shows registered repos |
| `threads list/show` | WORKS | Thread management functional |
| `audit` | WORKS | 200 status, shows dependencies |
| `observe metrics/alerts/traces` | WORKS | All observability endpoints clean |
| `mastery status/forecast/analytics` | WORKS | All mastery endpoints working |
| `chat -m -x -w` (single turn) | WORKS | Created fibonacci.py, hello_r9.txt |
| `chat -m -x -w` (multi turn, same session) | WORKS | Second/third invocations complete |
| `chat -t <thread_id>` (continuation) | WORKS | Thread continuation now works |
| `plan --no-confirm --json` | WORKS | Clean structured plan with 3 nodes |
| `config --show` | WORKS | Displays config cleanly |
| `diff` | WORKS | "No diff output" (correct — no pending changes) |
| `rollback --help` | WORKS | Has `--yes` flag (good pattern) |
| `login --help` / `logout --help` | WORKS | Clear usage |
| Error handling (bad IDs) | WORKS | 404 with clear message for nonexistent draft/thread |

---

## PHASE 1 SUMMARY

### Status: SUCCESS (calculator + fibonacci built via chat) / BLOCKED on plan-run flow

### Total issues: 8 (1 critical, 0 high, 2 medium, 5 low)

| Category | Count |
|----------|-------|
| BLOCKER | 1 (#1 — run execution WinError 206) |
| GAP | 3 (#2 watch stale, #6 model metadata, #7 repos create) |
| FRICTION | 2 (#3 gimo up feedback, #4 trust reset --yes) |
| INCONSISTENCY | 1 (#5 config preferred_model) |
| COGNITIVE_LOAD | 1 (#8 thread list noise) |

### Critical path issues:
1. **#1**: Run execution — `[WinError 206]` kills the orchestrator node. Entire plan-run pipeline is non-functional on Windows. This is GIMO's core differentiator and it doesn't work.

### Calculator app result:
- **Created via**: `gimo chat` (single and multi-turn)
- **Files**: `calculator.py`, `main.py`, `test_calculator.py`, `fibonacci.py`, `hello_r9.txt`, `hello_r9_second.txt`, `goodbye_r9.txt`
- **NOT created via**: `gimo run` (still broken)

### R8 → R9 Progress:
- **Issues fixed since R8**: 3 (chat hang, chat WinError on continuation, mastery analytics timeout)
- **Issues remaining from R8**: 7 (run execution, trust reset, model metadata, config mismatch, repos create, gimo up feedback, thread noise)
- **New issues in R9**: 1 (#2 — watch shows stale events)
- **Net improvement**: 11 issues → 8 issues (3 fewer, 1 new)

### Endpoints tested:
- GET /health → OK
- GET /ops/capabilities → OK
- POST /ops/plans/generate → OK
- POST /ops/runs/{id}/execute → FAIL (WinError 206)
- GET /ops/runs/{id} → OK
- GET /ops/events/stream → OK (stale events issue)
- POST /ops/threads/{id}/chat → OK (all modes)
- GET /ops/threads → OK
- GET /ops/threads/{id} → OK (404 for invalid)
- GET /ops/mastery/status → OK
- GET /ops/mastery/forecast → OK
- GET /ops/mastery/analytics → OK
- GET /ops/observability/metrics → OK
- GET /ops/observability/alerts → OK
- GET /ops/observability/traces → OK
- GET /ops/audit → OK
- GET /ops/trust/status → OK
- POST /ops/trust/reset → OK (but no --yes bypass)
- GET /ops/repos → OK
- GET /ops/provider/* → OK (all)
- GET /ops/skills → OK
- POST /ops/skills/{id}/run → OK
- GET /ops/files/diff → OK
- POST /ops/plans/{id}/approve → OK

### Suspicions for Phase 2:
1. **WinError 206 in pipeline**: The agentic loop service or LLM provider serializes context into a path/command that exceeds MAX_PATH. Chat fixed this for its code path but pipeline uses a different one (`cli_account.py` → `generate()` vs `chat_with_tools()`). Trace: `agentic_loop_service.py` → `cli_account.py` → probable `tempfile` or `subprocess` with long args.
2. **Watch stale events**: SSE endpoint keeps full event buffer in memory and replays on new connections. No "last-event-id" or cursor mechanism.
3. **Config preferred_model dead**: The server never reads `config.yaml` — it uses its own internal provider state. The config command writes to a file nobody reads.
