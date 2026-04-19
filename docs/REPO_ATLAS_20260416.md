# GIMO Repo Atlas — Mapa canónico del sistema

- **Fecha**: 2026-04-16
- **Branch**: `feature/gimo-mesh`
- **Método**: Análisis estático exhaustivo con 6 agentes paralelos sobre el repo completo. Toda afirmación lleva anclaje `archivo:línea`.
- **Propósito**: **Referencia obligatoria antes de cualquier propuesta arquitectónica.** Evita re-inventar subsistemas que ya existen. Se actualiza tras cada plan que cambie más de 500 LOC de código de producción.
- **No contiene**: opiniones, propuestas, especulación de futuro. Solo **lo que existe hoy**, con evidencia.

---

## Índice

1. [Top-level subsystems](#top-level-subsystems)
2. [Hardware & capability discovery stack](#hardware--capability-discovery-stack)
3. [Decision & routing pipeline (9 pasos)](#decision--routing-pipeline-9-pasos)
4. [Runtime packaging + bootstrap + distribution](#runtime-packaging--bootstrap--distribution)
5. [Mesh services (registry, dispatch, mDNS, telemetry, workspaces, audit)](#mesh-services)
6. [Android Kotlin adapter](#android-kotlin-adapter)
7. [HTTP / MCP / CLI surfaces](#surfaces)
8. [Data models canónicos](#data-models-canónicos)
9. [Persistencia (disco + locks)](#persistencia-disco--locks)
10. [Test coverage map](#test-coverage-map)
11. [Docs inventory](#docs-inventory)
12. [Matriz de conexiones](#matriz-de-conexiones)

---

## Top-level subsystems

Cada subsistema con su path raíz:

| Subsistema | Path | LOC aprox | Estado |
|---|---|---|---|
| Python Core backend | `tools/gimo_server/` | ~80,000 | Producción |
| Android Kotlin adapter | `apps/android/gimomesh/` | ~10,000 | Producción (con H1 latente) |
| Web UI React/Vite | `tools/orchestrator_ui/` | ~20,000 | Producción |
| CLI Typer | `gimo_cli/` + `gimo.py` | ~3,000 | Producción |
| Runtime packaging | `scripts/package_core_runtime.py` + `runtime_bootstrap.py` | ~1,500 | Producción (R21 2026-04-16) |
| MCP bridge | `tools/gimo_server/mcp_bridge/` | ~2,500 | Producción |
| Tests | `tests/unit/` + `tests/integration/` | ~40,000 | 1759 passed, 1 flaky |
| Docs | `docs/` + `docs/audits/` | 60+ archivos | Vivo |

---

## Hardware & capability discovery stack

### `HardwareMonitorService` — 489 LOC
`tools/gimo_server/services/hardware_monitor_service.py`

**Singleton** vía `get_instance()` (línea 309). Background async monitor via `start_monitoring()`/`stop_monitoring()`.

**27 señales** capturadas en `HardwareSnapshot` (líneas 34-72):

| Grupo | Campos | Detección |
|---|---|---|
| CPU | `cpu_percent`, `cpu_inference_capable` | psutil + heurística `total_ram≥16 ∧ cores≥4` (línea 350) |
| RAM | `ram_percent`, `ram_available_gb`, `total_ram_gb`, `unified_memory` | psutil.virtual_memory (línea 346) |
| GPU | `gpu_vendor`, `gpu_vram_gb`, `gpu_vram_free_gb`, `gpu_temp`, `gpu_compute_api` | pynvml (NVIDIA, línea 204-256), PowerShell WMI (AMD/Intel Windows), Metal detection (Apple) |
| NPU | `npu_vendor`, `npu_name`, `npu_tops` | Heurística sobre `cpu_name`: "Ryzen AI"/"Phoenix"→16 TOPS, "Strix Halo"→50, "Core Ultra"→11 (líneas 258-295) |
| SoC | `soc_model`, `soc_vendor`, `device_class` | `getprop ro.board.platform` (Android, líneas 115-148), `/proc/device-tree/model` (RPi), PowerShell WMI |
| Thermal | `cpu_temp`, `thermal_throttled`, `thermal_locked_out` | /sys/class/thermal/thermal_zone*/temp |
| Power | `battery_percent`, `battery_charging`, `battery_temp_c` | psutil.sensors_battery (desktop), /sys/class/power_supply (Android), termux-battery-status |
| Estimación | `max_model_params_b` | `ram_available_gb / 2.0` (Q4 GGUF rule, líneas 186-190) |

**Public surface**:
- `get_instance()` línea 309 — singleton
- `get_snapshot()` → `HardwareSnapshot` — uso principal
- `get_load_level()` → `"safe"|"caution"|"critical"` — filtro de dispatch
- `should_defer_run()` → bool
- `is_local_safe()` → bool

**Consumidores wired end-to-end**:
- `main.py` (startup) — inicia monitoring
- `tools/gimo_server/services/authority.py` (load level checks)
- `tools/gimo_server/services/capabilities_service.py`
- `tools/gimo_server/services/model_router_service.py` línea 531 — filtro hardware
- `tools/gimo_server/services/recommendation_service.py`
- `tools/gimo_server/services/resource_governor.py` — load gating
- `tools/gimo_server/routers/ops/mastery_router.py` — GET `/ops/mastery/model-recommendations`

### `DeviceCapabilities` + `MeshDeviceInfo` — `models/mesh.py`

**DeviceCapabilities** (líneas 38-48): `arch`, `cpu_cores`, `ram_total_mb`, `storage_free_mb`, `api_level`, `soc_model`, `has_gpu_compute`, `max_file_descriptors`.

**MeshDeviceInfo** (líneas 88-135): contiene `DeviceCapabilities` + estado (DeviceMode, ConnectionState, OperationalState) + thermal + battery + `max_model_params_b` + `model_loaded` + `inference_endpoint` + `active_workspace_id` + `health_score`.

Método clave: `can_execute()` línea 120 — gate agregado de estado, thermal lockout, device_mode, operational_state, core_enabled, local_allow_*.

### Mobile-side hardware detection (Android)

- `tools/gimo_mesh_agent/android_metrics.py` — Python agent para Termux: getprop, /proc/stat, /proc/meminfo, termux-battery-status
- `apps/android/gimomesh/.../service/MetricsCollector.kt` — Kotlin equivalente: /proc/stat, /proc/meminfo, BatteryManager sticky intent, /sys/class/thermal/thermal_zone*/temp
- Ambos alimentan `HeartbeatPayload` cada 30s

### Device capability inventory (summary table)

| Capability | Donde se detecta | Donde se almacena | Consumido por |
|---|---|---|---|
| arch | Build.SUPPORTED_ABIS[0] (Android) | DeviceCapabilities.arch | Task dispatch |
| cpu_cores | psutil.cpu_count, Runtime.getRuntime (Kotlin) | DeviceCapabilities.cpu_cores | model_recommendation.py:248 (thread_factor) |
| ram_total_mb | psutil / /proc/meminfo / MemTotal | DeviceCapabilities.ram_total_mb | model_recommendation.py:215-232 |
| storage_free_mb | StatFs(filesDir).availableBytes (Android) | DeviceCapabilities.storage_free_mb | model_recommendation.py:216-219 |
| api_level | Build.VERSION.SDK_INT | DeviceCapabilities.api_level | Task dispatch min_api_level |
| soc_model | getprop ro.hardware.chipname, WMI, machine registry | HardwareSnapshot.soc_model + MeshDeviceInfo.soc_model | model_recommendation.py:174-189 (_SOC_PERF lookup) |
| soc_vendor | Fuzzy match sobre soc_model | Idem | model_recommendation.py |
| gpu_compute_api | `_detect_gpu_compute_api(gpu_vendor)` | HardwareSnapshot.gpu_compute_api | model_recommendation.py:201 |
| gpu_vram_gb | pynvml / PowerShell WMI / Metal | HardwareSnapshot.gpu_vram_gb | device_detector.py (inference engine) |
| npu_vendor/tops | Fuzzy match en CPU name | HardwareSnapshot.npu_* | Execution provider selection |
| unified_memory | NPU vendor detection (APUs) | HardwareSnapshot.unified_memory | Inference memory access optimization |
| max_model_params_b | `ram_available_gb / 2.0` | HardwareSnapshot + HeartbeatPayload + MeshDeviceInfo | Model filtering |
| device_class | `_detect_device_class()` | HardwareSnapshot + HeartbeatPayload + MeshDeviceInfo | model_recommendation defaults, host_bootstrap |
| battery_percent/temp/charging | psutil / /sys/class/power_supply / Android BatteryManager | HardwareSnapshot + HeartbeatPayload + MeshDeviceInfo | ThermalEvent, scheduling |
| thermal_throttled/locked_out | Server-side monitor lee /sys/class/thermal | HeartbeatPayload + registry state machine | ConnectionState transition → thermal_lockout; `can_execute()` gate |

---

## Decision & routing pipeline (9 pasos)

Flujo end-to-end para una task que se dispatcha a un modelo:

```
1. TaskDescriptor (task_descriptor_service.py:150)
   └─ task_type, task_semantic, risk_band, path_scope, complexity_band
   
2. Intent classification (intent_classification_service.py:120)
   └─ intent_effective, execution_decision (AUTO_RUN/HUMAN_APPROVAL/RISK_TOO_HIGH/DRAFT_REJECTED)
   
3. ConstraintCompiler (constraint_compiler_service.py:367)
   └─ allowed_policies, allowed_binding_modes, trust authority advisory
   
4. ProviderTopology (topology_service.py:176)
   └─ candidate bindings (orchestrator / workers)
   
5. ModelInventoryService (model_inventory_service.py:214)
   └─ enriched con benchmarks vía BenchmarkEnrichmentService
   
6. ModelRouterService._score (model_router_service.py:263-357)
   └─ 14 scoring inputs; output: ModelSelectionDecision
   
7. CascadeService.execute_with_cascade (cascade_service.py:20)
   └─ escalation si quality < threshold
   
8. DispatchService._score_devices (services/mesh/dispatch.py:203)
   └─ selección de device en mesh (9 filtros + scoring)
   
9. Provider execution (tools/gimo_server/services/providers/*.py)
```

### 14 scoring inputs en `ModelRouterService`

| Señal | Fuente | Tipo filtro/score |
|---|---|---|
| Required capability | TASK_REQUIREMENTS (líneas 22-31) → task_type | Hard filter |
| Minimum tier | TASK_REQUIREMENTS → tier_min | Hard filter (fallback capability-only → chat fallback) |
| Topology preference | ProviderService.resolve_tier_routing() | +1.0 provider match / +0.7 model match |
| GICS reliability | `_gics_success_adjustment()` línea 232 | ±0.4 × (score - 0.5) |
| GICS anomaly | reliability.anomaly | -0.25 si True |
| GICS task success rate | CapabilityProfileService.get_capability() | ±0.2 × (success_rate - 0.5), solo si samples≥2 |
| Quality tier | ModelEntry.quality_tier | 1.0 si ≥ tier_min + (tier/100) |
| is_local | ModelEntry.is_local | +1.0 si local, +(0.5 - size/100) si size conocido |
| Cost | ModelEntry.cost_input + cost_output | 1.0 si free, else max(0, 1 - cost/1000) |
| Hardware state | HardwareMonitorService.get_load_level() | Hard filter: critical → solo remote, caution → solo small local |
| Budget mode | task_context.budget_mode | Hard filter: tight → quita workspace_experiment |
| Policy decision | RuntimePolicyService.evaluate_draft_policy | Hard filter: deny → 0 policies allowed |
| Trust anomaly | apply_trust_authority() | Advisory metadata, no modifica policy |
| Benchmark priors | BenchmarkEnrichmentService (startup seed) | Enriquece ModelEntry.capabilities; no consultado per-request |

### 9 filtros en `DispatchService`

En `tools/gimo_server/services/mesh/dispatch.py`:

1. Mesh enabled check (línea 85) — fallback si disabled
2. Eligible devices filter (`registry.get_eligible_devices()` línea 408):
   - `connection_state ∈ {approved, connected}`
   - `core_enabled ∧ local_allow_core_control ∧ local_allow_task_execution`
   - `operational_state ∉ {disabled, paused, error, draining, locked_out}`
   - `NOT thermal_locked_out`
3. Capacity filter (línea 99) — `max_model_params_b > 0 si fingerprint.requires_context_kb`
4. Staleness filter (`_filter_stale_heartbeats` línea 156) — heartbeat age > 120s → reject
5. Thermal headroom filter (`_filter_thermal_headroom` línea 173) — cpu > 65°C ∧ gpu > 70°C → skip; battery > 35°C ∧ (cpu_hot ∨ gpu_hot) → skip
6. Scoring base (línea 219): health_score 0-100
7. Bonuses dinámicos (líneas 221-229):
   - cpu_percent < 50 → +10
   - ram_percent < 70 → +5
   - battery_percent > 50 → +5
   - battery_percent < 20 → -10
8. Rev 2 Cambio 2 self-penalty (líneas 241-254):
   - Device es host ∧ device_mode=server → baseline -10
   - Headroom good → -5
   - Low battery not charging → -20 extra
9. PatternMatcher.select_model (pattern_matcher.py:62) — Thompson Sampling Beta(successes+1, failures+1) sobre GICS pattern

### Services individuales del pipeline

#### `TaskDescriptor` / `TaskDescriptorService`
Archivo: `models/agent_routing.py:41-54` + `services/task_descriptor_service.py:103-207`.

Campos TaskDescriptor: `task_id`, `title`, `description`, `task_type`, `task_semantic`, `artifact_kind`, `mutation_mode`, `risk_band`, `required_tools: List[str]` (siempre vacío — ver [BUGS H2](BUGS_LATENTES_20260416.md#h2)), `path_scope`, `complexity_band`, `parallelism_hint`, `source_shape`.

Heurística en `canonicalize_task()` línea 103: tokenización texto → task_type mapping con palabras clave "orchestr", "security", "review", "research", "human gate".

#### `IntentClassificationService` — líneas 1-200+
`evaluate()` línea 120 → `IntentDecisionAudit`. Gates:
- Policy deny → DRAFT_REJECTED_FORBIDDEN_SCOPE
- Risk > 60 → RISK_SCORE_TOO_HIGH
- Risk 31-60 → HUMAN_APPROVAL_REQUIRED
- Intent upgrade: touches `tools/gimo_server/security` → SECURITY_CHANGE; touches core runtime → CORE_RUNTIME_CHANGE

#### `ConstraintCompilerService` — 1-450+ líneas
`compile_for_descriptor()` línea 367 → `TaskConstraints`.

Mapa semantic → base policies (líneas 19-26):
- planning → [propose_only, read_only]
- research → [docs_research, read_only]
- security → [security_audit, read_only]
- implementation → [workspace_safe, workspace_experiment]

Trust-gated upgrade (líneas 47-86): modelo reliable (GICS > 0.5, no anomaly) → prepend workspace_safe.

`apply_trust_authority()` líneas 272-364: lee GICS anomaly, llama `CapabilityProfileService.recommend_model_for_task` para metadata, NUNCA modifica policy.

#### `CapabilityProfileService` — 252 líneas
Keys GICS: `ops:capability:{provider}:{model}:{task_type}` y `ops:capability_index:{provider}:{model}`.

Records: `TaskCapability` (samples, successes, success_rate, avg_latency_ms, avg_cost_usd, failure_streak).

Agregado: `ModelProfile` (strengths ≥ 0.7, weaknesses < 0.5).

Wiring: escrito por `run_worker.py` (task outcomes), leído por `model_router_service.py` línea 248, `constraint_compiler_service.py` línea 220, `capability_router.py` (REST).

#### `ModelInventoryService` — 274 líneas
`ModelEntry` (líneas 80-90): model_id, provider_id, provider_type, is_local, `quality_tier: int 1-5`, size_gb, context_window, `capabilities: set[str]`, cost_input, cost_output.

Inferencia capabilities (líneas 24-28 + `_infer_capabilities` línea 71):
- base: {"chat"}
- patterns regex: "code" ← `code|coder|starcoder|codellama|deepseek-coder`; "reasoning" ← `opus|o1|o3|deepseek-r1|qwq`; "vision" ← `vision|llava|bakllava|moondream`

Enrichment (líneas 180-209): async refresh benchmarks → lookup_model → si score > 0.6 añade "code"/"reasoning"/"math" → seed GICS priors.

#### `BenchmarkEnrichmentService` — 576 líneas
Fuentes:
- LMArena (lmarena-ai/leaderboard-dataset): 17 categorías Bradley-Terry
- Open LLM Leaderboard (open-llm-leaderboard/contents): IFEval, BBH, MATH, GPQA, MUSR, MMLU-PRO

**14 dimensiones GIMO**:
coding, math, reasoning, creative, long_context, business, science, writing, multi_step_reasoning, general_knowledge, expert_knowledge, instruction_following, multi_turn, overall.

Cache: `data/model_capabilities.json` (seed ship, permanente), `OPS_DATA_DIR/model_capabilities_cache.json` (TTL 7 días).

`seed_gics_priors()` línea 473 — blend 20% prior + 80% observed.

#### `ModelRecommendationEngine` — `services/mesh/model_recommendation.py`
`ModelRecommendation` (líneas 68-112): fit_level (optimal/comfortable/tight/overload), estimated_ram_gb, device_ram_gb, ram_headroom_pct, estimated_tokens_per_sec, estimated_battery_drain_pct_hr, storage_required_gb, score 0-100, quality_tier 1-10, impact, warnings, recommendation_reason, `recommended_mode`.

`score_model()` línea 192 — formula GGUF quantization (_QUANT_BITS, _QUANT_QUALITY) + SoC-specific benchmarks (_SOC_PERF, _SOC_DRAIN).

**Consumer único**: endpoint `GET /ops/mesh/devices/{device_id}/model-recommendations` en `mesh_router.py`. No consumido por dispatch principal.

#### `CascadeService` — 250 líneas
`execute_with_cascade()` línea 20 → `CascadeResult`.

Flow: empieza con model cheapest → ejecuta → `QualityService.analyze_output()` → si < threshold → next_tier → stop on budget exhausted.

`_get_next_model()` línea 137 → escalation via ModelInventory filter.

---

## Runtime packaging + bootstrap + distribution

### Productor — `scripts/package_core_runtime.py`

Subcomandos: `detect-target`, `build`, `verify`.

Build flow (línea 515+):
1. Fetch Python (host o `python-build-standalone`): `_fetch_standalone_python()`
2. Install wheels: `pip install --target --platform <tag> --only-binary :all:` (si cross-compile) o pip directo (si host)
3. Copy repo tree: `_build_repo_tree()` — `tools/gimo_server`, `tools/mcp_bridge`, `tools/orchestrator_cli`, `gimo_cli`, `gimo.py`, `data`, `docs/SECURITY.md`
4. List files para manifest
5. Compress `tarball.tar.xz` (xz preset=6)
6. SHA-256 del tarball
7. Ed25519 sign del payload `{sha256}|{target}|{version}` → hex 128 chars
8. Output: `.tar.xz` + `.json` manifest + `.sig` firma

Targets soportados (`_STANDALONE_ASSETS` dict):
- `android-arm64` → `aarch64-unknown-linux-gnu-install_only.tar.gz`
- `linux-x86_64` → `x86_64-unknown-linux-gnu-install_only.tar.gz`
- `windows-x86_64` → `x86_64-pc-windows-msvc-install_only.tar.gz`
- `darwin-arm64` → `aarch64-apple-darwin-install_only.tar.gz`
- `linux-arm64`, `android-armv7`, `darwin-x86_64` — mapeados, sin CI matrix aún

Release pin: `_STANDALONE_RELEASE = "20260414"`, `_STANDALONE_PYTHON_VERSION = "3.13.13"`.

### Firma — `tools/gimo_server/security/runtime_signature.py`
- Ed25519 via `cryptography` library
- Private key: `--signing-key <path|PEM>` o env `ORCH_RUNTIME_SIGNING_KEY`
- Public key: env `ORCH_RUNTIME_PUBLIC_KEY` (prioridad) o `EMBEDDED_RUNTIME_PUBLIC_KEY` constante (línea 46)
- Payload firma: `f"{tarball_sha256}|{target}|{runtime_version}"` (método `signing_payload()` en RuntimeManifest línea 177)
- Firma devuelta como hex 128 chars

### Bootstrap — `tools/gimo_server/services/runtime_bootstrap.py`

`ensure_extracted(assets_dir, target_dir, public_key_pem, allow_unsigned)` línea 125:

1. Load manifest (línea 84) → Pydantic validation
2. Verify Ed25519 sig (línea 158) → RuntimeBootstrapError si falla
3. Idempotence check (línea 165): `target_dir/.extracted-version == manifest.runtime_version`? → return cached
4. Cleanup residual `-extracting/` (línea 164)
5. Verify tarball SHA-256 (línea 105) vs `manifest.tarball_sha256`
6. Extract to `{target}-extracting/` con `tarfile.open(mode=_extraction_mode(compression))`
7. Atomic swap (línea 200): `os.rename(staging, target_dir)` + backup handling
8. Write `.extracted-version` marker
9. Verify layout: `python_binary` y `repo_root` deben existir

Return `BootstrapResult(runtime_dir, python_binary, repo_root, runtime_version, reused_existing)`.

**Importante**: `ensure_extracted` NO hace probe pre-exec del binary contra Bionic/Windows/etc. Ver [BUGS H8](BUGS_LATENTES_20260416.md#h8).

### Upgrader P2P — `tools/gimo_server/services/runtime_upgrader.py`

`upgrade_from_peer()` línea 217:
1. GET `{peer}/ops/mesh/runtime-manifest` (línea 258)
2. Verify sig bail-early (línea 265)
3. Compare semver (línea 272) — UP_TO_DATE / UPGRADED / needs allow_downgrade
4. Download tarball HTTP Range resume (línea 296) — soporta 206 Partial
5. SHA-256 verify post-descarga (línea 305)
6. Atomic promote: `os.replace(partial, final)` (línea 317)
7. Extract via `ensure_extracted()` (línea 326)

### CI matrix — `.github/workflows/ci.yml:244-387`
4 entries:
- `android-arm64`: ubuntu-latest + `--python-source=standalone`
- `linux-x86_64`: ubuntu-latest + `--python-source=host`
- `windows-x86_64`: windows-latest + `--python-source=host`
- `darwin-arm64`: macos-14 + `--python-source=host`

Steps por entry:
1. Generate ephemeral Ed25519 keypair (líneas 293-313)
2. Build bundle (línea 315)
3. Verify signature + sha (línea 327)
4. Smoke `ensure_extracted` si host (línea 334, `if: matrix.python_source == 'host'`)
5. Smoke layout check si standalone (línea 355, sin exec)
6. Upload artifact (línea 378)

### Android gradle — `apps/android/gimomesh/app/build.gradle.kts`
- Task `fetchRuntimeBundle` línea 88: si `GIMO_RUNTIME_BUNDLE_URL` set, download 3 artefactos a `runtime-assets/`
- Task `packageCoreRuntime` línea 115: copia `.json` + `.tar.xz` + `.sig` + `trusted-pubkey.pem` a `src/main/assets/runtime/`
- `noCompress += listOf("xz", "tar")` (línea 60) — APK no re-comprime
- `mergeDebugAssets` + `mergeReleaseAssets` → `dependsOn(packageCoreRuntime)` línea 111-113

### Desktop launcher — `gimo_cli/commands/server.py`
`_resolve_launcher_python()` línea 267:
- Si bundle existe → `ensure_extracted()` → `(python_binary, repo_root, "bundle")`
- Si corrupto → fallback `(sys.executable, None, "host")` con warning
- PYTHONPATH inject: repo_root + site-packages

---

## Mesh services

### `MeshRegistry` — `services/mesh/registry.py` (410 LOC)
File-backed state machine. Archivos bajo `.orch_data/ops/mesh/devices/{device_id}.json`.

Public surface:
- `get_device()`, `list_devices()`, `save_device()`, `remove_device()`
- `authenticate_device(secret)` línea 163 — constant-time
- `enroll_device()` línea 182 — genera `device_secret` (32 bytes urlsafe), estado inicial `pending_approval`, auto-enrolla en workspace "default"
- `set_connection_state()` / `approve_device()` / `refuse_device()` líneas 219-243
- `process_heartbeat(payload)` línea 247 — merge HeartbeatPayload, auto-transition approved/reconnecting/offline → connected (línea 301), thermal lockout safety valve (línea 309)
- `record_thermal_event()` línea 320 — append a `thermal_events.jsonl`
- `get_eligible_devices()` línea 408 — filtro para dispatch

**State transitions** — `_CONNECTION_TRANSITIONS` línea 46 — valid edges entre ConnectionState.

### `DispatchService` — `services/mesh/dispatch.py` (291 LOC)
`dispatch(fingerprint, mesh_enabled, preferred_model)` línea 54.

Detalle del scoring: ver [Decision & routing pipeline → 9 filtros](#9-filtros-en-dispatchservice).

`emit_dispatch()` línea 61 — span observability best-effort no-blocking.

### `MdnsAdvertiser` — `services/mesh/mdns_advertiser.py` (213 LOC)
`start()` línea 56:
- Resolve local IP vía socket trick (línea 204)
- TXT record: hostname, port, mode, health, load, runtime_version
- HMAC-SHA256 sign payload `f"{hostname}:{port}:{mode}:{health}:{load:.2f}:{runtime_version}"` (línea 169)
- Register `_gimo._tcp.local.` via Zeroconf (línea 88)

`update_signals(health, mode, load, runtime_version)` línea 113 — rebuild TXT + `zc.update_service()`.

Signing con `hmac_signer.sign_payload(token, payload)` → 32 hex chars (128 bits truncados).

### `MdnsDiscovery` — `services/mesh/mdns_discovery.py` (150 LOC)
`discover_peers(token, timeout_seconds, max_peers)` línea 50:
- Zeroconf `ServiceBrowser` sobre `_gimo._tcp.local.`
- Parse TXT → `DiscoveredPeer(hostname, port, mode, health, load, version, runtime_version, verified)`
- Verify HMAC si token (líneas 109-117) — reconstruct payload + constant-time compare
- Sort: verified first, then health desc, load asc

### `ObservabilityBridge` — `services/mesh/observability.py` (84 LOC)
Thin sink a `ObservabilityService`:
- `emit_enrollment()`, `emit_state_change()`, `emit_dispatch()`, `emit_thermal()`
- Best-effort no-blocking

### `AndroidHostBootstrapService` — `services/mesh/host_bootstrap.py` (137 LOC)
`bootstrap_from_env()` línea 78 — lee env vars `GIMO_MESH_HOST_*`:
- ENABLED, DEVICE_ID, DEVICE_NAME, DEVICE_MODE, DEVICE_CLASS, INFERENCE_ENDPOINT

Si enabled → `registry.enroll_device()` + `set_connection_state(connected)` + write `host_runtime.json`.

### `WorkspaceService` — `services/mesh/workspace_service.py` (300+ LOC)
Invariantes INV-W1 through INV-W6. Persistencia: `workspaces/{ws_id}/workspace.json` + `members/{device_id}.json` + `pairing/{code}.json`.

Operaciones:
- `create_workspace()`, `delete_workspace()` (INV-W4: no se puede borrar "default")
- `create_pairing_code()` — TTL 5 min, single-use
- `join_workspace()` — redeem pairing code
- `add_member()`, `remove_member()` (INV-W5: owner no se puede auto-remover)
- `activate_workspace()` — INV-W2 device switch

### `EnrollmentService` — `services/mesh/enrollment.py` (150+ LOC)
Tokens time-limited, persistidos `.orch_data/ops/mesh/tokens/enroll_{hash}.json`.

`claim(token_str, device_id, device_mode, device_class)` línea 84 → MeshDeviceInfo en pending_approval.

### `TaskQueue` — `services/mesh/task_queue.py` (250+ LOC)
Utility tasks (ping, text_validate, shell_exec, etc). Persistencia `.orch_data/ops/mesh/tasks/t-{task_id}.json`.

`auto_assign_pending()` — busca eligible devices del workspace + asigna al top score.

### `TelemetryService` — `services/mesh/telemetry.py` (250+ LOC)
Singleton via `TelemetryService._singleton_instance`.

`ingest_thermal_event()` línea 94:
- Update counters: warnings/throttles/lockouts
- Temporal decay: 3+ días → 0.75, 7+ días → 0.5
- Penalties: lockout -5.0, throttle -2.0, warning -0.5
- `health_score = max(0, 100 - total_penalties)`
- `duty_cycle = 0.8 × avg_time_to_throttle_min` (0 si throttles==0, unlimited)

### `MeshAuditService` — `services/mesh/audit.py` (140 LOC)
Append-only `audit.jsonl` con rotación a los 10 MB → `audit.1.jsonl` ... `audit.3.jsonl`.

---

## Android Kotlin adapter

`apps/android/gimomesh/app/src/main/` — 46 archivos Kotlin.

### Lifecycle completo
1. `MainActivity.onCreate()` (líneas 20-75): parse intent extras, deep link `gimo://enroll?code=...`, set Compose tree
2. `SetupWizardScreen` — enroll token/deep link, device_mode selection, hybrid pills
3. User toggles pill → `MeshViewModel.toggleMesh()` → `startMeshService()`
4. `MeshAgentService.onStartCommand(ACTION_START)` línea 75 → `startMesh()` línea 83-196
5. `ShellEnvironment.init()` (líneas 31-66):
   - Extract `bin/busybox` → `/files/bin/busybox`
   - Extract `bin/llama-server` → `/files/bin/llama-server`
   - Create symlinks: sh, wget, curl, ls, cat, grep, sed, awk, tar, gzip, etc. (líneas 48-55)
   - `prepareEmbeddedCoreRuntime()` (línea 164): read manifest JSON, extract 15169 files, set pythonBinary, repoRoot, PYTHONPATH
   - `isReady = File(binDir, "sh").exists() && llamaServer.canExecute()` (línea 59) — ver [BUGS H1](BUGS_LATENTES_20260416.md#h1)
6. Heartbeat loop cada 30s: `MetricsCollector.collect()` + sync device_secret + POST `/ops/mesh/heartbeat` + thermal lockout check + notification update
7. `EmbeddedCoreRunner.start()` (líneas 36-139):
   - Validate runtime + token
   - `python3 -m uvicorn tools.gimo_server.main:app --host 0.0.0.0 --port 9325`
   - Env: PYTHONPATH, ORCH_PORT, ORCH_OPERATOR_TOKEN, GIMO_MESH_HOST_*
   - Wait 60s for `/ready` 200 → health monitor loop cada 15s
8. `InferenceRunner.start()` (líneas 41-98): `llama-server --model ... --port 8080`
9. `startTaskPolling()` (líneas 287-324): cada 5s GET `/tasks/poll/{device_id}` → `TaskExecutor.execute()` → POST `/tasks/{id}/result`
10. STOP MESH NODE: `stopMesh()` (líneas 331-350) — cancel jobs + coreRunner.stop() + inferenceRunner.stop()

### Archivos clave

| Clase | Rol | File (relative to app/src/main/java/com/gredinlabs/gimomesh) |
|---|---|---|
| GimoMeshApp | Application singleton | (ver package) |
| MainActivity | Entry + Compose | |
| MeshViewModel | MVVM state holder | |
| MeshAgentService | Foreground service owner | service/MeshAgentService.kt |
| ShellEnvironment | Extract bins/runtime | service/ShellEnvironment.kt |
| EmbeddedCoreRunner | Python Core process lifecycle | service/EmbeddedCoreRunner.kt |
| InferenceRunner | llama-server process | service/InferenceRunner.kt |
| TaskExecutor | Sandboxed utility task exec | service/TaskExecutor.kt |
| MetricsCollector | /proc + /sys readers | service/MetricsCollector.kt |
| HostRuntimeReporter | StateFlow<Status> | service/HostRuntimeReporter.kt |
| TerminalBuffer | Ring buffer 5000 líneas | service/TerminalBuffer.kt |
| SettingsStore | DataStore persist | data/SettingsStore.kt |
| GimoCoreClient | OkHttp client | data/api/GimoCoreClient.kt |
| ControlPlaneRuntime | Helpers isServeMode / allowsInference | service/ControlPlaneRuntime.kt |
| BleWakeReceiver | Wake on BLE | service/BleWakeReceiver.kt |
| BootReceiver | BOOT_COMPLETED handler | service/BootReceiver.kt |

### Assets

Declarados por el código, extraídos por `ShellEnvironment`:
- `bin/busybox` — **0 bytes placeholder** (ver H1)
- `bin/llama-server` — **0 bytes placeholder** (ver H1)
- `runtime/gimo-core-runtime.tar.xz` — **78.5 MiB real** (producido 2026-04-16)
- `runtime/gimo-core-runtime.json` — manifest
- `runtime/gimo-core-runtime.sig` — Ed25519 firma
- `runtime/trusted-pubkey.pem` — public key

### HeartbeatPayload contract (Kotlin → Python)

POST `{baseUrl}/ops/mesh/heartbeat` con header `Authorization: Bearer {token}`:

```json
{
  "device_id": "samsung-galaxy-s24",
  "device_secret": "...",
  "device_mode": "server|inference|utility|hybrid",
  "operational_state": "idle|busy|paused|error",
  "cpu_percent": 45.2, "ram_percent": 62.1, "battery_percent": 87.0,
  "cpu_temp_c": 42.5, "gpu_temp_c": -1.0, "battery_temp_c": 35.0,
  "model_loaded": "qwen2.5:3b",
  "inference_endpoint": "http://192.168.1.100:8080",
  "active_task_id": "", "mode_locked": false,
  "capabilities": {
    "arch": "arm64-v8a", "cpu_cores": 8, "ram_total_mb": 12288,
    "storage_free_mb": 102400, "api_level": 35,
    "soc_model": "SM8650", "has_gpu_compute": true,
    "max_file_descriptors": 32768
  },
  "workspace_id": "default"
}
```

Response: `MeshDevice` (líneas 35-54 MeshModels.kt).

### TaskExecutor security
- `SHELL_ALLOWLIST = {ls, cat, df, free, uname, date, echo, wc, stat, uptime}`
- `SHELL_DENY_PATTERNS = {|, ;, &&, ||, ` +"`"+ `, $(, rm, su, chmod, chown, mkfs, dd, reboot, shutdown}`
- Path traversal check: `canonicalPath.startsWith(filesDir.canonicalPath)`
- `withTimeout(timeoutSeconds * 1000L)` envuelve toda ejecución

---

## Surfaces

### HTTP — `tools/gimo_server/routers/ops/` (31 routers)

| Router | Endpoints (aprox) | Función |
|---|---|---|
| `mesh_router.py` | 45 | Devices, enrollment, heartbeat, thermal, tasks, workspaces, onboarding, runtime |
| `run_router.py` | 30+ | Runs, drafts, workflows, action-drafts |
| `plan_router.py` | 10+ | Plan, drafts, approvals |
| `hitl_router.py` | 5+ | Human-in-the-loop gates |
| `capability_router.py` | 5 | Model capability queries |
| `catalog_router.py` | 8 | Provider catalog |
| `config_router.py` | 10+ | Provider config CRUD |
| `conversation_router.py` | 5 | Threads (incluye agentic chat P1.1) |
| `observability_router.py` | 5 | Spans, metrics, rate-limits |
| `skills_router.py` | 5 | Skills CRUD |
| `trust_router.py` | 5 | Trust engine queries |
| `tools_router.py` | 5 | Tools catalog |
| `policy_router.py` | 5 | Runtime policy config |
| `gics_patterns_router.py` | 5 | GICS pattern CRUD |
| `graph_router.py` | 3 | Plan graph rendering |
| `inference_router.py` | 5 | Local inference |
| `mastery_router.py` | 5 | Token mastery + forecast |
| Otros 14 routers... | | |

**Total**: ~270 paths.

Auth: `verify_token` sets `request.state.auth_role`. Rate limit per role en `security/rate_limit.py`: actions=60/min, operator=200/min, admin=1000/min.

### MCP — `tools/gimo_server/mcp_bridge/`

**Nativas (22 tools)**:
`gimo_get_status`, `gimo_wake_ollama`, `gimo_start_engine`, `gimo_stop_engine`, `gimo_propose_structured_plan`, `gimo_approve_draft`, `gimo_reject_plan`, `gimo_approve_plan`, `gimo_run_task`, `gimo_create_draft`, `gimo_get_draft`, `gimo_chat`, `gimo_list_agents`, `gimo_spawn_subagent`, `gimo_get_task_status`, `gimo_resolve_handover`, `gimo_dashboard`, `gimo_generate_team_config`, `gimo_estimate_cost`, `gimo_evaluate_action`, `gimo_get_trust_profile`, `gimo_trust_circuit_breaker_get`, `gimo_gics_anomaly_report`, `gimo_gics_model_reliability`, `gimo_verify_proof_chain`, `gimo_get_governance_snapshot`, `gimo_web_search`, `gimo_get_plan_graph`, `gimo_get_execution_policy`, `gimo_get_budget_status`, `gimo_get_gics_insight`, `gimo_register_model_context_limit`, `gimo_get_model_context_limits`, `gimo_get_server_info`.

**Dinámicas (~50)**: auto-sync desde OpenAPI.

**Resources (5)**: config, runs, drafts, roi, cascade.

**Prompts (3)**: plan_creation, debug_run, optimize_cost.

### CLI — `gimo.py` + `gimo_cli/commands/`

Comandos:
- **Core**: `main` (callback), `status`, `up`, `down`, `ps`
- **Auth**: `login`, `logout`, `whoami`
- **Runs**: `execute`, `status`, `logs`, `cancel`
- **Chat**: `chat_cmd` (interactive)
- **Plan**: `list`, `get`, `set`, `approve`, `reject`
- **Ops**: `draft create/list/update`, `run list/get`
- **Providers**: `list`, `connect`, `disconnect`, `test`
- **Skills**: `list`, `install`, `execute`, `create`
- **Threads**: `list`, `get`, `resume`
- **Trust**: `get_profile`, `circuit_breaker`
- **Observe**: `stream`, `logs`
- **Repos**: `list`, `connect`
- **Discover**: `scan`, `list`, `connect` (mDNS)
- **Mastery**: plan economy
- **Runtime**: `status`, `upgrade` (R21 2026-04-16)

`gimo` (sin subcomando) = interactive chat = `gimo chat` (P1.1).

### Web UI — `tools/orchestrator_ui/src/`
React + Vite + TypeScript. Dashboard + Mesh + Runs + Plan + Settings. i18n EN+ES vía react-i18next.

Auth dual: Bearer (API/CLI) + httpOnly cookie session (UI). Fetch via `fetchWithRetry` from `lib/fetchWithRetry.ts`.

---

## Data models canónicos

### `tools/gimo_server/models/mesh.py`
- `DeviceMode` enum (línea 10): `inference|utility|server|hybrid`
- `ConnectionState` enum (línea 17): `offline|discoverable|pending_approval|approved|refused|connected|reconnecting|thermal_lockout`
- `OperationalState` enum (línea 28): `idle|busy|paused|draining|disabled|error|locked_out`
- `DeviceCapabilities` (línea 38)
- `MeshDeviceInfo` (línea 88)
- `ThermalEvent` (línea 138)
- `HeartbeatPayload` (línea 178)
- `MeshHostInfo` — /ops/mesh/host response shape
- `Workspace`, `WorkspaceMembership`, `PairingCode`
- `MeshTask`, `TaskResult`

### `tools/gimo_server/models/agent_routing.py`
- `TaskDescriptor` (línea 41)
- `TaskConstraints` (línea 57)
- `ProviderRoleBinding`, `ProviderRolesConfig`
- `ExecutionPolicyName`, `BindingMode`, `RiskBand`, `ComplexityBand`, `ParallelismHint`, `SourceShape`, `MutationMode`

### `tools/gimo_server/models/runtime.py`
- `RuntimeTarget` enum (línea 25): android-arm64, android-armv7, linux-x86_64, linux-arm64, darwin-arm64, darwin-x86_64, windows-x86_64
- `RuntimeCompression` enum (línea 42): xz, zstd, none
- `RuntimeManifest` (línea 50): 18 campos + `signing_payload()` método

### `tools/gimo_server/ops_models.py`
Cost: `CostAnalytics`, `BudgetForecast`, `MasteryStatus`, `UserEconomyConfig`.

---

## Persistencia (disco + locks)

Bajo `.orch_data/ops/mesh/` salvo indicación:

| Datos | Path | Lock | Formato | Mutación |
|---|---|---|---|---|
| Devices | `devices/{device_id}.json` | `.mesh.lock` (5s) | JSON | atomic temp+rename |
| Thermal events | `thermal_events.jsonl` | — | JSONL append-only | append |
| Thermal profiles | `thermal_profiles/{device_id}.json` | `.telemetry.lock` | JSON | direct |
| Enrollment tokens | `tokens/enroll_{hash}.json` | `.enrollment.lock` | JSON | direct |
| Utility tasks | `tasks/t-{task_id}.json` | `.tasks.lock` | JSON | atomic |
| Workspaces | `workspaces/{ws_id}/workspace.json` | `.workspaces.lock` | JSON | direct |
| Workspace members | `workspaces/{ws_id}/members/{device_id}.json` | idem | JSON | atomic |
| Pairing codes | `workspaces/{ws_id}/pairing/{code}.json` | idem | JSON | direct |
| Audit log | `audit.jsonl` (rotativo 10MB → .1, .2, .3) | — | JSONL | append |
| Host runtime | `host_runtime.json` | — | JSON | direct |
| GICS data | (via `GicsService`) | — | named pipe | put/get |

---

## Test coverage map

### Unit (70+ files)
- `test_mesh_e2e.py` — registry/enrollment/telemetry/dispatch lifecycle
- `test_runtime_bootstrap.py` — sig verify + extraction + atomic swap
- `test_runtime_upgrader.py` — version compare + download + sig verify + fallback
- `test_runtime_signature.py` — Ed25519 ops
- `test_runtime_manifest_schema.py` — (nota: referenciado pero no existe; solo `test_runtime_manifest.py`?)
- `test_launcher_bundle_selection.py` — bundle vs host path
- `test_runtime_cross_compile.py` — standalone asset mapping + pip platform args (plan CROSS_COMPILE)
- `test_embedded_runtime_pubkey.py` — EMBEDDED_RUNTIME_PUBLIC_KEY constant
- `test_ci_runtime_matrix.py` — YAML static audit
- `test_android_gradle_runtime_wiring.py` — gradle task static audit
- `test_model_router_service.py` — scoring + tier filter
- `test_mesh_observability_bridge.py` — span emission
- `test_mdns_advertiser.py` — 21 tests: TXT build, HMAC, refresh loop
- `test_boot_mesh_disabled.py` — mesh-off invariant
- `test_server_mode_boot.py` — 8 tests: env bootstrap, TXT record signals, mDNS auto-enable gate
- 50+ más (policy gate, risk gate, intent classification, constraint compiler, session pool, run lifecycle, memory manager, shard planner, git pipeline, hardware monitor, compliance)

### Integration (5+ files)
- `test_mesh_runtime_endpoints.py` — 8 tests: 401, 404 actionable, 200 con headers, Range→206, 416, rate limit 6/60s
- `test_boot_mesh_disabled.py` — mesh-off invariant
- `test_core_packaging.py` — CI pipeline E2E
- `test_adversarial_e2e.py`, `test_adversarial_int.py`, `test_qwen_payload.py` — LLM suites

**Total broad**: 1759 passed, 1 flaky (`test_execute_plan_persists_running_and_final_node_states` — pre-existente, unrelated), 1 skipped. ~3 min full suite.

---

## Docs inventory

### Architecture
- `docs/DEV_MESH_ARCHITECTURE.md` — canonical mesh (APPROVED)
- `docs/GIMO_MESH_INVARIANTS.md` — I/II/III invariants (H1-H4, S1-S5, W1-W6)
- `docs/SYSTEM.md` — multi-surface sovereign platform
- `docs/SECURITY.md` — JWT offline auth + Ed25519 + credential sandboxing
- `docs/MCP_ARCHITECTURE.md` — canonical MCP reference
- `docs/MESH_SERVER_RUNBOOK.md` — operational procedures

### Audits (23+ E2E cycles, 2026-04-03 → 2026-04-16)

Pattern por ronda: `AUDIT_LOG → ROOT_CAUSE_ANALYSIS → ENGINEERING_PLAN → IMPLEMENTATION_REPORT`.

Rondas cubiertas: R5 (execution boundary), R6-R10 (delivery paths), R15-R16 (MCP bridge), R17 (trust engine), R18-R20 (governance), R21-R22 (landing).

Planes vivos relevantes:
- `E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING.md` — DONE, 11 changes + retired
- `E2E_IMPLEMENTATION_REPORT_20260416_RUNTIME_PACKAGING.md` — DONE
- `E2E_ENGINEERING_PLAN_20260416_RUNTIME_CROSS_COMPILE.md` — DONE, 6 changes
- `E2E_IMPLEMENTATION_REPORT_20260416_RUNTIME_CROSS_COMPILE.md` — DONE
- `E2E_ENGINEERING_PLAN_20260415_SERVER_MODE_FULL.md` — APROBADO, 11 changes, en Fase 4
- `E2E_IMPLEMENTATION_REPORT_20260415_SERVER_MODE_FULL.md` — PARTIALLY_DONE
- `E2E_S10_SERVER_MODE_RUNBOOK_20260415.md` — 6 fases
- `E2E_ENGINEERING_PLAN_20260415_SERVER_MODE_RUNTIMES.md` — PROPUESTO

---

## Matriz de conexiones

### Superficies × Servicios

| Superficie | HTTP Router | MCP Tool | CLI | Backend Service |
|---|---|---|---|---|
| Mesh UI | mesh_router | propose_structured_plan | ops | MeshRegistry, DispatchService |
| Heartbeat | mesh_router | — | runtime discover | TelemetryService |
| Task dispatch | mesh_router | run_task | run | DispatchService, TaskQueue |
| Plan editor | plan_router, run_router | create_draft | plan | PlanService, CognitiveService |
| Workspace | mesh_router | — | ops | WorkspaceService |
| Runtime dist | mesh_router | — | runtime | RuntimeBootstrapService |
| Onboard QR | mesh_router | — | mesh onboard | OnboardingService |
| Admin | hitl_router, run_router | approve_draft | — | HitlGateService |
| Trust/Policy | trust_router, policy_router | get_trust_profile | trust | TrustEngine |
| Provider | config_router, catalog_router | — | providers | ProviderService |
| Server | all routers | — | server up/down | main.py lifespan |

### Estados de conexión entre servicios (no-todos listados)

| Servicio A | Servicio B | Estado | Evidencia |
|---|---|---|---|
| RuntimePolicyService | IntentClassificationService | CONNECTED | intent checks policy_decision, línea 135 |
| RuntimePolicyService | ConstraintCompilerService | CONNECTED | líneas 149, reduce policies si deny |
| GICS reliability | ConstraintCompilerService | CONNECTED | trust gate línea 78 |
| GICS reliability | ModelRouterService | PARTIAL | penalty -0.25 sí, hard filter NO |
| CapabilityProfileService | ModelRouterService | CONNECTED | _gics_success_adjustment línea 248 |
| CapabilityProfileService | ConstraintCompilerService | PARTIAL | advisory metadata, no filter |
| ModelInventoryService | ModelRouterService | CONNECTED (stale-risky) | línea 161, no refresh |
| BenchmarkEnrichmentService | ModelInventoryService | CONNECTED (startup-only) | línea 184-209 |
| BenchmarkEnrichmentService | ModelRouterService | DISCONNECTED | no fetch per-request |
| ProviderTopologyService | ModelRouterService | CONNECTED | línea 274-277 |
| ProviderTopologyService | ConstraintCompilerService | DISCONNECTED | compiler no popula allowed_bindings |
| TaskDescriptor.required_tools | any | DEAD | siempre `[]` |
| TaskConstraints.allowed_bindings | any | DEAD | siempre `[]` |
| ModelEntry.context_window | any | DEAD | never read |
| HardwareMonitorService | ModelRouterService | CONNECTED | línea 530-531 |
| HardwareMonitorService | DispatchService | PARTIAL | filtros hardcoded en dispatch, no from HardwareSnapshot |
| ModelRecommendationEngine | DispatchService | DISCONNECTED | solo usado en endpoint `/model-recommendations` |
| DispatchService | ObservabilityService | CONNECTED | best-effort no-blocking |
| DispatchService | AuditLog | DISCONNECTED | no dispatch record |

---

## Cambios relevantes recientes

- **2026-04-16 RUNTIME_PACKAGING** (R21): 11 changes DONE. Bundle firmado Ed25519, pipeline completo CI matrix 4 targets, P2P upgrade, mDNS TXT con runtime_version, desktop launcher bundle-aware, Android gradle task.
- **2026-04-16 RUNTIME_CROSS_COMPILE** (R22): 6 changes DONE. Fetcher python-build-standalone, pip --platform, CI matrix real cross-compile, trusted pubkey embedded, gradle fetchRuntimeBundle.
- **2026-04-15 SERVER_MODE_FULL**: 11 changes PARTIALLY_DONE. --role server CLI flag, bind 0.0.0.0 auto, dispatch self-penalty, /ops/mesh/host endpoint, gimo discover CLI, mDNS TXT health/mode/load.

---

## Actualización de este documento

- **Rev 1**: 2026-04-16 — creado tras audit paralelo de 6 agentes
- Próxima revisión: tras cualquier plan que introduzca campos nuevos en `MeshDeviceInfo`, `TaskDescriptor`, `HardwareSnapshot`, o endpoints nuevos bajo `/ops/mesh/`

**Para preguntas arquitectónicas**: consultar este doc antes de consultar memoria o proponer. Si un servicio no aparece aquí, NO existe todavía. Si aparece con anclaje `file:línea`, **existe tal como se describe**.
