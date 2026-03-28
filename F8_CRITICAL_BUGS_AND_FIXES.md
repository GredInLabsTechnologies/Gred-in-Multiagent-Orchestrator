# F8 CRITICAL BUGS AND FIXES

## 🚨 BUGS ENCONTRADOS

### BUG #1: RACE CONDITION CRÍTICA (preset_telemetry_service.py)
**Severidad**: CRÍTICA
**Archivos**: `services/preset_telemetry_service.py` líneas 55-62, 90-144

**Problema**:
```python
# NO ES ATÓMICO
current = cls._get_or_init(key, task_semantic, preset_name)  # GET
current["samples"] += 1                                        # MODIFY in memory
GicsService.put(key, current)                                 # PUT
```

Si dos threads ejecutan simultáneamente:
- Thread A: GET (samples=10)
- Thread B: GET (samples=10)
- Thread A: samples++ → 11, PUT
- Thread B: samples++ → 11, PUT ❌ (debería ser 12)

**Impacto**:
- Pérdida de datos de telemetría
- Success rates incorrectos
- Counts no confiables
- Advisory engine toma decisiones con datos corruptos

**Solución**:
Usar operaciones atómicas de GICS o implementar locking.

---

### BUG #2: RUNNING AVERAGE INCORRECTO (preset_telemetry_service.py)
**Severidad**: CRÍTICA
**Archivo**: `services/preset_telemetry_service.py` líneas 115-122

**Problema**:
```python
93→  current["samples"] += 1          # ← samples incrementado AQUÍ
...
116→ n = current["samples"] - 1       # ← usa samples YA incrementado
117→ if n == 0:
118→     current["avg_latency_ms"] = latency_ms
119→ else:
120→     current["avg_latency_ms"] = (
121→         (current["avg_latency_ms"] * n + latency_ms) / current["samples"]
122→     )                               # ← MATEMÁTICA INCORRECTA
```

**Cálculo actual** (INCORRECTO):
- samples ya fue incrementado a N+1 en línea 93
- n = (N+1) - 1 = N
- Formula usa: `(old_avg * N + new_value) / (N+1)`
- Esto es CORRECTO **SI** n se calcula ANTES del incremento
- Pero aquí n se calcula DESPUÉS, causando double-counting

**Impacto**:
- Avg_latency_ms incorrectos
- Convergencia lenta o divergente
- Métricas no confiables

**Fix correcto**:
```python
# OPCIÓN 1: Guardar old_samples ANTES de incrementar
old_samples = current["samples"]
current["samples"] += 1

if old_samples == 0:
    current["avg_latency_ms"] = latency_ms
else:
    current["avg_latency_ms"] = (
        (current["avg_latency_ms"] * old_samples + latency_ms) / current["samples"]
    )

# OPCIÓN 2: Usar samples-1 consistentemente
if latency_ms is not None:
    if current["samples"] == 0:
        current["avg_latency_ms"] = latency_ms
    else:
        n = current["samples"] - 1  # ANTES del incremento
        current["avg_latency_ms"] = (
            (current["avg_latency_ms"] * n + latency_ms) / (n + 1)
        )
    # Ahora sí incrementar
    current["samples"] += 1
```

---

### BUG #3: MISMO PROBLEMA EN AVG_COST_USD (preset_telemetry_service.py)
**Severidad**: CRÍTICA
**Archivo**: `services/preset_telemetry_service.py` líneas 124-131

**Problema**: Idéntico a BUG #2, pero para `avg_cost_usd`

```python
93→  current["samples"] += 1          # ← samples incrementado
...
125→ n = current["samples"] - 1       # ← usa samples YA incrementado
129→     current["avg_cost_usd"] = (
130→         (current["avg_cost_usd"] * n + cost_usd) / current["samples"]
131→     )                             # ← MATEMÁTICA INCORRECTA
```

**Fix**: Mismo que BUG #2

---

### BUG #4: TYPE HINT INCORRECTO (feedback_collector.py)
**Severidad**: MENOR (no afecta runtime, pero causa warnings de type checker)
**Archivo**: `services/feedback_collector.py` líneas 38, 143

**Problema**:
```python
38→  ) -> Tuple[float, Dict[str, any]]:  # ❌ 'any' minúscula
...
143→ ) -> Optional[Dict[str, any]]:       # ❌ 'any' minúscula
```

**Fix**:
```python
from typing import Any  # Ya está importado

) -> Tuple[float, Dict[str, Any]]:   # ✅
) -> Optional[Dict[str, Any]]:        # ✅
```

---

## 📋 PLAN DE CORRECCIÓN

### Prioridad 1: BUG #1 (Race Condition)

**Estrategia A: Locking (más simple)**
```python
import threading

class PresetTelemetryService:
    _locks: Dict[str, threading.Lock] = {}
    _locks_lock = threading.Lock()

    @classmethod
    def _get_lock(cls, key: str) -> threading.Lock:
        with cls._locks_lock:
            if key not in cls._locks:
                cls._locks[key] = threading.Lock()
            return cls._locks[key]

    @classmethod
    def record_outcome(cls, ...):
        key = f"ops:preset_telemetry:{task_semantic}:{preset_name}"

        with cls._get_lock(key):  # ← LOCK CRÍTICO
            current = cls._get_or_init(key, task_semantic, preset_name)
            # ... todo el código de update ...
            GicsService.put(key, current)
```

**Estrategia B: GICS Atomic Operations (ideal pero requiere cambios en GICS)**
```python
# Si GicsService soporta operaciones atómicas:
GicsService.atomic_increment(key, "samples", 1)
GicsService.atomic_increment(key, "successes", 1 if success else 0)
```

### Prioridad 2: BUG #2 y #3 (Running Average)

**Fix inmediato**:
```python
@classmethod
def record_outcome(cls, ...):
    # ... código inicial ...

    # GUARDAR old_samples ANTES de cualquier incremento
    old_samples = current["samples"]

    # Actualizar counters
    current["samples"] += 1
    current["execution_count"] += 1
    # ... resto de counters ...

    # Actualizar promedios usando old_samples
    if quality_score is not None:
        n = current["quality_samples"]  # Este es diferente, OK
        if n == 0:
            current["avg_quality_score"] = quality_score
        else:
            current["avg_quality_score"] = (
                (current["avg_quality_score"] * n + quality_score) / (n + 1)
            )
        current["quality_samples"] += 1

    if latency_ms is not None:
        if old_samples == 0:  # ← usar old_samples
            current["avg_latency_ms"] = latency_ms
        else:
            current["avg_latency_ms"] = (
                (current["avg_latency_ms"] * old_samples + latency_ms) / current["samples"]
            )

    if cost_usd is not None:
        if old_samples == 0:  # ← usar old_samples
            current["avg_cost_usd"] = cost_usd
        else:
            current["avg_cost_usd"] = (
                (current["avg_cost_usd"] * old_samples + cost_usd) / current["samples"]
            )
```

### Prioridad 3: BUG #4 (Type Hints)

Simplemente cambiar `any` → `Any` en líneas 38 y 143.

---

## 🧪 TESTS NECESARIOS

### Test para Race Condition
```python
import asyncio
import pytest
from tools.gimo_server.services.preset_telemetry_service import PresetTelemetryService

@pytest.mark.asyncio
async def test_record_outcome_concurrent_no_race():
    """Verificar que múltiples threads no causan race condition."""

    # Seed inicial
    PresetTelemetryService.record_outcome(
        "planning", "test_preset", True, quality_score=50.0
    )

    # 100 updates concurrentes
    tasks = []
    for i in range(100):
        task = asyncio.create_task(
            asyncio.to_thread(
                PresetTelemetryService.record_outcome,
                "planning", "test_preset", True, quality_score=50.0 + i
            )
        )
        tasks.append(task)

    await asyncio.gather(*tasks)

    # Verificar que samples = 101 (1 inicial + 100 concurrent)
    telemetry = PresetTelemetryService.get_telemetry("planning", "test_preset")
    assert telemetry["samples"] == 101, f"Expected 101, got {telemetry['samples']}"
    assert telemetry["successes"] == 101
```

### Test para Running Average
```python
def test_running_average_correctness():
    """Verificar que el promedio móvil es matemáticamente correcto."""

    # Clear state
    from tools.gimo_server.services.gics_service import GicsService
    key = "ops:preset_telemetry:test:avg_test"
    GicsService.delete(key)

    # Agregar valores conocidos
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    expected_avg = sum(values) / len(values)  # 30.0

    for v in values:
        PresetTelemetryService.record_outcome(
            "test", "avg_test", True, latency_ms=v
        )

    telemetry = PresetTelemetryService.get_telemetry("test", "avg_test")

    # Verificar promedio
    assert abs(telemetry["avg_latency_ms"] - expected_avg) < 0.01, \
        f"Expected {expected_avg}, got {telemetry['avg_latency_ms']}"

    # Verificar samples
    assert telemetry["samples"] == 5
```

---

## ⚠️ RIESGO SI NO SE CORRIGE

### Sin Fix BUG #1 (Race Condition):
- ❌ Datos de telemetría corruptos
- ❌ Advisory engine toma decisiones incorrectas
- ❌ Degradación silenciosa del sistema
- ❌ Imposible debuggear (non-deterministic)

### Sin Fix BUG #2/3 (Running Average):
- ❌ Convergencia incorrecta de promedios
- ❌ Bias sistemático en métricas
- ❌ Advisory scores incorrectos
- ❌ Malas decisiones de routing

### Sin Fix BUG #4 (Type Hints):
- ⚠️ Warnings en type checkers (mypy, pyright)
- ⚠️ Confusión para desarrolladores
- ⚠️ No afecta runtime

---

## ✅ VERIFICACIÓN POST-FIX

1. **Tests unitarios pasan**: `pytest tests/unit/test_preset_telemetry_*.py -v`
2. **Tests de concurrencia**: Verificar race conditions
3. **Verificación manual**:
   ```python
   # Ejecutar 10 veces y verificar consistencia
   for i in range(10):
       PresetTelemetryService.record_outcome("test", "test", True, quality_score=50.0)

   t = PresetTelemetryService.get_telemetry("test", "test")
   assert t["samples"] == 10  # Must be exactly 10
   ```
4. **Type checking**: `mypy services/feedback_collector.py --strict`

---

## 📊 IMPACTO ESTIMADO

| Bug | Severidad | Impacto en Producción | Tiempo Fix |
|-----|-----------|------------------------|------------|
| #1 Race Condition | **CRÍTICA** | Alto - datos corruptos | 30 min |
| #2 Avg Latency | **CRÍTICA** | Medio - métricas incorrectas | 10 min |
| #3 Avg Cost | **CRÍTICA** | Medio - métricas incorrectas | 5 min (mismo fix) |
| #4 Type Hints | **MENOR** | Bajo - solo warnings | 2 min |

**Total tiempo estimado de fix**: ~45 minutos
**Prioridad de deploy**: INMEDIATA (antes de uso en producción)
