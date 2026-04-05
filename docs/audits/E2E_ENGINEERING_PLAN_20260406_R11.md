# GIMO Forensic Audit — Phase 3: Engineering Plan (Round 11)

**Date**: 2026-04-06
**Auditor**: Claude Opus 4.6
**Input**: `E2E_ROOT_CAUSE_ANALYSIS_20260406_R11.md`
**Design refs**: SYSTEM.md, AGENTS.md, CLIENT_SURFACES.md

---

## Diagnosis

Two architectural cables are broken:
1. **The MCP bridge's manifest is stale** — hand-maintained `manifest.py` drifted from live routes during P1 migration. A generator script (`scripts/generate_manifest.py`) exists but was never re-run.
2. **Governance tools create fresh service instances** instead of using the shared singletons wired at startup, producing synthetic data (trust 0.85 fallback) and import errors.

One execution path is broken:
3. **`CliAccountAdapter.generate()` on Windows** lacks `shell=True` for npm `.cmd` shims, blocking all Codex/OpenAI execution.

One governance invariant is violated:
4. **`native_tools.py:gimo_approve_draft`** bypasses all governance gates (risk, intent, auto_run) by calling OpsService directly instead of going through the HTTP endpoint.

---

## Changes (8 total)

### Change 1: Regenerate MCP Manifest from OpenAPI
**Solves**: R11-#1, R11-#3, R11-#5

### Change 2: Fix sagp_gateway — imports, attribute, shared GICS
**Solves**: R11-#2, R11-#6, R11-#9

### Change 3: Fix governance_tools — shared GICS for trust
**Solves**: R11-#9 (second location)

### Change 4: Windows `shell=True` for CliAccountAdapter
**Solves**: R11-#13

### Change 5: Unify native approve via proxy_to_api
**Solves**: R11-#4

### Change 6: Structured error envelope for governance tools
**Solves**: R11-#12

### Change 7: Expand agent_id validation
**Solves**: R11-#11

### Change 8: Add CLI `graph` and `capabilities` commands
**Solves**: R11-#7

---

## Deferred

- **R11-#8** (`/ops/trust/query` 404 on GET): POST-only by design.
- **R11-#10** (`/auth/check` false for Bearer): Cookie-only by design.

## 8-Criterion Compliance

| Criterion | Pass |
|-----------|------|
| Aligned | YES |
| Potent | YES |
| Lightweight | YES |
| Multi-solving | YES |
| Innovative | YES |
| Disruptive | YES |
| Safe | YES |
| Elegant | YES |

Full plan details in `C:\Users\shilo\.claude\plans\idempotent-gliding-boot.md`.
