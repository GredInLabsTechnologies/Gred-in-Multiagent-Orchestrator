# GIMO Client Surfaces Topology

This document formally defines the physical and conceptual boundaries of the GIMO ecosystem.

## GIMO Core (The Authoritative Source of Truth)
GIMO is a **multi-surface sovereign platform**.
All domain logic, execution authority, and state persistence lives strictly in the backend services and Canonical Contracts.
- Canonical state lives in: `.orch_data/ops/` and `GICS`.
- Execution gates live in: `EngineService`, `RunWorker`, `MergeGateService`.
- No client (UI, CLI, App) shall compute its own state, re-implement operations, or bypass the server.

---

## Official Surfaces

### 1. Frontend Web
- **Role**: Rich graphical dashboard.
- **Consumption**: Next.js app consuming `/ui/*` and `/ops/*` REST APIs.

### 2. Terminal Client (CLI & TUI)
- **Role**: Interactive command-line and Text User Interface for operators.
- **Consumption**: Consumes standard backend endpoints such as `/ops/operator/status` and `/ops/threads/*` rather than duplicating logic.
- **Note**: CLI and TUI are two modes of the same official terminal client.

### 3. API
- **Role**: Machine-to-machine integration and foundation for all clients.
- **Consumption**: `/ops/*` (Canonical actions-safe REST routes).

### 4. MCPs (Model Context Protocol) — SAGP Canonical Bridge
- **Role**: **Canonical governance bridge** for IDEs, Claude App/Code, and external agents.
- **Consumption**: MCP server via stdio (for Claude Desktop, VS Code, Cursor) or SSE (for web clients). Registered as `gimo` in surface configs.
- **Protocol**: SAGP (Surface-Agnostic Governance Protocol). All surfaces traverse the same `SagpGateway` before any action.
- **Governance tools**: 8 first-class MCP tools (`gimo_evaluate_action`, `gimo_estimate_cost`, `gimo_get_trust_profile`, `gimo_get_governance_snapshot`, `gimo_get_gics_insight`, `gimo_verify_proof_chain`, `gimo_get_execution_policy`, `gimo_get_budget_status`).
- **Resources**: `governance://snapshot`, `governance://policies`, `gics://health`.
- **Dashboard**: MCP App dashboard via `gimo_dashboard()` tool and `ui://gimo-dashboard` resource.
- **Surface detection**: Auto-inferred from User-Agent, headers (`X-Gimo-Surface`), or transport type.
- **Agent Teams**: `gimo_generate_team_config()` generates Claude Code Agent Teams configs from GIMO plans.
- **Auto-discovery**: `gimo surface connect <surface>` auto-discovers Python, repo root, and config paths per OS.
- **Status**: **[CANONICAL SAGP BRIDGE]** — primary governance entry point for all MCP-capable surfaces.
- **Note**: See [SAGP Architecture](architecture/SAGP.md) for full protocol specification.

### 5. ChatGPT Apps [Phase 7B Verified]
- **Role**: Official façade for ChatGPT consumers.
- **Consumption**: A hardened, purpose-built façade mounted at `/mcp/app` (**[OFFICIAL FAÇADE]**).
- **Transport note**: The official façade serves both `/mcp/app/sse` and `/mcp/app/mcp`.
- **Parity**: Shares the same backend authority as CLI and Web via Canonical Contracts.
- **Note**: This is the primary entry point for modern external agents.
- **Authority note**: ChatGPT Apps is not a sovereign operator surface. From the user perspective, the conversational ChatGPT-side agent acts as the outer orchestrator, so this surface must remain more constrained than first-party GIMO surfaces.
- **Profile note**: The default App MCP profile is `safe`, intentionally narrower for ChatGPT Developer Mode and no-auth personal drafts; `extended` is opt-in.
- **Agent note**: ChatGPT Apps may request or trigger worker execution through GIMO, but it must not expose orchestrator selection or create a second orchestrator authority for the same session.
- **Model-routing note**: ChatGPT Apps must not choose the session worker model. Provider/model routing remains backend-authored.
- **Repo access note**: ChatGPT Apps never read the registered source repository directly. App sessions bind an opaque repo handle to an App-managed snapshot/clone, and App reconnaissance runs only against that bound snapshot.
- **Lifecycle note**: App review resources operate on the App-bound snapshot/workspace. Manual merge remains a sovereign backend action and resolves the authoritative source repo server-side when another first-party surface closes the run.

---

### 6. Agent SDK
- **Role**: Programmatic integration for Claude Agent SDK and custom agent runtimes.
- **Consumption**: GIMO MCP server loaded as tool provider. Governance enforced via SAGP.
- **Capabilities**: streaming, sub_agents, hooks.
- **Status**: **[CANONICAL]**.

### 7. MCP Generic
- **Role**: Fallback for any unknown MCP client.
- **Consumption**: Minimum capability set. All governance tools available.
- **Capabilities**: (minimum — no streaming, no HITL, no MCP Apps).
- **Status**: **[CANONICAL]**.

---

## SAGP Governance Invariant

All surfaces — without exception — traverse the **SagpGateway** before any action. The gateway evaluates:

1. **Execution policy** — is the tool allowed under the active policy?
2. **Risk band** — LOW/MEDIUM/HIGH classification
3. **Trust score** — empirical reliability (0.0–1.0) with circuit breakers
4. **Cost estimation** — estimated USD cost of the action
5. **Budget check** — is there budget remaining?
6. **HITL requirement** — does this action need human confirmation?

The result is a **GovernanceVerdict** (frozen, immutable). No surface may bypass this evaluation.

See [SAGP Architecture](architecture/SAGP.md) for the full protocol specification.

---

## Parity Closure (Cross-Surface Invariants)

| Feature | Web | CLI/TUI | MCP (Claude/VS Code/Cursor) | App Façade | Agent SDK |
|---|---|---|---|---|---|
| Status | `/ops/operator/status` | `/ops/operator/status` | `gimo_get_status` | `/ops/operator/status` | `gimo_get_status` |
| Governance | `/ops/governance/snapshot` | `gimo status --json` | `gimo_get_governance_snapshot` | `/ops/governance/snapshot` | `gimo_get_governance_snapshot` |
| Pre-action check | (backend-enforced) | (backend-enforced) | `gimo_evaluate_action` | (backend-enforced) | `gimo_evaluate_action` |
| Notices | `alerts` in `/ops/operator/status` | `alerts` in `/ops/operator/status` | `alerts` in `gimo_get_status` | `alerts` in `/ops/operator/status` | `alerts` in `gimo_get_status` |
| Approval | `/ops/drafts/{id}/approve` | `/ops/drafts/{id}/approve` | `gimo_approve_draft` | `/ops/drafts/{id}/approve` | `gimo_approve_draft` |
| Execution | `RunWorker` (Backend) | `RunWorker` (Backend) | `RunWorker` (Backend) | `RunWorker` (Backend) | `RunWorker` (Backend) |
| Trust | `/ops/trust/*` | `/ops/trust/*` | `gimo_get_trust_profile` | `/ops/trust/*` | `gimo_get_trust_profile` |
| Cost | `/ops/mastery/*` | `/ops/mastery/*` | `gimo_estimate_cost` | `/ops/mastery/*` | `gimo_estimate_cost` |

All surfaces are strictly **thin clients** consuming the same **Canonical Backend** through the same **SAGP governance layer**. No surface-specific domain logic is permitted.

Additional invariant:

- there is exactly one orchestrator authority per active session
- workers may be multiple
- ChatGPT Apps must not introduce a second independent orchestrator authority inside the same session

---

## Surface Auto-Discovery

GIMO provides automatic surface configuration via the CLI:

```bash
gimo surface connect claude_desktop   # Auto-configure Claude Desktop
gimo surface connect vscode           # Auto-configure VS Code
gimo surface connect all              # Connect all detected surfaces
gimo surface list                     # Show all surfaces and status
gimo surface config                   # Print MCP config for manual setup
```

The system auto-discovers:
- **Repo root**: `ORCH_REPO_ROOT` env → walk up from CLI location → CWD
- **Python**: `.venv/Scripts/python` → `venv/` → `env/` → `sys.executable`
- **Config paths**: Per-OS paths for each surface (Windows/Darwin/Linux)

Uses `PYTHONPATH` (not `cwd`) for portability — Claude Desktop does not support the `cwd` field.

---

## Status and Lifecycle Designations

- **[CANONICAL]**: Fully supported components operating under the centralized GIMO Core authority.
- **[CANONICAL SAGP BRIDGE]**: MCP surfaces operating under SAGP governance protocol. This is the primary integration point for all IDE and agent surfaces.
- **[LEGACY/TRANSITIONAL]**: Systems slated for removal or refactoring as part of the Multiconsumer transition (e.g., executing worktrees directly on source repos, generic MCP entry for Apps, path-based repo selections). These must not be extended further.
