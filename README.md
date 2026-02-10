# GIMO — Gred in Multiagent Orchestrator (Repo Orchestrator) — UNRELEASED

**Status**: UNRELEASED (docs + evidence validation in progress)

This repo exposes **GIMO (Gred in Multiagent Orchestrator)**: a **token-protected FastAPI service** to safely inspect code repositories and run auditable operational workflows.
Design intent:

- **Read access is served from per-request snapshots** (for forensic integrity).
- Sensitive data is **redacted** in responses.
- The service can enter **Panic Mode (LOCKDOWN)** under attack/exception thresholds.

Until the maintainer explicitly declares `1.0.0`, the version stays `UNRELEASED`.

## Quick Start (Dev)

### Backend (FastAPI)

```cmd
pip install -r requirements.txt
python -m uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325
```

The API requires `Authorization: Bearer <TOKEN>`.

Token sources (in order):

1) `ORCH_TOKEN` env var, if set
2) auto-generated token stored in `tools/gimo_server/.orch_token` (created on first run)

Minimal smoke test:

```cmd
curl -H "Authorization: Bearer %ORCH_TOKEN%" http://127.0.0.1:9325/status
```

### Frontend (optional)

```cmd
cd tools\orchestrator_ui
npm ci
npm run build
```

If `tools/orchestrator_ui/dist/` exists, the backend will serve the SPA at `/`.

### Quality Gates (recommended)

```cmd
pip install -r requirements-dev.txt
python scripts\\ci\\quality_gates.py
```

## Documentation tracking

- Docs registry: `docs/DOCS_REGISTRY.md`
- **Source of Truth**: `docs/GIMO_SYSTEM.md`
- Evidence pack (verification logs / reports): `docs/evidence/`
- Deprecated snapshots: `docs/deprecated/`

## Release status

This project is **not declared v1.0** until:

1) documentation is consistent with code,
2) evidence pack is complete,
3) maintainer approves and updates version markers.
