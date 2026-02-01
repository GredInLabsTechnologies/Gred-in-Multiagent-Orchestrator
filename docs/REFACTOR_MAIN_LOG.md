# Refactor de `main.py` — Registro Operativo y de Trazabilidad

**Documento vivo**: Este registro se actualiza en cada fase del refactor.

## 0. Metadatos
- **Proyecto**: Gred Repo Orchestrator
- **Objetivo**: Desacoplar `tools/repo_orchestrator/main.py` sin romper funcionalidad.
- **Estado global**: ✅ F0 completada (baseline verde)
- **Fecha de inicio**: 2026-02-01 01:18 (Europe/Madrid, UTC+1)
- **Responsable**: Cline

---

## 1. Resumen Ejecutivo (cuando, cómo y por qué)
- **Cuándo**: _(fecha/hora exacta por fase)_
- **Cómo**: Refactor incremental con guardrails, sin cambios de comportamiento.
- **Por qué**: Eliminar “god file”, mejorar testabilidad, trazabilidad y mantenibilidad.

---

## 2. Guardrails (no negociables)
1. Compatibilidad total de API (rutas, payloads, códigos).
2. Refactor por fases, cambios pequeños y verificables.
3. Tests de contrato y smoke tests antes y después de cada fase.
4. Correlation ID y logging estructurado para trazabilidad end-to-end.
5. Roll-forward: no se continúa si hay test rojo.
6. **No se borra nada** hasta completar el refactor y validar con tests (source of truth intacto).
7. Al terminar el trabajo, el agente **debe pedir permiso** para:
   - Re-comprobar todo el trabajo (re-test completo).
   - Ejecutar `git commit`.
   - Ejecutar `git push`.

---

## 3. Fases del Refactor (estado por fase)

| Fase | Objetivo | Estado | Fecha | Resultado |
|------|----------|--------|-------|-----------|
| F0 | Baseline y tests de contrato | ✅ Completa | 2026-02-01 | 204 passed |
| F1 | Observabilidad + Correlation ID | ⏳ Pendiente | - | - |
| F2 | App Factory mínima | ⏳ Pendiente | - | - |
| F3 | Extracción por módulos (middlewares/tasks/static) | ⏳ Pendiente | - | - |
| F4 | Configuración modular (settings) | ⏳ Pendiente | - | - |
| F5 | End-to-end test harness | ⏳ Pendiente | - | - |

---

## 4. Detalle por Fase (cuando, cómo, por qué, resultado)

### F0 — Baseline y tests de contrato
- **Qué se hizo**: Ejecución de baseline con `pytest` completo y verificación de exclusión de artefactos de diagnóstico.
- **Cómo se hizo**: Se lanzó `pytest` desde la raíz del repo (Win11). Se intentó la colección inicialmente con errores por `test_diag_2.txt` y `test_failures.txt`. Se confirmó la exclusión vía `pytest.ini` (addopts `--ignore`) y se reejecutó `pytest` con éxito.
- **Por qué se hizo**: Establecer baseline de contrato antes de tocar `main.py` cumpliendo el guardrail de “no avanzar con tests en rojo”.
- **Resultado**: ✅ Baseline verde. `204 passed` (1 warning de deprecación del hook en `tests/conftest.py`).
- **Notas operativas**: Los archivos `test_diag_2.txt` y `test_failures.txt` se mantienen (no borrar). Se confirman como artefactos no-test de diagnóstico y quedan fuera del alcance del refactor. Se mantiene la exclusión en `pytest.ini` para evitar fallos de colección.

### F1 — Observabilidad + Correlation ID
- **Qué se hizo**: _(pendiente)_
- **Cómo se hizo**: _(pendiente)_
- **Por qué se hizo**: _(pendiente)_
- **Resultado**: _(pendiente)_
- **Notas operativas**: _(pendiente)_

### F2 — App Factory mínima
- **Qué se hizo**: _(pendiente)_
- **Cómo se hizo**: _(pendiente)_
- **Por qué se hizo**: _(pendiente)_
- **Resultado**: _(pendiente)_
- **Notas operativas**: _(pendiente)_

### F3 — Extracción por módulos
- **Qué se hizo**: _(pendiente)_
- **Cómo se hizo**: _(pendiente)_
- **Por qué se hizo**: _(pendiente)_
- **Resultado**: _(pendiente)_
- **Notas operativas**: _(pendiente)_

### F4 — Configuración modular (settings)
- **Qué se hizo**: _(pendiente)_
- **Cómo se hizo**: _(pendiente)_
- **Por qué se hizo**: _(pendiente)_
- **Resultado**: _(pendiente)_
- **Notas operativas**: _(pendiente)_

### F5 — End-to-end test harness
- **Qué se hizo**: _(pendiente)_
- **Cómo se hizo**: _(pendiente)_
- **Por qué se hizo**: _(pendiente)_
- **Resultado**: _(pendiente)_
- **Notas operativas**: _(pendiente)_

---

## 5. Validación de Éxito
- **Refactor completado sin roturas**: _(pendiente)_
- **Tests unit + integration verdes**: _(pendiente)_
- **Smoke tests API**: _(pendiente)_
- **Trazabilidad completa (Correlation ID)**: _(pendiente)_

---

## 6. Registro de Cambios (cronología)
- **2026-02-01** — Decisión operativa: **no se borra nada** hasta completar el refactor y validar con tests (source of truth intacto).
- **2026-02-01** — Se adopta **SSoT en `.agent/workflows/`** y **script de sincronización** para Cline/Claude: `scripts/sync-workflows.ps1`.
