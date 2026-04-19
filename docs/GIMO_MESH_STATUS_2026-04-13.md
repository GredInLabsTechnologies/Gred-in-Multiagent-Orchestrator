# GIMO Mesh — Operational Status (2026-04-13)

> Estado: referencia operativa actual
> Alcance: describe lo que está realmente listo, lo que está en progreso y lo que sigue bloqueado en el repo y la app Android a fecha 2026-04-13.

---

## 1. Resumen ejecutivo

GIMO Mesh **sí puede presentarse hoy como beta de `inference mode`**.

No debe presentarse todavía como:

- `utility mode` listo de producto
- `server mode` operativo
- `hybrid mode` operativo
- “GIMO Mesh completo”

La lectura honesta del estado actual es:

| Modo | Estado real | Juicio |
|---|---|---|
| `inference` | operativo y ya validado en hardware | **Beta usable** |
| `utility` | base implementada pero valor todavía parcial | **Experimental / in progress** |
| `server` | integración avanzada, arranque real bloqueado por runtime embebido ausente | **No listo** |
| `hybrid` | composición cableada, pero depende de `server` y de más validación | **No listo** |

---

## 2. Qué está claramente hecho

### Backend Mesh

Está implementado el núcleo backend de Mesh:

- modelos y enums de mesh
- registry file-backed
- heartbeat
- thermal history
- capability gating
- router `/ops/mesh/*`
- feature flag `mesh_enabled`

Evidencia:

- `docs/DEV_MESH_PHASE1_REPORT.md`
- `tools/gimo_server/models/mesh.py`
- `tools/gimo_server/routers/ops/mesh_router.py`
- `tools/gimo_server/services/mesh/registry.py`

### Android app base

La app Android ya tiene:

- scaffold Compose y pantallas
- onboarding con selección de modo
- servicio foreground dueño del runtime del nodo
- inferencia local
- polling de tareas utility
- cableado de `server` / `hybrid` como modos válidos

Evidencia:

- `docs/GIMO_MESH.md`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/MeshAgentService.kt`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/ui/setup/SetupWizardScreen.kt`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/ControlPlaneRuntime.kt`

### Hardware protection

La protección térmica y de batería es una pieza real del sistema, no un TODO cosmético.

Evidencia:

- `docs/GIMO_MESH_INVARIANTS.md`
- `tools/gimo_mesh_agent/thermal.py`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/MeshAgentService.kt`

---

## 3. Estado por modo

### 3.1 Inference mode

#### Qué hace

El dispositivo:

- carga un modelo GGUF local
- arranca `llama-server`
- publica un endpoint OpenAI-compatible
- hace heartbeat al Core con `inference_endpoint`

#### Estado actual

**Es el modo más maduro de GIMO Mesh.**

La propia documentación activa lo declara validado en S10:

- `docs/GIMO_MESH.md`:
  - `Status: Production — Inference mode validated on Galaxy S10`
  - ejemplo de validación: `qwen2.5:3b` a `3.9 tok/s`

Además, el onboarding actual está claramente optimizado para inference:

- exige catálogo/modelo GGUF
- descarga el modelo desde el Core
- no requiere ADB en el flujo normal

Evidencia:

- `docs/GIMO_MESH.md`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/ui/setup/SetupWizardScreen.kt`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/ui/navigation/NavGraph.kt`

#### Juicio

**Beta usable.**

#### Qué falta antes de llamarlo “estable”

- más validación en hardware distinto al S10
- validación sostenida de thermal throttling bajo sesiones largas
- pruebas de routing real desde Core en escenarios mixtos
- criterios claros de release para modelos soportados

---

### 3.2 Utility mode

#### Qué hace

El dispositivo:

- no carga modelo
- no sirve inferencia
- no corre GIMO Core
- hace polling de tareas al backend
- ejecuta microtareas sandboxed

#### Capacidad actual observada

Tareas actuales en `TaskExecutor`:

- `ping`
- `text_validate`
- `text_transform`
- `json_validate`
- `shell_exec` con allowlist
- `file_read`
- `file_hash`

Evidencia:

- `docs/GIMO_MESH.md`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/TaskExecutor.kt`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/MeshAgentService.kt`

#### Estado actual

La base operativa existe:

- `deviceMode == "utility"` habilita utility
- hay loop de polling
- hay executor con sandbox
- hay submit de resultados

Pero la propia documentación activa aún lo trata como “in progress”:

- `docs/GIMO_MESH.md` → `Android utility mode | In progress`
- `docs/GIMO_MESH.md` → “Status: In development — task queue + executor”

#### Juicio

**Experimental / in progress.**

No porque no exista, sino porque todavía no está demostrado que aporte suficiente valor de producto frente a su complejidad operativa.

#### Qué falta

- más tipos de microtareas útiles
- métricas por `task_type`
- demostrar ahorro de trabajo real del host
- receipts y batching más ricos
- validación de throughput en uso real

---

### 3.3 Server mode

#### Qué intenta hacer

El teléfono pasa a ser host de GIMO Core:

- ejecuta backend local
- expone localhost para la app
- expone LAN para clientes remotos
- se registra como host real de mesh

#### Qué sí está hecho

La integración está bastante avanzada:

- `server` y `hybrid` existen en modo y UI
- hay `EmbeddedCoreRunner`
- `ShellEnvironment` ya contempla runtime embebido
- `MeshAgentService` ya intenta componer serve/inference/utility desde un solo owner
- el backend tiene bootstrap de host mesh

Evidencia:

- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/EmbeddedCoreRunner.kt`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/ShellEnvironment.kt`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/ControlPlaneRuntime.kt`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/MeshAgentService.kt`

#### Qué bloquea su operación real

Hoy el runtime embebido del Core no está realmente presente en assets:

- `apps/android/gimomesh/app/src/main/assets/runtime/gimo-core-runtime.json` → ausente

`ShellEnvironment` intenta leer precisamente ese manifest:

- si falta, `readRuntimeManifest()` devuelve `null`
- `prepareEmbeddedCoreRuntime()` no puede montar el runtime
- `EmbeddedCoreRunner.start()` marca el host como `UNAVAILABLE`

Evidencia directa del repo:

- `ShellEnvironment.kt`
- `EmbeddedCoreRunner.kt`
- comprobación local: el manifest no existe en `assets/runtime`

#### Juicio

**No listo.**

La parte de integración está muy avanzada, pero falta el requisito material que lo convierte en una capacidad operativa real.

La forma honesta de decirlo es:

> `server mode` está arquitectónicamente cableado y parcialmente implementado, pero no está todavía cerrado como capacidad operativa.

---

### 3.4 Hybrid mode

#### Qué intenta hacer

Combinar:

- `serve`
- `inference`
- y opcionalmente `utility`

#### Estado actual

La composición está definida en código:

- `isServeMode(settings)`
- `allowsInference(settings)`
- `allowsUtility(settings)`

y `hybrid` ya está en la configuración del usuario.

Evidencia:

- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/ControlPlaneRuntime.kt`
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/data/store/SettingsStore.kt`

Pero en la práctica depende de dos cosas:

1. que `server mode` funcione de verdad
2. que haya más validación de coexistencia runtime

#### Juicio

**No listo.**

No porque falte la idea, sino porque hereda el bloqueo operativo de `server mode`.

---

## 4. Qué se puede usar hoy

### Recomendación honesta de producto

Lo que sí puede anunciarse hoy:

- **GIMO Mesh beta**
- alcance real: **Android inference nodes**

Lo que no debería anunciarse todavía:

- “server mode listo”
- “hybrid listo”
- “utility listo como producto”

### Configuración recomendada hoy

- `mesh_enabled = true`
- Android en `deviceMode = "inference"`
- un modelo GGUF probado
- activación del mesh desde Dashboard

---

## 5. Guía de uso hoy

### 5.1 Flujo recomendado para inference beta

1. Arrancar GIMO Core principal en la LAN.
2. En la app Android, elegir `inference`.
3. Conectar al Core por QR o código manual.
4. Descargar un GGUF desde el catálogo del Core.
5. Completar onboarding.
6. Activar mesh desde Dashboard.
7. Confirmar heartbeat y `inference_endpoint`.

Evidencia de flujo:

- `docs/GIMO_MESH.md`
- `SetupWizardScreen.kt`
- `DashboardScreen.kt`

### 5.2 Provisioning por ADB

La app acepta configuración por intent extras:

- `config_core_url`
- `config_token`
- `config_device_mode`
- `auto_start_mesh`

Ver:

- `docs/GIMO_MESH.md` §11

### 5.3 Utility mode hoy

Puede activarse, pero debe entenderse como experimental:

- no requiere descarga GGUF
- depende del task polling
- su catálogo actual de tareas sigue siendo limitado

### 5.4 Server mode hoy

No debe recomendarse como flujo de usuario final aún.

Aunque la UI permita seleccionarlo, si el payload embebido del Core no está en la APK:

- el host runtime quedará `UNAVAILABLE`
- el backend local no levantará

---

## 6. Qué está operativo, qué está in progress y qué está bloqueado

### Operativo

- backend mesh base
- registry y heartbeat
- hardware protection
- inference mode Android
- onboarding inference
- BLE wake / ADB provisioning

### In progress

- utility mode como producto valioso, no solo como base técnica
- task queue / lifecycle más rica
- device capability profiling más completo

### Bloqueado o no cerrado

- server mode operativo en Android
- hybrid mode operativo
- packaging real del runtime embebido del Core

---

## 7. Qué falta por probar

### Inference

- más dispositivos
- sesiones largas
- comportamiento con throttling real sostenido
- escenarios con varios nodos

### Utility

- carga real útil
- costes de red vs ahorro de host
- receipts y observabilidad de task types

### Server / Hybrid

- arranque real del backend local en APK final
- readiness en hardware
- LAN access real desde clientes
- estabilidad del host runtime

---

## 8. Qué falta por hacer

### Para server mode

- empaquetar de verdad el runtime embebido del Core
- poblar `assets/runtime/gimo-core-runtime.json`
- incluir los archivos que ese manifest declare
- verificar arranque real de `uvicorn tools.gimo_server.main:app` en dispositivo

### Para utility mode

- ampliar catálogo de microtareas deterministas
- receipts más ricos
- batching controlado
- medir valor real

### Para hybrid

- validar convivencia de serve + inference
- definir límites térmicos y de memoria más realistas

---

## 9. Merge / release guidance

### Mi lectura de release hoy

Sí:

- merge como **beta de inference**

No:

- release como “GIMO Mesh completo”

### Forma correcta de comunicarlo

> GIMO Mesh está listo para pruebas beta en `inference mode` sobre Android.  
> `utility mode` sigue experimental.  
> `server mode` y `hybrid mode` están integrados en código pero no cerrados como capacidad operativa.

---

## 10. Conclusión

GIMO Mesh no está “verde” ni está “terminado”.

Está en un punto bastante claro:

- ya existe una base seria
- `inference mode` ya es una beta defendible
- `utility mode` tiene potencial pero aún no ha demostrado todo su valor
- `server` y `hybrid` todavía no deben venderse como listos

La forma más honesta de sostenerlo hoy es:

> **GIMO Mesh = inference beta real + utility experimental + server/hybrid aún no cerrados.**

