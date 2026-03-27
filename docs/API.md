# GIMO API & Operations Contracts

**Version**: 1.1.0 | **Last Updated**: 2026-03-04

All endpoints require `Authorization: Bearer <ORCH_TOKEN>`.

## 1. Core & UI Endpoints
- `GET /status`: Returns version & uptime.
- `GET /ui/status`: Returns version, uptime, allowlist_count, service status.
- `GET /ui/audit?limit=200`: Tail the audit log.
- `GET /ui/allowlist`: List allowed paths.
- `GET /ui/security/events`: List security events & panic mode status.
- `POST /ui/security/resolve?action=clear_panic`: Clear panic mode.
- `GET /ui/service/status` | `POST /ui/service/restart` | `POST /ui/service/stop`: Service control.

## 2. File & Repo Operations
- `GET /ops/repos`: Canonical repo listing for clients.
- `GET /ops/repos/active`: Canonical active-repo snapshot.
- `POST /ops/repos/open?path=<path>`: [LEGACY] Open repo by host path.
- `POST /ops/repos/select?path=<path>`: [LEGACY] Select active repo by host path.
- `POST /ops/repos/vitaminize?path=<path>`: Operator vitaminize flow.
- `GET /ui/repos*`: [LEGACY UI] Compatibility surface, not the canonical client contract.
- `GET /tree?path=.&max_depth=3`: Get directory tree.
- `GET /file?path=<path>&start_line=1&end_line=500`: Read file content (uses `.orch_snapshots/`).
- `GET /search?q=<query>&ext=<ext>`: Search files.
- `GET /diff?base=main&head=HEAD`: Git diff output.

## 3. Ops Runtime Endpoints (Admin & Operator)
- `GET|PUT /ops/plan`: Active plan config.
- `GET|POST /ops/drafts` & `GET|PUT|POST /ops/drafts/{id}[/reject|approve]`: Drafts lifecycle.
- `GET /ops/approved` & `GET /ops/approved/{id}`: Approved operations.
- `POST|GET /ops/runs`, `GET|POST /ops/runs/{id}[/cancel]`: Run execution state.
- `GET|PUT /ops/provider` & `POST /ops/generate`: Provider configuration and LLM generation.
- `GET|PUT /ops/config`: General OPS config.
- `GET /ops/openapi.json`: [LEGACY INTEGRATION] OpenAPI schema for external agents. Preferred: `/mcp/app`.

## 4. First-Class Client Façades [Phase 7B Verified]
- `/mcp/app`: **[OFFICIAL]** App façade for ChatGPT and other first-class consumers.
- `/mcp/app/sse`: Official App MCP SSE transport for ChatGPT Developer Mode.
- `/mcp/app/mcp`: Official App MCP streamable HTTP transport.
- `/mcp`: **[LEGACY]** General-purpose MCP bridge.
- `/ops/operator/status`: Canonical backend status for TUI/CLI parity.
- `/ops/notices`: Canonical notification feed for all surfaces.
- Default App MCP profile is `safe`; `extended` is opt-in for broader internal dogfooding.
- `POST /ops/app/sessions`: Create App session.
- `GET /ops/app/sessions/{id}`: Read App session state.
- `POST /ops/app/sessions/{id}/repo/select`: Bind opaque repo handle to App session and provision an App-managed snapshot/clone. The App surface does not read the original repo directly.
- `GET /ops/app/sessions/{id}/recon/*`: App reconnaissance over opaque handles only.
- `POST /ops/app/sessions/{id}/drafts`: Create validated App draft from recon evidence.
- `POST /ops/app/sessions/{id}/context-requests`: Create/list/resolve/cancel App context requests.
- `GET /ops/app/runs/{run_id}/review`: Canonical review bundle + merge preview over the App-bound snapshot/workspace; this façade does not read the original repo directly.
- `POST /ops/app/runs/{run_id}/discard`: Discard run and purge reconstructive state.
- `POST /ops/app/sessions/{id}/purge`: Remove App session state.
- `POST /ops/runs/{id}/merge`: First-party/operator manual merge against the authoritative source repo resolved by backend contracts.

## 4. Multi-Agent API (UI / Orchestrator)
- `GET /ui/agent/{agent_id}/quality`: Quality metrics.
- `POST /ui/plan/create`, `GET|PATCH /ui/plan/{plan_id}`, `POST /ui/plan/{plan_id}/approve`: Plan management.
- `POST|GET /ui/agent/{agent_id}/message[s]`: Agent communication.
- `POST|GET /ui/agent/{agent_id}/delegate` & `POST /ui/sub_agent/{id}/terminate`: Sub-agent delegation.
- `POST /ui/agent/{agent_id}/control?action=pause|resume|cancel`: Control flow.
- `WS /ws`: Real-time events (plan_update, chat_message, etc.).

## 5. Provider Management
- `GET /ops/provider`: Provider config (redacted).
- `PUT /ops/provider`: Update provider config.
- `POST /ops/generate`: Generate draft from LLM provider.
- `GET /ops/provider/catalog`: Full provider catalog with capabilities.
- `GET /ops/provider/capabilities`: Provider capability matrix.
- `POST /ops/connectors/account/login/start`: Start device flow auth.
- `GET /ops/connectors/account/login/{flow_id}`: Check login flow status.
- `POST /ops/connectors/account/refresh`: Refresh account token.
- `POST /ops/connectors/account/logout`: Disconnect provider account.

## 6. Observability & Mastery
- `GET /ops/mastery/status`: Token usage and cost summary.
- `GET /ops/mastery/forecast`: Cost forecast.
- `GET /ops/observability/traces`: Execution traces.
- `GET /ops/observability/metrics`: System metrics.
- `GET /ops/observability/health`: Health status per service.

## 7. Trust & Security
- `GET /ops/trust/summary`: Trust engine summary.
- `GET /ops/trust/events`: Trust events.
- `POST /ops/trust/reset`: Reset trust scores.
- `PUT /ops/trust/config`: Update trust config.
- `GET /ops/trust/provider/{provider}`: Provider trust score.

## 8. Evals
- `GET /ops/evals`: List evaluations.
- `POST /ops/evals`: Create evaluation.
- `GET /ops/evals/{id}`: Get evaluation detail.
- `POST /ops/evals/compare`: Compare models.
- `POST /ops/evals/batch`: Batch evaluation.

## 9. Skills & Conversations
- `GET /ops/skills`: List available skills.
- `POST /ops/skills`: Register skill.
- `GET /ops/skills/{id}`: Get skill detail.
- `GET /ops/threads`: Canonical thread listing.
- `POST /ops/threads`: Create thread.
- `GET /ops/threads/{id}`: Get thread detail.
- `POST /ops/threads/{id}/messages`: Append user message.
- `POST /ops/threads/{id}/chat`: Agentic chat response.
- `POST /ops/threads/{id}/chat/stream`: Agentic chat SSE stream.
- `POST /ops/threads/{id}/reset`: Reset thread context without changing identity.
- `POST /ops/threads/{id}/config`: Persist effort/permissions session config.
- `POST /ops/threads/{id}/context/add`: Persist attached context items.
- `GET /ops/threads/{id}/usage`: Read authoritative thread usage snapshot.

## 10. Operations & Day-2
- **Launcher**: `gimo.cmd` is the official dev launcher (`gimo`, `gimo up`, `gimo down`, `gimo doctor`, `gimo bootstrap`).
- **Backend**: FastAPI running on `127.0.0.1:9325`.
- **GIMO Web**: Next.js on `localhost:3000`. Deploy via Vercel.
- **Audit Logging**: `logs/orchestrator_audit.log` (rotates, redacts secrets).
- **Panic Mode**: Triggered by invalid tokens or exceptions. Cleared via `/ui/security/resolve`.
- **Snapshots**: File reads use `.orch_snapshots/` with TTL (default 240s) for safe reading.
