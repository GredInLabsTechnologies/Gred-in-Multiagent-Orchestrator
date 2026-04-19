# GIMO Mesh — Server Mode Runbook

> rev 2 — 2026-04-15. Canonical procedure for bringing up a GIMO Core as a
> LAN-visible server mesh host on any supported platform (Windows, macOS,
> Linux, Android). Complements `docs/DEV_MESH_ARCHITECTURE.md` with the
> operator-facing steps.

## 0 · Principle

GIMO Core is the same binary surface on every platform. Server mode is a
single-lever switch that adjusts **three knobs**, no more:

1. Binding address (`0.0.0.0` vs `127.0.0.1`).
2. Host bootstrap record (`GIMO_MESH_HOST_DEVICE_MODE=server`).
3. mDNS advertiser auto-enable.

All three knobs derive from the same input (`--role server` or the equivalent
env vars). The orchestrator logic, schemas, endpoints, dispatch, and
observability are unchanged. If you add new logic that forks on "we are a
server", stop — that is a Phase 4 defect, not the intended design.

## 1 · Desktop launcher (Windows / macOS / Linux)

### 1a · CLI one-shot

```bash
# minimum — takes defaults, port 9325
python -m tools.gimo_server.main --role server --mesh-host-id my-desktop

# with explicit device class
python -m tools.gimo_server.main \
  --role server \
  --mesh-host-id my-desktop \
  --mesh-host-class desktop
```

Effects:

- Binds `0.0.0.0:9325` (WARN logged so the operator is aware of LAN exposure).
- Sets `GIMO_MESH_HOST_*` env vars for the lifespan, which the Android-shaped
  bootstrap path (`AndroidHostBootstrapService.from_env`) reuses cross-platform.
- Auto-enables the mDNS advertiser because `device_mode == server`.
- Seeds the TXT record with the host's initial health/mode/load signals.

### 1b · Env-var form (for systemd / Task Scheduler / launchd)

```bash
export ORCH_ROLE=server
export GIMO_MESH_HOST_ENABLED=true
export GIMO_MESH_HOST_DEVICE_ID=my-desktop
export GIMO_MESH_HOST_DEVICE_MODE=server
export GIMO_MESH_HOST_DEVICE_CLASS=desktop
python -m tools.gimo_server.main
```

Equivalent to the CLI form. Useful when the launcher is a service file.

### 1c · Verification

```bash
# 1. Health endpoint reports the expected build
curl http://127.0.0.1:9325/health

# 2. /ops/mesh/host shows the bootstrapped device and LAN URLs
curl -H "Authorization: Bearer $ORCH_TOKEN" http://127.0.0.1:9325/ops/mesh/host

# 3. mDNS advertiser is running — from a peer on the same LAN:
gimo discover --timeout 5
```

Expected `discover` output includes at least one verified peer whose
`MODE` column reads `server` and whose `HEALTH` is > 0. Unverified peers
(wrong token or no token configured) show `no` under VERIFIED — do not
auto-connect to those.

## 2 · Android launcher

Android phones run the embedded Core through `EmbeddedCoreRunner`. Server
mode is expressed in the UI as the "Serve" capability pill on the Settings
screen. Flipping "Serve" on does three things without the operator touching
env vars directly:

1. `hybridServe = true` in the `SettingsStore`.
2. `EmbeddedCoreRunner.resolveEffectiveDeviceMode()` resolves to `"server"`,
   which propagates as `GIMO_MESH_HOST_DEVICE_MODE=server` to the Core
   subprocess.
3. The embedded Core auto-enables mDNS and binds `0.0.0.0`, matching the
   desktop contract exactly.

The foreground notification then shows the LAN URL with a deep link — tapping
the notification opens the just-started dashboard in the phone's browser, so
the operator sees the same UI a desktop peer would. If no LAN URL is
resolvable (no Wi-Fi / hotspot), the notification stays in its plain form.

## 3 · LAN discovery from a second device

The second device does not need any prior configuration beyond the shared
`ORCH_TOKEN` (used to verify mDNS announcements). It scans with:

```bash
gimo discover                    # 3 s scan
gimo discover --timeout 8 --json # JSON for scripting
```

Verified peers are printed first, sorted by health desc, load asc. Setting
`ORCH_TOKEN` in the environment upgrades verification automatically; without
a token, peers are shown but marked unverified — a human should pick.

## 4 · Shutdown and cleanup

- **Desktop**: Ctrl-C in the foreground process; the lifespan teardown
  unregisters the mDNS service and stops the refresh loop. The host device
  record remains in the mesh registry until it is expired by the 90-second
  heartbeat timeout.
- **Android**: stop the foreground service from the app's notification or
  kill the process; `MeshAgentService.onDestroy()` already stops the Core
  subprocess and resets the host runtime reporter.

## 5 · Security reminders

- Every `/ops/*` endpoint still requires a Bearer token. Binding `0.0.0.0`
  exposes the surface but does **not** disable auth.
- mDNS announcements carry a 32-hex HMAC over `hostname:port:mode:health:load`.
  Clients should treat peers with missing or mismatched HMACs as untrusted.
- Do not expose `0.0.0.0` to the public internet. Server mode is a LAN
  primitive; if you need remote access, front it with an authenticated
  reverse proxy or WireGuard — never bare.

## 6 · When to use which mode

| Scenario | Launcher | device_mode |
| --- | --- | --- |
| Lone desktop, no mesh peers | `gimo` (default) | `inference` |
| Desktop serving LAN peers | `--role server --mesh-host-id X` | `server` |
| Phone contributing compute only | Settings → Inference pill | `inference` |
| Phone both serving its UI and accepting peers | Settings → Serve pill (+ Inference / Utility as desired) | `server` or `hybrid` |
| Laptop on battery, <30 % | Avoid `--role server`; dispatch scoring penalises it | n/a |

## 7 · Troubleshooting

- **mDNS auto-enable didn't fire**: confirm `app.state.mesh_host_device` is
  non-null in the lifespan logs. If `GIMO_MESH_HOST_DEVICE_ID` is empty the
  bootstrap is skipped and mDNS stays off.
- **`gimo discover` finds no peers**: firewall on the peer, mismatched
  subnets, or the peer is binding 127.0.0.1. Verify `ORCH_HOST` is not set to
  localhost on the server side.
- **Verified column reads `no` everywhere**: `ORCH_TOKEN` is not the same on
  both sides. Server signs with the host's token; client verifies with its
  own — they must match.
- **LAN URL missing from Android notification**: `HostRuntimeReporter`
  couldn't resolve a non-loopback interface. Check that the phone is on
  Wi-Fi or a hotspot, not cellular-only.

## 8 · Upgrade procedure (runtime packaging MVP)

> Canonical flow introduced by plan
> `E2E_ENGINEERING_PLAN_20260416_RUNTIME_PACKAGING`. See
> `docs/DEV_MESH_ARCHITECTURE.md §2.4` para el design rationale.

El Core se empaqueta como bundle portable (tarball XZ + manifest Ed25519-
firmado). Upgrades ocurren sin reinstalar la APK ni el launcher desktop.

### 8.1 · Estado local

```bash
gimo runtime status          # rutas + versión extraída vs versión del manifest
gimo runtime status --json   # para scripts
```

Campos relevantes:

- `manifest_version` — versión declarada por el bundle disponible localmente.
- `extracted_version` — versión que el Core actual está sirviendo (marker
  `.extracted-version` dentro de `target_dir`).
- Si `extracted_version != manifest_version` → hay un bundle nuevo pendiente
  de expansión; se aplicará en el próximo arranque.

### 8.2 · Producir un bundle local (dev)

```bash
# Generar keypair Ed25519 (una vez; guardar privada FUERA del repo)
python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey as K; \
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, PublicFormat; \
k = K.generate(); \
open('signing_key.pem', 'w').write(k.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()); \
open('public_key.pem', 'w').write(k.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode())"

# Empaquetar (sólo host target soportado localmente; cross-compile = CI)
python scripts/package_core_runtime.py build \
  --target host --compression xz \
  --runtime-version 0.1.0-dev \
  --signing-key signing_key.pem \
  --output runtime-assets/

# Verificar roundtrip
python scripts/package_core_runtime.py verify \
  --bundle runtime-assets/ --public-key public_key.pem
```

### 8.3 · Upgrade peer-to-peer

Desde un device consumidor, apuntando a un peer del mesh que ya sirve la
versión deseada:

```bash
export ORCH_TOKEN=<token-compartido>
export ORCH_RUNTIME_PUBLIC_KEY="$(cat public_key.pem)"

# El peer debe tener un bundle publicado en runtime-assets/ con la misma clave
gimo runtime upgrade --peer http://192.168.1.50:9325
```

Salida esperada (outcome `upgraded`):

```
→ Descargando runtime desde http://192.168.1.50:9325
  45.2 MiB / 45.2 MiB (100%)
✓ Upgrade completo: 0.1.0-dev → 0.2.0
  Runtime dir: /home/user/gimo/runtime
  Python:      /home/user/gimo/runtime/python/bin/python
```

El comando verifica **firma + sha256 antes de tocar el target_dir**; si algo
falla, el bundle anterior permanece intacto (rollback via backup en
`runtime_bootstrap.ensure_extracted`).

Flags útiles:

- `--allow-downgrade` — permitir bajar de versión (requerido si `remote <
  local`).
- `--allow-unsigned` — SÓLO en tests. Nunca en producción.
- `--json` — salida estructurada para automatización.
- `--token <tok>` — override de `ORCH_TOKEN` si el peer usa otro.

### 8.4 · Upgrade desde un build de CI

Cada run del matrix `runtime-packaging` en `.github/workflows/ci.yml` sube
un artefacto `gimo-core-runtime-<target>` (retención 7 días). Para
probarlo en un device local:

1. Descargar el artefacto de GitHub Actions.
2. Extraerlo a `runtime-assets/`.
3. Arrancar el Core (el launcher detectará el bundle y `ensure_extracted`
   lo expandirá en el primer arranque).

### 8.5 · Resolución de problemas

- **`signature verification failed`** — la clave pública embebida /
  `ORCH_RUNTIME_PUBLIC_KEY` no coincide con la privada que firmó el bundle.
  Intercambiar la pública correcta via canal fuera de banda.
- **`tarball sha256 mismatch`** — descarga interrumpida o corrupción. El
  archivo `.download-partial` queda borrado; reintentar el comando.
- **`peer runtime X is older than local`** — protección contra downgrade.
  Si es intencional, añadir `--allow-downgrade`.
- **Launcher desktop arranca con `provenance=host` en los logs** — el bundle
  no está presente o su bootstrap falló; el Core está usando el Python del
  sistema. Revisar `gimo runtime status` y los logs para el motivo concreto.
