# GIMO Inference Engine (GIE) — Plan de implementación por fases

## Estado actual

### Ya creado (branch `claude/gimo-npu-inference-engine-qG49d`):
- `tools/gimo_server/inference/` — estructura de directorios
- `tools/gimo_server/inference/contracts.py` — 15 dataclasses/enums: `HardwareTarget`, `TaskSemantic`, `ModelFormat`, `ExecutionProviderType`, `ShardStrategy`, `QuantizationType`, `ModelSpec`, `DeviceCapability`, `InferenceRequest`, `InferenceResult`, `MemoryBudget`, `CompiledModelInfo`
- `tools/gimo_server/inference/__init__.py` — módulo raíz
- Subdirectorios vacíos: `runtime/`, `hardware/`, `compiler/`, `router/`

### Ya existe en GIMO (servicios que GIE debe integrar):
- `hardware_monitor_service.py` — detecta CPU/GPU/NPU, `HardwareSnapshot`
- `recommendation_service.py` — scoring hardware, tiers, selección de provider
- `resource_governor.py` — admission control (CPU/RAM/VRAM gates)
- `model_router_service.py` — routing de modelos por task type + hardware state
- `model_inventory_service.py` — registro dinámico de modelos con quality tiers
- `engine_service.py` — pipeline compositions, `_COMPOSITION_MAP`

---

## Arquitectura objetivo

```
Agent Task
    ↓
GIMO Orchestrator (engine_service.py)
    ↓
GIE Task Router  ←──── Hardware Scheduler
    ↓                        ↓
Model Selector          Device Detector
    ↓                        ↓
Memory Manager     ←──── Memory Budget Calculator
    ↓
Runtime Adapter (ONNX Runtime)
    ↓
Execution Provider (CPU EP / CUDA EP / VitisAI EP / OpenVINO EP / DML EP)
    ↓
Hardware (CPU / GPU / NPU)
```

---

## FASE 1 — Runtime Abstraction Layer

**Objetivo**: Capa de abstracción sobre ONNX Runtime que gestiona sesiones de inferencia, detecta execution providers disponibles y ejecuta modelos.

### Archivos a crear:

#### 1.1 `inference/runtime/base_adapter.py`
- Protocol `RuntimeAdapter` con métodos:
  - `async load_model(spec: ModelSpec, device: HardwareTarget) -> SessionHandle`
  - `async run(session: SessionHandle, inputs: dict) -> dict`
  - `async unload(session: SessionHandle) -> None`
  - `get_available_providers() -> list[ExecutionProviderType]`
  - `get_provider_options(ep: ExecutionProviderType) -> dict`

#### 1.2 `inference/runtime/onnx_adapter.py`
- Implementación de `RuntimeAdapter` sobre `onnxruntime.InferenceSession`
- Detección automática de EPs instalados (`ort.get_available_providers()`)
- Mapeo de `HardwareTarget` → EP chain (prioridad):
  - NPU: `[VitisAI, OpenVINO, QNN, DML, CPU]`
  - GPU: `[CUDA, TensorRT, ROCm, DML, CPU]`
  - CPU: `[CPU]`
- Session options optimizados por device (graph optimization level, thread count, memory arena)
- IO binding para GPU/NPU (zero-copy cuando sea posible)

#### 1.3 `inference/runtime/gguf_adapter.py`
- Adapter para modelos GGUF via `llama-cpp-python`
- Soporte de layer offloading (`n_gpu_layers` dinámico basado en VRAM libre)
- Mapeo de `HardwareTarget` a configuración llama.cpp:
  - GPU: `n_gpu_layers=-1` (todo a GPU)
  - CPU: `n_gpu_layers=0`
  - Hybrid: cálculo automático de layers en GPU vs CPU

#### 1.4 `inference/runtime/session_pool.py`
- Pool de sesiones activas con LRU eviction
- `max_concurrent_sessions` basado en memoria disponible
- Warm-up de sesiones frecuentes (pre-load en startup)
- Métricas: hit rate, eviction count, load latency

### Dependencias nuevas:
- `onnxruntime` (core) — ya estándar, ~50MB
- `llama-cpp-python` (opcional) — para GGUF
- Ambas como optional dependencies en `requirements.txt`

### Tests:
- `tests/unit/test_onnx_adapter.py` — mock de onnxruntime
- `tests/unit/test_session_pool.py` — LRU eviction, concurrent access

---

## FASE 2 — Hardware Backends & Device Detection

**Objetivo**: Detección profunda de capacidades de cada device (no solo presencia, sino bandwidth, TOPS reales, EPs soportados).

### Archivos a crear:

#### 2.1 `inference/hardware/device_detector.py`
- Clase `DeviceDetector` que extiende la detección de `hardware_monitor_service.py`:
  - CPU: cores, cache L3, RAM bandwidth (estimada por DDR type)
  - GPU: VRAM, compute capability, memory bandwidth, driver version
  - NPU: vendor, TOPS, firmware version, EPs soportados
- Devuelve `list[DeviceCapability]` (uno por device)
- Cache de 30s (hardware no cambia en runtime)

#### 2.2 `inference/hardware/cpu_backend.py`
- Configuración óptima para CPU inference:
  - Thread count = physical cores (no hyperthreading)
  - Memory arena = enabled
  - Inter-op parallelism basado en cores disponibles
  - NUMA-aware allocation cuando sea posible
- Estimación de throughput: `tokens_per_sec ≈ cores * 2.5 / param_billions`

#### 2.3 `inference/hardware/gpu_backend.py`
- NVIDIA: CUDA EP con TensorRT fallback
- AMD: ROCm EP o DML EP
- Intel Arc: DML EP
- iGPU (AMD/Intel): DML EP con shared memory constraints
- Gestión de VRAM: pre-allocation, defragmentation hints
- Estimación: `tokens_per_sec ≈ memory_bandwidth_gbps * 0.5 / (param_billions * bytes_per_param)`

#### 2.4 `inference/hardware/npu_backend.py`
- AMD XDNA (Ryzen AI): VitisAI EP
  - Detección via `xrt-smi` o WMI
  - Quantization requerida: INT8 mínimo
  - Modelos soportados: ≤ 3B params (NPU solo), ≤ 13B (NPU+CPU hybrid)
- Intel Core Ultra: OpenVINO EP
  - Detección via `openvino.runtime.Core().available_devices`
- Qualcomm (futuro): QNN EP
- Apple (futuro): CoreML EP
- Cada backend reporta: TOPS reales, modelos soportados, constraints

#### 2.5 `inference/hardware/unified_memory_manager.py`
- Para APUs (ROG Ally X, Steam Deck, Mac M-series):
  - Detecta pool de memoria compartido
  - Calcula reparto óptimo: X GB para GPU context, Y GB para model weights
  - Ajusta dinámicamente según presión de memoria del sistema
  - Ventaja clave: sin copia CPU↔GPU (zero-copy via memory-mapped tensors)

### Integración con servicios existentes:
- `DeviceDetector` usa `HardwareMonitorService.get_snapshot()` como base
- Extiende con detección profunda (bandwidth, TOPS, EPs)
- `hardware_monitor_service.py` gana un nuevo campo `devices: list[DeviceCapability]`

### Tests:
- `tests/unit/test_device_detector.py`
- `tests/unit/test_npu_backend.py`
- Mock de subprocess para detección en CI

---

## FASE 3 — Memory Manager (carga de modelos oversized)

**Objetivo**: Cargar modelos más grandes de lo que cabe en un solo device. Esta es la innovación clave — donde GIMO supera a la competencia.

### Archivos a crear:

#### 3.1 `inference/memory_manager.py`
- Clase `MemoryManager`:
  - `calculate_budget(model: ModelSpec, devices: list[DeviceCapability]) -> MemoryBudget`
  - `plan_sharding(budget: MemoryBudget) -> ShardPlan`
  - `execute_shard_load(plan: ShardPlan) -> list[SessionHandle]`

#### 3.2 `inference/shard_planner.py`
- Algoritmo de sharding inteligente:

```
Dado: model_size, gpu_free, cpu_free, npu_capacity, disk_available

Si model_size <= gpu_free * 0.85:
    → NONE (carga completa en GPU)

Si model_size <= gpu_free + npu_capacity:
    → LAYER_SPLIT: embedding+attention en NPU, FFN en GPU

Si model_size <= gpu_free + cpu_free * 0.6:
    → OFFLOAD_CPU: primeras N capas en GPU, resto en CPU RAM
    → N = floor(gpu_free / layer_size)

Si model_size <= gpu_free + cpu_free * 0.6 + npu_capacity:
    → HYBRID: NPU (embedding/attention heads) + GPU (FFN) + CPU (overflow)

Si model_size <= gpu_free + cpu_free + disk_available:
    → OFFLOAD_DISK: mmap activado, GPU layers + CPU layers + disk pages
    → Con prefetch: lee siguiente batch de layers mientras ejecuta actual

Else:
    → REJECT con estimación de hardware necesario
```

- Para **ROG Ally X** (24GB unified, Z1 Extreme 16 TOPS NPU):
  - Modelo 13B Q4 (≈8GB): carga completa en unified memory, NPU para embedding
  - Modelo 34B Q4 (≈20GB): unified memory + disk offload para overflow
  - Modelo 70B Q4 (≈40GB): hybrid GPU+CPU+disk con aggressive mmap prefetch

#### 3.3 `inference/tensor_offloader.py`
- Implementa offloading real layer-by-layer:
  - Pre-fetching: while GPU procesa layer N, CPU carga layer N+2 a GPU
  - Pinned memory: usa `torch.cuda.pin_memory()` o equivalente ONNX para transfers rápidos
  - Doble buffering: dos buffers GPU alternando load/compute
- Métrica clave: **overhead ratio** = time_transfer / time_compute
  - Si < 0.3: offloading eficiente
  - Si > 0.5: alertar al usuario, recomendar modelo más pequeño

#### 3.4 `inference/mmap_engine.py`
- Memory-mapped model loading para modelos que no caben en RAM+VRAM:
  - Usa `mmap` de OS para cargar modelo desde disco bajo demanda
  - Page fault handling: el OS trae páginas según se necesitan
  - Prefetch hints: `madvise(MADV_SEQUENTIAL)` para lectura secuencial
  - Cache coherency: mantiene hot pages en RAM, evicta cold pages
- Esto permite "cargar" un modelo de 70GB en un PC con 24GB de RAM
  - Será lento pero funcional — mucho más útil que "no se puede"
  - Throughput estimado: ~2-5 tok/s (vs 20+ tok/s in-memory)

### Innovación diferenciadora:
La competencia (Ollama, LM Studio, vLLM) hace sharding simple. GIMO haría:
1. **NPU-aware sharding**: usa la NPU para embedding/attention (INT8) mientras GPU hace FFN
2. **Predictive prefetch**: analiza el patrón de acceso del modelo y pre-carga layers
3. **Adaptive rebalancing**: si GPU se calienta, mueve layers a CPU/NPU dinámicamente

### Tests:
- `tests/unit/test_shard_planner.py` — scenarios para cada strategy
- `tests/unit/test_memory_manager.py` — budget calculations
- `tests/integration/test_oversized_model.py` — with mock model

---

## FASE 4 — Hardware Scheduler & Task Router

**Objetivo**: Dado un task semántico, decidir qué hardware lo ejecuta y con qué modelo.

### Archivos a crear:

#### 4.1 `inference/router/task_router.py`
- Clase `TaskRouter`:
  - Input: `InferenceRequest` (contiene task semantic + model_id)
  - Output: `RoutingDecision` (device + EP + model + shard strategy)
- Tabla de afinidad task → hardware (configurable):

```python
TASK_AFFINITY = {
    TaskSemantic.EMBEDDING:       [NPU, GPU, CPU],   # NPU excels at INT8 matmul
    TaskSemantic.VISION:          [NPU, GPU, CPU],   # NPU has vision accelerators
    TaskSemantic.SPEECH:          [NPU, CPU, GPU],   # NPU speech blocks
    TaskSemantic.CLASSIFICATION:  [NPU, CPU, GPU],   # small, INT8 friendly
    TaskSemantic.RERANKING:       [NPU, CPU, GPU],   # small model, latency sensitive
    TaskSemantic.REASONING:       [GPU, CPU, NPU],   # large models, GPU memory
    TaskSemantic.CODE_GENERATION: [GPU, CPU, NPU],   # large models, long context
    TaskSemantic.DIFFUSION:       [GPU, NPU, CPU],   # GPU compute intensive
    TaskSemantic.SUMMARIZATION:   [GPU, NPU, CPU],   # medium models
    TaskSemantic.GENERAL:         [GPU, CPU, NPU],
}
```

- Priorización por:
  1. Afinidad del task
  2. Memoria disponible en el device
  3. Carga actual del device (utilization %)
  4. Historial de latencia (ewma)
  5. Temperatura del device

#### 4.2 `inference/router/hardware_scheduler.py`
- Scheduler de requests por hardware:
  - Queue por device (CPU queue, GPU queue, NPU queue)
  - Prioridad dentro de cada queue
  - Concurrent execution limits per device:
    - GPU: 1-2 concurrent (VRAM limited)
    - CPU: 1-N concurrent (RAM limited)
    - NPU: 1 concurrent (pipeline sequential)
  - Preemption: task de alta prioridad puede interrumpir baja prioridad
  - Batching: agrupa requests del mismo modelo para batch inference

#### 4.3 `inference/router/model_selector.py`
- Dado un task, selecciona el mejor modelo local:
  - Consulta `ModelInventoryService` para modelos disponibles
  - Filtra por task capability
  - Ordena por: fits_in_memory > quality_tier > latency_estimate
  - Considera modelo ya cargado en session pool (avoid reload penalty)

#### 4.4 `inference/router/load_balancer.py`
- Balanceo de carga entre devices del mismo tipo:
  - Round-robin weighted by free memory
  - Multi-GPU: distribuye requests entre GPUs
  - Fallback chain: si GPU full → NPU → CPU → cloud

### Integración:
- `TaskRouter` se integra con `ModelRouterService` existente
- Cuando `model_router_service` elige un modelo local, delega a GIE `TaskRouter`
- `hardware_scheduler` se conecta con `ResourceGovernor` para admission control

### Tests:
- `tests/unit/test_task_router.py` — affinity decisions
- `tests/unit/test_hardware_scheduler.py` — queue behavior, priorities
- `tests/unit/test_load_balancer.py` — fallback chains

---

## FASE 5 — Model Compiler Pipeline

**Objetivo**: Pipeline automático para convertir/optimizar/compilar modelos para cada target hardware.

### Archivos a crear:

#### 5.1 `inference/compiler/pipeline.py`
- Clase `CompilationPipeline`:
  - `async compile(model: ModelSpec, target: HardwareTarget) -> CompiledModelInfo`
  - Steps:
    1. Format conversion (PyTorch/GGUF → ONNX si necesario)
    2. Graph optimization (op fusion, constant folding)
    3. Quantization (INT8/INT4 calibration)
    4. Target-specific compilation (VitisAI, TensorRT, OpenVINO)
    5. Validation (accuracy check vs reference)
    6. Cache (save compiled + metadata)

#### 5.2 `inference/compiler/quantizer.py`
- Quantización automática:
  - Static quantization con calibration dataset
  - Dynamic quantization (sin dataset, más rápido)
  - Mixed precision: INT8 para linear layers, FP16 para attention
  - GPTQ/AWQ support para modelos pre-quantizados
- Selección automática de quantization por hardware:
  - NPU → INT8 obligatorio (INT4 si soporta)
  - GPU → FP16 o INT8 (según VRAM)
  - CPU → INT8 o INT4 (VNNI acceleration)

#### 5.3 `inference/compiler/graph_optimizer.py`
- ONNX graph optimizations:
  - Operator fusion (MatMul+Add → GEMM, LayerNorm fusion)
  - Constant folding
  - Dead code elimination
  - Shape inference
  - Usa `onnxruntime.transformers.optimizer` para transformer-specific fusions

#### 5.4 `inference/compiler/model_cache.py`
- Cache de modelos compilados en disco:
  - Path: `~/.gimo/models/<model_id>/<target>_<quant>/`
  - Estructura:
    ```
    ~/.gimo/models/
        qwen2.5-7b/
            cpu_int8/
                model.onnx
                metadata.json
            npu_int8/
                model.compiled
                metadata.json
            gpu_fp16/
                model.onnx
                metadata.json
    ```
  - Invalidación: hash del modelo original + versión del compiler
  - Limpieza: LRU por última fecha de uso, configurable max_cache_gb

### Tests:
- `tests/unit/test_quantizer.py`
- `tests/unit/test_model_cache.py`
- `tests/unit/test_compilation_pipeline.py`

---

## FASE 6 — Inference Engine Service (orquestación principal)

**Objetivo**: Servicio principal que unifica todo el subsistema y expone API.

### Archivos a crear:

#### 6.1 `inference/engine_service.py`
- Clase `InferenceEngineService` (singleton):
  - `async initialize()` — detecta hardware, pre-carga modelos frecuentes
  - `async infer(request: InferenceRequest) -> InferenceResult`
  - `async load_model(model_id: str, target: HardwareTarget) -> bool`
  - `async unload_model(model_id: str) -> bool`
  - `get_status() -> dict` — estado completo del engine
  - `get_loaded_models() -> list[ModelSpec]`
  - `get_device_status() -> list[DeviceCapability]`

- Flujo de `infer()`:
  1. `TaskRouter.route(request)` → device + model
  2. `MemoryManager.ensure_loaded(model, device)` → load/shard si necesario
  3. `HardwareScheduler.enqueue(request, device)` → espera turno
  4. `RuntimeAdapter.run(session, inputs)` → ejecuta
  5. Collect metrics, return `InferenceResult`

#### 6.2 `inference/metrics.py`
- Telemetría del inference engine:
  - Requests/sec per device
  - Average latency per task type
  - Token throughput (tok/s)
  - Memory utilization timeline
  - Cache hit rate
  - Model load time
  - Queue depth per device

### Integración con GIMO existente:

#### 6.3 Modificaciones a archivos existentes:

**`services/engine_service.py`**:
- Nueva composition `"local_inference"` que usa GIE en lugar de LLM API
- Cuando `model_router` selecciona modelo local → desvía a GIE

**`services/recommendation_service.py`**:
- NPU score sube de 0-5 a 0-15 (ahora es funcional, no "future-proofing")
- Nuevos tiers: `npu_accelerated` para PCs con NPU activa
- Task-specific recomendaciones (embedding→NPU, reasoning→GPU)

**`services/hardware_monitor_service.py`**:
- Nuevo campo `devices: list[DeviceCapability]` en `HardwareSnapshot`
- Integración con `DeviceDetector` de GIE

**`services/resource_governor.py`**:
- NPU admission gate (NPU tiene queue limitada)
- Shard-aware admission (oversized models consumen múltiples devices)

**`config.py`**:
- Nuevos settings:
  - `GIMO_INFERENCE_ENABLED: bool`
  - `GIMO_MODEL_CACHE_DIR: Path`  (default `~/.gimo/models/`)
  - `GIMO_MODEL_CACHE_MAX_GB: float` (default 50.0)
  - `GIMO_NPU_ENABLED: bool` (default True)
  - `GIMO_MAX_OVERSIZED_RATIO: float` (default 3.0 — load models up to 3x device memory)

#### 6.4 Nuevas rutas API:

**`routers/ops/inference_router.py`**:
- `GET /api/ops/inference/status` — estado del engine
- `GET /api/ops/inference/devices` — devices detectados
- `GET /api/ops/inference/models` — modelos cargados
- `POST /api/ops/inference/load` — cargar modelo
- `POST /api/ops/inference/unload` — descargar modelo
- `POST /api/ops/inference/run` — ejecutar inferencia
- `GET /api/ops/inference/metrics` — métricas

### Tests:
- `tests/unit/test_inference_engine_service.py`
- `tests/integration/test_inference_e2e.py`

---

## Resumen de fases y dependencias

```
FASE 1: Runtime Abstraction    ← sin dependencias, puede arrancar ya
FASE 2: Hardware Backends      ← depende parcialmente de Fase 1 (DeviceCapability)
FASE 3: Memory Manager         ← depende de Fase 1 + 2
FASE 4: Task Router/Scheduler  ← depende de Fase 2 (device info) + 3 (memory budget)
FASE 5: Model Compiler         ← depende de Fase 1 (runtime) + independiente del resto
FASE 6: Engine Service         ← integra todas las fases
```

### Paralelización posible:

```
     ┌── FASE 1 (Runtime) ──┐
     │                       ├── FASE 3 (Memory) ──┐
     ├── FASE 2 (Hardware) ──┘                      ├── FASE 6 (Engine)
     │                       ┌── FASE 4 (Router) ───┘
     └── FASE 5 (Compiler) ──┘
```

- **Agente A**: Fase 1 → Fase 3
- **Agente B**: Fase 2 → Fase 4
- **Agente C**: Fase 5 (independiente)
- **Agente D**: Fase 6 (espera a A+B+C)

### Archivos totales a crear: ~20 archivos Python nuevos
### Archivos a modificar: 4 servicios existentes + config + routes
### Dependencias nuevas: 2 (onnxruntime, llama-cpp-python) — ambas opcionales
