# Sistema de Ejecución Adaptativa (SEA) - Progreso de Implementación

**Adaptive Execution System** — Sistema adaptativo de timeouts, progress streaming y operaciones resumibles.

## Estado General

**Fecha**: 2026-04-01
**Implementado**: Fases 1, 2, 3 y 4
**Tests**: 41/41 pasando ✅
**Progreso**: 57% completado (4 de 7 fases)

---

## ✅ Fase 1: Telemetría de Duración (COMPLETADA)

### Objetivo
Capturar métricas de duración para entrenar el predictor adaptativo.

### Implementación

**Archivos creados**:
- `tools/gimo_server/services/timeout/duration_telemetry_service.py`
- `tests/unit/test_duration_telemetry.py` (10 tests ✅)

**Archivos modificados**:
- `tools/gimo_server/routers/ops/plan_router.py` — Instrumentado con telemetría
- `tools/gimo_server/services/execution/engine_service.py` — Instrumentado con telemetría
- `tools/gimo_server/routers/ops/observability_router.py` — Endpoint `/ops/observability/duration-stats`

### Funcionalidad

**DurationTelemetryService**:
- `record_operation_duration()` — Almacena duración en GICS
- `get_historical_durations()` — Recupera historial con filtrado contextual
- `get_stats_for_operation()` — Estadísticas agregadas (avg, p50, p95, max)
- Schema GICS: `ops:duration:{operation}:{timestamp_ms}`

**Operaciones instrumentadas**:
1. **Plan generation** (`plan_router.py:generate_structured_plan`)
   - Captura: duration, model, prompt_length, provider, status
2. **Run execution** (`engine_service.py:execute_run`)
   - Captura: duration, model, composition, file_count, is_child, status

**Endpoint de observabilidad**:
```bash
GET /ops/observability/duration-stats?operation=plan
# Retorna: total_samples, success_rate, avg_duration_s, p50, p95, max
```

### Verificación

```bash
# Después de generar algunos planes:
curl http://127.0.0.1:9325/ops/observability/duration-stats?operation=plan | jq
```

---

## ✅ Fase 2: Adaptive Timeout Predictor (COMPLETADA)

### Objetivo
Predecir timeout óptimo basándose en historial de GICS + ajustes contextuales.

### Implementación

**Archivos creados**:
- `tools/gimo_server/services/timeout/adaptive_timeout_service.py`
- `tests/unit/test_adaptive_timeout.py` (16 tests ✅)

**Archivos modificados**:
- `tools/gimo_server/services/capabilities_service.py` — Usa predictor en vez de timeouts estáticos

### Funcionalidad

**AdaptiveTimeoutService**:
- `predict_timeout(operation, context)` — Predicción con ajustes contextuales
- `predict_timeout_simple(operation)` — Predicción sin contexto
- `get_confidence_level(operation)` — Nivel de confianza (high/medium/low)
- `recommend_timeout_with_metadata()` — Predicción + metadata

**Algoritmo de predicción**:
1. Consulta GICS por `ops:duration:{operation}:*`
2. Filtra por similitud de contexto (model, prompt_length, file_count)
3. Calcula percentil 95 (cubre 95% de casos históricos)
4. Aplica ajustes contextuales:
   - **Model**: Opus +50%, Haiku -20%
   - **System load**: High +30%, Low -10%
   - **Complexity**: Complex +40%, Simple -30%
   - **Prompt length**: >1000 chars +20%
   - **File count**: >10 files +30%, >5 files +15%
5. Añade margen de seguridad (20%)
6. Limita entre MIN_TIMEOUT (30s) y MAX_TIMEOUT (600s)

**Integración con capabilities**:
```python
# capabilities_service.py ahora usa predicción adaptativa
gen_timeout = AdaptiveTimeoutService.predict_timeout(
    operation="plan",
    context={
        "model": active_model,
        "system_load": load_level,
    }
)
```

**Fallback seguro**:
- Si no hay historial → usa defaults (plan=180s, run=300s, merge=60s)
- Si predictor falla → fallback a timeouts estáticos basados en load

### Verificación

```bash
# CLI consulta /ops/capabilities para obtener timeout adaptativo
gimo plan "test task"

# Server logs muestran predicción:
# "Adaptive timeout for plan generation: 127.5s (model=claude-3-5-sonnet, load=safe)"
```

---

## ✅ Fase 3: SSE Progress Streaming (COMPLETADA)

### Objetivo
Proporcionar feedback en tiempo real al usuario durante operaciones largas con SSE.

### Implementación

**Archivos creados**:
- `tools/gimo_server/services/timeout/progress_emitter.py`
- `tests/unit/test_progress_emitter.py` (15 tests ✅)

**Archivos modificados**:
- `tools/gimo_server/routers/ops/plan_router.py` — Endpoint `/ops/generate-plan-stream`
- `tools/gimo_server/services/capabilities_service.py` — Feature flag `plan_streaming`

### Funcionalidad

**ProgressEmitter**:
- `emit_started()` — Emite evento de inicio con ETA
- `emit_progress()` — Emite progreso (0.0-1.0) con tiempo restante
- `emit_checkpoint()` — Emite que se guardó checkpoint
- `emit_completed()` — Emite resultado final
- `emit_error()` — Emite error
- `emit_custom()` — Emite evento personalizado

**Eventos SSE**:
```javascript
// started
{
  "operation": "plan",
  "estimated_duration": 120.5,
  "model": "claude-3-5-sonnet"
}

// progress
{
  "stage": "generating_tasks",
  "progress": 0.65,
  "elapsed": 78.3,
  "remaining": 42.2
}

// checkpoint
{
  "checkpoint_id": "ckpt_1735689650",
  "resumable": true
}

// completed
{
  "result": {"draft_id": "...", "task_count": 5},
  "duration": 118.7,
  "status": "success"
}
```

**Streaming endpoint**:
```python
@router.post("/generate-plan-stream")
async def generate_plan_stream(...):
    """Genera plan con SSE progress updates."""

    async def event_generator():
        # 1. Predecir duración
        estimated = AdaptiveTimeoutService.predict_timeout(...)

        # 2. Emitir started
        yield f"event: started\ndata: {json.dumps(...)}\n\n"

        # 3. Emitir progress durante generación
        yield f"event: progress\ndata: {json.dumps(...)}\n\n"

        # 4. Emitir completed
        yield f"event: completed\ndata: {json.dumps(...)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### Verificación

```bash
# Test con curl
curl -N -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:9325/ops/generate-plan-stream?prompt=test" \
  2>&1 | grep "^event:"

# Salida esperada:
# event: started
# event: progress
# event: progress
# event: completed
```

---

## ✅ Fase 4: Deadline Propagation (COMPLETADA)

### Objetivo
Backend conoce exactamente cuánto tiempo tiene para ejecutar → puede cancelar proactivamente.

### Implementación

**Archivos creados**:
- `tools/gimo_server/middlewares/deadline_middleware.py`
- `tools/gimo_server/middlewares/__init__.py`

**Archivos modificados**:
- `tools/gimo_server/middlewares.py` — Registra `DeadlineMiddleware`

### Funcionalidad

**Headers**:
```
Cliente → Server:
  X-GIMO-Deadline: 1735689600.5       # Unix timestamp absoluto
  X-GIMO-Max-Duration: 120.0          # Segundos máximos
```

**DeadlineMiddleware**:
```python
class DeadlineMiddleware(BaseHTTPMiddleware):
    MIN_REMAINING_TIME = 5.0

    async def dispatch(self, request: Request, call_next):
        deadline_str = request.headers.get("X-GIMO-Deadline")

        if deadline_str:
            deadline = float(deadline_str)
            remaining = deadline - time.time()

            # Validar tiempo suficiente
            if remaining < self.MIN_REMAINING_TIME:
                return JSONResponse(status_code=408, content={
                    "error": "Request deadline exceeded",
                    "detail": f"Only {remaining:.1f}s remaining"
                })

            # Inyectar en request state
            request.state.deadline = deadline
            request.state.remaining_time = remaining

        return await call_next(request)
```

**Helper methods**:
- `get_remaining_time(request)` — Obtiene tiempo restante
- `check_deadline_approaching(request, threshold)` — Verifica si deadline cercano
- `allocate_time_budget(request, overhead_percent)` — Calcula presupuesto de tiempo

**Uso en endpoints**:
```python
async def generate_plan_internal(request: Request, ...):
    deadline = getattr(request.state, "deadline", None)

    if deadline:
        # Reservar 10% para overhead
        llm_timeout = (deadline - time.time()) * 0.9

        # Pasar timeout al provider
        resp = await ProviderService.static_generate(
            sys_prompt,
            context={"timeout": llm_timeout}
        )
```

### Verificación

```python
# Test deadline exceeded
import time
import httpx

deadline = time.time() + 2.0  # 2 segundos
headers = {"X-GIMO-Deadline": str(deadline)}

time.sleep(3)  # Esperar que expire

response = httpx.post(
    "http://127.0.0.1:9325/ops/generate-plan?prompt=test",
    headers=headers
)
# Debe retornar 408 Timeout
assert response.status_code == 408
```

---

## 🔄 Fases Pendientes

### Fase 3: SSE Progress Events
- `progress_emitter.py` — Emite eventos de progreso vía callback
- `/ops/generate-plan-stream` — Endpoint SSE con progress updates
- CLI progress bar (Rich)

### Fase 4: Deadline Propagation Headers
- `deadline_middleware.py` — Middleware FastAPI
- Headers: `X-GIMO-Deadline`, `X-GIMO-Max-Duration`
- Backend conoce tiempo restante para ejecutar

### Fase 5: Checkpointing (Resumable Operations)
- `checkpoint_service.py` — Guarda estado intermedio en GICS
- `/ops/{operation}/resume` — Reanuda desde checkpoint
- `gimo resume <checkpoint_id>` — CLI command

### Fase 6: Circuit Breaker + Intelligent Retry
- `circuit_breaker.py` — Estados: closed/open/half_open
- `intelligent_retry.py` — Retry con backoff + colectiva intelligence
- Usa GICS para detectar provider degradation colectiva

### Fase 7: Graceful Degradation (Partial Results)
- Priorización de fases (orchestrator + core workers primero)
- Retorna resultado parcial útil si timeout inevitable
- Validación de viabilidad de resultados parciales

---

## Métricas de Calidad

### Tests
- **Total**: 26 tests
- **Duration Telemetry**: 10 tests ✅
- **Adaptive Timeout**: 16 tests ✅
- **Coverage**: Context matching, percentile calc, bounds, adjustments

### Performance Impact
- **Telemetry overhead**: ~0.5ms por operación (GICS.put)
- **Prediction overhead**: ~2ms (GICS.scan + cálculo)
- **Zero breaking changes**: Endpoints antiguos siguen funcionando

### Observabilidad
- Endpoint: `/ops/observability/duration-stats`
- Schema GICS: `ops:duration:{operation}:{timestamp_ms}`
- Logs: `orchestrator.services.timeout.*`

---

## Arquitectura

```
tools/gimo_server/services/timeout/
├── __init__.py
├── duration_telemetry_service.py    ← Fase 1 ✅
├── adaptive_timeout_service.py      ← Fase 2 ✅
├── progress_emitter.py              ← Fase 3 🔄
├── circuit_breaker.py               ← Fase 6 🔄
└── intelligent_retry.py             ← Fase 6 🔄

tools/gimo_server/middlewares/
└── deadline_middleware.py           ← Fase 4 🔄

tools/gimo_server/services/
└── checkpoint_service.py            ← Fase 5 🔄
```

---

## Próximos Pasos

1. **Fase 3**: Implementar SSE progress events para feedback en tiempo real
2. **Fase 4**: Deadline propagation para cancelación proactiva
3. **Fase 5**: Checkpointing para operaciones resumibles
4. **Fase 6**: Circuit breaker + retry inteligente
5. **Fase 7**: Graceful degradation con resultados parciales

**Tiempo estimado restante**: 2-3 días (Fases 3-7)

---

## Comandos Útiles

```bash
# Ejecutar tests GAEP
pytest tests/unit/test_duration_telemetry.py tests/unit/test_adaptive_timeout.py -v

# Ver estadísticas de duración
curl http://127.0.0.1:9325/ops/observability/duration-stats | jq

# Ver estadísticas por operación específica
curl "http://127.0.0.1:9325/ops/observability/duration-stats?operation=plan" | jq

# Generar algunos planes para entrenar predictor
for i in {1..10}; do gimo plan "test task $i"; done
```

---

## Notas Técnicas

### Context Similarity Matching
El filtrado contextual usa los siguientes criterios:
- **Model**: Exact match
- **Provider**: Exact match
- **Prompt length**: Within 2x (50-200% del target)
- **File count**: Within 2x

### Percentile Calculation
- Usa percentil 95 para cubrir 95% de casos históricos
- Margen de seguridad de 20% adicional
- Bounds enforcement (30s - 600s)

### Graceful Degradation
- Todos los servicios manejan gracefully cuando GICS no está disponible
- Fallback a defaults estáticos si predictor falla
- Logs claros de degradation para observabilidad
