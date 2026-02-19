# GIMO — Plan Unificado Fase 3 (Kickoff)

**Estado:** EN EJECUCIÓN (ARRANCADO)  
**Fecha:** 2026-02-19  
**Objetivo:** arrancar Fase 3 con backlog único, priorizado y verificable.

---

## 1) Alcance Fase 3 (fuente funcional)

Basado en el roadmap histórico v2, Fase 3 cubre:

1. Adapters adicionales (Codex + Gemini) integrados en runtime real.
2. Patrones multi-agente (supervisor/workers, reviewer loop, handoff explícito).
3. Model Router inteligente orientado a coste/calidad/presupuesto.
4. Onboarding multi-provider (detección, health checks, UX de conectores).

---

## 2) Estado actual verificado (hoy)

### Ya implementado y validado

- `CodexAdapter` y `GeminiAdapter` existen y comparten contrato `AgentAdapter`.
- `GraphEngine` soporta patrones:
  - `supervisor_workers`
  - `reviewer_loop`
  - `handoff`
- `ModelRouterService` soporta:
  - policy por `task_type`
  - degradación por presupuesto
  - ROI routing
  - eco mode + límites user floor/ceiling

### Evidencia de tests

Comando ejecutado:

`python -m pytest -q tests/test_adapters.py tests/test_graph_engine.py tests/test_model_router_service.py tests/services/test_roi_routing.py`

Resultado: **39 passed**.

---

## 3) Gap real detectado para cerrar Fase 3

1. `AdapterRegistry.initialize_defaults()` solo registra `local` (falta registro canónico de Codex/Gemini y bootstrap config-driven).
2. `supervisor_workers` ejecuta workers en secuencia; falta variante paralela controlada y límites de concurrencia.
3. Falta trazabilidad explícita de handoff (payload curado + metadatos de transferencia) en observabilidad/audit como entidad dedicada.
4. Falta contrato único de "routing tier" ↔ "modelo proveedor" para producción multi-provider.
5. Falta cierre UX/API de onboarding multi-agent como experiencia unificada (detección CLI + health + activación).

---

## 4) TODO unificado (priorizado)

## P0 — Cierre de runtime multi-agent

- [ ] Registrar adapters `codex` y `gemini` en `AdapterRegistry` con inicialización por configuración.
- [ ] Añadir health check de binarios CLI (codex/gemini) en bootstrap de adapters.
- [ ] Añadir test de registro por defecto y selección por nombre de adapter.

## P1 — Patrones multi-agente en modo producción

- [ ] Implementar modo paralelo en `supervisor_workers` (async gather) con `max_parallel_workers`.
- [ ] Persistir metadatos de sub-ejecuciones (worker_id, duración, estado, coste) por worker.
- [ ] Añadir política de fallo configurable por patrón (`fail_fast`, `collect_partial`).
- [ ] Añadir tests de concurrencia y comportamiento ante fallo parcial.

## P1 — Handoff explícito y auditable

- [x] Definir objeto `handoff_package` estándar (keys, resumen, source_node, target_node, timestamp).
- [x] Emitir eventos de observabilidad específicos para handoff.
- [ ] Exponer handoff en `step_logs`/timeline para inspección en UI.
- [x] Añadir tests del contrato de handoff (curación + trazabilidad).

## P1 — Model Router preparado para multi-provider real

- [x] Separar "tier lógico" (`haiku/sonnet/opus/local`) de "modelo físico" por provider activo.
- [x] Añadir resolución final de modelo por provider (`provider_model_map`).
- [x] Incluir razón de routing extendida (tier, provider, budget rule aplicada).
- [x] Añadir tests con escenarios cross-provider y fallback determinista.

## P2 — Onboarding multi-provider / conectores

- [ ] Definir endpoint/backend para detección de CLIs instalados (codex/gemini/claude).
- [x] Exponer estado de conector: `installed`, `configured`, `healthy`, `default_model`.
- [ ] Unificar en UI flujo de alta: detectar → validar → activar.
- [ ] Añadir tests de integración API para estado de conectores.

## P2 — Observabilidad y coste de Fase 3

- [ ] Añadir métricas por patrón (`pattern_type`, `workers_count`, `handoff_count`, `review_rounds`).
- [ ] Añadir coste agregado por patrón multi-agent y por adapter.
- [ ] Incluir vista resumida para comparar eficiencia single vs multi-agent.

---

## 5) Definition of Done Fase 3

- [ ] Adapters Codex/Gemini disponibles por registro dinámico en runtime.
- [ ] Patrones multi-agent soportan operación robusta (incluido paralelo/fallo parcial).
- [ ] Handoff queda trazado y auditable de extremo a extremo.
- [ ] Model Router enruta de forma determinista entre providers con control de presupuesto.
- [ ] Onboarding de conectores permite activar agentes sin pasos manuales ambiguos.
- [ ] Suite objetivo de Fase 3 en verde + evidencia documentada en `docs/evidence/`.

### Evidencia reciente (arranque)

- Comando: `python -m pytest -q tests/test_graph_engine.py tests/test_observability_service.py tests/services/test_model_router_v2.py tests/test_ops_v2.py tests/services/test_adapter_registry.py tests/test_adapters.py`
- Resultado: `88 passed, 2 xpassed, 0 failed`.

---

## 6) Sprint de arranque recomendado (próximas 48h)

1. **Día 1:** AdapterRegistry + tests + health checks CLI.
2. **Día 1-2:** `supervisor_workers` paralelo + fail policy + tests.
3. **Día 2:** contrato `handoff_package` + trazabilidad mínima.

Entrega esperada del sprint: cierre de los bloques P0 + primer bloque P1.