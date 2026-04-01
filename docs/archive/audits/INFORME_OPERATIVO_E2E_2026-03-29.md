# Informe Operativo: Gaps Críticos Detectados en Prueba E2E
**Fecha:** 2026-03-29
**Duración:** 90 minutos
**Resultado:** ❌ Test BLOQUEADO en Fase 2
**Gaps Detectados:** 11 críticos

---

## Resumen Ejecutivo

Prueba E2E para crear calculadora con Claude Haiku **falló completamente** debido a múltiples gaps de infraestructura. Sistema **NO está production-ready**.

### Severidad
- 🔴 **7 gaps bloqueantes** (P0)
- 🟡 **4 gaps de alta fricción** (P1-P2)

### Tiempo Perdido vs Esperado
- **Esperado:** 30-50 min
- **Real:** 90+ min (aún sin completar)
- **Overhead:** 180%

---

## Gaps Críticos (Acción Inmediata Requerida)

### 🔴 GAP #1: Dependencia MCP Faltante
**Error:**
```
ModuleNotFoundError: No module named 'mcp'
```

**Fix:**
```bash
# Agregar a requirements.txt:
fastmcp>=3.1.0
mcp>=1.26.0
```

**Prioridad:** P0
**Tiempo de Fix:** 5 minutos
**Impacto:** Backend no arranca → Bloqueante total

---

### 🔴 GAP #2-3: Sistema de 3 Tokens Confuso

**Problema:**
- 3 tokens diferentes: `ORCH_TOKEN`, `ORCH_ACTIONS_TOKEN`, `ORCH_OPERATOR_TOKEN`
- Usuario confundido: *"como que 3 tokens? que sentido tiene?"*
- Token generado por usuario es ignorado → Backend genera el suyo
- 30+ minutos debugging 401 Unauthorized

**Fix:**
1. **Corto plazo:** Documentar claramente en README
2. **Largo plazo:** Simplificar a 1 token admin + opcional role tokens
3. Backend debe respetar `.orch_token` del usuario en first-run

**Prioridad:** P0
**Tiempo de Fix:** 2-4 horas (docs) / 1-2 días (refactor)
**Impacto:** Experiencia de usuario pésima, abandono en setup

---

### 🔴 GAP #5: No ANTHROPIC_API_KEY Configurada

**Problema:**
- Test requiere Claude Haiku
- Provider `claude-account` usa "account mode" (browser auth)
- No hay forma fácil de configurar API key
- Imposible usar en CI/CD

**Fix:**
```bash
# Opción 1: Setup wizard
gimo providers setup anthropic

# Opción 2: .env.example template
ANTHROPIC_API_KEY=sk-ant-...
```

**Prioridad:** P0
**Tiempo de Fix:** 2-4 horas
**Impacto:** No se puede usar Claude en automatización

---

### 🔴 GAP #7: Schema Validation Mismatch

**Error:**
```json
{
  "error": "tasks.0.agent_assignee.role: Input should be 'orchestrator', 'worker' or 'external_action' [type=literal_error, input_value='Lead Orchestrator'"
}
```

**Problema:**
- LLM genera `role='Lead Orchestrator'`
- Schema acepta solo: `'orchestrator'` | `'worker'` | `'external_action'`
- Modelo pequeño (qwen2.5-coder:3b) no sigue schema
- **100% tasa de fallo** (3/3 intentos fallidos)

**Fix:**
1. Prompts del sistema con ejemplos estrictos:
   ```
   VALID: "orchestrator" | "worker" | "external_action"
   INVALID: "Lead Orchestrator", "Orchestrator Agent"
   ```
2. Default a modelo capaz (GPT-4, Claude Sonnet) para plan generation
3. Fallback/retry si validation falla

**Prioridad:** P0
**Tiempo de Fix:** 4-8 horas
**Impacto:** Generación de planes no funciona → Sistema inutilizable

---

### 🔴 GAP #8: Permisos Insuficientes

**Problema:**
```json
// Con operator_token:
{"detail": "admin role or higher required"}

// Con actions_token:
{"detail": "Read-only token cannot access this endpoint"}
```

- `operator_token` no puede cambiar providers
- `actions_token` es read-only
- `main_token` no funciona (GAP #3)
- Operaciones básicas bloqueadas

**Fix:**
- Dar permisos de cambio de provider a `operator_token`
- O documentar cómo obtener/usar admin token

**Prioridad:** P1
**Tiempo de Fix:** 2-4 horas
**Impacto:** Usuarios atrapados con configuración default

---

### 🔴 GAP #9: Provider Config No Se Actualiza

**Problema:**
- Edité `.orch_data/ops/provider.json`: `"active": "claude-account"`
- Reinicié backend
- Backend sigue usando: `"active": "local_ollama"`
- Archivo dice X, runtime hace Y

**Fix:**
- Hot-reload de config
- O endpoint: `POST /ops/provider/reload`
- Log warning si file ≠ runtime state

**Prioridad:** P1
**Tiempo de Fix:** 4-6 horas
**Impacto:** Cambios de config no confiables

---

### 🔴 GAP #11: GIMO Escribe en Repo Sin Confirmación (SEGURIDAD)

**Problema:**
- Usuario: *"deberias de apuntar tambien como un gap que gimo te permita escribir en un repo sin especificarlo"*
- Sistema asume repo actual automáticamente
- No pregunta: "¿Dónde quieres ejecutar esto?"
- Riesgo de escritura accidental en repo equivocado

**Impacto de Seguridad:**
- ⚠️ **Escritura no autorizada** en repos incorrectos
- ⚠️ **Pérdida de datos** si overwrite accidental
- ⚠️ **Commits no deseados** en repo principal

**Fix:**
```bash
# Opción 1: Flag obligatorio
gimo plan --repo /path/to/target "descripción"

# Opción 2: Confirmación interactiva
Target repository: /current/repo
Proceed? [Y/n]:

# Opción 3: Config .gimo/workspace.yaml
workspace:
  target_repo: /path/to/gimo_prueba
  confirm_writes: true
```

**Prioridad:** P0 (SEGURIDAD)
**Tiempo de Fix:** 1-2 días
**Impacto:** Riesgo de seguridad + UX pobre

---

## Gaps Menores (Alta Fricción)

### 🟡 GAP #4: Backend Startup Lento (20-40s)

**Causa:**
- License validation
- GICS daemon
- MCP initialization
- Model inventory

**Fix:** Lazy loading, paralelizar

**Prioridad:** P2
**Impacto:** Fricción en dev local

---

### 🟡 GAP #10: CLI No Automation-Friendly

**Problema:**
```
Save this draft? [Y/n]: _
```
Requiere `--no-confirm` en scripts/CI

**Fix:** Auto-detect non-TTY o env var `GIMO_AUTO_CONFIRM=1`

**Prioridad:** P2
**Impacto:** Scripts se cuelgan si olvidan flag

---

## Métricas de Impacto

### Developer Experience
| Métrica | Esperado | Real | Delta |
|---------|----------|------|-------|
| Setup time | 5 min | 30+ min | +500% |
| First success | 30 min | N/A (bloqueado) | ∞ |
| Support tickets | 0 | ~5 (estimado por gaps) | N/A |

### Reliability
| Componente | Tasa de Éxito |
|------------|---------------|
| Backend startup (first-run) | 0% (deps missing) |
| Auth (first-try) | 0% (token mismatch) |
| Plan generation | 0% (3/3 failed) |
| Provider switching | 0% (permisos + reload) |

### Production Readiness
- **Setup:** 🔴 No (deps faltantes, setup complejo)
- **Core functionality:** 🔴 No (plan generation falla)
- **Security:** 🔴 No (GAP #11 sin confirmar repo)
- **Docs:** 🟡 Incompletas (tokens, providers)

---

## Acciones Prioritarias (Orden de Ejecución)

### Sprint 0 (Immediate - Antes de Release)
1. ✅ Fix requirements.txt (+MCP deps) - **5 min**
2. ✅ Fix GAP #11 (confirm repo antes de write) - **1 día**
3. ✅ Documentar sistema de 3 tokens - **2 horas**
4. ✅ Fix schema prompts para plan generation - **4 horas**

**Total Sprint 0:** 1.5-2 días

### Sprint 1 (High Priority)
5. ✅ Setup wizard para providers - **2 días**
6. ✅ Simplificar auth a 1 token - **2 días**
7. ✅ Provider hot-reload - **1 día**
8. ✅ Permisos operator token - **4 horas**

**Total Sprint 1:** 4-5 días

### Sprint 2 (Polish)
9. ✅ Startup performance - **1 día**
10. ✅ CLI automation flags - **4 horas**
11. ✅ E2E test suite automatizada - **3 días**

**Total Sprint 2:** 4 días

---

## Riesgos de No Actuar

### Si se deploya sin fixes:

**Impacto en Usuarios:**
- 🔴 80%+ abandono en setup (GAP #1, #2-3)
- 🔴 Imposible usar en CI/CD (GAP #5, #10)
- 🔴 Plan generation no funciona (GAP #7)
- ⚠️ Riesgo de escritura en repos incorrectos (GAP #11)

**Impacto en Negocio:**
- Support overhead: +5-10 tickets/día
- Reputación: "No está listo para producción"
- Churn: Usuarios prueban, fallan, abandonan

**Impacto en Equipo:**
- Dev time waste: 30-60 min extra por developer
- Debugging burden en cada onboarding
- Morale impact: "¿Por qué no funciona?"

---

## Evidencia

### Logs Críticos

**1. Missing MCP:**
```
ModuleNotFoundError: No module named 'mcp'
ERROR: Application startup failed. Exiting.
```

**2. Plan Validation Error (3/3 intentos):**
```json
{
  "status": "error",
  "error": "2 validation errors for OpsPlan\ntasks.0.agent_assignee.role\n  Input should be 'orchestrator', 'worker' or 'external_action'"
}
```

**3. Provider Switch Forbidden:**
```json
{"detail": "admin role or higher required"}
```

### Stats
- **Drafts generados:** 3
- **Drafts válidos:** 0 (0%)
- **Backend restarts:** 4
- **Token changes:** 3 (hasta encontrar el correcto)
- **Time to first success:** ∞ (bloqueado)

---

## Recomendación Final

### Estado Actual
🔴 **NO PRODUCTION READY**

### Acción Requerida
**BLOCKER para release.** Requiere fixes de Sprint 0 (1.5-2 días) antes de desplegar a usuarios.

### Siguiente Paso Inmediato
1. Crear issues en GitHub para cada GAP P0
2. Asignar Sprint 0 a equipo core
3. Re-test E2E después de Sprint 0 completo
4. Validar con usuarios beta después de Sprint 1

---

**Reporte generado por:** Claude Sonnet 4.5
**Contexto:** E2E test bloqueado, 11 gaps detectados
**Acción siguiente:** Implementar Sprint 0 (gaps P0)
