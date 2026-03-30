# E2E Audit Round 2: Gaps Adicionales Detectados
**Fecha**: 2026-03-30
**Test Suite**: Comprehensive (32 tests, 252 endpoints)
**Resultado**: 26 PASS / 6 FAIL

---

## Nuevos Gaps Detectados

### GAP #4: `/health/deep` Requiere Admin (403 con Operator Token)

**Severidad**: 🟡 MEDIA
**Test**: `GET /health/deep`
**Esperado**: 200
**Recibido**: 403 "Operator token cannot access this endpoint"

**Análisis**:
`/health/deep` está marcado como admin-only pero conceptualmente debería ser accesible a operator para diagnostics.

**Causa Raíz**:
Probablemente `/health/deep` NO está en `READ_ONLY_ACTIONS_PATHS` ni en `OPERATOR_EXTRA_PREFIXES`.

**Impacto**:
- ⚠️ `gimo doctor` no puede hacer deep health check
- ⚠️ Operators no pueden diagnosticar issues del servidor

**Recomendación**:
```python
# tools/gimo_server/routes.py
READ_ONLY_ACTIONS_PATHS = {
    "/status",
    "/health",
    "/health/deep",  # ← AÑADIR
    ...
}
```

**Prioridad**: P2 (nice-to-have, no crítico)

---

### GAP #5: `/status` Endpoint Legacy Requiere Admin (403)

**Severidad**: 🟡 MEDIA
**Test**: `GET /status` (root level, NO `/ops/operator/status`)
**Esperado**: 200
**Recibido**: 403 "Operator token cannot access this endpoint"

**Análisis**:
Hay DOS endpoints de status:
- `/status` (legacy) — requiere admin
- `/ops/operator/status` (nuevo) — funciona con operator ✅

El GAP #3 que "arreglamos" fue añadir `/status` a `READ_ONLY_ACTIONS_PATHS`, pero al parecer NO está funcionando.

**Verificación**:
```bash
$ grep -n "READ_ONLY_ACTIONS_PATHS" tools/gimo_server/routes.py
28:READ_ONLY_ACTIONS_PATHS = {
29:    "/file",
...
31:    "/status",       # ← Añadido en GAP #3
32:    "/health",
```

El path ESTÁ en la lista. El problema debe ser otro.

**Causa Probable**:
El middleware de auth verifica ANTES de llegar a `READ_ONLY_ACTIONS_PATHS`. O hay un bug en `require_read_only_access()`.

**Impacto**:
- ⚠️ Endpoint legacy `/status` inaccesible para operator
- ⚠️ Usuarios antiguos que usan `/status` van a tener 403

**Recomendación**:
Investigar por qué `READ_ONLY_ACTIONS_PATHS` no está tomando efecto.

**Prioridad**: P1 (afecta backward compatibility)

---

### GAP #6: `/ops/capabilities` Retorna 404

**Severidad**: 🔴 CRÍTICA
**Test**: `GET /ops/capabilities`
**Esperado**: 200 (es el endpoint que agregamos en implementation!)
**Recibido**: 404 "Not Found"

**Análisis**:
¡Este endpoint ES CRUCIAL para el ServerBond handshake! Lo implementamos en `ops_routes.py` línea ~148.

**Verificación**:
Vimos en test anterior que el endpoint SÍ está registrado:
```bash
$ python -c "from tools.gimo_server.main import app; ..."
Capabilities endpoint: ['/ops/provider/capabilities', '/ops/capabilities']
```

**Teoría**:
El endpoint existe pero quizá:
1. No está siendo mounted correctamente en el router
2. Hay conflicto de rutas
3. Falta dependency injection

**Causa Probable**:
Verificar si `verify_token` dependency está funcionando. El 404 puede ser previo a auth.

**Impacto**:
- 🔴 `gimo login` NO PUEDE negociar capabilities
- 🔴 ServerBond NO puede determinar plan/features
- 🔴 **BLOQUEANTE para producción del feature completo**

**Prioridad**: P0 (CRÍTICO — bloquea ServerBond)

---

### GAP #7: `/ops/context/git-status` Requiere Header `X-Session-ID`

**Severidad**: 🟡 MEDIA
**Test**: `GET /ops/context/git-status`
**Esperado**: 200 o parámetro opcional
**Recibido**: 422 "Field required: X-Session-ID"

**Análisis**:
El endpoint requiere header que no está documentado y no es obvio cómo obtenerlo.

**Impacto**:
- ⚠️ CLI no puede usar `/ops/context/git-status` fácilmente
- ⚠️ Falta documentación de cómo crear sesiones

**Recomendación**:
- Opción 1: Hacer `X-Session-ID` opcional (default a sesión nueva)
- Opción 2: Documentar flujo de creación de sesión

**Prioridad**: P2 (feature-specific, no bloquea core flows)

---

### GAP #8: `gimo status` desde /tmp No Muestra "Authoritative Status"

**Severidad**: 🟡 MEDIA
**Test**: CLI `gimo status` desde `/tmp`
**Esperado**: "Authoritative Status" en output
**Recibido**: "GIMO Status" + mensaje "Workspace not initialized"

**Análisis**:
Cuando no hay proyecto inicializado, `gimo status` muestra mensaje de init en vez de intentar llamar al servidor.

**Código Problemático**:
```python
# gimo.py línea ~1675
config = _load_config(require_project=False)

if not config:  # ← Aquí está el problema
    # Muestra mensaje "not initialized" y return
    return
```

`config` no está vacío (tiene config global), pero el check está mal.

**Impacto**:
- ⚠️ `gimo status` con ServerBond o env token NO funciona si no hay proyecto
- ⚠️ Portabilidad del bond sigue rota para este caso

**Fix Necesario**:
```python
config = _load_config(require_project=False)

# Solo mostrar "not initialized" si NO hay token de ninguna fuente
if not config and not _resolve_token("operator", config):
    # mensaje de init
    return
```

**Prioridad**: P1 (rompe promesa de portabilidad del ServerBond)

---

### GAP #9: `gimo providers auth-status` desde /tmp Requiere Proyecto

**Severidad**: 🟡 MEDIA
**Test**: CLI `gimo providers auth-status` desde `/tmp`
**Esperado**: Tabla de provider status
**Recibido**: "Project not initialized. Run 'gimo init' first."

**Análisis**:
Mismo problema que GAP #8 — el comando `providers auth-status` llama a `_load_config()` sin `require_project=False`.

**Código**:
```python
# gimo.py providers_auth_status
def providers_auth_status() -> None:
    config = _load_config()  # ← require_project=True por default
```

**Impacto**:
- ⚠️ No se puede check provider auth sin proyecto inicializado
- ⚠️ Inconsistente con promesa de ServerBond

**Fix**:
```python
config = _load_config(require_project=False)
```

**Prioridad**: P1 (consistency con otros comandos)

---

## Resumen de Gaps Round 2

| # | Gap | Severidad | Status | Prioridad |
|---|-----|-----------|--------|-----------|
| 4 | `/health/deep` requiere admin | 🟡 MEDIA | NEW | P2 |
| 5 | `/status` legacy requiere admin | 🟡 MEDIA | NEW | P1 |
| 6 | `/ops/capabilities` 404 | 🔴 CRÍTICA | NEW | **P0** |
| 7 | `/ops/context/git-status` requiere X-Session-ID | 🟡 MEDIA | NEW | P2 |
| 8 | `gimo status` desde /tmp no funciona | 🟡 MEDIA | NEW | P1 |
| 9 | `gimo providers auth-status` requiere proyecto | 🟡 MEDIA | NEW | P1 |

---

## Tests Pasados (26/32 = 81%)

✅ Core funcionando:
- `/health` — OK
- `/ops/operator/status` — OK (el correcto)
- `/auth/check` — OK
- `/ops/provider` + `/ops/provider/models` — OK
- `/ops/connectors/*` auth-status — OK
- `/ops/repos` — OK
- `/ops/config` — OK
- `/ops/runs`, `/ops/drafts`, `/ops/approved` — OK
- Token Mastery (4/4 endpoints) — OK
- Observability (3/3 endpoints) — OK
- Skills — OK
- CLI help + doctor — OK
- File tree — OK
- Policy — OK

---

## Acción Inmediata Requerida

### P0 — BLOQUEANTE

**GAP #6**: `/ops/capabilities` 404
- Este endpoint es CRÍTICO para ServerBond
- Sin él, `gimo login` no puede negociar capabilities
- Investigar POR QUÉ retorna 404 cuando SÍ está registrado

### P1 — ALTA PRIORIDAD

**GAP #5**: `/status` legacy no accesible
- Investigar middleware de auth
- Verificar por qué `READ_ONLY_ACTIONS_PATHS` no funciona

**GAP #8**: `gimo status` portability rota
- Fix logic de `if not config`

**GAP #9**: `gimo providers auth-status` requiere proyecto
- Cambiar a `require_project=False`

---

## Próximos Tests Requeridos

1. Test específico de `/ops/capabilities` con curl directo
2. Test de auth middleware para `/status`
3. Test de todos los comandos CLI desde `/tmp` con env token
4. Test de POST endpoints (drafts, runs, etc.)
5. Test de error handling (500, 401, 403, etc.)

---

**Conclusión**: El core funciona (81% pass rate), pero hay **1 gap crítico (P0)** que bloquea el feature completo de ServerBond.
