# Setup

**Status**: NEEDS_REVIEW
**Last verified**: 2026-02-06 04:59 CET

This document is being rebuilt from scratch. Every claim must be backed by reproducible evidence under `docs/evidence/`.

> Scope: this repo’s backend lives in `tools/gimo_server/` and serves a read-only inspection API.

## Backend (Python)

```cmd
pip install -r requirements.txt
python -m uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325
```

### Environment variables

Create a `.env` (see `.env.example`) or export env vars.

Minimum required:

- `ORCH_TOKEN` (Bearer token for API access). If not set, the service will auto-generate one and store it in:
  - `tools/gimo_server/.orch_token`
- `ORCH_REPO_ROOT` (base directory where repos live; defaults to `../` of BASE_DIR)

Optional (common):

- `ORCH_ACTIONS_TOKEN` (read-only token, typically used for automated clients)
- `ORCH_CORS_ORIGINS`

### Smoke test

```cmd
curl -H "Authorization: Bearer %ORCH_TOKEN%" http://127.0.0.1:9325/status
```

## Docker

This repo includes a backend-only Docker image.

```cmd
docker build -t gred-orchestrator:local .
docker run --rm -p 9325:9325 gred-orchestrator:local
```

Or via compose:

```cmd
docker compose up --build
```

Notes:

- The provided Dockerfile does **not** build the UI; the SPA is only served when `tools/orchestrator_ui/dist/` exists.

## Quality gates

```cmd
pip install -r requirements-dev.txt
python scripts\\ci\\quality_gates.py
```

## Frontend (UI)

```cmd
cd tools\orchestrator_ui
npm ci
npm run lint
npm run build
npm run test:coverage
```

UI configuration:

- `tools/orchestrator_ui/.env.local` may define `VITE_API_URL=http://localhost:9325`.
- If `VITE_API_URL` is not set, the UI fallback uses port `9325`.

Known inconsistency:

- The UI no longer hard-codes a port in the dashboard; it derives the display label from `VITE_API_URL`/fallback.

## Secure Launcher (`GIMO_LAUNCHER.cmd`)
The launcher provides a safe development experience:
- **Authentication**: Generates a 32-byte secure token on first run (`ORCH_TOKEN`).
- **Localhost Binding**: Binds backend and frontend to `127.0.0.1` minimizing attack surface.
- **Port Hygiene**: Kills zombie processes on 9325 and 5173.
- **Health Verification**: Waits for backend readiness before starting frontend.

## CI & Testing Suites
Local gates recommended before any PR:
```cmd
pip install -r requirements.txt -r requirements-dev.txt
pre-commit run --all-files
python scripts\ci\check_no_artifacts.py --tracked
python scripts\ci\quality_gates.py
python -m pytest -m "not integration" -v
```

For LLM / adversarial test suites, run LM Studio or Ollama locally, then:
```cmd
set LM_STUDIO_REQUIRED=1
set LM_STUDIO_HOST=http://localhost:11434/v1
set LM_STUDIO_MODEL=qwen2.5:0.5b
python -m pytest tests/adversarial -v --tb=short
```

## Troubleshooting
- **401 Token missing / Invalid token**: Ensure `ORCH_TOKEN` is set, or read from `.orch_token`.
- **503 System in LOCKDOWN**: System panicked. Clear with: `curl -X POST -H "Authorization: Bearer %ORCH_TOKEN%" "http://127.0.0.1:9325/ui/security/resolve?action=clear_panic"`
- **Port already in use**: Kill whatever is on port 9325.
- **UI cannot connect**: Check backend is running. Set `VITE_API_URL=http://localhost:9325` in `tools/orchestrator_ui/.env.local`.

## Release Process
The project remains unreleased until v1.0. 
Definition of Done for 1.0:
1. Docs consistent with code.
2. Evidence pack complete under `docs/evidence/`.
3. Version markers updated.
