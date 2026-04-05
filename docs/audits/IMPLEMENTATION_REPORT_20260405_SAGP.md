# GIMO Implementation Report — SAGP: Surface-Agnostic Governance Protocol

**Date**: 2026-04-05
**Agent**: Claude Opus 4.6
**Type**: **Architecture implementation** (not a forensic audit)
**Input**: SAGP plan (`eager-plotting-nygaard.md`) — 7 phases
**Verification**: `python -m pytest -x -q` — 1377 passed, 0 failures
**Commit**: `f70c6e1` — 35 files changed, +3,680 lines

---

## Nature of This Report

This is **NOT** a forensic audit round (R1–R10). Those rounds followed a 4-phase cycle: black-box stress test → root cause analysis → SOTA research → fix implementation.

This session was a **full architectural implementation** driven by an external compliance event (Anthropic's April 2026 OAuth policy change). The scope was:

1. **Compliance fix** — block the now-illegal `CliAccountAdapter` for Claude
2. **Architectural transformation** — build SAGP, a governance protocol that makes GIMO surface-agnostic
3. **MCP parity** — elevate MCP to the same authority level as CLI and REST, not a second-class bridge
4. **Documentation** — extensive architecture docs for the new protocol

Going forward, **CLI and MCP are tested at the same level**. SAGP ensures all surfaces — Claude App, VS Code, Cursor, CLI, TUI, Web — traverse identical governance and share identical authority.

---

## Session Summary

This session implemented the complete SAGP (Surface-Agnostic Governance Protocol) across 7 phases, transforming GIMO from an "LLM consumer" to a **"governance authority"** that any surface consumes via MCP.

**Trigger**: Anthropic's April 2026 policy change blocking third-party harnesses from using Claude subscription OAuth tokens. GIMO's `CliAccountAdapter` (`claude -p` subprocess) violated this policy.

**Solution**: Invert the control flow. GIMO becomes an MCP server that Claude App/Code calls (first-party, allowed) instead of GIMO calling Claude as a subprocess (third-party, blocked).

---

## Phase 0: Compliance Fix + Data Updates

### 0A. Block CliAccountAdapter for Claude

| File | Lines | Description |
|------|-------|-------------|
| `services/providers/adapter_registry.py` | +15 -2 | For `claude` + `account` auth: check `ANTHROPIC_API_KEY` first (→ AnthropicAdapter), else raise `ValueError` with migration instructions. Codex unaffected. |
| `services/providers/service_impl.py` | +71 -20 | New priority: `ANTHROPIC_API_KEY` env → codex CLI → ollama local → empty. Claude CLI NOT auto-provisioned. SAGP warning logged. |
| `services/providers/topology_service.py` | +9 -7 | Removed `claude-account` from `inject_cli_account_providers()` specs. Without this, `_normalize_config()` would re-inject claude-account on every config load. |

**Why not just add API key support?** That fixes compliance but misses the strategic opportunity. SAGP makes GIMO more valuable — governance authority vs. just another LLM wrapper.

### 0B-0C. Data Updates

| File | Lines | Description |
|------|-------|-------------|
| `data/model_pricing.json` | +10 -10 | Context windows 200K → 1M for all Claude 4.x models (opus-4, opus-4-5, opus-4-6, sonnet-4-5, sonnet-4-6). |
| `services/economy/cost_service.py` | +6 | Model 4.6 alias mappings: `opus-4.5`, `opus-4.6`, `sonnet-4.6` and their `claude-` prefixed forms. |

---

## Phase 1: SAGP Core — The Governance Gateway

### 1A. Surface Identity Model

| File | Lines | Description |
|------|-------|-------------|
| `models/surface.py` | +78 (new) | `SurfaceIdentity` frozen dataclass with `SurfaceType` literal (9 types), capabilities frozenset, session_id, created_at. Properties: `supports_streaming`, `supports_mcp_apps`, `supports_hitl`, `supports_agent_teams`. |

### 1B. Governance Verdict Model

| File | Lines | Description |
|------|-------|-------------|
| `models/governance.py` | +62 (new) | `GovernanceVerdict`: allowed, policy_name, risk_band, trust_score, estimated_cost_usd, requires_approval, circuit_breaker_state, proof_id, reasoning, constraints. `GovernanceSnapshot`: aggregate governance state. |

### 1C. SAGP Gateway Service

| File | Lines | Description |
|------|-------|-------------|
| `services/sagp_gateway.py` | +275 (new) | Central governance entry point. `evaluate_action()` orchestrates: ExecutionPolicyService → risk classification → TrustEngine → CostService → budget check → HITL determination → proof generation → GovernanceVerdict. `get_snapshot()`, `get_gics_insight()`, `verify_proof_chain()`. |

**Critical fixes during implementation**:
- TrustStorage import path: `..services.trust_storage` → `..services.storage.trust_storage`
- GicsService: class-level calls → instance-based with `count_prefix("")`
- `scan()` called with unsupported `limit` kwarg → slice after call
- BudgetForecastService too heavy for pre-action → lightweight `CostService.load_pricing()` check
- Fresh installs: trust score 0.0 → conservative 0.85 default
- GICS count None → `or 0` fallback
- Tuple literal: `tuple(f"fs:{x}",)` iterates string → `(f"fs:{x}",)` correct 1-tuple

### 1D. Contract Integration

| File | Lines | Description |
|------|-------|-------------|
| `models/contract.py` | +8 | Added `surface: SurfaceIdentity | None = None` field (backward-compatible). TYPE_CHECKING guard for import. |
| `services/contract_factory.py` | +14 | Surface detection from `X-Gimo-Surface` header in `build()` method. |
| `models/__init__.py` | +4 | Exports: SurfaceIdentity, SurfaceType, GovernanceVerdict, GovernanceSnapshot. |

---

## Phase 2: MCP Supertools — Governance as First-Class

### 2A. Governance Tools

| File | Lines | Description |
|------|-------|-------------|
| `mcp_bridge/governance_tools.py` | +195 (new) | 8 MCP tools: `gimo_evaluate_action`, `gimo_estimate_cost`, `gimo_get_trust_profile`, `gimo_get_governance_snapshot`, `gimo_get_gics_insight`, `gimo_verify_proof_chain`, `gimo_get_execution_policy`, `gimo_get_budget_status`. |

### 2B. Enhanced Native Tools

| File | Lines | Description |
|------|-------|-------------|
| `mcp_bridge/native_tools.py` | +95 | Enhanced `gimo_spawn_subagent` with provider, model, execution_policy params. New tools: `gimo_generate_team_config`, `gimo_gics_model_reliability`, `gimo_gics_anomaly_report`. |

### 2C. Server Registration

| File | Lines | Description |
|------|-------|-------------|
| `mcp_bridge/server.py` | +4 | Register governance_tools and dashboard_app in `_register_native()`. |

### 2D-2E. Resources + Prompts

| File | Lines | Description |
|------|-------|-------------|
| `mcp_bridge/resources.py` | +45 | 3 governance resources: `governance://snapshot`, `governance://policies`, `gics://health`. |
| `mcp_bridge/prompts.py` | +43 | 2 governance prompts: `governance_check`, `multi_agent_plan`. |

### 2F. Manifest Expansion

| File | Lines | Description |
|------|-------|-------------|
| `mcp_bridge/manifest.py` | +185 | 33 new endpoint definitions: inference (8), app sessions (6), recon (3), threads extended (4), checkpoints (4), HITL action drafts (5), observability (2), child runs (3). |

---

## Phase 3: MCP App Dashboard

| File | Lines | Description |
|------|-------|-------------|
| `mcp_bridge/mcp_app_dashboard.py` | +65 (new) | Registers `gimo_dashboard` tool and `ui://gimo-dashboard` resource. Returns governance snapshot as text or interactive HTML. |
| `mcp_bridge/dashboard_template.html` | +380 (new) | Interactive HTML: trust heatmap, budget gauge, GICS health, policy grid, action buttons. Bidirectional MCP Apps communication via `postMessage` JSON-RPC. |

---

## Phase 4: Surface Adapter Layer

### 4A. Surface Negotiation

| File | Lines | Description |
|------|-------|-------------|
| `services/surface_negotiation_service.py` | +105 (new) | `SURFACE_CAPABILITIES` dict for 9 surface types. `negotiate()` builds SurfaceIdentity. `infer_surface()` detects from User-Agent, headers, transport. |

### 4B. Surface-Aware Response

| File | Lines | Description |
|------|-------|-------------|
| `services/surface_response_service.py` | +125 (new) | Formats GovernanceVerdict per surface: JSON (default), Rich markdown (MCP Apps), ANSI (terminal with colors). |

---

## Phase 5: Multi-Provider Agent Broker

| File | Lines | Description |
|------|-------|-------------|
| `services/agent_broker_service.py` | +130 (new) | `BrokerTaskDescriptor`, `BrokerModelBinding` dataclasses. `select_provider_for_task()` via ModelRouterService. `spawn_governed_agent()` with SAGP governance check. |
| `services/agent_teams_service.py` | +140 (new) | `generate_team_config()` converts GIMO plans → Claude Code Agent Teams configs. `generate_teammate_prompt()` creates governance-constrained system prompts. |

---

## Phase 6: Surface Auto-Discovery CLI

| File | Lines | Description |
|------|-------|-------------|
| `gimo_cli/commands/surface.py` | +345 (new) | Full auto-discovery system. `_repo_root()`: ORCH_REPO_ROOT → walk up → CWD. `_python_exe()`: .venv → venv → env → sys.executable. `_mcp_server_entry()`: PYTHONPATH-based config (not cwd — Claude Desktop doesn't support it). 4 commands: connect, disconnect, list, config. Supports claude_desktop, claude_code, vscode, cursor per OS. |
| `gimo_cli/__init__.py` | +1 | Register surface command module. |

**MCP connection debugging** (2 failures fixed):
1. **ENOENT**: Claude Desktop couldn't resolve Microsoft Store Python symlink → Use `.venv/Scripts/python.exe` (real binary)
2. **Server disconnected**: Claude Desktop ignores `cwd` field → Replace with `PYTHONPATH` env var

---

## Phase 7: Testing + Documentation

### Tests

| File | Tests | Description |
|------|-------|-------------|
| `tests/unit/test_sagp_gateway.py` | 17 | GovernanceVerdict, evaluate_action, get_snapshot, get_gics_insight, verify_proof_chain |
| `tests/unit/test_surface_negotiation.py` | 12 | negotiate, infer_surface, capabilities per surface type |
| `tests/unit/test_compliance.py` | 7 | Claude adapter blocked, Codex allowed, API key works, models importable, contract surface field |
| `tests/unit/test_provider_topology_service.py` | (modified) | claude-account NOT in injected providers, socket mock for Ollama |
| `tests/unit/test_account_mode_e2e_min.py` | (modified) | claude-account NOT injected assertion |

**Test fix notes**:
- `isinstance(adapter, CliAccountAdapter)` failed due to module identity mismatch → `type(adapter).__name__` comparison
- `ANTHROPIC_API_KEY` env leak between tests → `monkeypatch.delenv()` isolation

### Documentation

| File | Description |
|------|-------------|
| `docs/architecture/SAGP.md` | ~500 lines. Full SAGP specification: philosophy, components, tools, architecture diagram, usage guide. |
| `docs/CLIENT_SURFACES.md` | MCP → `[CANONICAL SAGP BRIDGE]`. Added Agent SDK + MCP Generic surfaces. SAGP Governance Invariant section. Expanded parity table (5 columns × 8 features). Surface Auto-Discovery section. |
| `docs/SYSTEM.md` | SAGP layer in architecture diagram. New §9 with 5 subsections. Updated service count (60+), MCP tool count (180+). Last verified → 2026-04-05. |

---

## Verification

### Test Suite
```
1377 passed, 0 failed (full suite)
```

### MCP Server
```
31 native tools registered (+ dynamic bridge tools)
11 resources
7 prompts
Governance tools return correct data
```

### Claude Desktop Integration
```
MCP server connects successfully via stdio
PYTHONPATH-based config works cross-platform
No ENOENT, no Server disconnected
```

---

## Files Summary

| Category | New | Modified | Total |
|----------|-----|----------|-------|
| Models | 2 | 2 | 4 |
| Services | 5 | 3 | 8 |
| MCP Bridge | 3 | 5 | 8 |
| CLI | 1 | 1 | 2 |
| Tests | 3 | 2 | 5 |
| Data | 0 | 1 | 1 |
| Config | 2 | 0 | 2 |
| Docs | 1 | 2 | 3 |
| **Total** | **17** | **18** | **35** |

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Breaking existing MCP clients | All changes are additive. Existing tools unchanged. New tools are opt-in. |
| CliAccountAdapter block breaks workflows | Clear error message with migration instructions. Codex unaffected. API key path works. |
| Governance overhead on hot path | SagpGateway is lightweight (no I/O on happy path except TrustStorage read). Fresh install defaults avoid expensive lookups. |
| Surface detection false positives | Conservative fallback to `mcp_generic` (minimum capabilities). |
| Dashboard in untrusted iframe | MCP Apps spec-compliant postMessage with origin validation. |
