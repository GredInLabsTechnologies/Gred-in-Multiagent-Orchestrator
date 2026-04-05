# GIMO Forensic Audit — Phase 1: Black-Box CLI Stress Test (Round 6)

**Date**: 2026-04-05 01:00 UTC
**Tester**: Claude Opus 4.6 (independent auditor, sixth audit round)
**Objective**: Build a calculator app using only GIMO CLI, document all issues
**Server version**: UNRELEASED (PID 15608, port 9325, healthy via manual uvicorn)
**Provider**: claude-account / claude-sonnet-4-6
**Prior audit references**:
- `docs/audits/E2E_AUDIT_LOG_20260403_2000.md` (Round 3 — most recent in docs/)

---

## Issues

### [BLOCKER] #1 — `gimo up` does not start the server

- **Command**: `python gimo.py up`
- **Expected**: Server starts and becomes reachable within 10-15 seconds
- **Actual**: Prints "Starting GIMO server on http://127.0.0.1:9325..." then hangs indefinitely. After 25+ seconds, `curl http://127.0.0.1:9325/health` still returns connection refused. `gimo ps` reports "No GIMO instances found". Reproduced twice.
- **Workaround**: Manual `ORCH_TOKEN=$(cat .orch_token) python -m uvicorn tools.gimo_server.main:app --port 9325` works fine.
- **Severity**: critical
- **Suspicion**: `gimo up` likely spawns the subprocess but the process dies or fails to bind the port. No error output is visible — the failure is completely silent.

### [BLOCKER] #2 — `gimo run` falsely reports "Server not reachable" when server IS running

- **Command**: `python gimo.py run d_1775343175505_5ae791 --no-confirm --auto --timeout 120`
- **Expected**: Plan is approved and run starts
- **Actual**: First attempt: "Server not reachable at http://127.0.0.1:9325 / Error: timed out / Run start failed (503)". `curl` to the same endpoint returns 200 at the same moment. Second attempt (identical command, seconds later): succeeds immediately, run starts.
- **Severity**: critical
- **Suspicion**: Race condition in the health-check logic inside the CLI's run command. Timeout too low or the check runs before the first HTTP request completes.

### [GAP] #3 — `gimo run` plan execution fails with cascading skips

- **Command**: `python gimo.py run d_1775343175505_5ae791 --no-confirm --auto` (second attempt, after #2 workaround)
- **Expected**: Run executes the plan tasks (add history feature to calculator)
- **Actual**: Run starts (status: running) but `watch` output shows: `custom_node_status` t_worker_3 "skipped: Skipped because an upstream dependency failed", then `custom_plan_finished` status: "error". Zero tokens consumed (cost_usd: 0.0, total_tokens: 0).
- **Severity**: critical
- **Suspicion**: The orchestrator node or an upstream worker fails silently, triggering cascading skips on downstream tasks. No useful error message about WHAT failed.

### [GAP] #4 — Chat `-x` writes files to CWD, ignores target workspace

- **Command**: `python gimo.py chat -m "Create a calculator..." -x`
- **Expected**: Files created in the workspace associated with the thread/repo context
- **Actual**: `calculator.py`, `main.py`, `test_calculator.py` created in the GIMO repo root (`C:\Users\shilo\Documents\Github\gred_in_multiagent_orchestrator\`), NOT in `gimo_prueba/`. The chat agent has no concept of target workspace — it writes wherever the write_file tool resolves paths relative to the server's CWD.
- **Severity**: high
- **Suspicion**: The `write_file` tool uses the server's working directory, not a per-thread/per-repo workspace. The `-w` flag on `plan` exists but chat has no equivalent workspace targeting.

### [GAP] #5 — Thread title always "New Conversation" regardless of content

- **Command**: `python gimo.py chat -m "Create a calculator..." -x` followed by `python gimo.py threads list`
- **Expected**: Thread title auto-generated from the first message (e.g., "Calculator App Creation")
- **Actual**: Thread `thread_244f1f6f` has title "New Conversation". This is the 15th+ thread with this title in the list. Only 3 out of 19 threads have meaningful titles ("CLI Agentic Session" x3, "ollama-test" x1).
- **Severity**: medium
- **Suspicion**: Thread creation endpoint either doesn't receive a title or ignores the LLM's first message for title generation. Prior audits flagged this — still unfixed.

### [GAP] #6 — `audit` Dependencies check returns 500

- **Command**: `python gimo.py audit`
- **Expected**: All audit checks pass or report meaningful diagnostics
- **Actual**: "Dependencies | 500 | n/a dependencies". The 500 error is not elaborated — no traceback, no hint about what dependency check failed.
- **Severity**: high
- **Suspicion**: The `/ops/security/dependencies` endpoint (or whatever audit hits) throws an unhandled exception. This has been present since Round 1 (all prior audits).

### [FRICTION] #7 — `providers test` reports "Auth status: unknown" for authenticated provider

- **Command**: `python gimo.py providers test claude-account`
- **Expected**: "Auth status: authenticated" (since `auth-status` shows `[OK] authenticated / api_key`)
- **Actual**: "Provider 'claude-account' endpoint is reachable. Auth status: unknown"
- **Severity**: medium
- **Suspicion**: `test` subcommand doesn't reuse the auth-status check; it only tests HTTP reachability. Misleading because the user expects a connectivity test to include auth.

### [FRICTION] #8 — `providers models` shows `None` for Quality Tier and Context Window

- **Command**: `python gimo.py providers models`
- **Expected**: Model metadata populated (e.g., "high"/"medium", "200K")
- **Actual**: Installed Models shows `claude-sonnet-4-6 | None | None`. Available models all show `Quality Tier: None`.
- **Severity**: low
- **Suspicion**: Model inventory doesn't enrich metadata from the provider's model catalog. The data fields exist but are never populated.

### [FRICTION] #9 — `repos list` shows filesystem repos not managed by GIMO

- **Command**: `python gimo.py repos list`
- **Expected**: Only repos explicitly registered or initialized with GIMO
- **Actual**: Shows 18 repos including random directories from `C:\Users\[USER]\Documents\Github\` (e.g., "Locco-Burger", "GICS-ARCHIVE") and a pytest temp dir (`dummy_repo`). None are marked "Active". No way to distinguish GIMO-managed vs discovered repos.
- **Severity**: medium
- **Suspicion**: Repos endpoint scans the filesystem parent directory of the current workspace, listing everything that has a `.git` folder. No curation, no active/managed distinction.

### [FRICTION] #10 — TUI status bar shows all dashes, doesn't hydrate from backend

- **Command**: `python gimo.py tui`
- **Expected**: Status bar shows current repo, branch, model, permissions, budget, context
- **Actual**: `REPO: - | BRANCH: - | MODEL: - | PERM: - | BUDGET: - | CTX: -` — all empty. Content panels say "Loading topology..." and "Fetching telemetry..." indefinitely within the 5-second window tested.
- **Severity**: medium
- **Suspicion**: TUI launches but the reactive data fetch from the backend either hasn't started or silently fails. The status bar never updates.

### [FRICTION] #11 — `watch` hangs silently when no run is active

- **Command**: `python gimo.py watch` (with no active run)
- **Expected**: "No active run to watch" or similar feedback, then exit
- **Actual**: Hangs indefinitely with no output. Must Ctrl+C or timeout to exit.
- **Severity**: low
- **Suspicion**: SSE stream opens but since there's no run generating events, the connection stays open forever with no heartbeat or "idle" message.

### [FRICTION] #12 — `trust reset` requires admin role but doctor says "operator" role

- **Command**: `echo "y" | python gimo.py trust reset`
- **Expected**: Trust state is cleared (since user is authenticated)
- **Actual**: `Reset failed (403): {'detail': 'admin role or higher required'}`
- **Severity**: low
- **Suspicion**: CLI user is bonded as "operator" role (confirmed by `doctor`). Trust reset requires "admin". No way to escalate to admin via CLI. The command exists but is unusable for most users.

### [ERROR] #13 — `skills run` fails with 422 — missing request body

- **Command**: `python gimo.py skills run test-skill-1772674265105-82e5`
- **Expected**: Skill executes or at minimum shows usage instructions for required parameters
- **Actual**: `Execution failed (422): {'detail': [{'type': 'missing', 'loc': ['body'], 'msg': 'Field required', 'input': None}]}`
- **Severity**: medium
- **Suspicion**: The CLI sends no request body but the backend endpoint requires one. The CLI help for `skills run` doesn't indicate what parameters are needed beyond the skill ID.

### [INCONSISTENCY] #14 — `doctor` says "CLI Bond: not configured" but auth works

- **Command**: `python gimo.py doctor`
- **Expected**: Bond status reflects that the user is authenticated and operational
- **Actual**: Shows `[~] CLI Bond: not configured` alongside `[OK] Legacy Bond: valid (operator)`. The "CLI Bond" concept and the "Legacy Bond" concept are never explained. A user would not know which matters.
- **Severity**: low
- **Suspicion**: Two parallel auth systems (new CLI Bond vs legacy token-based). The legacy one works, the new one is not implemented. `doctor` surfaces both without explaining.

### [COGNITIVE_LOAD] #15 — No guidance on how to target a specific workspace/repo for chat

- **Command**: N/A — missing feature
- **Expected**: `gimo chat -w gimo_prueba -m "Create a file..."` or similar workspace targeting
- **Actual**: `chat` has `-m`, `-t`, `-x` but no `-w` (workspace) flag. `plan` has `-w` but `chat` doesn't. The `repos select` is deprecated. The only path is `cd <target> && gimo init && gimo chat -x -m "..."`, which is never documented.
- **Severity**: high
- **Suspicion**: Workspace targeting was designed for the plan/run flow but not extended to the chat flow.

### [SILENT_FAILURE] #16 — `gimo run` first attempt silently fails, second attempt works

- **Command**: `python gimo.py run <plan_id> --no-confirm --auto`
- **Expected**: Consistent behavior — either succeeds or fails with clear reason
- **Actual**: First call: exits 1 with "Server not reachable" despite server being up. Second call (identical, 2 seconds later): succeeds. The first failure is silent — no retry, no "try again" hint.
- **Severity**: high
- **Suspicion**: Same as #2 but categorized separately because the intermittent nature makes it a silent failure — the user might accept the error and give up.

---

## Summary of Commands Tested

| Command | Status | Notes |
|---------|--------|-------|
| `gimo --help` | OK | All commands listed |
| `gimo up` | FAIL | #1 — Server never starts |
| `gimo down` | OK | Kills server correctly |
| `gimo ps` | OK | Reports instances correctly |
| `gimo doctor` | PARTIAL | Works but confusing bond display (#14) |
| `gimo status` | OK | Shows authoritative status correctly |
| `gimo init` | OK | Initializes workspace |
| `gimo chat -m "..." -x` | PARTIAL | Creates files but in wrong directory (#4) |
| `gimo chat -m "..." -t <id>` | OK | Thread continuation works |
| `gimo plan "..."` | OK | Plan generation works |
| `gimo run <id>` | FAIL | Intermittent false unreachable (#2), execution fails (#3) |
| `gimo watch` | PARTIAL | Works with active run, hangs without one (#11) |
| `gimo diff` | OK | "No diff output" — correct for clean state |
| `gimo rollback` | OK | Correctly warns about dirty worktree |
| `gimo config --show` | OK | Shows config correctly |
| `gimo audit` | PARTIAL | Dependencies 500 (#6) |
| `gimo providers list` | OK | Clean table output |
| `gimo providers set <name>` | OK | Works correctly |
| `gimo providers test <name>` | PARTIAL | Misleading auth status (#7) |
| `gimo providers models` | PARTIAL | Metadata all None (#8) |
| `gimo providers auth-status` | OK | Shows correct auth table |
| `gimo repos list` | PARTIAL | Shows unmanaged repos (#9) |
| `gimo repos select` | OK | Correctly explains it's deprecated |
| `gimo threads list` | OK | Shows all threads |
| `gimo threads show <id>` | OK | Shows thread detail with tool call history |
| `gimo trust status` | OK | "No trust data yet" — correct |
| `gimo trust reset` | FAIL | 403 admin required (#12) |
| `gimo mastery status` | OK | Shows token economy data |
| `gimo mastery forecast` | OK | "No forecast data yet" |
| `gimo mastery analytics` | OK | "No analytics data yet" |
| `gimo observe metrics` | OK | Shows comprehensive metrics table |
| `gimo observe alerts` | OK | "No active alerts" |
| `gimo observe traces` | OK | "No traces recorded yet" |
| `gimo skills list` | OK | Shows registered skills |
| `gimo skills run <id>` | FAIL | 422 missing body (#13) |
| `gimo tui` | PARTIAL | Launches but status bar empty (#10) |
| `gimo login --help` | OK | Help displayed |
| `gimo logout --help` | OK | Help displayed |

---

## PHASE 1 SUMMARY

### Status: SUCCESS (calculator created via chat -x, tests pass)

The calculator application was successfully created through GIMO's agentic chat (`chat -m "..." -x`). Both `calculator.py` and `test_calculator.py` were generated with 26 passing pytest tests. However, files were written to the GIMO repo root instead of the target `gimo_prueba/` directory.

The plan/run flow was also tested but failed to execute (cascading worker failures with zero token consumption).

### Total issues: 16 (2 blockers, 5 gaps, 6 frictions, 1 error, 1 inconsistency, 1 cognitive_load, 1 silent_failure)

### Critical path issues:
1. **#1 BLOCKER**: `gimo up` doesn't start the server — forces manual uvicorn
2. **#2 BLOCKER**: `gimo run` intermittently claims server unreachable when it's running
3. **#3 GAP**: Plan execution fails with cascading worker skips, zero tokens consumed
4. **#4 GAP**: Chat writes files to server CWD, not target workspace
5. **#15 COGNITIVE_LOAD**: No way to target a workspace from chat

### Regression vs Round 3 (docs/audits/E2E_AUDIT_LOG_20260403_2000.md):

| Round 3 Issue | Status in Round 6 |
|---------------|-------------------|
| N1 BLOCKER — tools denied by propose_only policy | **FIXED** — `-x` flag enables workspace_safe policy |
| N2 BLOCKER — Windows cp1252 encoding crash | **FIXED** — no crash observed in any Rich output |
| N3 GAP — providers login accepts invalid keys | NOT TESTED |
| Round3 "run approves but never starts" | **PARTIALLY FIXED** — run starts but workers fail (#3) |
| Round3 "CLI Bond not configured" | STILL PRESENT (#14) |
| Round3 "thread title ignored" | STILL PRESENT (#5) |
| Round3 "audit Dependencies 500" | STILL PRESENT (#6) |
| Round3 "providers test says unknown auth" | STILL PRESENT (#7) |

### New issues not in prior audits:
- **#1**: `gimo up` completely broken (not noted in Round 3 — server was started manually)
- **#2/#16**: `run` intermittent false unreachable
- **#10**: TUI status bar empty
- **#13**: Skills run 422

### Endpoints tested (via CLI):
- GET /health → OK
- GET /ops/status → OK
- GET /ops/threads → OK
- GET /ops/threads/{id} → OK
- POST /ops/threads/{id}/chat → OK (via `chat -m`)
- POST /ops/plans → OK (via `plan`)
- POST /ops/plans/{id}/approve → OK (via `run`)
- POST /ops/runs → INTERMITTENT FAIL
- GET /ops/runs/{id} → OK (via `watch`)
- GET /ops/observability/metrics → OK
- GET /ops/observability/alerts → OK
- GET /ops/observability/traces → OK
- GET /ops/mastery/status → OK
- GET /ops/mastery/forecast → OK
- GET /ops/mastery/analytics → OK
- GET /ops/repos → OK
- GET /ops/providers → OK
- POST /ops/providers/{id}/test → OK
- GET /ops/security/dependencies → 500
- GET /ops/trust/status → OK
- POST /ops/trust/reset → 403
- GET /ops/skills → OK
- POST /ops/skills/{id}/run → 422
- SSE /ops/events → OK (when run active)

### Suspicions for Phase 2:
1. `gimo up` subprocess spawning mechanism is broken on Windows — likely a detach/fork issue
2. `run` health-check uses different timeout/logic than `curl` — possible async race
3. Worker execution in plan/run has no useful error propagation — cascade failures are opaque
4. Chat write_file tool resolves paths relative to server CWD, not thread workspace
5. Thread title is never set from first user message — the field exists but is ignored
6. `/ops/security/dependencies` endpoint has been 500 since Round 1 — likely dead code
7. TUI status bar fetch is fire-and-forget with no fallback when data arrives slowly
