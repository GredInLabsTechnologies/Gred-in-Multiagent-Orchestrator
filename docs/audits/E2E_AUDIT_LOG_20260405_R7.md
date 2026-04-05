# GIMO Forensic Audit — Phase 1: Black-Box CLI + API Stress Test (Round 7)

**Date**: 2026-04-05 01:40 UTC
**Tester**: Claude Opus 4.6 (independent auditor, seventh audit round)
**Objective**: Verify R6 fixes persist, discover new issues via CLI + direct API testing
**Server version**: UNRELEASED (PID 36576→20372, port 9325)
**Provider**: claude-account / claude-sonnet-4-6
**Prior audit**: `docs/audits/IMPLEMENTATION_REPORT_20260405_R6.md` (Round 6 — 18/18 resolved)

---

## R6 Fix Verification

| R6 Fix | Claim | R7 Verdict |
|--------|-------|------------|
| C1: Workspace boundary | Absolute paths blocked | **NOT TESTED** (would require chat -x with absolute path) |
| C2: Resilient lifespan | `gimo up` works | **REGRESSION** — `gimo up` still hangs (#1) |
| C3: Server-driven timeouts | `run` doesn't false-timeout | **REGRESSION** — `run` still reports unreachable (#5) |
| C4: Cascade error propagation | Root cause in skip messages | **PARTIAL** — run logs say "Stage failed" with no detail (#6) |
| C5a: Chat -w + thread title | Workspace flag, auto-title | **CONFIRMED** — both work correctly |
| C5b: Provider auth-status | Normalized name | **CONFIRMED** — shows "authenticated (api_key)" |
| C5c: Skills body | `json_body={}` | **REGRESSION** — skills run shows "failed (201)" (#3) |
| C5d: Registry-only repos | No filesystem scan | **REGRESSION** — shows 17 unmanaged repos (#2) |
| C6: Model metadata | Quality tier + context window | **REGRESSION** — still shows None/None (#4) |
| C7a: Trust reset operator | Lowered to operator | **REGRESSION** — still 403 admin required (#7) |
| C7b: Dual bond display | Hide false alarm | **CONFIRMED** — doctor clean, no false alarm |
| C7c: TUI dead code | Header update on failure | **NOT TESTED** (TUI requires interactive terminal) |

**R6 regression rate: 6/12 fixes reverted or not applied.**

---

## Issues

### [BLOCKER] #1 — `gimo up` still hangs indefinitely

- **Command**: `python gimo.py up`
- **Expected**: Server starts and becomes reachable within 15 seconds
- **Actual**: Prints "Starting GIMO server on http://127.0.0.1:9325..." then hangs. After 30s timeout, server never started. `curl /health` returns connection refused.
- **Workaround**: Manual `ORCH_TOKEN=$(cat .orch_token) python -m uvicorn tools.gimo_server.main:app --port 9325`
- **Severity**: critical
- **R6 reference**: R6/#1 claimed resolved by C2 (resilient lifespan). Fix did not persist.

### [REGRESSION] #2 — `repos list` still shows filesystem repos

- **Command**: `python gimo.py repos list`
- **Expected**: Only registry entries + current workspace (R6/C5d)
- **Actual**: Shows 17 repos from parent directory scan including unrelated directories (Locco-Burger, GICS-ARCHIVE, etc.). None marked "Active".
- **Severity**: high
- **R6 reference**: R6/#9 claimed resolved by C5d ("Completely rewrote list_repos() to be registry-only"). Fix did not persist.

### [BUG] #3 — `skills run` reports failure on 201 success

- **Command**: `python gimo.py skills run test-skill-1772674265105-82e5`
- **Expected**: "Skill queued" or success message
- **Actual**: `Execution failed (201): {'skill_run_id': 'skill_run_1775352509_ae30', 'skill_id': 'test-skill-...', 'status': 'queued'}`. The skill was queued successfully (201 Created) but CLI treats non-200 as failure.
- **Severity**: medium
- **R6 reference**: R6/#13 claimed resolved by C5c (added json_body={}). The 422 is fixed but now the success display is wrong.

### [REGRESSION] #4 — `providers models` still shows None metadata

- **Command**: `python gimo.py providers models`
- **Expected**: Quality Tier and Context Window populated (R6/C6)
- **Actual**: `claude-sonnet-4-6 | None | None`. All available models also show `Quality Tier: None`.
- **Severity**: low
- **R6 reference**: R6/#8 claimed resolved by C6 (model_pricing.json enrichment). Fix did not persist.

### [REGRESSION] #5 — `run` falsely reports "Server not reachable" mid-execution

- **Command**: `python gimo.py run d_1775353398335_25d14d --no-confirm --auto --timeout 120`
- **Expected**: Run starts and watch begins
- **Actual**: Run successfully created (`r_... -> running`) then CLI immediately reports "Server not reachable" and "Error: timed out". Direct `curl` to the same endpoint returns 200 at the same moment.
- **Severity**: critical
- **R6 reference**: R6/#2 and R6/#16 claimed resolved by C3 (server-driven timeout negotiation). Fix did not persist.

### [GAP] #6 — Run fails with "Stage failed" — no root cause in logs

- **API**: `GET /ops/runs/{id}` → status: "error", log: ["Run created", "Execution started...", "Stage failed"]
- **Expected**: Error message explains what stage failed and why
- **Actual**: Only "Stage failed" — no task ID, no error detail, no cascade context
- **Severity**: high
- **R6 reference**: R6/#3 claimed C4 improved error truncation. Run-level logs still opaque.

### [REGRESSION] #7 — `trust reset` still requires admin role

- **Command**: `echo "y" | python gimo.py trust reset`
- **Expected**: Trust state cleared (user is operator)
- **Actual**: `Reset failed (403): {'detail': 'admin role or higher required'}`
- **Severity**: low
- **R6 reference**: R6/#12 claimed resolved by C7a (lowered to operator). Fix did not persist.

### [GAP] #8 — `audit` Dependencies always fails

- **Command**: `python gimo.py audit`
- **Expected**: Dependencies check passes or gives meaningful diagnostic
- **Actual**: `Dependencies | 500 | n/a dependencies`
- **API direct**: `GET /ops/security/dependencies` returns `{"detail":"Not Found"}` (404)
- **Severity**: medium
- **Notes**: Present since R1. The endpoint may have been removed but audit CLI still tries to call it.

### [GAP] #9 — `capabilities` returns null active_model and active_provider

- **API**: `GET /ops/capabilities`
- **Expected**: `active_model: "claude-sonnet-4-6"`, `active_provider: "claude-account"`
- **Actual**: `active_model: null`, `active_provider: null`
- **Severity**: medium
- **Impact**: Any UI or client reading capabilities cannot determine the current model/provider.

### [GAP] #10 — `system_load: critical` and `generation: degraded` in capabilities

- **API**: `GET /ops/capabilities` → `system_load: "critical"`, `service_health.generation: "degraded"`
- **Expected**: System should be healthy when server is running normally
- **Actual**: HardwareMonitorService reports critical load. Generation service reports degraded.
- **Severity**: high
- **Impact**: This is likely the root cause of run failures (#6). The system may refuse to execute or throttle based on this false degraded state.
- **Suspicion**: HardwareMonitorService psutil thresholds too aggressive, or generation service health check failing for a benign reason.

### [GAP] #11 — Graph node types are swapped

- **API**: `GET /ops/graph`
- **Expected**: `t_orch` node has `type: "orchestrator"`, `t_worker_1` has `type: "worker"` or similar
- **Actual**: `t_orch` has `type: "bridge"`, `t_worker_1` has `type: "orchestrator"`
- **Severity**: low
- **Impact**: Graph visualization in UI would show wrong icons/colors for node roles

### [FRICTION] #12 — `plan` fails with "must have exactly one orchestrator node" on some prompts

- **Command**: `echo "y" | python gimo.py plan "Add a README.md to gimo_prueba with project description" -w gimo_prueba`
- **Expected**: Plan generated successfully
- **Actual**: `Plan generation failed: Plan must have exactly one orchestrator node`
- **Note**: Simpler prompt ("Create a simple hello world script") succeeds. The LLM sometimes generates a plan structure that doesn't match the validator's expectations. This is a plan generation robustness issue, not a total failure.
- **Severity**: medium

### [FRICTION] #13 — `mastery status` reports `hardware_state: critical`

- **Command**: `python gimo.py mastery status`
- **Expected**: Hardware state normal when running on a standard dev machine
- **Actual**: `hardware_state: critical`
- **Severity**: low
- **Suspicion**: Same root cause as #10 — HardwareMonitorService thresholds too aggressive

---

## Summary of Commands Tested

| Command | Status | Notes |
|---------|--------|-------|
| `gimo --help` | OK | All commands listed |
| `gimo up` | FAIL | #1 — Still hangs indefinitely |
| `gimo down` | OK | Kills server correctly |
| `gimo ps` | OK | Reports instances correctly |
| `gimo doctor` | OK | Clean output, bond display fixed |
| `gimo status` | OK | Authoritative status correct |
| `gimo init` | OK | (tested in prior rounds, stable) |
| `gimo chat -m "..." -w <dir>` | OK | Workspace targeting works, title auto-generated |
| `gimo chat -m "..." -x -w <dir>` | OK | File written to correct workspace |
| `gimo plan "..." -w <dir>` | PARTIAL | Simple prompts work, complex prompts fail (#12) |
| `gimo run <id> --no-confirm --auto` | FAIL | False unreachable (#5), run errors (#6) |
| `gimo diff` | OK | Correct "No diff output" |
| `gimo config --show` | OK | Shows config correctly |
| `gimo audit` | PARTIAL | Dependencies always fails (#8) |
| `gimo providers list` | OK | Clean table output |
| `gimo providers test <name>` | OK | Auth status now correct (R6 fix confirmed) |
| `gimo providers models` | PARTIAL | Metadata all None (#4) |
| `gimo providers auth-status` | OK | Shows correct auth table |
| `gimo repos list` | FAIL | Shows filesystem repos (#2) |
| `gimo threads list` | OK | Shows all threads |
| `gimo trust status` | OK | "No trust data yet" |
| `gimo trust reset` | FAIL | 403 admin required (#7) |
| `gimo mastery status` | PARTIAL | hardware_state: critical (#13) |
| `gimo mastery forecast` | OK | No data yet |
| `gimo observe metrics` | OK | Comprehensive metrics table |
| `gimo observe alerts` | OK | "No active alerts" |
| `gimo observe traces` | OK | "No traces recorded yet" |
| `gimo skills list` | OK | Shows registered skills |
| `gimo skills run <id>` | PARTIAL | Queued but displays as failure (#3) |

---

## Endpoints Tested (Direct API)

| Endpoint | Status | Notes |
|----------|--------|-------|
| GET /health | 200 | OK |
| GET /ops/capabilities | 200 | active_model/provider null (#9), system_load critical (#10) |
| GET /ops/graph | 200 | Node types swapped (#11) |
| GET /ops/security/dependencies | 404 | Endpoint missing (#8) |
| GET /ops/observability/rate-limits | 200 | OK |
| GET /ops/threads/{id} | 200 | OK, title populated |
| GET /ops/runs/{id} | 200 | Shows status but logs opaque (#6) |
| GET /auth/check | 200 | Returns false (expected — cookie auth, not Bearer) |

---

## PHASE 1 SUMMARY

### Total issues: 13

| Severity | Count | Issues |
|----------|-------|--------|
| BLOCKER | 1 | #1 |
| CRITICAL | 1 | #5 |
| HIGH | 3 | #2, #6, #10 |
| MEDIUM | 4 | #3, #8, #9, #12 |
| LOW | 4 | #4, #7, #11, #13 |

### Key finding: R6 fixes did not persist

6 of 12 R6 fixes appear to have reverted. The most likely explanation is that R6 changes were committed but the running server binary does not reflect them — or the changes were made to code paths that don't execute in the current configuration.

### Systemic patterns observed:

1. **Server startup broken** — `gimo up` never worked; manual uvicorn is the only path (#1)
2. **CLI timeout logic still guesses** — `run` falsely reports unreachable despite server being up (#5)
3. **Repos endpoint still scans filesystem** — R6 registry-only rewrite not effective (#2)
4. **Hardware monitor too aggressive** — Reports critical on normal dev machine, cascades to degraded generation (#10, #13)
5. **Model inventory doesn't enrich metadata** — Pricing data fallback not working (#4)
6. **Audit references deleted endpoint** — `/ops/security/dependencies` returns 404 (#8)

### Suspicions for Phase 2:

1. R6 fixes may be in code but server runs stale bytecode / different import path
2. `gimo up` subprocess spawning is fundamentally broken on Windows (detach issue)
3. `HardwareMonitorService` psutil thresholds need calibration for dev workstations
4. `capabilities` active_model population depends on a startup sequence that fails silently
5. Graph node type assignment uses wrong field mapping
6. `skills run` CLI checks `response.status_code == 200` instead of `2xx`
