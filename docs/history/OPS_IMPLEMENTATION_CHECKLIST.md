#+ OPS Runtime v2 — Checklist Operativa de Implementación (HISTORICAL — DO NOT USE)

**STATUS**: HISTORICAL (DO NOT USE)
**Reason**: preserved as project history. Not authoritative.
**Authoritative spec**: `docs/GIMO_SYSTEM.md`

> Este documento convierte `docs/history/OPS_RUNTIME_PLAN_v2.md` en una **checklist ejecutable**.
> Enfoque: entregar valor por fases, con **GO/NO‑GO** claro, comandos de verificación y guardarraíles de seguridad.

---

## Convenciones y variables

### URLs / Auth

- **Base URL**: `http://localhost:9325`
- **TOKEN**: bearer token con rol `admin` (para mutaciones) o `actions` (lectura)

Ejemplos (bash/cmd con `curl`):

```bash
set TOKEN=REEMPLAZA
set ORCH=http://localhost:9325
curl -H "Authorization: Bearer %TOKEN%" %ORCH%/status
```

> Nota: si usas PowerShell, cambia el quoting acorde.

### IDs

- Draft: `d_<ulid>`
- Approved: `a_<ulid>`
- Run: `r_<ulid>`

### Directorios

- Storage OPS: `.orch_data/ops/`
  - `plan.json`
  - `provider.json`
  - `drafts/`
  - `approved/`
  - `runs/`

---

## Preflight (antes de tocar código)

- [ ] (Local) `python --version` y dependencias instaladas (venv/poetry/pip según tu repo).
- [ ] (Local) El orchestrator arranca sin OPS:
  - [ ] `python -m tools.repo_orchestrator.main` (o `scripts/launch_orchestrator.ps1`).
- [ ] (API) `/status` responde OK.
- [ ] (Seguridad) Confirmar cómo se mapean roles `actions/admin` (claims/JWT/env) en tu middleware actual.

---

## Fase 0 — Scaffolding + Storage (stubs 501)

### Objetivo

Estructura mínima de OPS integrada en FastAPI, directorios creados, endpoints existentes pero **stub**.

### Backend

- [ ] Crear modelos Pydantic
  - [ ] `tools/repo_orchestrator/ops_models.py`
    - [ ] `OpsPlan`
    - [ ] `OpsDraft`
    - [ ] `OpsApproved`
    - [ ] `OpsRun`
    - [ ] `ProviderConfig` (mínimo)

- [ ] Crear router OPS
  - [ ] `tools/repo_orchestrator/ops_routes.py`
    - [ ] Declarar `/ops/*` con respuestas `501 Not Implemented`

- [ ] Registrar router y asegurar storage
  - [ ] `tools/repo_orchestrator/main.py`
    - [ ] Incluir router OPS
    - [ ] En lifespan: crear `.orch_data/ops/{drafts,approved,runs}`
    - [ ] Inicializar `plan.json` y `provider.json` si faltan

- [ ] Config
  - [ ] `tools/repo_orchestrator/config.py`
    - [ ] `OPS_DATA_DIR`
    - [ ] `OPS_RUN_TTL`

### Tests

- [ ] `tests/unit/test_ops_models.py` (validación schema)

### Verificación

- [ ] `GET /ops/plan` devuelve `501`

```bash
curl -i -H "Authorization: Bearer %TOKEN%" %ORCH%/ops/plan
```

- [ ] `pytest tests/unit/test_ops_models.py` → PASS

### GO/NO‑GO

- GO si: server arranca + router registrado + storage creado + tests verdes.

---

## Fase 1 — OPS Service CRUD (plan + drafts + approved)

### Objetivo

CRUD funcional y auditable. Todavía **sin provider**.

### Backend

- [ ] `tools/repo_orchestrator/services/ops_service.py`
  - [ ] Plan
    - [ ] `get_plan()` / `set_plan()`
  - [ ] Drafts
    - [ ] `list_drafts()`
    - [ ] `create_draft(prompt, context?)`
    - [ ] `get_draft(id)`
    - [ ] `update_draft(id, ...)`
    - [ ] `reject_draft(id)`
    - [ ] `approve_draft(id)`
      - [ ] **atómico**: `rename drafts/d_*.json → approved/a_*.json`
  - [ ] Approved
    - [ ] `list_approved()`
    - [ ] `get_approved(id)`
  - [ ] Guardarraíles
    - [ ] Validación de paths (BASE_DIR)
    - [ ] Audit log por operación
    - [ ] Rate limit / auth / correlation ya heredado por middleware

- [ ] Implementar rutas reales en `tools/repo_orchestrator/ops_routes.py`
  - [ ] `GET/PUT /ops/plan`
  - [ ] `GET/POST /ops/drafts`
  - [ ] `GET/PUT /ops/drafts/{id}`
  - [ ] `POST /ops/drafts/{id}/approve`
  - [ ] `POST /ops/drafts/{id}/reject`
  - [ ] `GET /ops/approved`
  - [ ] `GET /ops/approved/{id}`

### Tests

- [ ] `tests/unit/test_ops_service.py`
- [ ] `tests/unit/test_ops_routes.py`

### Verificación (manual)

- [ ] Crear draft

```bash
curl -s -X POST -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" \
  -d "{\"prompt\":\"refactor X\"}" %ORCH%/ops/drafts
```

- [ ] Aprobar draft

```bash
curl -s -X POST -H "Authorization: Bearer %TOKEN%" %ORCH%/ops/drafts/d_xxx/approve
```

- [ ] Ver approved

```bash
curl -s -H "Authorization: Bearer %TOKEN%" %ORCH%/ops/approved
```

### GO/NO‑GO

- GO si: RBAC correcto (admin muta, actions lee), audit registra y approval mueve a `approved/`.

---

## Fase 2 — Provider Layer + `/ops/generate`

### Objetivo

Generación de drafts vía provider seleccionable. Falla “gracefully” si provider offline.

### Backend

- [ ] Providers
  - [ ] `tools/repo_orchestrator/providers/base.py` (ABC)
  - [ ] `tools/repo_orchestrator/providers/openai_compat.py`
    - [ ] Soporta LM Studio / Ollama / OpenAI (mismo protocolo)
  - [ ] (Opcional) `gemini.py`, `anthropic.py`

- [ ] `tools/repo_orchestrator/services/provider_service.py`
  - [ ] Carga/guarda `provider.json`
  - [ ] Resuelve `${ENV_VAR}` en runtime
  - [ ] `generate(prompt, context)` con timeout (30s)
  - [ ] `health_check()`
  - [ ] Sanitización: **nunca** devolver api_key al cliente

- [ ] Endpoints
  - [ ] `GET/PUT /ops/provider`
  - [ ] `POST /ops/generate` → crea draft

### Tests

- [ ] `tests/unit/test_provider_service.py` (mock HTTP)

### Verificación

- [ ] Con LM Studio/Ollama corriendo:

```bash
curl -s -X POST -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" \
  -d "{\"prompt\":\"analyze this code\"}" %ORCH%/ops/generate
```

- [ ] Provider offline: respuesta de error controlada, sin tumbar el server.

### GO/NO‑GO

- GO si: `/ops/generate` crea drafts, provider switcheable y **secretos no salen**.

---

## Fase 3 — Runs + Dispatch

### Objetivo

Crear y seguir runs **solo** desde approved, con log estructurado.

### Backend

- [ ] Extender `ops_service` para runs
  - [ ] `create_run(approved_id)`
  - [ ] `get_run(run_id)` / `list_runs()`
  - [ ] `append_log(run_id, {ts, level, msg, correlation_id?})`
  - [ ] Enforce: si `approved_id` no existe → 404; si intentan draft → 403

- [ ] Rutas
  - [ ] `POST /ops/runs`
  - [ ] `GET /ops/runs`
  - [ ] `GET /ops/runs/{run_id}`

### Tests

- [ ] `tests/unit/test_ops_runs.py`

### Verificación

```bash
curl -s -X POST -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" \
  -d "{\"approved_id\":\"a_xxx\"}" %ORCH%/ops/runs
curl -s -H "Authorization: Bearer %TOKEN%" %ORCH%/ops/runs/r_xxx
```

### GO/NO‑GO

- GO si: no hay camino de ejecución desde drafts y el historial/log funciona.

---

## Fase 4 — UI “OpsIsland” (Approval Gate)

### Objetivo

Operar todo el flujo desde UI.

### Frontend

- [ ] Hook
  - [ ] `tools/orchestrator_ui/src/hooks/useOpsService.ts`

- [ ] Islas/vistas
  - [ ] `OpsIsland.tsx`
  - [ ] `PromptFactory.tsx`
  - [ ] `ReviewPanel.tsx`
  - [ ] `RunsView.tsx`
  - [ ] Provider selector + health

- [ ] Integración
  - [ ] `App.tsx` (tabs: Maintenance | OPS)
  - [ ] `types.ts` (interfaces OPS)

### Verificación

- [ ] `cd tools/orchestrator_ui && npm run build && npm run test:coverage`
- [ ] Manual:
  - [ ] crear draft
  - [ ] editar
  - [ ] aprobar
  - [ ] crear run
  - [ ] ver logs

### GO/NO‑GO

- GO si: UI no permite ejecutar nada no aprobado (no hay botones/paths para drafts→run).

---

## Fase 5 — MCP Bridge (READ‑ONLY + tools acotadas)

### Objetivo

Exponer el modelo MCP:

- Resources (read-only)
- Prompts (dispatch)
- Tools (crear run, consultar status)

…con regla **innegociable**:

> **Prompts y Tools solo operan sobre `approved/*`.**

### Node MCP

- [ ] `tools/mcp_ops/server.mjs`
  - [ ] Resources
    - [ ] `ops://plan` → `GET /ops/plan`
    - [ ] `ops://approved` → `GET /ops/approved`
    - [ ] `ops://approved/{id}` → `GET /ops/approved/{id}`
    - [ ] `ops://runs/{id}` → `GET /ops/runs/{id}`
    - [ ] `ops://context` → `GET /ui/status`
  - [ ] Prompts
    - [ ] `orch_dispatch(approved_id)`
    - [ ] `sub_dispatch(approved_id, agent)`
    - [ ] `editp_dispatch(approved_id, file)`
    - [ ] Validación: si no está en approved → error
  - [ ] Tools
    - [ ] `create_run(approved_id)` → `POST /ops/runs`
    - [ ] `get_run_status(run_id)` → `GET /ops/runs/{id}`

- [ ] `tools/mcp_ops/package.json`

### Verificación

- [ ] Con inspector:
  - [ ] resources listan bien
  - [ ] `orch_dispatch` con `draft_id` falla
  - [ ] `create_run` con `approved_id` funciona

### GO/NO‑GO

- GO si: MCP no tiene ninguna ruta que permita ejecutar drafts.

---

## Fase 6 — Hardening + OpenAPI + Docs + E2E

### Objetivo

Cerrar calidad: OpenAPI actualizado, e2e, y docs.

- [ ] OpenAPI
  - [ ] `tools/repo_orchestrator/openapi.yaml` incluir `/ops/*`

- [ ] Docs
  - [ ] `docs/OPERATIONS.md` (operativa OPS)
  - [ ] `docs/SECURITY.md` (RBAC + redaction + audit)

- [ ] E2E
  - [ ] `tests/test_ops_e2e.py` (draft→approve→mcp prompt→create_run→get_status)

- [ ] Quality gates
  - [ ] `python scripts/quality_gates.py`
  - [ ] `pytest tests/ -x`

### GO/NO‑GO

- GO si: quality gates verdes, sin regresiones, y el flujo completo es reproducible.

---

## Runbook mínimo (día a día)

- [ ] Crear draft (manual o provider)
- [ ] Revisar/editar
- [ ] Approve
- [ ] Ejecutar run (UI o MCP tool)
- [ ] Consultar status/log

---

## Rollback mínimo

- [ ] Activar `panic_mode` si aplica para congelar cambios.
- [ ] Revertir commit(s) / desregistrar router OPS.
- [ ] Conservar `.orch_data/ops/approved` si necesitas auditoría.
- [ ] Opcional: purgar `.orch_data/ops/runs`.
