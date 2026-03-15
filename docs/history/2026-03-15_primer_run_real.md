# 2026-03-15 — El primer día que GIMO funcionó de verdad

## Qué ocurrió

El 15 de marzo de 2026, después de aproximadamente dos meses de desarrollo continuo, GIMO completó su primera prueba end-to-end real. El pipeline completo funcionó de extremo a extremo:

1. Se creó un draft con intención `DOC_UPDATE`
2. El sistema lo evaluó automáticamente como `AUTO_RUN_ELIGIBLE`
3. Se aprobó el draft
4. Se lanzó un run
5. El engine ejecutó el pipeline: `PolicyGate → RiskGate → LlmExecute → FileWrite`
6. GPT-5 (via Codex CLI en modo account) generó el contenido del archivo
7. GIMO escribió `DISENO_CALCULADORA.md` en el repositorio `CALCULADORA PRUEBA` con 9,257 bytes de especificaciones de diseño reales

**Archivo resultante:** `C:/Users/shilo/Documents/GitHub/CALCULADORA PRUEBA/DISENO_CALCULADORA.md`

---

## Bugs corregidos para llegar aquí

Durante las sesiones de validación e2e se identificaron y corrigieron 11 bugs reales. Los primeros 4 fueron corregidos en la sesión anterior (handoff), los 7 restantes en esta sesión:

| # | Archivo | Bug |
|---|---------|-----|
| 1 | `models/core.py` | `UserEconomyConfig` y `AgentProfile` bajo `TYPE_CHECKING` → crash Pydantic en runtime |
| 2 | `mcp_bridge/server.py` | `_active_run_worker` no existía como atributo de módulo |
| 3 | `mcp_bridge/server.py` | Backend HTTP nunca se iniciaba automáticamente |
| 4 | `mcp_bridge/native_tools.py` | Acceso sin `getattr` defensivo a `_active_run_worker` |
| 5 | `engine_service.py` | Composición `file_task` sin etapa LLM → archivo vacío |
| 6 | `engine_service.py` | `execute_run()` no actualizaba status a `done`/`error` al terminar |
| 7 | `engine_service.py` | Prompt del draft no se inyectaba al contexto del pipeline |
| 8 | `provider_service_impl.py` | `economy=None` → crash en `_check_cache` |
| 9 | `providers/cli_account.py` | Prompt con espacios se fragmentaba al hacer `" ".join(cmd)` en Windows |
| 10 | `providers/cli_account.py` | `_parse_codex_jsonl` no manejaba el formato `item.completed` del Codex CLI actual |
| 11 | `engine_service.py` | Prompt de `file_task` pedía "crear archivo" → Codex intentaba escritura agentica propia |

---

## Configuración activa en el momento del hito

- **Provider:** `codex-account` (Codex CLI 0.113.0)
- **Modelo real:** GPT-5 (según respuesta del propio CLI)
- **GIMO API:** `http://127.0.0.1:9325`
- **Composición usada:** `file_task` (PolicyGate → RiskGate → LlmExecute → FileWrite)
- **Intent:** `DOC_UPDATE` → `AUTO_RUN_ELIGIBLE` → riesgo 0.0

---

## Lo que queda por validar

La prueba definitiva: **multi-agente paralelo sobre el repositorio**.

Lanzar varios agentes independientes que trabajen simultáneamente en diferentes zonas del repositorio y entreguen un resultado cohesionado al final. Esto validará:

- Coordinación entre agentes hijo (`child_run_ids`, `awaiting_count`)
- Aislamiento de worktrees por agente
- Merge final de resultados
- Composición `multi_agent` del engine

---

## Nota personal

Dos meses de trabajo continuo. Este archivo documenta el momento en que dejó de ser un sistema en construcción y se convirtió en un sistema que funciona.
