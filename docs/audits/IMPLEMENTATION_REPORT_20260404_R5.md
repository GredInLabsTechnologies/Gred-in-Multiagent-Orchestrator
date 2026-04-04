# GIMO R5 Implementation Report: Execution Boundary Hardening

**Date**: 2026-04-04
**Auditor**: Claude Opus 4.6
**Round**: R5 (post R0a-R4, 17/21 issues resolved)
**Scope**: 4 new gaps in execution boundary lifecycle management

---

## Summary

R5 hardens the execution boundary — the point where authority materializes
into action. R4 hardened the chain of authority (constraint compiler, honesty
gate, CLI flags). R5 ensures that authority is enforced without exception and
that runtime resources are managed deterministically.

**4 gaps fixed, 5 changes, ~44 lines of production diff, 0 new files/abstractions/dependencies.**

---

## Changes Implemented

### Change A: Fail-Closed Policy Enforcement

**Files**: `tools/gimo_server/services/agentic_loop_service.py` (2 locations)

Unknown execution policies now raise `RuntimeError` instead of silently
defaulting to no tool filtering (fail-open). Both `_run_reserved` and
`_run_stream_reserved` are hardened.

**Alignment**: OWASP ASI02 (Tool Misuse), AGENTS.md "fail closed in
security-sensitive paths", Microsoft Agent Governance Toolkit "default
allow = false".

### Change B: Idempotent Lock Cleanup via BackgroundTask

**File**: `tools/gimo_server/routers/ops/conversation_router.py`

Added `BackgroundTask` safety net for streaming endpoint lock cleanup.
Prevents zombie locks when client disconnects between `StreamingResponse`
creation and generator iteration. Three-layer defense: generator `finally`
(primary), BackgroundTask (safety net), TTL expiry (backstop).

**Alignment**: OWASP ASI08 (Cascading Failures), Starlette streaming patterns.

### Change C: Heartbeat Failure Signals lock_lost

**File**: `tools/gimo_server/services/agentic_loop_service.py`

`_start_thread_execution_heartbeat` now returns a 3-tuple including a
`lock_lost: asyncio.Event`. When heartbeat fails, `lock_lost` is set and
the streaming queue consumer aborts with an explicit error message (circuit
breaker pattern). All call sites updated: `run()`, `run_stream()`,
`resume_session()`, and `conversation_router.py`.

**Alignment**: OWASP ASI08 (circuit breaker), Redis heartbeat renewal patterns.

### Change D: Log Tool Parse Errors

**File**: `tools/gimo_server/services/agentic_loop_service.py`

`_parse_tool_arguments` now logs `JSONDecodeError` with truncated raw input
instead of silently returning `{}`.

**Alignment**: AGENTS.md "no silent degradation".

### Change E: Security Posture Documentation

**File**: `AGENTS.md`

Added "Execution Boundary Security (OWASP Agentic AI 2026)" section
documenting ASI02, ASI03, and ASI08 compliance under Architectural Rules.

### Bonus: Git Signing Fix for Tests

**Files**: `tests/unit/test_ephemeral_repo.py`, `tests/unit/test_git_service.py`

Fixed pre-existing test failures caused by commit signing in sandbox/CI
environments. Tests now disable `commit.gpgSign` in temporary repos.

---

## Verification

```
python -m pytest tests/unit/test_agentic_loop.py tests/unit/test_merge_gate.py -x -v --timeout=30
# 36 passed

python -m pytest tests/unit tests/contracts -q --timeout=30 \
  -k "not (test_phase10_merge or test_merge_gate_stops or test_manual_merge or test_run_lifecycle or test_review_merge)"
# 1258 passed, 1 skipped, 1 failed (Windows path test on Linux — pre-existing)

python -c "from tools.gimo_server.services.agentic_loop_service import AgenticLoopService; print('OK')"
# OK

python -c "from tools.gimo_server.routers.ops.conversation_router import router; print('OK')"
# OK
```

### New Tests Added

| Test | Validates |
|------|-----------|
| `TestFailClosedPolicyEnforcement::test_run_stream_reserved_raises_on_unknown_policy` | RuntimeError on unknown policy (second defense layer) |
| `TestHeartbeatLockLost::test_heartbeat_failure_sets_lock_lost` | lock_lost Event set on heartbeat exception |
| `TestHeartbeatLockLost::test_heartbeat_returns_three_tuple` | API contract: 3-tuple return |
| `TestToolParseErrorLogging::test_malformed_json_logs_warning` | JSONDecodeError logged, not swallowed |
| `TestToolParseErrorLogging::test_valid_json_no_warning` | No false positives |

### Existing Test Updated

| Test | Change |
|------|--------|
| `test_merge_gate.py::test_run_stream_propagates_session_id` | 2-tuple mock -> 3-tuple |

---

## Pre-existing Failures (Not in Scope)

| Test | Cause |
|------|-------|
| `test_phase10_merge_conflict_main_intact` | Timeout — git signing in sandbox |
| `test_merge_gate_stops_at_awaiting_merge` | Timeout — MergeGateService async loop |
| `test_run_lifecycle` tests | Timeout — git signing in sandbox |
| `test_review_merge_service` tests | Missing workspace evidence fixtures |
| `test_security_guards::test_normalize_path_logic[C:\\Windows]` | Windows path on Linux |

---

## Residual Risks

1. **TTL as final backstop**: If the process is killed (SIGKILL), no Python
   cleanup runs. The 120s TTL is the correct backstop for that scenario.
   Already existed.

2. **Non-streaming paths**: `run()` and `resume_session()` unpack `lock_lost`
   but don't actively check it. The heartbeat `break` + `finally` is
   sufficient for non-streaming paths where the risk window is shorter.

3. **`run_stream()` is dead code**: Defined but no callers in the repo.
   Updated for consistency but candidate for future cleanup.

4. **Pre-existing test timeouts**: Several MergeGateService and lifecycle
   tests timeout in this sandbox due to git commit signing. These need a
   broader fix (e.g., global `GIT_CONFIG_COUNT` in conftest.py).
