# GIMO Forensic Audit — Phase 4: Implementation Report (Round 10)

**Date**: 2026-04-05
**Auditor**: Claude Opus 4.6
**Input**: `docs/audits/E2E_ENGINEERING_PLAN_20260405_R10.md` (approved plan v2)
**Verification**: `python -m pytest -x -q` — 1341 passed, 0 failures (3:11)

---

## Session Summary

This session executed a full 4-phase forensic audit of GIMO:

1. **Phase 1** — Black-box CLI stress test: 35+ commands, discovered 4 issues (lowest count in 10 rounds).
2. **Phase 2** — Root-cause tracing with 4 parallel subagents: traced all issues + Dynamic Model Pricing investigation.
3. **Phase 3** — SOTA research with 9 parallel subagents across 200+ sources. Identified 3 genuine differentiators. Honest assessment: 1 change is first-to-market, rest are good engineering.
4. **Phase 4** — Implementation of all 5 changes from approved plan.

---

## Changes Implemented

### Change 1: Fix `/v1/v1` URL Bug [BLOCKER]

| File | Lines | Description |
|------|-------|-------------|
| `tools/gimo_server/services/providers/adapter_registry.py` | +4 | Strip `/v1` suffix from `base_url` before passing to `AnthropicAdapter` at both routing paths (account auth line 30, API key auth line 37). Prevents `DEFAULT_BASE_URLS` OpenAI-compat convention from colliding with AnthropicAdapter's own `/v1/messages` append. |

**Result**: `https://api.anthropic.com/v1` → stripped to `https://api.anthropic.com` → adapter appends `/v1/messages` → correct URL `https://api.anthropic.com/v1/messages`.

---

### Change 2: Per-Action Cost in SSE Events [FIRST-TO-MARKET]

| File | Lines | Description |
|------|-------|-------------|
| `tools/gimo_server/services/agentic_loop_service.py` | +6 | Added `cumulative_cost` field to `iteration_start` event (line 756). Added `iteration_cost` + `cumulative_cost` fields to `tool_call_end` event (line 1140). |

**SSE event payloads after change**:

```json
// iteration_start (before each LLM turn):
{"iteration": 1, "mood": "neutral", "cumulative_cost": 0.000000}

// tool_call_end (after each tool execution):
{"tool_call_id": "...", "tool_name": "read_file", "status": "success",
 "duration": 0.12, "risk": "LOW",
 "iteration_cost": 0.003200, "cumulative_cost": 0.003200}
```

**Why first-to-market**: Verified across 15+ tools (Aider, Cline, Claude Code, Cursor, LangSmith, Codex CLI, etc.) — no AI coding tool or agent framework emits per-action cost in real-time during execution. Aider shows per-message cost after completion (closest). Cline shows cumulative total. Nobody shows cost flowing tool-by-tool as it happens.

**Multi-surface impact**: All surfaces (CLI, TUI, Web) consume the same SSE events. The new fields are additive — existing renderers ignore unknown fields, new renderers can display them.

---

### Change 3: Tier-Based Pricing Fallback

| File | Lines | Description |
|------|-------|-------------|
| `tools/gimo_server/services/economy/cost_service.py` | +13 | Added `TIER_DEFAULT_PRICING` dict (5 tiers, conservative USD/1M token defaults derived from actual model averages). Modified `get_pricing()` to check tier inference before falling back to $0 for non-local models. |
| `tests/unit/test_cost_service.py` | +7 -2 | Updated test: `test_unknown_model_falls_back_to_local` → `test_unknown_model_uses_tier_default` (asserts non-zero pricing) + added `test_local_model_falls_back_to_zero` (preserves $0 for local models). |

**Tier defaults**:

| Tier | Input $/1M | Output $/1M | Class |
|------|-----------|------------|-------|
| 1 | $0.10 | $0.20 | nano |
| 2 | $0.40 | $1.50 | small/mini |
| 3 | $0.80 | $2.00 | balanced |
| 4 | $3.00 | $12.00 | premium |
| 5 | $12.00 | $60.00 | flagship |

**Impact**: Unknown models (o3, mistral-*, cohere-*, etc.) now get non-zero cost tracking. `CascadeService.get_cheapest_for_capability()` no longer returns unknown models as "cheapest" at $0. Budget alerts fire for any model.

---

### Change 4: Registry Test Isolation

| File | Lines | Description |
|------|-------|-------------|
| `tests/unit/test_recon_gate.py` | +8 -2 | `session_with_repo` fixture now saves original `repo_registry.json` before writing, restores in `finally` block after yield. Matches pattern from `conftest.py:203-232`. |
| `tools/gimo_server/repo_registry.json` | 1 | Reset to `{"repos": []}` (removed stale pytest temp path). |

---

### Change 5: HITL Mode Context in Status

| File | Lines | Description |
|------|-------|-------------|
| `gimo_cli/chat.py` | +6 | Added `_hitl_desc` dict mapping permission modes to plain-language explanations. Status line now shows: `Permissions: suggest (agent proposes, you approve)` |

---

## Diff Summary

```
 tools/gimo_server/services/providers/adapter_registry.py  |  +4
 tools/gimo_server/services/agentic_loop_service.py        |  +6
 tools/gimo_server/services/economy/cost_service.py        |  +13
 tests/unit/test_cost_service.py                           |  +7 -2
 tests/unit/test_recon_gate.py                             |  +8 -2
 tools/gimo_server/repo_registry.json                      |  ~1
 gimo_cli/chat.py                                          |  +6
 ────────────────────────────────────────────────────────────
 7 files changed, +44 -4 (net: +40 lines)
```

---

## Verification

```bash
$ python -m pytest -x -q
1341 passed, 9 skipped, 11 deselected, 4 warnings in 191.19s (0:03:11)
```

All 1341 tests pass. Zero failures. One test updated to reflect new behavior (tier pricing replaces silent $0).

Syntax verification passed on all 5 edited production files via `ast.parse()`.

---

## Issues Resolved (Traceability)

| Issue ID | Description | Severity | Change | Status |
|----------|-------------|----------|--------|--------|
| R10-#1 | AnthropicAdapter `/v1/v1/messages` double URL | Blocker | Change 1 | RESOLVED |
| R10-#2 | `repos list` shows dummy_repo from pytest | Low | Change 4 | RESOLVED |
| R10-#3 | Historical threads titled "New Conversation" | Low | — | DEFERRED (historical data) |
| R10-#4 | `Permissions: suggest` unexplained in status | Low | Change 5 | RESOLVED |
| R9 follow-up | Dynamic Model Pricing gap | Medium | Change 3 | RESOLVED |
| — | Per-action cost not surfaced in SSE | — | Change 2 | NEW CAPABILITY |

**4 of 5 issues resolved. 1 intentionally deferred. 1 new capability added.**

---

## GIMO Differentiators Status

| Differentiator | Status | Evidence |
|----------------|--------|----------|
| Schema-time tool filtering | EXISTING (no change needed) | `filter_tools_by_policy()` at `agentic_loop_service.py:1266-1272` — verified unique vs all competitors |
| GICS closed-loop reliability | EXISTING (no change needed) | `record_model_outcome()` + `_filter_gics_anomalies()` + `CascadeService` — 4-piece integration unique |
| **Per-action cost streaming** | **NEW (Change 2)** | `iteration_cost` + `cumulative_cost` in `iteration_start` + `tool_call_end` SSE events — first-to-market |

---

## Residual Risks

1. **Frontend rendering**: CLI/TUI don't yet render the new `iteration_cost`/`cumulative_cost` fields. They are harmlessly ignored (SSE is additive). Rendering is a follow-up UX task.
2. **Tier defaults accuracy**: Conservative estimates may over-estimate costs for some models. Users can add exact pricing to `model_pricing.json`.
3. **R10-#3 old thread titles**: 9 historical threads still titled "New Conversation". Low impact, will age out.
4. **QualityService heuristics**: GICS reliability tracking uses keyword-based quality assessment ("i'm sorry", "i cannot"). Works but fragile. Statistical anomaly detection (CUSUM/EMA) would harden Differentiator B.

---

## Audit Trail

| Phase | Document | Date |
|-------|----------|------|
| 1. Black-box stress test | `E2E_AUDIT_LOG_20260405_R10.md` | 2026-04-05 |
| 2. Root-cause analysis | `E2E_ROOT_CAUSE_ANALYSIS_20260405_R10.md` | 2026-04-05 |
| 3. Engineering plan | `E2E_ENGINEERING_PLAN_20260405_R10.md` | 2026-04-05 |
| 4. Implementation report | `E2E_IMPLEMENTATION_REPORT_20260405_R10.md` | 2026-04-05 |

---

## AGENTS.md Completion Standard

| Criterion | Pass | Evidence |
|-----------|------|----------|
| Correct | YES | 1341 tests pass, all targeted issues resolved |
| Honest | YES | 1 issue deferred, residual risks declared, innovation claims verified by research |
| Smaller than alternatives | YES | +40 net lines for 5 changes including a first-to-market capability |
| Easy to audit | YES | Each change isolated, traceable to an issue ID or differentiator |
| Preserves system coherence | YES | SSE events are additive, no breaking changes, all surfaces benefit |
| No unnecessary complexity | YES | Zero new files, zero new dependencies, zero new abstractions |
| Proud to keep | YES | Per-action cost streaming is permanent infrastructure, not a patch |
| Strongest design in scope | YES | Research-verified against 15+ competitors |
