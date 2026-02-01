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
- **Qué se hizo**: Se añadió middleware de Correlation ID y logging de requests en `main.py`, y se ajustó `panic_catcher` para reutilizar el ID de la petición. Se añadió un assert en tests para validar el header `X-Correlation-ID`.
- **Cómo se hizo**: Se incorporó un middleware `correlation_id_middleware` que toma `X-Correlation-ID` o genera UUID, lo guarda en `request.state`, mide duración con `time.perf_counter`, añade el header de respuesta y registra un log estructurado vía `logger.info(..., extra=...)`. En `panic_catcher` se obtiene el correlation ID desde `request.state` con fallback. En `tests/unit/test_main.py` se añadió verificación del header en `test_root_route`.
- **Por qué se hizo**: Para garantizar trazabilidad end-to-end y observabilidad básica sin cambiar comportamiento de rutas, cumpliendo el guardrail de compatibilidad.
- **Resultado**: ✅ Cambios aplicados en `main.py` y `tests/unit/test_main.py`. Tests unitarios relevantes ejecutados: `pytest tests/unit/test_main.py` (8 passed, 1 warning). Se actualizó `tests/integrity_manifest.json` con el hash normalizado (LF) de `main.py` y se validó `pytest tests/test_integrity_deep.py` (3 passed, 1 warning).
- **Notas operativas**: Se mantiene la política de no borrar archivos. Logging usa el logger existente `orchestrator` y no altera payloads ni respuestas. El hash se calculó con normalización CRLF→LF para coherencia cross-platform. Durante el re-test completo apareció un fallo inicial por `tests/integrity_manifest.json` (hash de `main.py` desactualizado) y se corrigió actualizando el manifest. Se usó `pytest tests/test_integrity_deep.py` para validar el fix. Commit/push ejecutados tras permisos explícitos del usuario.

### F2 — App Factory mínima
- **Qué se hizo**: Se introdujo un `create_app()` en `tools/repo_orchestrator/main.py` para construir la instancia de FastAPI y se mantuvo `app = create_app()` para compatibilidad.
- **Cómo se hizo**: Se movió la creación de la app, rutas, middlewares, registro de rutas y montaje de static/SPAs dentro de `create_app()` sin alterar la lógica existente. `lifespan` y tareas de cleanup permanecen intactos y se reutilizan en el factory. Se evitó introducir side-effects adicionales en importación.
- **Por qué se hizo**: Desacoplar la construcción de la aplicación (app factory) para habilitar refactors posteriores y mejorar testabilidad, sin cambiar el comportamiento externo.
- **Resultado**: ✅ App factory mínima implementada; se mantiene compatibilidad con import `app` y el entrypoint `__main__`.
- **Notas operativas**: No se elimina ningún archivo. Se requiere ejecutar tests relevantes y actualizar `tests/integrity_manifest.json` si cambia el hash de `main.py`.

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
