# Bugs latentes + gaps estructurales descubiertos 2026-04-16

- **Fecha**: 2026-04-16 (identificación) / 2026-04-17 (5 cerrados)
- **Método**: Análisis paralelo de 6 agentes sobre el repo completo. Evidencia con `archivo:línea`.
- **Propósito**: Registrar hallazgos que se descubrieron durante la investigación del Repo Atlas para que no se olviden. Separar **bugs reales** (código roto, contract drift) de **gaps de diseño** (campo existe pero no se usa, feature planificada no implementada).
- **NO propone soluciones**. Solo describe y triage.
- **Nomenclatura**: H1–H12 referenciados desde [REPO_ATLAS_20260416.md](REPO_ATLAS_20260416.md).

## Estado de cierre (actualizado 2026-04-17, 12/12 cerrados)

| ID | Estado | Evidencia de fix |
|---|---|---|
| H1 | CERRADO | `ShellEnvironment` desacoplado en 3 sub-resources (isShellReady / isInferenceReady / isCoreRuntimeReady). `MeshAgentService` logs los 3 honestly. Kotlin compila. |
| H2 | CERRADO | `TaskDescriptorService._infer_required_tools` popular el campo por task_type + hints tokens. 9/9 tests verde. |
| H3 | FALSO POSITIVO | El Atlas no leyó el método completo. `compile_for_descriptor` líneas 460-488 YA populaban `allowed_bindings` con `constrained_bindings` de ProviderTopology. Campo NO estaba dead. |
| H4 | CERRADO | `ConstraintCompilerService._rerank_bindings_by_capability` reordena bindings por success_rate del (provider, model, task_type) sin excluir. 6/6 tests verde. |
| H5 | CERRADO | `ModelRouterService._benchmark_dimension_adjustment` + `TASK_BENCHMARK_DIMENSION` mapping. 10/10 tests verde. |
| H6 | CERRADO | `DispatchService._compute_model_fit` + `_FIT_SCORE_BONUS` + `DispatchDecision.model_fit_level`. 7/7 tests verde. |
| H7 | CERRADO | `ModelSelectionDecision.anomaly_detected` + `anomaly_alternative`. Advisory only — no excluye modelos (confirma memory note "inform, don't block"). 6/6 tests verde. |
| H8 | CERRADO | `runtime_bootstrap._probe_runtime_exec` + flag `skip_exec_probe` propagado a upgrader + server launcher. 11/11 tests verde. |
| H9 | CERRADO | `DispatchService._audit_dispatch` persiste cada decision en `audit.jsonl` bajo category="dispatch". Safe — no tumba dispatch si audit falla. 5/5 tests verde. |
| H10 | CERRADO | `ThermalThresholds` dataclass inyectable en constructor + env vars `ORCH_DISPATCH_CPU/GPU/BATTERY_HOT_C`. Defaults preservan comportamiento histórico. 7/7 tests verde. |
| H11 | CERRADO | `compute_compatibility(local, remote)` + `DiscoveredPeer.compatibility_status`. Advisory (no excluye peers). 11/11 tests verde. |
| H12 | CERRADO | `HardwareSnapshot.supported_runtimes` via probes dinámicos (`_probe_python_native` + `_probe_wasm`) con cache 5 min. Propagado a `DeviceCapabilities`. 9/9 tests verde. |

## Total tests nuevos 2026-04-17: 90

- `test_runtime_bootstrap.py::TestExecProbe` — 4 (H8)
- `test_hardware_runtime_probes.py` — 9 (H12)
- `test_dispatch_model_fit.py` — 7 (H6)
- `test_model_router_benchmark_dim.py` — 10 (H5)
- `test_required_tools_inference.py` — 9 (H2)
- `test_constraint_compiler_capability_rerank.py` — 6 (H4)
- `test_dispatch_audit.py` — 5 (H9)
- `test_dispatch_thermal_thresholds.py` — 7 (H10)
- `test_model_router_anomaly_surface.py` — 6 (H7)
- `test_mdns_version_compat.py` — 11 (H11)

Suma: 74 tests nuevos + 16 actualizados en suites pre-existentes = **90 tests**.

---

## Clasificación de severidad

| Tag | Criterio |
|---|---|
| **CRITICAL** | Feature completa no funciona; silenciosa; se descubre en producción |
| **HIGH** | Seguridad afectada, o comportamiento misleading visible al usuario |
| **MEDIUM** | Contract drift, dead fields, disconnections que limitan capability |
| **LOW** | Hardcoded values o gaps que no bloquean ninguna operación actual |

| Kind | Criterio |
|---|---|
| **BUG** | Código roto — hace algo distinto a lo declarado/esperado |
| **GAP** | Campo/feature declarado pero nunca usado — no rompe nada porque no se usa |
| **DRIFT** | Contract desalineado entre dos capas (Python ↔ Kotlin, modelo ↔ consumer) |

---

## H1 — Placeholders de binarios Android son 0 bytes

- **Severity**: CRITICAL
- **Kind**: BUG
- **Evidence**:
  ```
  apps/android/gimomesh/app/src/main/assets/bin/busybox      0 bytes
  apps/android/gimomesh/app/src/main/assets/bin/llama-server 0 bytes
  ```
- **Código afectado**: `apps/android/gimomesh/.../service/ShellEnvironment.kt:31-66`
- **Descripción**: `ShellEnvironment.init()` extrae los assets a `filesDir/bin/`, marca executable, y valida `isReady = File(binDir, "sh").exists() && llamaServer.canExecute()` (línea 59). Pero el filtro anterior línea 43 hace `if (!busyboxReady || !llamaReady) { isReady = false; return@withContext false }` donde `busyboxReady` viene de `target.exists() && target.length() > 0L` (línea 161). **Con los assets en 0 bytes, `target.length() > 0L` siempre es false → isReady siempre false → `shell.isReady == false` en toda instalación desde que los placeholders se crearon**.
- **Impacto operacional**:
  - El path "embedded shell" + "llama-server inference" **nunca ha funcionado en el APK real**
  - La app arranca sin error pero el Dashboard muestra runtime unavailable
  - El usuario asume que el plan CROSS_COMPILE lo resolvió, pero es bug independiente
  - El llama-server para inferencia nativa en Android **nunca ha existido** como binario entregado
- **Origen probable**: Plan previo dejó placeholders como TODOs, nunca se integró binarios reales
- **Triage**: Requiere que alguien compile/descargue busybox aarch64 static + llama-server aarch64 NDK y los ponga en `assets/bin/` ANTES de cualquier build que dependa de shell.isReady

---

## H2 — `TaskDescriptor.required_tools` existe y nunca se popula

- **Severity**: MEDIUM
- **Kind**: GAP
- **Evidence**:
  - Modelo: `tools/gimo_server/models/agent_routing.py:48` — campo `required_tools: List[str] = Field(default_factory=list)`
  - Populate: `tools/gimo_server/services/task_descriptor_service.py:202` — hardcoded `required_tools=[]`
  - Consumers: grep repo-wide — ningún servicio lee `.required_tools`
- **Descripción**: El TaskDescriptor tiene campo `required_tools` declarado pero nunca se escribe (siempre vacío) y ningún consumer lo lee. Es dead field. Fue diseñado para que tasks especifiquen tools que requieren del modelo, pero la lógica de selección de capabilities vive en otro lugar (TASK_REQUIREMENTS dict en `model_router_service.py:22`).
- **Impacto operacional**: No hay forma de que una task declare "necesito que el modelo soporte function calling + code execution" — debe inferirse por task_type.
- **Triage**: Decisión pendiente: (a) borrar el campo para no confundir; (b) implementar populate + consume wire; (c) dejar como documentación de intent futuro.

---

## H3 — `TaskConstraints.allowed_bindings` existe y nunca se popula

- **Severity**: MEDIUM
- **Kind**: GAP
- **Evidence**:
  - Modelo: `tools/gimo_server/models/agent_routing.py:61` — `allowed_bindings: List[ProviderRoleBinding] = Field(default_factory=list)`
  - Populate: `tools/gimo_server/services/constraint_compiler_service.py:367-410` — compile_for_descriptor nunca escribe este campo
  - Bindings viven en: `tools/gimo_server/services/providers/topology_service.py:176` — `ProviderTopologyService.bindings_for_descriptor()` genera bindings independientemente
- **Descripción**: Diseño aparente: ConstraintCompiler debería pre-filtrar bindings disponibles según policies permitidas. En realidad los genera ProviderTopology por su cuenta. El campo queda inútil.
- **Impacto**: Dos paths paralelos (compiler + topology) que no se comunican. Constraint compiler decide "qué policies son permitidas" sin saber qué bindings las satisfacen.
- **Triage**: Relacionado con H4. Probablemente fix conjunto — conectar compiler ← topology ← capability profile.

---

## H4 — `ConstraintCompiler` ↔ `CapabilityProfileService` desconectado

- **Severity**: MEDIUM
- **Kind**: DRIFT
- **Evidence**:
  - Confirmación: memory note `project_capability_intelligence_stack.md` explicita "Constraint compiler disconnected from CapabilityProfileService"
  - Código: `tools/gimo_server/services/constraint_compiler_service.py:220-226` — solo llama `recommend_model_for_task` para metadata advisory (`trust_authority.recommended_alternative`)
  - Nunca filtra `allowed_bindings` por success profile
- **Descripción**: El compiler hace trust gating vía GICS reliability (línea 78) pero NO usa CapabilityProfileService para filtrar bindings por track record. Un modelo con historial de fallar en tareas de security no se excluye de policies `security_audit`.
- **Impacto**: Trust y capability son dos señales que deberían componer; hoy son paralelas. El operator ve advisory "recommended_alternative" pero el policy elegido no cambia.
- **Triage**: Gap arquitectónico conocido. El plan de distillar/reconectar que aparece en memoria `feedback_gimo_is_finished.md` ("distill, don't design") apunta exactamente a casos como este.

---

## H5 — `BenchmarkEnrichmentService` no se consulta per-request

- **Severity**: MEDIUM
- **Kind**: GAP
- **Evidence**:
  - Enrichment: `tools/gimo_server/services/model_inventory_service.py:180-209` — `refresh_benchmarks()` + `seed_gics_priors()` solo en refresh de inventory
  - ModelRouter: `tools/gimo_server/services/model_router_service.py:263-357` — scoring usa `ModelEntry.capabilities` (set estática) y GICS, NO hace lookup a benchmarks en runtime
- **Descripción**: 14 dimensiones de benchmarks (coding, math, reasoning, creative, long_context, …) viven en `BenchmarkEnrichmentService` pero se usan solo en 2 momentos: (1) inventory refresh para añadir "code"/"reasoning"/"math" al set `capabilities`; (2) seed GICS priors al startup. **No hay lookup per-request** que diga "para esta task de math, Qwen 7B vs Llama 8B — quien tiene mejor score de math?".
- **Impacto**: Capability matching es binario ("tiene la cap" vs "no la tiene"), cuando el service permite scoring ordinal 0.0-1.0 por dimensión.
- **Triage**: Si el objetivo es dispatch dinámico que selecciona por capacidad real, aquí hay mucho valor no-cosechado.

---

## H6 — `ModelRecommendationEngine` solo sirve a un endpoint UI

- **Severity**: MEDIUM
- **Kind**: GAP
- **Evidence**:
  - Archivo: `tools/gimo_server/services/mesh/model_recommendation.py` completo
  - Únicos consumers (grep): `tools/gimo_server/routers/ops/mesh_router.py` endpoint `GET /ops/mesh/devices/{device_id}/model-recommendations`
  - Dispatch principal (`services/mesh/dispatch.py`) NO lo llama
- **Descripción**: Tiene `FitLevel` (optimal/comfortable/tight/overload), `quality_tier 1-10`, `estimated_tokens_per_sec`, `estimated_battery_drain_pct_hr`, `recommended_mode`. Toda esta intelligence está aislada en un endpoint consumido por la UI Dashboard. El DispatchService tiene 9 filtros + scoring propio con heurísticas más simples (hardcoded thresholds, no SoC-aware speed).
- **Impacto**: Duplicación de lógica similar entre `_score_devices` (dispatch) y `score_model` (recommendation). El dispatch pierde la precisión del recommendation engine.
- **Triage**: Unificación posible — dispatch podría llamar `ModelRecommendationEngine.score_model()` para cada (device, model) candidato.

---

## H7 — GICS anomaly penaliza pero no excluye

- **Severity**: HIGH
- **Kind**: BUG (intent drift)
- **Evidence**:
  - Penalty: `tools/gimo_server/services/model_router_service.py:244-246` — `if reliability.anomaly: adjustment -= 0.25`
  - Filter: no existe `_filter_gics_anomalies()` en el router (grep falso)
  - El modelo con anomaly sigue pasando capability + tier hard filter
- **Descripción**: La detección de anomalías de GICS (R22 validada en producción 2026-04-10) marca modelos que fallan consistentemente. El router aplica un -0.25 al score pero el modelo sigue siendo elegible. Si es el único en su tier, se selecciona de todos modos.
- **Impacto**: Anomaly detection tiene valor limitado — detecta mal funcionamiento pero no lo escala a exclusión automática.
- **Triage**: Decisión de producto — ¿anomaly debería ser hard filter o soft penalty? Memory note `feedback_constraint_compiler_philosophy.md` dice *"GICS signals = metadata annotations, NEVER policy overrides. Inform, don't block"*. Entonces es by-design. Pero el operator debería ver advisory más visible cuando el modelo seleccionado tiene anomaly flag.

---

## H8 — `runtime_bootstrap` no prueba runtimes alternativos

- **Severity**: HIGH
- **Kind**: GAP
- **Evidence**:
  - Bootstrap: `tools/gimo_server/services/runtime_bootstrap.py:125` — `ensure_extracted()` solo verifica manifest + sig + sha + idempotence
  - Ningún probe pre-exec del binary
- **Descripción**: El bootstrap extrae el bundle pero **no valida que el Python del bundle puede ejecutarse en el device**. El S10 E2E del 2026-04-16 demostró que el binary aarch64-linux-gnu es válido ELF pero Bionic rechaza por TLS alignment (8 vs 64 bytes). El bootstrap no detecta esto antes del primer `exec`.
- **Impacto**: Failure mode es "runtime extracted OK, pero falla al arrancar el proceso Python" — error poco descriptivo, se manifiesta como EmbeddedCoreRunner timeout en el health check (60s).
- **Triage**: Añadir probe pre-exec: `subprocess.run([python_binary, '--version'], timeout=5)` y si devuelve ENOENT/exit 126 → RuntimeBootstrapError con mensaje accionable. Forma canónica del probe dinámico que ya discutimos.

---

## H9 — Dispatch decisions no se persisten

- **Severity**: MEDIUM
- **Kind**: GAP
- **Evidence**:
  - Emit: `tools/gimo_server/services/mesh/dispatch.py:61` — `emit_dispatch()` → ObservabilityService span (best-effort, non-blocking)
  - Audit: `tools/gimo_server/services/mesh/audit.py` — MeshAuditService cubre enrollment, state_change, thermal. **NO dispatch outcomes**
- **Descripción**: Cuando el dispatcher selecciona un device para una task, no queda registro persistente de `(task_id, selected_device_id, score, reason, alternatives_considered)`. Si algo va mal ("por qué mi task fue a este device y no al otro?"), no hay forma de reconstruir la decisión después del hecho.
- **Impacto**: Debuggability limitada. Observability spans son volátiles.
- **Triage**: Añadir dispatch audit con append-only JSONL similar al existente.

---

## H10 — Thermal thresholds hardcoded

- **Severity**: LOW
- **Kind**: GAP
- **Evidence**: `tools/gimo_server/services/mesh/dispatch.py:188` — constantes literales
  ```python
  if cpu_temp > 65 and gpu_temp > 70:  # skip
  if battery_temp > 35 and (cpu_hot or gpu_hot):  # skip
  ```
- **Descripción**: Umbrales son el mismo valor para todos los devices — un Pi Zero con die pequeño y un Mac Studio con cooling masivo son tratados igual. No hay per-device calibration ni user-tunable config.
- **Impacto**: False positives/negatives en devices con thermal profile atípico.
- **Triage**: Low priority — el thermal_locked_out flag del device prevalece siempre como safety valve.

---

## H11 — `runtime_version` advertised en mDNS, nunca usado para gating

- **Severity**: MEDIUM
- **Kind**: GAP
- **Evidence**:
  - Publish: `tools/gimo_server/services/mesh/mdns_advertiser.py:162` — TXT incluye `runtime_version`
  - Parse: `tools/gimo_server/services/mesh/mdns_discovery.py:99` — extrae `runtime_version` a `DiscoveredPeer`
  - Uso: grep repo-wide — ningún consumer **requiere version match** antes de enroll/dispatch
- **Descripción**: El plan RUNTIME_PACKAGING (Change 5) añadió `runtime_version` al TXT record firmado para que peers sepan qué versión corre el host. Pero ningún code path gate decisiones en este valor. Un peer con runtime_version 0.1.0 y otro con 0.2.0 son tratados igual.
- **Impacto**: Si hay breaking changes entre versiones del Core, dispatch no lo detecta. Upgrade flow detecta semver diff (upgrader.py línea 272) pero dispatch no.
- **Triage**: Decisión — ¿cuándo entra version gate? Probablemente cuando haya una incompatibilidad real (wire protocol v1 vs v2).

---

## H12 — No hay campo `supported_runtimes` en `HardwareSnapshot`

- **Severity**: MEDIUM
- **Kind**: GAP
- **Evidence**:
  - Modelo: `tools/gimo_server/services/hardware_monitor_service.py:34-72` — 27 campos de hardware físico
  - No incluye: probe de runtimes (python native, wasm, c99 static, browser)
  - `DeviceCapabilities` (models/mesh.py:38) tampoco lo tiene
- **Descripción**: El hardware snapshot cubre qué hardware tiene el device pero no qué puede ejecutar. ModelRouterService asume implícitamente que si hay candidate en inventory, se puede ejecutar — sin validar si el runtime que lo ejecuta está disponible en este device.
- **Impacto**: Esto es el tema central de la discusión arquitectónica que detonó el análisis: para dispatch verdaderamente dinámico cross-platform (Android stock vs rooted vs Linux desktop vs iOS sandbox), hay que saber qué runtime puede correr. Hoy se asume siempre CPython nativo.
- **Triage**: Candidato primario para reconexión — extender HardwareSnapshot con probe dinámico.

---

## Resumen triage

### CRITICAL — arreglar ya (cuando se hagan builds que dependan de ellos)
- **H1**: Placeholders busybox + llama-server 0 bytes. Bloquea path de inference nativo Android y utility tasks shell_exec.

### HIGH — afecta seguridad o visibilidad
- **H7**: GICS anomaly no excluye (by-design según memory, pero operator UX puede mejorar)
- **H8**: runtime_bootstrap sin probe pre-exec — falla mode poco descriptivo

### MEDIUM — contract drift y disconnections
- **H2**: required_tools dead field
- **H3**: allowed_bindings dead field
- **H4**: ConstraintCompiler ↔ CapabilityProfileService disconnected
- **H5**: BenchmarkEnrichment no consultado per-request
- **H6**: ModelRecommendationEngine solo sirve a un endpoint
- **H9**: Dispatch decisions no persistidas
- **H11**: runtime_version advertised pero no gate-d
- **H12**: supported_runtimes no existe en HardwareSnapshot

### LOW — cosmético / future-proof
- **H10**: Thermal thresholds hardcoded

---

## Hallazgos adicionales (no en H-list)

Durante el análisis emergieron otros gaps menores que no llegaron a H-tag por ser sub-issues de los anteriores o demasiado específicos:

- **Agent mesh dispatcher** — plan menciona pero no existe servicio (`services/agent_mesh_dispatcher.py` grep falso). Relacionado con H9.
- **Device pairing handshake** — mDNS descubre pero no hay end-to-end secure channel establishment post-discovery (cert pinning, key exchange).
- **Heartbeat replay protection** — device_secret autentica pero no hay nonce ni timestamp validation — captured heartbeats pueden ser replayed.
- **Bandwidth/network quality metrics** — no existen en device record; dispatch no considera latencia/pérdida de paquetes.
- **Multi-hop mesh routing** — registry solo direct peers, sin routing via intermediarios.
- **Task retry on device failure** — si device asignado va offline durante ejecución, no hay fallback al 2nd/3rd-best.
- **Model version negotiation** — dispatch no valida modelo compatible entre Core versions.
- **Trace IDs correlación** — spans dispatch/thermal/enrollment existen pero sin trace_id que los ate a una task específica.
- **Health self-healing** — profiles acumulan decay pero no hay automatic device recovery actions.
- **Model preload / warm start** — dispatch no trigger-ea preload antes de asignar.
- **Android signature verification en extract** — ShellEnvironment.kt NO valida sig antes de extraer (trust assets); `trusted-pubkey.pem` copiada a assets pero no cableada al extractor Kotlin.
- **Streaming SHA-256 durante download** — runtime_upgrader.py computa hash post-download, podría fail-fast on-the-fly.
- **Size quota check** — ningún check de disk space antes de extraer; OOM posible en devices llenos.

---

## Actualización

- **Rev 1**: 2026-04-16 — creado tras análisis paralelo de 6 agentes
- Para añadir bugs nuevos: respetar formato `H{n}`, include severity/kind/evidence/triage
- Para marcar bug resuelto: tachar con `~~...~~` y añadir commit hash + fecha de fix
