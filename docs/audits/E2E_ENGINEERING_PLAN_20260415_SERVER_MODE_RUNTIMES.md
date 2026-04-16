# E2E Engineering Plan — Server Mode Runtime Selector

**Fecha**: 2026-04-15
**Estado**: PROPUESTO — espera aprobación
**Ámbito**: GIMO Mesh — cerrar el gap entre runners funcionales y selector automático
**Inputs**:
- `AGENTS.md` (contrato operativo, backend authority first, legacy hunting)
- `docs/SYSTEM.md` (multi-surface sovereign platform, backend = truth)
- `docs/DEV_MESH_ARCHITECTURE.md` (3 device modes, GICS task pattern intelligence, hardware protection)
- `memory/project_dev_mesh_experiment.md` (mesh product invariants)
- Reconocimiento directo del repo (evidencia inline)

---

## 1. Resumen de diagnóstico

El informe previo planteaba "server mode multi-runtime" como diseño nuevo a persistir. El reconocimiento del repo muestra otra realidad: **los runners existen, la separación conceptual `mode × runtime` no**.

### Lo que ya existe (evidencia)

| Componente | Archivo | Estado |
|---|---|---|
| `DeviceMode` enum (inference / utility / server / hybrid) | [tools/gimo_server/models/mesh.py:10](tools/gimo_server/models/mesh.py:10) | ✅ canónico, usado en registry y tests (`test_mesh_e2e.py:205`) |
| Runner Python embebido | [apps/android/gimomesh/.../EmbeddedCoreRunner.kt:21-283](apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/EmbeddedCoreRunner.kt:21) | ✅ lanza `uvicorn tools.gimo_server.main:app` |
| Runner llama.cpp | [apps/android/gimomesh/.../InferenceRunner.kt:23-60](apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/InferenceRunner.kt:23) | ✅ lanza `llama-server` binario |
| Selector manual `isServeMode()` | [ControlPlaneRuntime.kt:8-13](apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/ControlPlaneRuntime.kt:8) | ✅ lee `settings.deviceMode` |
| `ModelRecommendationEngine` (HW scoring) | [services/mesh/model_recommendation.py:289-295](tools/gimo_server/services/mesh/model_recommendation.py:289) | ⚠️ recomienda `inference/hybrid/utility` — **NO emite `server`** |
| Registry con `device_mode` | [services/mesh/registry.py:14-22](tools/gimo_server/services/mesh/registry.py:14) | ✅ persiste modo por device |
| Docs §2.3 Server Node | [docs/DEV_MESH_ARCHITECTURE.md:110-134](docs/DEV_MESH_ARCHITECTURE.md:110) | ✅ definido conceptualmente |

### El gap real (3 huecos, no 1)

1. **Conflación `mode × runtime`**: el código asume 1:1 entre `DeviceMode` y qué runner se lanza. Un device puede tener `mode=server` y correr `EmbeddedCoreRunner` (Python embebido) O ningún motor de inferencia (server puro). La dimensión **runtime** (kotlin-only, llama.cpp, embedded-core) no existe en el modelo de datos.

2. **`ModelRecommendationEngine` está incompleto**: recomienda modo de inferencia basado en si el modelo cabe. No considera `server` como salida, ni evalúa si el device puede ejecutar GIMO Core embebido (Python runtime + ≥4GB RAM + storage).

3. **Android reporta hardware pero no capacidades de runtime**: el payload de enrollment manda RAM/SoC/storage. No manda "tengo Python runtime instalado" / "tengo llama-server binary" / "solo puedo preprocesar en Kotlin". El backend no puede recomendar runtime porque no sabe qué tiene el device.

El informe del usuario estaba correcto en intuición (*"no hay un server mode, hay un selector"*) pero subestimaba cuánto existe. El plan es **mucho más pequeño** de lo que parecía.

---

## 2. Principios de diseño

Derivados de `AGENTS.md` + memoria proyecto:

1. **Backend authority first** (`AGENTS.md`): la recomendación de runtime se calcula en el backend, no en el Android. Android solo reporta capacidades y consume la recomendación.
2. **Mesh-off invariant** (`project_dev_mesh_experiment.md`): nada de lo que se añada puede requerir `mesh_enabled=True` para que GIMO arranque. El test de `test_boot_mesh_disabled.py` sigue siendo gate.
3. **Hardware protection non-bypassable** (`DEV_MESH_ARCHITECTURE.md §5`): recomendar un runtime **nunca** puede bypassear la matriz de autorización — el runtime selector es advisory, no overrides thermal lockout.
4. **One canonical path** (`AGENTS.md` Plan Quality Standard §9): una sola `ModelRecommendationEngine` — no creamos `RuntimeSelectorService` paralelo. Extendemos lo que hay.
5. **Contratos como código vivo** (decisión previa usuario): interfaces + stubs + tests que fallan en commit inicial, implementación en commits siguientes.
6. **Legacy hunting in-scope** (`AGENTS.md §12`): verificar si el código actual que hardcodea "inference / hybrid / utility" en `recommended_mode` tiene otros callers que asumen esas 3 strings — si sí, migrar en el mismo cambio.

---

## 3. Lista de cambios

### Change 1: Añadir `DeviceRuntime` enum y `RuntimeProfile` a `models/mesh.py`

- **Resuelve**: Gap #1 (conflación mode × runtime)
- **Qué**: nuevo enum `DeviceRuntime = {kotlin_only, llama_cpp, embedded_core}` + dataclass `RuntimeProfile` con `available_runtimes: list[DeviceRuntime]` + `ram_gb`, `has_gpu`, `python_runtime_present`, `llama_binary_present`.
- **Dónde**: [tools/gimo_server/models/mesh.py](tools/gimo_server/models/mesh.py) — extender, no archivo nuevo.
- **Por qué este diseño**: el enum canónico vive con `DeviceMode` (misma capa de modelado). Evita paralelismo entre Android Kotlin y backend — ambos leen del mismo contrato Pydantic traducido a serializable JSON.
- **Riesgo**: bajo. Campo nuevo opcional en `MeshDeviceInfo` (default `None` para devices legacy sin reportar).
- **Verificación**: test de serialización/deserialización JSON + test de que `None` no rompe enrollments existentes.

### Change 2: Android reporta `runtime_profile` al enrollment

- **Resuelve**: Gap #3 (backend no sabe qué runtimes tiene el device)
- **Qué**: `ShellEnvironment` detecta qué runtimes están presentes (chequea `runtime/gimo-core-runtime.json`, chequea binario `llama-server`). Genera `RuntimeProfile` serializable. `OnboardingClient` lo incluye en el payload de enrollment.
- **Dónde**:
  - `apps/android/gimomesh/.../ShellEnvironment.kt` — añadir `fun buildRuntimeProfile(): RuntimeProfile`
  - `apps/android/gimomesh/.../data/api/OnboardingClient.kt` — incluir en request de enrollment
  - `apps/android/gimomesh/.../data/model/MeshModels.kt` — tipo Kotlin espejo de `RuntimeProfile`
- **Por qué este diseño**: la detección ya vive parcialmente en `ShellEnvironment` (ya verifica `getEmbeddedCoreRuntime()`). Extendemos en su sitio natural, no creamos un `RuntimeDetector` separado.
- **Riesgo**: bajo. Detección es lazy y tolerante a fallos (si no existe el archivo, el runtime queda fuera de la lista).
- **Verificación**: test unitario Kotlin con ShellEnvironment mockeado devolviendo distintos escenarios (binario presente / ausente, python runtime / no).

### Change 3: Extender `ModelRecommendationEngine` con `recommend_runtime()`

- **Resuelve**: Gap #2 (motor no emite `server`, no considera runtime)
- **Qué**: nueva función `recommend_runtime(profile: RuntimeProfile) -> tuple[DeviceMode, DeviceRuntime]`. Matriz:
  - RAM ≥ 4GB + `embedded_core` disponible → `(DeviceMode.server, DeviceRuntime.embedded_core)` si GPU, sino `(DeviceMode.hybrid, DeviceRuntime.embedded_core)`
  - GPU compute + `llama_cpp` disponible + modelo cabe → `(DeviceMode.inference, DeviceRuntime.llama_cpp)`
  - Solo `kotlin_only` → `(DeviceMode.utility, DeviceRuntime.kotlin_only)`
  - Overload (nada cabe) → `(DeviceMode.utility, DeviceRuntime.kotlin_only)` con warning
- **Dónde**: [services/mesh/model_recommendation.py](tools/gimo_server/services/mesh/model_recommendation.py) — añadir función junto a `recommend_models`.
- **Por qué este diseño**: reusa el SoC database, RAM formula, y `FitLevel` existente. El resultado es una tupla de contratos canónicos existentes. NO reemplaza `score_model`, solo añade una capa superior que consume las mismas primitivas.
- **Riesgo**: medio. La tabla de thresholds (≥4GB para server) es calibrable — test de contrato valida los límites no la calidad heurística.
- **Verificación**: tests parametrizados sobre escenarios conocidos (S10 = hybrid+embedded_core con Qwen 3B validado 2026-04-11, smartphone viejo = utility+kotlin_only, laptop con GPU = server+llama_cpp).

### Change 4: Endpoint `GET /ops/mesh/devices/{id}/runtime-recommendation`

- **Resuelve**: superficie HTTP para que Android + UI consuman la recomendación
- **Qué**: endpoint read-only que toma `device_id`, carga `MeshDeviceInfo` del registry, ejecuta `recommend_runtime(profile)`, devuelve JSON `{recommended_mode, recommended_runtime, reasoning, warnings}`.
- **Dónde**: [tools/gimo_server/routers/ops/mesh_router.py](tools/gimo_server/routers/ops/mesh_router.py) — junto a los endpoints de device.
- **Por qué este diseño**: un endpoint, un contrato. Android, CLI, MCP, Web UI lo consumen idénticamente (multi-surface parity — AGENTS.md).
- **Riesgo**: bajo. Es computo puro, no muta estado, no requiere hardware check.
- **Verificación**: test de integración con TestClient (sin `with`, respetando convención repo).

### Change 5: Android UI advisory

- **Resuelve**: UX para que el usuario vea la recomendación y la acepte/sobreescriba
- **Qué**: en `SetupWizardScreen` (u otra pantalla natural post-enrollment), llamar al endpoint y mostrar *"Recomendado: Server + Python embebido (este device tiene 8GB RAM y Python runtime)"* con un botón **Aceptar** que ajusta `settings.deviceMode` + persiste preferencia de runtime. Override manual siempre disponible.
- **Dónde**: 1-2 archivos en `apps/android/gimomesh/.../ui/setup/`.
- **Por qué este diseño**: advisory, no forzado — respeta el principio de autonomía del device owner. Consistente con cómo el `ModelRecommendationEngine` ya se usa en la wizard (según S11 handoff).
- **Riesgo**: bajo — es UI sobre un endpoint read-only.
- **Verificación**: manual smoke test sobre APK (el test automatizado queda como follow-up, los tests UI Android no son parte del flujo de CI estándar del repo).

### Change 6: Documentación §2.4 "Runtime Selection Policy"

- **Resuelve**: narrativa arquitectónica viva en el canonical
- **Qué**: nueva sección en `docs/DEV_MESH_ARCHITECTURE.md` justo después de §2.3, ~40-60 líneas, describiendo: el eje mode × runtime, la matriz de recomendación, el principio advisory-no-forzado, cómo interactúa con hardware protection.
- **Dónde**: [docs/DEV_MESH_ARCHITECTURE.md](docs/DEV_MESH_ARCHITECTURE.md) — insertar sección nueva.
- **Por qué este diseño**: una sola fuente de verdad doc — NO se crea markdown separado (respeta la decisión *"cero documento markdown repetido"*).
- **Riesgo**: ninguno (doc).
- **Verificación**: revisión editorial + enlaces internos funcionando.

---

## 4. Orden de ejecución

Commits en este orden (cada uno debería pasar su propio test narrowest):

1. **Contratos Python + tests que fallan** (Change 1 + 3 test skeletons)
   - `models/mesh.py`: añadir `DeviceRuntime`, `RuntimeProfile`
   - `services/mesh/model_recommendation.py`: stub `recommend_runtime()` que hace `raise NotImplementedError`
   - `tests/unit/test_runtime_selector.py`: tests parametrizados que fallan con NotImplementedError
   - CI narrowest: `pytest tests/unit/test_runtime_selector.py -v` debe mostrar N failures esperados

2. **Implementación Python del selector** (Change 3 real)
   - Llenar `recommend_runtime()` con la matriz
   - Tests del Change 1 ahora pasan
   - CI: `pytest tests/unit/test_runtime_selector.py tests/unit/test_model_recommendation.py -v`

3. **Endpoint HTTP + test integración** (Change 4)
   - Añadir endpoint en `mesh_router.py`
   - Test integración en `tests/integration/test_mesh_runtime_recommendation.py`
   - CI: `pytest tests/integration/test_mesh_runtime_recommendation.py -v`

4. **Android runtime profile reporting** (Change 2)
   - `ShellEnvironment.buildRuntimeProfile()`
   - Modificar `OnboardingClient` payload
   - Test Kotlin unitario (si la app tiene gradle test task; si no, manual smoke)

5. **UI advisory Android** (Change 5)
   - Integrar endpoint en `SetupWizardScreen` (o donde decidamos en detalle)
   - Manual smoke test

6. **Documentación §2.4** (Change 6)
   - Añadir sección al canonical
   - No rompe tests

7. **Verificación broad final** (gate)
   - `python -m pytest -x -q` (suite completa)
   - `gimo up` smoke (health check + boot OK)
   - Android build limpio
   - `test_boot_mesh_disabled.py` sigue verde (invariant mesh-off preservada)

---

## 5. Unification check

| Superficie | Consume el contrato de runtime | Cómo |
|---|---|---|
| Backend registry | ✅ persiste `DeviceRuntime` en `MeshDeviceInfo` | dataclass Pydantic |
| HTTP API | ✅ expone via `/ops/mesh/devices/{id}/runtime-recommendation` | JSON schema |
| Android | ✅ reporta `runtime_profile` + consume recomendación | tipo Kotlin espejo |
| CLI | ✅ mismo endpoint via `gimo mesh runtime <device>` *(follow-up, no parte del scope)* | - |
| MCP bridge | ✅ auto-exposed via OpenAPI sync | dinámico |
| Web UI | ✅ misma llamada HTTP con fetchWithRetry | React |
| Tests | ✅ contract tests + integración | pytest |
| Docs | ✅ §2.4 en canonical | markdown único |

**Cero paths paralelos**. Cero hardcoded strings. Cero lógica de selección en cliente.

---

## 6. Estrategia de verificación

### Contract tests (narrowest, Change 3)

```python
# tests/unit/test_runtime_selector.py
@pytest.mark.parametrize("profile,expected_mode,expected_runtime", [
    # S10 validado 2026-04-11: 8GB, Exynos 9820, llama.cpp válido
    (RuntimeProfile(ram_gb=8, has_gpu=False, python_runtime_present=True,
                    llama_binary_present=True, soc="exynos 9820"),
     DeviceMode.hybrid, DeviceRuntime.embedded_core),
    # Smartphone viejo: 2GB, sin Python, sin llama
    (RuntimeProfile(ram_gb=2, has_gpu=False, python_runtime_present=False,
                    llama_binary_present=False, soc="exynos 850"),
     DeviceMode.utility, DeviceRuntime.kotlin_only),
    # Laptop con GPU + llama
    (RuntimeProfile(ram_gb=16, has_gpu=True, python_runtime_present=True,
                    llama_binary_present=True, soc="unknown"),
     DeviceMode.server, DeviceRuntime.embedded_core),
])
def test_runtime_recommendation(profile, expected_mode, expected_runtime):
    mode, runtime = recommend_runtime(profile)
    assert mode == expected_mode
    assert runtime == expected_runtime
```

### Integration tests (boundary, Change 4)

Test HTTP end-to-end: enroll device con profile → GET recommendation → verificar payload.

### Runtime smoke (final gate)

1. `gimo up` → health check
2. `curl /ops/mesh/devices/{known_id}/runtime-recommendation` → esperar 200 + payload válido
3. Android APK build
4. `test_boot_mesh_disabled.py` verde

### Broader check

- Suite unitaria completa: `python -m pytest -x -q` (debería seguir en 1665+ verde)
- Frontend tsc: `cd tools/orchestrator_ui && npm run build` (sin cambios frontend, pero gate por si acaso)

---

## 7. Matriz de compliance (AGENTS.md Plan Quality Standard)

| # | Gate | ¿Cumple? | Justificación |
|---|---|---|---|
| 1 | Permanence | ✅ | El enum `DeviceRuntime` es modelo canónico estable. No es patch temporal. |
| 2 | Completeness | ✅ | Cubre los 3 gaps identificados (modelado, recomendación, reporte de capacidades). |
| 3 | Foresight | ✅ | Enum es extensible (futuro: MLX, ONNX, TensorRT sin romper contrato). |
| 4 | Potency | ✅ | Desbloquea federación GICS (fase diferida) y servidor-en-móvil. |
| 5 | Innovation | ✅ | No hay en el estado del arte OSS un selector mesh mode×runtime — todos asumen 1:1. |
| 6 | Elegance | ✅ | Un enum + una función + un endpoint. Sin nueva service class. |
| 7 | Lightness | ✅ | ~6 archivos tocados, ~250 LOC netas estimadas. |
| 8 | Multiplicity | ✅ | Una misma recomendación sirve a Android UI, CLI, MCP, Web, tests. |
| 9 | Unification | ✅ | Un endpoint `GET /ops/mesh/devices/{id}/runtime-recommendation` es canónico y mandatorio para todas las superficies. |

| E2E skill gate | ¿Cumple? |
|---|---|
| Aligned (SYSTEM/CLIENT_SURFACES/SECURITY) | ✅ — backend authority, multi-surface parity, no weakening de hardware protection |
| Honest | ✅ — stubs raise NotImplementedError hasta implementar; tests contractuales |
| Potent | ✅ — resuelve 3 gaps con una abstracción |
| Minimal | ✅ — 6 archivos, 0 nuevas services |
| Unified | ✅ — un endpoint, un enum |
| Verifiable | ✅ — contract tests parametrizados + smoke runtime |
| Operational | ✅ — mesh-off invariant preservada por diseño (runtime recommendation requires `mesh_enabled=True`) |
| Durable | ✅ — enum extensible, modelo Pydantic canónico |

---

## 8. Riesgos residuales

1. **Calibración de thresholds (≥4GB RAM para server)** — los tests validan la forma, no la calidad heurística. La calibración real requiere datos de campo. **Mitigación**: los thresholds son constantes nombradas, fáciles de ajustar con un commit + cambio de test.

2. **Android reporting desalineado** — si la detección de runtime en `ShellEnvironment` falla silenciosamente, el device aparecería con `available_runtimes=[]` y acabaría en `utility+kotlin_only`. **Mitigación**: log warning en Android cuando la detección devuelve vacío Y el device claramente tiene capacidades (ej: ≥4GB RAM sugiere Python viable).

3. **Endpoint expone info de device** — `GET /ops/mesh/devices/{id}/runtime-recommendation` revela capabilities del device. **Mitigación**: requires auth `operator` role (mismo nivel que otros endpoints de mesh device).

4. **Follow-ups explícitamente fuera de scope**:
   - CLI `gimo mesh runtime <id>` (Change 5 solo Android)
   - Web UI panel (UI existe pero se extiende en follow-up)
   - Federación GICS del aprendizaje runtime-per-device (fase 2)
   - Descarga on-demand de Python runtime / llama binary (fase 2, el informe lo menciona correctamente)

5. **`ModelRecommendationEngine` actual sigue emitiendo `recommended_mode` string** — Change 3 coexiste, no lo reemplaza. **Decisión pendiente**: ¿Change 3 reemplaza el campo `recommended_mode` de `ModelRecommendation` por uno que use el enum? Si sí, es un cambio de contrato; hay que auditar callers. **Propuesta**: diferir el reemplazo a un follow-up — el nuevo `recommend_runtime()` convive, y cuando se consolide el uso, se deprecia el string.

---

## 9. Pausa obligatoria

Siguiendo el protocolo del skill /e2e, el plan queda aquí. **No se inicia Fase 4 sin tu aprobación explícita.**

Preguntas abiertas que bloquean implementación:

1. **¿Aprobado el alcance de 6 changes tal como está?** ¿o querés recortar (ej: diferir Change 5 Android UI) o extender (ej: incluir deprecation del `recommended_mode` string en el mismo cambio)?
2. **¿Empezamos por Change 1 (contratos + tests failing)?** — este es el commit mínimo que ancla el contrato sin riesgo.
3. **¿Pusheamos antes los 16 commits del sprint anterior a origin?** — orden sugerido del informe usuario.
4. **¿Calibración inicial de thresholds**: vamos con ≥4GB para server + GPU-para-llama, o querés revisar los números con datos de S10 (8GB, validado a 2.6 tok/s)?
