# Sistema de Ejecución Adaptativa (SEA)

**Adaptive Execution System** — Timeouts adaptativos, streaming de progreso y operaciones resumibles para GIMO.

---

## Visión General

El Sistema de Ejecución Adaptativa (SEA) resuelve los problemas fundamentales de timeout en sistemas LLM multi-agente:

### Problemas que Resuelve

1. **Timeouts arbitrarios** → CLI usa 180s fijo sin considerar la operación real
2. **Ansiedad del usuario** → No sabe si la operación está colgada o procesando
3. **Pérdida de progreso** → Si timeout → pierde todo el trabajo
4. **Sin retry inteligente** → Falla una vez → usuario debe reintentar manualmente
5. **Sin visibilidad** → No hay trace de dónde se consume el tiempo

### Solución: 7 Fases Integradas

```
┌─────────────────────────────────────────────────────────────────┐
│  Phase 1: Duration Telemetry (Foundation)                       │
│  ↓ Captura duraciones reales en GICS                           │
├─────────────────────────────────────────────────────────────────┤
│  Phase 2: Adaptive Timeout Predictor                            │
│  ↓ Predice timeout óptimo basado en historial                  │
├─────────────────────────────────────────────────────────────────┤
│  Phase 3: SSE Progress Streaming                                │
│  ↓ Feedback en tiempo real al usuario                          │
├─────────────────────────────────────────────────────────────────┤
│  Phase 4: Deadline Propagation                                  │
│  ↓ Backend conoce tiempo restante                              │
├─────────────────────────────────────────────────────────────────┤
│  Phase 5: Checkpointing (Resumable Operations)                  │
│  ↓ Guarda estado intermedio, permite reanudar                   │
├─────────────────────────────────────────────────────────────────┤
│  Phase 6: Circuit Breaker + Intelligent Retry                   │
│  ↓ Retry inteligente con detección colectiva de degradation    │
├─────────────────────────────────────────────────────────────────┤
│  Phase 7: Graceful Degradation (Partial Results)                │
│  ↓ Retorna resultados parciales útiles si timeout inevitable   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Fase 1: Telemetría de Duración ✅

### Objetivo
Establecer la foundation capturando duraciones reales de operaciones para entrenar el predictor.

### Arquitectura

```python
# Schema GICS
ops:duration:{operation}:{timestamp_ms} → {
    operation: str,           # "plan", "run", "merge"
    duration_s: float,        # Duración en segundos
    success: bool,            # Si completó exitosamente
    context: {                # Metadata contextual
        model: str,           # e.g., "claude-3-5-sonnet"
        provider: str,        # e.g., "anthropic"
        prompt_length: int,   # Para plans
        file_count: int,      # Para runs
        complexity: str,      # "simple", "moderate", "complex"
    },
    timestamp: int            # Unix timestamp
}
```

### Implementación

**DurationTelemetryService** (`services/timeout/duration_telemetry_service.py`):
```python
class DurationTelemetryService:
    @staticmethod
    def record_operation_duration(
        operation: str,
        duration: float,
        context: dict,
        success: bool
    ) -> str:
        """Almacena métrica en GICS."""

    @staticmethod
    def get_historical_durations(
        operation: str,
        context: dict = None,
        limit: int = 100
    ) -> List[float]:
        """Recupera duraciones similares."""

    @staticmethod
    def get_stats_for_operation(operation: str) -> dict:
        """Estadísticas agregadas: avg, p50, p95, max."""
```

**Context Similarity Matching**:
- **Model**: Exact match (claude-3-5-sonnet != gpt-4)
- **Provider**: Exact match (anthropic != openai)
- **Prompt length**: Within 2x (100-200 chars similar a 150 chars)
- **File count**: Within 2x (5-10 files similar a 7 files)

### Instrumentación

**Plan generation** (`routers/ops/plan_router.py`):
```python
start_time = time.time()
# ... generación del plan ...
duration = time.time() - start_time

DurationTelemetryService.record_operation_duration(
    operation="plan",
    duration=duration,
    context={
        "model": contract.model_id,
        "prompt_length": len(prompt),
        "provider": resp.get("provider"),
    },
    success=(draft.status == "draft")
)
```

**Run execution** (`services/execution/engine_service.py`):
```python
start_time = time.time()
# ... ejecución del run ...
duration = time.time() - start_time

DurationTelemetryService.record_operation_duration(
    operation="run",
    duration=duration,
    context={
        "model": model_used,
        "composition": composition,
        "file_count": file_count,
        "is_child": is_child,
    },
    success=(final_status == "done")
)
```

### Observabilidad

**Endpoint**: `GET /ops/observability/duration-stats?operation={plan|run|merge}`

```json
{
  "operation": "plan",
  "total_samples": 47,
  "success_rate": 0.957,
  "avg_duration_s": 42.3,
  "p50_duration_s": 38.5,
  "p95_duration_s": 67.2,
  "max_duration_s": 89.1
}
```

---

## Fase 2: Predictor de Timeout Adaptativo ✅

### Objetivo
Predecir timeout óptimo basándose en historial real + ajustes contextuales inteligentes.

### Algoritmo

```
1. Consulta GICS: ops:duration:{operation}:*
   ↓
2. Filtra por similitud de contexto
   ↓ (model, prompt_length, file_count)
3. Calcula Percentil 95
   ↓ (cubre 95% de casos históricos)
4. Aplica Ajustes Contextuales:
   ├─ Model: Opus +50%, Haiku -20%
   ├─ System Load: High +30%, Low -10%
   ├─ Complexity: Complex +40%, Simple -30%
   ├─ Prompt Length: >1000 chars +20%
   └─ File Count: >10 files +30%, >5 +15%
   ↓
5. Margen de Seguridad: +20%
   ↓
6. Bounds Enforcement: [30s, 600s]
   ↓
   Timeout Óptimo
```

### Implementación

**AdaptiveTimeoutService** (`services/timeout/adaptive_timeout_service.py`):
```python
class AdaptiveTimeoutService:
    # Defaults por operación
    DEFAULT_TIMEOUTS = {
        "plan": 180.0,
        "run": 300.0,
        "merge": 60.0,
        "recon": 120.0,
        "validate": 30.0,
    }

    # Safety bounds
    MIN_TIMEOUT = 30.0
    MAX_TIMEOUT = 600.0
    PERCENTILE = 95
    SAFETY_MARGIN = 1.2

    @classmethod
    def predict_timeout(
        cls,
        operation: str,
        context: dict = None
    ) -> float:
        """Predice timeout óptimo."""

    @classmethod
    def get_confidence_level(
        cls,
        operation: str,
        context: dict = None
    ) -> str:
        """Retorna: high (>50 samples), medium (10-50), low (<10)."""

    @classmethod
    def recommend_timeout_with_metadata(
        cls,
        operation: str,
        context: dict = None
    ) -> dict:
        """Predicción + metadata completo."""
```

### Integración con Capabilities

**CapabilitiesService** (`services/capabilities_service.py`):
```python
# Antes (hardcoded):
if load_level == "critical":
    gen_timeout = 300
elif load_level == "caution":
    gen_timeout = 240
else:
    gen_timeout = 120

# Ahora (adaptativo):
gen_timeout = AdaptiveTimeoutService.predict_timeout(
    operation="plan",
    context={
        "model": active_model,
        "system_load": load_level,
    }
)
```

**CLI smart timeout** (`gimo_cli/api.py`):
```python
def smart_timeout(path: str, config: dict) -> float:
    caps = fetch_capabilities(config)
    hints = caps.get("hints", {})

    if "/generate-plan" in path:
        return hints.get("generation_timeout_s", 180)  # Dinámico!
    if "/stream" in path:
        return None  # Sin timeout para SSE
    return hints.get("default_timeout_s", 15)
```

### Fallback Seguro

Si predictor falla:
1. Intenta usar historial sin filtrado contextual
2. Si no hay historial → usa DEFAULT_TIMEOUTS
3. Si todo falla → fallback a timeouts estáticos por load

```python
try:
    timeout = AdaptiveTimeoutService.predict_timeout(...)
except Exception:
    # Graceful degradation
    timeout = DEFAULT_TIMEOUTS.get(operation, 60.0)
```

---

## Fase 3: SSE Progress Streaming 🔄

### Objetivo
Proporcionar feedback en tiempo real al usuario durante operaciones largas.

### Arquitectura de Eventos

```
Cliente (CLI/UI)                    Server (FastAPI)
      │                                    │
      ├─ GET /ops/generate-plan-stream ──→│
      │                                    ├─ Predice duración
      │                                    │
      │←── event: started ─────────────────┤
      │    data: {                         │
      │      operation: "plan",            │
      │      estimated_duration: 85.5      │
      │    }                               │
      │                                    │
      │←── event: progress ────────────────┤
      │    data: {                         │
      │      stage: "analyzing_prompt",    │
      │      progress: 0.15,               │
      │      elapsed: 12.3,                │
      │      remaining: 73.2               │
      │    }                               │
      │                                    │
      │←── event: progress ────────────────┤
      │    data: {                         │
      │      stage: "generating_tasks",    │
      │      progress: 0.65,               │
      │      elapsed: 55.4,                │
      │      remaining: 30.1               │
      │    }                               │
      │                                    │
      │←── event: checkpoint ──────────────┤
      │    data: {                         │
      │      checkpoint_id: "ckpt_...",    │
      │      resumable: true               │
      │    }                               │
      │                                    │
      │←── event: completed ───────────────┤
      │    data: {                         │
      │      result: {...},                │
      │      duration: 82.7                │
      │    }                               │
      │                                    │
      │    (connection closes)             │
```

### Implementación

**ProgressEmitter** (`services/timeout/progress_emitter.py`):
```python
class ProgressEmitter:
    def __init__(self, emit_fn: Callable):
        self.emit_fn = emit_fn
        self.start_time = time.time()
        self.estimated_duration = None

    async def emit_started(self, operation: str, estimated: float):
        """Emite evento de inicio con ETA."""

    async def emit_progress(self, stage: str, progress: float):
        """Emite progreso (0.0-1.0) con tiempo restante."""

    async def emit_checkpoint(self, checkpoint_id: str):
        """Emite que se guardó checkpoint."""

    async def emit_completed(self, result: dict):
        """Emite resultado final."""
```

**Streaming endpoint** (`routers/ops/plan_router.py`):
```python
@router.post("/generate-plan-stream")
async def generate_plan_stream(
    request: Request,
    prompt: str = Query(...),
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """Genera plan con SSE progress updates."""

    async def event_generator():
        # 1. Predecir duración
        estimated = AdaptiveTimeoutService.predict_timeout(
            "plan",
            context={...}
        )

        emitter = ProgressEmitter(...)
        await emitter.emit_started("plan", estimated)

        # 2. Generar plan con progress updates
        await emitter.emit_progress("analyzing_prompt", 0.1)
        # ... llamada al LLM ...
        await emitter.emit_progress("generating_tasks", 0.5)
        # ... validación ...
        await emitter.emit_progress("validating", 0.9)

        # 3. Completado
        await emitter.emit_completed({"draft_id": draft.id})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

**CLI consumer** (`gimo_cli/commands/plan.py`):
```python
caps = fetch_capabilities(config)
supports_streaming = "plan_streaming" in caps.get("features", [])

if supports_streaming:
    # Usar endpoint streaming
    with httpx.Client(timeout=None) as client:
        with client.stream("POST", f"{base_url}/ops/generate-plan-stream", ...) as resp:
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    event = json.loads(line[5:])

                    if event["type"] == "started":
                        console.print(f"🔮 Estimated: {event['estimated_duration']}s")
                    elif event["type"] == "progress":
                        progress_bar.update(event["progress"])
                    elif event["type"] == "completed":
                        draft = event["result"]
else:
    # Fallback a endpoint sin streaming
    ...
```

### Progress Bar (CLI)

```python
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

with Progress(
    SpinnerColumn(),
    "[progress.description]{task.description}",
    BarColumn(),
    "[progress.percentage]{task.percentage:>3.0f}%",
    TimeElapsedColumn(),
    "~{task.fields[remaining]}s remaining"
) as progress:
    task = progress.add_task("Generating plan...", total=100, remaining=85)

    # Actualizar desde eventos SSE
    progress.update(task, completed=progress_pct*100, remaining=remaining_s)
```

---

## Fase 4: Deadline Propagation 🔄

### Objetivo
Backend conoce exactamente cuánto tiempo tiene para ejecutar → puede cancelar proactivamente.

### Headers

```
Cliente → Server:
  X-GIMO-Deadline: 1735689600.5       # Unix timestamp absoluto
  X-GIMO-Max-Duration: 120.0          # Segundos máximos
```

### Middleware

**DeadlineMiddleware** (`middlewares/deadline_middleware.py`):
```python
class DeadlineMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        deadline_str = request.headers.get("X-GIMO-Deadline")

        if deadline_str:
            deadline = float(deadline_str)
            remaining = deadline - time.time()

            # Validar que hay tiempo suficiente
            if remaining < 5.0:
                return JSONResponse(
                    status_code=408,
                    content={"error": "Deadline already exceeded"}
                )

            # Inyectar en request state
            request.state.deadline = deadline
            request.state.remaining_time = remaining

        return await call_next(request)
```

### Uso en Endpoints

**Plan generation** (`routers/ops/plan_router.py`):
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

**Run execution** (`services/execution/engine_service.py`):
```python
async def execute_run(cls, run_id: str, ...):
    deadline = getattr(request.state, "deadline", None)

    if deadline:
        # Cancelar proactivamente si muy poco tiempo
        if (deadline - time.time()) < 10.0:
            OpsService.update_run_status(
                run_id, "error",
                msg="Insufficient time to complete (deadline approaching)"
            )
            return
```

### CLI Injection

**gimo_cli/api.py**:
```python
def api_request(config, method, path, ...):
    timeout = smart_timeout(path, config)

    if timeout:
        deadline = time.time() + timeout
        headers["X-GIMO-Deadline"] = str(deadline)
        headers["X-GIMO-Max-Duration"] = str(timeout)

    # ... request ...
```

---

## Fase 5: Checkpointing (Operaciones Resumibles) 🔄

### Objetivo
Si operación falla o timeout → usuario puede reanudar desde donde quedó.

### Schema GICS

```
ckpt:{operation}:{operation_id}:{checkpoint_id} → {
    operation: str,           # "plan", "run"
    operation_id: str,        # draft.id, run.id
    state: {                  # Estado resumible
        stage: str,           # "generating_tasks"
        completed_tasks: [...],
        partial_result: {...}
    },
    timestamp: int,
    resumable: bool,
    expires_at: int           # 24h TTL
}
```

### Implementación

**CheckpointService** (`services/checkpoint_service.py`):
```python
class CheckpointService:
    @staticmethod
    def save_checkpoint(
        operation: str,
        operation_id: str,
        state: dict
    ) -> str:
        """Guarda checkpoint con TTL 24h."""

    @staticmethod
    def get_checkpoint(checkpoint_id: str) -> dict:
        """Recupera checkpoint."""

    @staticmethod
    def list_resumable(operation: str) -> List[dict]:
        """Lista checkpoints resumables."""
```

**Instrumentación** (`routers/ops/plan_router.py`):
```python
async def generate_plan_with_checkpoint(...):
    last_checkpoint = time.time()

    async for stage in plan_generation_stages():
        # ... proceso ...

        # Guardar checkpoint cada 15s
        if time.time() - last_checkpoint > 15.0:
            checkpoint_id = CheckpointService.save_checkpoint(
                operation="plan",
                operation_id=draft.id,
                state={
                    "stage": stage.name,
                    "completed_tasks": completed_tasks,
                    "partial_result": {...}
                }
            )

            await emitter.emit("checkpoint", {
                "checkpoint_id": checkpoint_id,
                "resumable": True
            })

            last_checkpoint = time.time()
```

### Resume Endpoint

**checkpoint_router.py**:
```python
@router.post("/ops/{operation}/resume")
async def resume_operation(
    operation: str,
    checkpoint_id: str = Body(...),
    auth: Annotated[AuthContext, Depends(verify_token)]
):
    """Reanuda operación desde checkpoint."""

    checkpoint = CheckpointService.get_checkpoint(checkpoint_id)
    if not checkpoint:
        raise HTTPException(404, "Checkpoint not found")

    state = checkpoint["state"]

    # Continuar desde stage guardado
    # ... reanudar generación ...

    return {"resumed": True, "checkpoint_id": checkpoint_id}
```

### CLI Command

**gimo_cli/commands/resume.py**:
```python
@app.command("resume")
def resume_operation(
    checkpoint_id: str = typer.Argument(...),
):
    """Reanuda operación desde checkpoint."""

    status, payload = api_request(
        config, "POST", "/ops/plan/resume",
        json_body={"checkpoint_id": checkpoint_id}
    )

    console.print(f"[green]✓ Resumed from {checkpoint_id}[/green]")
```

**Flujo de usuario**:
```bash
# Generación interrumpida
$ gimo plan "tarea compleja"
🔮 Estimated: 120s
🚀 [████████░░░] 65% (78s elapsed, ~42s remaining)
   Stage: Generating worker tasks
✓ Checkpoint saved: ckpt_1735689600
^C  # Usuario cancela

# Reanudar más tarde
$ gimo resume ckpt_1735689600
✓ Resumed from checkpoint
🚀 [████████░░░] 65% (continuing...)
   Stage: Generating worker tasks
✓ Plan generated in 162s total (82s actual work)
```

---

## Fase 6: Circuit Breaker + Intelligent Retry 🔄

### Objetivo
Retry inteligente que aprende de fallos colectivos → no reintentar si provider está degradado.

### Circuit Breaker States

```
┌─────────────┐
│   CLOSED    │  Normal operation
│  (working)  │
└──────┬──────┘
       │ failure_count >= threshold
       ↓
┌─────────────┐
│    OPEN     │  Block all, fast-fail
│ (degraded)  │
└──────┬──────┘
       │ recovery_timeout elapsed
       ↓
┌─────────────┐
│ HALF_OPEN   │  Limited test calls
│  (testing)  │
└──────┬──────┘
       │ success → CLOSED
       │ failure → OPEN
```

### Implementación

**CircuitBreaker** (`services/timeout/circuit_breaker.py`):
```python
class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3
    ):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None

    def can_proceed(self) -> bool:
        """Check if operation can proceed."""

    def record_success(self):
        """Reset failure count, transition to CLOSED."""

    def record_failure(self):
        """Increment failures, open if threshold reached."""
```

**IntelligentRetry** (`services/timeout/intelligent_retry.py`):
```python
class IntelligentRetry:
    def __init__(self):
        self.circuit_breaker = CircuitBreaker(...)
        self.backoff = ExponentialBackoff(
            base_delay=1.0,
            max_delay=32.0,
            multiplier=2.0
        )

    async def execute_with_retry(
        self,
        operation: Callable,
        operation_name: str,
        max_retries: int = 3
    ):
        """Execute with retry + circuit breaker."""

        attempt = 0
        while attempt < max_retries:
            # 1. Check circuit breaker
            if not self.circuit_breaker.can_proceed():
                raise CircuitBreakerOpenError(...)

            try:
                result = await operation()
                self.circuit_breaker.record_success()
                return result

            except TimeoutError:
                self.circuit_breaker.record_failure()

                # 2. Check collective intelligence (GICS)
                recent_timeouts = gics.count_prefix(
                    f"ops:timeout:{operation_name}:",
                    # Filtrar por last_minutes=5
                )

                if recent_timeouts > 10:
                    # Provider degraded colectivamente
                    raise ProviderDegradedError(...)

                # 3. Retry con backoff
                delay = self.backoff.next_delay(attempt)
                await asyncio.sleep(delay)
                attempt += 1

        raise MaxRetriesExceededError(...)
```

### Collective Intelligence

**Timeout tracking in GICS**:
```python
# Cuando ocurre timeout
gics.put(f"ops:timeout:{operation}:{timestamp_ms}", {
    "operation": operation,
    "provider": provider,
    "model": model,
    "timestamp": time.time()
})

# Consultar degradation colectiva
recent_count = gics.count_prefix(f"ops:timeout:{operation}:")
if recent_count > THRESHOLD:
    # Provider está degradado → no retry
    raise ProviderDegradedError()
```

### CLI Integration

**gimo_cli/api.py**:
```python
retry_service = IntelligentRetry()

async def api_request_with_retry(config, method, path, ...):
    async def operation():
        return await api_request(config, method, path, ...)

    return await retry_service.execute_with_retry(
        operation,
        operation_name=path.split("/")[-1],
        max_retries=3
    )
```

---

## Fase 7: Graceful Degradation (Resultados Parciales) 🔄

### Objetivo
Si timeout inevitable → devolver resultado parcial útil en vez de nada.

### Priorización de Fases

```python
# Para plan generation
priority_phases = [
    "orchestrator",      # CRÍTICO: coordinación
    "core_workers"       # CRÍTICO: trabajo real
]

optional_phases = [
    "tests",            # OPCIONAL: testing
    "docs",             # OPCIONAL: documentación
    "ci_cd"             # OPCIONAL: pipeline
]
```

### Implementación

**plan_router.py con degradation**:
```python
async def generate_plan_with_graceful_degradation(...):
    deadline = request.state.deadline

    partial_plan = {
        "tasks": [],
        "status": "in_progress",
        "completed_phases": []
    }

    # 1. Generar fases prioritarias primero
    for phase in priority_phases:
        remaining = deadline - time.time()
        if remaining < 10.0:
            logger.warning("Approaching deadline, skipping optional phases")
            break

        tasks = await generate_phase_tasks(
            phase,
            timeout=remaining * 0.8
        )
        partial_plan["tasks"].extend(tasks)
        partial_plan["completed_phases"].append(phase)

    # 2. Generar opcionales si hay tiempo
    for phase in optional_phases:
        remaining = deadline - time.time()
        if remaining < 5.0:
            break

        try:
            tasks = await generate_phase_tasks(
                phase,
                timeout=remaining * 0.8
            )
            partial_plan["tasks"].extend(tasks)
            partial_plan["completed_phases"].append(phase)
        except TimeoutError:
            logger.info(f"Skipped optional phase {phase}")

    # 3. Validar viabilidad de resultado parcial
    if is_valid_partial_plan(partial_plan):
        partial_plan["status"] = "partial_success"
        partial_plan["message"] = (
            f"Generated {len(partial_plan['tasks'])} core tasks. "
            f"Skipped: {', '.join(set(optional_phases) - set(partial_plan['completed_phases']))}"
        )
        return partial_plan
    else:
        raise InsufficientTimeError(
            "Not enough time for minimum viable plan"
        )
```

### Validación de Viabilidad

```python
def is_valid_partial_plan(plan: dict) -> bool:
    """Determina si plan parcial es ejecutable."""

    # Requisitos mínimos
    has_orchestrator = any(
        t.get("role") == "orchestrator"
        for t in plan["tasks"]
    )
    has_workers = any(
        t.get("role") == "worker"
        for t in plan["tasks"]
    )

    # Plan mínimo viable: 1 orchestrator + 1 worker
    return has_orchestrator and has_workers
```

### UI/CLI Feedback

```bash
$ gimo plan "tarea muy compleja" --timeout 30

🔮 Estimated: 85s (based on 47 similar operations)
⚠️  Warning: Requested timeout (30s) is below estimate

🚀 [██████████░░] 75% (22s elapsed, ~8s remaining)
   Stage: Generating core workers

⚠️  Deadline approaching — skipping optional phases

✓ Plan generated (partial)
  ├─ Core phases: ✓ orchestrator, ✓ core_workers
  ├─ Skipped: tests, docs, ci_cd
  └─ Tasks: 5 (executable)

💡 Tip: Use `gimo plan --no-timeout` for complete plan generation
```

---

## Arquitectura de Código

```
tools/gimo_server/
├── services/
│   ├── timeout/
│   │   ├── __init__.py
│   │   ├── duration_telemetry_service.py     ✅ Fase 1
│   │   ├── adaptive_timeout_service.py       ✅ Fase 2
│   │   ├── progress_emitter.py               🔄 Fase 3
│   │   ├── circuit_breaker.py                🔄 Fase 6
│   │   └── intelligent_retry.py              🔄 Fase 6
│   │
│   └── checkpoint_service.py                 🔄 Fase 5
│
├── middlewares/
│   └── deadline_middleware.py                🔄 Fase 4
│
└── routers/
    └── ops/
        ├── plan_router.py                    ✅ Instrumentado (Fase 1)
        │                                     🔄 Streaming (Fase 3)
        │                                     🔄 Graceful (Fase 7)
        ├── checkpoint_router.py              🔄 Fase 5
        └── observability_router.py           ✅ Stats endpoint (Fase 1)

gimo_cli/
├── api.py                                    ✅ Smart timeout (Fase 2)
│                                             🔄 Deadline headers (Fase 4)
│                                             🔄 Retry (Fase 6)
└── commands/
    ├── plan.py                               🔄 SSE consumer (Fase 3)
    └── resume.py                             🔄 Resume command (Fase 5)
```

---

## Flujo End-to-End

```
Usuario: gimo plan "Crea una aplicación web completa..."

1. [Fase 2] CLI consulta /ops/capabilities
   → Server predice timeout adaptativo: 127s (basado en 47 ops similares)

2. [Fase 4] CLI envía request con headers:
   X-GIMO-Deadline: 1735689727.5
   X-GIMO-Max-Duration: 127.0

3. [Fase 3] Server inicia streaming SSE:
   event: started
   data: {"operation":"plan","estimated_duration":127.0}

4. [Fase 3] Server emite progreso cada 5-10s:
   event: progress
   data: {"stage":"analyzing_prompt","progress":0.15,"elapsed":19,"remaining":108}

5. [Fase 5] Server guarda checkpoint cada 15s:
   event: checkpoint
   data: {"checkpoint_id":"ckpt_1735689650","resumable":true}

6. [Fase 4] Server monitorea deadline:
   remaining = deadline - time.time()
   if remaining < 10s → priorizar fases críticas (Fase 7)

7. [Fase 1] Server registra duración al completar:
   GICS: ops:duration:plan:1735689727500 → {duration_s: 118.3, success: true}

8. [Fase 3] Server emite completado:
   event: completed
   data: {"result":{draft_id:"..."},"duration":118.3}

9. [Fase 2] Próxima invocación usará esta duración para mejorar predicción

Si falla:
  [Fase 6] Circuit breaker detecta provider degraded → fast-fail
  [Fase 5] Usuario puede reanudar: gimo resume ckpt_1735689650
  [Fase 7] Si timeout inevitable → retorna plan parcial ejecutable
```

---

## Métricas de Éxito

| Métrica | Baseline Actual | Target SEA | Mejora |
|---------|-----------------|------------|--------|
| Timeout rate | ~15% | <5% | 67% ↓ |
| User satisfaction | 3.2/5 | 4.5/5 | 40% ↑ |
| Retry success rate | N/A | >80% | ∞ |
| Estimation accuracy | N/A | ±20% (80% casos) | ∞ |
| Operations con progress | 0% | 100% | ∞ |
| Operations resumables | 0% | 100% | ∞ |
| Lost work (timeout) | 100% | 0% | 100% ↓ |

---

## Observabilidad

### Endpoints

- `GET /ops/observability/duration-stats` — Estadísticas de duración
- `GET /ops/observability/timeout-prediction` — Predicciones actuales
- `GET /ops/observability/circuit-breaker-status` — Estado de circuit breakers
- `GET /ops/observability/checkpoint-health` — Salud de checkpoints

### Logs

```
orchestrator.services.timeout.duration_telemetry   # Fase 1
orchestrator.services.timeout.adaptive_timeout     # Fase 2
orchestrator.services.timeout.progress_emitter     # Fase 3
orchestrator.middlewares.deadline                  # Fase 4
orchestrator.services.checkpoint                   # Fase 5
orchestrator.services.timeout.circuit_breaker      # Fase 6
orchestrator.services.timeout.intelligent_retry    # Fase 6
```

### GICS Schema Summary

```
ops:duration:{operation}:{timestamp_ms}            # Fase 1: Telemetría
ckpt:{operation}:{operation_id}:{checkpoint_id}    # Fase 5: Checkpoints
ops:timeout:{operation}:{timestamp_ms}             # Fase 6: Timeout tracking
```

---

## Próximos Pasos

1. ✅ **Fase 1**: Telemetría de Duración
2. ✅ **Fase 2**: Adaptive Timeout Predictor
3. 🔄 **Fase 3**: SSE Progress Streaming
4. 🔄 **Fase 4**: Deadline Propagation
5. 🔄 **Fase 5**: Checkpointing
6. 🔄 **Fase 6**: Circuit Breaker + Retry
7. 🔄 **Fase 7**: Graceful Degradation

**Tiempo estimado restante**: 18-22 horas (Fases 3-7)

---

## Comandos Útiles

```bash
# Ejecutar tests
pytest tests/unit/test_duration_telemetry.py tests/unit/test_adaptive_timeout.py -v

# Ver estadísticas
curl http://127.0.0.1:9325/ops/observability/duration-stats | jq

# Entrenar predictor con datos
for i in {1..20}; do gimo plan "test task $i"; done

# Probar streaming (Fase 3+)
gimo plan "tarea compleja" --progress

# Reanudar desde checkpoint (Fase 5+)
gimo resume ckpt_1735689650

# Ver estado de circuit breakers (Fase 6+)
curl http://127.0.0.1:9325/ops/observability/circuit-breaker-status | jq
```

---

## Referencias

- **Cursor AI**: Long-running agents (sin progreso intermedio)
- **GitHub Copilot**: SSE streaming + timeout configurable
- **gRPC**: Deadline propagation (concepto clave)
- **Google SRE**: Adaptive timeouts con ML
- **Aider**: Timeout manual

**SEA combina lo mejor de cada sistema** + collective intelligence vía GICS.
