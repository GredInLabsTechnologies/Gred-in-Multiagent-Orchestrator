# GIMO Product Key System — Plan Maestro
> Fecha: 2026-03-03 | Estado: BORRADOR

## Objetivo
Permitir al owner de GIMO generar **claves de producto** (product keys) que pueda distribuir libremente a cualquier persona. El receptor activa la clave en su instalación de GIMO (app compilada, sin acceso al código fuente), y el sistema valida/revoca licencias de forma segura y anti-piratería.

---

## Estado Actual (lo que ya existe)

| Componente | Archivo | Función |
|---|---|---|
| ColdRoomManager | `security/cold_room.py` | Licencia offline con blobs Ed25519 |
| LicenseGuard | `security/license_guard.py` | Validación híbrida online/offline, JWT cache AES-GCM |
| Fingerprint | `security/fingerprint.py` | 5 señales HW, fuzzy matching 60% |
| Key Generator | `scripts/generate_license_keys.py` | Genera par Ed25519 (signing keys) |

### Problemas del sistema actual
1. **No hay generación de product keys** — solo claves criptográficas de firma
2. **No hay dashboard de admin** para crear/revocar licencias
3. **No hay endpoint en GIMO WEB** (`gimo.giltech.dev`) para validar licencias
4. **Las claves no son portables** — el blob Cold Room está atado a machine_id
5. **No hay planes/tiers** gestionables (pro, enterprise, etc.)
6. **No hay límite de instalaciones** controlable por el owner

---

## Arquitectura Propuesta

```
┌──────────────────────────────────────────────────────────────┐
│                    GIMO WEB (Vercel/Next.js)                 │
│                    gimo.giltech.dev                          │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ Admin Panel  │  │ License API  │  │ Firestore DB       │  │
│  │ /admin/keys  │  │ /api/license │  │ licenses collection│  │
│  │ (owner only) │  │ /validate    │  │ activations coll.  │  │
│  │              │  │ /activate    │  │ revocations coll.  │  │
│  │ • Crear keys │  │ /revoke      │  │                    │  │
│  │ • Revocar    │  │ /status      │  │                    │  │
│  │ • Ver stats  │  │              │  │                    │  │
│  └─────────────┘  └──────┬───────┘  └────────────────────┘  │
│                          │                                   │
└──────────────────────────┼───────────────────────────────────┘
                           │ HTTPS
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                  GIMO Server (Cliente)                        │
│                  App compilada del usuario                    │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐  │
│  │ LicenseGuard │  │ ColdRoomMgr   │  │ Fingerprint      │  │
│  │ (mejorado)   │  │ (mejorado)    │  │ Engine           │  │
│  │              │  │               │  │ (sin cambios)    │  │
│  │ • Startup    │  │ • Air-gapped  │  │                  │  │
│  │ • Periodic   │  │ • Fallback    │  │ • 5 señales HW   │  │
│  │ • Activate   │  │               │  │ • Fuzzy match    │  │
│  └──────────────┘  └───────────────┘  └──────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ .gimo_license (AES-256-GCM, machine-bound)              ││
│  │ Cache local cifrado con fingerprint de la máquina       ││
│  └──────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

---

## Formato de Product Key

```
GIMO-XXXX-XXXX-XXXX-XXXX
```

- 20 caracteres alfanuméricos (base32 limpio, sin 0/O/1/I/L para evitar confusión)
- Prefijo `GIMO-` para identificación visual
- Generado con `secrets.token_bytes(12)` → base32 → split en grupos de 4
- **Checksum**: último grupo incluye 2 chars de verificación (CRC-8 del resto)
- Ejemplo: `GIMO-K7HF-B3WN-QR9D-M2YC`

### Alfabeto seguro (28 chars)
```
ABCDEFGHJKMNPQRSTUVWXYZ234679
```
(Sin: 0, O, 1, I, L, 5/S, 8/B)

---

## Fase 1: Backend — Generación y Validación de Keys

### 1.1 Modelo de datos (Firestore)

```
Collection: licenses
Document ID: <product_key_hash_sha256>

{
  "key_hash": "sha256(GIMO-XXXX-...)",     // nunca guardamos la key en claro
  "key_prefix": "GIMO-K7HF",               // primeros 9 chars para búsqueda visual
  "plan": "pro",                            // "standard" | "pro" | "enterprise" | "lifetime"
  "created_at": Timestamp,
  "created_by": "owner@giltech.dev",        // UID Firebase del creador
  "expires_at": Timestamp | null,           // null = lifetime
  "max_installations": 2,                   // máximo de máquinas simultáneas
  "features": ["code", "reasoning", ...],   // features habilitadas
  "revoked": false,
  "revoked_at": null,
  "revoked_reason": "",
  "notes": "Para cliente X",                // nota privada del owner
  "metadata": {}                            // datos extra
}

Collection: activations
Document ID: auto

{
  "key_hash": "sha256(GIMO-XXXX-...)",
  "machine_fingerprint": "sha256...",
  "machine_label": "Windows 11 - DESKTOP-ABC",
  "activated_at": Timestamp,
  "last_seen": Timestamp,
  "last_validated": Timestamp,
  "ip_address": "x.x.x.x",                // para detección de abuso
  "app_version": "1.0.0",
  "deactivated": false,
  "deactivated_at": null
}

Collection: validation_log  (opcional, auditoría)
Document ID: auto

{
  "key_hash": "...",
  "action": "validate" | "activate" | "revoke" | "deactivate",
  "result": "ok" | "expired" | "revoked" | "max_installs",
  "machine_fingerprint": "...",
  "ip": "...",
  "timestamp": Timestamp
}
```

### 1.2 API Endpoints (GIMO WEB — Next.js API Routes)

| Método | Endpoint | Auth | Descripción |
|--------|----------|------|-------------|
| `POST` | `/api/license/generate` | Owner only (Firebase UID check) | Genera 1-N product keys |
| `POST` | `/api/license/validate` | Product key + fingerprint | Valida key + renueva JWT |
| `POST` | `/api/license/activate` | Product key + fingerprint | Primera activación en máquina |
| `POST` | `/api/license/deactivate` | Product key + fingerprint | Libera slot de instalación |
| `POST` | `/api/license/revoke` | Owner only | Revoca una key inmediatamente |
| `GET`  | `/api/license/status` | Owner only | Lista keys, activaciones, stats |
| `GET`  | `/api/license/info` | Product key | Info pública de la key (plan, expiry) |

### 1.3 Flujo de Activación

```
Usuario recibe key: GIMO-K7HF-B3WN-QR9D-M2YC

1. Abre GIMO → pantalla de activación (primera vez)
2. Introduce la product key
3. GIMO Server →  POST /api/license/activate
   Body: { licenseKey, machineFingerprint, machineLabel, os, hostname, appVersion }
4. GIMO WEB:
   a. Hash de la key → buscar en Firestore
   b. Verificar: no revocada, no expirada
   c. Contar activaciones activas < max_installations
   d. Crear documento en activations
   e. Firmar JWT (Ed25519) con: plan, features, exp, max, fingerprint
   f. Retornar { valid: true, token: "eyJ...", plan: "pro", ... }
5. GIMO Server:
   a. Cachear JWT en .gimo_license (AES-256-GCM + fingerprint)
   b. Arrancar normalmente
   c. Periodic recheck cada 24h
```

### 1.4 Flujo de Validación (recurrente)

```
Cada 24h (o en startup):
1. GIMO Server → POST /api/license/validate
   Body: { licenseKey, machineFingerprint, appVersion }
2. GIMO WEB:
   a. Verificar key vigente y no revocada
   b. Verificar que el fingerprint tiene una activación activa
   c. Actualizar last_seen, last_validated
   d. Firmar nuevo JWT
   e. Retornar { valid: true, token: "eyJ...", ... }
3. Si falla (sin red): usar cache offline (grace period 3-7 días)
4. Si la key fue revocada: JWT expirado, GIMO se bloquea
```

---

## Fase 2: Protecciones Anti-Piratería

### 2.1 Protecciones en el servidor de validación (GIMO WEB)

| Protección | Implementación |
|---|---|
| **Key nunca en claro** | Solo se almacena `SHA-256(key)` en Firestore |
| **Rate limiting** | Max 10 validates/min por IP, 3 activates/hora por key |
| **IP geofencing** | Alertar si misma key se usa desde IPs muy distantes |
| **Fingerprint binding** | Key atada a N máquinas específicas |
| **Revocación instantánea** | Owner revoca → siguiente validate falla |
| **JWT short-lived** | Token expira en 7 días → fuerza revalidación |
| **Nonce anti-replay** | Cada validate incluye nonce único, servidor rechaza repetidos |

### 2.2 Protecciones en el cliente (GIMO Server compilado)

| Protección | Ya existe | Archivo |
|---|---|---|
| **AES-256-GCM cache** | Si | `license_guard.py` |
| **Machine-bound** | Si | `fingerprint.py` |
| **Anti-tamper** (hash propio) | Si | `license_guard.py:_verify_file_integrity` |
| **Clock-tampering detect** | Si | `license_guard.py:_validate_offline` |
| **Fuzzy fingerprint** | Si | `fingerprint.py:compare_fingerprints` |
| **Grace period** | Si | `license_guard.py` (3 días default) |
| **Guard versioning** | Si | `license_guard.py:_GUARD_VERSION` |
| **Cold Room (air-gapped)** | Si | `cold_room.py` |

### 2.3 Protecciones nuevas a añadir

| Protección | Descripción |
|---|---|
| **Heartbeat encriptado** | Beacon cada 4h con estado → detectar clones |
| **Checksum de key en UI** | Validar formato antes de enviar (UX) |
| **Obfuscation del binario** | PyInstaller + PyArmor para el .exe distribuido |
| **Certificate pinning** | TLS pinning a gimo.giltech.dev |
| **Telemetry anti-clone** | Si 2+ máquinas con misma key están online simultáneamente → alert al owner |

---

## Fase 3: Admin Panel (GIMO WEB)

### Página `/admin/keys` (solo accesible por UIDs autorizados)

```
┌─────────────────────────────────────────────────────────────┐
│  GIMO License Manager                          [+ Nueva Key]│
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Resumen                                                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  │ 47 Total │ │ 42 Activ │ │ 3 Expirad│ │ 2 Revoc. │      │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │
│                                                             │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Key          Plan      Installs  Expira      Estado    ││
│  │ GIMO-K7HF   Pro       1/2       2027-03-01  ● Activa  ││
│  │ GIMO-B3WN   Standard  2/2       2026-12-01  ● Activa  ││
│  │ GIMO-QR9D   Lifetime  1/5       Nunca       ● Activa  ││
│  │ GIMO-M2YC   Pro       0/2       2026-06-01  ○ Sin uso ││
│  │ GIMO-F8TK   Standard  0/2       2026-01-15  ✕ Expirad ││
│  └─────────────────────────────────────────────────────────┘│
│                                                             │
│  [Generar Batch]  [Exportar CSV]  [Revocar seleccionadas]  │
└─────────────────────────────────────────────────────────────┘
```

### Modal "Nueva Key"

```
┌─────────────────────────────────────┐
│  Generar Product Key                │
│                                     │
│  Plan:      [Pro           ▼]       │
│  Cantidad:  [1        ]             │
│  Duración:  [12 meses     ▼]       │
│  Max instl: [2        ]             │
│  Features:  [✓] Code  [✓] Vision   │
│             [✓] Reasoning  [ ] API  │
│  Nota:      [________________]      │
│                                     │
│  [Cancelar]  [Generar & Copiar]     │
└─────────────────────────────────────┘
```

---

## Fase 4: UX de Activación en GIMO Server

### Primera ejecución (sin licencia)

```
┌──────────────────────────────────────────────────┐
│                                                  │
│              G I M O                             │
│        Orchestrator Engine                       │
│                                                  │
│   ┌──────────────────────────────────────────┐   │
│   │  Introduce tu Product Key:               │   │
│   │  ┌──────────────────────────────────┐    │   │
│   │  │ GIMO-____-____-____-____        │    │   │
│   │  └──────────────────────────────────┘    │   │
│   │                                          │   │
│   │  [Activar]                               │   │
│   │                                          │   │
│   │  ¿No tienes una key?                    │   │
│   │  → Consíguela en gimo.giltech.dev       │   │
│   └──────────────────────────────────────────┘   │
│                                                  │
└──────────────────────────────────────────────────┘
```

### En la app compilada (.exe / CLI)

El usuario pone la key de dos formas:
1. **Variable de entorno**: `ORCH_LICENSE_KEY=GIMO-K7HF-B3WN-QR9D-M2YC`
2. **Archivo**: `.gimo_product_key` en el directorio de la app
3. **CLI interactivo**: `gimo activate` → pide la key por stdin

La key NUNCA se guarda en claro después de la activación. Se almacena solo el hash + el JWT cifrado.

---

## Fase 5: Implementación — Orden de Trabajo

### Sprint 1 (Backend GIMO WEB)
1. [ ] Crear colecciones Firestore (`licenses`, `activations`, `validation_log`)
2. [ ] Implementar `pages/api/license/generate.ts` — generar keys
3. [ ] Implementar `pages/api/license/activate.ts` — activar en máquina
4. [ ] Implementar `pages/api/license/validate.ts` — validar + renovar JWT
5. [ ] Implementar `pages/api/license/revoke.ts` — revocar key
6. [ ] Implementar `pages/api/license/status.ts` — listar keys (admin)
7. [ ] Rate limiting middleware para license endpoints
8. [ ] Tests unitarios de cada endpoint

### Sprint 2 (Cliente GIMO Server)
1. [ ] Actualizar `LicenseGuard` para aceptar product keys formato `GIMO-XXXX-...`
2. [ ] Añadir validación de checksum en cliente antes de enviar
3. [ ] Nuevo método `activate()` en LicenseGuard (distinto de `validate()`)
4. [ ] CLI command `gimo activate` para activación interactiva
5. [ ] Soporte `.gimo_product_key` file
6. [ ] Tests de integración

### Sprint 3 (Admin Panel)
1. [ ] Página `/admin/keys` con tabla de licencias
2. [ ] Modal de generación de keys
3. [ ] Acciones: revocar, ver activaciones, exportar
4. [ ] Protección: solo UIDs autorizados (Firebase custom claims)
5. [ ] Notificaciones: email/webhook cuando key se activa

### Sprint 4 (Hardening)
1. [ ] Heartbeat anti-clone
2. [ ] Telemetría de uso simultáneo
3. [ ] Certificate pinning a gimo.giltech.dev
4. [ ] Documentación para usuario final
5. [ ] PyArmor integration para build del .exe

---

## Planes de Producto

| Plan | Duración | Max Installs | Features | Precio sugerido |
|---|---|---|---|---|
| `trial` | 14 días | 1 | Básico | Gratis |
| `standard` | 12 meses | 2 | code, chat | — |
| `pro` | 12 meses | 3 | code, chat, reasoning, vision | — |
| `enterprise` | 12 meses | 10 | Todo + API + soporte prioritario | — |
| `lifetime` | Ilimitado | 5 | Todo | — |

---

## Licencia del Owner

Para ti (owner), el sistema genera automáticamente una **master key** con:
- Plan: `lifetime`
- Max installations: `999`
- Expiración: `null` (nunca)
- Features: todas
- Flag especial: `is_owner: true` → bypass de todas las restricciones

Comando para generarla:
```bash
# En GIMO WEB admin panel, o directamente:
curl -X POST https://gimo.giltech.dev/api/license/generate \
  -H "Authorization: Bearer <firebase-token>" \
  -d '{"plan":"lifetime","max_installations":999,"notes":"Owner master key"}'
```

---

## Seguridad — Vectores de Ataque Mitigados

| Ataque | Mitigación |
|---|---|
| Compartir key entre amigos | Límite de instalaciones + fingerprint binding |
| Clonar disco/VM | Fingerprint detecta cambio de hardware |
| Modificar binario para skip check | Anti-tamper hash + PyArmor obfuscation |
| Interceptar JWT | AES-256-GCM en disco, TLS en tránsito |
| Replay de validación | Nonces únicos, JWT short-lived |
| Revocar y seguir usando | Grace period corto (3 días), JWT expira |
| Cambiar reloj del sistema | Clock-tampering detection (iat check) |
| Keygen/cracker | Ed25519 256-bit, no bruteforceable |
| Descompilar para extraer key | Key no está en claro, solo hash + JWT cifrado |

---

## Decisiones Pendientes

1. **¿Dónde empieza?** — ¿Sprint 1 (backend de GIMO WEB) o Sprint 2 (cliente)?
2. **¿Pricing?** — ¿Definir precios ahora o dejarlo para después?
3. **¿Stripe integration?** — ¿Venta automática de keys o solo manual?
4. **¿Trial automático?** — ¿Key de trial al registrarse en la web?
