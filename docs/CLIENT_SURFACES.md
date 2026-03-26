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

### 4. MCPs (Model Context Protocol)
- **Role**: General-purpose bridge for IDEs and external agents.
- **Consumption**: Exposed securely over `/mcp` (**[LEGACY/GENERAL BRIDGE]**).
- **Note**: Not intended for first-class App integration.

### 5. ChatGPT Apps [Phase 7B Verified]
- **Role**: Official façade for ChatGPT consumers.
- **Consumption**: A hardened, purpose-built façade mounted at `/mcp/app` (**[OFFICIAL FAÇADE]**).
- **Parity**: Shares the same backend authority as CLI and Web via Canonical Contracts.
- **Note**: This is the primary entry point for modern external agents.

---

## Parity Closure (Cross-Surface Invariants)

| Feature | Web Authority | CLI/TUI Authority | App Façade Authority |
|---|---|---|---|
| Status | `/ops/operator/status` | `/ops/operator/status` | `/ops/operator/status` |
| Notices | `/ops/notices` | `/ops/notices` | `/ops/notices` |
| Approval | `/ops/drafts/{id}/approve` | `/ops/drafts/{id}/approve` | `/ops/drafts/{id}/approve` |
| Execution | `RunWorker` (Backend) | `RunWorker` (Backend) | `RunWorker` (Backend) |

All surfaces are strictly **thin clients** consuming the same **Canonical Backend**. No surface-specific domain logic is permitted.

---

## Status and Lifecycle Designations

- **[CANONICAL]**: Fully supported components operating under the centralized GIMO Core authority.
- **[LEGACY/TRANSITIONAL]**: Systems slated for removal or refactoring as part of the Multiconsumer transition (e.g., executing worktrees directly on source repos, generic MCP entry for Apps, path-based repo selections). These must not be extended further.
