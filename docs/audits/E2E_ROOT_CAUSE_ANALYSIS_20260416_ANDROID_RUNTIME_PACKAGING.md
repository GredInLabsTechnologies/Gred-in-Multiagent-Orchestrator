# E2E Root Cause Analysis — Runtime Packaging (hardware-agnóstico)

- **Fecha**: 2026-04-16
- **Ronda**: R1 (ANDROID_RUNTIME_PACKAGING)
- **Rama**: `feature/gimo-mesh`
- **Input Phase 1**: conversación operativa 2026-04-16 (no se escribió audit log separado; el hallazgo emergió mientras intentábamos validar runtime smoke del plan R22 SERVER_MODE_FULL).
- **Input Phase 2 vecino**: [E2E_ENGINEERING_PLAN_20260415_SERVER_MODE_RUNTIMES.md](./E2E_ENGINEERING_PLAN_20260415_SERVER_MODE_RUNTIMES.md) — plan del selector mode×runtime, que explícitamente defiere a "fase 2" la adquisición del runtime (§8.4).

> Aviso de alcance: el usuario pidió explícitamente que esta fase no se limite a Android/S10. GIMO Core debe poder arrancar como server-seed en **cualquier hardware** (desktop, laptop, Raspberry Pi, tablet, nevera conectada). El RCA trata el problema como "runtime packaging multi-plataforma"; el Android APK es el caso más agresivo (assets empaquetados, sin pip), no el único.

---

## 1. Issue map

| ID | Título | Severidad | Superficie principal |
|---|---|---|---|
| PKG-1 | No existe pipeline de empaquetado del runtime Python canónico; el APK asume `assets/runtime/gimo-core-runtime.json` que no se genera en el build | BLOCKER | Android build + backend bootstrap |
| PKG-2 | No existe un origen canónico del Core cuando el device es "seed" (primer nodo de la mesh) — el diseño actual implica descarga desde un "equipo principal" que puede no existir | GAP | Arquitectura mesh |
| PKG-3 | No existe protocolo de sincronización/upgrade del runtime entre peers de la mesh — cada device quedaría atado a la versión empaquetada en su instalador | GAP | Mesh protocol |
| PKG-4 | `ShellEnvironment.prepareEmbeddedCoreRuntime()` (Android) es el único camino para lanzar Core; no hay equivalente en desktop que use empaquetado idéntico — dos caminos para el mismo rol | INCONSISTENCY | Multi-plataforma |

PKG-1/2/3/4 comparten raíz: **la definición operacional de "GIMO Core como server mode" existe sólo en docs y en el selector UI; el artefacto físico que lo ejecuta no tiene productor canónico**.

---

## 2. Traces por issue

### PKG-1 — No hay pipeline de empaquetado del runtime

**Síntoma reportado**: al intentar smoke de R22 S10, el APK instalado en el device no contenía rev 2 (Cambios 1–11). Reconstruir el APK no resuelve el problema: el runtime Python que el APK supuestamente empaquetaría tampoco tiene productor.

**Entry point**: [apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/ShellEnvironment.kt:195-204](apps/android/gimomesh/app/src/main/java/com/gredinlabs/gimomesh/service/ShellEnvironment.kt:195) — `readRuntimeManifest()` abre `assets/runtime/gimo-core-runtime.json`.

**Trace**:
- `ShellEnvironment.prepareEmbeddedCoreRuntime()` — copia archivos listados en `manifest.files` desde `assets/runtime/*` a `context.filesDir/runtime/*`.
- `ShellEnvironment.readRuntimeManifest()` — deserializa `EmbeddedCoreRuntimeManifest { files, python_rel_path, repo_root_rel_path, python_path_entries, extra_env }`.
- `EmbeddedCoreRunner.start()` — lanza `ProcessBuilder(runtime.pythonBinary.absolutePath, "-m", "uvicorn", "tools.gimo_server.main:app", ...)` — requiere que `pythonBinary` exista y ejecute.
- **El archivo `assets/runtime/gimo-core-runtime.json` no existe en el repo** (verificado con Glob). No hay script en `scripts/` que lo produzca. No hay gradle task, no hay CI job, no hay documentación del formato más allá de la deserialización Kotlin.
- Resultado: el APK se construye sin el manifest → `prepareEmbeddedCoreRuntime()` devuelve `null` → `EmbeddedCoreRunner.start()` loguea *"embedded GIMO Core runtime missing"* → nunca arranca server mode en Android.

**Raíz**: la arquitectura define el contrato (manifest + CPython + wheels + repo_root + env) pero no hay productor. El consumer (Android) está listo desde hace meses.

**Radio de impacto**: bloquea completamente server mode en cualquier dispositivo que no pueda depender de pip/system Python (Android, iOS futuro, distribuciones embebidas). En desktop coincide con "user tiene Python instalado"; ese coincide no es diseño, es suerte.

**Confianza**: HIGH — verificado en código, no hay dobles caminos ocultos.

### PKG-2 — Origen canónico del Core cuando el device es seed

**Síntoma reportado** (user): *"imaginate que un usuario comienza a usar gimo desde su movil y ese movil es gimo core original... de donde se baja el core el?"*

**Entry point**: mismo que PKG-1 — `ShellEnvironment.prepareEmbeddedCoreRuntime()`.

**Trace**:
- `docs/DEV_MESH_ARCHITECTURE.md §2.3 Server Node` + §11.2 Phone-as-Server ya declaran que cualquier device suficientemente capaz puede ser el Core Server canónico de una mesh.
- `E2E_ENGINEERING_PLAN_20260415_SERVER_MODE_RUNTIMES.md §8.4` explícitamente lista *"Descarga on-demand de Python runtime / llama binary (fase 2)"* como follow-up, confirmando que el equipo sabía del gap.
- El asumido "descarga on-demand" falla en el escenario seed: el primer device de una mesh no tiene peer del que bajar. El diseño actual por lo tanto tiene un bootstrap gap no resuelto.

**Raíz**: el diseño asume una red pre-existente que no existe en instalaciones nuevas. Es un "chicken-and-egg": peer discovery requiere runtime; runtime requiere peer.

**Radio de impacto**: bloquea la tesis del producto ("un móvil basta para arrancar una mesh soberana"). Sin esto, GIMO depende de un desktop con Python pre-instalado, lo que convierte el móvil en nodo secundario — invirtiendo la arquitectura declarada.

**Confianza**: HIGH.

### PKG-3 — Protocolo de sincronización de upgrades entre peers

**Síntoma reportado**: una vez que el Core viene bundled en el instalador, el device queda atado a esa versión — pero la mesh evoluciona (rev 2 hoy, rev 3 mañana). Un móvil instalado hace seis meses nunca vería las mejoras si no tiene forma de pedir el runtime nuevo a un peer.

**Entry point**: [tools/gimo_server/services/mesh/mdns_advertiser.py](tools/gimo_server/services/mesh/mdns_advertiser.py) — ya firma TXT record con HMAC sobre `hostname:port:mode:health:load`.

**Trace**:
- mDNS advertiser actualmente incluye `mode`, `health`, `load`. No incluye `runtime_version`.
- `gimo discover` y `/ops/mesh/host` exponen el host actual pero no mecanismo para pedir "dame tu runtime".
- `docs/SECURITY.md` tiene infraestructura Ed25519 + JWT offline + clave pública bundled — reutilizable para firmar payloads del runtime sin crear criptografía nueva.
- No existe endpoint `/ops/mesh/runtime-payload` ni manifest de versiones.

**Raíz**: la mesh transporta cómputo (dispatch) pero no transporta su propio código. Faltan dos piezas: un identificador de versión del runtime en el gossip y un endpoint para servir el payload firmado.

**Radio de impacto**: sin esto, cada upgrade requiere reinstalar el APK/MSI/deb en cada device, perdiendo la propiedad "la mesh se actualiza sola" que hace atractivo el diseño peer-to-peer.

**Confianza**: HIGH.

### PKG-4 — Dos caminos para el mismo rol

**Síntoma reportado**: hoy en desktop, `python -m tools.gimo_server.main --role server` asume que el operador tiene Python + pip + requirements.txt instalados. En Android, `EmbeddedCoreRunner` asume runtime bundled. Dos caminos diferentes para la misma función ("correr Core").

**Entry point**:
- Desktop: `tools/gimo_server/main.py:907-963` (CLI).
- Android: `apps/android/gimomesh/.../EmbeddedCoreRunner.kt:79-96` (ProcessBuilder).

**Trace**:
- Desktop lanza `python -m uvicorn tools.gimo_server.main:app` asumiendo Python en PATH.
- Android lanza `<bundled-cpython> -m uvicorn tools.gimo_server.main:app` desde un runtime tree bajo `filesDir/runtime/`.
- El comando canónico de uvicorn es idéntico; lo que cambia es el **origen del intérprete**.
- Principio del usuario (feedback 2026-04-16): *"no queremos dobles caminos de verdad, no queremos que un mismo sistema funcione de dos formas diferentes"*.

**Raíz**: el desktop no se ha beneficiado del mismo esquema self-contained que ya contempla Android. La asimetría es histórica, no de diseño.

**Radio de impacto**: para convertir GIMO en verdaderamente multi-hardware (Raspberry, Synology NAS, frigorífico, tablet sin dev kit), el desktop debe consumir el mismo bundle autocontenido que el móvil. Hoy no puede.

**Confianza**: HIGH.

---

## 3. Patrones sistémicos

1. **Consumer-sin-productor**: `ShellEnvironment` consume un manifest que nadie produce. Esto es la versión empaquetado del patrón "API documentada sin servidor" — código de lectura sin código de escritura.
2. **Bootstrap asimétrico**: el diseño mesh asume "peer ya existe"; el producto real asume "operador instaló Python". Ninguna asunción soporta el escenario seed.
3. **Crypto infra subutilizada**: Ed25519 + JWT offline + clave pública bundled existe para licencias; podría cubrir firma de runtime payloads con coste cero de arquitectura.
4. **Multi-plataforma desplazado a "Android primero"**: el plan anterior menciona runtimes pero el naming entero orbita sobre móvil, mientras que el Raspberry / tablet / desktop sin Python caen en el mismo gap sin representación explícita.

---

## 4. Riesgos preventivos (para tener en cuenta en Phase 3)

- **Licencias propietarias tentadoras**: Chaquopy (~$1000/año), Termux API. Rechazados por mandato del usuario: *"empaquetado artesanal, aquí todo gratis"*. La alternativa OSS es python-for-android (p4a, licencia MIT/Apache), ampliamente validada por Kivy.
- **Tamaño del APK**: CPython + stdlib + wheels para 5 deps nativos (cryptography, pydantic-core, psutil, lxml si aparece, zeroconf puro) ~ 30–60 MB extra. Aceptable para server mode; puede ser opcional vía variante de build.
- **Firmado de payloads**: NO usar HMAC compartido (el HMAC de mDNS basta para "no MITM del anuncio" pero no para "este binario viene de Gred In Labs"). Ed25519 + clave pública bundled es la opción correcta.
- **Superficie de ataque del upgrade**: un endpoint que sirve binarios ejecutables es un vector crítico. Necesita auth operator + firma Ed25519 verificable + hash SHA-256 en el manifest + validación de versión monótona.
- **ABI matrix**: Android ARM64 + Android ARMv7 (32-bit legacy) + Linux x86_64 + Linux ARM64 (Raspberry Pi 4+) + Windows x86_64 + macOS ARM64. Producto cartesiano ≤ 7 artefactos; manejable.
- **Dependencias con componente nativo**: `cryptography` (Rust + OpenSSL), `pydantic-core` (Rust), `psutil` (C), `nvidia-ml-py` (puro Python pero irrelevante en ARM). p4a tiene recipes para cryptography y psutil; pydantic-core necesita recipe o alternativa.

---

## 5. Orden de fix prioritizado

1. **PKG-1** primero — sin productor no hay nada que sincronizar. Es el bloqueo físico.
2. **PKG-4** en el mismo paso — al diseñar el productor, diseñar un bundle multi-plataforma, no Android-only. Mismo coste, beneficio ×N.
3. **PKG-2** como consecuencia de PKG-1 — en cuanto el instalador trae el runtime, el escenario seed se resuelve.
4. **PKG-3** al final — el sync de upgrades sólo tiene sentido cuando hay bundles versionados circulando. Necesita PKG-1 + PKG-4 cerrados.

---

## 6. Confianza global

HIGH. Todas las trazas están ancladas a código o documentación existente. Ningún paso del RCA depende de comportamiento hipotético.

La única incertidumbre real es la calibración: qué wheels del producto compilan con p4a out-of-the-box y cuáles requieren un recipe custom. Esto se resuelve en el spike ejecutivo de Phase 3, no en esta fase.
