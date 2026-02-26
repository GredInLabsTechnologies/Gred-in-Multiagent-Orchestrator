# Cold Room Fortress + Login Cinematico + Redesign Visual Completo

> **Status:** ACTIVE
> **Fecha:** 2026-02-26
> **Supersedes:** docs/FIREBASE_SSO_PROFILE_PLAN_2026-02-25.md (Fases 1-5 completadas),
> docs/UI_IMPROVEMENT_PLAN_2026-02-23.md (Fases 1-2 completadas, Fase 3 items pendientes absorbidos aqui como Fase 0)
> **Scope:** tools/gimo_server/security/, tools/gimo_server/routers/, tools/orchestrator_ui/src/
> **Ejecutores:** Claude Code + shilo

---

## Contexto

GIMO necesita: (1) soporte para entornos air-gapped via licencia firmada asimetricamente, (2) una experiencia de login cinematica, y (3) un rediseno visual completo de la app con una paleta derivada de la esencia del codigo — "precision instrument" en vez de "iOS clone". NO se cambia estructura/layout de componentes a menos que mejore el flujo de trabajo. La maxima: minimizar clicks, facilitar comprension y ejecucion de tareas.

---

## FASE 0: Deuda pendiente de planes anteriores

Items que quedaron incompletos del UI_IMPROVEMENT_PLAN_2026-02-23.md Fase 3:

### 0.1 Chat collapsible (Fase 3.2 vieja) — PARCIAL

- Estado: App.tsx tiene isChatCollapsed state y react-resizable-panels importado, pero la logica de colapso no esta conectada
- Archivos: App.tsx, OrchestratorChat.tsx
- Fix: Conectar el estado isChatCollapsed con la UI — boton chevron visible, panel se colapsa a barra de input flotante

### 0.2 Creacion manual de nodos en grafo (Fase 3.5 vieja) — PENDIENTE

- Estado: GraphCanvas.tsx tiene isEditMode state pero no hay UI para crear nodos ni edges
- Archivos: GraphCanvas.tsx
- Fix: Anadir boton toggle "Modo Edicion", double-click en canvas crea nodo, drag entre handles crea edge, guardar como draft via POST /ops/drafts
- Nota: Esta mejora es significativa y mejora directamente el flujo de trabajo. Prioridad ALTA.

### 0.3 console.log como error handlers — MENOR

- Estado: App.tsx y GraphCanvas.tsx tienen console.error donde deberia haber toast
- Fix: Reemplazar por addToast(message, 'error')

---

## PARTE 1: Arquitectura Fortress — Anti-Pirateria + Cold Room Seguro

### 1.0 Threat model y filosofia

El sistema anterior (HMAC simetrico con pairing code) tenia un fallo critico: un atacante
podia aislar GIMO en una VM sin red, solicitar Cold Room mode, y obtener licencia gratuita
indefinida. El shared secret era derivable por ambas partes, permitiendo falsificacion.

**Nuevo principio**: La unica entidad que puede emitir licencias es el servidor de GIMO,
usando una clave privada Ed25519 que **nunca sale del servidor**. La maquina local solo
puede verificar firmas con la clave publica embebida en codigo compilado. No existe
operacion local que permita generar una licencia valida.

**Capas de defensa**:

| Capa | Que protege | Contra que ataque |
|------|-------------|-------------------|
| 1. Server-Side Gating | Funciones core | Uso sin licencia (las funciones no existen localmente) |
| 2. Firma Ed25519 asimetrica | Cold Room license | Falsificacion de licencia offline |
| 3. Manifest firmado de integridad | Codigo fuente | Parcheo de license_guard.py o cold_room.py |
| 4. Compilacion Cython nativa | Modulos de seguridad | Lectura/modificacion de logica de verificacion |
| 5. Anti-tamper runtime | Ejecucion en vivo | Debugging, instrumentacion, VM spoofing |
| 6. Telemetria + revocacion | Licencias activas | Compartir licencias, anomalias de uso |

### 1.1 Capa 1: Server-Side Gating

Las funciones mas valiosas de GIMO **no existen en la instalacion local**. El servidor
las ejecuta y devuelve resultados.

**Funciones gated (requieren servidor)**:
- Plan generation (`POST /ops/generate`)
- Draft approval workflows (`POST /ops/drafts/{id}/approve`)
- Workflow execution (`POST /ops/workflows/execute`)
- Eval runs (`POST /ops/evals/run`)
- Model routing inteligente (`POST /ops/model/recommend`)

**Flujo**:
```
Usuario → GIMO local (UI + orchestration basica, grafo, chat)
              ↓ (con license_token en header)
         GIMO Cloud API (valida token por request)
              ↓
         Ejecuta funcion gated → devuelve resultado
```

- Sin licencia valida → el servidor rechaza con 403
- No puedes "parchear" logica que no esta en tu maquina
- La UI local funciona como visor/editor, pero la ejecucion real es server-side

**Cold Room enterprise**: Para clientes air-gapped con licencia pagada, se entrega un
bundle compilado (Cython .pyd/.so) con las funciones gated incluidas, firmado y con
fecha de expiracion embebida. Este bundle es **unico por maquina** (bound al fingerprint).

### 1.2 Capa 2: Licencia Cold Room con firma Ed25519

Reemplaza completamente el sistema HMAC simetrico anterior.

**Generacion (solo en servidor, con clave PRIVADA)**:
```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import msgpack, base64, os

def generate_cold_room_license(private_key: Ed25519PrivateKey,
                                machine_id: str,
                                plan: str,
                                duration_days: int = 30,
                                max_renewals: int = 12,
                                features: list[str] = None) -> str:
    """Solo ejecutable en el servidor de licencias GIMO."""
    payload = {
        "v": 2,                                    # version del formato
        "mid": machine_id,                         # GIMO-XXXX-XXXX
        "plan": plan,                              # "enterprise_cold_room"
        "iat": int(time.time()),                   # issued at
        "exp": int(time.time()) + duration_days * 86400,  # expiracion
        "rnw": max_renewals,                       # renovaciones permitidas
        "feat": features or ["orchestration", "eval", "mastery", "trust"],
        "nonce": os.urandom(16).hex(),             # anti-replay
    }
    payload_bytes = msgpack.packb(payload, use_bin_type=True)
    signature = private_key.sign(payload_bytes)     # Ed25519 firma (64 bytes)
    return base64.urlsafe_b64encode(payload_bytes + signature).decode()
```

**Verificacion (en la maquina local, con clave PUBLICA embebida)**:
```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# Clave publica embebida en codigo COMPILADO (Cython .pyd)
# El atacante tendria que hacer reverse engineering del binario para cambiarla
EMBEDDED_PUBLIC_KEY = Ed25519PublicKey.from_public_bytes(bytes.fromhex("..."))

def verify_cold_room_license(license_blob: str, machine_id: str) -> LicenseStatus:
    raw = base64.urlsafe_b64decode(license_blob)
    payload_bytes, signature = raw[:-64], raw[-64:]

    # 1. Verificar firma — sin clave privada, imposible falsificar
    try:
        EMBEDDED_PUBLIC_KEY.verify(signature, payload_bytes)
    except InvalidSignature:
        return LicenseStatus(valid=False, reason="invalid_signature")

    payload = msgpack.unpackb(payload_bytes, raw=False)

    # 2. Verificar que es para ESTA maquina
    if payload["mid"] != machine_id:
        return LicenseStatus(valid=False, reason="machine_mismatch")

    # 3. Verificar expiracion
    if time.time() > payload["exp"]:
        return LicenseStatus(valid=False, reason="cold_room_renewal_required")

    # 4. Verificar version del formato
    if payload.get("v") != 2:
        return LicenseStatus(valid=False, reason="unsupported_license_version")

    return LicenseStatus(
        valid=True,
        plan=payload["plan"],
        expires_at=datetime.fromtimestamp(payload["exp"]),
        features=payload["feat"],
        renewals_remaining=payload["rnw"],
    )
```

**Flujo de pairing**:
```
1. Maquina air-gapped muestra Machine ID: GIMO-XXXX-XXXX
2. Admin lleva Machine ID al portal web de GIMO (otro PC con internet)
3. Portal genera license_blob FIRMADO (Ed25519 privada) → base64 string
4. Admin copia el blob (USB, papel, telefono) → lo introduce en la maquina
5. Maquina verifica firma con clave publica COMPILADA
6. Si valido → almacena blob cifrado en .gimo_cold_room (AES-256-GCM)
7. Cada 30 dias: misma ceremonia de renovacion (nuevo blob)
```

**Por que es seguro**:
- El atacante NO tiene la clave privada Ed25519 → no puede generar blobs validos
- La clave publica esta en un binario Cython compilado → no es trivial cambiarla
- Cada blob es unico por maquina + tiene expiracion + tiene nonce anti-replay
- VM detection (Capa 5) puede hacer que el portal RECHACE generar blobs para VMs

### 1.3 Capa 3: Manifest de integridad firmado

Problema del sistema actual: el file integrity check usa SHA-256 contra si mismo.
Un atacante puede modificar el archivo y recalcular el hash.

**Solucion**: Manifest firmado en build time con una clave separada.

```python
# BUILD TIME (CI/CD — nunca en la maquina del usuario):
import json
from pathlib import Path

CRITICAL_FILES = [
    "security/license_guard.py",   # o .pyd si compilado
    "security/cold_room.py",
    "security/fingerprint.py",
    "security/integrity.py",
    "config.py",
    "main.py",
]

def build_manifest(source_dir: Path, build_private_key) -> dict:
    manifest = {"v": 1, "built_at": int(time.time()), "files": {}}
    for f in CRITICAL_FILES:
        content = (source_dir / f).read_bytes()
        manifest["files"][f] = hashlib.sha256(content).hexdigest()
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    signature = build_private_key.sign(manifest_bytes)
    return {
        "manifest": manifest,
        "signature": base64.b64encode(signature).decode()
    }
    # Se guarda como .gimo_manifest en el paquete distribuido
```

```python
# RUNTIME (en la maquina del usuario):
def verify_integrity(manifest_path: Path, source_dir: Path) -> bool:
    data = json.loads(manifest_path.read_text())
    manifest_bytes = json.dumps(data["manifest"], sort_keys=True).encode()
    signature = base64.b64decode(data["signature"])

    # Verificar firma del manifest
    EMBEDDED_BUILD_PUBLIC_KEY.verify(signature, manifest_bytes)

    # Verificar cada archivo
    for filename, expected_hash in data["manifest"]["files"].items():
        actual = hashlib.sha256((source_dir / filename).read_bytes()).hexdigest()
        if not hmac.compare_digest(actual, expected_hash):
            raise TamperDetected(f"Modified: {filename}")
    return True
```

**Claves separadas**: La clave de build (manifest) es DIFERENTE a la de licencias.
Comprometer una no compromete la otra.

### 1.4 Capa 4: Compilacion Cython de modulos criticos

Los siguientes modulos se compilan a binario nativo (.pyd en Windows, .so en Linux):

```
tools/gimo_server/security/
├── license_guard.pyd     # Verificacion de licencias (contiene clave publica embebida)
├── cold_room.pyd         # Verificacion Cold Room (contiene clave publica embebida)
├── fingerprint.pyd       # Generacion de Machine ID
├── integrity.pyd         # Verificacion de manifest
```

**En distribucion de produccion**:
- NO se incluyen los .py fuente de estos modulos
- Solo los .pyd/.so compilados
- Las claves publicas estan como `bytes` literals dentro del codigo Cython
- Reverse engineering requiere descompilar binario nativo — skill de RE significativo

**En desarrollo** (DEBUG=true): se usan los .py normales para facilitar debugging.

**Build pipeline** (en setup.py o build script):
```python
from Cython.Build import cythonize
ext_modules = cythonize([
    "tools/gimo_server/security/license_guard.py",
    "tools/gimo_server/security/cold_room.py",
    "tools/gimo_server/security/fingerprint.py",
    "tools/gimo_server/security/integrity.py",
], compiler_directives={'language_level': "3"})
```

### 1.5 Capa 5: Anti-tamper en runtime

```python
# tools/gimo_server/security/runtime_guard.py

class RuntimeGuard:
    """Detecta instrumentacion y entornos sospechosos."""

    @staticmethod
    def check_debugger() -> bool:
        """Detecta debuggers activos."""
        if sys.gettrace() is not None:
            return True
        if sys.getprofile() is not None:
            return True
        # Windows: IsDebuggerPresent via ctypes
        if sys.platform == "win32":
            import ctypes
            if ctypes.windll.kernel32.IsDebuggerPresent():
                return True
        return False

    @staticmethod
    def check_vm_indicators() -> dict:
        """Detecta indicadores de VM (no bloquea, reporta)."""
        indicators = {}
        # Registry keys de VirtualBox/VMware/Hyper-V
        if sys.platform == "win32":
            import winreg
            vm_keys = [
                r"SOFTWARE\Oracle\VirtualBox Guest Additions",
                r"SOFTWARE\VMware, Inc.\VMware Tools",
            ]
            for key in vm_keys:
                try:
                    winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key)
                    indicators["vm_registry"] = True
                except FileNotFoundError:
                    pass
        # CPUID hypervisor bit
        # MAC address prefixes conocidos (08:00:27 = VirtualBox, 00:0C:29 = VMware)
        mac = uuid.getnode()
        mac_hex = f"{mac:012x}"
        vm_mac_prefixes = ["080027", "000c29", "001c42", "00155d", "00505e"]
        if mac_hex[:6] in vm_mac_prefixes:
            indicators["vm_mac"] = True
        return indicators

    @staticmethod
    def timing_check(func, max_ms: int = 500):
        """Si una funcion critica tarda demasiado, probable stepping."""
        start = time.perf_counter_ns()
        result = func()
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        if elapsed_ms > max_ms:
            # No bloquear inmediatamente, pero registrar anomalia
            logger.warning(f"Timing anomaly: {func.__name__} took {elapsed_ms:.0f}ms")
        return result
```

**Politica**: La deteccion de VM NO bloquea automaticamente (hay usuarios legitimos en VMs).
Pero el dato se envia al servidor en telemetria, y el portal de licencias puede:
- Mostrar warning al admin que solicita Cold Room para una VM
- Requerir aprobacion manual para VMs
- Limitar duracion de licencia para VMs (7 dias en vez de 30)

### 1.6 Capa 6: Telemetria + revocacion remota

**En modo online** (cada license check envía):
```python
telemetry = {
    "license_id": license.id,
    "machine_fingerprint": fingerprint_hash,
    "vm_detected": bool(RuntimeGuard.check_vm_indicators()),
    "debugger_detected": RuntimeGuard.check_debugger(),
    "file_integrity": "pass" | "fail" | "skip",
    "guard_version": GUARD_VERSION,
    "uptime_hours": get_uptime(),
    "geo_hint": None,  # el servidor detecta geo-IP del request
}
```

**Servidor detecta anomalias**:
- Misma licencia en >N maquinas distintas → revocacion automatica
- VM + Cold Room request → flag de sospecha, requiere aprobacion manual
- Fingerprint cambia frecuentemente → probable spoofing → rate limit
- Geo-IP imposible (dos paises distantes en <2h) → revocacion
- Debugger detectado repetidamente → flag

**Revocacion**:
- `periodic_recheck()` consulta al servidor cada 24h
- Si licencia revocada → `sys.exit(1)` con mensaje explicativo
- Para Cold Room: el blob tiene expiracion fija, no se puede revocar remotamente,
  pero el portal puede negarse a emitir renovaciones

### 1.7 Archivos a crear/modificar

| Archivo | Accion | Descripcion |
|---------|--------|-------------|
| `security/cold_room.py` | **Reescribir** | Ed25519 verify, license blob parsing, state cifrado |
| `security/runtime_guard.py` | **Nuevo** (~120 lineas) | Debugger detection, VM indicators, timing checks |
| `security/integrity.py` | **Nuevo** (~80 lineas) | Manifest verification con firma Ed25519 |
| `security/license_guard.py` | **Modificar** | Integrar RuntimeGuard, Integrity, nuevo Cold Room |
| `config.py` | **Modificar** | Nuevos campos (ver 1.8) |
| `routers/auth_router.py` | **Modificar** | Endpoints Cold Room actualizados |
| `main.py` | **Modificar** | Startup con integrity check + runtime guard |
| `setup_security.py` | **Nuevo** (~60 lineas) | Build script para Cython compilation |
| `.gimo_manifest` | **Generado** | Output del build pipeline |
| `tests/unit/test_cold_room.py` | **Reescribir** | Tests para firma Ed25519 |
| `tests/unit/test_runtime_guard.py` | **Nuevo** (~15 tests) | Tests anti-tamper |
| `tests/unit/test_integrity.py` | **Nuevo** (~10 tests) | Tests manifest verification |

### 1.8 Config (tools/gimo_server/config.py)

Campos nuevos/modificados en Settings:
```python
# Cold Room v2 (Fortress)
cold_room_enabled: bool              # ORCH_COLD_ROOM_ENABLED (default: false)
cold_room_license_path: Path         # base_dir / ".gimo_cold_room"
cold_room_renewal_days: int          # ORCH_COLD_ROOM_RENEWAL_DAYS (default: 30)

# Integrity
integrity_manifest_path: Path        # base_dir / ".gimo_manifest"
integrity_check_enabled: bool        # ORCH_INTEGRITY_CHECK (default: true)

# Runtime Guard
runtime_guard_enabled: bool          # ORCH_RUNTIME_GUARD (default: true)
runtime_guard_block_debugger: bool   # ORCH_BLOCK_DEBUGGER (default: false, solo reporta)
```

### 1.9 Endpoints Cold Room actualizados

4 endpoints sin auth (pre-auth):

- `GET /auth/cold-room/status` → `{enabled, paired, machine_id, expires_at, renewal_needed, vm_detected}`
- `POST /auth/cold-room/activate` (antes "pair") → Recibe `{license_blob: str}`, verifica firma Ed25519, almacena
- `GET /auth/cold-room/info` (antes "challenge") → `{machine_id, expires_at, plan, features, renewals_remaining}`
- `POST /auth/cold-room/renew` (antes "verify") → Recibe `{license_blob: str}` nuevo, verifica, actualiza

**Cambio clave**: Ya no hay challenge-response. El admin trae un blob firmado nuevo cada 30 dias.
El flujo es mas simple y mas seguro.

### 1.10 Startup (main.py)

```
1. RuntimeGuard.check_debugger() → si enabled y detectado → warning (o exit si block=true)
2. Integrity.verify_manifest() → si falla → exit(1) "Tamper detected"
3. LicenseGuard.validate() → flujo normal (online → offline cache → cold room)
4. Si cold_room + renewal_required → modo limitado (solo endpoints cold-room)
5. Spawn background: periodic_recheck + periodic integrity check (cada 6h)
```

### 1.11 Matriz de ataques vs defensas

| Ataque | Capa 1 | Capa 2 | Capa 3 | Capa 4 | Capa 5 | Capa 6 |
|--------|--------|--------|--------|--------|--------|--------|
| Editar license_guard.py | — | — | BLOQUEA | BLOQUEA | — | — |
| Fabricar license blob | — | BLOQUEA | — | — | — | — |
| Cambiar clave publica en .py | — | — | BLOQUEA | BLOQUEA | — | — |
| Cambiar clave publica en .pyd | — | — | — | DIFICULTA | — | — |
| VM aislada para Cold Room | — | — | — | — | DETECTA | BLOQUEA |
| Usar sin licencia | BLOQUEA | — | — | — | — | — |
| Compartir licencia entre PCs | — | BLOQUEA (mid) | — | — | — | BLOQUEA |
| Modificar env vars | — | — | BLOQUEA | — | — | — |
| Clock tampering | — | BLOQUEA (exp firmado) | — | — | — | — |
| Debugger/stepping | — | — | — | — | DETECTA | REPORTA |
| Uso offline eterno | BLOQUEA | BLOQUEA (exp 30d) | — | — | — | — |
| Parchear binario Cython | — | — | BLOQUEA | ~resistente | — | — |

**Costo para el atacante**: Para crackear GIMO necesitaria:
1. Descompilar binarios Cython (.pyd) — requiere herramientas de RE + skill
2. Encontrar la clave publica embebida en el binario
3. Reemplazarla por una propia
4. Generar su propia clave privada para firmar licencias
5. Recompilar el binario modificado
6. Repetir en cada actualizacion de GIMO

**Estimacion**: Horas a dias de trabajo especializado por version. Economicamente irracional
comparado con pagar la licencia.

### 1.12 Tests (~45 tests)

```
tests/unit/test_cold_room.py (~20 tests):
- test_machine_id_deterministic
- test_machine_id_format
- test_activate_valid_blob
- test_activate_invalid_signature
- test_activate_wrong_machine
- test_activate_expired_blob
- test_activate_wrong_version
- test_renewal_valid
- test_renewal_expired
- test_renewal_wrong_machine
- test_is_paired_after_activate
- test_is_paired_before_activate
- test_state_persistence_encrypted
- test_state_tamper_detected
- test_nonce_prevents_replay
- test_features_extracted
- test_renewals_remaining_decremented
- test_license_guard_integration_cold_room_valid
- test_license_guard_integration_cold_room_expired
- test_license_guard_integration_cold_room_disabled

tests/unit/test_runtime_guard.py (~15 tests):
- test_no_debugger_by_default
- test_debugger_detection_trace
- test_debugger_detection_profile
- test_vm_indicators_clean_machine
- test_vm_mac_detection
- test_timing_check_normal
- test_timing_check_slow
- test_check_all_returns_report
- test_windows_debugger_api (skip si no windows)
- test_vm_registry_keys (skip si no windows)
- test_guard_disabled_skips_all
- test_guard_report_format
- test_block_debugger_mode
- test_non_block_debugger_mode
- test_telemetry_payload_shape

tests/unit/test_integrity.py (~10 tests):
- test_valid_manifest_passes
- test_tampered_file_detected
- test_invalid_manifest_signature
- test_missing_manifest_file
- test_missing_critical_file
- test_manifest_version_check
- test_constant_time_comparison
- test_build_manifest_generates_valid
- test_manifest_with_compiled_modules
- test_integrity_disabled_skips
```

---

## PARTE 2: Design System — Paleta "Precision Instrument"

### 2.1 Nueva paleta de colores

Reemplaza la paleta iOS-inspired con una identidad propia derivada de la esencia del codigo.

**Fondos (Surface hierarchy)**:
```css
--surface-0: #080c14;    /* Deep navy — fondo base, NO negro puro */
--surface-1: #0c1222;    /* Navy principal — cards, panels */
--surface-2: #141c2e;    /* Elevado — dropdowns, modals */
--surface-3: #1c2640;    /* Terciario — hovers, active states */
```

**Texto**:
```css
--text-primary: #e8ecf4;    /* Off-white con tinte azul frio */
--text-secondary: #7d8a99;  /* Slate — labels, hints */
--text-tertiary: #3d4a5c;   /* Muy sutil — placeholders */
```

**Bordes**:
```css
--border-primary: #1e2a3e;  /* Sutil navy */
--border-subtle: #141c2e;   /* Casi invisible */
--border-focus: #3b82f6;    /* Azul electrico para focus rings */
```

**Acentos funcionales**:
```css
--accent-primary: #3b82f6;     /* Azul electrico — CTAs, links, focus */
--accent-approval: #d4a574;    /* Ambar calido — aprobaciones, exito, gates abiertos */
--accent-trust: #5a9f8f;       /* Verde azulado — trust ganado, cascade exitoso */
--accent-alert: #c85450;       /* Rojo calibrado — errores, amenazas */
--accent-warning: #d4975a;     /* Ambar oscuro — warnings */
--accent-purple: #8b7ec8;      /* Purpura instrumental — mastery, economia */
```

**Status (nodos del grafo, badges)**:
```css
--status-running: #3b82f6;   /* Azul electrico */
--status-done: #5a9f8f;      /* Verde azulado */
--status-error: #c85450;     /* Rojo calibrado */
--status-pending: #7d8a99;   /* Slate neutro */
--status-warning: #d4975a;   /* Ambar */
```

**Glows (para hover/focus effects)**:
```css
--glow-primary: rgba(59, 130, 246, 0.15);
--glow-approval: rgba(212, 165, 116, 0.15);
--glow-trust: rgba(90, 159, 143, 0.15);
--glow-alert: rgba(200, 84, 80, 0.12);
```

### 2.2 Archivos a modificar para la paleta

| Archivo | Cambio |
|---------|--------|
| tailwind.config.js | Reemplazar colores en theme.extend.colors, nuevas animaciones |
| src/index.css | Actualizar CSS custom properties :root |
| Todos los ~77 componentes | Reemplazar hex literals hardcoded por variables Tailwind |

### 2.3 Estrategia de migracion de colores

Para no tocar 77 archivos manualmente, la estrategia es:

1. Definir tokens en index.css como CSS custom properties (ya parcialmente hecho)
2. Mapear en tailwind.config.js a clases utilitarias (bg-surface-0, text-accent-primary, etc.)
3. Buscar y reemplazar los hex hardcoded mas comunes:
   - `#000000` → bg-surface-0 / var(--surface-0)
   - `#0a0a0a` → bg-surface-1
   - `#141414` → bg-surface-2
   - `#1c1c1e` → bg-surface-3
   - `#0a84ff` → text-accent-primary / bg-accent-primary
   - `#32d74b` → text-accent-trust
   - `#ff453a` / `#ff3b30` → text-accent-alert
   - `#ff9f0a` → text-accent-warning
   - `#86868b` → text-secondary
   - `#f5f5f7` → text-primary
   - `#2c2c2e` → border-primary
   - `#af52de` → text-accent-purple
4. No cambiar estructura — solo color values, respetando las mismas clases Tailwind

---

## PARTE 3: Login Cinematico

### 3.1 Componentes nuevos

```
src/components/login/
├── LoginBootSequence.tsx    (~80 lineas) — secuencia arranque <2s
├── LoginGlassCard.tsx       (~60 lineas) — contenedor con transiciones
├── AuthMethodSelector.tsx   (~120 lineas) — elegir Google/Token/Cold Room
├── GoogleSSOPanel.tsx       (~50 lineas) — extraido de LoginModal
├── TokenLoginPanel.tsx      (~60 lineas) — extraido de LoginModal
├── ColdRoomActivatePanel.tsx(~140 lineas) — Machine ID + license blob entry
├── ColdRoomRenewalPanel.tsx (~120 lineas) — muestra info + nuevo blob entry
├── AuthLoadingOverlay.tsx   (~40 lineas) — animacion verificacion
├── AuthSuccessTransition.tsx(~50 lineas) — transicion exito → app
├── AuthErrorPanel.tsx       (~30 lineas) — error con retry
├── LoginParallaxLayer.tsx   (~60 lineas) — parallax mouse
src/hooks/
└── useColdRoomStatus.ts     (~30 lineas) — fetch /auth/cold-room/status
```

### 3.2 Componentes modificados

- LoginModal.tsx → refactored como state machine
- AuthGraphBackground.tsx → recibe loginState prop, ajusta colores a nueva paleta

### 3.3 State machine

```
boot(1.5s) → select → google|token|cold-activate|cold-renew → verifying → success|error
                                                                  ↓
                                                                select
```

### 3.4 Boot sequence (1500ms)

1. 0-400ms: Fondo #080c14. Logo GIMO fade-in con glow azul electrico expandiendose
2. 400-800ms: Linea de escaneo horizontal (gradient animation). Texto monospace "Inicializando sistema..."
3. 800-1200ms: Dot grid materializa con wave. 4 indicadores: LICENCIA, RED, SEGURIDAD, MOTOR
4. 1200-1500ms: Todo se disuelve (scale 1.05 + opacity 0) revelando selector

prefers-reduced-motion: skip directo a selector con fadeIn simple.

### 3.5 Selector de metodo

3 cards con nueva paleta:
- **Google SSO**: borde --accent-primary (azul electrico), glow azul hover
- **Token Local**: borde --border-primary (navy sutil), icono Key
- **Sala Limpia**: borde --accent-trust (verde azulado), icono Shield. Solo si cold_room enabled. Badge ambar si renewal needed

Card base: `bg-surface-2/60 backdrop-blur-lg rounded-2xl border-[var(--border-primary)] hover:scale-[1.02] hover:border-accent-primary/50`

### 3.6 Cold Room panels (actualizados para Fortress)

**Activate** (antes "Pairing"):
- Machine ID grande monospace con borde brillante + boton copiar
- Textarea para pegar el license blob (base64 string largo)
- Boton "Activar Licencia" → POST /auth/cold-room/activate
- Feedback: firma valida → success transition, firma invalida → shake + error message

**Renewal**:
- Info card: plan, features, expira en X dias, renovaciones restantes
- Textarea para pegar nuevo license blob
- Boton "Renovar" → POST /auth/cold-room/renew

### 3.7 Parallax layer

2 circulos blur decorativos siguen el mouse. Glass card se mueve inverso (-0.5%). Deshabilitado con reduced-motion.

### 3.8 Animaciones nuevas en tailwind.config.js

```
'scan-line': 'scanLine 0.6s ease-out forwards',
'type-in': 'typeIn 0.4s steps(20) forwards',
'glow-pulse': 'glowPulse 2s ease-in-out infinite',
'materialize': 'materialize 0.5s ease-out forwards',
'zoom-fade-out': 'zoomFadeOut 0.3s ease-in forwards',
'orbit': 'orbit 1.2s linear infinite',
```

---

## PARTE 4: Migracion visual de componentes internos

Regla: NO cambiar estructura ni layout. Solo colores, glows, y transiciones.

### 4.1 Componentes core (impacto visual alto)

| Componente | Cambios |
|-----------|---------|
| MenuBar.tsx | bg → surface-0, borders → navy, hover → surface-3, profile pill → border-primary |
| Sidebar.tsx | bg → surface-0, active tab → accent-primary/15, divider → border-subtle |
| Footer.tsx | bg → surface-1, text → text-secondary |
| GraphCanvas.tsx | Canvas bg → surface-1, minimap → surface-2, controls → surface-2 |
| OrchestratorNode.tsx | bg → surface-2, running → glow-primary, done → accent-trust, error → accent-alert |
| BridgeNode/RepoNode/ClusterNode | Mismos cambios que OrchestratorNode |
| OrchestratorChat.tsx | Container → surface-1, messages → surface-2/3, input → surface-2 |
| InspectPanel.tsx | bg → surface-1, tabs → surface-2, active → accent-primary |
| PlanOverlayCard.tsx | Approve → accent-approval (ambar), Reject → accent-alert |

### 4.2 Dashboards (impacto medio)

| Componente | Cambios |
|-----------|---------|
| TokenMastery.tsx | Header purple → accent-purple, charts → nueva paleta status |
| TrustDashboard.tsx | Score bars → accent-trust/warning/alert, table → surface-1/2 |
| EvalDashboard.tsx | Cards → surface-2, accents → nueva paleta |
| ObservabilityPanel.tsx | Timeline → surface-1/2, status colors → nueva paleta |
| ProviderSettings.tsx | Cards → surface-2, health → accent-trust, install btn → accent-primary |

### 4.3 Micro-componentes

| Componente | Cambios |
|-----------|---------|
| Toast.tsx | Success → accent-trust/10, Error → accent-alert/10, Info → accent-primary/10 |
| ConfidenceMeter.tsx | Niveles → nueva paleta status |
| TrustBadge.tsx | autonomous → accent-trust, supervised → accent-warning, restricted → accent-alert |
| ThreatLevelIndicator.tsx | NOMINAL → accent-trust, ALERT → accent-warning, GUARDED → accent-warning, LOCKDOWN → accent-alert |
| SkeletonLoader.tsx | Gradient → surface-2 ↔ surface-3 |
| LiveLogs.tsx | bg → surface-0, text → accent-trust (verde azulado) |
| WelcomeScreen.tsx | bg → surface-1, accent buttons → accent-primary |
| ProfilePanel.tsx | bg → surface-1, plan badges → accent-approval/trust/purple |
| CommandPalette.tsx | Modal → surface-2/60 backdrop blur, borders → navy |

### 4.4 Componentes UI base

| Componente | Cambios |
|-----------|---------|
| ui/button.tsx | Primary → accent-primary, destructive → accent-alert |
| ui/card.tsx | bg → surface-2, border → border-primary |
| ui/input.tsx | bg → surface-2, focus → border-focus, placeholder → text-tertiary |
| ui/select.tsx | Dropdown → surface-2, hover → surface-3 |

### 4.5 Glass morphism actualizado

```css
.glass {
    background-color: var(--surface-2);
    border: 1px solid var(--border-primary);
    box-shadow: 0 4px 12px rgba(8, 12, 20, 0.4);  /* navy shadow en vez de negro */
    backdrop-filter: blur(16px);
}

.glow-primary { box-shadow: 0 0 30px var(--glow-primary); }
.glow-approval { box-shadow: 0 0 20px var(--glow-approval); }
.glow-trust { box-shadow: 0 0 20px var(--glow-trust); }
.glow-alert { box-shadow: 0 0 20px var(--glow-alert); }
```

### 4.6 AuthGraphBackground.tsx — nueva paleta

Cambiar el rango de hue de 195-230 (sky blue) a un rango que alterne entre:
- Navy/azul electrico (hue 210-230)
- Ambar calido (hue 30-40) para algunos nodos
- Verde azulado (hue 165-175) para nodos "done"

---

## PARTE 5: Mejoras de flujo UX (solo si mejora productividad)

Regla: solo cambios que reduzcan clicks o mejoren comprension.

### 5.1 Approve/Reject en PlanOverlayCard

El boton Approve cambia de verde generico a ambar calido (--accent-approval), que es mas distinguible y comunica "puerta abierta". El boton Reject se mantiene rojo pero mas suave.

### 5.2 Status colors en nodos del grafo

Los nodos running/done/error usan la nueva paleta status. done con verde azulado es mas legible que el verde brillante iOS anterior contra fondos navy.

### 5.3 Toast notifications

Sin cambio estructural. Solo nueva paleta de colores.

---

## PARTE 6: Microanimaciones — Kinestesia y Valor Percibido

Cada interaccion debe sentirse como operar un instrumento de precision. Nada es gratuito: cada animacion comunica estado, confirma accion, o guia la atencion.

### 6.1 Principios de animacion

| Principio | Regla | Ejemplo |
|-----------|-------|---------|
| Feedback tactil | Todo click tiene respuesta visual en <100ms | Boton escala 0.97 al pulsar |
| Entrada con proposito | Elementos aparecen de donde tienen sentido | Panel lateral entra desde la derecha |
| Salida discreta | Las salidas son mas rapidas que las entradas | Entrada 300ms, salida 150ms |
| Estado continuo | Los estados activos "respiran" suavemente | Nodo running pulsa glow |
| Jerarquia temporal | Lo importante aparece primero | Cards escalonan 50ms entre si |
| Sin bloqueo | Ninguna animacion bloquea la interaccion | Todas con pointer-events: auto |

### 6.2 Nuevas animaciones en tailwind.config.js

```javascript
keyframes: {
    // --- Feedback tactil ---
    press: {
        '0%': { transform: 'scale(1)' },
        '50%': { transform: 'scale(0.97)' },
        '100%': { transform: 'scale(1)' },
    },
    // --- Entradas ---
    slideInRight: {
        '0%': { transform: 'translateX(12px)', opacity: '0' },
        '100%': { transform: 'translateX(0)', opacity: '1' },
    },
    slideInUp: {
        '0%': { transform: 'translateY(8px)', opacity: '0' },
        '100%': { transform: 'translateY(0)', opacity: '1' },
    },
    slideInDown: {
        '0%': { transform: 'translateY(-8px)', opacity: '0' },
        '100%': { transform: 'translateY(0)', opacity: '1' },
    },
    // --- Glow estados ---
    glowBreath: {
        '0%, 100%': { boxShadow: '0 0 12px var(--glow-primary)' },
        '50%': { boxShadow: '0 0 24px var(--glow-primary)' },
    },
    glowBreathApproval: {
        '0%, 100%': { boxShadow: '0 0 8px var(--glow-approval)' },
        '50%': { boxShadow: '0 0 20px var(--glow-approval)' },
    },
    // --- Status ---
    statusPulse: {
        '0%, 100%': { opacity: '1' },
        '50%': { opacity: '0.6' },
    },
    // --- Confirmacion ---
    confirmFlash: {
        '0%': { backgroundColor: 'var(--accent-approval)', opacity: '0.3' },
        '100%': { backgroundColor: 'transparent', opacity: '0' },
    },
    // --- Shake para error ---
    shake: {
        '0%, 100%': { transform: 'translateX(0)' },
        '20%, 60%': { transform: 'translateX(-4px)' },
        '40%, 80%': { transform: 'translateX(4px)' },
    },
    // --- Barra de progreso indeterminada ---
    indeterminate: {
        '0%': { transform: 'translateX(-100%)' },
        '100%': { transform: 'translateX(200%)' },
    },
    // --- Counter/numero que cambia ---
    countUp: {
        '0%': { transform: 'translateY(100%)', opacity: '0' },
        '100%': { transform: 'translateY(0)', opacity: '1' },
    },
},
animation: {
    'press': 'press 150ms ease-out',
    'slide-in-right': 'slideInRight 250ms ease-out',
    'slide-in-up': 'slideInUp 200ms ease-out',
    'slide-in-down': 'slideInDown 200ms ease-out',
    'glow-breath': 'glowBreath 2.5s ease-in-out infinite',
    'glow-breath-approval': 'glowBreathApproval 3s ease-in-out infinite',
    'status-pulse': 'statusPulse 2s ease-in-out infinite',
    'confirm-flash': 'confirmFlash 600ms ease-out forwards',
    'shake': 'shake 400ms ease-out',
    'indeterminate': 'indeterminate 1.5s ease-in-out infinite',
    'count-up': 'countUp 300ms ease-out',
    // Login-specific (de PARTE 3)
    'scan-line': 'scanLine 0.6s ease-out forwards',
    'type-in': 'typeIn 0.4s steps(20) forwards',
    'glow-pulse': 'glowPulse 2s ease-in-out infinite',
    'materialize': 'materialize 0.5s ease-out forwards',
    'zoom-fade-out': 'zoomFadeOut 0.3s ease-in forwards',
    'orbit': 'orbit 1.2s linear infinite',
}
```

### 6.3 Microanimaciones por componente

**Botones** (todos los ui/button.tsx):
- `active:scale-[0.97]` — feedback tactil al click
- `transition-all duration-150` — transicion rapida en hover
- Hover: `shadow-[0_0_12px_var(--glow-primary)]` — glow sutil
- Disabled: `opacity-50` sin transicion
- Approve button: hover → `animate-glow-breath-approval`
- Destructive button: hover → borde rojo intensifica `border-accent-alert/80`

**Cards y paneles**:
- Entrada al DOM: `animate-slide-in-up` con `animation-delay: calc(var(--i) * 50ms)`
- Hover: `transition-all duration-200 hover:translate-y-[-1px] hover:shadow-lg`
- Click en card navegable: `active:scale-[0.99]`

**Sidebar tabs** (Sidebar.tsx):
- Tab activo: `transition-colors duration-200`
- Indicador: barra lateral izquierda (2px) con `transition-all duration-300`
- Hover: `bg-surface-3/50` con `transition-colors duration-150`
- Icono tab activo: `text-accent-primary` con `transition-colors duration-200`

**MenuBar dropdowns** (MenuBar.tsx):
- Apertura: `animate-slide-in-down`
- Cierre: `opacity-0 transition-opacity duration-100`
- Item hover: `bg-surface-3` con `transition-colors duration-100`

**Graph nodes** (OrchestratorNode.tsx, etc.):
- Pending: estatico, `opacity-70`, sin glow
- Running: `animate-glow-breath` — borde azul pulsa
- Done: `animate-confirm-flash` una vez, luego estatico con borde accent-trust
- Error: `animate-shake` una vez, luego borde rojo estatico
- Seleccion: `ring-2 ring-accent-primary/50 transition-shadow duration-200`
- Hover: `translate-y-[-1px] shadow-lg transition-all duration-150`

**Graph edges** (ReactFlow custom):
- Edge activo: `stroke-dasharray: 6 4` con `animation: edgeFlow 0.8s linear infinite`
- Edge completado: linea solida `stroke: var(--accent-trust)`
- Edge error: `stroke: var(--accent-alert)` con `opacity: 0.5`

**InspectPanel**:
- Apertura: `animate-slide-in-right` (300ms)
- Cierre: `translateX(100%) transition-transform duration-150`
- Tab switch: contenido `animate-slide-in-up` sutil (100ms)

**Chat panel** (OrchestratorChat.tsx):
- Mensajes nuevos: `animate-slide-in-up` escalonado
- Typing indicator: 3 puntos con `animate-status-pulse` desfasados 200ms
- Input focus: borde → `border-accent-primary` con `transition-colors duration-200`
- Envio: input hace `animate-press` brief

**Toast notifications** (Toast.tsx):
- Entrada: `animate-slide-in-right` (250ms)
- Salida: `opacity-0 translate-x-4 transition-all duration-150`
- Success: flash fondo `accent-trust/10`
- Error: `animate-shake` suave

**PlanOverlayCard**:
- Aparicion: `animate-slide-in-up` con backdrop-blur gradual
- Approve hover: `animate-glow-breath-approval`
- Approve click: `animate-confirm-flash`
- Reject hover: borde rojo intensifica
- Reject click: `animate-shake` sutil

**Trust/Confidence badges** (TrustBadge.tsx, ConfidenceMeter.tsx):
- Cambio de valor: efecto odometro con `animate-count-up`
- Nivel sube: flash verde sutil
- Nivel baja: flash ambar sutil

**ThreatLevelIndicator**:
- NOMINAL: punto verde estatico
- ALERT: punto ambar con `animate-status-pulse`
- GUARDED: punto ambar con pulse rapido (1s)
- LOCKDOWN: punto rojo con pulse rapido + borde rojo pulsante

**TokenMastery charts**:
- Numeros: `animate-count-up` cuando cambian
- Barras: `transition-all duration-500` (Recharts ya anima)
- Tab switch: anterior sale `opacity-0 duration-100`, nuevo entra `animate-slide-in-up`

**Profile panel** (ProfilePanel.tsx):
- Apertura: `animate-slide-in-down`
- Avatar: hover → `scale-105 transition-transform duration-200`
- Plan badge premium: `animate-glow-breath-approval`

**Command palette** (CommandPalette.tsx):
- Apertura: `animate-slide-in-down` + backdrop blur 0→16px en 200ms
- Resultados: escalonados `animation-delay: calc(var(--i) * 30ms)`
- Seleccion: `bg-surface-3` con `transition-colors duration-100`

### 6.4 Transiciones CSS globales en index.css

```css
/* Transicion base para TODOS los elementos interactivos */
button, a, [role="button"], [tabindex="0"],
input, select, textarea {
    transition-property: color, background-color, border-color, box-shadow, opacity, transform;
    transition-duration: 150ms;
    transition-timing-function: ease-out;
}

/* Active state tactil global */
button:active, [role="button"]:active {
    transform: scale(0.97);
}

/* Focus visible global — anillo azul electrico */
:focus-visible {
    outline: none;
    box-shadow: 0 0 0 2px var(--surface-0), 0 0 0 4px var(--accent-primary);
}

/* Reduced motion: cancelar TODAS las animaciones complejas */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}
```

### 6.5 Resumen de timings

| Tipo | Duracion | Easing | Cuando |
|------|----------|--------|--------|
| Feedback tactil (press) | 150ms | ease-out | Click en botones/cards |
| Hover color | 150ms | ease-out | Hover en cualquier interactivo |
| Entrada panel/card | 200-300ms | ease-out | Aparicion de elementos |
| Salida panel/card | 100-150ms | ease-in | Desaparicion (mas rapida) |
| Glow breathing | 2-3s | ease-in-out | Estados activos (running, approval) |
| Status pulse | 2s | ease-in-out | Indicadores de estado vivo |
| Confirm flash | 600ms | ease-out | Confirmacion de accion critica |
| Error shake | 400ms | ease-out | Error o rechazo |
| Escalonado entre cards | 50ms delay | — | Multiples cards apareciendo |
| Count up (odometro) | 300ms | ease-out | Numeros que cambian |

---

## Orden de implementacion

| Fase | Que | Archivos |
|------|-----|----------|
| 0a | Deuda: Chat collapsible | App.tsx, OrchestratorChat.tsx |
| 0b | Deuda: Creacion manual de nodos | GraphCanvas.tsx |
| 0c | Deuda: console.log → toasts | App.tsx, GraphCanvas.tsx |
| 1 | Design tokens + animaciones | index.css, tailwind.config.js |
| 2 | Transiciones globales CSS | index.css |
| 3 | Fortress: cold_room.py (Ed25519) + runtime_guard.py + integrity.py | security/*.py |
| 4 | Fortress: config + LicenseGuard integracion | config.py, license_guard.py |
| 5 | Fortress: endpoints + startup + build script | auth_router.py, main.py, setup_security.py |
| 6 | Fortress: tests completos (~45) | tests/unit/test_cold_room.py, test_runtime_guard.py, test_integrity.py |
| 7 | Login cinematico (boot + state machine + selector) | LoginModal.tsx, login/*.tsx |
| 8 | Cold Room UI panels + hook | ColdRoomActivatePanel.tsx, ColdRoomRenewalPanel.tsx, useColdRoomStatus.ts |
| 9 | Migracion paleta + microanim — layout core | MenuBar, Sidebar, Footer, GraphCanvas |
| 10 | Migracion paleta + microanim — nodos y graph | OrchestratorNode, edges, InspectPanel, PlanOverlayCard |
| 11 | Migracion paleta + microanim — chat y paneles | OrchestratorChat, AgentChat, panels |
| 12 | Migracion paleta + microanim — dashboards | TokenMastery, TrustDashboard, Eval*, Observability |
| 13 | Migracion paleta + microanim — micro componentes | Toast, TrustBadge, Confidence, Skeleton, ThreatLevel |
| 14 | Migracion paleta + microanim — UI base | button, card, input, select, Accordion |
| 15 | AuthGraphBackground nueva paleta | AuthGraphBackground.tsx |
| 16 | Parallax + animaciones login finales | LoginParallaxLayer.tsx |
| 17 | ProfilePanel + CommandPalette + WelcomeScreen | microanim y nueva paleta |
| 18 | Accesibilidad + reduced motion audit | todos los componentes |

---

## Verificacion

1. `pytest tests/unit/test_cold_room.py` — todos pasan (Ed25519 signature flow)
2. `pytest tests/unit/test_runtime_guard.py` — todos pasan
3. `pytest tests/unit/test_integrity.py` — todos pasan
4. `pytest tests/` — suite completa sin regresiones
5. Arranque normal con `ORCH_LICENSE_KEY` — funciona como antes
6. `ORCH_COLD_ROOM_ENABLED=true` — modo limitado, endpoints accesibles
7. Cold Room activate con blob firmado → licencia valida
8. Cold Room activate con blob falsificado → rechazo con error claro
9. Cold Room activate con blob de otra maquina → rechazo machine_mismatch
10. Tampering de license_guard.py → integrity check falla al startup
11. Login boot sequence < 2s, transiciona a selector
12. Google SSO sigue funcionando identico
13. Cold Room visible solo si enabled
14. Nueva paleta consistente en TODOS los componentes (no quedan hex hardcoded de paleta vieja)
15. `prefers-reduced-motion` — sin animaciones complejas
16. Navegacion teclado Tab/Enter funcional en todo el flujo
17. Contraste WCAG AA en nueva paleta (text-primary sobre surface-0 >7:1)
18. RuntimeGuard no bloquea en desarrollo (`DEBUG=true`)
19. VM detection reporta pero no bloquea (politica configurable)
