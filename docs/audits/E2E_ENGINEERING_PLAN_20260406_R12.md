# E2E Engineering Plan — R12

**Date**: 2026-04-06
**Round**: 12
**Phase**: 3 (SOTA Research + Engineering Plan)
**Status**: IMPLEMENTED

---

## Context

R12 audit found **13 issues** (5 BLOCKER, 2 CRITICAL, 3 GAP, 2 INCONSISTENCY, 1 FRICTION).
Root cause analysis identified **5 systemic patterns**: manifest drift, existence-not-validity checks, display-only workarounds, silent failure gates, stale bytecache.

## Solution: 8 Changes

### Change 1: Replace MCP Bridge with FastMCP OpenAPIProvider
- **Solves**: R12-#1, #2, #4, #8 (manifest drift, broken names, wrong paths, missing params)
- **Files modified**: `mcp_bridge/server.py`, `mcp_bridge/bridge.py`
- **Approach**: FastMCP's `OpenAPIProvider` derives MCP tools at runtime from the FastAPI `.openapi()` spec. Zero drift by construction.
- **Net effect**: ~500 lines of manifest generation replaced by ~25 lines of provider config

### Change 2: Fix `should_run` gate
- **Solves**: R12-#5 (no surface can execute a run)
- **File**: `routers/ops/run_router.py`
- **Fix**: When `auto_run=True` is explicitly passed, trust the caller — don't require `AUTO_RUN_ELIGIBLE`. Also replaced silent `except Exception: pass` with logged error.

### Change 3: `PYTHONDONTWRITEBYTECODE=1` in launcher
- **Solves**: R12-#3, #12 (stale bytecache, R11 fixes not persisting)
- **File**: `gimo.cmd`
- **Fix**: Set env var before all Python invocations + clean existing `__pycache__` on startup.

### Change 4: Deeper CLI connector health check
- **Solves**: R12-#6, #13 (provider test false positive, validate endpoint unused)
- **File**: `services/providers/connector_service.py`
- **Fix**: CLI connectors now verify the binary actually runs (`--version`), not just that it exists on PATH.

### Change 5: `gimo init` registers repo
- **Solves**: R12-#10 (repos empty via MCP/HTTP)
- **Files**: `gimo_cli/commands/core.py`, `mcp_bridge/bridge.py`
- **Fix**: After creating `.gimo/` dirs, `init` calls `POST /ops/repos/register`. Bridge injects `X-Gimo-Workspace` header.

### Change 6: GICS health liveness probe
- **Solves**: R12-#7 (GICS health false positive)
- **Files**: `services/gics_service.py`, `services/sagp_gateway.py`
- **Fix**: Added `_last_alive` flag updated by health loop's actual ping. SAGP reads this instead of checking `_supervisor is not None`.

### Change 7: Trust profile `effective_score`
- **Solves**: R12-#11 (trust profile vs snapshot inconsistency)
- **File**: `routers/ops/trust_router.py`
- **Fix**: `/ops/trust/query` response includes `effective_score` (0.85 default for fresh installs) matching what SAGP actually uses.

### Change 8: `--yes`/`-y` alias for `gimo run`
- **Solves**: R12-#9 (gimo run needs --yes flag)
- **File**: `gimo_cli/commands/run.py`
- **Fix**: Added `--yes`/`-y` option that skips the confirmation prompt.

## Issue-to-Change Matrix

| Issue | Severity | Change | Description |
|-------|----------|--------|-------------|
| #1 | BLOCKER | 1 | Manifest drift |
| #2 | BLOCKER | 1 | Broken tool names |
| #3 | BLOCKER | 3 | Stale bytecache |
| #4 | CRITICAL | 1 | Wrong paths in manifest |
| #5 | BLOCKER | 2 | should_run blocks all execution |
| #6 | CRITICAL | 4 | Provider test false positive |
| #7 | GAP | 6 | GICS health false positive |
| #8 | BLOCKER | 1 | Missing params in manifest |
| #9 | FRICTION | 8 | No --yes flag for gimo run |
| #10 | GAP | 5 | Repos empty via MCP/HTTP |
| #11 | INCONSISTENCY | 7 | Trust profile vs snapshot |
| #12 | INCONSISTENCY | 3 | R11 fixes broken by pycache |
| #13 | GAP | 4 | Validate endpoint unused |

## Metrics

- **Issues resolved**: 13/13
- **Systemic patterns killed**: 5/5
- **Files modified**: 9
- **Files deprecated**: 2 (manifest.py, registrar.py — no longer imported by server.py)
- **Net lines**: ~-400

## SOTA Findings

1. **FastMCP OpenAPIProvider** (already installed, unused) — runtime tool derivation with zero drift
2. **No competitor** refuses execution after explicit human approval — GIMO's `should_run` gate was an anti-pattern
3. **`PYTHONDONTWRITEBYTECODE`** is standard practice for dev servers — eliminates entire class of cache bugs
