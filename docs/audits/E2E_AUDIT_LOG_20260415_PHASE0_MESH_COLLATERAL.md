# Phase 0 — Auditoría de daño colateral a GIMO Mesh desde el sprint de tech debt 2026-04-15

**Fecha**: 2026-04-15
**Rama**: `feature/gimo-mesh`
**Motivo**: antes de implementar el selector de runtime de server mode, verificar que los 16 commits del sprint de limpieza `zero tech debt pre-export Android` no rompieron ni desconectaron la implementación existente de mesh (precede al sprint).
**Disparador**: "pero si server mode ya existe, significa que parte de los bugs que intentabamos limpiar estan dentro, por que esa implementacion fue de antes de la limpieza en gimo core."

## Resumen ejecutivo

- **ROTO**: 0 hallazgos
- **DESCONECTADO**: 2 hallazgos (ambos pre-existentes al sprint, no causados por él)
- **OK**: 7 verificaciones pasaron en verde

**Conclusión**: el sprint NO causó daño colateral a mesh. Se puede proceder con la implementación del selector de runtime sin trabajo preparatorio. Los 2 hallazgos DESCONECTADO son gaps de producto que ya existían antes del sprint y no bloquean el export.

## Matriz de capacidades

| Capacidad | Estado | Evidencia |
|---|---|---|
| Import de todos los módulos mesh | OK | `from tools.gimo_server.services.mesh import ...` sin fallos |
| `DeviceMode` enum con `server` | OK | `['inference', 'utility', 'server', 'hybrid']` |
| 44 rutas `/ops/mesh/*` registradas | OK | app boot 301 routes totales |
| Host bootstrap con env vars Android | OK | enroll `phase0-smoke` con `device_mode=server` → `connected` |
| Runtime JSON file escrito | OK | `.orch_data/ops/mesh/host_runtime.json` con `device_mode: "server"` |
| Tests unitarios mesh | OK | 45 passed in 2.51s — tests reales (FS temp vía monkeypatch), no mocks de servicios |
| Endpoints que Android invoca | OK | `/health`, `/ready`, `/ops/shutdown`, `/ops/mesh/heartbeat`, `/ops/mesh/devices`, `/ops/mesh/status`, `/ops/mesh/tasks/poll/{id}`, `/ops/mesh/workspaces`, `/ops/mesh/models` — 9/9 presentes |

## Probes ejecutadas

### Probe 1: imports post-sprint

Buscar en `tools/gimo_server/services/mesh/` referencias a los 16 archivos shim borrados en `a5c994c`:

```
grep -rn "from tools.gimo_server.services.cost_service\|...services.observability_service\|...services.execution_policy_service" tools/gimo_server/services/mesh/
```

**Resultado**: cero matches. Los servicios mesh solo importan de `...config`, `...models.mesh`, y submódulos propios (`.registry`, `.audit`, `.telemetry`, `.dispatch`, `.enrollment`, `.host_bootstrap`).

### Probe 2: asyncio migration blast radius (058bc76)

```
grep -rn "asyncio.get_event_loop" tools/gimo_server/services/mesh/
```

**Resultado**: cero matches. El código mesh nunca usó el API deprecated, así que el commit no le afecta.

### Probe 3: live boot smoke con mesh host enabled

Con las 8 env vars que Android setea en `EmbeddedCoreRunner.kt:190-198`:

```
GIMO_MESH_HOST_ENABLED=true
GIMO_MESH_HOST_DEVICE_ID=phase0-smoke
GIMO_MESH_HOST_DEVICE_NAME="Phase0 Smoke"
GIMO_MESH_HOST_DEVICE_MODE=server
GIMO_MESH_HOST_DEVICE_CLASS=smartphone
GIMO_MESH_HOST_INFERENCE_ENDPOINT=""
```

Resultado:

```
APP_ROUTES: 301
HOST_ENABLED: True
HOST_MODE: DeviceMode.server
DEVICE_ID: phase0-smoke
DEVICE_MODE: server
CONNECTION_STATE: connected
RUNTIME_PATH: True
CLEANUP: OK
```

Log interno confirma el flujo completo:
```
INFO:orchestrator.mesh.registry:Enrolled device phase0-smoke (mode=DeviceMode.server)
INFO:gimo.mesh.workspace:member added: phase0-smoke -> workspace default (role=member)
INFO:orchestrator.mesh.host_bootstrap:Android host bootstrap registered phase0-smoke (mode=server)
```

### Probe 4: paridad de env vars Android ↔ Python

| Env var | Android (Kotlin) | Python (consumer) | Match |
|---|---|---|---|
| `ORCH_PORT` | EmbeddedCoreRunner.kt:191 | main.py:494,883 | OK |
| `ORCH_OPERATOR_TOKEN` | EmbeddedCoreRunner.kt:192 | config.py:146,334,487 | OK |
| `GIMO_MESH_HOST_ENABLED` | EmbeddedCoreRunner.kt:193 | host_bootstrap.py:36 | OK |
| `GIMO_MESH_HOST_DEVICE_ID` | EmbeddedCoreRunner.kt:194 | host_bootstrap.py:44 | OK |
| `GIMO_MESH_HOST_DEVICE_NAME` | EmbeddedCoreRunner.kt:195 | host_bootstrap.py:59 | OK |
| `GIMO_MESH_HOST_DEVICE_MODE` | EmbeddedCoreRunner.kt:196 | host_bootstrap.py:49 | OK |
| `GIMO_MESH_HOST_DEVICE_CLASS` | EmbeddedCoreRunner.kt:197 | host_bootstrap.py:61 | OK |
| `GIMO_MESH_HOST_INFERENCE_ENDPOINT` | EmbeddedCoreRunner.kt:198 | host_bootstrap.py:62 | OK |

8/8 match 1:1. No hay drift entre las dos caras.

### Probe 5: endpoints Android-side → Python-side

| Android call | Path | Existe |
|---|---|---|
| `GimoCoreClient.sendHeartbeat()` | `/ops/mesh/heartbeat` | OK |
| `GimoCoreClient.getDevices()` | `/ops/mesh/devices` | OK |
| `GimoCoreClient.getDevice(id)` | `/ops/mesh/devices/{device_id}` | OK |
| `GimoCoreClient.getMeshStatus()` | `/ops/mesh/status` | OK |
| `GimoCoreClient.pollTasks(id)` | `/ops/mesh/tasks/poll/{device_id}` | OK |
| `GimoCoreClient.listWorkspaces()` | `/ops/mesh/workspaces` | OK |
| `OnboardingClient.getModels()` | `/ops/mesh/models` | OK |
| `EmbeddedCoreRunner.isHealthy()` | `/health` | OK |
| `EmbeddedCoreRunner.isReady()` | `/ready` | OK |
| `EmbeddedCoreRunner.requestShutdown()` | `/ops/shutdown` | OK |

### Probe 6: calidad de los tests mesh (real vs mocks)

`tests/unit/test_mesh_e2e.py` (705 LOC, 45 tests):
- Monkeypatcha rutas de FS a un `tmpdir` (registry, enrollment, telemetry, audit)
- **No** mocks de servicios. Instancia `MeshRegistry()`, `EnrollmentService(registry)`, `TelemetryService()`, `MeshAuditService()` reales.
- Verifica estado real (device objects, thermal profiles, audit entries) con asserts semánticos.
- Incluye integration test `test_full_mesh_lifecycle` que recorre 12 pasos: enroll → approve → heartbeat → dispatch → thermal warning → throttle → lockout → cleanup.
- Cumple con el criterio AGENTS.md: "tests that validate outcomes, not implementation".

Ejecución actual:

```
pytest tests/unit/test_mesh_e2e.py
45 passed in 2.51s
```

### Probe 7: /ui/* removal (dabf44d)

```
grep -rn "/ui/" apps/android/gimomesh/
```

**Resultado**: cero matches. Android siempre usó `/ops/*` canónico. El commit que eliminó `legacy_ui_router.py` no afecta al cliente Android.

## Hallazgos DESCONECTADO (pre-existentes al sprint)

### [D-1] `ModelRecommendationEngine` nunca emite `recommended_mode = "server"`

**Archivo**: `tools/gimo_server/services/mesh/model_recommendation.py:289-295`

```python
if rec.fit_level == FitLevel.overload:
    rec.recommended_mode = "utility"
elif rec.fit_level == FitLevel.tight:
    rec.recommended_mode = "hybrid"
else:
    rec.recommended_mode = "inference"
```

**Gap**: el motor de recomendación devuelve solo 3 de los 4 valores del enum `DeviceMode`. `server` solo entra por ruta explícita del bootstrap Android (env var `GIMO_MESH_HOST_DEVICE_MODE=server`).

**Origen**: pre-sprint, no causado por los 16 commits.

**Impacto para server mode selector**: bajo. El selector que vamos a añadir es ortogonal a `recommended_mode` (es sobre runtime, no sobre modo de dispositivo). Pero deja un hueco conceptual: un dispositivo con hardware potente nunca recibiría sugerencia `server` automática.

**Acción**: registrar como finding para seguimiento; no bloquea server mode runtime selector.

### [D-2] Servicios mesh no reportan a `ObservabilityService`

**Archivos**: ningún archivo en `tools/gimo_server/services/mesh/` importa `observability_service` ni `observability_pkg`.

**Gap**: los eventos de mesh (enrollment, dispatch decisions, thermal events) se persisten en logs dedicados (`audit.jsonl`, `thermal_events.jsonl`, `thermal_profiles/*.json`) pero no emiten spans a `UnifiedObservabilityService`. Un dashboard de observabilidad no ve tráfico mesh.

**Origen**: pre-sprint. El servicio `ObservabilityService` canonicalizado en el sprint (commit 5ac9c31) nunca fue consumido por mesh.

**Impacto para server mode selector**: bajo. La decisión de runtime quedará capturada en `device_mode` / nuevo campo `device_runtime`; el observability gap es separado.

**Acción**: registrar para sprint futuro de observabilidad mesh; no bloquea server mode runtime selector.

## Hallazgos ROTO

Ninguno.

## Verificación de invariante mesh-off

`tests/unit/test_boot_mesh_disabled.py` (añadido en commit `1f7bdcc` durante el sprint) garantiza que GIMO Core bootea sin mesh. Confirmado en el sprint verification suite (1665/1 skipped).

## Conclusión

El sprint de 16 commits (f640044 → dabf44d) no causó daño colateral a GIMO Mesh. Las razones:

1. **Aislamiento estructural**: mesh es un subpaquete autocontenido en `services/mesh/` que ya usaba imports canónicos (no dependía de los 16 shims borrados).
2. **Nunca usó APIs deprecated**: no usaba `asyncio.get_event_loop()` ni `/ui/*` ni el módulo `observability.py` simple.
3. **Tests reales**: el suite de 45 tests verifica comportamiento real con FS temporal; no se rompieron con la refactorización.
4. **Env vars estables**: las 8 variables del contrato Android↔Python no cambiaron.

**Estado post-Phase-0**: `DONE`. Desbloqueado para proceder con la implementación del plan Phase 3 (E2E_ENGINEERING_PLAN_20260415_SERVER_MODE_RUNTIMES.md) sin trabajo preparatorio.

Los 2 hallazgos DESCONECTADO (D-1 y D-2) son deuda técnica pre-existente, no bloquean el export ni el runtime selector.

## Resultado

- `[GOAL]` Determinar si el sprint de tech debt rompió mesh
- `[INPUT DATA]` 16 commits sprint + código mesh pre-existente + tests/unit/test_mesh_e2e.py + Android gimomesh app
- `[PLAN]` 7 probes (imports, asyncio migration, live boot, env vars, endpoints, tests reales, /ui removal)
- `[CHANGES]` Ninguno (solo auditoría)
- `[VERIFICATION]` 45/45 mesh tests pass; live boot con server mode → `connected`; 8/8 env vars match; 9/9 endpoints existen
- `[RESULT]` 0 ROTO, 2 DESCONECTADO pre-existentes, mesh intacto
- `[RISKS]` Ninguno bloqueante para Phase 4
- `[STATUS]` DONE
