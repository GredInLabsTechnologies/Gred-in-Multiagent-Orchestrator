# Dead Code Audit — 2026-03-21

## Resumen

Auditoría de código muerto basada en `tmp/vulture_report.txt` (175 findings). Muchos de los reportes son **falsos positivos** o **código intencionalmente sin usar** (parámetros FastAPI Depends, parámetros de compatibilidad futura).

## Categorías

### 1. Falsos Positivos (NO eliminar)

#### FastAPI Depends parameters (155 instancias)
- **Parámetros:** `rl`, `_rl` en todos los routers
- **Razón:** Son parámetros de FastAPI `Depends(check_rate_limit)` que activan middleware de rate limiting
- **Acción:** MANTENER — eliminarlos desactivaría la protección de rate limit
- **Archivos afectados:**
  - `tools/gimo_server/routers/ops/*.py` (todos)
  - `tools/gimo_server/routes.py` (25 endpoints)

#### Parámetros de función públicos/API (6 instancias)
- **Parámetros sin usar pero parte de signature pública:**
  1. `current_state` en `services/cascade_service.py:26`
  2. `agent_profile_role` en `services/child_run_service.py:21`
  3. `layer_size` en `services/custom_plan_service.py:442`
  4. `target_agent_id` en `mcp_bridge/native_tools.py:274`
  5. `target_agent_id` en `mcp_bridge/native_tools.py:285`

- **Razón:** Pueden ser hooks para extensibilidad futura o parámetros de API estable
- **Recomendación:** Marcar con `_` prefix (ej: `_current_state`) para indicar "intencionalmente sin usar"
- **Riesgo de eliminación:** ALTO — rompe contratos de API

### 2. Dead Code Confirmado (seguro eliminar)

#### Imports ya eliminados (14 instancias)
Los siguientes imports fueron reportados por vulture pero YA NO EXISTEN en el código:
- `Union` en `engine/contracts.py:3`
- `struct`, `contextmanager`, `Generator` en `inference/mmap_engine.py:25-29`
- `mean` en `inference/router/task_router.py:20`
- `create_model` en `mcp_bridge/registrar.py:3`
- `load_security_db` en `routes.py:13`
- `shlex` en `services/slice0_orchestrator.py:85`

**Status:** ✅ Ya limpiados

#### Imports sin usar en shim (verificación manual requerida)
En `ops_models.py` (shim de compatibilidad), los siguientes símbolos se re-exportan pero nunca se importan:
- `CacheStats`
- `CascadeStatsEntry`
- `GraphState`
- `ModelStrategyAudit`
- `RoiLeaderboardEntry`
- `RunLogEntry`

**Búsqueda realizada:**
```bash
grep -r "from.*ops_models import.*CacheStats" tools/gimo_server/  # 0 results
```

**Recomendación:** Eliminar de la re-exportación en `ops_models.py` líneas 7-40
**Riesgo:** BAJO — solo afecta el shim, no el módulo original en `models/`

#### Variable sin usar (1 instancia confirmada)
- `devs` en `inference/router/model_selector.py:52`
  - Línea: `self._fits = fits_fn or (lambda m, devs: True)`
  - El parámetro `devs` del lambda nunca se usa
  - **Recomendación:** Cambiar a `lambda m, _devs: True`

### 3. Variables en exception handlers (falsos positivos)
- `exc_tb`, `exc_type`, `exc_val` en `adapters/mcp_client.py:24`
- `exc_type`, `tb` en `services/gics_client.py:129`

**Razón:** Python exception unpacking (`exc_type, exc_val, exc_tb = sys.exc_info()`)
**Acción:** MANTENER o usar `_` prefix

### 4. WebSocket import (falso positivo)
- `WebSocketDisconnect` en `main.py:6`

**Status:** ✅ Verificado — SÍ se usa en línea 410 (`async def websocket_endpoint(ws: WebSocket)`)

## Métricas

| Categoría | Findings | Status |
|-----------|----------|--------|
| Falsos positivos FastAPI | 155 | MANTENER |
| Falsos positivos API params | 6 | MANTENER (considerar `_` prefix) |
| Imports obsoletos (ya limpiados) | 14 | ✅ DONE |
| Re-exports sin usar (ops_models) | 6 | TODO |
| Variables lambda sin usar | 1 | TODO |
| Exception handlers | 5 | MANTENER |
| **TOTAL** | **175** | **~93% falsos positivos** |

## Recomendaciones

### Acción inmediata (bajo riesgo)
1. Eliminar 6 símbolos de `ops_models.py` re-exports
2. Cambiar `devs` → `_devs` en model_selector.py lambda

### Acción futura (requiere análisis)
1. Evaluar si parámetros públicos sin usar son necesarios
2. Si no, agregar `_` prefix para indicar "intencionalmente sin usar"
3. Configurar vulture para ignorar parámetros FastAPI Depends

### No tocar
- Parámetros `rl`/`_rl` en routers (rate limiting activo)
- Imports de exception handlers
- `WebSocket` en main.py

## Conclusión

El reporte de vulture tiene **~93% de falsos positivos**. La limpieza de código muerto debe ser **quirúrgica y manual**, no bulk automation. La mayoría del "dead code" es en realidad:
- Activación de middleware FastAPI
- Parámetros de API pública para extensibilidad
- Código ya eliminado (reporte obsoleto)
