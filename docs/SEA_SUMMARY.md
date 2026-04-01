# Sistema de Ejecución Adaptativa (SEA) - Resumen Ejecutivo

**Estado**: 57% completado (4 de 7 fases)
**Tests**: 41/41 pasando ✅
**Fecha**: 2026-04-01

---

## 🎯 ¿Qué es SEA?

Sistema que elimina los timeouts arbitrarios de GIMO mediante:
- **Predicción adaptativa** basada en historial real
- **Feedback en tiempo real** vía SSE streaming
- **Operaciones resumibles** con checkpointing
- **Retry inteligente** con circuit breaker

---

## ✅ Fases Completadas

### Fase 1: Telemetría de Duración
**Status**: ✅ Completada (10 tests)

- Captura duraciones reales en GICS
- Schema: `ops:duration:{operation}:{timestamp_ms}`
- Instrumentación de plan_router.py y engine_service.py
- Endpoint de observabilidad: `/ops/observability/duration-stats`

```bash
curl http://127.0.0.1:9325/ops/observability/duration-stats?operation=plan | jq
```

---

### Fase 2: Adaptive Timeout Predictor
**Status**: ✅ Completada (16 tests)

- Predice timeout óptimo basándose en percentil 95 + ajustes contextuales
- Ajustes por: model, system load, complexity, prompt length, file count
- Integración con capabilities_service.py
- Fallback seguro a defaults

**Algoritmo**:
1. Consulta historial GICS
2. Filtra por similitud contextual
3. Calcula P95
4. Aplica ajustes (Opus +50%, Haiku -20%, etc.)
5. Margen de seguridad +20%
6. Bounds [30s, 600s]

---

### Fase 3: SSE Progress Streaming
**Status**: ✅ Completada (15 tests)

- ProgressEmitter para eventos SSE
- Endpoint `/ops/generate-plan-stream`
- Feature flag: `plan_streaming` en capabilities
- Eventos: started, progress, checkpoint, completed, error

**Ejemplo de uso**:
```javascript
// Cliente consume SSE stream
const evtSource = new EventSource("/ops/generate-plan-stream?prompt=...");

evtSource.addEventListener("progress", (e) => {
  const data = JSON.parse(e.data);
  console.log(`${data.stage}: ${data.progress * 100}%`);
  console.log(`Remaining: ${data.remaining}s`);
});
```

---

### Fase 4: Deadline Propagation
**Status**: ✅ Completada

- DeadlineMiddleware para propagación de headers
- Headers: `X-GIMO-Deadline`, `X-GIMO-Max-Duration`
- Inyección en request.state (deadline, remaining_time)
- Validación de tiempo mínimo (5s)

**Uso en endpoints**:
```python
deadline = request.state.deadline
remaining = request.state.remaining_time

if remaining < 10.0:
    # Deadline approaching, priorizar fases críticas
    ...
```

---

## 🔄 Fases Pendientes

### Fase 5: Checkpointing (4-5 horas)
**Objetivo**: Operaciones resumibles

- `CheckpointService` — Guarda estado intermedio en GICS
- Checkpoint cada 15s durante operaciones largas
- Endpoint `/ops/{operation}/resume`
- CLI command: `gimo resume <checkpoint_id>`

**Schema GICS**:
```
ckpt:{operation}:{operation_id}:{checkpoint_id} → {
    operation: str,
    state: {stage, completed_tasks, partial_result},
    resumable: bool,
    expires_at: int  # 24h TTL
}
```

---

### Fase 6: Circuit Breaker + Intelligent Retry (4-5 horas)
**Objetivo**: Retry inteligente que aprende de fallos colectivos

**CircuitBreaker**:
- Estados: CLOSED → OPEN → HALF_OPEN
- Threshold: 5 fallos → abrir circuit
- Recovery timeout: 60s

**IntelligentRetry**:
- Backoff exponencial (1s → 32s)
- Consulta GICS por timeouts recientes
- Si >10 timeouts en 5min → provider degraded, no retry

**Collective Intelligence**:
```python
# Detectar degradation colectiva
recent_timeouts = gics.count_prefix("ops:timeout:plan:")
if recent_timeouts > 10:
    raise ProviderDegradedError()  # No retry
```

---

### Fase 7: Graceful Degradation (3-4 horas)
**Objetivo**: Resultados parciales útiles si timeout inevitable

**Priorización de fases**:
```python
priority_phases = ["orchestrator", "core_workers"]  # CRÍTICO
optional_phases = ["tests", "docs", "ci_cd"]        # OPCIONAL
```

**Lógica**:
1. Generar fases prioritarias primero
2. Si deadline approaching → skip opcionales
3. Validar viabilidad de plan parcial (min: 1 orchestrator + 1 worker)
4. Retornar con status `partial_success`

**UX**:
```bash
⚠️  Deadline approaching — skipping optional phases

✓ Plan generated (partial)
  ├─ Core phases: ✓ orchestrator, ✓ core_workers
  ├─ Skipped: tests, docs, ci_cd
  └─ Tasks: 5 (executable)

💡 Tip: Use `gimo plan --no-timeout` for complete generation
```

---

## 📊 Métricas

| Componente | Tests | Status |
|-----------|-------|--------|
| Duration Telemetry | 10 | ✅ |
| Adaptive Timeout | 16 | ✅ |
| Progress Emitter | 15 | ✅ |
| Deadline Middleware | - | ✅ |
| **TOTAL** | **41** | **✅** |

---

## 🏗️ Arquitectura Implementada

```
tools/gimo_server/
├── services/
│   └── timeout/
│       ├── duration_telemetry_service.py     ✅
│       ├── adaptive_timeout_service.py       ✅
│       └── progress_emitter.py               ✅
│
├── middlewares/
│   └── deadline_middleware.py                ✅
│
└── routers/ops/
    ├── plan_router.py                        ✅ (instrumentado + streaming)
    └── observability_router.py               ✅ (stats endpoint)

tests/unit/
├── test_duration_telemetry.py                ✅ 10 tests
├── test_adaptive_timeout.py                  ✅ 16 tests
└── test_progress_emitter.py                  ✅ 15 tests
```

---

## 🚀 Próximos Pasos

### Opción 1: Completar Fases Restantes (11-14 horas)
Implementar Fases 5, 6 y 7 para tener SEA completo.

### Opción 2: Validar Implementación Actual
1. Ejecutar server y probar streaming:
   ```bash
   python tools/gimo_server/main.py
   ```

2. Generar algunos planes para entrenar predictor:
   ```bash
   for i in {1..20}; do gimo plan "test task $i"; done
   ```

3. Ver estadísticas adaptativas:
   ```bash
   curl http://127.0.0.1:9325/ops/observability/duration-stats | jq
   ```

4. Probar endpoint streaming:
   ```bash
   curl -N -H "Authorization: Bearer $ORCH_TOKEN" \
     "http://127.0.0.1:9325/ops/generate-plan-stream?prompt=test task"
   ```

---

## 📚 Documentación

- **Arquitectura completa**: `docs/architecture/adaptive_execution_system.md`
- **Progreso detallado**: `docs/GAEP_PROGRESS.md`
- **Este resumen**: `docs/SEA_SUMMARY.md`

---

## 💡 Beneficios Logrados (Fases 1-4)

✅ **Timeouts adaptativos** — Ya no más 180s arbitrarios
✅ **Feedback en tiempo real** — Usuario ve progreso y ETA
✅ **Predicción inteligente** — Aprende de historial real
✅ **Deadline awareness** — Backend sabe cuánto tiempo tiene
✅ **Observabilidad completa** — Estadísticas de duración

---

## 🎯 Beneficios Pendientes (Fases 5-7)

🔄 **Operaciones resumibles** — No perder progreso en timeout
🔄 **Retry inteligente** — No reintentar si provider degraded
🔄 **Resultados parciales** — Algo es mejor que nada

---

## 🔧 Comandos Útiles

```bash
# Ejecutar todos los tests SEA
pytest tests/unit/test_duration_telemetry.py \
       tests/unit/test_adaptive_timeout.py \
       tests/unit/test_progress_emitter.py -v

# Ver estadísticas de todas las operaciones
curl http://127.0.0.1:9325/ops/observability/duration-stats | jq

# Verificar feature flags
curl http://127.0.0.1:9325/ops/capabilities | jq '.features'

# Probar streaming (requiere server corriendo)
curl -N "http://127.0.0.1:9325/ops/generate-plan-stream?prompt=test" \
  -H "Authorization: Bearer $ORCH_TOKEN"
```

---

**¿Continuar con Fases 5-7?** → Total 11-14 horas adicionales
**¿Validar implementación actual?** → Probar con casos reales
**¿Iterar sobre lo existente?** → Mejorar predictor, agregar más ajustes contextuales
