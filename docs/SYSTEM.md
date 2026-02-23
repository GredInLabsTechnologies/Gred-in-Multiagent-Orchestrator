# GIMO — Gred in Multiagent Orchestrator (System & Operations)

**Status**: AUTHORITATIVE (Source of Truth)
**Last verified**: 2026-02-10

This document defines **what GIMO is today** (not a roadmap). If something conflicts with this doc, this doc wins.

---

## 0) Product definition

**GIMO (Gred in Multiagent Orchestrator)** is a token-protected FastAPI service + UI that provides a safe, auditable, and human-in-the-loop control plane for running LLM-driven operational workflows.

Core principles:

- **Agnostic operator**: can be driven by the web UI, scripts/CLI, ChatGPT Actions, MCP clients, etc.
- **Auditability by design**: every mutation is authenticated and audit-logged; executions have durable state on disk.
- **Security-first**: strict role separation, rate limiting, panic mode, redaction, allowlists.
- **Human-in-the-loop**: generation ≠ execution; approval gates exist and are mandatory for execution paths.
- **No fear UX**: the UI should show status, logs, and allow safe intervention (approve/reject/cancel).

---

## 1) Runtime architecture (as implemented)

High level:

```
┌─────────────────────────────────────────────────────────┐
│ FastAPI (tools/gimo_server/main.py)               │
│  - /status, /ui/*, /tree /file /search /diff            │
│  - /ops/* (OPS runtime: drafts/approve/runs/config)     │
│ middlewares: panic│cors│correlation│rate_limit│auth     │
├─────────────────────────────────────────────────────────┤
│ Services                                                │
│  - OpsService (file-backed state)                       │
│  - ProviderService (LLM adapters)                       │
│  - RunWorker (executes pending runs)                    │
├─────────────────────────────────────────────────────────┤
│ Storage (.orch_data/ops)                                │
│  - plan.json, config.json, provider.json                │
│  - drafts/*.json, approved/*.json, runs/*.json          │
└─────────────────────────────────────────────────────────┘
```

Durability model:

- All OPS/GIMO operational objects are persisted as JSON files under `.orch_data/ops/`.
- State changes use a file lock for critical mutations (e.g. approve/update run state).
- Cleanup loops run in the background to prevent unbounded growth.

---

## 2) Security model (roles, tokens, and guardrails)

### 2.1 Tokens and roles

Authentication is **Bearer token**.

Roles are derived from which token is used:

- `actions` — lowest privilege (read-only for actions-safe endpoints)
- `operator` — can approve and create/cancel runs (operational control)
- `admin` — full control, can mutate plans/provider/config and manage drafts

Role enforcement is implemented in `tools/gimo_server/ops_routes.py` using `_require_role()`.

### 2.2 Token safety

Raw tokens must never be persisted in operational artifacts.

- `approved_by` uses a safe label: `role:<sha256(token)[:12]>`.

### 2.3 Panic mode and rate limiting

- Invalid tokens are tracked and can trigger **panic mode** (lockdown) on threshold.
- Rate limiting is applied to mitigate brute-force and abuse.

### 2.4 Non-negotiable guardrails

These are invariants of the system:

1) **Drafts are never executed directly.** Only `approved` artifacts may create `runs`.
2) **Runs cannot be created from draft IDs.** Attempting to do so is blocked.
3) **Approval is a security boundary**, not a UX affordance.
4) Secrets (provider API keys) are not exposed via public endpoints.

---

## 3) OPS/GIMO operational objects (storage)

Directory: `.orch_data/ops/`

- `drafts/d_*.json` — drafts (status: `draft|rejected|approved|error`)
- `approved/a_*.json` — approved artifacts (the only allowed run input)
- `runs/r_*.json` — run execution state + log
- `config.json` — OPS config (see below)
- `plan.json` — active plan payload (optional)
- `provider.json` — provider configuration (admin-only access; redacted in public GET)

---

## 4) API contract (implemented today)

### 4.1 Key endpoints

All endpoints require `Authorization: Bearer <TOKEN>` unless explicitly public.

**Plan**

- `GET  /ops/plan` (actions+) — read plan
- `PUT  /ops/plan` (admin) — set plan

**Drafts**

- `GET  /ops/drafts` (actions+) — list
- `POST /ops/drafts` (admin) — create
- `GET  /ops/drafts/{draft_id}` (actions+) — read
- `PUT  /ops/drafts/{draft_id}` (admin) — edit
- `POST /ops/drafts/{draft_id}/reject` (admin) — reject

**Approval gate**

- `POST /ops/drafts/{draft_id}/approve` (operator+) — approve a draft
  - optional `auto_run=true|false` query param
  - default: derived from `OpsConfig.default_auto_run`

**Approved**

- `GET /ops/approved` (actions+) — list
- `GET /ops/approved/{approved_id}` (actions+) — read

**Runs**

- `POST /ops/runs` (operator+) — create run from `approved_id`
- `GET  /ops/runs` (actions+) — list
- `GET  /ops/runs/{run_id}` (actions+) — read
- `POST /ops/runs/{run_id}/cancel` (operator+) — cancel (second cancel returns 409)

**Provider + generation**

- `GET /ops/provider` (admin) — provider config (redacted)
- `PUT /ops/provider` (admin) — update provider config
- `POST /ops/generate` (admin or operator if allowed) — generate a draft from provider

**Config**

- `GET /ops/config` (operator+) — read
- `PUT /ops/config` (admin) — update

### 4.2 Filtered OpenAPI for integrations

- `GET /ops/openapi.json` returns a **filtered** OpenAPI spec suitable for external tools.

---

## 5) Configuration (OpsConfig)

Persisted in `.orch_data/ops/config.json`.

Fields:

- `default_auto_run: bool` — default behavior for approve if `auto_run` is not passed
- `draft_cleanup_ttl_days: int` — cleanup TTL for drafts in `rejected|error`
- `max_concurrent_runs: int` — run worker concurrency guard
- `operator_can_generate: bool` — whether operator may call `/ops/generate`

---

## 6) Background loops and cleanup

Background tasks started from FastAPI lifespan:

- snapshot cleanup loop (existing)
- OPS cleanup loop:
  - `OpsService.cleanup_old_runs()` — removes old run files based on TTL
  - `OpsService.cleanup_old_drafts()` — removes `rejected|error` drafts older than `draft_cleanup_ttl_days`

---

## 7) UI contract (current)

The UI is served from `tools/orchestrator_ui/dist/` when built.

Implemented ops UI entrypoint:

- `tools/orchestrator_ui/src/islands/system/OpsIsland.tsx`

The UI is expected to:

- visualize drafts/approved/runs
- allow safe operational actions (approve/reject/edit/cancel)
- never circumvent approval gates

---

## 8) Multi-agent direction (frozen specification boundary)

GIMO is being used as the operational substrate for multi-agent execution.

**Important**: This doc does not describe a roadmap. It defines the boundary conditions any multi-agent executor must respect:

- All actions must be represented as durable, auditable artifacts.
- Execution must be pausable/cancellable and must support human approval gates.
- Operators (Antigravity + VS Code + Actions) are clients; execution authority remains server-side.
- Any future “step graph” system must preserve the guardrails in §2.4.

---

## Appendix A — Operational commands

Run dev server:

```cmd
python -m uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325
```

Run quality gates:

```cmd
python scripts\\ci\\quality_gates.py
```

## Appendix B — Component Architecture

### Capas
0. **GICS Daemon (Node.js)** - Storage distribuido propietario
1. **Services (Python)** - 30+ servicios, GraphEngine es el nucleo
2. **REST API (FastAPI)** - ~95 endpoints en `/ops/*`, `/ui/*`, `/auth/*`
3. **MCP Server (FastMCP)** - 14 tools para IDEs via stdio/SSE
4. **Frontend (React+Vite)** - Dashboard en puerto 5173

### Sistema de Storage
- **Actual**: SQLite predominante en varios storages (`cost_storage`, `trust_storage`, `eval_storage`, etc.).
- **GICS**: Daemon Node.js para almacenamiento. Tiene conectividad via socket y tiers de storage (hot/warm/cold).
- **Pendiente**: Migrar todo el almacenamiento de SQLite a GICS para tener a GICS como unico origen de datos.

### Flujo Principal Detallado
1. **Draft**: Se recibe un prompt o intenct y se genera un borrador (`ExecutionPlanDraft`).
2. **Approved**: El usuario (o regla automatica) aprueba el plan.
3. **Run**: El draft se convierte en un plan de ejecucion en el `GraphEngine`.
4. **RunWorker**: El worker asincrono toma los nodos del grafo y delega el trabajo real.
5. **ProviderService / LLM**: Se solicita inferencia al proveedor (ej. Qwen via Ollama, Groq, Codex).

IDE → MCP tool → OpsService → RunWorker → ProviderService → LLM

## Appendix C — LLM Adapters & Connectivity

Desde esta fase, la **fuente unica de verdad** para providers es OPS (`/ops/provider`, `/ops/connectors`, etc.).
Taxonomia canonica `provider_type`:
- `ollama_local`, `openai`, `codex`, `groq`, `openrouter`, `custom_openai_compatible`

### Matriz de Adaptadores (Compatibilidad)
- **OpenAICompatibleAdapter**: Ollama, LM Studio, vLLM, DeepSeek, OpenAI (HTTP/JSON, Streaming, Tools limitados)
- **ClaudeCodeAdapter**: Claude Code CLI (Stdio/MCP, Streaming, Tools)
- **GeminiAdapter**: Gemini CLI (Stdio/JSON, Streaming, Tools)
- **CodexAdapter**: Custom Codex CLI (Stdio/JSON, Streaming, Tools)
- **GenericCLIAdapter**: Any CLI (Stdio/Text, Streaming)

### Capability Matrix
Cada provider declara `auth_modes_supported`, `can_install`, `install_method`, `supports_account_mode`, `supports_recommended_models`, `requires_remote_api`.

## Appendix D — Sub-Delegation Protocol
El protocolo define como un Primary Agent (e.g., Claude/GPT-4) delega sub-tareas a Sub-Agents (e.g., Ollama/CodeLlama).
1. **Delegation Request**: POST `/api/agent/{agentId}/delegate`
2. **Approval & Instantiation**: Orchestrator verifica TrustLevel. Instancia el Sub-Agent y lo anade al Graph.
3. **Execution & Reporting**: Streaming output al contexto del Primary Agent.
4. **Completion**: Retorna artefacto final como "tool result". Success or Failure.

## Appendix E - Real State Map Priorities
Prioridades basadas en el mapa de estado real de GIMO (P0/P1/P2/P3):
- **P0**: Fix `gics_service.py` (import errors), fix `gimo_run_task()` (draft vacio), fix `custom_plan_router.py` (asyncio).
- **P1**: Exponer ~80 endpoints faltantes via MCP bridge. Arreglar hooks frontend vacios y path mismatches.
- **P2**: Migrar queries de agregacion (cost/trust/evals) de SQLite a GICS.
- **P3**: Eliminar dependencias de servicios legacy. Actualizar `setup_mcp.py` para todos los IDEs.
