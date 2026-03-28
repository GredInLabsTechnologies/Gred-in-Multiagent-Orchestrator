# Status Del Plan Oficial De Migracion: Perfil De Agente + Routing De Nodos + Learning GICS

## Proposito

Este documento no redefine la hoja de ruta.

Sirve como dashboard corto de estado, evidencia y siguiente fase obligatoria
para el plan oficial en:

- `docs/refactor/AGENT_PROFILE_ROUTING_MIGRATION_CANONICAL_PLAN_2026-03-28.md`

## Ledger De Estado

| Fase | Titulo | Estado | Estado real |
|---|---|---|---|
| 0 | Canon del nodo y del routing | `DONE` | Cerrada |
| 1 | Separar `mood` de permisos | `DONE` | Cerrada |
| 2 | Descriptor de tarea y fingerprint | `DONE` | Cerrada |
| 3 | Compilador de constraints | `PARTIAL` | Abierta y siguiente |
| 4 | `ProfileRouter` y binding real | `PARTIAL` | Abierta, bloqueada por F3 |
| 5 | Materializacion correcta de planes y threads | `PARTIAL` | Abierta, bloqueada por F3 |
| 6 | `CustomPlanService` ejecuta perfiles reales | `PARTIAL` | Abierta, bloqueada por F3 |
| 7 | `GraphEngine` y `WorkflowGraph` | `NOT_STARTED` | No iniciada |
| 8 | Learning GICS por fingerprint y perfil | `NOT_STARTED` | No iniciada |
| 9 | Surface parity y catalogo canonico | `NOT_STARTED` | No iniciada |
| 10 | Compatibilidad de datos legacy | `NOT_STARTED` | No iniciada formalmente |
| 11 | Limpieza final | `NOT_STARTED` | No iniciada |

## Lo Que Ya Esta Hecho

### Fase 0

- existen `tools/gimo_server/models/plan.py` y
  `tools/gimo_server/models/agent_routing.py`
- `tools/gimo_server/services/custom_plan_service.py` ya consume el esquema
  desde `models`
- `tools/gimo_server/models/__init__.py` y
  `tools/gimo_server/ops_models.py` exportan el canon

### Fase 1

- existen `tools/gimo_server/services/agent_catalog_service.py` y
  `tools/gimo_server/services/execution_policy_service.py`
- `tools/gimo_server/engine/moods.py` ya es comportamiento, no autoridad de
  permisos
- `tools/gimo_server/engine/tools/executor.py` usa `execution_policy` en los
  caminos productivos
- `tools/gimo_server/services/agentic_loop_service.py` resuelve policy desde
  metadata/preset/catalog antes de compatibilidad legacy
- `tools/gimo_server/services/role_profiles.py` ya no es una autoridad paralela

### Fase 2

- existen `tools/gimo_server/services/task_descriptor_service.py` y
  `tools/gimo_server/services/task_fingerprint_service.py`
- la escritura nueva de `proposed_plan` y de drafts estructurados ya es
  canonica
- `approve`, `modify` y `approve_draft` ya hacen `read-old/write-new`
- `tools/gimo_server/services/plan_graph_builder.py` y lectores MCP aceptan
  shape vieja y canonica

## Lo Que Falta

### Fase 3

- integrar el compilador de constraints con:
  - `runtime_policy_service.py`
  - `intent_classification_service.py`
  - `workspace_policy_service.py`
  - `provider_topology_service.py`
- introducir allowlist real para `binding_mode="runtime"`
- demostrar que ningun ranking o binding posterior rompe el envelope compilado

### Fase 4

- convertir `ProfileRouterService` en router completo constraints-first
- subordinar binding a `ModelRouterService` sin romper constraints
- fijar la function objective explicita:
  `seguridad -> exito -> calidad -> latencia -> coste`
- dejar GICS solo como ajuste advisory

### Fase 5

- cerrar hidratacion lazy de threads legacy
- completar `read-old/write-new` en todos los caminos de persistencia de thread
- retirar el resto de semantica legacy de fase de las surfaces

### Fase 6

- eliminar la dependencia restante del adapter global del orquestador como
  verdad de nodo
- reforzar observabilidad y pruebas de ejecucion con `resolved_profile` real

### Fases 7 a 11

- siguen abiertas conforme al plan oficial
- no deben empezarse antes de cerrar Fase 3

## Evidencia Utilizada

Evidencia estructural revisada:

- existen:
  - `tools/gimo_server/models/plan.py`
  - `tools/gimo_server/models/agent_routing.py`
  - `tools/gimo_server/services/agent_catalog_service.py`
  - `tools/gimo_server/services/execution_policy_service.py`
  - `tools/gimo_server/services/task_descriptor_service.py`
  - `tools/gimo_server/services/task_fingerprint_service.py`
  - `tools/gimo_server/services/constraint_compiler_service.py`
  - `tools/gimo_server/services/profile_router_service.py`
  - `tools/gimo_server/services/profile_binding_service.py`
- no existen todavia:
  - `tools/gimo_server/services/profile_learning_service.py`
  - `tools/gimo_server/routers/ops/agent_profiles_router.py`

Verificacion historica ya registrada para cierres previos:

```powershell
python -m pytest -q `
  tests/test_mood_contracts.py `
  tests/unit/test_agentic_loop.py `
  tests/unit/test_phase2_dogma.py `
  tests/unit/test_file_write.py
```

```powershell
python -m pytest -q `
  tests/unit/test_phase4_ops_routes.py `
  tests/unit/test_routes.py `
  tests/unit/test_phase7.py `
  tests/unit/test_plan_graph_builder.py `
  tests/unit/test_task_descriptor_service.py `
  tests/test_plan_approval.py `
  tests/unit/test_agentic_loop.py
```

Ultimo resultado focal registrado:

- `118 passed`

## Siguiente Fase Obligatoria

La siguiente fase a cerrar es:

- `Fase 3 - Compilador De Constraints`

No debe cerrarse Fase 4, 5, 6, 7, 8, 9, 10 u 11 antes de cerrar Fase 3.

## Regla Para El Siguiente Agente

El siguiente agente debe:

1. leer primero el plan oficial en
   `docs/refactor/AGENT_PROFILE_ROUTING_MIGRATION_CANONICAL_PLAN_2026-03-28.md`
2. usar este archivo solo como dashboard de estado
3. trabajar solo Fase 3
4. detenerse si descubre que Fase 3 depende de reabrir una fase marcada como
   `DONE`
