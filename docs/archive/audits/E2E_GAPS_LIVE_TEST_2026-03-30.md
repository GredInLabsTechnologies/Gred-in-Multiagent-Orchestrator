# E2E Live Test Gaps - Calculadora Real 2026-03-30

**Test Scenario**: Crear calculadora desde cero usando GIMO CLI + múltiples agentes Haiku 4.5
**Repo Test**: ~/gimo-prueba (dummy repo)
**Objetivo**: Calculadora ejecutable con UI

---

## Gaps Detectados en Prueba en Vivo

### GAP #12: `gimo plan` timeout - CLI timeout demasiado corto

**Severidad**: 🔴 CRÍTICO
**Test**: `gimo plan "Crea una calculadora..."`
**Error**: `Server unreachable at http://127.0.0.1:9325 - Error: timed out`

**CAUSA RAÍZ CONFIRMADA**:
✅ El endpoint `/ops/generate-plan` SÍ funciona correctamente
✅ Tarda ~32 segundos en generar un plan simple
❌ El CLI tiene timeout de 30 segundos configurado en .gimo/config.yaml
❌ La generación supera el timeout y se corta la conexión

**Evidencia**:
```bash
# Test directo con curl (timeout 120s) → FUNCIONA ✅
$ curl -X POST "http://127.0.0.1:9325/ops/generate-plan?prompt=..." \
  -H "Authorization: Bearer TOKEN" \
  --max-time 120
# → HTTP 201, plan generado exitosamente en ~32 segundos

# Timeout actual del CLI:
$ cat .gimo/config.yaml
api:
  timeout_seconds: 30.0  # ← AQUÍ ESTÁ EL PROBLEMA
```

**Fix Necesario**:
```yaml
# .gimo/config.yaml
api:
  timeout_seconds: 180.0  # ← Aumentar a 3 minutos para generación de planes
```

**Impacto**:
- 🔴 **BLOQUEANTE TOTAL** para flujo E2E
- Cualquier plan que tarde >30s falla
- El feature principal de GIMO no funciona desde CLI con prompts complejos
- Planes simples PUEDEN funcionar si se generan en <30s

---

### GAP #13: Confirmación interactiva bloquea automation

**Severidad**: 🟡 P1
**Test**: `gimo plan "..."`
**Error**: `Proceed? [Y/n]:` bloquea el flujo

**Problema**:
- `gimo plan` pide confirmación interactiva
- Intenté `echo "y" | gimo plan` pero falló en el auth antes
- No hay flag `--yes` o `-y` obvio en la ayuda

**Impacto**:
- ⚠️ Dificulta scripting y automation
- ⚠️ Tests automatizados no pueden usar `gimo plan` fácilmente

**Fix Recomendado**:
```python
@plan_app.command("plan")
def plan(
    prompt: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve without confirmation"),
    ...
):
    if not yes:
        proceed = typer.confirm("Proceed?")
        ...
```

---

### OBSERVACIÓN #3: No hay helper para obtener token desde UI

**Severidad**: ℹ️ UX
**Contexto**: Para usar CLI necesito token, pero no hay manera fácil de obtenerlo desde la UI

**Impacto**: ⚠️ Fricción de onboarding para nuevos usuarios

**Recomendación**: Agregar botón "Copy CLI Token" en UI settings

---

## Test Flow Ejecutado (Incompleto)

```bash
# 1. Setup repo ✅
mkdir ~/gimo-prueba
cd ~/gimo-prueba && git init
git commit -m "Initial commit"

# 2. Init GIMO ✅
python /path/to/gimo.py init
# → .gimo/ creado, config.yaml generado

# 3. Configurar modelo ✅
# Editado .gimo/config.yaml: preferred_model → claude-haiku-4-5-20251001

# 4. Crear plan ❌ BLOQUEADO
export ORCH_OPERATOR_TOKEN="..."
gimo plan "Crea una calculadora..."
# → Error: Server unreachable (timeout)

# 5. Run plan (NO EJECUTADO - bloqueado por #4)
# 6. Verificar código generado (NO EJECUTADO)
# 7. Ejecutar calculadora (NO EJECUTADO)
```

**Status**: ❌ **BLOQUEADO EN PASO 4/7** por GAP #12

---

## Métricas de Esta Prueba

| Métrica | Valor |
|---------|-------|
| Steps completados | 3/7 (43%) |
| Gaps críticos nuevos | 1 (GAP #12) |
| Gaps P1 nuevos | 1 (GAP #13) |
| Observaciones UX | 1 |
| Tiempo invertido | ~5 min |
| **E2E Bloqueado** | ✅ SÍ |

---

## Action Items Inmediatos

### P0 — URGENTE
- [ ] **Investigar GAP #12**: ¿Por qué `gimo plan` da timeout si servidor responde?
  - Revisar logs del servidor durante request
  - Verificar endpoint `/ops/plans/create` existe
  - Ver stack trace completo del timeout
  - Probar con curl directo al endpoint

### P1 — Alta Prioridad
- [ ] **GAP #13**: Agregar flag `--yes` a `gimo plan`
- [ ] **Investigar auth flow**: ¿ServerBond se está usando? ¿O env var?

---

## Conclusión Provisional

**VEREDICTO**: ❌ **E2E NO FUNCIONA** - bloqueado por GAP #12 crítico

El flujo de "crear plan → ejecutar run → obtener código" está COMPLETAMENTE ROTO en el estado actual. No es posible usar GIMO CLI para su propósito principal (crear planes y ejecutarlos).

**Prioridad**: GAP #12 debe ser P0 urgente antes de cualquier release.

---

**Timestamp**: 2026-03-30T07:40:00Z
**Tester**: Claude Opus 4.6
**Status**: Prueba E2E suspendida - esperando fix de GAP #12
