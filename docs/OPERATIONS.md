# Operations

**Status**: NEEDS_REVIEW
**Last verified**: N/A

This document covers day-2 operations for the Repo Orchestrator service.

## Service overview

- Backend: FastAPI (`tools/gimo_server/main.py`)
- Default port (docs + docker + scripts): **9325**
- Auth: `Authorization: Bearer <TOKEN>` required for API endpoints
- Local-only by default: helper scripts bind to `127.0.0.1`

## Start / Stop

### Development (manual)

```cmd
python -m uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325
```

### Windows helper scripts

- `scripts/ops/start_orch.cmd` (dev convenience; kills any process listening on 9325)
- `scripts/ops/run_as_service.bat` (intended for Windows Service style execution)
- `scripts/ops/manage_service.ps1` (create/start/stop Windows service wrapper around an executable)

Known inconsistency:

- `scripts/ops/launch_orchestrator.ps1` launches `tools.gimo_server.main:app` on port `9325`.

Note:

- Scripts were reorganized under `scripts/{dev,ops,ci,tools}`.

## Health & status

- `GET /status` → version + uptime
- `GET /ui/status` → version + uptime + allowlist_count + last audit line

## Logging

### Audit log

- Path: `logs/orchestrator_audit.log`
- Rotation: configured via `ORCH_AUDIT_LOG_MAX_BYTES` and `ORCH_AUDIT_LOG_BACKUP_COUNT`
- Entries redact long actor tokens to avoid leaks

### Panic Mode (LOCKDOWN)

Panic mode is a protective lockdown state.

- Trigger sources:
  - repeated invalid auth attempts (threshold-based)
  - unhandled exceptions (threshold-based)
- Behavior:
  - blocks unauthenticated requests with `503` (root and resolve endpoints remain reachable)
  - authenticated requests may still pass depending on token and path
- Clear:
  - `POST /ui/security/resolve?action=clear_panic` (requires valid token)

## Repository selection

The service supports selecting an “active repo” under a configured root.

Endpoints (see `tools/gimo_server/routes.py`):

- `GET /ui/repos`
- `GET /ui/repos/active`
- `POST /ui/repos/select?path=...`
- `POST /ui/repos/vitaminize?path=...`

## Snapshots

File reads are served from snapshots:

- Snapshot directory: `.orch_snapshots/`
- TTL: `ORCH_SNAPSHOT_TTL` (default 240 seconds)
- Cleanup loop runs in background (see `tools/gimo_server/tasks.py`).

## Rollback (safe)

1) Stop the running uvicorn process (Ctrl+C) / stop the service.
2) Remove Cloudflare tunnel / reverse proxy rules if applicable.
3) Archive `logs/` and `tools/gimo_server/security_db.json` if you need incident traces.
