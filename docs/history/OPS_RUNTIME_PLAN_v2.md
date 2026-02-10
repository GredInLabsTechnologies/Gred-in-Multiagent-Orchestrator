# OPS Runtime — Plan de Implementacion v2 (HISTORICAL — DO NOT USE)

**STATUS**: HISTORICAL (DO NOT USE)
**Reason**: preserved as project history. Not authoritative.
**Authoritative spec**: `docs/GIMO_SYSTEM.md`

## 1. Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│  FastAPI (main.py :9325)                                │
│  ┌──────────┐ ┌──────────┐ ┌───────────────────────┐   │
│  │ /tree    │ │ /file    │ │ /ops/*  (NEW)         │   │
│  │ /search  │ │ /diff    │ │  drafts/approve/runs  │   │
│  │ /ui/*    │ │ /status  │ │  provider/plan        │   │
│  └──────────┘ └──────────┘ └───────────────────────┘   │
│  middlewares: panic│cors│correlation│rate_limit│auth    │
│  security:   allowlist│redaction│audit│snapshot         │
├─────────────────────────────────────────────────────────┤
│  Services Layer                                         │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────────┐ │
│  │ ops_service  │ │ provider_svc │ │ existing svcs    │ │
│  │ (CRUD draft/ │ │ (adapter     │ │ (file/repo/git/  │ │
│  │  approve/run)│ │  dispatch)   │ │  snapshot/system)│ │
│  └─────────────┘ └──────────────┘ └──────────────────┘ │
├─────────────────────────────────────────────────────────┤
│  Storage (.orch_data/ops/)                              │
│  plans/ │ drafts/ │ approved/ │ runs/ │ provider.json   │
├─────────────────────────────────────────────────────────┤
│  UI (orchestrator_ui)                                   │
│  MaintenanceIsland (existing) + OpsIsland (NEW)         │
├─────────────────────────────────────────────────────────┤
│  MCP Bridge (mcp_ops_server.mjs) — READ-ONLY consumer   │
│  Reads from /ops/* endpoints; exposes resources/prompts │
│  to Antigravity (/orch /sub /editp)                     │
└─────────────────────────────────────────────────────────┘
```

**Modules nuevos** (backend):
- `tools/repo_orchestrator/services/ops_service.py` — CRUD plans/drafts/approved/runs
- `tools/repo_orchestrator/services/provider_service.py` — adapter dispatch
- `tools/repo_orchestrator/providers/` — adapter modules
- `tools/repo_orchestrator/ops_routes.py` — `/ops/*` endpoints
- `tools/repo_orchestrator/ops_models.py` — Pydantic schemas

## 2. Endpoints /ops/*

| Metodo | Ruta                        | Rol min   | Proposito                                  |
|--------|-----------------------------|-----------|---------------------------------------------|
| GET    | /ops/plan                   | actions   | Plan activo (plan.json)                     |
| PUT    | /ops/plan                   | admin     | Crear/actualizar plan activo                |
| GET    | /ops/drafts                 | actions   | Listar drafts pendientes                    |
| POST   | /ops/drafts                 | admin     | Crear draft (Prompt Factory)                |
| GET    | /ops/drafts/{id}            | actions   | Detalle de un draft                         |
| POST   | /ops/drafts/{id}/approve    | admin     | Aprobar draft → mueve a approved/           |
| POST   | /ops/drafts/{id}/reject     | admin     | Rechazar draft (marca rejected)             |
| PUT    | /ops/drafts/{id}            | admin     | Editar draft antes de aprobar               |
| GET    | /ops/approved               | actions   | Listar aprobados pendientes de ejecucion    |
| GET    | /ops/approved/{id}          | actions   | Detalle aprobado (lo que MCP consume)       |
| POST   | /ops/runs                   | admin     | Crear run desde approved_id → dispatch      |
| GET    | /ops/runs                   | actions   | Listar runs (historial)                     |
| GET    | /ops/runs/{run_id}          | actions   | Estado/log de un run                        |
| GET    | /ops/provider               | admin     | Config actual del provider                  |
| PUT    | /ops/provider               | admin     | Cambiar provider activo                     |
| POST   | /ops/generate               | admin     | Pedir al provider que genere un draft       |

Todos heredan: Bearer auth, rate_limit, panic_mode, audit_log, correlation_id.

## 3. Almacenamiento en disco

```
.orch_data/
└── ops/
    ├── plan.json              # Plan activo {id, title, tasks[], status}
    ├── provider.json          # Provider config (ver §4)
    ├── drafts/
    │   ├── d_<ulid>.json      # {id, prompt, context, status: draft|rejected, created_at, provider}
    │   └── ...
    ├── approved/
    │   ├── a_<ulid>.json      # {id, draft_id, prompt, approved_at, approved_by}
    │   └── ...
    └── runs/
        ├── r_<ulid>.json      # {id, approved_id, status: pending|running|done|error, log[], started_at}
        └── ...
```

- Directorio creado en lifespan (como SnapshotService.ensure_snapshot_dir).
- Limpieza: runs > 7 dias se archivan (configurable via `ORCH_OPS_RUN_TTL`).
- Path validado contra BASE_DIR (reutiliza validate_path pattern).

## 4. Provider Adapter Interface

**provider.json** schema minimo:
```json
{
  "active": "local_ollama",
  "providers": {
    "local_ollama": {
      "type": "openai_compat",
      "base_url": "http://localhost:11434/v1",
      "model": "qwen2.5-coder:7b",
      "api_key": null
    },
    "lm_studio": {
      "type": "openai_compat",
      "base_url": "http://localhost:1234/v1",
      "model": "loaded-model",
      "api_key": null
    },
    "gemini": {
      "type": "gemini",
      "api_key": "${GEMINI_API_KEY}",
      "model": "gemini-2.5-pro"
    },
    "openai": {
      "type": "openai_compat",
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-4o",
      "api_key": "${OPENAI_API_KEY}"
    },
    "claude_api": {
      "type": "anthropic",
      "api_key": "${ANTHROPIC_API_KEY}",
      "model": "claude-sonnet-4-5-20250929"
    }
  }
}
```

**Adapter interface** (Python ABC):
```
class ProviderAdapter(ABC):
    async def generate(self, prompt: str, context: dict) -> str
        # Devuelve texto generado (el draft content)
    def health_check(self) -> bool
```

**Adapters concretos** (un archivo cada uno):
- `providers/openai_compat.py` — cubre Ollama, LM Studio, OpenAI (mismo protocolo)
- `providers/gemini.py` — Google Generative AI SDK
- `providers/anthropic.py` — Anthropic SDK

Cambiar provider = editar `provider.json` campo `active` (o `PUT /ops/provider`).

## 5. Approval Gate UI

**Pantalla nueva**: `OpsIsland.tsx` (montada junto a MaintenanceIsland en App.tsx via tabs).

### Vista "Prompt Factory"
- Textarea para prompt manual + boton "Generate via Provider"
- Al generar: POST /ops/generate → crea draft → aparece en Review Panel

### Vista "Review Panel" (tabla/lista)
- Columnas: ID | Prompt (truncado) | Provider | Status | Actions
- Status badges: `DRAFT` (amarillo) | `APPROVED` (verde) | `REJECTED` (rojo)
- Botones por fila:
  - **Approve** (verde) → POST /ops/drafts/{id}/approve
  - **Reject** (rojo) → POST /ops/drafts/{id}/reject
  - **Edit** (azul) → abre modal edicion → PUT /ops/drafts/{id}
  - **View** → expande contenido completo

### Vista "Runs"
- Lista de runs con: run_id | approved_id | status | timestamp
- Status: `PENDING` | `RUNNING` | `DONE` | `ERROR`
- Click en run → log detallado

### Vista "Provider"
- Muestra provider activo
- Dropdown para cambiar (options de provider.json keys)
- Health check indicator

**Hook nuevo**: `useOpsService.ts` (patron identico a useRepoService/useSecurityService).

## 6. MCP Contract

MCP server (`mcp_ops_server.mjs` o equivalente) — bridge HTTP que lee del backend.

### Resources (read-only, Antigravity los consulta)
| URI                        | Devuelve                         | Source              |
|----------------------------|----------------------------------|---------------------|
| ops://plan                 | Plan activo                      | GET /ops/plan       |
| ops://approved             | Lista de aprobados pendientes    | GET /ops/approved   |
| ops://approved/{id}        | Detalle aprobado especifico      | GET /ops/approved/id|
| ops://runs/{id}            | Estado de un run                 | GET /ops/runs/id    |
| ops://context              | Repo activo + status + allowlist | GET /ui/status      |

### Prompts (consumidos por /orch /sub /editp en Antigravity)
| Prompt name    | Input              | Output                          |
|----------------|--------------------|---------------------------------|
| orch_dispatch  | approved_id        | Instruccion formateada para orchestrator task |
| sub_dispatch   | approved_id, agent | Instruccion para sub-agent      |
| editp_dispatch | approved_id, file  | Instruccion para edit-in-place  |

**Regla critica**: prompts SOLO devuelven contenido de `/ops/approved/*`. Si el ID no esta en approved → error. Nunca drafts.

### Tools (MCP tools para que Antigravity ejecute)
| Tool name      | Params          | Accion                           |
|----------------|-----------------|----------------------------------|
| create_run     | approved_id     | POST /ops/runs (crea run)        |
| get_run_status | run_id          | GET /ops/runs/{run_id}           |

## 7. Fases de Implementacion

### Fase 0 — Scaffolding + Storage
**Objetivo**: estructura en disco + modelos + registro de rutas vacio.
**Archivos**:
- NEW: `tools/repo_orchestrator/ops_models.py`
- NEW: `tools/repo_orchestrator/ops_routes.py` (stubs que retornan 501)
- MOD: `tools/repo_orchestrator/main.py` (import + register ops routes, ensure .orch_data/ops/)
- MOD: `tools/repo_orchestrator/config.py` (OPS_DATA_DIR, OPS_RUN_TTL)
- NEW: `.orch_data/ops/provider.json` (template)

**Verificacion**:
```
curl -H "Authorization: Bearer $TOKEN" http://localhost:9325/ops/plan → 501
pytest tests/unit/test_ops_models.py → PASS (schema validation)
```
**GO/NO-GO**: stubs responden 501, modelos validan, server arranca sin regresion.

### Fase 1 — OPS Service CRUD
**Objetivo**: CRUD completo de drafts + plan + approved (sin provider).
**Archivos**:
- NEW: `tools/repo_orchestrator/services/ops_service.py`
- MOD: `tools/repo_orchestrator/ops_routes.py` (implementar GET/POST/PUT drafts, approve, reject, plan)
- NEW: `tests/unit/test_ops_service.py`
- NEW: `tests/unit/test_ops_routes.py`

**Verificacion**:
```
# Crear draft
curl -X POST -H "Authorization: Bearer $TOKEN" -d '{"prompt":"refactor X"}' http://localhost:9325/ops/drafts → 201
# Aprobar
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:9325/ops/drafts/d_xxx/approve → 200
# Verificar approved
curl -H "Authorization: Bearer $TOKEN" http://localhost:9325/ops/approved → [{id, draft_id, ...}]
pytest tests/unit/test_ops_service.py tests/unit/test_ops_routes.py → PASS
```
**GO/NO-GO**: CRUD funcional, audit_log registra todas las ops, role enforcement ok.

### Fase 2 — Provider Layer
**Objetivo**: adapter interface + al menos openai_compat adapter + /ops/generate.
**Archivos**:
- NEW: `tools/repo_orchestrator/providers/__init__.py`
- NEW: `tools/repo_orchestrator/providers/base.py` (ABC)
- NEW: `tools/repo_orchestrator/providers/openai_compat.py`
- NEW: `tools/repo_orchestrator/services/provider_service.py`
- MOD: `tools/repo_orchestrator/ops_routes.py` (implementar /ops/generate, /ops/provider)
- NEW: `tests/unit/test_provider_service.py`

**Verificacion**:
```
# Con LM Studio/Ollama corriendo:
curl -X POST -H "Authorization: Bearer $TOKEN" -d '{"prompt":"analyze this code"}' http://localhost:9325/ops/generate → 201 (draft creado)
# Cambiar provider:
curl -X PUT -H "Authorization: Bearer $TOKEN" -d '{"active":"lm_studio"}' http://localhost:9325/ops/provider → 200
pytest tests/unit/test_provider_service.py → PASS
```
**GO/NO-GO**: generate crea draft, provider switcheable, sin crash si provider offline (graceful error).

### Fase 3 — Runs + Dispatch
**Objetivo**: crear runs desde approved, dispatch real (preparar payload para MCP/Antigravity).
**Archivos**:
- MOD: `tools/repo_orchestrator/services/ops_service.py` (run lifecycle)
- MOD: `tools/repo_orchestrator/ops_routes.py` (POST/GET /ops/runs)
- NEW: `tests/unit/test_ops_runs.py`

**Verificacion**:
```
curl -X POST -H "Authorization: Bearer $TOKEN" -d '{"approved_id":"a_xxx"}' http://localhost:9325/ops/runs → 201 {run_id}
curl -H "Authorization: Bearer $TOKEN" http://localhost:9325/ops/runs/r_xxx → {status, log}
pytest tests/unit/test_ops_runs.py → PASS
```
**GO/NO-GO**: run se crea solo desde approved (403 si draft_id), audit trail completo.

### Fase 4 — UI OpsIsland
**Objetivo**: Review Panel + Prompt Factory + Runs view + Provider selector.
**Archivos**:
- NEW: `tools/orchestrator_ui/src/hooks/useOpsService.ts`
- NEW: `tools/orchestrator_ui/src/islands/ops/OpsIsland.tsx`
- NEW: `tools/orchestrator_ui/src/islands/ops/ReviewPanel.tsx`
- NEW: `tools/orchestrator_ui/src/islands/ops/PromptFactory.tsx`
- NEW: `tools/orchestrator_ui/src/islands/ops/RunsView.tsx`
- MOD: `tools/orchestrator_ui/src/App.tsx` (tabs: Maintenance | OPS)
- MOD: `tools/orchestrator_ui/src/types.ts` (OPS types)

**Verificacion**:
```
cd tools/orchestrator_ui && npm run build && npm run test:coverage → PASS
# Manual: abrir UI, crear draft, approve, ver en approved list
```
**GO/NO-GO**: approve/reject/edit funcional desde UI, draft nunca se ejecuta sin approval.

### Fase 5 — MCP Bridge
**Objetivo**: MCP server que expone resources/prompts/tools leyendo de /ops/*.
**Archivos**:
- NEW: `tools/mcp_ops/server.mjs` (MCP server Node)
- NEW: `tools/mcp_ops/package.json`
- MOD: `docs/OPS_RUNTIME_PLAN_v2.md` (actualizar con config MCP)

**Verificacion**:
```
# MCP resources devuelven approved (nunca drafts)
# /orch prompt con approved_id → instruccion formateada
# /orch prompt con draft_id → ERROR
npx @anthropic/mcp-inspector tools/mcp_ops/server.mjs → resources listados
```
**GO/NO-GO**: MCP solo sirve approved, prompts /orch /sub /editp funcionales.

### Fase 6 — Hardening + OpenAPI + Docs
**Objetivo**: actualizar openapi.yaml, tests e2e, docs.
**Archivos**:
- MOD: `tools/repo_orchestrator/openapi.yaml` (/ops/* paths)
- MOD: `docs/OPERATIONS.md`, `docs/SECURITY.md`
- NEW: `tests/test_ops_e2e.py`

**Verificacion**:
```
python scripts/quality_gates.py → PASS
bandit -c pyproject.toml -r tools → no new findings
pytest tests/ -x → ALL PASS
```
**GO/NO-GO**: quality gates green, zero regresion, openapi actualizado.

---

## CHANGESET

### Archivos nuevos
- `tools/repo_orchestrator/ops_models.py`
- `tools/repo_orchestrator/ops_routes.py`
- `tools/repo_orchestrator/services/ops_service.py`
- `tools/repo_orchestrator/services/provider_service.py`
- `tools/repo_orchestrator/providers/__init__.py`
- `tools/repo_orchestrator/providers/base.py`
- `tools/repo_orchestrator/providers/openai_compat.py`
- `tools/orchestrator_ui/src/hooks/useOpsService.ts`
- `tools/orchestrator_ui/src/islands/ops/OpsIsland.tsx`
- `tools/orchestrator_ui/src/islands/ops/ReviewPanel.tsx`
- `tools/orchestrator_ui/src/islands/ops/PromptFactory.tsx`
- `tools/orchestrator_ui/src/islands/ops/RunsView.tsx`
- `tools/mcp_ops/server.mjs`
- `tools/mcp_ops/package.json`
- `.orch_data/ops/provider.json`
- `tests/unit/test_ops_models.py`
- `tests/unit/test_ops_service.py`
- `tests/unit/test_ops_routes.py`
- `tests/unit/test_ops_runs.py`
- `tests/unit/test_provider_service.py`
- `tests/test_ops_e2e.py`

### Archivos modificados
- `tools/repo_orchestrator/main.py` — register ops routes, ensure ops data dir
- `tools/repo_orchestrator/config.py` — OPS_DATA_DIR, OPS_RUN_TTL
- `tools/repo_orchestrator/openapi.yaml` — /ops/* paths
- `tools/repo_orchestrator/static_app.py` — add "ops/" to api_prefixes
- `tools/orchestrator_ui/src/App.tsx` — tabs Maintenance|OPS
- `tools/orchestrator_ui/src/types.ts` — OPS interfaces
- `docs/OPERATIONS.md` — ops section
- `docs/SECURITY.md` — ops auth section

---

## RISKS

| # | Riesgo | Mitigacion |
|---|--------|------------|
| 1 | Provider offline bloquea /ops/generate | generate es async con timeout 30s; falla → draft con status=error, no bloquea CRUD |
| 2 | Drafts acumulados sin limpiar | Cleanup task (como snapshot_cleanup_loop) borra drafts rejected > 7d |
| 3 | MCP bridge lee datos stale | MCP hace fetch HTTP al backend en cada request; no cache propio; TTL del backend aplica |
| 4 | API keys en provider.json | Variables ${ENV_VAR} resueltas en runtime por provider_service; archivo nunca servido por endpoint (solo /ops/provider devuelve config sin keys) |
| 5 | Race condition approve/reject concurrente | ops_service usa file lock (fcntl/msvcrt) al mutar estado de draft; operacion atomica rename draft→approved |
