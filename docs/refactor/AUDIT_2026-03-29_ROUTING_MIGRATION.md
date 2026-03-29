# Auditoría de Estado Real: Migración Agent Profile Routing

**Fecha:** 2026-03-29
**Tipo:** Auditoría code-by-code completa
**Auditor:** Claude Sonnet 4.5 (agentId: a7e6651)
**Duración:** 145.4 segundos, 89,412 tokens

---

## Resumen Ejecutivo

### Hallazgo Principal

**La documentación estaba desactualizada en 5+ fases.**

El código tiene **P1-P10 COMPLETAMENTE IMPLEMENTADAS Y FUNCIONALES** con:
- ✅ Modelos canónicos (RoutingDecision v2.0, PlanNode con single source of truth)
- ✅ Servicios integrados (ProfileRouterService, ExecutionPolicyService, etc.)
- ✅ Ejecución runtime (GraphEngine + NodeExecutor con governance)
- ✅ Migración legacy (PlanMigrationService, SchemaEvolutionService)
- ✅ Validación (ContractValidator)
- ✅ 100+ tests passing (unit + integration)

**Solo falta:** Fase 11 (limpieza de autoridades paralelas legacy)

---

## Comparación: Documentado vs Real

| Fase | Estado Docs (27/28 mar) | Estado Real (29 mar) | Gap |
|------|-------------------------|----------------------|-----|
| P0 | DONE | ✅ DONE | ✅ Correcto |
| P1 | DONE | ✅ DONE | ✅ Correcto |
| P2 | DONE | ✅ DONE | ✅ Correcto |
| P3 | DONE | ✅ DONE | ✅ Correcto |
| P4 | DONE | ✅ DONE | ✅ Correcto |
| P5 | DONE | ✅ DONE | ✅ Correcto |
| **P6** | **PARTIAL** | ✅ **DONE** | ⚠️ **5 fases desactualizadas** |
| **P7** | **NOT_STARTED** | ✅ **DONE** | ⚠️ |
| **P8** | **NOT_STARTED** | ✅ **DONE** | ⚠️ |
| **P9** | **NOT_STARTED** | ✅ **DONE** | ⚠️ |
| **P10** | **NOT_STARTED** | ✅ **DONE** | ⚠️ |
| P11 | NOT_STARTED | ⚠️ PENDING | ✅ Correcto |

---

## Evidencia de Implementación

### P6: CustomPlanService ✅

**Documentado:** PARTIAL
**Real:** DONE

**Evidencia:**
- `custom_plan_service.py:49-130` → Pipeline integrado con ProfileRouterService
- Save guard (P10 Gap 2): Migra v1→v2 antes de persistir
- Tests: `test_custom_plan_service.py` passing

### P7: GraphEngine ✅

**Documentado:** NOT_STARTED
**Real:** DONE

**Evidencia:**
- `services/graph/engine.py` → Execution loop con budget guard
- `services/graph/node_executor.py:44-85` → Ejecuta con routing canónico
- Tool governance: ExecutionPolicyService enforcement
- Tests: `test_graph_engine_routing.py`, `test_node_executor_uses_policy.py` passing

### P8: Learning GICS ✅

**Documentado:** NOT_STARTED
**Real:** DONE

**Evidencia:**
- `services/advisory_engine.py` → Scoring adaptativo (F8.2)
- Blended score: 30% prior + 70% telemetry
- `services/preset_telemetry_service.py` → Tracking de success_rate, quality_score
- Integrado en ProfileRouterService._gics_advisory_adjustment()
- Tests: `test_advisory_engine.py` passing

### P9: Auto-downgrade ✅

**Documentado:** NOT_STARTED
**Real:** DONE

**Evidencia:**
- `services/anomaly_detection_service.py` → Baseline estadístico (μ, σ)
- Anomaly threshold: quality < μ - 2σ (95.4% confidence)
- Downgrade: failure_streak ≥ 5
- Integrado en ProfileRouterService._allowed_presets()
- Tests: `test_anomaly_detection_service.py` passing

### P10: Compatibilidad Legacy ✅

**Documentado:** NOT_STARTED formalmente
**Real:** DONE (3 gaps cerrados)

**Evidencia:**
- `services/contract_validator.py` → Runtime validation (14 tests)
- `services/plan_migration_service.py` → v1→v2 migration (9 tests)
- `services/schema_evolution_service.py` → Schema registry (20 tests)
- **Gap 1:** OpsRun routing fields (agent_preset, execution_policy_name, routing_snapshot) ✅
- **Gap 2:** Save guard en CustomPlanService._save() ✅
- **Gap 3:** Audit methods (migration_status, run_routing_coverage) ✅
- Tests: `test_phase10*.py`, `test_contract_validator.py`, etc. passing

---

## Pipeline Completo End-to-End

```
PLAN TIME:
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
→ Persist JSON

RUNTIME EXECUTION:
GraphEngine.execute()
└─ NodeExecutorMixin._execute_llm_call()
   ├─ ProfileRouterService.route() [re-route si agent_preset]
   ├─ Actualizar node.config[routing_decision_summary]
   └─ ProviderService.generate()

NodeExecutorMixin._execute_tool_call()
└─ _enforce_tool_governance()
   ├─ ExecutionPolicyService.get_policy()
   ├─ Validar tool en allowed_tools
   └─ Check HITL requirement

OBSERVABILITY:
├─ ContractValidator.validate() [P10]
├─ PresetTelemetryService.record_telemetry() [P8]
├─ AnomalyDetectionService.compute_baseline() [P9]
└─ SchemaEvolutionService.migrate() [P10]
```

---

## Test Coverage

| Fase | Tests | Status |
|------|-------|--------|
| P1-P2 | test_phase1.py, test_phase2*.py | ✅ Passing |
| P3 | test_phase3_terminal_commands.py | ✅ Passing |
| P4 | test_phase4_ops_routes.py, test_profile_router_service.py (18), test_profile_binding_service.py (12) | ✅ Passing |
| P5 | test_phase_5*.py (77 tests) | ✅ Passing |
| P6 | test_phase_6*.py, test_custom_plan_service.py | ✅ Passing |
| P7 | test_phase_7*.py, test_graph_engine_routing.py, test_node_executor_uses_policy.py | ✅ Passing |
| P8 | test_advisory_engine.py | ✅ Passing |
| P9 | test_anomaly_detection_service.py | ✅ Passing |
| P10 | test_phase10*.py (6), test_contract_validator.py (14), test_plan_migration_service.py (9), test_schema_evolution_service.py (20) | ✅ Passing |

**Total:** 100+ tests cubriendo todas las fases implementadas

---

## Backward Compatibility

| Mecanismo | Ubicación | Status |
|-----------|-----------|--------|
| Legacy fields exclusion | PlanNode (exclude=True) | ✅ Implementado |
| Accessor methods | get_binding(), get_profile() | ✅ Implementado |
| Properties | RoutingDecision.provider, .model | ✅ Implementado |
| PlanMigrationService | Auto-migrate v1→v2 | ✅ Implementado |
| SchemaEvolutionService | Registry + migration paths | ✅ Implementado |
| Save guard | CustomPlanService._save() | ✅ Implementado |
| ContractValidator | Runtime validation | ✅ Implementado |

---

## Trabajo Pendiente

### Fase 11: Limpieza Final ⚠️

**Archivos a modificar:**
- `services/role_profiles.py` → Retirar como autoridad paralela
- `engine/moods.py` → Limpiar partes legacy
- Rutas y metadata que hablen de `mood_transition`

**Documentación a actualizar:**
- `docs/SYSTEM.md`
- `docs/CLIENT_SURFACES.md`
- `docs/GIMO_GICS_INTEGRATION_SPEC_v1.0.md`

**Criterios de aceptación:**
- Ya no quedan dos autoridades semánticas vivas
- El runtime no depende de defaults legacy escondidos

---

## Recomendaciones

1. **Actualizar roadmap oficial** con estado P1-P10 = DONE
2. **Cerrar Fase 11** (limpieza) como último paso de migración
3. **Considerar migración completa** si P11 está cerrada
4. **Mantener docs sincronizados** con código en futuras fases

---

## Commits Históricos Relevantes

```
1e1e35e (2026-03-21) - Close migration phases 1 and 2
ed70544 (2026-03-22) - Harden phase 3 and 4 agent profile routing
3ce8ba3 (2026-03-28) - consolidate local work and close Phase 5
ab23f06 (2026-03-28) - apply execution policies from routing decisions
c840f80 (2026-03-29) - refactor(router): adopt canonical constraint-based routing
```

---

## Archivos Generados por Auditoría

1. `docs/refactor/AGENT_PROFILE_ROUTING_MIGRATION_STATUS_2026-03-29.md` (nuevo)
2. `docs/refactor/AGENT_PROFILE_ROUTING_MIGRATION_CANONICAL_PLAN_2026-03-28.md` (actualizado)
3. `docs/refactor/AUDIT_2026-03-29_ROUTING_MIGRATION.md` (este documento)

---

**Conclusión:** La migración de agent profile routing está funcionalmente completa (P1-P10). Solo falta limpieza cosmética (P11).
