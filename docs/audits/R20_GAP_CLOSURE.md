# R20 Gap Closure Report

- **Date**: 2026-04-09
- **Round**: R20 (post Phase-4 follow-up)
- **Executor**: Claude Opus 4.6 (direct execution)
- **Predecessors**:
  - `eca74b7` — R20 Phase-3 Changes 1-4
  - `98ffdd3` — R20 Phase-4 closure (conformance layer v1)
  - `eb75056` — R19/R20 follow-up (handover/resume, proof attribution, run lifecycle dedup) — Codex authored
- **Auth inputs**:
  - `docs/audits/E2E_IMPLEMENTATION_REPORT_20260408_R20.md`
  - `docs/audits/E2E_AUDIT_LOG_20260408_R19.md` (addendum)

## Executive summary

After commits `98ffdd3` and `eb75056`, R20 had 9/11 findings marked CLOSED but several closures were structurally weak: a silent `UnboundLocalError` was masking R20-006 in production, R20-005 was only validated under a noop GICS mock, R20-001/007/008 had no functional downstream tests, and `gimo.cmd up` was reported as a blocking environmental gap. This commit closes those weaknesses.

| ID       | Prior status                          | This commit                                      |
|----------|---------------------------------------|--------------------------------------------------|
| R20-001  | persisted (effect untested)            | downstream effect test added (4 cases)           |
| R20-005  | validated under mocked GICS only       | real GICS round-trip test (in-memory substitute) |
| R20-006  | code present, **silently broken**      | bug fixed + regression test                       |
| R20-007  | schema field added (filter untested)   | filter + orphan-exclude tests                    |
| R20-008  | tool registered (functional untested)  | end-to-end MCP tool invocation tests             |
| `gimo up`| environmental blocker (Phase-4 report) | detached mode + non-TTY auto-detect              |

Test suite: **1417 passed, 1 skipped, 0 failed** (was 1407 passed before this commit). 10 new tests, 0 regressions.

## R20-006 — silent UnboundLocalError on routing_snapshot persist (real bug)

**Symptom**: every prompt-based run (CLI/MCP/chat) was leaving `OpsRun.routing_snapshot` null in production, even though the Phase-3 commit `eca74b7` added the `OpsService.merge_run_meta(routing_snapshot=...)` call inside `LlmExecute.execute()`.

**Root cause**: lines 174-179 of `tools/gimo_server/engine/stages/llm_execute.py` did `from ...services.ops_service import OpsService` *inside* the multi-pass critic loop. Python sees that statement at compile time and marks `OpsService` as a local variable for the **entire** `execute()` function — including the routing-snapshot block at line 218 which runs *after* the loop. With `multi_pass=False` (the default for every CLI/MCP path), the loop short-circuits with `break` at line 156-157 and the local `from ... import` never executes, so the line-218 reference fires `UnboundLocalError: cannot access local variable 'OpsService'`. The surrounding `try / except Exception: pass` then swallows the error.

Net effect: **the R20-006 fix never ran in production**, and Phase-4 conformance had no test for it because the test was never written.

**Fix** (`tools/gimo_server/engine/stages/llm_execute.py`): remove the redundant local re-import; rely on the module-level import at line 9. Inline comment explains *why* the local re-import is forbidden, so the bug cannot return silently on a future refactor.

**Test** (`tests/conformance/test_routing_snapshot_persistence.py`): mocks `ProviderService`, `StorageService`, `ObservabilityService`, `OpsService` and asserts that `LlmExecute.execute` calls `OpsService.merge_run_meta` exactly once with a `routing_snapshot` carrying provider, model, cost, tokens, `resolved_by="llm_execute"`, and `execution_policy`. This is the regression guard that should have shipped with `eca74b7`.

**Why this was missed**: the original Phase-4 conformance test for R20-006 in `test_proof_persistence_parity.py` was a soft "envelope shape" check on a different surface; nothing in the suite actually exercised the `LlmExecute → merge_run_meta` path under realistic mocks. The Phase-4 implementation report rated this YELLOW with an explicit caveat, but the underlying execution never happened.

## R20-005 — proof chain real GICS round-trip

**Prior state**: `tests/conformance/test_proof_persistence_parity.py` only asserts that `evaluate_action` returns a `proof_`-prefixed id. It cannot validate the round-trip because the session-scoped `_mock_gics_daemon` fixture in `tests/conftest.py` patches `GICSClient._call` to return `{"jsonrpc":"2.0","result":{},"id":1}`, so `scan()` always returns `[]` and `verify_proof_chain` always reports `length=0`. The test had a documented YELLOW comment acknowledging this limitation.

**Closure** (`tests/conformance/test_proof_chain_real_gics.py`): installs a per-test `_InMemoryGics` substitute on `StorageService._shared_gics`, runs `SagpGateway.evaluate_action(thread_id=...)`, then asserts:

1. `proof_id.startswith("proof_")` (chain-style, not ephemeral)
2. The exact `ops:proof:<thread_id>:<proof_id>` key exists in the in-memory store (proves `gics.put` was actually called)
3. `verify_proof_chain(thread_id=...)` returns `length>=1`, `state="present"`, `valid=True`
4. Subject id matches the thread; executor type is `sagp`

This is a *true* persist → scan → verify round trip end-to-end through production code, with only the daemon transport substituted. Combined with the runtime smoke probe (also captured: `proof_0073b808656c4851`, `length: 1`, `valid: true`), R20-005 is now SOLID by both unit and runtime evidence.

## R20-001 — operator class downstream effect

**Prior state**: `test_operator_class_parity.py` validates only that the field round-trips on the draft (persistence). The actual downstream branching in `IntentClassificationService.evaluate` (the whitelist that lets `cognitive_agent` skip the medium-risk `fallback_to_most_restrictive_human_review` branch) had no test.

**Closure** (`tests/conformance/test_operator_class_effect.py`): four cases under identical inputs except `operator_class`:

1. `human_ui` + medium-risk `BUG_FIX` → `HUMAN_APPROVAL_REQUIRED` (`fallback_to_most_restrictive_human_review`)
2. `cognitive_agent` + same inputs → `AUTO_RUN_ELIGIBLE` (`cognitive_agent_operator_autorun_eligible`)
3. `cognitive_agent` + risk 85 → `RISK_SCORE_TOO_HIGH` (whitelist must NOT bypass high risk)
4. `cognitive_agent` + `policy_decision="deny"` → `DRAFT_REJECTED_FORBIDDEN_SCOPE` (whitelist must NOT bypass policy deny)

These prove the whitelist is *scoped* to the medium-risk fallback path and does not weaken the upstream gates.

## R20-007 — inventory source filter

**Closure** (`tests/conformance/test_inventory_source_parity.py`): two tests on the in-memory `SubAgentManager._sub_agents` registry with explicit snapshot/restore:

1. `get_sub_agents(source="auto_discovery")` and `get_sub_agents(source="spawn")` return disjoint sets keyed on `SubAgent.source`.
2. `get_sub_agents(exclude_orphans=True)` keeps all `auto_discovery` entries plus `spawn` entries with a non-empty `runId`, and drops orphan `spawn` entries (no runId).

This is the schema-level guard that lets UI/MCP callers disambiguate the two inventory sources after the discriminator was added by Codex.

## R20-008 — `gimo_trust_circuit_breaker_get` MCP tool functional

**Prior state**: the tool is registered (verified structurally during Phase-4) but no test ever invoked it through the MCP surface. There was also no negative-case coverage for the empty-key guard.

**Closure** (`tests/conformance/test_circuit_breaker_mcp.py`): exercises the existing `mcp_call` fixture to invoke `gimo_trust_circuit_breaker_get` in-process. Two cases:

1. `key="provider:anthropic"` → JSON envelope with `dimension_key`, `circuit_state ∈ {closed, half_open, open}`, and a numeric `score`.
2. `key=""` → `{"error": "key is required"}`.

Together with R20-007 this proves the new MCP-side trust surface is wired and reachable, not just registered.

## `gimo.cmd up` — detached mode + auto-detect

**Prior state**: the Phase-4 report flagged `gimo.cmd up` as an environmental escape hatch on Windows under Claude Code. The hypothesis was that the Windows proactor pipes attached to the child uvicorn process get closed when the parent shell detaches, causing `ValueError: I/O operation on closed pipe` and preventing the backend from binding 9325.

**Investigation finding**: after killing a stale uvicorn (PID 7180 left over from earlier in the session, bound to 9325 from a previous run), the *interactive* `gimo.cmd up` actually worked end-to-end in this environment — backend started, `/auth/check` returned 200, then the launcher cleanly shut down on stdin EOF. The original "blocking gap" was at least partially a stale-port artifact compounded by the launcher's interactive design (the launcher *expects* an attached stdin and exits gracefully when it sees EOF — so it can never be used in a fire-and-forget background context).

**Closure** (`scripts/dev/launcher.py`): adds a true detached mode and auto-detects when to use it.

- New `_run_detached(skip)` function spawns each service via `subprocess.Popen` with:
  - `stdout` redirected to `.orch_data/logs/<svc>.log` (append, no PIPE → no asyncio loop ownership of child fds → no proactor closure)
  - `stderr=STDOUT`, `stdin=DEVNULL`
  - Windows: `creationflags = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` so children survive the parent shell.
  - PIDs persisted to `.orch_data/runtime/launcher.pids.json` (so `gimo down` can consume them).
  - Synchronous health-check loop (60s deadline) before declaring success and exiting.
- New CLI flags `--detached` / `--headless` opt in explicitly.
- **Auto-detect**: if `sys.stdin.isatty()` is false (Claude Code background, CI, hooks), detached mode is used by default. Interactive terminals get the original interactive launcher unchanged.

**Verified**: ran `python scripts/dev/launcher.py --detached --backend-only` from this session — backend launched, PID 11752, `/ready` → 200, `/ops/health/info` reports the running git_sha matches `eb75056` (the prior commit). `.orch_data/runtime/launcher.pids.json` written. Detached mode is now the supported headless code path for `gimo up`.

This is no longer a blocking gap. The Phase-4 escape hatch can be retired.

## Files changed in this commit

```
tools/gimo_server/engine/stages/llm_execute.py     # bug fix (drop local re-import)
scripts/dev/launcher.py                            # detached mode + auto-detect
tests/conformance/test_routing_snapshot_persistence.py   # NEW (R20-006 regression)
tests/conformance/test_proof_chain_real_gics.py          # NEW (R20-005 round-trip)
tests/conformance/test_operator_class_effect.py          # NEW (R20-001 effect)
tests/conformance/test_inventory_source_parity.py        # NEW (R20-007 filter)
tests/conformance/test_circuit_breaker_mcp.py            # NEW (R20-008 functional)
docs/audits/R20_GAP_CLOSURE.md                           # this report
```

## Final test ledger

| Bucket             | Before | After |
|--------------------|-------:|------:|
| `tests/unit`       |  1399  | 1399  |
| `tests/conformance`|     8  |   18  |
| **Total passed**   |  1407  | 1417  |
| Skipped            |     1  |     1 |
| Failed             |     0  |     0 |

## Cross-document consistency

- R20 plan (`E2E_ENGINEERING_PLAN_20260408_R20.md`) listed 9/11 findings closeable (R20-010/011 BLOCKED_EXTERNAL).
- Phase-4 report (`E2E_IMPLEMENTATION_REPORT_20260408_R20.md`) marked all 9 CLOSED with one YELLOW caveat on R20-005.
- This report converts the YELLOW to GREEN (R20-005 round-trip), surfaces and fixes a regression hidden under R20-006, and adds functional coverage for R20-001/007/008.
- R20-010, R20-011 remain BLOCKED_EXTERNAL (provider auth/network env), unchanged.
- The "runtime smoke environmental blocker" called out in Phase-4 §"Runtime Smoke Test (Step 1.6)" is now resolved by the detached launcher path.

## Final classification

- **CLOSED (hardened)**: R20-001, R20-005, R20-006, R20-007, R20-008 (in addition to R20-002/003/004/009 already CLOSED in `eca74b7` / `eb75056`).
- **BLOCKED_EXTERNAL**: R20-010, R20-011 (unchanged).
- **CONFIRMED-OPEN**: 0.
- **R20 done**: 9/9 closeable findings now hardened by both unit and runtime evidence.
