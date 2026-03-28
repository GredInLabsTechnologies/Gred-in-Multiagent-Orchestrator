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
| 3 | Compilador de constraints | `DONE` | Cerrada |
| 4 | `ProfileRouter` y binding real | `DONE` | Cerrada |
| 5 | Materializacion correcta de planes y threads | `DONE` | Cerrada |
| 6 | `CustomPlanService` ejecuta perfiles reales | `PARTIAL` | Abierta y siguiente |
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

### Fase 3

- `ConstraintCompilerService` ya compila un envelope duro por nodo usando
  runtime policy, intent classification, workspace policy y topology
- requests invalidos de `workspace_mode` por surface ya fallan cerrado; no hay
  degradacion silenciosa a defaults
- `TaskConstraints` ya conserva `allowed_bindings`, surface/workspace y notas
  de compilacion
- `ProfileRouterService` ya falla cerrado cuando el compilador devuelve
  `allowed_policies=[]`
- `ProfileRouterService` ya no puede emitir `executor` si el envelope compilado
  solo permite politicas de lectura
- `ProfileBindingService` ya no puede elegir `provider`, `model` o
  `binding_mode` fuera del envelope compilado
- la allowlist real de `binding_mode="runtime"` ya existe y esta probada
- `TaskDescriptorService`, `conversation_router.py` y
  `custom_plan_service.py` ya preservan y propagan el `context` del plan hasta
  la compilacion por nodo

### Fase 4

- `ProfileRouterService` ya hace ranking constraints-first sobre candidatos de
  preset validos
- `ProfileRouterService` ya usa priors locales `task_semantic -> preset` y
  emite razon auditable con `candidate_count` filtrado
- `ProfileBindingService` ya subordina provider/model a
  `ModelRouterService` sin salir del envelope compilado
- `ProfileBindingService` ya falla cerrado cuando el compilador devuelve
  `allowed_bindings=[]`; no puede escapar a topology
- `ModelRouterService` ya fija orden explicito de decision para binding:
  `constraints -> success -> quality -> latency -> cost`
- `ModelRouterService` ya filtra por capacidad requerida y quality floor antes
  de aplicar topology, latencia o coste
- GICS ya solo ajusta score dentro del set valido y no reroutea despues del
  ranking
- `provider_service_impl.py` ya usa `ModelRouterService` para auto-binding
- `provider_service_impl.py` ya preserva `selected_model` explicito y no lo
  sobreescribe con auto-routing
- `custom_plan_service.py` ya persiste `provider` y `model` en
  `routing_decision_summary` y concatena la razon de binding al `routing_reason`

### Fase 5

- `ConversationService` ya hidrata threads legacy en `get`, `list`, `mutate`,
  `save` y `fork` sin migracion masiva silenciosa
- el shape canonico del thread ya se reescribe en el siguiente cambio real con
  `agent_preset`, `profile_summary`, `workflow_phase` honesto y
  `proposed_plan` canonico
- `TaskDescriptorService` ya rellena `agent_preset` desde `legacy_mood` para
  completar `read-old/write-new` en planes conversacionales
- `agentic_loop_service.py` ya mueve threads con plan propuesto a
  `awaiting_approval`
- `conversation_router.py` ya conserva `proposed_plan` al rechazar y solo mueve
  `workflow_phase` a `planning`
- `conversation_router.py` ya escribe `plan_approved_at` con timestamp real
- `chat_tools_schema.py`, `executor.py` y `mcp_bridge/native_tools.py` ya
  presentan `agent_preset` y `workflow_phase` como contrato conversacional
  primario; los hints legacy de mood quedan solo como compatibilidad de lectura

## Lo Que Falta

### Fase 4

- nada; cerrada con evidencia abajo

### Fase 6

- eliminar la dependencia restante del adapter global del orquestador como
  verdad de nodo
- reforzar observabilidad y pruebas de ejecucion con `resolved_profile` real

### Fases 7 a 11

- siguen abiertas conforme al plan oficial
- no deben cerrarse antes de cerrar Fase 5

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

Verificacion nueva ejecutada para el cierre de Fase 3:

```powershell
python -m pytest -q `
  tests/unit/test_constraint_compiler_service.py `
  tests/unit/test_profile_router_service.py `
  tests/unit/test_task_descriptor_service.py `
  tests/test_plan_approval.py `
  tests/unit/test_provider_topology_service.py `
  tests/unit/test_runtime_policy_service.py `
  tests/unit/test_workspace_policy.py
```

Resultado:

- `44 passed`

Cobertura de cierre de Fase 3 demostrada:

- `ConstraintCompilerService` ya usa `RuntimePolicyService`,
  `IntentClassificationService`, `WorkspacePolicyService` y
  `ProviderTopologyService`
- `workspace_mode` invalido para la surface ya se rechaza con fail-closed
- `runtime` queda bloqueado fuera del allowlist y probado
- `ProfileRouterService` ya rechaza `allowed_policies=[]`
- `ProfileRouterService` ya rebaja presets incompatibles al primer preset
  compatible con el envelope compilado
- `ProfileBindingService` ya no puede salir del allowlist de bindings
- `surface`, `workspace_mode`, `budget` y topology a nivel de plan ya llegan al
  compilador durante `approve` y `modify`

Verificacion de no regresion sobre flows de plan:

```powershell
python -m pytest -q `
  tests/unit/test_phase4_ops_routes.py `
  tests/unit/test_routes.py `
  tests/unit/test_plan_graph_builder.py `
  tests/test_plan_approval.py
```

Resultado:

- `71 passed`

Verificacion nueva ejecutada para el cierre de Fase 4:

```powershell
python -m pytest -q `
  tests/unit/test_constraint_compiler_service.py `
  tests/unit/test_profile_router_service.py `
  tests/unit/test_profile_binding_service.py `
  tests/unit/test_task_descriptor_service.py `
  tests/test_plan_approval.py `
  tests/unit/test_phase4_ops_routes.py `
  tests/unit/test_routes.py `
  tests/unit/test_plan_graph_builder.py `
  tests/unit/test_services.py `
  tests/unit/test_adapters.py
```

Resultado:

- `144 passed, 1 skipped`

Cobertura de cierre de Fase 4 demostrada:

- `ProfileRouterService` ya rankea solo presets compatibles con
  `TaskConstraints`
- `ProfileBindingService` ya delega provider/model a
  `ModelRouterService.choose_binding_from_candidates(...)`
- `ProfileBindingService` ya falla cerrado con `allowed_bindings=[]`
- el objective ordering de binding ya es explicito y auditable:
  `constraints -> success -> quality -> latency -> cost`
- `ModelRouterService` ya hace gating por capacidad requerida y quality floor
  antes de scorear latencia/coste
- GICS ya solo ajusta score dentro del set valido y no puede ampliar
  candidatos
- `provider_service_impl.py` ya no hace reroute post-ranking por fiabilidad
- `provider_service_impl.py` ya preserva `selected_model` explicito
- `custom_plan_service.py` ya persiste `provider` y `model` en el summary de
  routing del nodo

Verificacion nueva ejecutada para el cierre de Fase 5:

```powershell
python -m pytest -q `
  tests/test_conversational_flow.py `
  tests/test_plan_approval.py `
  tests/test_meta_tools.py `
  tests/unit/test_agentic_loop.py `
  tests/unit/test_task_descriptor_service.py `
  tests/unit/test_chat_tools.py
```

Resultado:

- `77 passed`

Verificacion minima compartida de no regresion:

```powershell
python -m pytest -q `
  tests/unit/test_phase4_ops_routes.py `
  tests/unit/test_routes.py `
  tests/unit/test_plan_graph_builder.py `
  tests/test_plan_approval.py
```

Resultado:

- `71 passed`

Cobertura de cierre de Fase 5 demostrada:

- `ConversationService` ya hidrata threads legacy en lectura y preserva el
  shape canonico en el siguiente write real
- `list_threads()` ya usa la misma carga/hidratacion que `get_thread()`
- `fork_thread()` ya preserva metadata conversacional, plan propuesto y summary
  sin compartir referencias mutables
- el flujo `plan_proposed -> awaiting_approval -> approve/modify/reject` ya usa
  `workflow_phase` como verdad conversacional
- `reject` ya no destruye `proposed_plan`
- el contrato de `propose_plan` ya escribe `agent_preset` aun cuando el input
  llegue con `agent_mood` o `mood` legacy
- la surface MCP ya deja de resumir threads como `Mood: ...` y usa
  `Preset + Workflow phase`

## Siguiente Fase Obligatoria

La siguiente fase a cerrar es:

- `Fase 6 - CustomPlanService ejecuta perfiles reales`

No debe cerrarse Fase 7, 8, 9, 10 u 11 antes de cerrar Fase 6.

## Regla Para El Siguiente Agente

El siguiente agente debe:

1. leer primero el plan oficial en
   `docs/refactor/AGENT_PROFILE_ROUTING_MIGRATION_CANONICAL_PLAN_2026-03-28.md`
2. usar este archivo solo como dashboard de estado
3. trabajar solo Fase 6
4. detenerse si descubre que Fase 6 depende de reabrir una fase marcada como
   `DONE`
