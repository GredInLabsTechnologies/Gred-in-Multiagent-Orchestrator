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
- **Consumption**: Exposed securely over `/mcp`.

### 5. ChatGPT Apps
- **Role**: Official facade for ChatGPT consumers.
- **Consumption**: A hardened, purpose-built facade mounted at `/mcp/app`.
- **Note**: It is not meant to replace CLI or Web, but serves as another first-class citizen client.

---

## Status and Lifecycle Designations

- **[CANONICAL]**: Fully supported components operating under the centralized GIMO Core authority.
- **[LEGACY/TRANSITIONAL]**: Systems slated for removal or refactoring as part of the Multiconsumer transition (e.g., executing worktrees directly on source repos, generic MCP entry for Apps, path-based repo selections). These must not be extended further.
