# GIMO — Gred in Multiagent Orchestrator (System & Operations)

**Status**: AUTHORITATIVE (Source of Truth)
**Last verified**: 2026-03-04

This document defines **what GIMO is today** (not a roadmap). If something conflicts with this doc, this doc wins.

> GIMO is part of the **Gred In Labs Technologies** monorepo.
> Repo structure: `apps/web/` (GIMO Web — Next.js), `tools/gimo_server/` (backend), `tools/orchestrator_ui/` (frontend).

---

## 0) Product definition

**GIMO (Gred in Multiagent Orchestrator)** is a multi-surface sovereign platform (Web, CLI/TUI, API, MCPs, ChatGPT Apps) powered by a token-protected FastAPI service that provides a safe, auditable, and human-in-the-loop control plane for running LLM-driven operational workflows. See [CLIENT_SURFACES.md](CLIENT_SURFACES.md) for the official topology.

Core principles:

- **Agnostic operator**: can be driven by the web UI, scripts/CLI, ChatGPT Actions, MCP clients, etc.
- **Auditability by design**: every mutation is authenticated and audit-logged; executions have durable state on disk.
- **Security-first**: strict role separation, rate limiting, panic mode, redaction, allowlists.
- **Human-in-the-loop**: generation ≠ execution; approval gates exist and are mandatory for execution paths.
- **No fear UX**: the UI should show status, logs, and allow safe intervention (approve/reject/cancel).

---

## 1) Canonical terminology and authority

This section is authoritative. It exists to stop recurring ambiguity between provider, model, agent, orchestrator, and worker.

### 1.1 Provider

A **provider** is the external service or runtime that gives GIMO access to AI capability.

Examples:

- OpenAI
- Anthropic
- Google
- Ollama
- an OpenAI-compatible endpoint

A provider is **not** a model and **not** an agent.

A single provider may expose **multiple models** through its API, subscription, connector, or runtime.

Short version:

- provider = who gives access to AI service

### 1.2 Model

A **model** is the concrete LLM exposed by a provider.

A provider can expose many models. Those models may differ in:

- coding strength
- reasoning strength
- multimodal capability
- design or aesthetic capability
- latency
- cost
- context window

Short version:

- provider = who gives access
- model = which concrete LLM is being used

### 1.3 Agent

In GIMO, an **agent** is an active AI unit operating inside the system.

In practice, an agent is usually:

- a concrete model
- assigned a role
- given a goal, scope, or responsibility

This means that in casual conversation people may sometimes blur `model` and `agent`, and that is acceptable. But when precision matters:

- model = the LLM itself
- agent = that model as an active unit inside GIMO with a role and operational responsibility

Short version:

- every agent uses a model
- not every mention of a model implies an active agent instance

### 1.4 Orchestrator

The **orchestrator** is the highest non-human agent authority in GIMO.

Authority ladder:

- human
- orchestrator
- workers

An orchestrator is an agent designated to coordinate the full agentic flow under human authority.

Its responsibilities may include:

- understanding the user objective
- mapping the repository
- planning and decomposing work
- deciding which workers to use
- spawning, replacing, or stopping agents
- validating worker outputs
- requesting more context
- researching externally when allowed
- programming directly when appropriate
- deciding when a session is operationally complete

The orchestrator operates under:

- human authority
- backend or server authority
- GICS policy
- configured permission and autonomy mode

The orchestrator may operate in:

- fully audited mode
- semi-automatic mode
- fully automatic mode

depending on configuration and policy.

Important distinction:

- the orchestrator is a kind of agent
- not every agent is an orchestrator

### 1.5 Worker

A **worker** is the lowest-authority active agent tier in GIMO.

Workers are delegated executors selected by the orchestrator for specific tasks.

Typical worker responsibilities:

- implement code
- edit files
- analyze a bounded subsystem
- review or validate a bounded artifact
- perform specialized design or multimodal work

Workers do not define top-level operational authority. They execute within the scope delegated by the orchestrator.

Short version:

- orchestrator = coordinates and decides
- worker = executes delegated work

### 1.6 Single-orchestrator invariant

For a given GIMO session, thread, or active agentic execution context, there must be **exactly one orchestrator authority**.

This is a system invariant.

Allowed:

- one orchestrator
- zero or more workers

Not allowed:

- multiple orchestrators competing within the same active session
- multiple parallel orchestrator authorities for the same user thread

Future concepts such as helper, chronicler, or assistant-orchestrator are explicitly out of scope for the current release line and must not weaken the single-orchestrator invariant.

### 1.7 Surface note: ChatGPT Apps

For ChatGPT Apps, the conversational ChatGPT-side agent acts as the outer interactive orchestrator from the user's point of view.

Because ChatGPT Apps run through a third-party-controlled surface, they are more restricted than sovereign first-party surfaces such as CLI/TUI, MCP, or internal operator UIs.

Implications:

- ChatGPT Apps must remain more constrained
- ChatGPT Apps must not gain unrestricted operator powers
- ChatGPT Apps must not be treated as a sovereign repo-control surface
- ChatGPT Apps must not read registered source repositories directly; App-bound repo access must go through an App-managed snapshot or clone
- App-facing review and reconnaissance must stay inside the App-bound snapshot or derived workspace
- App-facing controls may be intentionally narrower than first-party surfaces
- ChatGPT Apps may still cause GIMO to deploy workers
- authoritative manual merge remains a backend/first-party action resolved against the canonical source repo, not a ChatGPT App repo control
- ChatGPT Apps must not choose or replace the session orchestrator authority
- ChatGPT Apps must not choose the worker model; backend topology resolves provider/model role bindings authoritatively

### 1.8 Practical selection logic

The orchestrator should select workers according to task fitness, not by treating all providers or models as equivalent.

Examples:

- choose a strong coding model for heavy implementation work
- choose a strong multimodal or design-capable model for visual work
- choose a cheaper or lighter model for narrow bounded tasks when sufficient

This means the following are related but distinct:

- provider choice
- model choice
- agent role
- orchestrator authority

They must not be collapsed into a single fuzzy concept.

### 1.9 Technical debt still pending

The following items remain as explicit technical debt after the current authority and topology hardening work.

1. **Legacy provider topology fields still exist for compatibility.**
   `ProviderConfig` still carries compatibility fields such as `orchestrator_provider`, `worker_provider`, `orchestrator_model`, and `worker_model`.
   They are no longer the authoritative source of truth when `roles` is present, but they have not yet been fully removed from all external contracts.
   Desired end state:
   a roles-first public contract where provider/model topology is expressed only through canonical role bindings.

2. **Historical naming cleanup is intentionally incomplete.**
   Active server and OpenAPI surfaces now use `GIMO Orchestrator`, but archived docs, legacy plans, and historical artifacts may still contain `Repo Orchestrator`.
   This is documentation debt, not live runtime authority debt.
   Desired end state:
   only historical archives retain the old product-role wording, with active system surfaces fully normalized.

3. **Conversation turn validation is hardened at runtime insertion boundaries, not by backfill migration.**
   Backend turn creation now restricts supported runtime `agent_id` values for the current release line.
   However, previously stored thread JSON written outside the backend could still contain non-canonical agent identities.
   Desired end state:
   a canonical thread participant model plus migration or repair for non-conforming persisted turns when needed.

---

## 2) Runtime architecture (as implemented)

High level:

```
┌─────────────────────────────────────────────────────────────┐
│ GIMO Web (apps/web — Next.js 16)                           │
│  - Landing, Firebase Auth, Stripe suscripciones            │
│  - /api/license/*, /api/checkout, /api/webhooks/stripe     │
│  - Deploy: Vercel (gimo-web.vercel.app)                    │
├─────────────────────────────────────────────────────────────┤
│ FastAPI (tools/gimo_server/main.py)                        │
│  - /status, /ui/*, /tree, /file, /search, /diff            │
│  - /ops/* (drafts/approve/runs/config/provider/evals/...)  │
│  - /auth/* (session, login, provider accounts)             │
│  middlewares: panic│cors│correlation│rate_limit│auth        │
│  routers: 13 modular routers under routers/ops/            │
├─────────────────────────────────────────────────────────────┤
│ Services (52+ in tools/gimo_server/services/)              │
│  - OpsService, ProviderService, RunWorker, GraphEngine     │
│  - ProviderCatalogService, ProviderCapabilityService       │
│  - CostService, TrustEngine, ObservabilityService          │
│  - MergeGateService, PolicyService, SkillsService          │
├─────────────────────────────────────────────────────────────┤
│ Adapters (tools/gimo_server/adapters/)                     │
│  - OpenAICompatible, ClaudeCode, Codex, Gemini             │
│  - GenericCLI, MCPClient                                   │
├─────────────────────────────────────────────────────────────┤
│ Storage (.orch_data/ops)                                   │
│  - plan.json, config.json, provider.json                   │
│  - drafts/*.json, approved/*.json, runs/*.json             │
└─────────────────────────────────────────────────────────────┘
```

Durability model:

- All OPS/GIMO operational objects are persisted as JSON files under `.orch_data/ops/`.
- State changes use a file lock for critical mutations (e.g. approve/update run state).
- Cleanup loops run in the background to prevent unbounded growth.

---

## 3) Security model (roles, tokens, and guardrails)

### 2.1 Tokens and roles

Authentication is **Bearer token**.

Roles are derived from which token is used:

- `actions` — lowest privilege (read-only for actions-safe endpoints)
- `operator` — can approve and create/cancel runs (operational control)
- `admin` — full control, can mutate plans/provider/config and manage drafts

Role enforcement is implemented in `tools/gimo_server/routers/ops/common.py` using `_require_role()`.

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

## 4) OPS/GIMO operational objects (storage)

Directory: `.orch_data/ops/`

- `drafts/d_*.json` — drafts (status: `draft|rejected|approved|error`)
- `approved/a_*.json` — approved artifacts (the only allowed run input)
- `runs/r_*.json` — run execution state + log
- `config.json` — OPS config (see below)
- `plan.json` — active plan payload (optional)
- `provider.json` — provider configuration (admin-only access; redacted in public GET)

---

## 5) API contract (implemented today)

### 5.1 Key endpoints

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
  - creates a **new run instance** (`run_id`) per attempt
  - keeps a logical `run_key` for intent correlation (`draft_id + commit_base`)
  - returns `409 RUN_ALREADY_ACTIVE:*` if an active run exists for the same `run_key`
- `GET  /ops/runs` (actions+) — list
- `GET  /ops/runs/{run_id}` (actions+) — read
- `POST /ops/runs/{run_id}/cancel` (operator+) — cancel (second cancel returns 409)
- `POST /ops/runs/{run_id}/rerun` (operator+) — create a new run instance from an existing run
  - links lineage through `rerun_of`
  - increments `attempt`

**Provider + generation**

- `GET /ops/provider` (admin) — provider config (redacted)
- `PUT /ops/provider` (admin) — update provider config
- `POST /ops/generate` (admin or operator if allowed) — generate a draft from provider

**Config**

- `GET /ops/config` (operator+) — read
- `PUT /ops/config` (admin) — update

### 5.2 Filtered OpenAPI for integrations

- `GET /ops/openapi.json` returns a **filtered** OpenAPI spec suitable for external tools.

---

## 6) Configuration (OpsConfig)

Persisted in `.orch_data/ops/config.json`.

Fields:

- `default_auto_run: bool` — default behavior for approve if `auto_run` is not passed
- `draft_cleanup_ttl_days: int` — cleanup TTL for drafts in `rejected|error`
- `max_concurrent_runs: int` — run worker concurrency guard
- `operator_can_generate: bool` — whether operator may call `/ops/generate`

---

## 7) Background loops and cleanup

Background tasks started from FastAPI lifespan:

- snapshot cleanup loop (existing)
- OPS cleanup loop:
  - `OpsService.cleanup_old_runs()` — removes old run files based on TTL
  - `OpsService.cleanup_old_drafts()` — removes `rejected|error` drafts older than `draft_cleanup_ttl_days`

---

## 8) UI contract (current)

The Orchestrator UI is served from `tools/orchestrator_ui/dist/` when built (dev server on port 5173).

Stack: React + Vite + TypeScript + Zustand + Framer Motion.

Key components:

- `GraphCanvas` — interactive workflow graph (ReactFlow/xyflow)
- `OrchestratorChat` — chat interface for plan creation
- `SettingsPanel` / `ProviderSettings` — provider configuration and management
- `InspectPanel` — node detail view
- `StatusBar` — provider status, latency, cost

The UI:

- Visualizes drafts/approved/runs as interactive graph nodes
- Allows safe operational actions (approve/reject/edit/cancel)
- Never circumvents approval gates
- Supports multi-provider configuration (Ollama, OpenAI, Anthropic, Groq, etc.)

---

## 9) Multi-agent direction (frozen specification boundary)

GIMO is being used as the operational substrate for multi-agent execution.

**Important**: This doc does not describe a roadmap. It defines the boundary conditions any multi-agent executor must respect:

- Any future “step graph” system must preserve the guardrails in §2.4.
- **Multi-Surface Stabilization (Phase 7B)**:
  - Canonical authority is strictly server-side.
  - Clients (App, CLI, TUI) consume the same backend contracts (`/ops/operator/status`, `/ops/notices`).
  - Deprecated paths (`/mcp`, path-based repo selection) are marked as legacy and slated for removal.
  - The official App façade is hosted at `/mcp/app`.

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
0. **GIMO Web (Next.js 16)** - Landing, auth, licencias, Stripe (apps/web)
1. **Services (Python)** - 52+ servicios, GraphEngine es el nucleo
2. **REST API (FastAPI)** - ~100+ endpoints en `/ops/*`, `/ui/*`, `/auth/*`
3. **MCP Server (FastMCP)** - 14 tools para IDEs via stdio/SSE
4. **Frontend (React+Vite)** - Dashboard en puerto 5173

### Sistema de Storage
- **Actual**: JSON file-backed para OPS state, SQLite para cost/trust/eval storage.
- **GICS**: Daemon con SDK Python para almacenamiento distribuido de memoria operativa.
  Ver sección "Autoridad de GICS" a continuación.

### Autoridad de Motores de Ejecución

GIMO tiene **dos motores de ejecución** con dominios distintos y no superpuestos:

| Motor | Archivo | Dominio |
|---|---|---|
| **Pipeline** | `tools/gimo_server/engine/pipeline.py` | Runs operativos creados desde drafts aprobados. Es el motor principal invocado por `RunWorker → EngineService`. |
| **GraphEngine** | `tools/gimo_server/services/graph/engine.py` | Ejecución de workflows estructurados (`WorkflowGraph`). Usado desde rutas `/ops/workflow/*`. No compite con Pipeline. |

Cada run operativo usa Pipeline. GraphEngine es para workflows definidos explícitamente como grafos.
Los dos motores no se solapan ni se sustituyen mutuamente.

### Autoridad de GICS

GICS (`tools/gimo_server/services/gics_service.py`) **no es un daemon experimental**. Es la memoria operativa central de GIMO. Participa en:

- **Fiabilidad de modelos**: `record_model_outcome()` + `get_model_reliability()` — score empírico blended (80% tasa real + 20% prior) con detección de anomalías (failure_streak ≥ 3).
- **Routing de modelos**: `ModelRouterService` excluye modelos con `anomaly=True` via `_filter_gics_anomalies()`.
- **Telemetría de agentes**: push de outcomes y eventos de runs al namespace `ops:*`.
- **ACE pre-flight**: capability history para decisiones de decomposición multi-agente.
- **Priors de política**: `seed_profile()` / `seed_policy()` para priors por workspace/host.

**Source of truth por dominio**:
- `OPS JSON` (`.orch_data/ops/`) → estado operacional duradero (drafts, runs, config)
- `Pipeline journal` → trazabilidad de ejecución por stage
- `GICS` → memoria estadística, fiabilidad, capability, policy priors
- `Provider config` → topología y binding de proveedores LLM

### Flujo Principal Detallado
1. **Draft**: Se recibe un prompt o intent y se genera un borrador (`OpsDraft`).
2. **Approved**: El usuario (o regla automatica) aprueba el plan (`OpsApproved`).
3. **Run**: Se crea un run con `status=pending` (`OpsRun`).
4. **RunWorker**: El worker asíncrono detecta el run y llama a `EngineService.execute_run()`.
5. **EngineService**: Selecciona composición (por `execution_mode` explícito o heurística) y ejecuta Pipeline.
6. **Pipeline stages**: PolicyGate → RiskGate → [LlmExecute / FileWrite / SpawnAgents / etc.]
7. **ProviderService / LLM**: Se solicita inferencia al proveedor configurado.

IDE → MCP tool → OpsService → RunWorker → ProviderService → Adapter → LLM

## Appendix C — LLM Adapters & Connectivity

Desde esta fase, la **fuente unica de verdad** para providers es OPS (`/ops/provider`, `/ops/connectors`, etc.).

### Adaptadores Implementados (`tools/gimo_server/adapters/`)

| Adapter | Protocolos | Providers |
|---|---|---|
| `OpenAICompatibleAdapter` | HTTP/JSON, Streaming | Ollama, LM Studio, vLLM, DeepSeek, OpenAI, Groq, OpenRouter |
| `ClaudeCodeAdapter` | Stdio/MCP, Streaming | Claude Code CLI |
| `CodexAdapter` | Stdio/JSON, Streaming | OpenAI Codex CLI |
| `GeminiAdapter` | Stdio/JSON, Streaming | Gemini CLI |
| `GenericCLIAdapter` | Stdio/Text, Streaming | Any CLI |
| `MCPClientAdapter` | MCP Protocol | Any MCP-compatible server |

### Capability Matrix
Cada provider declara `auth_modes_supported`, `can_install`, `install_method`, `supports_account_mode`, `supports_recommended_models`, `requires_remote_api`.

Provider catalog: `tools/gimo_server/services/provider_catalog_service.py` (39K LOC).

## Appendix D — Sub-Delegation Protocol
El protocolo define como un Primary Agent (e.g., Claude/GPT-4) delega sub-tareas a Sub-Agents (e.g., Ollama/CodeLlama).
1. **Delegation Request**: POST `/api/agent/{agentId}/delegate`
2. **Approval & Instantiation**: Orchestrator verifica TrustLevel. Instancia el Sub-Agent y lo anade al Graph.
3. **Execution & Reporting**: Streaming output al contexto del Primary Agent.
4. **Completion**: Retorna artefacto final como "tool result". Success or Failure.

## Appendix E — Test Suite

| Metric | Current |
|---|---|
| Test files | 37 |
| Tests collected | 346 |
| Directories | `unit/`, `integration/`, `fixtures/` |
| Execution time | ~4s (unit), ~30s (with integration) |

Run: `python -m pytest -m "not integration" -v`
