# GIMO API & Operations Contracts

**Version**: 1.0.0 | **Last Updated**: 2026-02-23

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
- `GET /ui/repos`: List repositories.
- `GET /ui/repos/active`: Get active repository.
- `POST /ui/repos/open?path=<path>`: Open repo.
- `POST /ui/repos/select?path=<path>`: Select active repo.
- `POST /ui/repos/vitaminize?path=<path>`: Init GIMO config in repo.
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
- `GET /ops/openapi.json`: OpenAPI schema for integrations.

## 4. Multi-Agent API (UI / Orchestrator)
- `GET /ui/agent/{agent_id}/quality`: Quality metrics.
- `POST /ui/plan/create`, `GET|PATCH /ui/plan/{plan_id}`, `POST /ui/plan/{plan_id}/approve`: Plan management.
- `POST|GET /ui/agent/{agent_id}/message[s]`: Agent communication.
- `POST|GET /ui/agent/{agent_id}/delegate` & `POST /ui/sub_agent/{id}/terminate`: Sub-agent delegation.
- `POST /ui/agent/{agent_id}/control?action=pause|resume|cancel`: Control flow.
- `WS /ws`: Real-time events (plan_update, chat_message, etc.).

## 5. Operations & Day-2
- **Backend**: FastAPI running on `127.0.0.1:9325`. Start with `scripts/ops/start_orch.cmd`.
- **Audit Logging**: `logs/orchestrator_audit.log` (rotates, redacts secrets).
- **Panic Mode**: Triggered by invalid tokens or exceptions. Cleared via `/ui/security/resolve`.
- **Snapshots**: File reads use `.orch_snapshots/` with TTL (default 240s) for safe reading.
