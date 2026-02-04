# Handover: Ejecución y Análisis Adversarial — Qwen vs Gred Orchestrator

**Fecha**: 2026-02-04
**Preparado por**: Claude Sonnet 4.5
**Estado**: Suite lista, 24 tests, 0 warnings. Pendiente ejecución con LM Studio + Qwen.

---

## MISIÓN

1. Verificar que LM Studio corre con Qwen
2. Ejecutar los 24 tests adversariales
3. Analizar los reportes JSON generados
4. Identificar cada fallo, clasificarlo, y documentar exactamente qué código necesita fix y dónde
5. Reportar resultados

---

## PASO 1 — VERIFICAR LM STUDIO + QWEN

```bash
# Verificar que el servidor responde
curl -s http://localhost:1234/v1/models

# Verificar desde Python (mismo entorno que los tests)
cd c:\Users\shilo\Documents\Github\gred_orchestrator
python -c "
from tests.llm.lm_studio_client import is_lm_studio_available
print('LM Studio disponible:', is_lm_studio_available())
"
```

Si no responde: abrir LM Studio, cargar Qwen 3 8B, iniciar el servidor local en puerto 1234.
Si los tests hacen `skip` masivo: esto es la causa. No hay datos sin LM Studio.

---

## PASO 2 — EJECUTAR LA SUITE

```bash
cd c:\Users\shilo\Documents\Github\gred_orchestrator

# Ejecución completa
pytest tests/adversarial/test_exhaustive_adversarial.py -v --tb=long -s 2>&1 | tee logs/adversarial_run.txt
```

Por categoría si necesitas re-ejecutar algo específico:

```bash
pytest tests/adversarial/test_exhaustive_adversarial.py::TestPathTraversalExhaustive -v -s
pytest tests/adversarial/test_exhaustive_adversarial.py::TestAuthBypassExhaustive -v -s
pytest tests/adversarial/test_exhaustive_adversarial.py::TestInjectionExhaustive -v -s
pytest tests/adversarial/test_exhaustive_adversarial.py::TestSpecialCharsExhaustive -v -s
pytest tests/adversarial/test_exhaustive_adversarial.py::TestRateLimitBypass -v -s
pytest tests/adversarial/test_exhaustive_adversarial.py::TestPanicEvasion -v -s
```

---

## PASO 3 — LEER LOS REPORTES

Tres fuentes de datos, en orden de utilidad:

### A) Reporte detallado (el principal)

`tests/metrics/adversarial_exhaustive_<YYYYMMDD_HHMMSS>.json`

```json
{
    "total_tests": 0,
    "panic_count": 0,
    "bypass_count": 0,
    "avg_latency_ms": 0.0,
    "duration_sec": 0.0,
    "results": [
        {
            "suite": "path_traversal_basic",
            "target_endpoint": "/file",
            "payload": "../../etc/passwd",
            "status_code": 403,
            "latency_ms": 2.5,
            "panic_triggered": false,
            "bypassed": false,
            "timestamp": 1706000000.0
        }
    ]
}
```

**Campo clave**: `bypassed`. Si es `true` en cualquier resultado → seguridad comprometida.

### B) Resumen

`tests/metrics/adversarial_summary_latest.json`

```json
{
    "timestamp": "20260204_120000",
    "total_tests": 0,
    "bypasses": 0,
    "panics": 0,
    "categories_tested": []
}
```

### C) Log de debug de Qwen (qué generó exactamente)

`logs/llm_debug.log` — cada llamada a Qwen logueada con prompt y respuesta raw.

---

## PASO 4 — ANÁLISIS: INTERPRETAR CADA RESULTADO

### Respuestas HTTP esperadas por categoría

| Categoría | Endpoint | Respuesta CORRECTA | Respuesta que indica FALLO |
|-----------|----------|--------------------|-----------------------------|
| Path Traversal | `/file` | 400, 403, 404 | 200 + contenido de `passwd`, `SAM`, `system32`, `[extensions]` |
| Auth Bypass | `/status` | 401 (o 503 si panic activo) | 200 con cualquier token no válido |
| Injection | `/file` | 400, 403, 404 | 200 + `uid=`, `gid=`, `volume serial`, `syntax error`, `49` |
| Special Chars | `/file` | 400, 403, 404 | 200 (bypass) o 500 (crash — también es fallo) |
| Rate Limit Bypass | `/status` | 429 tras 100 req | 200 tras 100+ requests con headers spoofed |
| Panic Evasion | `/status` | 503 durante lockdown | 200 con token no válido durante panic |

### Comportamientos NORMALES (no son fallos)

- **401** en auth bypass → validación de token funciona
- **403** en path traversal → path validation funciona
- **503** tras 5 tokens inválidos → panic mode se activó correctamente
- **429** tras 100 requests → rate limit funciona
- Algunos payloads de auth generan **503** al final del batch → dentro de un mismo vector, tras 5 tokens inválidos el panic se activa y el resto recibe 503 del middleware. Es correcto: el sistema entró en lockdown.

### Comportamientos que SON fallos

- `bypassed: true` en cualquier resultado → **CRÍTICO**
- `status_code: 500` en Special Chars → el app crashea con input malicioso
- `status_code: 200` en Rate Limit Bypass tras exhaustar el límite → rate limiting no funciona
- `status_code: 200` en Panic Evasion con token inválido → lockdown comprometido
- 0 payloads generados por Qwen en algún vector → re-ejecutar ese vector

---

## PASO 5 — MAPA DE FIXES (ubicación exacta de código por fallo)

### Si Path Traversal falla (bypass en `/file`)

**Primera línea de defensa**: `tools/repo_orchestrator/security/validation.py`

- `_normalize_path()` — línea 35. Es el gatekeeper.
  - Línea 40: bloquea null bytes (`\0`)
  - Líneas 44-76: bloquea Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
  - Línea 78-82: resuelve path relativo contra `base_dir`
  - Líneas 84-90: verifica que el path resuelto está dentro de `base_dir` con `.relative_to()`. **Si un payload escapa esto → el archivo se lee fuera del sandbox.**

- `validate_path()` — línea 98. Wrapper que convierte `None` en HTTP 403.

**Segunda línea**: `tools/repo_orchestrator/routes.py`

- `get_file_handler()` — línea 300. Llama a `validate_path()`, luego `.is_file()`, luego `.stat().st_size`.

**Qué buscar en el payload que escapó**: encodings que `Path()` en Windows no normaliza antes de `.resolve()`. Por ejemplo, overlong UTF-8 o secuencias que el OS interpreta diferente que Python.

---

### Si Auth Bypass falla (200 con token inválido)

**Archivo**: `tools/repo_orchestrator/security/auth.py`

- `verify_token()` — línea 23. Flujo:
  1. Línea 26: si `credentials` es None → 401
  2. Línea 30: `.strip()` al token
  3. Línea 35: si `len(token) < 16` → 401
  4. Línea 40: si `token not in TOKENS` → 401 + activa panic

- `TOKENS` es un `set` con dos tokens: el principal y el de actions. Viene de `config.py`.

**Possible gap**: el middleware `panic_mode_check_middleware` (`middlewares.py` línea 20) parsea Bearer manualmente con `auth_header[7:].strip()`. Si este parsing acepta algo que `verify_token` también acepta pero que no debería estar en TOKENS, hay gap.

**Qué buscar**: tokens que contienen caracteres que `.strip()` no elimina pero que el sistema interpreta como válidos.

---

### Si Injection falla (output de comandos en respuesta)

**Archivo**: `tools/repo_orchestrator/services/file_service.py`

- `get_file_content()` — línea 22. El path ya pasó por `validate_path()`, así que si hay injection es porque el path escapó la validación (ver sección Path Traversal arriba).

**Archivo**: `tools/repo_orchestrator/services/git_service.py`

- Si hay llamadas a subprocess con input derivado de parámetros del usuario → command injection. Revisar si `base` o `head` del endpoint `/diff` se pasan directamente a git sin sanitizar.

**Qué buscar**: `subprocess.run()` o `Popen` con `shell=True` y variables no escapadas.

---

### Si Rate Limit Bypass falla (200 tras 100+ req)

**Archivo**: `tools/repo_orchestrator/security/rate_limit.py`

- `check_rate_limit()` — línea 29. Usa `request.client.host` como clave de IP.
- El límite es `RATE_LIMIT_PER_MIN = 100` (en `config.py` línea 135).

**Qué buscar**: si algún middleware upstream reescribe `request.client` basándose en headers como `X-Forwarded-For` o `X-Real-IP`. Si eso pasa, el attacker puede rotar IPs via headers.

---

### Si Panic Evasion falla (200 durante lockdown)

**Archivo**: `tools/repo_orchestrator/middlewares.py`

- `panic_mode_check_middleware()` — líneas 20-46. Cuando `panic_mode` es True:
  - Si el token está en `TOKENS` → la request pasa (operadores legítimos siguen trabajando)
  - Si no → 503

**Qué buscar**: un token que no está en `TOKENS` pero que el middleware acepta por algún parsing quirk. O un endpoint que no pasa por el middleware.

---

## PASO 6 — REPORTE FINAL

El reporte debe incluir:

1. **Estado general**: PASS (0 bypasses) o FAIL (N bypasses)
2. **Cobertura**: cuántos payloads testeados, cuántos generó Qwen vs cuántos fueron skipped
3. **Fallos detallados** (por cada bypass):
   - Payload exacto (copiado del JSON)
   - Endpoint afectado
   - Status code recibido
   - Categoría del ataque
   - Análisis de qué mecanismo de seguridad se eludió
   - Ubicación del código que falla (archivo + línea)
   - Recomendación de fix específica
4. **Observaciones adicionales**: comportamientos sospechosos que no son bypasses pero merecen atención (latencias altas, 500s, patrones raro)

---

## REFERENCIA — ARQUITECTURA DE SEGURIDAD (flujo de una request)

```
Request entrante
  │
  ▼
panic_catcher_middleware          → captura exceptions no-HTTP, activa panic tras 3 en 60s
  │
  ▼
correlation_id_middleware         → asigna X-Correlation-ID, loguea timing
  │
  ▼
allow_options_preflight_middleware → resuelve CORS OPTIONS
  │
  ▼
panic_mode_check_middleware       → si panic=true y token no en TOKENS → 503
  │                                  si panic=true y token válido → pasa
  │                                  si panic=false → pasa
  ▼
Route Handler
  ├── Depends(verify_token)       → Bearer parse, strip, min 16 chars, in TOKENS
  │     └── si falla → _trigger_panic_for_invalid_token() → incrementa contador
  ├── Depends(check_rate_limit)   → 100 req/60s por request.client.host
  └── validate_path(path, base_dir)
        ├── null bytes → None → 403
        ├── reserved names → None → 403
        ├── resolve() + relative_to(base_dir) → si escapa → None → 403
        └── retorna Path resuelto dentro del sandbox
              │
              ▼
            FileService.get_file_content()
              ├── SnapshotService.create_snapshot() → copia del archivo
              ├── slice lines (start_line..end_line, max 500)
              ├── redact_sensitive_data() → oculta tokens, keys
              └── audit_log() → escribe en logs/orchestrator_audit.log
```

### Valores clave en tests

| Parámetro | Valor |
|-----------|-------|
| ORCH_TOKEN (test) | `test-token-a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0` |
| Panic threshold | 5 tokens inválidos en 60s |
| Rate limit | 100 req / 60s por IP |
| Token mínimo | 16 caracteres |
| LM Studio | `http://localhost:1234/v1` |
| Modelo | `qwen/qwen3-8b` |
| Temperatura | 0.1 |

### Archivos clave del proyecto

| Rol | Archivo |
|-----|---------|
| App entry | `tools/repo_orchestrator/main.py` |
| Configuración | `tools/repo_orchestrator/config.py` |
| Rutas API | `tools/repo_orchestrator/routes.py` |
| Middlewares | `tools/repo_orchestrator/middlewares.py` |
| Auth + Panic | `tools/repo_orchestrator/security/auth.py` |
| Path validation | `tools/repo_orchestrator/security/validation.py` |
| Rate limiting | `tools/repo_orchestrator/security/rate_limit.py` |
| Audit + Redacción | `tools/repo_orchestrator/security/audit.py` |
| Cliente Qwen | `tests/llm/lm_studio_client.py` |
| Prompts adversariales | `tests/adversarial/prompts_exhaustive.py` |
| Suite de tests | `tests/adversarial/test_exhaustive_adversarial.py` |
| Métricas collector | `tests/metrics/runtime_metrics.py` |
| Fixtures pytest | `tests/conftest.py` |
