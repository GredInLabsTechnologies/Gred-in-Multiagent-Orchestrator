# Plan Oficial De Migracion: Perfil De Agente + Routing De Nodos + Learning GICS

## Proposito

Este documento es el plan canonico y el ledger de fases para esta migracion.

No es un resumen libre. Es la referencia que debe seguir cualquier agente que
continue el trabajo.

Regla operativa:

- este documento define el plan oficial y el estado fase por fase
- `docs/refactor/AGENT_PROFILE_ROUTING_MIGRATION_STATUS_2026-03-27.md` es el
  dashboard de estado y evidencia
- no se salta ninguna fase
- el siguiente cierre obligatorio es la Fase 4

## Estado Verificado Del Repo

Estado actual contra este plan oficial:

- Fase 0: `DONE`
- Fase 1: `DONE`
- Fase 2: `DONE`
- Fase 3: `DONE`
- Fase 4: `DONE`
- Fase 5: `DONE`
- Fase 6: `PARTIAL`
- Fase 7: `NOT_STARTED`
- Fase 8: `NOT_STARTED`
- Fase 9: `NOT_STARTED`
- Fase 10: `NOT_STARTED`
- Fase 11: `NOT_STARTED`

Phase lock:

1. No reabrir Fase 0, 1, 2 o 3 salvo evidencia nueva de regresion real.
2. El siguiente cierre obligatorio es Fase 6.
3. Trabajo parcial en fases posteriores no autoriza saltarse Fase 6.

## Resumen

Este programa convierte el sistema actual, basado en strings, defaults
implicitos y semantica perdida, en un runtime con verdad explicita por nodo.

- la superficie publica queda simple con `agent_preset`
- la verdad ejecutiva interna pasa a ser `ResolvedAgentProfile`
- `execution_policy` se convierte en la unica autoridad dura de permisos
- `mood` queda reducido a conducta
- `task_role` define funcion
- `workflow_phase` sustituye el uso incorrecto de `mood` como fase
- GICS aprende sobre tareas reales mediante `task_fingerprint`, no solo sobre
  `model + task_type`

## Objetivo Final

Al terminar la migracion:

- un plan aprobado persiste nodos con `resolved_profile`, `routing_reason`,
  `binding_mode`, `task_fingerprint` y versiones de esquema
- ningun nodo ejecuta con `mood="executor"` por inercia
- ningun nodo ejecuta usando solo el adapter global del orquestador por defecto
- conversacion, plan, graph engine y surfaces externas consumen el mismo
  catalogo
- GICS mejora routing y coste sin tocar seguridad

## Invariantes Del Sistema

- `execution_policy` es la unica autoridad de filesystem, network, shell, HITL,
  budget y post-write checks
- `mood` nunca vuelve a ser fuente de permisos
- `task_role` nunca vuelve a ser fuente de permisos
- `workflow_phase` nunca vuelve a modelarse como `mood`
- `agent_preset` es la abstraccion publica principal
- `resolved_profile` es la verdad ejecutiva del nodo
- el thread no es la verdad principal del nodo
- runtime re-routing nunca amplia policy
- runtime re-routing solo puede cambiar preset/model/provider dentro del sobre
  ya compilado
- GICS nunca anade candidatos invalidos; solo rankea candidatos validos
- debe preservarse el `single-orchestrator invariant`
- todo nodo persistido nuevo debe incluir `routing_schema_version` y
  `profile_schema_version`
- `task_fingerprint` no usa prompt raw completo ni depende de wording
  superficial

## Persistencia vs Derivacion

Persistente:

- `agent_preset`
- `resolved_profile`
- `routing_decision_summary`
- `routing_reason`
- `binding_mode`
- `execution_policy`
- `workflow_phase`
- `task_fingerprint`
- `routing_schema_version`
- `profile_schema_version`

Derivado:

- `candidate lists`
- `score breakdown` detallado
- aliases legacy ya resueltos
- `prompt fragments`
- senales internas de desempate
- evidencias auxiliares de GICS que puedan recomputarse

## Catalogo Inicial Cerrado

- `plan_orchestrator`
- `researcher`
- `executor`
- `reviewer`
- `safety_reviewer`
- `human_gate`

## Fase 0 - Canon Del Nodo Y Del Routing

Estado actual del repo: `DONE`

### Objetivo

- sacar el esquema de nodo/plan del service
- introducir el lenguaje canonico del sistema antes de tocar runtime

### Archivos a crear

- `tools/gimo_server/models/plan.py`
- `tools/gimo_server/models/agent_routing.py`

### Debe contener

`tools/gimo_server/models/plan.py`

- `PlanNode`
- `PlanEdge`
- `CustomPlan`
- `PlanNodeRoutingSummary`
- `PlanNodeBinding`
- `PlanNodeExecutionHints`
- `binding_mode: Literal["plan_time","runtime"]`
- `routing_schema_version`
- `profile_schema_version`

`tools/gimo_server/models/agent_routing.py`

- `TaskRole`
- `MoodName`
- `ExecutionPolicyName`
- `WorkflowPhase`
- `AgentPresetName`
- `TaskDescriptor`
- `TaskConstraints`
- `ResolvedAgentProfile`
- `RoutingDecision`
- `RoutingDecisionSummary`
- `TaskFingerprintParts`

### Archivos a modificar

- `tools/gimo_server/models/__init__.py`
- `tools/gimo_server/ops_models.py`
- `tools/gimo_server/services/custom_plan_service.py`

### Funcionamiento esperado

- el service deja de ser dueno del esquema
- el nodo ya puede alojar binding, routing y versiones
- el comportamiento funcional todavia no cambia

### Criterios de aceptacion

- `CustomPlanService` importa el esquema desde `models/plan.py`
- no quedan definiciones productivas de `PlanNode`, `PlanEdge` o `CustomPlan`
  dentro de `services`
- la suite existente de planes sigue pasando sin cambios de comportamiento

### Hecho en el repo

- `tools/gimo_server/models/plan.py` existe y aloja el esquema canonico de plan
  y nodo
- `tools/gimo_server/models/agent_routing.py` existe y aloja el lenguaje
  canonico de routing
- `tools/gimo_server/services/custom_plan_service.py` ya consume esos modelos
- `tools/gimo_server/models/__init__.py` y `tools/gimo_server/ops_models.py`
  exponen el canon desde `models`

### Falta para cierre

- nada; la fase queda cerrada

## Fase 1 - Separar mood De Permisos

Estado actual del repo: `DONE`

### Objetivo

- extraer toda gobernanza dura fuera de `mood`
- introducir `execution_policy` como autoridad unica

### Archivos a crear

- `tools/gimo_server/services/agent_catalog_service.py`
- `tools/gimo_server/services/execution_policy_service.py`

### Debe contener

`tools/gimo_server/services/agent_catalog_service.py`

- catalogo tipado de roles, moods, policies, phases y presets
- aliases legacy `neutral`, `forensic`, `executor`, `dialoger`, `creative`,
  `guardian`, `mentor`
- prompts base por `task_role` y `workflow_phase`

`tools/gimo_server/services/execution_policy_service.py`

- `ExecutionPolicyProfile`
- enforcement de filesystem, network, shell, tools, HITL, budget y post-write
  hooks
- traduccion legacy desde moods antiguos

### Archivos a modificar

- `tools/gimo_server/engine/moods.py`
- `tools/gimo_server/engine/tools/executor.py`
- `tools/gimo_server/services/agentic_loop_service.py`
- `tools/gimo_server/services/role_profiles.py`

### Que deben contener los cambios

- `moods.py` queda solo con `prompt_prefix`, `temperature`, `response_style`,
  `max_turns`
- `ToolExecutor` deja de leer `mood.contract`
- `agentic_loop_service` deja de resolver presupuesto desde
  `mood_profile.contract`
- el loop conversacional puede funcionar con `execution_policy` aunque el input
  siga entrando como `mood` legacy
- `role_profiles.py` queda como shim minimo hacia
  `execution_policy_service`

### Funcionamiento esperado

- cambiar `mood` no cambia seguridad
- cambiar `execution_policy` si cambia seguridad
- el loop conversacional sigue funcionando durante compatibilidad

### Criterios de aceptacion

- ningun callsite productivo puede leer permisos desde `mood`
- `mood.contract` deja de ser fuente de verdad para red/fs/shell/budget
- el presupuesto por turno sale de policy o de config equivalente, nunca de
  `mood`
- `role_profiles.py` no puede seguir siendo autoridad paralela de permisos

### Hecho en el repo

- `tools/gimo_server/services/agent_catalog_service.py` existe y centraliza
  presets, roles, moods, policies y phases
- `tools/gimo_server/services/execution_policy_service.py` existe y es la
  autoridad de policy
- `tools/gimo_server/engine/moods.py` quedo reducido a conducta
- `tools/gimo_server/engine/tools/executor.py` usa `execution_policy` como
  camino productivo y deja `mood` solo para compatibilidad de borde
- `tools/gimo_server/services/agentic_loop_service.py` resuelve policy desde
  metadata/preset/catalog antes de tocar compatibilidad legacy
- `tools/gimo_server/services/role_profiles.py` ya no es autoridad paralela

### Falta para cierre

- nada para el cierre de Fase 1; la limpieza de shims restantes pertenece a la
  Fase 11

## Fase 2 - Descriptor De Tarea Y Fingerprint

Estado actual del repo: `DONE`

### Objetivo

- normalizar toda task o node a una unidad canonica
- dejar de enrutar sobre strings pobres

### Archivos a crear

- `tools/gimo_server/services/task_descriptor_service.py`
- `tools/gimo_server/services/task_fingerprint_service.py`

### Debe contener

`tools/gimo_server/services/task_descriptor_service.py`

- parser dual para plan estructurado y conversacional
- extraccion de:
  - `task_type`
  - `task_semantic`
  - `artifact_kind`
  - `mutation_mode`
  - `required_tools`
  - `risk_band`
  - `complexity_band`
  - `path_scope`
  - `parallelism_hint`

`tools/gimo_server/services/task_fingerprint_service.py`

- fingerprint estructural estable
- sanitizacion de paths sensibles
- helpers de backoff keys

### Archivos a modificar

- `tools/gimo_server/services/custom_plan_service.py`
- `tools/gimo_server/services/agentic_loop_service.py`

### Funcionamiento esperado

- dos shapes equivalentes producen el mismo descriptor/fingerprint
- ya no se pierde `depends_on`, `model`, `agent_mood` o `rationale` al
  materializar

### Criterios de aceptacion

- `create_plan_from_llm()` ya no usa `role_map` como clasificacion principal
- planes conversacionales y estructurados conservan dependencias y hints
  semanticos
- el fingerprint no usa prompt raw completo

### Hecho en el repo

- `tools/gimo_server/services/task_descriptor_service.py` existe y es el borde
  canonico de ingreso para tareas/planes
- `tools/gimo_server/services/task_fingerprint_service.py` existe y genera el
  fingerprint desde el descriptor, no desde el prompt raw completo
- `tools/gimo_server/services/agentic_loop_service.py`,
  `tools/gimo_server/routers/ops/conversation_router.py`,
  `tools/gimo_server/routers/ops/plan_router.py`,
  `tools/gimo_server/routes.py`,
  `tools/gimo_server/services/ops/_draft.py` y
  `tools/gimo_server/mcp_bridge/native_tools.py` ya hacen escrituras nuevas en
  shape canonica
- `tools/gimo_server/services/plan_graph_builder.py` y lectores MCP aceptan
  shapes old/new

### Falta para cierre

- nada; la fase queda cerrada

## Fase 3 - Compilador De Constraints

Estado actual del repo: `DONE`

### Objetivo

- fijar el envelope duro antes de cualquier ranking

### Archivos a crear

- `tools/gimo_server/services/constraint_compiler_service.py`

### Debe contener

- calculo de constraints desde surface, riesgo, paths, mutation, approvals,
  topology y budget
- allowlist estricta de `binding_mode="runtime"`

### Archivos a modificar

- `tools/gimo_server/services/runtime_policy_service.py`
- `tools/gimo_server/services/intent_classification_service.py`
- `tools/gimo_server/services/workspace_policy_service.py`
- `tools/gimo_server/services/provider_topology_service.py`

### Reglas de binding_mode

- default `plan_time`
- `runtime` solo si el nodo depende de outputs no materializados, gates/HITL o
  topology dinamica justificada
- `runtime` nunca toca `execution_policy`
- `runtime` solo esta permitido en tipos de nodo allowlisted

### Funcionamiento esperado

- ya existe un `candidate envelope` duro por nodo
- ninguna senal posterior puede romperlo

### Criterios de aceptacion

- el compilador siempre corre antes del router
- un nodo con policy `read_only` nunca recibe candidato mutante
- `runtime` queda bloqueado fuera de allowlist

### Hecho en el repo

- `tools/gimo_server/services/constraint_compiler_service.py` existe
- `custom_plan_service.py` ya llama al compilador antes de `ProfileRouterService`
- el default actual de `binding_mode` es `plan_time`
- `ConstraintCompilerService` ya compila el envelope por nodo usando:
  - `RuntimePolicyService` para deny/review duro sobre scope mutante
  - `IntentClassificationService` para escalado de riesgo y core runtime
  - `WorkspacePolicyService` para clamping de `workspace_experiment`
  - `ProviderTopologyService` para el allowlist de bindings provider/model
- `TaskConstraints` ya persiste `allowed_bindings`, surface/workspace y audit
  basica del compilador
- requests invalidos de `workspace_mode` por surface ya no degradan en silencio;
  el compilador falla cerrado con `allowed_policies=[]` y
  `policy_status_code="WORKSPACE_MODE_NOT_ALLOWED"`
- `ProviderTopologyService` ya expone helpers para:
  - resolver bindings validos por descriptor
  - estrechar el envelope ante requests de provider/model sin salir del sobre
- `ProfileRouterService` ya rechaza routing cuando el compilador devuelve
  `allowed_policies=[]`
- `ProfileRouterService` ya no puede devolver un preset mutante cuando el
  envelope compilado solo permite `read_only` o `security_audit`
- `ProfileBindingService` ya clampa `provider`, `model` y `binding_mode` al
  envelope compilado
- `custom_plan_service.py` ya pasa contexto de task al compilador y al binding,
  de forma que el clamp ocurre antes de persistir el nodo
- `conversation_router.py` y `task_descriptor_service.py` ya preservan el
  `context` de plan para que `surface`, `workspace_mode`, `budget` y topology
  lleguen al compilador en approve/modify

### Falta para cierre

- nada; la fase queda cerrada con evidencia en el status doc

## Fase 4 - ProfileRouter Y Binding Real

Estado actual del repo: `DONE`

### Objetivo

- introducir el router canonico: constraints primero, ranking despues, binding
  despues

### Archivos a crear

- `tools/gimo_server/services/profile_router_service.py`
- `tools/gimo_server/services/profile_binding_service.py`

### Debe contener

`tools/gimo_server/services/profile_router_service.py`

- generacion de candidatos por preset
- priors locales `task_semantic -> preset`
- ranking determinista
- hook a GICS como ajuste advisory
- salida `RoutingDecision`

`tools/gimo_server/services/profile_binding_service.py`

- binding de provider/model
- integracion con `ModelRouterService`
- summary persistible del binding

### Archivos a modificar

- `tools/gimo_server/services/model_router_service.py`
- `tools/gimo_server/services/provider_service_impl.py`

### Function objective explicita

Orden de decision:

- seguridad y constraints
- tasa de exito esperada
- calidad minima aceptable
- latencia
- coste

### Funcionamiento esperado

- el sistema puede elegir preset/perfil/modelo con razon auditable
- `ModelRouterService` deja de ser el router semantico principal

### Criterios de aceptacion

- `ConstraintCompiler` filtra antes de cualquier ranking
- `ProfileRouter` no puede anadir candidatos fuera del set valido
- `ProfileBindingService` no puede romper constraints
- GICS solo puede ajustar score

### Hecho en el repo

- `tools/gimo_server/services/profile_router_service.py` existe
- `tools/gimo_server/services/profile_binding_service.py` existe
- `custom_plan_service.py` ya usa ambos servicios para materializar nodos
- el nodo persiste `routing_decision_summary`, `routing_reason` y binding
- `ProfileRouterService` ya genera candidatos por preset solo dentro del set
  permitido por `TaskConstraints`
- `ProfileRouterService` ya aplica priors locales `task_semantic -> preset`,
  ranking determinista y `candidate_count` filtrado, con razon auditable
- el hook advisory de GICS para ranking de preset ya existe y falla honesto a
  `0.0` cuando no hay telemetria de preset en el repo
- `ProfileBindingService` ya subordina provider/model a
  `ModelRouterService.choose_binding_from_candidates(...)` sin salir del
  envelope compilado
- `ProfileBindingService` ya falla cerrado cuando el compilador entrega
  `allowed_bindings=[]`; no puede escapar a topology global
- `ModelRouterService` ya normaliza `task_type` de plan a categorias canonicas
  de routing de modelo
- `ModelRouterService` ya filtra candidatos de binding por capacidad requerida y
  quality floor antes de aplicar topology, latencia o coste
- el ranking de binding ya explicita el orden:
  - constraints
  - success
  - quality
  - latency
  - cost
- el ajuste de GICS ya ocurre solo como score advisory dentro del set de
  candidatos validos; no anade candidatos ni reroutea post-ranking
- `provider_service_impl.py` ya delega el auto-binding a `ModelRouterService`
  y ya no hace reroute post-ranking por fiabilidad
- `provider_service_impl.py` ya preserva `selected_model` explicito y solo
  auto-routea cuando no existe modelo pedido por el caller
- `custom_plan_service.py` ya persiste `provider` y `model` en
  `routing_decision_summary` y agrega la razon de binding al `routing_reason`

### Falta para cierre

- nada; la fase queda cerrada con evidencia en el status doc

## Fase 5 - Materializacion Correcta De Planes Y Threads

Estado actual del repo: `DONE`

### Objetivo

- arreglar el puente entre conversacion, plan generado y plan ejecutable

### Archivos a modificar

- `tools/gimo_server/engine/tools/chat_tools_schema.py`
- `tools/gimo_server/engine/tools/executor.py`
- `tools/gimo_server/services/agentic_loop_service.py`
- `tools/gimo_server/routers/ops/conversation_router.py`
- `tools/gimo_server/models/conversation.py`
- `tools/gimo_server/services/conversation_service.py`

### Que debe quedar en el thread

- `agent_preset` requested/default
- `workflow_phase`
- `profile_summary` opcional
- `proposed_plan`

### Que no debe quedar como verdad principal del thread

- `resolved_profile` autoritativo del nodo
- `task_role` operativo del nodo
- `execution_policy` autoritativa del nodo

### Funcionamiento esperado

- aprobar un `proposed_plan` ya no destruye semantica
- el thread sigue siendo conversacion, no estado operativo detallado

### Criterios de aceptacion

- `mood_transition` deja de ser el mecanismo principal del flujo conversacional
- aprobar plan produce nodos con metadata de routing completa
- rechazar plan solo mueve `workflow_phase` a `planning`

### Hecho en el repo

- el thread ya persiste `agent_preset`, `workflow_phase`, `profile_summary` y
  `proposed_plan`
- `ConversationService` ya hidrata threads legacy en `get/list/mutate/save/fork`
  sin hacer backfill masivo por detras
- `ConversationService` ya reescribe threads mutados en shape nueva con
  `agent_preset`, `profile_summary`, `workflow_phase` honesto y
  `proposed_plan` canonico
- `TaskDescriptorService` ya backfillea `agent_preset` desde `legacy_mood`
  durante canonicalizacion para que el write nuevo no dependa de `mood`
- `agentic_loop_service.py` ya mueve el thread a `awaiting_approval` cuando se
  propone un plan
- aprobar y modificar plan ya preservan la shape canonica del plan y mantienen
  `workflow_phase` coherente con el estado conversacional
- rechazar plan ya no borra `proposed_plan`; solo mueve `workflow_phase` a
  `planning`
- `conversation_router.py` ya registra `plan_approved_at` con timestamp real,
  no placeholder
- `chat_tools_schema.py`, `executor.py` y `mcp_bridge/native_tools.py` ya
  exponen `agent_preset` + `workflow_phase` como contrato conversacional y
  dejan los hints legacy de mood solo en compatibilidad de lectura
- `mcp_bridge/native_tools.py` ya resume el flujo conversacional usando
  `workflow_phase`

### Falta para cierre

- nada; la fase queda cerrada con evidencia en el status doc

## Fase 6 - CustomPlanService Ejecuta Perfiles Reales

Estado actual del repo: `PARTIAL`

### Objetivo

- quitar defaults implicitos y eliminar el adapter global como mentira del nodo

### Archivos a modificar

- `tools/gimo_server/services/custom_plan_service.py`
- `tools/gimo_server/services/agentic_loop_service.py`

### Deuda a abatir explicita

- ningun nodo debe ejecutar usando solo el adapter del orquestador por inercia
- `run_node()` no puede seguir dependiendo de
  `_resolve_orchestrator_adapter()` como fallback principal para plan nodes

### Que debe contener la fase

- nodos persistidos con `resolved_profile`
- `_build_node_prompt()` usando `role + phase + mood`
- `_execute_node()` usando binding real del nodo
- coste y observabilidad etiquetados con profile real

### Funcionamiento esperado

- desaparece `node.config.get("mood", "executor")` como comportamiento normal
- desaparece el adapter global como verdad de ejecucion por nodo

### Criterios de aceptacion

- plan nodes ejecutan con el binding real del nodo
- el model/provider del nodo deja de ser metadata decorativa
- el `resolved_profile` del nodo queda visible en observabilidad

### Hecho en el repo

- los nodos ya persisten `resolved_profile`, `execution_policy`,
  `workflow_phase`, binding y fingerprint
- `custom_plan_service.py` ya ejecuta usando metadata real del nodo en el camino
  normal
- el prompt de nodo ya incorpora contexto de profile

### Falta para cierre

- eliminar la dependencia restante del adapter global como fallback principal
  para plan nodes
- reforzar pruebas y observabilidad para demostrar uso de `resolved_profile`
  en ejecucion

## Fase 7 - GraphEngine Y WorkflowGraph

Estado actual del repo: `NOT_STARTED`

### Objetivo

- llevar el mismo canon al motor de grafos generico

### Archivos a modificar

- `tools/gimo_server/models/workflow.py`
- `tools/gimo_server/services/graph/engine.py`
- `tools/gimo_server/services/graph/node_executor.py`
- `tools/gimo_server/services/graph/agent_patterns.py`

### Funcionamiento esperado

- `CustomPlan` y `WorkflowGraph` comparten semantica de routing
- runtime re-routing solo ocurre en allowlist
- `fan-out` y handoffs usan el mismo router, no roles literales fragiles

### Criterios de aceptacion

- `agent_task` y `llm_call` pueden consumir `resolved_profile`
- children heredados respetan constraints del padre
- ningun branch paralelo puede escapar de envelope seguro

### Hecho en el repo

- solo existe preparacion indirecta por la canonizacion del plan y lectores
  old/new; el runtime de graph no ha sido portado

### Falta para cierre

- toda la fase sigue abierta

## Fase 8 - Learning GICS Por Fingerprint Y Perfil

Estado actual del repo: `NOT_STARTED`

### Objetivo

- ampliar el aprendizaje sin volver el sistema opaco ni inestable

### Archivos a crear

- `tools/gimo_server/services/profile_learning_service.py`

### Debe contener

- write/read de outcomes exactos
- rollups por `task_type`, `task_semantic`, `agent_preset`, `task_role`,
  `execution_policy`
- backoff jerarquico
- utility score compuesto
- fallback degradado local

### Archivos a modificar

- `tools/gimo_server/services/capability_profile_service.py`
- `tools/gimo_server/services/gics_service.py`
- `tools/gimo_server/services/run_worker.py`
- `tools/gimo_server/services/ops/_telemetry.py`
- `tools/gimo_server/services/observability_service.py`

### Namespaces GICS

- `ops:route_exact:{task_fingerprint}:{agent_preset}:{provider}:{model}`
- `ops:route_type:{task_type}:{agent_preset}`
- `ops:route_semantic:{task_semantic}:{agent_preset}`
- `ops:profile_rollup:{task_role}:{execution_policy}`

### Funcionamiento esperado

- GICS aprende que perfil rinde mejor para clases de tarea reales
- coste y latencia se optimizan despues de exito/quality minima

### Criterios de aceptacion

- sin GICS, el router sigue funcionando
- con GICS, el ranking mejora sin alterar constraints
- la funcion objetivo se respeta en este orden: seguridad, exito, calidad,
  latencia, coste

### Hecho en el repo

- no existe `tools/gimo_server/services/profile_learning_service.py`

### Falta para cierre

- toda la fase sigue abierta

## Fase 9 - Surface Parity Y Catalogo Canonico

Estado actual del repo: `NOT_STARTED`

### Objetivo

- exponer el nuevo contrato sin cargar al usuario con internals

### Archivos a crear

- `tools/gimo_server/routers/ops/agent_profiles_router.py`

### Debe contener

- `GET /ops/agents/catalog`
- `POST /ops/agents/resolve`
- catalogo, aliases, presets y summaries

### Archivos a modificar

- `tools/gimo_server/routers/ops/__init__.py`
- `tools/gimo_server/mcp_bridge/native_tools.py`
- `tools/gimo_server/services/skills_service.py`
- `tools/gimo_server/routers/ops/skills_router.py`

### Funcionamiento esperado

- surfaces muestran `preset · role · mood · policy · phase`
- `GET /skills/moods` queda como wrapper deprecated
- ninguna surface reimplementa logica

### Criterios de aceptacion

- web, CLI/TUI, MCP y App muestran el mismo summary
- el catalogo se obtiene del backend, no de heuristicas cliente

### Hecho en el repo

- no existe `tools/gimo_server/routers/ops/agent_profiles_router.py`
- solo hay preparacion parcial en textos MCP, no paridad de surface

### Falta para cierre

- toda la fase sigue abierta

## Fase 10 - Compatibilidad De Datos Legacy

Estado actual del repo: `NOT_STARTED`

### Objetivo

- soportar lectura de datos viejos sin bloquear la migracion
- escribir siempre en el contrato nuevo

### Estrategia

- lectura vieja, escritura nueva
- no hacer migracion masiva upfront
- usar lazy hydration en bordes de carga
- anadir versiones a todo objeto persistido nuevo

### Casos obligatorios a soportar

- leer planes viejos sin `routing_schema_version`
- leer threads viejos con solo `mood`
- leer nodos viejos sin `resolved_profile`
- rehidratar runs antiguos sin metadata nueva

### Comportamiento de compatibilidad

- si un thread viejo solo tiene `mood`, se traduce a `preset/profile summary`
  conversacional al cargar
- si un plan viejo no tiene schema version, se normaliza en memoria y al
  siguiente save se escribe con version nueva
- si un nodo viejo no tiene `resolved_profile`, se usa resolucion transicional
  `plan_time` con defaults explicitos y `routing_reason="legacy_backfill"`
- si un run antiguo se reabre, no se reescribe por detras salvo al persistir un
  cambio real

### Archivos a modificar

- `tools/gimo_server/services/conversation_service.py`
- `tools/gimo_server/services/custom_plan_service.py`
- `tools/gimo_server/services/run_worker.py`

### Criterios de aceptacion

- ningun objeto legacy valido deja de poder abrirse
- todos los nuevos writes salen con esquema nuevo
- no se hace backfill silencioso masivo

### Hecho en el repo

- hay compatibilidad local ya introducida en P1 y P2, pero no existe todavia un
  programa sistematico de compatibilidad legacy a nivel de plan/thread/run

### Falta para cierre

- toda la fase sigue abierta

## Fase 11 - Limpieza Final

Estado actual del repo: `NOT_STARTED`

### Objetivo

- retirar dualidades y shortcuts prohibidos

### Archivos a limpiar

- `tools/gimo_server/services/role_profiles.py`
- partes legacy de `tools/gimo_server/engine/moods.py`
- respuestas, rutas y metadata que sigan hablando de `mood_transition`

### Documentacion a actualizar

- `docs/SYSTEM.md`
- `docs/CLIENT_SURFACES.md`
- `docs/GIMO_GICS_INTEGRATION_SPEC_v1.0.md`

### Criterios de aceptacion

- ya no quedan dos autoridades semanticas vivas
- el runtime no depende de defaults legacy escondidos

### Hecho en el repo

- nada de esta fase puede declararse cerrado todavia

### Falta para cierre

- toda la fase sigue abierta

## Forbidden Shortcuts

- no persistir `candidate lists` completas en nodos o threads
- no dejar `mood` como fallback de permisos temporal mas alla del shim de borde
- no permitir que GICS genere candidatos fuera del envelope de constraints
- no usar seleccion LLM por nodo como router primario
- no dejar `role_profiles.py` como segunda autoridad duradera
- no seguir ejecutando plan nodes con el adapter global del orquestador
- no meter `resolved_profile` autoritativo del nodo como verdad principal del
  thread
- no conservar `mood_transition` como semantica de fase
- no hacer migracion masiva silenciosa de datos legacy
- no aceptar nuevos writes sin `routing_schema_version` y
  `profile_schema_version`

## Matriz De Verificacion Obligatoria

- separar `mood` de `policy` sin regresion funcional
- materializacion correcta de plan estructurado y conversacional
- binding efectivo por nodo
- compatibilidad de lectura legacy
- degraded mode sin GICS
- cross-surface parity
- observabilidad y proofs con profile real
- runtime binding sin ampliacion de policy
- desaparicion del adapter global como verdad de nodo

## Orden Estricto

- Fase 0
- Fase 1
- Fase 2
- Fase 3
- Fase 4
- Fase 5
- Fase 6
- Fase 7
- Fase 8
- Fase 9
- Fase 10
- Fase 11

## Resultado

- UX simple hacia fuera
- runtime explicito hacia dentro
- routing auditable
- policy honesta
- semantica conservada entre surfaces
- aprendizaje util y barato con GICS

## Regla De Handoff

El siguiente agente no debe crear otro roadmap.

Debe:

1. tomar este archivo como plan oficial
2. tomar `docs/refactor/AGENT_PROFILE_ROUTING_MIGRATION_STATUS_2026-03-27.md`
   como dashboard de estado y evidencia
3. empezar por Fase 6
4. detenerse si Fase 6 no puede cerrarse sin reabrir una fase ya marcada como
   `DONE`
