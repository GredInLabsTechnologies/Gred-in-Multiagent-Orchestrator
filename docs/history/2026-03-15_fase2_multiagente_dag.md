# 2026-03-15 — Fase 2: Orquestación Multi-Agente DAG Completa

## Qué ocurrió

El mismo 15 de marzo de 2026, horas después del primer run real, GIMO completó su segunda prueba e2e: la validación completa de la **orquestación multi-agente con DAG de dependencias**.

Se ejecutó un escenario de 4 agentes en waves, con Claude como orquestador HITL y Codex/GPT-5 ejecutando cada nodo:

```
N1: architect   (Wave 1, sin deps)           → ARQUITECTURA.md       ✓
N2: ui_dev      (Wave 2, dep: N1) ──┐
N3: logic_dev   (Wave 2, dep: N1) ──┤ paralelo  → UI_SPEC.md / LOGIC_SPEC.md  ✓
N4: test_writer (Wave 3, dep: N2+N3)         → TEST_PLAN.md          ✓
```

**Run padre:** `r_1773562167666_2f0937` — estado final `done`

Cada nodo llegó a `awaiting_review`, Claude revisó el output, y dio GO. El padre evolucionó por las transiciones: `running → awaiting_subagents → running → awaiting_subagents → running → awaiting_subagents → running → done` (×3 waves).

---

## Bugs corregidos para llegar aquí (sesión de Fase 2)

| # | Archivo | Bug |
|---|---------|-----|
| 1 | `main.py` | Zombie runs (`running`/`awaiting_subagents`/`awaiting_review`) sobrevivían reinicios del servidor. Fix: startup reconcile que los marca como `error`. |
| 2 | `child_run_service.py` | IDs de hijos con prefijo `run_` no los encontraba el glob `r_*.json`. Fix: cambiar prefijo a `r_`. |
| 3 | `ops_service.py` | `_RUN_GLOB = "r_*.json"` excluía IDs legacy. Fix: cambiar a `*.json`. |
| 4 | `engine_service.py` | Hijos heredaban `wake_on_demand: true` y `child_tasks` del padre → inferían `multi_agent` en lugar de `agent_task`. Fix: strip de esas claves en contexto de hijos. |
| 5 | `engine_service.py` | Worker no transitaba el run a `running` antes de ejecutar pipeline → FSM fallaba en ReviewGate. Fix: `update_run_status("running")` al inicio de `execute_run` si status es `pending`. |
| 6 | `ops_service.py` | FSM guard leía `_load_run_metadata` (base JSON sin eventos) → siempre veía `pending` aunque el estado real (event-sourced) fuera `running`. Además `awaiting_review` no estaba en el FSM. Fix: materializar estado antes del guard + añadir transiciones `awaiting_review`. |

---

## Sistemas validados

| Sistema | Señal | Verificado |
|---------|-------|-----------|
| SpawnAgentsStage waves | `Wave 1/2/3: spawning N child(ren)` en logs | ✓ |
| ACE self-assessment | `[ACE] Strategy: MULTI_PASS, Confidence: 0.526` | ✓ |
| ReviewGate HITL | GO manual vía `POST /action-drafts/{id}/approve` | ✓ |
| Padre re-ejecuta tras wave | `awaiting_subagents → running` (×3) | ✓ |
| CapabilityProfile (GICS) | Registro de outcomes por task_type | ✓ |
| Fractal guardrail | `spawn_depth=1` en todos los hijos | ✓ |
| Startup reconcile | Runs zombie marcados como `error` al reiniciar | ✓ |

---

## Lo que quedó pendiente

- **Generación de código real**: Los 4 agentes generaron especificaciones Markdown excelentes, pero el objetivo final es generar código TypeScript/React funcional.
- **Bug FileWrite con rutas con espacios**: `CALCULADORA PRUEBA` tiene un espacio. El regex `TARGET_FILE:\s*(\S+)` cortaba en el espacio. Fix aplicado en `file_write.py`: cambiado a `.+?(?:\s*\n|$)` + strip de la línea con `[^\n]*`. Fase 2b en curso.
- **Generación dinámica de target_path**: Implementado soporte `TARGET_FILE: <ruta>` en primera línea del output del LLM. FileWrite extrae la ruta y la elimina del contenido antes de escribir.

---

## Configuración

- **Provider:** `codex-account` (Codex CLI 0.113.0, GPT-5)
- **GIMO API:** `http://127.0.0.1:9325`
- **OPS_DATA_DIR:** `C:\Users\shilo\Documents\GitHub\.orch_data\ops`
- **Composición padre:** `multi_agent` (PolicyGate → RiskGate → SpawnAgentsStage → SubagentGate)
- **Composición hijos:** `agent_task` (PolicyGate → RiskGate → CognitiveAssessmentStage → LlmExecute → SubdivideRouter → FileWrite → ReviewGate)

---

## Nota

La orquestación multi-agente funciona. El DAG con dependencias, las waves secuenciales, el HITL review loop y el learning loop (CapabilityProfile) están todos operativos. El siguiente hito es que esos agentes generen código que compile.
