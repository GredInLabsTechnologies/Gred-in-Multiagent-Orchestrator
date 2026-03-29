# Status Del Plan Oficial De Migracion: Perfil De Agente + Routing De Nodos + Learning GICS

**Actualizado:** 2026-03-29
**Auditoría:** Revisión code-by-code completa del estado real del repositorio

## Proposito

Este documento sirve como dashboard actualizado de estado real vs documentado, evidencia y cierre de gaps.

Referencia al plan oficial en:
- `docs/refactor/AGENT_PROFILE_ROUTING_MIGRATION_CANONICAL_PLAN_2026-03-28.md`

## ⚠️ HALLAZGO CRÍTICO

**La documentación estaba desactualizada.** El código tiene **P1-P10 COMPLETAMENTE IMPLEMENTADAS** con tests, servicios y ejecución funcional. No solo "documentadas" sino en producción.

## Ledger De Estado (ACTUALIZADO)

| Fase | Titulo | Estado Doc | Estado Real | Evidencia |
|------|--------|------------|-------------|-----------|
| 0 | Canon del nodo y del routing | `DONE` | ✅ **DONE** | models/plan.py, agent_routing.py |
| 1 | Separar `mood` de permisos | `DONE` | ✅ **DONE** | ExecutionPolicyService, tests/test_phase1.py |
| 2 | Descriptor de tarea y fingerprint | `DONE` | ✅ **DONE** | TaskDescriptorService, tests/test_phase2*.py |
| 3 | Compilador de constraints | `DONE` | ✅ **DONE** | ConstraintCompilerService, tests/test_phase3*.py |
| 4 | `ProfileRouter` y binding real | `DONE` | ✅ **DONE** | ProfileRouterService (18 tests) |
| 5 | Materializacion correcta de planes y threads | `DONE` | ✅ **DONE** | ConversationService, tests/test_phase_5*.py |
| 6 | `CustomPlanService` ejecuta perfiles reales | `PARTIAL` | ✅ **DONE** | CustomPlanService integrado con routing |
| 7 | `GraphEngine` y `WorkflowGraph` | `NOT_STARTED` | ✅ **DONE** | GraphEngine.execute(), NodeExecutorMixin |
| 8 | Learning GICS por fingerprint y perfil | `NOT_STARTED` | ✅ **DONE** | AdvisoryEngine (F8.2), PresetTelemetryService |
| 9 | Surface parity y catalogo canonico | `NOT_STARTED` | ✅ **DONE** | AnomalyDetectionService, auto-downgrade |
| 10 | Compatibilidad de datos legacy | `NOT_STARTED` | ✅ **DONE** | PlanMigrationService, SchemaEvolutionService, ContractValidator |
| 11 | Limpieza final | `NOT_STARTED` | ⚠️ **PENDING** | Role_profiles.py legacy cleanup |

---

## Evidencia De Implementación Por Fase

### Fase 0 — Canon del nodo y del routing ✅

**Archivos:**
- `models/agent_routing.py:105-164` → `RoutingDecision` (v2.0, schema_version frozen)
- `models/plan.py:43-141` → `PlanNode` con `routing_decision` como single source of truth
- `models/core.py:114-116` → `OpsRun` con routing metadata (agent_preset, execution_policy_name, routing_snapshot)

**Contratos:**
```python
class RoutingDecision(BaseModel):
    profile: ResolvedAgentProfile  # 5 core fields
    binding: ModelBinding          # provider, model, binding_mode, binding_reason
    routing_reason: str
    candidate_count: int
    schema_version: str = "2.0"    # Frozen, inmutable
```

**Backward compatibility:**
- Legacy fields en `PlanNode`: `model`, `provider`, `agent_preset` (exclude=True)
- Properties en `RoutingDecision`: `.provider`, `.model`, `.binding_mode` (read-only)
- Accessor methods: `get_binding()`, `get_profile()`, `get_routing_reason()`

---

### Fase 1 — Separar `mood` de permisos ✅

**Archivos:**
- `services/execution_policy_service.py` → 6 policies (read_only, docs_research, propose_only, workspace_safe, workspace_experiment, security_audit)
- `services/agent_catalog_service.py` → PRESET_CATALOG (11 presets)
- `engine/moods.py` → Comportamiento, no autoridad
- `engine/tools/executor.py` → Usa `execution_policy` en caminos productivos

**Tests:** `tests/unit/test_execution_policy_service.py` (15 tests)

---

### Fase 2 — Descriptor de tarea y fingerprint ✅

**Archivos:**
- `services/task_descriptor_service.py`
- `services/task_fingerprint_service.py`
- `services/custom_plan_service.py` → Escritura canónica de proposed_plan

**Tests:** `tests/test_phase2*.py`

---

### Fase 3 — Compilador de constraints ✅

**Archivos:**
- `services/constraint_compiler_service.py` → Compila TaskDescriptor → TaskConstraints
- `services/runtime_policy_service.py`
- `services/workspace_policy.py`
- `services/provider_topology_service.py`

**Contratos:**
```python
class TaskConstraints(BaseModel):
    allowed_policies: List[ExecutionPolicyName]
    allowed_bindings: Optional[List[PlanNodeBinding]]
    requires_human_approval: bool
    budget_constraints: Optional[BudgetConstraints]
```

**Tests:** `tests/unit/test_constraint_compiler_service.py` (44 passed)

---

### Fase 4 — `ProfileRouter` y binding real ✅

**Archivos:**
- `services/profile_router_service.py:1-183` → Pipeline completo:
  1. `_allowed_presets()` → Filtrado por constraints + downgraded (P9)
  2. `_gics_advisory_adjustment()` → Scoring adaptativo (F8.2)
  3. `_select_ranked_candidate()` → Ranking multinivel (requested > legacy > semantic > gics)
  4. `ProfileBindingService.resolve_binding_decision()` → Provider/model resolution
  5. Retorna `RoutingDecision` canónico (v2.0)

- `services/profile_binding_service.py` → Binding resolution con constraints

**Tests:**
- `test_profile_router_service.py` (18 tests)
- `test_profile_binding_service.py` (12 tests)

---

### Fase 5 — Materializacion correcta de planes y threads ✅

**Archivos:**
- `services/conversation_service.py` → Hidratación legacy en get/list/mutate/save/fork
- `services/agentic_loop_service.py` → Mueve threads con plan propuesto a awaiting_approval
- `routers/ops/conversation_router.py` → Conserva proposed_plan en reject

**Tests:** `tests/test_phase_5*.py` (77 passed)

---

### Fase 6 — `CustomPlanService` ejecuta perfiles reales ✅

**Archivos:**
- `services/custom_plan_service.py:49-130` → Pipeline integrado:
  ```python
  def llm_response_to_plan_nodes():
      descriptor = TaskDescriptorService.descriptor_from_task()
      constraints = ConstraintCompilerService.compile_for_descriptor()
      routing = ProfileRouterService.route()
      binding_resolution = ProfileBindingService.resolve_binding_decision()

      node = PlanNode(routing_decision=routing, ...)
  ```

- **Save guard (P10 Gap 2):** Migra v1→v2 antes de persistir
  ```python
  def _save(plan):
      plan.nodes = [PlanMigrationService.migrate_node(n) for n in plan.nodes]
  ```

**Tests:** `test_custom_plan_service.py`

---

### Fase 7 — `GraphEngine` y `WorkflowGraph` ✅

**Archivos:**
- `services/graph/engine.py` → Execution loop con budget guard + node dispatch
- `services/graph/node_executor.py:44-85` → Ejecuta con routing canónico:
  ```python
  async def _execute_llm_call(node):
      if agent_preset and not routing_decision_summary:
          routing = ProfileRouterService.route()
          node.config["routing_decision_summary"] = routing.summary
          node.config["selected_model"] = routing.binding.model
          node.config["execution_policy"] = routing.profile.execution_policy
  ```

- **Tool governance:**
  ```python
  async def _enforce_tool_governance(node, tool_name, args):
      policy = ExecutionPolicyService.get_policy(execution_policy)
      if tool_name not in policy.allowed_tools:
          raise PermissionError()
  ```

**Tests:**
- `test_graph_engine_routing.py`
- `test_node_executor_uses_policy.py`

---

### Fase 8 — Learning GICS por fingerprint y perfil ✅

**Archivos:**
- `services/advisory_engine.py` → Scoring adaptativo (F8.2):
  - Blended score: 30% prior + 70% telemetry
  - Wilson score interval para confianza estadística
  - Exploration bonus para presets con < 3 samples

- `services/preset_telemetry_service.py` → Tracking de success_rate, quality_score

**Integración:** `ProfileRouterService._gics_advisory_adjustment()` (línea 41-47)

**Tests:** `test_advisory_engine.py`

---

### Fase 9 — Surface parity y catalogo canonico ✅

**Archivos:**
- `services/anomaly_detection_service.py` → Auto-downgrade por estadísticas:
  - Baseline: μ, σ (min 20 samples)
  - Anomaly threshold: quality < μ - 2σ (95.4% confidence)
  - Downgrade: failure_streak ≥ 5

**Integración:** `ProfileRouterService._allowed_presets()` excluye downgraded

**Tests:** `test_anomaly_detection_service.py`

---

### Fase 10 — Compatibilidad de datos legacy ✅

**Archivos:**

1. **ContractValidator** (`services/contract_validator.py`):
   - Valida v2.0 nodes tienen routing_decision
   - Detecta schema drift (legacy fields vs routing_decision)
   - 3 violation levels: ERROR, WARNING, INFO
   - **Tests:** `test_contract_validator.py` (14 tests)

2. **PlanMigrationService** (`services/plan_migration_service.py`):
   - `migrate_node(node)` → v1.0 → v2.0 idempotente
   - `audit_migration_status()` → v1 vs v2 counts (JSON, sin parsing)
   - `audit_run_routing_coverage()` → runs con/sin routing metadata
   - **Tests:** `test_plan_migration_service.py` (9 tests)

3. **SchemaEvolutionService** (`services/schema_evolution_service.py`):
   - Registry de versiones con metadata
   - Migration paths v1→v2 para RoutingDecision + PlanNode
   - Backward compatible (breaking_changes=[])
   - **Tests:** `test_schema_evolution_service.py` (20 tests)

**P10 Gaps Cerrados:**
- ✅ Gap 1: OpsRun routing fields (agent_preset, execution_policy_name, routing_snapshot)
- ✅ Gap 2: Save guard en CustomPlanService._save()
- ✅ Gap 3: Audit methods (migration_status, run_routing_coverage)

**Tests adicionales:**
- `test_phase10_legacy_compat.py` (6 tests)
- `test_phase10_integral_validation.py`
- `tests/integration/test_phase10_integral_validation_int.py`
- `tests/contracts/test_routing_contracts.py`

---

### Fase 11 — Limpieza final ⚠️ PENDING

**Pendiente:**
- Retirar `role_profiles.py` como autoridad paralela
- Limpiar partes legacy de `moods.py`
- Actualizar documentación: SYSTEM.md, CLIENT_SURFACES.md, GIMO_GICS_INTEGRATION_SPEC_v1.0.md

---

## Pipeline Completo (End-to-End)

```
1. PLAN TIME:
   CustomPlanService.llm_response_to_plan_nodes()
   ├─ TaskDescriptorService.descriptor_from_task()      → TaskDescriptor
   ├─ ConstraintCompilerService.compile_for_descriptor() → TaskConstraints
   ├─ ProfileRouterService.route()                       → RoutingDecision (v2.0)
   │  ├─ _allowed_presets() [P9: filter downgraded]
   │  ├─ _gics_advisory_adjustment() [F8.2: AdvisoryEngine]
   │  ├─ _select_ranked_candidate() [multi-level ranking]
   │  └─ AgentCatalogService.resolve_profile() + ModelBinding
   └─ ProfileBindingService.resolve_binding_decision()   → resolved binding

   → PlanNode con routing_decision (v2.0)
   → CustomPlanService._save() [P10: migrate v1→v2]
   → Persist JSON (routing_decision incluido)

2. RUNTIME EXECUTION:
   GraphEngine.execute()
   └─ NodeExecutorMixin._execute_llm_call()
      ├─ Si agent_preset: ProfileRouterService.route() [re-route en runtime]
      ├─ Actualizar node.config[routing_decision_summary]
      └─ ProviderService.generate() con selected_model

   NodeExecutorMixin._execute_tool_call()
   └─ _enforce_tool_governance()
      ├─ ExecutionPolicyService.get_policy(execution_policy)
      ├─ Validar tool en allowed_tools
      └─ Check HITL requirement

3. OBSERVABILITY & GOVERNANCE:
   ├─ ContractValidator.validate(routing_decision)       [runtime checks]
   ├─ PresetTelemetryService.record_telemetry()          [P8: advisory data]
   ├─ AnomalyDetectionService.compute_baseline()         [P9: statistical baseline]
   ├─ AnomalyDetectionService.get_downgrade_list()       [P9: auto-downgrade]
   └─ SchemaEvolutionService.migrate() [P10: v1→v2 on load]
```

---

## Test Suite Coverage

| Fase | Tests | Status |
|------|-------|--------|
| P1-P2 | test_phase1.py, test_phase2*.py | ✅ Passing |
| P3 | test_phase3_terminal_commands.py | ✅ Passing |
| P4 | test_phase4_ops_routes.py | ✅ Passing |
| P5 | test_phase_5*.py (5a, 5b, 5c) | ✅ Passing |
| P6 | test_phase_6*.py (6a, 6b) | ✅ Passing |
| P7 | test_phase_7*.py (7a, 7b) | ✅ Passing |
| P8 | test_advisory_engine.py | ✅ Passing |
| P9 | test_anomaly_detection_service.py | ✅ Passing |
| P10 | test_phase10*.py, test_contract_validator.py, test_plan_migration_service.py, test_schema_evolution_service.py | ✅ Passing |

**Total:** 100+ tests cubriendo todas las fases

---

## Backward Compatibility

| Mecanismo | Ubicación | Propósito |
|-----------|-----------|----------|
| Legacy fields exclusion | PlanNode (exclude=True) | No serializar v1 fields |
| Accessor methods | PlanNode.get_binding(), get_profile() | Clean API para ambos v1/v2 |
| Properties | RoutingDecision.provider, .model | Backward compat con legacy code |
| PlanMigrationService | Servicio dedicado | Auto-migrate v1→v2 on load |
| SchemaEvolutionService | Registry + migration paths | Evolucionable a v3.0+ |
| Save guard | CustomPlanService._save() | Migra antes de persistir |
| Validator warnings | ContractValidator | Detección de redundancia |

---

## Conclusión

**Estado real:** P1-P10 COMPLETAMENTE IMPLEMENTADAS Y FUNCIONALES.

**Único pendiente:** Fase 11 (limpieza de autoridades paralelas legacy)

**Single source of truth:** `RoutingDecision` (v2.0) correctamente posicionado como canonical decision maker.

**Evidencia histórica de commits:**
- `1e1e35e` (2026-03-21): "Close migration phases 1 and 2"
- `ed70544` (2026-03-22): "Harden phase 3 and 4 agent profile routing"
- `3ce8ba3` (2026-03-28): "consolidate local work and close Phase 5"
- `ab23f06` (2026-03-28): "apply execution policies from routing decisions"
- `c840f80` (2026-03-29): "refactor(router): adopt canonical constraint-based routing"

**Siguiente paso:** Fase 11 (limpieza final) o considerar migración completa.
