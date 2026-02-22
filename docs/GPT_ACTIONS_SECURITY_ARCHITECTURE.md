# GPT Actions Security Architecture

> **Principio rector:** Actions = proponer, nunca ejecutar.
> La seguridad no nace del prompt: nace de permisos + gates + verificación criptográfica.

## Diagrama de flujo

```
                     ┌───────────────┐
                     │   ChatGPT     │
                     │   Actions     │
                     └──────┬────────┘
                            │ HTTPS 443/TLS
                            │ x-openai-isConsequential: true
                            ▼
┌─────────────────────────────────────────────────────────┐
│              GATEWAY (puerto 9326)                      │
│                                                         │
│  ┌─────────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │ IP Allowlist     │→│ Auth Bearer  │→│ Rate Limit │ │
│  │ (OpenAI CIDRs)  │  │              │  │ 20 req/min │ │
│  └─────────────────┘  └──────────────┘  └────────────┘ │
│                            │                            │
│  ┌─────────────────────────▼──────────────────────────┐ │
│  │              Request Audit Chain                    │ │
│  │  (hash-chained, tamper-evident, append-only)       │ │
│  └─────────────────────────┬──────────────────────────┘ │
│                            │                            │
│  ┌────────────┐     ┌──────▼──────┐                    │
│  │ GET /repo/ │     │ POST /patch │                    │
│  │ manifest   │     │ /propose    │                    │
│  │ file       │     │             │                    │
│  └──────┬─────┘     └──────┬──────┘                    │
│         │                  │                            │
│    Solo archivos      Schema strict                     │
│    del manifest       validation +                      │
│    (read-only)        policy gate                       │
│                            │                            │
│                     ┌──────▼──────┐                     │
│                     │    JAIL     │ ← Solo patches/     │
│                     │ filesystem  │   pueden escribirse  │
│                     └─────────────┘                     │
└─────────────────────────────────────────────────────────┘
                            │
                            │ Patch .json en jail
                            ▼
┌─────────────────────────────────────────────────────────┐
│           VALIDADOR (Fase B — proceso separado)         │
│           Usuario: diferente al gateway                 │
│                                                         │
│  1. Structural Check                                    │
│     - Rutas en allowlist                                │
│     - Sin binarios                                      │
│     - Sin traversal                                     │
│     - Límites de tamaño/hunks                           │
│     - Hard-block: CI/CD, .env, credenciales             │
│                                                         │
│  2. SAST + Secret Scan                                  │
│     - bandit (Python)                                   │
│     - semgrep (multi-lenguaje)                          │
│     - gitleaks (secrets en diff)                        │
│                                                         │
│  3. Dependency Gate                                     │
│     - requirements, package-lock → MANUAL_REQUIRED      │
│                                                         │
│  4. Attestation Ed25519                                 │
│     ┌──────────────────────────────────┐                │
│     │ patch_id, patch_hash(SHA-256),   │                │
│     │ policy_version, checks{},        │                │
│     │ outcome, signature(Ed25519)      │                │
│     └──────────────────────────────────┘                │
│     Clave privada: solo este proceso tiene acceso       │
└──────────────────────┬──────────────────────────────────┘
                       │ Attestation firmada
                       ▼
┌─────────────────────────────────────────────────────────┐
│          INTEGRADOR (Fase C — el humano decide)         │
│                                                         │
│  1. Verificar firma Ed25519 con clave pública           │
│  2. Verificar hash del patch (anti-TOCTOU)              │
│  3. Si outcome = MANUAL_REQUIRED → requiere --confirm   │
│  4. Si outcome = APPROVED → aplicar diff                │
│  5. Crear rama gptactions/patch-XXXXXXXX                │
│  6. Commit con metadatos de attestation                 │
│  7. El humano revisa y hace merge/PR                    │
└─────────────────────────────────────────────────────────┘
```

## Superficie de ataque y mitigaciones

| Vector | Mitigación | Archivo |
|--------|-----------|---------|
| IP spoofing | Allowlist de CIDRs de OpenAI (auto-sync) | `security/ip_allowlist.py` |
| Token robado | Rate limit + audit chain + rotación | `config.py`, `main.py` |
| Path traversal | Jail con 10 checks (null, ADS, .., symlink, depth, reserved, forbidden) | `security/jail.py` |
| Prompt injection | Schema estricto (Pydantic) — no acepta texto libre como instrucciones | `security/patch_schema.py` |
| TOCTOU | SHA-256 del patch en attestation, verificado en integración | `attestation.py`, `integrator.py` |
| Audit tampering | Hash-chain: cada entrada incluye hash de la anterior | `security/chain_audit.py` |
| Privilege escalation | Usuario gimo-actions sin Admin, sin SeDebug, sin SeImpersonate | `setup_gptactions_jail.ps1` |
| Dependency poisoning | Dependency gate: archivos de deps → MANUAL_REQUIRED automático | `structural_checker.py` |
| CI/CD takeover | Hard-block: .github/workflows → rechazado sin posibilidad de override | `structural_checker.py` |
| Secret leak en diff | gitleaks scan obligatorio en Fase B | `sast_runner.py` |
| Attestation forgery | Ed25519 firma + clave privada aislada con ACL | `attestation.py` |
| Symlink/junction escape | os.path.realpath() + verificación post-resolve dentro del jail | `security/jail.py` |
| Quota flooding | MAX_PENDING_PATCHES=5 + TTL 24h + rate limit 5 patches/hora | `jail.py`, `patch_router.py` |
| NTFS ADS | Detección de ':' fuera de drive letters | `security/jail.py` |
| Stale allowlist | BLOCK_ON_STALE_ALLOWLIST=true → 503 si > 12h sin sync | `main.py` |

## Archivos del sistema

```
tools/gptactions_gateway/          # Gateway (Fase A)
├── main.py                        # FastAPI + middlewares
├── config.py                      # Configuración centralizada
├── openapi_gptactions.yaml        # Spec OpenAPI para GPT Actions
├── openai_ips.json                # Allowlist de IPs (auto-generado)
├── security/
│   ├── chain_audit.py             # Audit log con cadena de hashes
│   ├── ip_allowlist.py            # Allowlist de IPs thread-safe
│   ├── jail.py                    # Filesystem jail
│   └── patch_schema.py            # Schema estricto + policy gate
└── routers/
    ├── repo_router.py             # GET /repo/manifest, /repo/file
    └── patch_router.py            # POST /patch/propose, GET /patch/status

tools/patch_validator/             # Validador (Fase B) — FUERA del jail
├── validator.py                   # Orquestador de validación
├── attestation.py                 # Firma/verificación Ed25519
├── structural_checker.py          # Checks estructurales
├── sast_runner.py                 # Integración con bandit/semgrep/gitleaks
└── keys/                          # Claves Ed25519 (ACL estricta)
    ├── attestation_private.pem    # Solo el validador puede leer
    └── attestation_public.pem     # El integrador y el gateway la leen

tools/patch_integrator/            # Integrador (Fase C) — el humano decide
└── integrator.py                  # Verificación + aplicación de diffs

scripts/setup/
├── setup_gptactions_jail.ps1      # Setup de usuario Windows + ACLs
└── sync_openai_ips.py             # Sincronización de IPs de OpenAI

tests/gptactions/
└── test_gateway_security.py       # 30+ tests de vectores de ataque
```

## Setup inicial

```bash
# 1. Crear usuario y jail (requiere admin)
powershell -ExecutionPolicy Bypass scripts/setup/setup_gptactions_jail.ps1

# 2. Generar claves de attestation
python -m tools.patch_validator.attestation --generate-keys

# 3. Asegurar clave privada (solo usuario validador)
icacls tools\patch_validator\keys\attestation_private.pem /inheritance:r
icacls tools\patch_validator\keys\attestation_private.pem /grant:r "%USERNAME%:(R)"

# 4. Sincronizar IPs de OpenAI
python scripts/setup/sync_openai_ips.py

# 5. Crear manifest de archivos legibles
# Edita: <jail_root>/manifest/readable_files.json

# 6. Iniciar gateway
python -m tools.gptactions_gateway.main

# 7. Iniciar validador en modo watch
python -m tools.patch_validator.validator --watch
```

## Checklist de verificación

- [ ] `gimo-actions` solo puede escribir en `<jail>/patches/`
- [ ] `gimo-actions` NO puede leer el repo principal
- [ ] `gimo-actions` NO pertenece a Administrators
- [ ] `gimo-actions` NO tiene SeDebugPrivilege ni SeImpersonatePrivilege
- [ ] IP allowlist actualizado (< 12h)
- [ ] Clave privada de attestation con ACL restringida
- [ ] Gateway corriendo en puerto 9326 (separado del servidor principal 9325)
- [ ] Validador corriendo como usuario diferente al gateway
- [ ] Audit chain verificable: `python -c "from tools.gptactions_gateway.security.chain_audit import ChainedAuditLog; print(ChainedAuditLog('logs/gptactions/gptactions_audit.jsonl').verify_chain())"`
- [ ] Task Scheduler configurado para sync diario de IPs
- [ ] Tests pasando: `pytest tests/gptactions/ -v`
