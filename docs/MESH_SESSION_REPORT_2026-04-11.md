# GIMO Mesh — Session Report 2026-04-11

## Resumen ejecutivo

Sesión completa de hardening, validación en hardware real (Samsung Galaxy S10), y despliegue local-only de inferencia LLM en un dispositivo Android sin root y sin internet. Se cross-compiló llama.cpp con Android NDK, se transfirió el modelo Qwen2.5-3B-Instruct vía ADB, y se validó inferencia funcional sobre la LAN a 2.6 tok/s.

---

## 1. Mesh Hardening (10+ fixes)

### Commit: `8a6c236` — `feat: GIMO Mesh hardening, inference endpoint, and mesh agent`

**Archivos modificados:**

| Archivo | Cambio |
|---|---|
| `tools/gimo_server/models/mesh.py` | Añadido `device_secret`, `inference_endpoint` a `MeshDeviceInfo` y `HeartbeatPayload` |
| `tools/gimo_server/services/mesh/registry.py` | Device secret generation, validation en heartbeat, `expire_stale_devices()`, offline→connected auto-recovery, atomic writes, cleanup de thermal profiles |
| `tools/gimo_server/services/mesh/dispatch.py` | `_filter_stale_heartbeats()` (120s max), `inference_endpoint` en `DispatchDecision` |
| `tools/gimo_server/services/mesh/enrollment.py` | TOCTOU fix — `enroll_device()` dentro del lock |
| `tools/gimo_server/services/mesh/audit.py` | Rotación de audit log (10MB, 3 rotaciones) |
| `tools/gimo_server/services/mesh/telemetry.py` | Singleton pattern, temporal decay (>7d = 50% penalty reduction) |
| `tools/gimo_server/main.py` | Background task `_mesh_heartbeat_timeout_loop()` — cada 15s expira devices sin heartbeat en 90s |
| `tests/unit/test_mesh_e2e.py` | 43 tests (era 42), nuevo test `test_heartbeat_wrong_secret_rejected`, todos los heartbeats actualizados con `device_secret` |
| `tests/integrity_manifest.json` | Regenerado con hashes normalizados CRLF→LF |

### Detalle de cada fix:

1. **Device secret authentication**: `secrets.token_urlsafe(32)` generado en enrollment, validado en cada heartbeat. Si no coincide → `ValueError`.
2. **Heartbeat timeout**: Background task cada 15s llama `registry.expire_stale_devices(90.0)`. Dispositivos sin heartbeat en 90s → `ConnectionState.offline`.
3. **TOCTOU en enrollment**: `enroll_device()` se movió dentro del bloque `with self._lock()`.
4. **Staleness filter en dispatch**: `_filter_stale_heartbeats()` rechaza devices con heartbeat >120s.
5. **Audit log rotation**: `_rotate_if_needed()` rota `audit.jsonl` → `.1` → `.2` → `.3` cuando supera 10MB.
6. **Telemetry singleton**: Patrón `__new__` + `__init__` con `_singleton_instance` a nivel de módulo.
7. **Temporal decay**: Eventos térmicos >7 días = 50% de reducción de penalty, >3 días = 75%.
8. **Atomic writes**: `tempfile.mktemp()` + `tmp.replace(path)` en `save_device()`.
9. **Offline→connected recovery**: Añadida transición `ConnectionState.offline` → `ConnectionState.connected` en `_CONNECTION_TRANSITIONS` y en `process_heartbeat()`.
10. **Device cleanup**: `remove_device()` también borra el JSON de thermal profile.
11. **Refused→approved**: Transición añadida para que admin pueda aprobar tras refusal.

---

## 2. Mesh Agent (nuevo — `tools/gimo_mesh_agent/`)

### Archivos nuevos:

| Archivo | Propósito |
|---|---|
| `mesh_agent_lite.py` | Agente standalone para Android/Termux. Envía heartbeats con métricas, device_secret, model_loaded, inference_endpoint. Exponential backoff, fatal code handling (401/403 → stop), max 10 failures consecutivos. |
| `android_metrics.py` | Recolección de métricas Android sin psutil: batería (`/sys/class/power_supply/battery/`), RAM (`/proc/meminfo`), temperaturas (`/sys/class/thermal/`), SoC info (`getprop`). |
| `start_mesh_node.sh` | Script de arranque unificado: lanza `llama-server` + `mesh_agent_lite.py`. Detecta runtime (adb shell vs Termux), auto-detecta IP local, cleanup on exit. |
| `setup_llama.sh` | Instalador de llama.cpp para Termux (pkg install + cmake build). **No usado** — se cross-compiló con NDK en su lugar. |
| `download_model.sh` | Downloader de modelos HuggingFace. **No usado** — user requiere local-only (sin internet en device). |

### CLI del agente:
```bash
python mesh_agent_lite.py \
  --core-url http://192.168.0.49:9325 \
  --token <GIMO_TOKEN> \
  --device-id galaxy-s10 \
  --device-secret <SECRET> \
  --model-loaded "qwen2.5:3b" \
  --inference-endpoint "http://192.168.0.244:8080" \
  --interval 30
```

---

## 3. Cross-compilación y despliegue local-only

### Hardware target: Samsung Galaxy S10 (Exynos 9820)

| Spec | Valor |
|---|---|
| SoC | Exynos 9820 |
| CPU | 4x Cortex-A55 + 2x Cortex-A75 + 2x Mongoose M4 (2.73GHz) |
| ISA | ARMv8.2 con `asimddp` (dot product), `asimd` (NEON), `fphp`, `asimdhp` |
| RAM total | 7,598 MB |
| RAM disponible | ~4,100 MB |
| Storage libre | 84 GB |
| GPU | Mali-G76 MP12 (inaccesible sin root) |
| Android | Stock, NO rooted |
| IP LAN | 192.168.0.244 |
| ADB WiFi | 192.168.0.244:36669 |

### Proceso de cross-compilación:

1. **Android NDK 27.2** instalado vía `sdkmanager` en PC
2. **CMake 3.22.1** instalado vía `sdkmanager`
3. **llama.cpp** clonado en `C:\Users\shilo\llama.cpp-build\`
4. Cross-compilado con:
   ```bash
   cmake -G Ninja -B build-android -S . \
     -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
     -DANDROID_ABI=arm64-v8a \
     -DANDROID_PLATFORM=android-28 \
     -DCMAKE_BUILD_TYPE=Release \
     -DGGML_OPENMP=OFF \
     -DGGML_LLAMAFILE=OFF
   cmake --build build-android --config Release -j8
   ```
5. **Binarios resultantes** en `build-android/bin/`:
   - `llama-server` (99MB) — servidor de inferencia con API OpenAI-compatible
   - `llama-cli` (83MB)
   - `libggml-base.so`, `libggml-cpu.so`, `libggml.so`, `libllama.so`, `libmtmd.so`
6. Binarios son **dynamically linked** contra `/system/bin/linker64` (Android linker) — funcionan directamente en Android sin Termux

### Transferencia al S10 (100% local, sin internet):

```bash
ADB="C:\Users\shilo\AppData\Local\Android\Sdk\platform-tools\adb.exe"

# Binario + libs → /sdcard/Download/ → cp → /data/local/tmp/
adb push llama-server //sdcard/Download/llama-server
adb push lib*.so //sdcard/Download/
adb shell "cp /sdcard/Download/llama-server /data/local/tmp/ && chmod 755 /data/local/tmp/llama-server"
adb shell "for f in lib*.so; do cp /sdcard/Download/$f /data/local/tmp/; done"

# Modelo (1.9GB) — blob directo de Ollama
adb push D:\Ollama\models\blobs\sha256-5ee4f07... //sdcard/Download/qwen2.5-3b-instruct.gguf
adb shell "cp /sdcard/Download/qwen2.5-3b-instruct.gguf /data/local/tmp/"
```

**NOTA IMPORTANTE sobre Git Bash en Windows**: Las rutas que empiezan con `/` se manglan por MSYS path conversion. Usar `//sdcard/` o `MSYS_NO_PATHCONV=1` para evitarlo.

### Ejecución y benchmarks:

```bash
# Arranque desde adb shell
MSYS_NO_PATHCONV=1 adb shell "cd /data/local/tmp && \
  LD_LIBRARY_PATH=/data/local/tmp \
  ./llama-server -m qwen2.5-3b-instruct.gguf -c 2048 --host 0.0.0.0 --port 8080 -t 4 -tb 8"
```

| Métrica | -t 4 | -t 8 |
|---|---|---|
| Prompt processing | 4.3-5.8 tok/s | 5.8 tok/s |
| Generation | **2.6 tok/s** | 1.4 tok/s |
| Recomendación | **Usar -t 4** | Demasiado overhead de sincronización |

**Conclusión**: 4 threads de generación es el sweet spot. Los 4 cores Cortex-A55 (efficiency) son tan lentos que lastran la sincronización. Los 2x Mongoose M4 + 2x A75 son los que hacen el trabajo real.

### Modelo seleccionado: Qwen2.5-3B-Instruct Q4_K_M

| Propiedad | Valor |
|---|---|
| Formato | GGUF V3, Q4_K_M (4.99 BPW) |
| Tamaño en disco | 1.79 GiB (1,929,903,008 bytes) |
| Parámetros | 3.09B |
| Arquitectura | Qwen2 |
| Capas | 36 |
| Embedding | 2048 |
| Context train | 32,768 |
| KV heads | 16 / 2 (GQA 8x) |
| Chat template | ChatML (`<\|im_start\|>`) |
| Idiomas | Multilingual (incluye español) |

**Por qué este modelo**: Superior a `qwen2.5-coder:3b` para tareas de mesh agent (instruction following > code generation). El agente no escribe código — ejecuta tareas, reporta status, maneja JSON estructurado. Qwen2.5-Instruct es best-in-class en structured output a 3B.

### Validación de inferencia:

```bash
# Desde el PC, via LAN
curl http://192.168.0.244:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5-3b-instruct","messages":[{"role":"user","content":"Hello"}]}'
```

Respuesta confirmada: `"I am running on a Samsung Galaxy S10."` — 12 tokens en 4.6s.

---

## 4. Cambios de ChatGPT (commit separado)

### Commit: `03c5215` — `refactor: remove legacy /ui/providers* routes`

ChatGPT ejecutó un plan de extirpación de `/ui/providers*`. **Estos cambios están commiteados pero ChatGPT puede no haber terminado aún su trabajo completo.** Verificar que:

- `tools/gimo_server/routers/legacy_ui_router.py` — rutas `/ui/providers*` eliminadas
- `tools/orchestrator_ui/src/hooks/useProviders.ts` — fallback a `/ui/providers` eliminado
- `tools/gimo_server/mcp_bridge/manifest.py` — regenerado sin entradas `/ui/providers*`
- Tests de ausencia (404) y canonicalidad añadidos

**El agente sucesor debe verificar** que ChatGPT completó su trabajo y que los tests pasan.

---

## 5. Estado actual del entorno

### Servidor GIMO
- **Corriendo** en PC (localhost:9325)
- Iniciado con `GICS_DISABLED=1` (zstd-codec no disponible)
- Token: almacenado en `.orch_token`

### S10
- **ADB WiFi conectado**: `192.168.0.244:36669`
- **llama-server**: PARADO (se paró al final de la sesión para ahorrar batería)
- **Archivos en `/data/local/tmp/`**: llama-server, 5 .so libs, modelo GGUF (1.9GB), mesh_agent_lite.py, android_metrics.py, start_mesh_node.sh
- **Device secret**: Generado manualmente → `JWjMJ8Zc5ZbmBIInasDuxJUV0cbJaN8_N9VoFwKnG8A` (en `.orch_data/ops/mesh/devices/galaxy-s10.json`)
- **Termux**: Abierto pero el agente NO corre desde Termux actualmente — corre desde `adb shell` en `/data/local/tmp/`

### ADB
- Binario: `C:\Users\shilo\AppData\Local\Android\Sdk\platform-tools\adb.exe`
- Siempre usar `MSYS_NO_PATHCONV=1` antes de comandos ADB con rutas absolutas en Git Bash

### Ollama (PC)
- Instalado: `C:\Users\shilo\AppData\Local\Programs\Ollama\ollama.exe`
- Modelos en: `D:\Ollama\models\`
- Modelos disponibles: `qwen2.5:3b`, `qwen2.5-coder:3b`, `llama3.2:3b`

### Cross-compilation artifacts
- llama.cpp source: `C:\Users\shilo\llama.cpp-build\`
- Android build: `C:\Users\shilo\llama.cpp-build\build-android\bin\`
- NDK: `C:\Users\shilo\AppData\Local\Android\Sdk\ndk\27.2.12479018\`
- CMake: `C:\Users\shilo\AppData\Local\Android\Sdk\cmake\3.22.1\`

### Git
- Branch: `feature/gimo-mesh`
- 2 commits ahead of origin
- Archivos untracked restantes: `engineering_calculator.py`, `vendor/__init__.py`, algunos test files de providers

---

## 6. Tareas pendientes (próxima sesión)

### Prioridad alta
1. **Mover ejecución a Termux**: Actualmente llama-server corre desde `adb shell`. Termux daría persistencia y acceso a `termux-notification`. Problema: Termux perdió permisos de `/sdcard/` tras un `am force-stop`. Necesita `termux-setup-storage` (interactivo — diálogo Android).

2. **Sentinel de wake/convocatoria**: Implementar el patrón descrito al final de la sesión — un proceso ligero que escucha UDP en el S10 y muestra notificación Android cuando GIMO Core necesita el dispositivo. Requiere `termux-api` package.

3. **Task delivery via heartbeat**: La respuesta del heartbeat debe incluir `pending_task` si hay una tarea asignada al dispositivo. El agente la ejecuta y reporta resultado en el siguiente heartbeat.

### Prioridad media
4. **Optimización de rendimiento del S10**: No se completó la investigación. El agente de búsqueda no devolvió resultados. Investigar:
   - `taskset` para afinidad a cores Mongoose M4 (¿funciona sin root?)
   - Cuantización Q4_0 vs Q4_K_M (Q4_0 usa dot product nativamente, podría ser más rápido)
   - Flags de compilación ARM-específicos (`-DGGML_CPU_AARCH64=ON` si existe)
   - `--no-mmap` para evitar page faults en la carga inicial

5. **Verificar trabajo de ChatGPT**: Confirmar que la extirpación de `/ui/providers*` está completa. Correr tests. Comprobar que no queden referencias vivas a `/ui/providers*` en el repo.

6. **Correr suite de tests completa**: 43 tests mesh + tests de providers + integrity test. No se corrió la suite completa en esta sesión tras todos los cambios.

### Prioridad baja
7. **SGLang como tier de servidor**: El PC tiene RTX 3060 8GB. SGLang sería un upgrade significativo sobre Ollama para el nodo servidor de la mesh. API compatible (OpenAI), constrained decoding para JSON, RadixAttention.

8. **Push a origin**: Los 2 commits locales no se pushearon. Verificar tests antes de push.

---

## 7. Decisiones de diseño tomadas

1. **Local-only**: El usuario requiere explícitamente que TODA la comunicación sea via WiFi local (LAN del router). Sin internet en el S10. Esto descarta FCM, Ollama pull, HuggingFace downloads, etc.

2. **Cross-compilación vs compilar en device**: Se eligió cross-compilación con NDK porque `pkg install` en Termux requiere internet para descargar build tools.

3. **adb shell vs Termux**: El binario NDK usa el linker de Android (`/system/bin/linker64`), funciona en ambos entornos. Actualmente corre desde adb shell porque Termux perdió permisos de storage.

4. **-t 4 vs -t 8**: Benchmark demostró que 4 threads es óptimo (2.6 tok/s vs 1.4 tok/s). Los cores efficiency (A55) lastran en vez de ayudar.

5. **Modelo Qwen2.5-3B-Instruct vs Coder**: Se eligió Instruct por ser superior en instruction following y structured output, que es lo que necesita un agente mesh (no escribe código).

6. **Separación de commits**: Mesh hardening y provider cleanup en commits separados para mantener historial limpio y facilitar revert si es necesario.

---

## 8. Problemas conocidos y workarounds

| Problema | Workaround | Estado |
|---|---|---|
| Git Bash mangla rutas `/data/...` | `MSYS_NO_PATHCONV=1` antes del comando ADB | Resuelto |
| `adb push` a `/data/local/tmp/` da fchown error | Push a `/sdcard/Download/`, luego `adb shell cp` a `/data/local/tmp/` | Resuelto |
| Termux pierde permisos `/sdcard/` tras force-stop | Necesita `termux-setup-storage` (interactivo) | Pendiente |
| `input text` con `%s` es unreliable en ADB | Usar archivos + cp en vez de typing commands | Workaround |
| GICS daemon crash (zstd-codec) | `GICS_DISABLED=1` al iniciar servidor | Workaround |
| CPU governor `schedutil` downclocka cores idle | Sin root no se puede cambiar a `performance`. La carga de inferencia lo sube naturalmente. | Sin fix |
| `curl` en Git Bash corrompe UTF-8 en JSON | Usar archivos temporales (`-d @/tmp/file.json`) | Resuelto |
