# GIMO Mesh — E2E Validation Findings (2026-04-19)

**Contexto**: Prueba E2E con Galaxy S10 (SM-G973F, Android 12) y Core en `192.168.0.213:9325` tras merge `feature/mesh-merge-and-audit-remediation → main` (HEAD `899f824`).

Se registran problemas **por orden de aparición**. Cada uno incluye: síntoma, evidencia, impacto, fix sugerido.

---

## F-01 — `mesh_enabled` requiere PUT completo de `/ops/config`, no hay toggle dedicado

**Síntoma**: Para activar el mesh hay que descargar `/ops/config`, modificar un campo y hacer PUT con el JSON completo (1.2 KB). No existe `POST /ops/mesh/enable` ni toggle UI en la web UI ni en la app Android.

**Evidencia**:
```
curl -X POST /ops/mesh/onboard/code → {"detail":"Mesh is disabled"}
curl -X POST /ops/config            → 405 Method Not Allowed
curl -X PUT  /ops/config --data @full-config.json → 200 (sólo así funciona)
```

**Impacto**: UX rota para operador. Riesgo de race conditions si dos admins editan config a la vez.

**Fix**: añadir `POST /ops/mesh/enable` y `POST /ops/mesh/disable` (admin-only) con audit log, o bien PATCH parcial en `/ops/config`.

---

## F-02 — `/ops/mesh/status` responde con `mesh_enabled=false` (doc dice 404)

**Síntoma**: `docs/GIMO_MESH.md §8.1` afirma: *"All require operator or admin auth. Return 404 when mesh_enabled = false."* Pero `GET /ops/mesh/status` devuelve 200 con el payload completo aun con mesh deshabilitado.

**Evidencia**:
```
mesh_enabled: false
GET /ops/mesh/status → 200 {"mesh_enabled":false,"device_count":22,...}
POST /ops/mesh/onboard/code → 400 {"detail":"Mesh is disabled"}
```

**Impacto**: Inconsistencia contrato↔doc. Puede filtrar inventario de devices cuando mesh debería estar cerrado.

**Fix**: decidir política (todos 404, o exponer solo status). Actualizar doc o router.

---

## F-03 — Credenciales fragmentadas: `.env` vs `.gimo_credentials` desincronizados

**Síntoma**: El servidor está usando `ORCH_TOKEN` de `.env` (`yqdhQb_...` role admin). Pero `tools/gimo_server/.gimo_credentials` tiene otro token admin (`K07aBtIW...`) que el servidor rechaza como `Invalid token`.

**Evidencia**:
```
.env → ORCH_TOKEN=yqdhQb_...  → auth/check → admin ✅
.gimo_credentials → admin: K07a... → auth/check → Invalid token ❌
```

**Impacto**: Confusión operativa. La doc de memory dice `.orch_token` es el canónico, pero hay 3 archivos distintos con tokens distintos.

**Fix**: definir un ÚNICO source of truth. Si es `.gimo_credentials`, migrar `ORCH_TOKEN` del `.env` o que el loader las reconcilie al arrancar.

---

## F-04 — `/ops/mesh/host` devuelve `device: null, lan_urls: [], mdns_active: false`

**Síntoma**: El endpoint que debería permitir auto-discovery al device devuelve vacío, aunque el propio `onboard/code` sí genera un `qr_payload` con la URL correcta (`http://192.168.0.213:9325/...`).

**Evidencia**:
```
GET /ops/mesh/host → {"device":null,"lan_urls":[],"mdns_active":false,"advertised_signals":{}}
POST /ops/mesh/onboard/code → qr_payload contiene http://192.168.0.213:9325/...
```

**Impacto**: El wizard "Locate the Core" en la app muestra un placeholder hardcoded `http://192.168.0.49:9325` que casi nunca coincide con la IP real. Sin mDNS el usuario tiene que teclear la IP manual.

**Fix**: `/ops/mesh/host` debe leer IPs de interfaces activas y devolver al menos una `lan_url`. `mdns_active=false` indica que el advertiser no arranca — revisar ciclo de vida en `mdns_advertiser.py`.

---

## F-05 — IP placeholder del wizard (`192.168.0.49:9325`) es hardcoded y desactualizado

**Síntoma**: En "Locate the Core" el campo trae por defecto `http://192.168.0.49:9325`. Esa IP no corresponde al PC host actual (`192.168.0.213`). No hay auto-detección ni pre-fill desde el QR scan.

**Evidencia**: screenshot wizard paso 2 (INFERENCE → Connect). Doc `GIMO_MESH.md §12` registra `coreUrl` default = `http://192.168.0.49:9325`.

**Impacto**: UX friccional. Usuario medio tiene que descubrir la IP del PC y teclearla en el móvil.

**Fix**: (a) eliminar default hardcoded, usar placeholder informativo; (b) pre-rellenar desde el `qr_payload` cuando entra por SCAN QR; (c) implementar mDNS discovery real en la app.

---

## F-06 — Legado acumulado: 22 devices registrados, 2 "connected" de runs previas

**Síntoma**: Tras habilitar mesh aparece `device_count: 22, devices_connected: 2` aunque el S10 aún no ha hecho enrollment en esta sesión.

**Evidencia**:
```
GET /ops/mesh/status → {"device_count":22,"devices_by_mode":{"hybrid":1,"server":3,"inference":18},"devices_connected":2}
```

**Impacto**: Ruido en dashboards. Tests previos no limpian `.orch_data/ops/mesh/devices/`.

**Fix**: comando CLI `gimo mesh prune --stale-days 7` o auto-prune devices que no hayan emitido heartbeat en N días.

---

## F-07 — Dualidad endpoints `/enrollment/*` vs `/onboard/*` — doc desalineada

**Síntoma**: `docs/GIMO_MESH.md §8.2` documenta `POST /ops/mesh/enrollment/token` como flow oficial, pero la app Android usa `/ops/mesh/onboard/code` (comprobado por `qr_payload`). Ambos caminos existen en OpenAPI.

**Evidencia**: OpenAPI lista los dos conjuntos:
- `/ops/mesh/enrollment/token`, `/ops/mesh/enrollment/tokens`, `/ops/mesh/enrollment/claim` (4 endpoints)
- `/ops/mesh/onboard/code`, `/ops/mesh/onboard/redeem`, `/ops/mesh/onboard/discover`, etc. (6 endpoints)

**Impacto**: Doc caduca, superficie duplicada. Un integrador nuevo no sabe cuál usar.

**Fix**: si `/enrollment/*` es legado, marcarlo deprecated (header `Deprecation: true`) y migrar doc a `/onboard/*`. Si ambos son válidos, documentar la diferencia.

---

## F-08 — 🚨 SHOW-STOPPER: Core bind a `127.0.0.1`, inalcanzable desde LAN

**Síntoma**: El S10 (192.168.0.244) hace CONNECT al wizard con `http://192.168.0.213:9325` → **timeout 10s** `"failed to connect to /192.168.0.213 (port 9325) from /192.168.0.244 (port 51024) after 10000ms"`.

**Root cause**: `scripts/dev/up.cmd:127` lanza:
```
uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325 --reload
```
`netstat -an | grep :9325` confirma: `TCP 127.0.0.1:9325 LISTENING` (solo loopback).

**Impacto**: **GIMO Mesh es inoperable en dev con el launcher por defecto**. Ningún device externo puede conectar. El "zero-ADB setup" queda como feature muerta. Auto-discovery mDNS, aunque se activara, publicaría un socket loopback inalcanzable.

**Fix**:
1. Cambiar `up.cmd:127` a `--host 0.0.0.0` (o derivar de `ORCH_HOST` env, default `0.0.0.0` cuando `mesh_enabled=true`).
2. Idem `up.cmd:148` para el frontend si se quiere acceso LAN al UI.
3. Actualizar `scripts/dev/doctor.cmd` para avisar si Core está bindeado a 127.0.0.1 con mesh activo.
4. Firewall Windows: abrir 9325/tcp inbound para `192.168.0.0/24` (el user lo deberá hacer manual una vez).

---

## F-09 — Duplicación de procesos Core uvicorn

**Síntoma**: Dos uvicorn del Core corriendo simultáneamente (PID 29920 y 10744), idéntica línea de comandos. Solo uno puede tener el puerto 9325 — el otro estará en estado loop o zombie.

**Evidencia**:
```
PID 29920  python -m uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325
PID 10744  python -m uvicorn tools.gimo_server.main:app --host 127.0.0.1 --port 9325
```

**Impacto**: Uno de los dos consume RAM sin servir. Riesgo si uvicorn tiene `--reload` y ambos intentan bind al mismo puerto.

**Fix**: `up.cmd` debe detectar Core ya corriendo antes de arrancar otro. Ya tiene un chequeo a HEAD /auth/check (línea 132) pero aparentemente se saltó. Revisar.

---

## F-10 — 5 procesos MCP bridge corriendo (huérfanos de clientes cerrados)

**Síntoma**: 5 instancias de `python -m tools.gimo_server.mcp_bridge.server` activas, probablemente una por cada `claude mcp` que se ha abierto en la sesión pero ninguna murió al cerrarse el cliente.

**Impacto**: Fugas de memoria. Cada bridge mantiene cache + handshake al Core.

**Fix**: el bridge debería detectar `stdin EOF` y terminar. Revisar `mcp_bridge/server.py` main loop.

---

## F-11 — App Android no transiciona a Dashboard tras redeem exitoso

**Síntoma**: E2E tras fix F-08: la app del S10 completa el wizard, envía `POST /ops/mesh/onboard/redeem` y recibe **200 OK**. Luego hace `GET /ops/mesh/devices/{id}` autenticado vía `device_secret` — todo funciona a nivel backend. **Pero la UI permanece en la pantalla "Redeem your code" y no navega al Dashboard**. Relanzar la app vuelve a la misma pantalla (el estado enrolado no se persiste en UI state).

**Evidencia** (logs Core 2026-04-19 20:53-20:54 UTC):
```
INFO: 192.168.0.244:51176 - "POST /ops/mesh/onboard/redeem HTTP/1.1" 200 OK
DEBUG: Authenticated mesh device sm-g973f-b2ce27fd via device_secret
INFO: 192.168.0.244:51174 - "GET /ops/mesh/devices/sm-g973f-b2ce27fd HTTP/1.1" 200 OK
```
Admin approve → `connection_state: approved` → app sigue en Redeem.

**Root cause presumido** (requiere confirmar con logs/Logcat de la app):
- El ViewModel no observa la respuesta del redeem o no emite navegación tras 200 OK.
- `SettingsStore` no persiste `enrolled=true` (o equivalente) tras redeem exitoso — por eso relaunch vuelve al wizard.

**Archivos candidatos a revisar**:
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/ui/MeshViewModel.kt` — manejo del resultado de `redeem()`.
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/ui/setup/*` — transición tras success.
- `apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/data/store/SettingsStore.kt` — persistir `localDeviceSecret`, `deviceId`, `coreUrl` después de redeem.

**Impacto**: bug UX bloqueante — el device SE enrola (backend lo confirma) pero el usuario no puede salir del wizard. Heartbeat tampoco arranca (MeshAgentService no se lanza porque la UI no avanza).

**Fix**: inspeccionar el flow `SetupViewModel.redeemCode()` → `GimoCoreClient.redeem()` → `SettingsStore.persist()` → navegación. Falta probablemente un `emit(SetupUiState.Success)` y/o un `NavController.navigate(Screen.Dashboard)`.

---

## Estado final sesión 2026-04-19

**Backend fixes aplicados y verificados**: F-01…F-10 resueltos.

**E2E status**:
- ✅ Core bindeado a `0.0.0.0:9325` — accesible desde LAN.
- ✅ Token precedence file>env con warning sobre divergencia.
- ✅ `POST /ops/mesh/toggle` funcional (atómico + audit log).
- ✅ `GET /ops/mesh/status` → 404 con mesh OFF, 200 con mesh ON.
- ✅ `/enrollment/*` marcados `deprecated=True` con sunset 2026-06-01.
- ✅ mDNS advertiser arranca con `mesh_enabled=true` (antes requería device_mode=server).
- ✅ `_gimo._tcp.local.` con TXT enriquecido (role, caps, endpoint, mesh_protocol).
- ✅ `GET /ops/mesh/host` devuelve `lan_urls` reales vía psutil + `mdns_active=true`.
- ✅ Launcher `up.cmd` idempotente + `doctor.cmd` con WARN bind.
- ✅ `POST /ops/mesh/prune` admin-only para devices offline > N días.
- ✅ MCP bridge con signal handlers (SIGTERM/EOFError/KeyboardInterrupt) — no más zombies.
- ✅ App Android: `coreUrl` default = `""` (no más IP fabricada).
- ✅ **E2E wizard del S10 alcanza el Core y completa redeem** (backend confirma enrollment).

**Pendiente post-sesión** (bug nuevo descubierto):
- F-11: app Android no transiciona a Dashboard tras redeem OK (ver sección arriba).

**Diferido del plan** (marcado post-MVP):
- NsdManager discovery real en la app Android (`apps/android/.../service/MdnsDiscovery.kt`).
- Worker token con scope `mesh:worker` (hoy se usa `device_secret` simple, que cumple el principio de scope limitado pero no es JWT rotable).
- Tests de contrato para 404/toggle/prune.
