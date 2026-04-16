# E2E Engineering Plan — GIMO Mesh Server Mode (Full) — REV 2

**Fecha**: 2026-04-15
**Estado**: APROBADO — en implementación (Fase 4)
**Revisión**: rev 2 (integra 3 mejoras ancladas en investigación SOTA; Cambio 12 retirado por duplicación con `local_allow_task_execution` existente)
**Ámbito**: Cierre operativo de `DeviceMode.server` en GIMO Mesh — mismo Core en todos los hosts
**Ronda**: seguimiento de `E2E_AUDIT_LOG_20260415_PHASE0_MESH_COLLATERAL.md` (Fase 0) — los 2 hallazgos DESCONECTADO (D-1, D-2) ya están cerrados en la rama `feature/gimo-mesh`
**Plan hermano**: `E2E_ENGINEERING_PLAN_20260415_SERVER_MODE_RUNTIMES.md` (runtime selector `kotlin_only / llama_cpp / embedded_core`) — este plan lo complementa, no lo sustituye

## Changelog rev 2

Tras investigación SOTA (Off Grid, Cactus, exo, Prima.cpp, TAPAS ASPLOS 2025, Federate the Router, GAR, ICL-Router, llm-d, Istio AI multicluster) se añaden 3 mejoras al plan original y se retira un cambio redundante:

- **Refinamiento Cambio 2**: penalty dinámico battery/thermal-aware en lugar de fijo `-20`. Ancla: TAPAS (thermal + **power** aware scheduling para LLM).
- **Cambio nuevo 10**: client-side mDNS auto-discovery con verificación HMAC en `gimo.cmd`. Ancla: Off Grid (auto-scan LAN) + inexistente combinación con HMAC auth.
- **Cambio nuevo 11**: health/mode/load en TXT record mDNS. Ancla: **white space**, nadie lo hace en el espacio mesh consumer.
- **Retirado Cambio 12**: campo `serves_only` — duplicado con `local_allow_task_execution` existente en [models/mesh.py:97](tools/gimo_server/models/mesh.py:97). El sistema ya resuelve automáticamente vía enrollment capabilities + heartbeat real-time + `can_execute()` + dispatch filters.
**Inputs leídos**:
- `docs/DEV_MESH_ARCHITECTURE.md §0–§2`
- `tools/gimo_server/main.py:470–530` (lifespan, bootstrap, mDNS gate)
- `tools/gimo_server/services/mesh/host_bootstrap.py` (env vars → `MeshDeviceInfo`)
- `tools/gimo_server/services/mesh/mdns_advertiser.py` (opt-in `_gimo._tcp.local.`)
- `tools/gimo_server/services/mesh/model_recommendation.py` (server-mode threshold, ya emite `server`)
- `tools/gimo_server/services/mesh/dispatch.py` (pipeline de scoring, ya emite span)
- `tools/gimo_server/services/mesh/registry.py` (enrollment, state, thermal, ahora con bridge `_mesh_obs`)
- `apps/android/gimomesh/.../service/EmbeddedCoreRunner.kt` (bind `0.0.0.0`, env vars)
- `apps/android/gimomesh/.../service/MeshAgentService.kt` (foreground service, heartbeat 30s, poll 5s)
- memoria proyecto: `project_dev_mesh_experiment.md`, `project_surface_unification.md`, `project_dual_surface_vision.md`

---

## 1. Resumen de diagnóstico

El usuario planteó una invariante dura que reordena el plan:

> *"La idea es que GIMO Core sea el mismo aquí y en Pekín. En un Android, un Mac, un Linux o en un Windows. Debe ser la misma superficie. Después, si es necesario hacer correcciones para que funcione bien en el sistema donde está, se pueden crear adaptadores que van por fuera de GIMO Core, pero la esencia del sistema debe ser la misma en todos sitios."*

Esto es compatible con `project_surface_unification.md` y `project_dual_surface_vision.md` y define el contrato del plan: **un solo Core Python**, **adaptadores platform-specific viven fuera** (`apps/android/`, futuros `apps/macos/`, `apps/windows/`, etc.), y esos adaptadores **no reimplementan lógica de mesh** — solo lanzan Core con la configuración adecuada y lo mantienen vivo.

### Qué ya existe (evidencia inline)

| Pieza | Archivo | Estado |
|---|---|---|
| `DeviceMode.server` canónico en enum | `tools/gimo_server/models/mesh.py` | ✅ |
| Bootstrap por env vars (`GIMO_MESH_HOST_*`) | `services/mesh/host_bootstrap.py:34-63` | ✅ cualquier launcher (Android, script, systemd) puede activarlo |
| mDNS advertiser `_gimo._tcp.local.` con HMAC | `services/mesh/mdns_advertiser.py` | ✅ pero gated detrás de `ORCH_MDNS_ENABLED=true` (default off) — no se auto-activa por modo server |
| Uvicorn bind a `0.0.0.0` en Android | `EmbeddedCoreRunner.kt:86` | ✅ acepta tráfico LAN |
| Foreground service con heartbeat/poll | `MeshAgentService.kt` | ✅ mantiene Core vivo en Android |
| Dashboard de observability recibe spans de mesh | `services/mesh/observability.py` (D-2 fix) | ✅ recién cerrado |
| `ModelRecommendationEngine` emite `server` | `services/mesh/model_recommendation.py:289-306` (D-1 fix) | ✅ recién cerrado |
| UI mesh en `/ops/mesh/*` (HTTP) | routers existentes | ✅ misma superficie en todos los hosts — la UI la consume cualquier browser de la LAN |

### Qué falta para que server mode sea realmente usable (5 huecos)

1. **mDNS no se auto-activa en modo server**. Un dispositivo con `GIMO_MESH_HOST_DEVICE_MODE=server` debería anunciarse en la LAN automáticamente; hoy requiere que el launcher exponga además `ORCH_MDNS_ENABLED=true`. Acoplamiento frágil: dos palancas para una sola intención.
2. **Uvicorn CLI bindea a `127.0.0.1` por default**. El Android pasa `--host 0.0.0.0` explícito, pero un launcher de desktop (macOS/Linux/Windows) que arranque `python -m tools.gimo_server.main` queda invisible para la mesh. No hay una sola palanca que diga "soy server, acepta LAN".
3. **No hay admin UI accesible desde el propio phone-host**. El notification del foreground service no lleva a ningún sitio. Para aprobar enrollments pendientes hay que conectarse desde otra máquina — aceptable si es política, pero hoy no está decidido ni documentado.
4. **Dispatch no prefiere peers sobre el host en modo server**. Cuando el device server ejecuta GIMO Core + acepta tareas, consume CPU/RAM propia para ambos roles. La lógica en `dispatch._score_devices()` no distingue "este device ES el host" — puede autoseleccionarse como inference target bajo carga y throttearse. Debería preferir peers si existen eligibles.
5. **No hay procedimiento E2E documentado para S10**. El S10 (Exynos 9820, 6–8 GB) no supera el auto-umbral de server mode (≥12 GB + base_tps≥18) — hay que forzarlo manualmente. El usuario quiere probarlo, y no existe un runbook que describa los pasos exactos.

Estos 5 huecos son el scope. Nada más es "server mode" en estricto sentido. El **runtime selector** (Kotlin-only vs llama.cpp vs embedded-core) es un problema distinto y su propio plan.

---

## 2. Principios de diseño

Derivados del mensaje del usuario + `AGENTS.md` + memoria:

1. **Core único, superficie idéntica** (*usuario 2026-04-15*): la misma `tools/gimo_server/` corre en Android, macOS, Linux, Windows y un server en Pekín. No introducimos código platform-specific dentro de `tools/gimo_server/`. Si hay variación de plataforma, vive en `apps/<platform>/`.
2. **Adaptadores fuera del Core**: Android es un adapter (`apps/android/gimomesh/`); futuros shells desktop son adapters. Su única responsabilidad es: (a) lanzar Core con env vars, (b) mantenerlo vivo, (c) exponer una forma de abrir la UI que Core ya sirve.
3. **Una palanca por intención** (`AGENTS.md` *Plan Quality Standard §9*): declarar `device_mode=server` debe disparar todo lo que implica server mode — LAN bind, mDNS, registro, role-aware dispatch — sin que el operador tenga que cablear 4 variables correlacionadas.
4. **Web UI es la admin surface** (`project_dual_surface_vision.md`): no reimplementamos "aprobar device" en Kotlin. Core ya sirve `/ops/mesh/*` desde FastAPI; cualquier browser de la LAN (incluido el del propio phone) entra ahí con el token.
5. **Mesh-off invariant** (`project_dev_mesh_experiment.md`): nada de esto puede requerir `mesh_enabled=True` para que Core arranque. El test `test_boot_mesh_disabled` sigue siendo gate.
6. **Hardware protection no-bypassable** (`DEV_MESH_ARCHITECTURE.md §5`): las heurísticas de dispatch se tocan, pero thermal lockout y `can_execute()` siguen siendo ley.
7. **Observability honesty** (`AGENTS.md`): cualquier cambio de routing emite span via `_mesh_obs.emit_dispatch(...)` — el dashboard debe ver la preferencia peers→host.

---

## 3. Lista de cambios

Agrupado en **Backend (Core — igual en todas las plataformas)**, **Android adapter**, **Desktop adapter (documentación + script)**, **Tests**, **Docs/Runbook**.

### Backend / Core (autoritativo)

#### Cambio 1: `device_mode=server` auto-habilita mDNS y bind LAN

- **Soluciona**: huecos #1, #2
- **Qué**: cuando `AndroidHostBootstrapConfig.device_mode == DeviceMode.server`, `main.py` activa mDNS aunque `ORCH_MDNS_ENABLED` no esté seteado, y emite warning si detecta que el bind está en `127.0.0.1` (que indicaría un launcher mal configurado). Para el caso CLI, añadir un flag `--role server` que cambie el default de host a `0.0.0.0`.
- **Dónde**:
  - `tools/gimo_server/main.py:491` — condición: `ORCH_MDNS_ENABLED=true` **O** `app.state.mesh_host_device.device_mode == DeviceMode.server`.
  - `tools/gimo_server/main.py:~885` (entry CLI) — flag `--role {client|server}`; `server` ⇒ host default `0.0.0.0`.
- **Por qué este diseño**: la intención "este host es server" vive en una sola variable (`GIMO_MESH_HOST_DEVICE_MODE=server` o `--role server`). No hay que coordinar 3 envs independientes. No rompe el path de Android (ya pasa `--host 0.0.0.0` explícito y set `GIMO_MESH_HOST_*`). No afecta hosts client (default sigue `127.0.0.1`).
- **Riesgo**: **medio**. Cambiar el bind default es un cambio de seguridad — un usuario que pasa `--role server` sin saber lo que implica expone la API a la LAN. Mitigación: el token Bearer sigue siendo obligatorio; log WARN visible al arranque ("GIMO Core bound to 0.0.0.0 — LAN mesh mode active"); doc explícito en runbook.
- **Verificación**:
  - Unit: `test_mdns_auto_enables_for_server_mode` — monkeypatch bootstrap para devolver un device con `device_mode=server`, verificar que `app.state.mdns_advertiser.is_running` es True sin setear `ORCH_MDNS_ENABLED`.
  - Unit: `test_server_role_flag_binds_lan` — invocar el parser de flags con `--role server`, verificar que `host == "0.0.0.0"`.
  - Smoke: boot con `--role server`, `curl http://<lan-ip>:9325/healthz` desde otro host.

#### Cambio 2 (REV 2): Dispatch prefiere peers cuando el host corre en server mode — penalty dinámico

- **Soluciona**: hueco #4
- **Ancla SOTA rev 2**: TAPAS (ASPLOS 2025) — scheduling thermal + **power** aware. GIMO aplica el principio a consumer mesh.
- **Qué**: `DispatchService._score_devices()` penaliza al host server con penalty **dinámico** que modula por battery y thermal:
  - Baseline: `-10` al host
  - `battery_percent < 30 && !battery_charging` → extra `-20` (total `-30`): evita suicidio de batería en phone server
  - `cpu_temp < 50 && ram_percent < 60` → reduce a `-5`: host con headroom real merece menos penalty
  - `thermal_throttled` → ya lo filtra `_filter_thermal_headroom` arriba (no duplicamos)
- **Dónde**: `tools/gimo_server/services/mesh/dispatch.py` — inyectar `host_device_id: Optional[str]` al constructor; aplicar penalty en `_score_devices`.
- **Por qué este diseño**: preferencia blanda, no hard filter. El SOTA (TAPAS) valida que power-awareness es clave en scheduling sostenido; en consumer mesh con phones, battery es el equivalente. Reutiliza el scoring existente, no introduce capa nueva.
- **Riesgo**: **bajo**. Monotónico — el host sigue seleccionable si es el único eligible. Penalty refinable sin cambiar diseño.
- **Verificación**:
  - Unit: `test_dispatch_deprefers_server_host_when_peers_available`
  - Unit: `test_dispatch_penalty_increases_on_low_battery`
  - Unit: `test_dispatch_penalty_reduces_on_high_headroom`
  - Unit: `test_dispatch_observability_span_reflects_peer_preference`

#### Cambio 3: Endpoint `GET /ops/mesh/host` — "¿quién soy yo?"

- **Soluciona**: hueco #3 parcial (admin UI necesita saber el rol local)
- **Qué**: endpoint que devuelve el `MeshDeviceInfo` del host (si existe) — `device_id`, `device_mode`, `lan_urls: list[str]` (URLs útiles para imprimir en la UI/notification).
- **Dónde**: nuevo handler en `tools/gimo_server/routers/ops/mesh_router.py` (o el router de mesh existente). Auth-protected como el resto de `/ops/mesh/*`.
- **Por qué este diseño**: elimina la necesidad de que Android duplique la decisión "¿soy server?" — la pregunta se contesta en Core. La UI web pinta un banner "This host is serving mesh at http://192.168.x.y:9325". La notification de Android llama este endpoint para pintar la URL LAN.
- **Riesgo**: **muy bajo**. Read-only, no muta estado.
- **Verificación**:
  - Unit: `test_host_endpoint_returns_none_when_not_bootstrapped` (401/200 con payload null según política) + `test_host_endpoint_returns_server_info_when_bootstrapped`.
  - Integración: con bootstrap env vars, `GET /ops/mesh/host` responde `{device_mode: "server", lan_urls: [...]}`.

### Android adapter (fuera de Core)

#### Cambio 4: Settings toggle "Server mode" con UX honesta

- **Soluciona**: hueco #5 parcial (operador necesita forzar server en S10)
- **Qué**: en `SettingsScreen.kt`, añadir un switch "Serve GIMO Core to the LAN (server mode)". Al activarlo, se setea `settings.deviceMode = server` y el `MeshAgentService` reinicia Core con `GIMO_MESH_HOST_DEVICE_MODE=server`. Texto de ayuda que explique: "requires charged + cool device, battery will drain ~X%/h".
- **Dónde**:
  - `apps/android/gimomesh/.../ui/screen/SettingsScreen.kt`
  - `apps/android/gimomesh/.../service/ControlPlaneRuntime.kt` (ya existe `isServeMode()`, solo hay que cablear el toggle)
  - `apps/android/gimomesh/.../service/EmbeddedCoreRunner.kt` (ya acepta el env var, no cambia)
- **Por qué este diseño**: **el adapter no reimplementa lógica de mesh** — solo setea la env var que Core lee. Ningún cambio en rutas, dispatch, o mDNS en Kotlin.
- **Riesgo**: **bajo**. Es UI + un switch conectado a estado persistido que ya existe.
- **Verificación**: test Compose unit + manual smoke en S10.

#### Cambio 5: Notification lleva a la UI web servida por Core

- **Soluciona**: hueco #3
- **Qué**: la notification persistente del foreground service muestra la LAN URL (obtenida de `GET /ops/mesh/host`). Tap abre el browser del phone apuntando a `http://localhost:9325/ops/mesh` con token autoinyectado via deep link.
- **Dónde**: `apps/android/gimomesh/.../service/MeshAgentService.kt` — el notification builder.
- **Por qué este diseño**: respeta "Web UI is the admin surface" — cero Kotlin screens duplicando aprobación de devices. El phone se trata como un host cualquiera de la mesh, su UI es la misma que un laptop vería.
- **Riesgo**: **bajo**. La UI web ya existe y funciona en browser móvil.
- **Verificación**: manual — tap en notification abre browser, se ve la página de mesh admin con token válido.

### Desktop adapter (macOS / Linux / Windows) — este plan solo documenta, no implementa

#### Cambio 6: Runbook de launcher server mode en desktop

- **Soluciona**: valida la invariante "mismo Core en todos lados" sin escribir apps nativas todavía
- **Qué**: sección nueva en `docs/DEV_MESH_ARCHITECTURE.md` o nuevo `docs/MESH_SERVER_RUNBOOK.md` que describe cómo arrancar Core como server en Linux/macOS/Windows con un comando simple:
  ```bash
  python -m tools.gimo_server.main --role server \
    --mesh-host-id my-laptop \
    --mesh-host-class desktop
  ```
- **Dónde**: doc nueva + sección "Adapters" explicando que Android empaqueta esto en una app pero el Core es idéntico.
- **Por qué este diseño**: valida que no hay código Android-específico en Core. Si un usuario en Pekín puede arrancar un server con una línea Python, hemos probado la invariante.
- **Riesgo**: **cero**. Solo documentación.
- **Verificación**: un dev en Linux ejecuta el comando del runbook, el server aparece en mDNS, otro host lo ve.

### Tests

#### Cambio 7: Test de integración LAN bind + mDNS auto-enable

- **Qué**: `tests/integration/test_server_mode_boot.py` — arranca Core con `GIMO_MESH_HOST_DEVICE_MODE=server` en un worker, verifica (a) bind en `0.0.0.0`, (b) `mdns_advertiser.is_running`, (c) `GET /ops/mesh/host` devuelve `device_mode=server`.
- **Dónde**: `tests/integration/`.
- **Riesgo**: requiere fixture que lance subproceso — seguir el patrón de `test_mesh_e2e.py`.

#### Cambio 8: Test de smoke "server-disabled no regresiona"

- **Qué**: `test_boot_mesh_disabled.py` ya existe. Extenderlo con aserción: sin `--role server` y sin `GIMO_MESH_HOST_*`, el bind es `127.0.0.1` y mDNS es inactivo.
- **Riesgo**: nulo.

### Cambios nuevos rev 2 (SOTA-anclados)

#### Cambio 10: Client-side mDNS auto-discovery con verificación HMAC

- **Soluciona**: fricción de enrollment manual; hoy server anuncia pero nadie escanea
- **Ancla SOTA rev 2**: Off Grid hace auto-scan LAN pero sin HMAC auth. GIMO combina discovery + integridad firmada — **inexistente** en el espacio.
- **Qué**: nuevo comando `gimo discover` (o flag `--discover` en arranque client) que escanea `_gimo._tcp.local.` durante 2s, verifica el HMAC del TXT record contra `ORCH_TOKEN` (o token compartido), y muestra hosts saludables ofreciéndose a enrollarse:
  ```
  Found GIMO mesh:
    gimo-laptop.local (192.168.1.10:9325) — health 87%, mode=server, load 0.3
  Enroll this device as worker? [y/N]
  ```
- **Dónde**:
  - `tools/gimo_server/services/mesh/mdns_discovery.py` — nuevo módulo (client-side Zeroconf listener + HMAC verify)
  - `gimo.py` — subcomando `discover`
- **Por qué este diseño**: feature client-side aditiva, no toca server. Reusa `zeroconf` ya presente + `hmac_signer` ya presente.
- **Riesgo**: **bajo**. Opt-in; si `zeroconf` no está instalado degrada a mensaje informativo. Sin HMAC válido muestra el host marcado como "unverified".
- **Verificación**:
  - Unit: `test_mdns_discovery_parses_txt_record` — mock Zeroconf ServiceInfo, verificar extracción de health/mode/load
  - Unit: `test_mdns_discovery_rejects_invalid_hmac` — TXT record con HMAC roto → marcado unverified
  - Integración manual: arrancar server + client en misma LAN → client descubre server

#### Cambio 11: Health / mode / load en TXT record mDNS

- **Soluciona**: discovery sin signal — clients no saben si el host está saludable antes de enrollarse
- **Ancla SOTA rev 2**: **white space**. exo no hace consumer discovery, Prima.cpp tampoco, Off Grid detecta presencia pero no salud. Nadie publica signals de routing en service discovery.
- **Qué**: extender `MdnsAdvertiser._build_properties` (o equivalente) para incluir en TXT record:
  - `health=<0-100>` — health_score del host (computado desde `app.state.mesh_host_device` + `TelemetryService`)
  - `mode=<inference|utility|server|hybrid>` — device_mode actual
  - `load=<0.0-1.0>` — utilización normalizada (max de cpu_percent, ram_percent) / 100
  - Refresh cada 60s vía `update_service` de Zeroconf cuando cambie significativamente
- **Dónde**: `tools/gimo_server/services/mesh/mdns_advertiser.py` — nuevos properties + timer de refresh.
- **Por qué este diseño**: los properties ya están firmados con HMAC; añadir campos no reduce seguridad. Convierte service discovery de "existe" a "existe y está sano AHORA".
- **Riesgo**: **muy bajo**. Si el host no tiene TelemetryService aún inicializado, campos usan defaults (health=100, load=0).
- **Verificación**:
  - Unit: `test_mdns_txt_record_includes_health_mode_load`
  - Unit: `test_mdns_refresh_updates_txt_when_load_changes`

### Docs

#### Cambio 9: `docs/audits/E2E_S10_SERVER_MODE_RUNBOOK_20260415.md`

- **Qué**: procedimiento E2E para el S10, reconociendo que el S10 NO cumple el auto-umbral — hay que forzar server manualmente. Pasos:
  1. Ajustar settings del agente Android: toggle "Server mode" ON.
  2. Verificar notification muestra LAN URL `http://192.168.x.y:9325`.
  3. Desde laptop, abrir browser → entrar a la URL con token → ver dashboard de mesh.
  4. Desde laptop, enrollar un segundo device (el propio laptop via `gimo.cmd`) contra el S10.
  5. Approvar desde la web UI del S10 (laptop browser apuntando a S10).
  6. Dispatch una task trivial; verificar via `/ops/observability` que el span `dispatch` prefiere el laptop sobre el S10 (Cambio 2).
  7. Caveats S10: 6–8 GB RAM limita inferencia concurrente — mantener `model_loaded=""` en el S10 server o usar modelo Q4 ≤1 GB.
- **Dónde**: `docs/audits/`.
- **Riesgo**: nulo (doc).

---

## 4. Orden de ejecución (REV 2)

1. **Cambio 1 + 11** (mDNS auto-enable + health/mode/load en TXT) — ambos tocan `mdns_advertiser.py` y `main.py` lifespan; juntarlos evita tocar esos archivos dos veces.
2. **Cambio 3** (endpoint `/ops/mesh/host`) — lo necesita la notification de Android, la UI web y el runbook.
3. **Cambio 2 refinado** (dispatch penalty dinámico battery/thermal) — aislado, sin dependencias nuevas.
4. **Cambio 7** (test integración server mode boot).
5. **Cambio 8** (test smoke mesh-disabled ampliado).
6. **Cambio 4** (Settings toggle Android).
7. **Cambio 5** (Notification deep link a UI web).
8. **Cambio 10** (client mDNS auto-discovery) — feature CLI, se encaja tras tener los TXT records enriquecidos.
9. **Cambio 6** (runbook desktop launcher).
10. **Cambio 9** (runbook E2E S10).

Backend primero (1–3, 7–8, 10), Android en medio (4–5), docs al final (6, 9). Orden elegido para que tras los pasos 1–5 ya sea posible E2E en S10 aunque los runbooks queden por redactar.

---

## 5. Unification check

| Superficie | Cómo converge |
|---|---|
| MCP bridge (Claude Code, etc.) | Llama los mismos `/ops/mesh/*` — sin cambios necesarios. |
| CLI (`gimo.cmd`, `gimo.py`) | `--role server` añade el flag; el resto de comandos no cambia. Mantiene paridad con env var `GIMO_MESH_HOST_DEVICE_MODE`. |
| HTTP directo | Endpoint nuevo `/ops/mesh/host` visible desde cualquier cliente con token. |
| Web UI (`/ops/mesh`) | Consumidor principal de `/ops/mesh/host` — muestra banner "this host is serving mesh at …". |
| Android app | Reducido a launcher + notification; **cero reimplementación de lógica mesh en Kotlin**. |
| Futuros desktop adapters | Reusan `--role server`; un script bash/ps1/plist invoca Core idéntico. |

No hay "server mode para Android" distinto de "server mode para Linux". Es el mismo Core con la misma palanca.

---

## 6. Verification strategy

| Nivel | Check | Cuándo |
|---|---|---|
| Unit | `test_mdns_auto_enables_for_server_mode`, `test_server_role_flag_binds_lan`, `test_dispatch_deprefers_server_host_when_peers_available`, `test_host_endpoint_*` | Tras cada cambio backend relevante |
| Integración | `test_server_mode_boot.py` — subprocess + `curl` | Tras Cambios 1+3 |
| Regresión | `test_boot_mesh_disabled` ampliado | Tras Cambio 1 |
| Smoke runtime | `python -m tools.gimo_server.main --role server` en linux local → `curl http://<lan>:9325/healthz` desde otro host | Tras Cambio 1 |
| E2E S10 | Runbook §4 completo | Tras Cambios 4–5 |
| Observability | Dashboard `/ops/observability` debe mostrar `kind=mesh, name=dispatch` con `device_id` del peer, no del host | Durante E2E |

---

## 7. Compliance matrix (Phase 3 quality gate)

| Gate | Respuesta | Justificación |
|---|---|---|
| Aligned (AGENTS/SYSTEM/CLIENT_SURFACES/SECURITY) | YES | Core único, superficie igual, adapters fuera — match con `project_surface_unification.md` |
| Honest (claim vs enforcement) | YES | "Server mode" se enforcea con bind LAN + mDNS real + endpoint consultable, no solo un flag cosmético |
| Potent (ataca cluster, no síntoma) | YES | 5 huecos reales detectados, los 5 cubiertos por 9 cambios mínimos |
| Minimal (no hay diseño más simple ignorado) | YES | Considerada la alternativa "todo en Kotlin en Android" y rechazada por violar la invariante del usuario |
| Unified (todas las superficies convergen) | YES | ver §5 |
| Verifiable (cada cambio tiene proof path) | YES | ver §6 |
| Operational (arranque, smoke, stale state) | YES | runbook explícito, test de mesh-disabled protegido |
| Durable (el diseño merece quedarse) | YES | Ningún cambio es un hack; todos viven en capas canónicas (`main.py` lifespan, `dispatch.py` scoring, `mesh_router.py` endpoint, Android settings) |

---

## 8. Residual risks

1. **Exponer `0.0.0.0` por accidente**: un usuario pasa `--role server` sin entender que abre la API al LAN. Mitigación: WARN log visible, doc explícito en runbook, token obligatorio sigue siendo la capa de seguridad.
2. **S10 se throttlea corriendo Core + inferencia**: el propio motivo por el que el auto-umbral exige 12 GB. Mitigación: la de-preference de dispatch (Cambio 2) descarga tareas a peers; hardware protection (thermal lockout) sigue activo.
3. **Deep link Android → browser con token**: inyectar el token por query string puede filtrarlo a logs del browser. Mitigación: doc + usar `localhost` donde sea posible; evaluar cookie de sesión en iteración siguiente.
4. **mDNS en redes corporativas/WiFi guest**: muchos APs bloquean multicast. Mitigación: runbook incluye "si mDNS no funciona, usar IP LAN directa"; no es un regresor — hoy ni siquiera lo intentamos.
5. **Dispatch penalty fija `-20` puede ser agresiva**: es un número elegido a dedo. Mitigación: unit test valida que host sigue seleccionable si es el único eligible; el número vive en una constante y se puede tunear sin cambiar diseño.

---

## 9. Out of scope (explícito)

- **Runtime selector** (`kotlin_only / llama_cpp / embedded_core`) — cubierto por `E2E_ENGINEERING_PLAN_20260415_SERVER_MODE_RUNTIMES.md`.
- **Adapters reales para macOS/Windows/Linux** (empaquetado `.app`, `.msi`, systemd unit) — este plan solo produce documentación de cómo se arrancarían; el empaquetado es trabajo futuro.
- **Federación multi-LAN / Pekín**: mDNS cubre LAN; wireguard/tailscale/VPN queda fuera.
- **Auth hardening**: el plan mantiene el contrato token Bearer actual; rotación/OAuth/mTLS es otro scope.

---

## ✋ Pausa obligatoria

Per `/e2e` skill §"Mandatory pause": este plan debe recibir aprobación explícita antes de entrar en Fase 4.

**Pregunta al usuario**: ¿apruebas este plan y el orden de ejecución, o quieres ajustar scope (quitar/añadir cambios), recalibrar riesgos, o tunear umbrales (por ejemplo el penalty `-20` del Cambio 2) antes de implementar?
