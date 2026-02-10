#+ OPS v2 Multi‑Agent Trigger — Informe de Decisiones (HISTORICAL — DO NOT USE)

**STATUS**: HISTORICAL (DO NOT USE)
**Reason**: preserved as project history. Not authoritative.
**Authoritative spec**: `docs/GIMO_SYSTEM.md`

Fecha: 2026-02-09
Repo: `gred_orchestrator`

Este documento resume **las decisiones y conclusiones** tomadas en la conversación para que otro agente pueda revisar y preparar la implementación.

---

## 1) Qué “plan.md” era y qué encontramos

### 1.1 No existe `plan.md` en el repo
- Se buscó `plan.md` / `PLAN.md` en el repositorio y **no hay un `plan.md`** propio del repo.

### 1.2 Sí existe `C:\Users\shilo\.ops\PLAN.md` (OPS Runtime v1, fuera del repo)
- Ese `~/.ops/PLAN.md` describe el **OPS Runtime v1**: Node + CLI (`ops.mjs`) + MCP stdio (`mcp-server.mjs`) + `protocol/*.md` + `plans/active.md` + `state.json`.
- Conclusión: **v1 está implementado y operativo** (archivos presentes y CLI valida el `sample-plan.md`).

### 1.3 En el repo existe OPS Runtime v2 (documentación)
- `docs/history/OPS_RUNTIME_PLAN_v2.md`: diseño/arquitectura del runtime v2 embebido en el orquestador.
- `docs/history/OPS_IMPLEMENTATION_CHECKLIST.md`: **la misma v2** pero en formato checklist GO/NO‑GO.

**Decisión:** Para lo que se busca (disparador multiagente para ChatGPT Actions y operadores variados), el camino es **OPS Runtime v2 (HTTP/OpenAPI)**. El v1 se mantiene como runtime local para Antigravity/MCP si se desea, pero no es la base del disparador para Actions.

---

## 2) Objetivo funcional acordado

### 2.1 Objetivo principal
“Establecer un disparador multiagente en el orquestador para que ChatGPT Actions pueda trabajar con ellos”.

### 2.2 Aclaración clave
No se quiere que el disparo dependa de “ChatGPT Actions” como actor único.

**Decisión:** El sistema debe ser **agnóstico al operador**:
- Operador puede ser: ChatGPT Actions, UI del repo, Antigravity, script CLI, etc.
- La interfaz común es **HTTP (FastAPI)**.

---

## 3) Arquitectura elegida (v2)

### 3.1 v2 = FastAPI + storage + UI + provider adapters
El “cerebro” (estado + persistencia) vive en el orquestador:
- Endpoints `GET/PUT/POST /ops/*`
- Persistencia en `.orch_data/ops/` (`plan.json`, `drafts/`, `approved/`, `runs/`, `provider.json`).
- UI `tools/orchestrator_ui` consume `/ops/*`.
- “Provider” = adaptador de LLM para generar drafts (`/ops/generate`).

### 3.2 El provider NO es el operador
**Decisión:**
- Provider se usa para generación de texto (drafts) y/o ejecución en el futuro.
- Operador es quien llama la API (Actions/UI/otros). Ambos son independientes.

---

## 4) Modelo de seguridad / roles

### 4.1 Estado actual del repo (ya implementado)
- Auth por Bearer token.
- Dos roles derivan del token:
  - `actions` (read-only)
  - `admin` (mutaciones)

Detalles relevantes:
- En `tools/repo_orchestrator/security/auth.py`:
  - `role = "actions" if token == ORCH_ACTIONS_TOKEN else "admin"`
- En `tools/repo_orchestrator/routes.py`:
  - El token `actions` se restringe por allowlist a endpoints read-only.
  - Incluye lectura de OPS v2: `/ops/plan`, `/ops/drafts`, `/ops/approved`, `/ops/runs` (y sus subrutas GET).
- En `tools/repo_orchestrator/ops_routes.py`:
  - `POST/PUT` requieren admin.
  - `GET` permite actions.

### 4.2 Decisión propuesta (aún por confirmar)
Se sugirió introducir un rol/token intermedio:
- `operator`: puede aprobar y crear runs, pero no cambiar provider config.

Esto facilitaría que “cualquier operador” dispare ejecución sin dar privilegios de admin.

**Estado:** Propuesto, no confirmado.

---

## 5) Ejecución: “a veces automático, a veces manual”

El usuario confirmó que el comportamiento deseado es **híbrido**:
- A veces: aprobar → ejecutar automáticamente.
- A veces: aprobar → NO ejecutar; luego alguien decide ejecutar.

### Decisión de diseño
Implementar “modo híbrido” en v2:
- Añadir un flag simple en la aprobación:
  - `auto_run=true|false`
- Y opcionalmente un default global (por plan o configuración):
  - `default_auto_run`.

Efecto:
- `auto_run=true`: `approve` crea approved y además crea un run.
- `auto_run=false`: solo crea approved.

**Estado:** Decidido a nivel de diseño; pendiente de implementación.

---

## 6) Estado actual de implementación v2 (inventario rápido)

### 6.1 Backend (presentes)
- `tools/repo_orchestrator/ops_models.py` (OpsPlan, OpsDraft, OpsApproved, OpsRun, ProviderConfig).
- `tools/repo_orchestrator/services/ops_service.py` (CRUD file-backed para plan/drafts/approved/runs + cleanup runs).
- `tools/repo_orchestrator/services/provider_service.py` (provider.json, adapter openai_compat, generate, health_check).
- `tools/repo_orchestrator/providers/openai_compat.py` (chat/completions + models).
- `tools/repo_orchestrator/ops_routes.py` (endpoints `/ops/*`).
- `tools/repo_orchestrator/main.py` incluye el router OPS y crea dirs en lifespan.

### 6.2 UI (presentes)
- `tools/orchestrator_ui/src/hooks/useOpsService.ts` (consume `/ops/*`).
- `tools/orchestrator_ui/src/islands/system/OpsIsland.tsx` existe (vista OPS).

### 6.3 MCP bridge v2 (ausente)
- No se encontró implementación de `tools/mcp_ops/server.mjs` ni prompts `orch_dispatch/sub_dispatch/editp_dispatch`.

### 6.4 OpenAPI (incompleto para Actions)
- `tools/repo_orchestrator/openapi.yaml` **no incluye `/ops/*`**.

---

## 7) Implicaciones para ChatGPT Actions

**Decisión:** ChatGPT Actions debe integrarse contra HTTP/OpenAPI del orquestador (v2).

Pendiente:
- Añadir `/ops/*` a OpenAPI o exponer un OpenAPI específico para Actions.
- Definir qué token usa Actions:
  - recomendado por defecto: `actions` (read-only) para minimizar riesgo.
  - si Actions necesita ejecutar (crear run), usar `operator` o endpoint muy acotado.

---

## 8) Próximos pasos recomendados (para el agente que implementa)

1) **Inventario completo v2 vs checklist** (`docs/history/OPS_IMPLEMENTATION_CHECKLIST.md`):
   - Marcar qué items ya están implementados.
   - Identificar gaps reales (OpenAPI, MCP bridge, tests e2e, auto_run, role operator).

2) **OpenAPI**:
   - Añadir rutas `/ops/*` a `tools/repo_orchestrator/openapi.yaml`.
   - Verificar que el schema sea consumible por ChatGPT Actions.

3) **Modelo híbrido auto/manual**:
   - Implementar `auto_run` en `POST /ops/drafts/{id}/approve` (o endpoint nuevo) y default global.

4) **Roles/tokens** (opcional pero recomendado):
   - Añadir token `operator` + enforcement.

5) **MCP bridge v2** (opcional):
   - Implementar `tools/mcp_ops/server.mjs` read-only y prompts basados SOLO en `/ops/approved/*`.

6) **Tests**:
   - Añadir tests unit/e2e del flujo: generate → approve(auto/no) → runs.

---

## 9) Notas de compatibilidad / guardarraíles

- Mantener “approval gate”: **nunca ejecutar drafts**, solo approved.
- Provider config nunca debe exponer `api_key` (ya está redacted en `get_public_config`).
- Conservar auditoría (`audit_log`) en mutaciones OPS.
