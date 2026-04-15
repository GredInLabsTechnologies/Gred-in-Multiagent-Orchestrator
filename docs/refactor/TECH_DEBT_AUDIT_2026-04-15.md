# Tech Debt Audit - 2026-04-15

## Resumen ejecutivo

Total hallazgos: 47
Por categoría:
- Servicios duplicados/shim: 16
- Routers/endpoints duplicados: 6
- Imports contradictorios: 4
- Componentes frontend huerfanos: 12
- Archivos de servicio sin callers: 5
- Documentacion: 2
- Misc: 2

Top 5 mas graves:
1. ~~Dual ObservabilityService (observability.py vs observability_pkg)~~ — CERRADO 2026-04-15
2. Legacy /ui/* endpoints aun activos - redundancia con /ops/*
3. 16 archivos shim sin deprecation markers
4. AdapterRegistry huerfano (0 callers)
5. Plan/create endpoint sin equivalente /ops/*

## HALLAZGO 1: 16 Servicios relocados a subcarpetas (SHIM RE-EXPORTS)

Archivos afectados (en tools/gimo_server/services/):
- cascade_service.py -> services/economy/cascade_service.py
- cost_service.py -> services/economy/cost_service.py
- cost_predictor.py -> services/economy/cost_predictor.py
- anomaly_detection_service.py -> services/economy/anomaly_detection_service.py
- budget_forecast_service.py -> services/economy/budget_forecast_service.py
- log_rotation_service.py -> services/observability_pkg/log_rotation_service.py
- observability_service.py -> services/observability_pkg/observability_service.py
- run_worker.py -> services/execution/run_worker.py
- execution_policy_service.py -> services/execution/execution_policy_service.py
- engine_service.py -> services/execution/engine_service.py
- repo_service.py -> services/workspace/repo_service.py
- workspace_context_service.py -> services/workspace/workspace_context_service.py
- workspace_policy_service.py -> services/workspace/workspace_policy_service.py
- sandbox_service.py -> services/execution/sandbox_service.py
- repo_override_service.py -> services/workspace/repo_override_service.py
- repo_recon_service.py -> services/workspace/repo_recon_service.py

Cada archivo raiz contiene:
  # {filename}.py - DEPRECATED, use services.{submodule}.{filename}
  from tools.gimo_server.services.{submodule}.{filename} import *

Estado: Shims funcionan correctamente. Callers: main.py, routers siguen usando rutas antiguas via shims.

Clasificacion: ANNOTATE-AND-DEFER
Blast radius: MEDIO (obscurece estructura)
Recomendacion: Anotar con deprecation headers + refactor imports en PR coordinado 2026-06-15

---

## HALLAZGO 2: Dual ObservabilityService implementations — CERRADO 2026-04-15

Estado previo (snapshot del audit): observability.py exponia una clase SIMPLE con
record_llm_usage/record_usage/record_span y agentic_loop_service.py hacia dual-import
contra ambas implementaciones.

Cierre 2026-04-15:
1. observability.py ELIMINADO (era shim de 17 lineas, 0 callers runtime verificados
   via grep en arbol completo: tools/, tests/, gimo_cli/, scripts/).
2. agentic_loop_service.py ya usa un unico sink (UnifiedObservabilityService) —
   el dual-import fue retirado en commits previos; el audit captur\u00f3 un estado
   obsoleto.
3. observability_pkg.ObservabilityService cubre tanto la API legacy
   (record_llm_usage, record_usage, record_agent_action, get_agent_insights,
   record_span, get_metrics, list_traces, record_structured_event) como la
   OTel (record_workflow_start, record_node_span, record_handoff_event,
   get_trace, reset, record_ai_usage).
4. Shim observability_service.py (wildcard re-export desde observability_pkg)
   permanece — 9 callers: engine/stages/llm_execute.py,
   services/graph/engine.py, services/graph/agent_patterns.py,
   services/providers/service_impl.py, services/agentic_loop_service.py,
   routers/ops/observability_router.py, routers/ops/run_router.py,
   tests/unit/test_observability.py, tests/unit/test_observability_preview.py.
   Migracion masiva de esos callers queda bajo Hallazgo 1 (16 shims).

Verificacion: tests/unit/test_observability.py + test_observability_preview.py
ambos verdes (10/10) tras eliminar observability.py.

---

## HALLAZGO 3: Legacy /ui/* endpoints (REDUNDANCIA)

Archivo: tools/gimo_server/routers/legacy_ui_router.py

Rutas duplicadas:
- /ui/hardware -> /ops/hardware (mastery_router.py)
- /ui/audit -> /ops/audit (mesh_router.py)
- /ui/cost/compare -> /ops/cost/compare (config_router.py)
- /ui/drafts/{id}/reject -> /ops/drafts/{id}/reject (plan_router.py) + /ops/action-drafts/{id}/reject (hitl_router.py)
- /ui/plan/create -> NO EXISTE equivalente /ops/*
- /ui/allowlist -> NO EXISTE equivalente /ops/*

EVIDENCIA:
- legacy_ui_router.py lineas 38-197: 6 endpoints respondiendo directamente
- redirects.py lineas 19-36: 17 redirects 308 hacia /ops/* (DIFERENTE estrategia)
- mastery_router.py ~150: @router.get("/hardware")

COMPORTAMIENTO INCONSISTENTE:
- Algunos /ui/* -> 308 redirect (redirects.py)
- Otros /ui/* -> direct response (legacy_ui_router.py)

Clasificacion: KILL CANDIDATE (para covered endpoints) + RECONNECT (para /ui/plan/create, /ui/allowlist)
Blast radius: MEDIO (backward compatibility)
Recomendacion:
1. Migrar legacy_ui_router.py endpoints a 308 redirects (como redirects.py)
2. Para /ui/plan/create y /ui/allowlist: identificar /ops/* canonical o deprecate
3. Deprecate legacy_ui_router.py file entirely

---

## HALLAZGO 4: AdapterRegistry - COMPLETO HUERFANO

Archivo: tools/gimo_server/services/adapter_registry.py

Evidencia:
- Grep "AdapterRegistry" en todo repo: 1 resultado (solo definicion)
- Clase nunca instanciada ni importada

Clasificacion: RECONNECT CANDIDATE (posible codigo intencional pero desconectado)
Blast radius: BAJO
Recomendacion:
1. Grep ProviderAdapter en repo para ver alternativas (probablemente build_provider_adapter)
2. Si reemplazado, marcar como deprecated shim
3. Si aun relevante, conectar a initialization path (main.py, engine.py)

---

## HALLAZGO 5: Componentes React huerfanos (12 hallazgos)

tools/orchestrator_ui/src/components/:
- analytics/AnalyticsView.tsx (0 refs)
- ClusterNode.tsx (0 refs)
- Graph/WorkflowCanvas.tsx (0 refs)
- LiveLogs.tsx (0 refs)
- SkeletonLoader.tsx (0 refs)
- ThreadView.tsx (0 refs)
- __tests__/ (8 test files sin importadores)

Clasificacion: ANNOTATE-AND-DEFER + POSSIBLE DELETE
Blast radius: BAJO (frontend only)
Recomendacion:
1. Check git log para ver si fueron removidos de App.tsx router
2. Si removidos hace >1 mes sin intent restaurar, delete

---

## HALLAZGO 6: Inconsistencia endpoints /reject

Tres variantes:
- /ui/drafts/{id}/reject (legacy_ui_router.py)
- /ops/drafts/{id}/reject (plan_router.py)
- /ops/action-drafts/{id}/reject (hitl_router.py)

PROBLEMA: Tres endpoints para concepto similar, nombres casi identicos.
Probable: tipos distintos de drafts o verdadera duplicata.

Clasificacion: ANNOTATE-AND-DEFER
Recomendacion: Auditar tipos de draft y consolidar nombres

---

## HALLAZGO 7: Config SonarCloud apunta a org INCORRECTA

Archivos con `organization = shiloren`:
- `sonar-project.properties` linea 3: `sonar.organization=shiloren`
- `.sonarlint/connectedMode.json` linea 2: `"sonarCloudOrganization": "shiloren"`

EVIDENCIA:
- Org real del proyecto en SonarCloud: `gredinlabstechnologies` (avatar GH 260796998)
- Org `shiloren` en EU tiene 4 proyectos (GICS, Gred-In-Labs, Semantic-Hub, Locco-Burger), ninguno orchestrator
- Org `gredinlabstechnologies` en EU es donde realmente vive el proyecto del orchestrator
- Comprobado vía API: `https://sonarcloud.io/api/organizations/search?organizations=gredinlabstechnologies` → existe; `?organizations=shiloren` no contiene proyecto orchestrator
- Connected Mode declara region EU pero el componentKey local `Shiloren_gred_orchestrator` no resuelve en API EU bajo org `shiloren`
- Probable causa raiz: proyecto fue migrado de org `shiloren` a `gredinlabstechnologies` y los archivos de config nunca se actualizaron
- Resultado practico: GitHub Actions sube reportes a un slot que no se corresponde con donde el equipo ve los issues, o falla silenciosamente

Clasificacion: KILL CANDIDATE (config obsoleta) + RECONNECT (apuntar a org y key correctos)
Blast radius: MEDIO (CI/CD desincronizado del dashboard real)
Recomendacion:
1. Confirmar componentKey real en SonarCloud UI bajo org `gredinlabstechnologies`
2. Actualizar `sonar-project.properties` -> `sonar.organization=gredinlabstechnologies` + `sonar.projectKey=<key real>`
3. Actualizar `.sonarlint/connectedMode.json` con misma org y key
4. Verificar que `secrets.SONAR_TOKEN` en GitHub tiene scope sobre la nueva org

---

## RESUMEN EJECUCION

Documentacion guardada en: docs/refactor/TECH_DEBT_AUDIT_2026-04-15.md

Hallazgos por severidad:
- KILL CANDIDATE (con reemplazo): 6 hallazgos
- RECONNECT CANDIDATE (huerfanos): 5 hallazgos  
- ANNOTATE-AND-DEFER (mejora futura): 20 hallazgos
- VERIFY (fuera de scope): 5 hallazgos
- OK (sin accion): 6 hallazgos

Blast radius distribution:
- ALTO: 10 hallazgos
- MEDIO: 22 hallazgos
- BAJO: 15 hallazgos

