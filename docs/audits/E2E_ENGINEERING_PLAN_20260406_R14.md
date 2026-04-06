# E2E Engineering Plan — R14

**Date**: 2026-04-06
**Round**: R14
**Scope**: Advanced Engineering Calculator (all functions + Windows executable + web frontend)
**Auditor**: Claude Opus 4.6 (E2E Forensic Protocol)

---

## Root Cause Summary

R14 identified **15 issues** (4 BLOCKER, 3 CRITICAL, 5 GAP, 2 FRICTION, 1 INCONSISTENCY).
A singular architectural failure cascades to all surfaces: **approved runs are re-gated
by PolicyGate/RiskGate, which halts them silently**. This causes zero LLM execution,
zero cost tracking, and zero trust recording. Secondary issues are MCP bridge serialization
bugs and CLI/server SSE protocol mismatch.

**Design principle**: "Approval is terminal." Once a human approves a draft, downstream
pipeline gates become audit-only (log, don't block).

---

## Plan (7 Changes)

### Change 1: Approval-Aware Pipeline Gates [P0]
- **Solves**: #1 (run stuck), #7 (zero cost)
- **Files**: `policy_gate.py`, `risk_gate.py`, `engine_service.py`
- **What**: Skip gates when `approved_id` is in context. Update halt handler to set
  `HUMAN_APPROVAL_REQUIRED` status instead of silently returning.

### Change 2: CLI SSE Protocol Alignment [P0]
- **Solves**: #2 (CLI plan/chat silent)
- **Files**: `gimo_cli/commands/plan.py`, `tests/unit/test_gimo_cli.py`
- **What**: Rewrite SSE parser to match server protocol (`result`/`error`/`stage` events).

### Change 3: MCP Bridge Serialization Fixes [P1]
- **Solves**: #5 (chat 422), #6 (spawn workspace_path)
- **Files**: `native_tools.py`
- **What**: Fix `params=` to `json=` for chat. Add `workspace_path` param to spawn.

### Change 4: MCP Draft Creation — Fire-and-Return [P1]
- **Solves**: #4 (MCP timeouts), #8 (team_config can't find drafts)
- **Files**: `native_tools.py`
- **What**: Replace blocking LLM calls with instant HTTP draft creation via `/ops/drafts`.

### Change 5: Trust Profile Unification [P2]
- **Solves**: #9 (trust inconsistency across 3 surfaces)
- **Files**: `governance_tools.py`
- **What**: Use `SagpGateway._get_trust_score()` as single source of truth.

### Change 6: GICS Daemon Pre-Check [P2]
- **Solves**: #3 (GICS not initialized)
- **Files**: `gics_service.py`
- **What**: `shutil.which('node')` pre-check, pass resolved node path, capture stderr on failure.

### Change 7: Missing API Routes [P3]
- **Solves**: #10 (connectors/health), #11 (child-runs list), #12 (threads workspace_root)
- **Files**: `config_router.py`, `child_run_router.py`, `conversation_router.py`
- **What**: Add `GET /connectors/health` aggregate, `GET /child-runs` listing, make `workspace_root` optional.

---

## Execution Order

1. Change 1 (P0) — unblocks all run execution
2. Change 2 (P0) — unblocks CLI plan/chat
3. Change 3 (P1) — unblocks MCP chat + spawn
4. Change 4 (P1) — unblocks MCP draft creation
5. Change 5 (P2) — trust consistency
6. Change 6 (P2) — GICS diagnostics
7. Change 7 (P3) — API completeness

## 8-Criterion Compliance

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Aligned | YES | All changes follow SYSTEM.md (SAGP), AGENTS.md (minimal diffs), CLIENT_SURFACES.md (parity) |
| Potent | YES | Change 1 creates permanent leverage: approval-aware gates solve execution block for all future runs |
| Lightweight | YES | ~120 lines of changes across ~10 files. Zero new files. Zero new dependencies |
| Multi-solving | YES | Change 1 solves #1+#7. Change 3 solves #5+#6. Change 4 solves #4+#8 |
| Innovative | YES | "Approval is terminal" with audit logging |
| Disruptive | YES | Provider-agnostic governance with approval-aware gates |
| Safe | YES | Only approved runs skip gates. Unapproved actions get full evaluation |
| Elegant | YES | One concept: "approval is terminal". Applied consistently across pipeline |
