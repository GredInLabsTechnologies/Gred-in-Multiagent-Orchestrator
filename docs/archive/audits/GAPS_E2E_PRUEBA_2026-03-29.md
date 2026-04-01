# Informe de Gaps E2E - GIMO Prueba de Calculadora
**Fecha**: 2026-03-29
**Objetivo**: Validar flujo E2E de GIMO creando una calculadora en repositorio "gimo-prueba"
**Estado**: ❌ **BLOQUEADO** - No se pudo completar la prueba por problemas críticos de arquitectura

---

## 🔴 Gaps Críticos (Bloquean E2E)

### GAP #1: CLI asume ejecución desde repo del servidor
**Severidad**: 🔴 CRÍTICA
**Impacto**: El CLI no puede usarse desde repositorios externos

**Descripción**:
- `_project_root()` en `gimo.py:53-58` usa `git rev-parse --show-toplevel`
- Esto devuelve la raíz del repositorio git actual
- Cuando el CLI se ejecuta desde `gimo-prueba`, busca credenciales en `gimo-prueba/tools/gimo_server/.gimo_credentials`
- Las credenciales están en `gred_in_multiagent_orchestrator/tools/gimo_server/.gimo_credentials`

**Evidencia**:
```bash
# Desde gimo-prueba
$ python ../gred_in_multiagent_orchestrator/gimo.py status
Failed to fetch authoritative status (401): Token missing
```

**Root Cause**:
```python
# gimo.py:180
unified_creds = _project_root() / "tools" / "gimo_server" / ".gimo_credentials"
```

**Solución Propuesta**:
1. **Opción A**: Instalar CLI globalmente con ruta fija al servidor GIMO
2. **Opción B**: Agregar parámetro `--server-path` o variable de entorno `GIMO_SERVER_PATH`
3. **Opción C**: El CLI debe leer la ubicación del servidor desde `.gimo/config.yaml:api.base_url` y solicitar credenciales al usuario la primera vez

---

### GAP #2: Servidor no lee `.gimo_credentials` unificado
**Severidad**: 🔴 CRÍTICA
**Impacto**: Inconsistencia entre migración y carga de tokens

**Descripción**:
- `_migrate_to_unified_credentials()` crea `.gimo_credentials` con formato YAML
- `_build_settings()` en `config.py:332-335` sigue leyendo archivos legacy:
  - `.orch_token`
  - `.orch_operator_token`
  - `.orch_actions_token`
- El servidor carga tokens de archivos legacy, ignora el archivo unificado

**Evidencia**:
```python
# config.py:332-335
main_token = _load_or_create_token(orch_token_file, "ORCH_TOKEN")
actions_token = _load_or_create_token(actions_token_file, "ORCH_ACTIONS_TOKEN")
operator_token = _load_or_create_token(operator_token_file, "ORCH_OPERATOR_TOKEN")
tokens = {main_token, actions_token, operator_token}
```

**Root Cause**:
- Código de migración existe pero el servidor no fue actualizado para leer del nuevo formato
- Esto sugiere que la migración fue planificada pero no completada

**Solución Propuesta**:
1. Actualizar `_build_settings()` para leer de `.gimo_credentials` primero
2. Caer de regreso a archivos legacy solo si `.gimo_credentials` no existe
3. Agregar warning de deprecación cuando se usen archivos legacy

---

### GAP #3: Tokens inválidos después de modificación
**Severidad**: 🟡 ALTA
**Impacto**: Servidor requiere reinicio para reconocer cambios en tokens

**Descripción**:
- Token admin modificado a las 13:14 (`stat .orch_token`)
- Servidor devuelve "Invalid token" para token correcto
- Servidor necesita reinicio para recargar configuración

**Evidencia**:
```bash
$ TOKEN=$(cat tools/gimo_server/.orch_token)
$ curl -H "Authorization: Bearer $TOKEN" http://localhost:9325/status
{"detail":"Invalid token"}
```

**Root Cause**:
- `Settings` es un `@dataclass(frozen=True)` cargado en `main.py` al inicio
- Cambios en archivos de tokens no se reflejan en tiempo de ejecución

**Solución Propuesta**:
1. Implementar recarga de tokens en caliente (watch de archivos)
2. Agregar endpoint administrativo `/ops/admin/reload-config`
3. Documentar claramente que cambios en tokens requieren reinicio

---

## 🟡 Fricción UX (Dificultan uso sin bloquearlo)

### FRICCIÓN #1: `gimo init` no configura autenticación
**Severidad**: 🟡 ALTA
**Impacto**: Usuario debe configurar tokens manualmente

**Descripción**:
- `gimo init` crea estructura `.gimo/` pero no configura credenciales
- Usuario necesita saber:
  1. Dónde están los tokens del servidor
  2. Cómo copiarlos al workspace (no aplica, ver GAP #1)
  3. Qué rol usar (admin/operator/actions)

**Experiencia actual**:
```bash
$ python gimo.py init
# ✓ Workspace initialized
$ python gimo.py status
# ✗ Failed to fetch authoritative status (401): Token missing
```

**Solución Propuesta**:
1. `gimo init` debe pedir URL del servidor y token interactivamente
2. Guardar credenciales en `.gimo/.credentials` (local al workspace)
3. Alternativa: `gimo login` como comando separado

---

### FRICCIÓN #2: Endpoint `/ops/operator/status` devuelve 500
**Severidad**: 🟡 MEDIA
**Impacto**: CLI `status` falla incluso con token válido

**Descripción**:
- Endpoint `/ops/operator/status` existe pero devuelve error 500
- Error observado en logs del servidor:
```
INFO: 127.0.0.1:59584 - "GET /ops/operator/status HTTP/1.1" 500 Internal Server Error
```

**Contexto**:
- Ruta esperada por CLI basada en logs anteriores
- `/status` requiere token admin (403/401 con operator/actions)
- Falta endpoint específico para role operator

**Solución Propuesta**:
1. Investigar causa de error 500 en `/ops/operator/status`
2. O redirigir a `/status` con autenticación apropiada
3. Documentar qué endpoints usa cada role

---

### FRICCIÓN #3: Confusión entre `/status` y `/ops/status`
**Severidad**: 🟢 BAJA
**Impacto**: Documentación y consistencia de API

**Descripción**:
- `/status` existe en `routes.py:442`
- `/ops/status` devuelve 404 Not Found
- No está claro si los endpoints de status deben estar bajo `/ops/` o raíz

**Según memoria**:
> Route Architecture (P1 2026-03-22)
> - **All endpoints under /ops/**: 27 OPS routers in `routers/ops/`

**Inconsistencia**:
- Status sigue en raíz, no en `/ops/`
- Memoria dice "All endpoints under /ops/" pero `/status`, `/health`, `/me` están en raíz

**Solución Propuesta**:
1. Decidir estrategia: ¿Todo bajo `/ops/` o endpoints core en raíz?
2. Si core en raíz: Documentar excepción en arquitectura
3. Si todo bajo `/ops/`: Migrar `/status` a `/ops/status` con redirect 308

---

## 📊 Resumen de Problemas Encontrados

| Categoría | Cantidad | Críticos |
|-----------|----------|----------|
| Gaps Críticos | 3 | 3 |
| Fricciones UX | 3 | 1 |
| **TOTAL** | **6** | **4** |

---

## 🚫 Funcionalidades NO Probadas

Por los gaps críticos, **NO se pudieron probar**:
- ✗ Crear plan con `gimo plan`
- ✗ Aprobar y ejecutar con `gimo run`
- ✗ Ver diff con `gimo diff`
- ✗ Chat agéntico con `gimo chat`
- ✗ Commit con `gimo commit` (si existe)
- ✗ Observabilidad con `gimo observe`
- ✗ Mastery dashboard con `gimo mastery`
- ✗ Trust engine con `gimo trust`
- ✗ Gestión de providers con `gimo providers`

---

## 🎯 Prioridades para Siguiente Refactor

### P0 - Desbloquear E2E básico
1. ✅ Resolver GAP #1 (CLI portable)
2. ✅ Resolver FRICCIÓN #1 (auth en init)
3. ✅ Verificar funcionamiento de `/ops/operator/status`

### P1 - Consistencia de arquitectura
4. ✅ Resolver GAP #2 (migración completa a `.gimo_credentials`)
5. ✅ Resolver GAP #3 (reload de tokens en caliente)
6. ✅ Resolver FRICCIÓN #3 (estrategia de rutas `/ops/` vs raíz)

### P2 - Mejoras de DX
7. ⬜ Agregar `gimo doctor` para diagnosticar problemas comunes
8. ⬜ Mejorar mensajes de error (incluir hints de solución)
9. ⬜ Agregar tests E2E automatizados para flujo completo

---

## 📝 Notas Adicionales

### Estado del Servidor
- **Proceso**: PID 2188 (cerrado al finalizar prueba)
- **Puerto**: 9325
- **Health**: ✅ Respondía correctamente
- **Auth**: ❌ Tokens no reconocidos

### Archivos Creados Durante la Prueba
```
C:\Users\shilo\Documents\Github\gimo-prueba\
├── .git/                           # ✓ Repositorio inicializado
├── .gimo/
│   ├── config.yaml                 # ✓ Generado por init
│   ├── plans/                      # ✓ Directorio creado
│   ├── history/                    # ✓ Directorio creado
│   ├── runs/                       # ✓ Directorio creado
│   └── .gimo_credentials           # ✗ Creado manualmente (inútil por GAP #1)
```

### Lecciones Aprendidas
1. **CLI y servidor están acoplados**: No hay separación clara entre CLI cliente y servidor
2. **Migración incompleta**: Código de migración existe pero no está activo
3. **Tokens requieren restart**: No hay mecanismo de reload en caliente
4. **Falta documentación de auth**: No hay guía clara de cómo configurar credenciales

---

## ✅ Siguiente Sesión de Refactor

**Objetivo**: Hacer que el CLI funcione desde cualquier repositorio externo

**Tareas**:
1. Modificar `gimo.py` para leer ubicación del servidor de config local
2. Implementar `gimo login` para configurar credenciales
3. Migrar `_build_settings()` para usar `.gimo_credentials`
4. Agregar tests para verificar CLI portable
5. Documentar setup de workspace externo en README

**Criterio de Éxito**:
```bash
# Desde cualquier repositorio
$ git init my-project && cd my-project
$ gimo init
$ gimo login http://localhost:9325 <token>
$ gimo status        # ✅ DEBE FUNCIONAR
$ gimo plan "Create calculator"
$ gimo run
```

---

**Fin del Informe**
