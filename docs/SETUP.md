# Setup

**Status**: CURRENT
**Last verified**: 2026-03-04

> Scope: monorepo GIMO — backend (`tools/gimo_server/`), UI (`tools/orchestrator_ui/`), web (`apps/web/`).

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

## Frontend (Orchestrator UI)

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

## GIMO Web (apps/web)

```cmd
cd apps\web
npm ci
npm run lint
npm run build
npm run dev   # → http://localhost:3000
```

Configuration:

- Copy `apps/web/.env.example` to `apps/web/.env.local` and fill in values.
- Key variables: `NEXT_PUBLIC_FIREBASE_*`, `STRIPE_*`, `LICENSE_SIGNING_PRIVATE_KEY`.
- See `apps/web/README.md` for the full variable list.
- Deploy: Vercel (configured to point to `apps/web`).

## MCP Integrations (Claude/Cline/Cursor/Antigravity)

### Recommended MCP wiring (Cline ↔ GIMO)

```text
Cline/Antigravity (MCP client)
        │
        │ reads mcp_config.json
        ▼
"gimo" server entry
  command: python
  args: -m tools.gimo_server.mcp_bridge.server
  cwd:  C:\Users\shilo\Documents\Github\gred_in_multiagent_orchestrator
        │
        ▼
tools.gimo_server.mcp_bridge.server (FastMCP stdio)
        ├─ dynamic tools (registrar.py)
        ├─ resources (resources.py)
        └─ native tools (native_tools.py)
```

### Minimal `gimo` config

```json
{
  "mcpServers": {
    "gimo": {
      "command": "python",
      "args": ["-m", "tools.gimo_server.mcp_bridge.server"],
      "cwd": "C:\\Users\\shilo\\Documents\\Github\\gred_in_multiagent_orchestrator",
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "ORCH_REPO_ROOT": "C:\\Users\\shilo\\Documents\\Github\\gred_in_multiagent_orchestrator"
      }
    }
  }
}
```

### Config locations (Windows)

In this environment, the active paths are:

- `C:\Users\shilo\.gemini\antigravity\mcp_config.json`
- `C:\Users\shilo\.gemini\mcp_config.json`

### Automatic registration

```cmd
python scripts\setup_mcp.py
```

Validation without modifying config:

```cmd
python scripts\setup_mcp.py --check
```

### Critical rule

After changing MCP config, restart the client session (Cline/Antigravity).
Without restart, you may see: `No connection found for server: gimo`.

## Secure Launcher (`GIMO_DEV_LAUNCHER.cmd`)
The launcher provides a safe development experience:
- **Authentication**: Generates a 32-byte secure token on first run (`ORCH_TOKEN`).
- **Localhost Binding**: Binds backend and frontend to `127.0.0.1` minimizing attack surface.
- **Port Hygiene**: Kills zombie processes on 9325, 5173, and 3000.
- **Three Services**: Launches backend (9325), orchestrator UI (5173), and GIMO Web (3000).
- **Health Verification**: Waits for backend readiness before starting frontend.

## CI & Testing Suites

CI runs 4 jobs on every push: `python-gates`, `python-tests`, `ui/lint-test-build`, `web/lint-build`.

Local gates recommended before any PR:
```cmd
pip install -r requirements.txt -r requirements-dev.txt
pre-commit run --all-files
python scripts\ci\check_no_artifacts.py --tracked
python scripts\ci\quality_gates.py
python -m pytest -m "not integration" -v
cd apps\web && npm run build
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
