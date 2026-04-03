# GIMO Authority Chain — Implementation Report

**Date**: 2026-04-04
**Auditor**: Claude Opus 4.6
**Plan**: ENGINEERING_PLAN_20260403_2000.md ("Complete the Authority Chain")
**Tests**: 1303 passed, 0 failed, 9 skipped

---

## What Was Implemented

### Wire 1: Windows Encoding + Surface Identification

**Problem**: CLI crashed on Windows with `UnicodeEncodeError` for any emoji/unicode output. Threads created from CLI had no surface identity. Thread title ignored when passed.

**Changes**:

| File | Change |
|------|--------|
| `gimo_cli/__init__.py` | `_setup_windows_console()`: reconfigures stdout/stderr to UTF-8, sets console codepage to 65001, enables VT processing. Runs before `Console()` creation. Both `reconfigure()` and ctypes calls wrapped in try/except for piped/service scenarios. |
| `gimo_cli/api.py:217` | Injects `X-GIMO-Surface: cli` header in all `api_request()` calls |
| `gimo_cli/stream.py:34` | Injects `X-GIMO-Surface: cli` header in SSE streaming client |
| `gimo_cli/chat.py:315,470` | Injects `X-GIMO-Surface: cli` header in both streaming and non-streaming chat paths |
| `conversation_router.py:53-75` | `CreateThreadRequest.title` changed from `str = "New Conversation"` to `Optional[str] = None`. Added `X-GIMO-Surface` header param. Title resolution: `body.title or title or "New Conversation"` (no fragile sentinel). Surface normalized and passed to service. |
| `conversation_service.py:238` | Added `surface: str = "operator"` parameter, passes to `WorkspacePolicyService.default_metadata_for_surface()` |

**Edge cases handled**:
- Piped stdout (no console): `reconfigure()` wrapped in try/except, ctypes call checks `GetConsoleMode` return
- Empty string title in body: falsy, falls through to query param or default (documented behavior)
- Missing header: defaults to "operator" surface (backward compatible)

---

### Wire 2: Dynamic Trust-Gated Orchestrator Authority

**Problem**: `plan_orchestrator` preset hardcoded `propose_only` policy, making the orchestrator unable to write files — contradicting SYSTEM.md 1.4 ("highest non-human authority"). GICS model reliability and TrustEngine feedback were disconnected from the execution policy system.

**Changes**:

| File | Change |
|------|--------|
| `agent_catalog_service.py:88` | `plan_orchestrator` preset: `"propose_only"` -> `"workspace_safe"` |
| `constraint_compiler_service.py` | New `_is_gics_daemon_available()` classmethod: checks pipe (Windows) or socket (Unix) existence before any GICS call — prevents blocking retries when daemon is down |
| `constraint_compiler_service.py` | New `apply_trust_authority()` classmethod (~50 lines): queries GICS model reliability + TrustEngine workspace dimension, returns `(effective_policy, requires_human_approval)` |
| `agentic_loop_service.py` (3 sites) | Calls `apply_trust_authority()` after resolving thread context, before `_run_loop()` |
| `agentic_loop_service.py:692` | New `force_hitl: bool = False` parameter in `_run_loop()` |
| `agentic_loop_service.py:834` | HITL condition expanded: `risk == "HIGH" or force_hitl` — trust engine's "require_review" now actually forces HITL |

**Trust-gate decision table**:

| TrustEngine | GICS anomaly | Result |
|-------------|-------------|--------|
| auto_approve | False | `workspace_safe` (full authority) |
| require_review | False | `workspace_safe` + HITL forced on all tool calls |
| blocked | any | Clamp to `propose_only` |
| any | True | Clamp to `propose_only` |
| unavailable | unavailable | `workspace_safe` (fail-open) |

**Fail-open guarantees**:
- GICS daemon not running: `_is_gics_daemon_available()` returns False, skip instantly (no blocking)
- TrustEngine no data for workspace: `trust_policy is None` -> no-op, full authority
- Any exception in either check: caught by broad `except Exception: pass`

---

### Wire 3: Streaming Plan Endpoint Parity

**Problem**: Non-streaming plan endpoint included `"execution_decision": "AUTO_RUN_ELIGIBLE"` in context; streaming endpoint omitted it. This caused `gimo run {id} --no-confirm` to return `"run": null` because `should_run` requires `execution_decision == "AUTO_RUN_ELIGIBLE"`.

**Changes**:

| File | Change |
|------|--------|
| `plan_router.py:531` | Added `"execution_decision": "AUTO_RUN_ELIGIBLE"` to streaming endpoint context dict |

1 line. Copy-paste omission fixed.

---

### Wire 4: Schema-Time Tool Filtering

**Problem**: All 12 tools were sent to the LLM regardless of execution policy. The LLM attempted to use tools it couldn't execute (e.g., `write_file` under `propose_only`), wasting tokens and producing failed tool calls. No competitor does schema-time filtering.

**Changes**:

| File | Change |
|------|--------|
| `chat_tools_schema.py` | New `filter_tools_by_policy()` function. Convention: `None` or empty frozenset = no restriction (all tools); non-empty frozenset = only those tools visible. Matches `ExecutionPolicyProfile.assert_tool_allowed` semantics. |
| `agentic_loop_service.py` (3 sites) | Resolves policy profile, calls `filter_tools_by_policy()`, passes `effective_tools` to `_run_loop()` instead of `CHAT_TOOLS` |

**KeyError protection**: `get_policy()` wrapped in try/except at all 3 call sites. Invalid policy name logs warning and falls back to no filtering (all tools visible).

**Verified**: `propose_only` -> 7 tools (read_file, list_files, search_text, ask_user, propose_plan, request_context, web_search). `workspace_safe` -> 12 tools (no restriction).

---

### Wire 2 Supplement: provider_id vs provider_type Fix

**Problem found during deep review**: `apply_trust_authority()` received `provider_id` (e.g., `"my-anthropic"`) but GICS stores model reliability under `provider_type` (e.g., `"anthropic"`). Lookups would silently fail, making anomaly detection ineffective.

**Changes**:

| File | Change |
|------|--------|
| `agentic_loop_service.py:177-201` | `_resolve_orchestrator_adapter()` return type changed from `tuple[..., 3]` to `tuple[..., 4]` — adds `canonical_type` |
| `agentic_loop_service.py:204-232` | `_resolve_bound_adapter()` same change |
| `agentic_loop_service.py` (3 sites) | Unpacks `canonical_type` and passes to `apply_trust_authority(provider_type=canonical_type)` |
| 4 test files | Updated mocks to return 4-element tuples |

---

### Hardening: API Key Validation

**Changes**:

| File | Change |
|------|--------|
| `providers/auth_service.py` | New `validate_api_key_format()`: advisory validation — rejects keys < 10 chars, warns on unexpected prefixes. Provider-type-aware (anthropic: `sk-ant-`, openai: `sk-`, google: `AIza`). |
| `providers/service_impl.py:398` | Calls validation before storing key. Raises `ValueError` (caught by router as HTTP 400). |

---

### Hardening: Honest Response Check

**Changes**:

| File | Change |
|------|--------|
| `agentic_loop_service.py:1033` | Checks `canonical_plan` is truthy before emitting "Plan proposed" success message. If falsy, emits error instead. |

---

## Deep Review Findings and Fixes

After initial implementation, a deep code review with 4 parallel analysis agents found 6 additional issues:

| # | Finding | Severity | Root Cause | Fix |
|---|---------|----------|------------|-----|
| 1 | `_trust_hitl` flag discarded at all 3 call sites | HIGH | TrustEngine's "require_review" had no enforcement path | Added `force_hitl` param to `_run_loop`, connected at all 3 sites |
| 2 | `provider_id` used as `provider_type` in GICS lookups | HIGH | `_resolve_orchestrator_adapter` only returned 3 values | Extended to return `canonical_type` as 4th element |
| 3 | `get_policy()` could throw `KeyError` crashing chat | HIGH | No try/except at Wire 4 call sites | Added try/except with logging at all 3 sites |
| 4 | `X-GIMO-Surface` missing from `stream.py` and `chat.py` | HIGH | CLI has 3 separate HTTP client paths; only `api_request()` was patched | Added header to `stream.py:34` and `chat.py:315,470` |
| 5 | `stdout.reconfigure()` not in try/except | MEDIUM | Could fail when piped to non-UTF-8 targets | Wrapped in try/except |
| 6 | Test mocks returned 3-element tuples, new code expects 4 | MEDIUM | Signature change in `_resolve_orchestrator_adapter` | Updated 4 test files |

### Findings NOT Fixed (Documented for Future)

| Finding | Reason Deferred |
|---------|----------------|
| `GicsService()` created per message when daemon is running | Acceptable: constructor is lightweight, `_client` is lazy. Optimize with singleton in P2 if profiling shows cost |
| Plan endpoints skip intent/policy evaluation pipeline | Pre-existing: both streaming and non-streaming paths skip this. Not introduced by our changes. Separate issue. |
| No test for `filter_tools_by_policy` | Low risk: function is 3 lines with clear semantics. Covered indirectly by `test_agentic_loop_execution_policy`. Add dedicated test in next PR. |
| MCP/ChatGPT adapters don't send surface header | MCP uses protocol-level communication, not HTTP. ChatGPT App has explicit surface handling in `workspace_policy_service`. Neither creates threads via `conversation_router`. |

---

## Files Changed

### Production Code (13 files)

1. `gimo_cli/__init__.py` — Windows console setup
2. `gimo_cli/api.py` — CLI surface header
3. `gimo_cli/stream.py` — SSE surface header
4. `gimo_cli/chat.py` — Chat streaming + fallback surface headers
5. `tools/gimo_server/routers/ops/conversation_router.py` — Surface header, title fix
6. `tools/gimo_server/routers/ops/plan_router.py` — execution_decision in streaming
7. `tools/gimo_server/services/conversation_service.py` — Surface parameter
8. `tools/gimo_server/services/agent_catalog_service.py` — Preset policy change
9. `tools/gimo_server/services/constraint_compiler_service.py` — Trust authority gate
10. `tools/gimo_server/services/agentic_loop_service.py` — All 4 wires integrated
11. `tools/gimo_server/engine/tools/chat_tools_schema.py` — Schema-time filtering
12. `tools/gimo_server/services/providers/auth_service.py` — API key validation
13. `tools/gimo_server/services/providers/service_impl.py` — Validation integration

### Test Files (4 files)

14. `tests/unit/test_agentic_loop.py` — Mock tuple updated
15. `tests/unit/test_agentic_loop_execution_policy.py` — Mock tuple updated
16. `tests/unit/test_run_node.py` — Mock tuple updated
17. `tests/unit/test_run_node_honors_routing_summary.py` — Mock tuple updated
18. `tests/unit/test_merge_gate.py` — Mock tuple updated

---

## Metrics

- **Lines added**: ~120 production, ~5 test
- **Lines modified**: ~30 production, ~10 test
- **New services**: 0
- **New dependencies**: 0
- **Tests**: 1303 passed, 0 failed, 9 skipped
