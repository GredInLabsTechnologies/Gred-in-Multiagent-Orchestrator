# GraphEngine v2 — Production Checklist

> **Objetivo**: Igualar y superar LangGraph con inteligencia incremental via GICS.
> **Fecha**: 2026-03-23
> **Estado**: En ejecución

---

## Fase 1: State Reducers + GICS Learning

### Implementación
- [ ] Crear `tools/gimo_server/services/graph/state_manager.py`
  - [ ] Clase `StateManager`
  - [ ] Método `apply_update(current_state, update, reducers)`
  - [ ] Reducers: `overwrite` (default), `append`, `add`, `max`, `min`, `merge_dict`, `dedupe_append`
  - [ ] Método `_detect_conflict(current, key, new_value)` para GICS learning
- [ ] Modificar `tools/gimo_server/models/workflow.py`
  - [ ] Campo `reducers` en `WorkflowGraph.state_schema` (backward compatible)
- [ ] Modificar `tools/gimo_server/services/graph/engine.py`
  - [ ] Reemplazar `self.state.data.update(output)` por `self._apply_state_update(output)`
  - [ ] Instanciar `StateManager` en `__init__`
- [ ] GICS: registrar conflictos en `ops:reducer_conflict:{workflow_id}:{key}`

### Tests
- [ ] Test: reducer `append` concatena listas de ramas paralelas
- [ ] Test: reducer `add` suma números
- [ ] Test: reducer `overwrite` es default (backward compat)
- [ ] Test: reducer `merge_dict` hace deep merge
- [ ] Test: reducer `dedupe_append` no duplica
- [ ] Test: todos los tests existentes de `test_graph_engine.py` siguen pasando

### Validación
- [ ] `pytest tests/unit/test_graph_engine.py -x -v` — 0 failures
- [ ] 62 tests de governance siguen pasando

---

## Fase 2: Command (goto + state update atómico)

### Implementación
- [ ] Añadir a `tools/gimo_server/models/workflow.py`
  - [ ] Clase `GraphCommand(BaseModel)` — goto, update, send (placeholder), graph
  - [ ] Helper `is_graph_command(output)` para detección
- [ ] Modificar `tools/gimo_server/services/graph/engine.py`
  - [ ] En `execute()` loop: detectar GraphCommand en output
  - [ ] Aplicar `command.update` via StateManager
  - [ ] Override `_get_next_node` con `command.goto`
  - [ ] Soportar `command.goto` como lista (multiple targets → error si >1 sin Send)
  - [ ] Soportar `command.graph == "PARENT"` para escape de subgraph
- [ ] GICS: registrar en `ops:command_trace:{workflow_id}`

### Tests
- [ ] Test: nodo retorna Command con goto override
- [ ] Test: Command con goto + update atómico
- [ ] Test: Command con goto sin update
- [ ] Test: escape de subgraph con graph="PARENT"
- [ ] Test: backward compat — nodos sin Command siguen funcionando
- [ ] Test: todos los tests existentes siguen pasando

### Validación
- [ ] `pytest tests/unit/test_graph_engine.py -x -v` — 0 failures

---

## Fase 3: Send (Map-Reduce dinámico)

### Implementación
- [ ] Añadir a `tools/gimo_server/models/workflow.py`
  - [ ] Clase `SendAction(BaseModel)` — node, state
- [ ] Crear `tools/gimo_server/services/graph/map_reduce.py`
  - [ ] Clase `MapReduceMixin`
  - [ ] Método `_execute_send_actions(sends, reducers, budget)`
  - [ ] Semaphore para limitar parallelism
  - [ ] Budget distribuido: `total_budget / len(sends)` por instancia
  - [ ] Execution proof por cada instancia
- [ ] Integrar en `engine.py`: si Command tiene `send`, ejecutar map-reduce
- [ ] GICS: registrar en `ops:send_stats:{workflow_id}:{node_id}`

### Tests
- [ ] Test: map-reduce con 5 instancias, reducer `append`
- [ ] Test: map-reduce con reducer `add` suma scores
- [ ] Test: semaphore limita parallelism
- [ ] Test: budget se distribuye correctamente
- [ ] Test: fallo de una instancia no mata las demás (`return_exceptions=True`)

### Validación
- [ ] `pytest tests/unit/test_graph_engine.py -x -v` — 0 failures

---

## Fase 4: Ciclos declarativos

### Implementación
- [ ] Modificar `tools/gimo_server/models/workflow.py`
  - [ ] Campo `max_iterations: Optional[int]` en `WorkflowEdge`
  - [ ] Campo `break_condition: Optional[str]` en `WorkflowEdge`
- [ ] Modificar `tools/gimo_server/services/graph/engine.py`
  - [ ] `_detect_cycles()` en `__init__` — identifica ciclos con DFS
  - [ ] Contadores por ciclo en `state.data["_cycle_counters"]`
  - [ ] En `_get_next_node`: evaluar `break_condition`, respetar `max_iterations`
- [ ] Modificar `tools/gimo_server/services/graph/checkpoint_manager.py`
  - [ ] `_evaluate_condition` ya existe — reutilizar para `break_condition`
- [ ] GICS: registrar en `ops:cycle_stats:{workflow_id}:{edge_id}`

### Tests
- [ ] Test: loop A→B→A con break_condition
- [ ] Test: loop con max_iterations que sale al nodo C
- [ ] Test: nested loops (loop dentro de loop)
- [ ] Test: ciclo sin break_condition respeta max_iterations global
- [ ] Test: backward compat — self-loop existente sigue funcionando

### Validación
- [ ] `pytest tests/unit/test_graph_engine.py -x -v` — 0 failures

---

## Fase 5: Time-Travel (Replay + Fork)

### Implementación
- [ ] Crear `tools/gimo_server/services/graph/time_travel.py`
  - [ ] Clase `TimeTravelMixin`
  - [ ] `replay_from_checkpoint(checkpoint_index)` — re-ejecuta desde checkpoint
  - [ ] `fork_from_checkpoint(checkpoint_index, state_patch)` — nueva rama
  - [ ] `get_checkpoint_timeline()` — lista navegable
- [ ] Modificar `tools/gimo_server/models/workflow.py`
  - [ ] Campos en `WorkflowCheckpoint`: `parent_checkpoint_id`, `fork_id`, `replayed`
- [ ] Modificar `tools/gimo_server/services/graph/checkpoint_manager.py`
  - [ ] Extender persist/restore para nuevos campos
- [ ] Fork hereda cadena de execution proofs
- [ ] Endpoint: `POST /ops/workflows/{id}/time-travel` en graph_router
- [ ] GICS: registrar en `ops:fork_outcomes:{workflow_id}:{checkpoint_index}`

### Tests
- [ ] Test: replay re-ejecuta nodos desde checkpoint
- [ ] Test: fork crea GraphEngine independiente con state editado
- [ ] Test: fork hereda checkpoints anteriores
- [ ] Test: timeline muestra todos los checkpoints
- [ ] Test: backward compat — resume_from_checkpoint sigue funcionando

### Validación
- [ ] `pytest tests/unit/test_graph_engine.py -x -v` — 0 failures

---

## Fase 6: Swarm (handoff descentralizado)

### Implementación
- [ ] Crear `tools/gimo_server/services/graph/swarm.py`
  - [ ] Clase `SwarmMixin`
  - [ ] `_run_swarm(node)` — loop de ejecución descentralizado
  - [ ] `active_agent` en state
  - [ ] Handoff tools generados dinámicamente por agente
  - [ ] Execution proof por cada handoff
- [ ] Añadir a `tools/gimo_server/models/workflow.py`
  - [ ] Clase `SwarmAgent(BaseModel)` — id, name, instructions, tools, handoff_targets, mood
- [ ] Modificar `tools/gimo_server/services/graph/agent_patterns.py`
  - [ ] Integrar pattern `"swarm"` en `_run_agent_task`
- [ ] MoodContracts por agente
- [ ] GICS: registrar en `ops:handoff_stats:{agent_from}:{agent_to}`
- [ ] Reutilizar `CapabilityProfileService.recommend_model_for_task()` para routing inteligente

### Tests
- [ ] Test: swarm con 3 agentes, handoff A→B→C
- [ ] Test: handoff con context filtering
- [ ] Test: max_iterations respetado en swarm loop
- [ ] Test: MoodContract enforcement por agente
- [ ] Test: backward compat — otros patterns siguen funcionando

### Validación
- [ ] `pytest tests/unit/test_graph_engine.py -x -v` — 0 failures

---

## Fase 7: Graph Streaming + Observability

### Implementación
- [ ] Modificar `tools/gimo_server/services/graph/engine.py`
  - [ ] Método `async execute_stream(initial_state)` — async generator de eventos
  - [ ] Eventos: `node_start`, `node_end`, `state_update`, `checkpoint`, `command`, `send_map`, `send_reduce`, `cycle_iteration`, `handoff`, `error`, `done`
  - [ ] Cada evento: `{event_type, node_id, timestamp, data, duration_ms}`
- [ ] Modificar `tools/gimo_server/routers/ops/graph_router.py`
  - [ ] Endpoint SSE: `POST /ops/workflows/{id}/execute/stream`
- [ ] GICS: métricas en `ops:stream_metrics:{workflow_id}`

### Tests
- [ ] Test: stream emite eventos para ejecución lineal
- [ ] Test: stream emite eventos para branching
- [ ] Test: stream emite cycle_iteration para loops
- [ ] Test: stream emite send_map/send_reduce para map-reduce
- [ ] Test: backward compat — execute() sigue funcionando sin stream

### Validación
- [ ] `pytest tests/unit/test_graph_engine.py -x -v` — 0 failures
- [ ] 62 tests de governance siguen pasando
- [ ] Full test suite no introduce regresiones

---

## Innovaciones vs LangGraph

| GIMO | LangGraph |
|---|---|
| Reducers extensibles (7 tipos) | Solo operator.add y custom |
| Command con escape de subgraph | Paridad |
| Send con MoodContracts heredados | No tiene moods |
| Send con budget distribuido | No tiene budget nativo |
| Send con execution proofs | No tiene proofs |
| Ciclos con break_condition | Solo conditional edges |
| Ciclos con max_iterations por edge | Solo global max |
| Time-travel con proof chain | No tiene proofs |
| Fork con herencia de proofs | No tiene proofs |
| Swarm con MoodContracts | No tiene governance por agente |
| Swarm con approval cross-mood | No tiene governance |
| GICS aprende de cada ejecucion | No aprende |
| Hardware-aware routing | No tiene |
| Cascade (modelo barato primero) | No tiene |
| Contract checks con rollback | No tiene |
| Confidence/doubt proactivo | No tiene |
