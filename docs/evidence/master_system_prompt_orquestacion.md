# Evidencia — System Prompt principal para orquestación y agentes

Fecha: 2026-02-19

## Objetivo

Implementar un **system prompt principal** que el orquestador inyecta a sub-agentes **antes de ejecutar** su parte del plan.

## Implementación

### 1) Servicio central de prompt maestro

Archivo: `tools/repo_orchestrator/services/system_prompt_service.py`

- `SystemPromptService.BASE_MASTER_PROMPT`
  - Reglas base de ejecución (alcance, bloqueo por falta de contexto, trazabilidad, seguridad, no inventar resultados).
- `build_master_prompt(...)`
  - Construye prompt final con:
    - `parent_id`
    - `sub_task`
    - `constraints.system_prompt` (si el plan añade reglas extra)
- `compose_execution_prompt(...)`
  - Ensambla `system_prompt + # EJECUCIÓN + task` para ejecución consistente.

### 2) Inyección en ciclo de vida de sub-agente

Archivo: `tools/repo_orchestrator/services/sub_agent_manager.py`

- Se añade almacenamiento por sub-agente: `SubAgentManager._system_prompts`.
- En `create_sub_agent(...)`:
  - Se genera y guarda el prompt maestro específico del sub-agente.
- En `execute_task(...)`:
  - Se compone prompt de ejecución con el prompt maestro.
  - Se pasa explícitamente `system_prompt` a `ModelService.generate(...)`.
- En `terminate_sub_agent(...)`:
  - Se limpia el prompt guardado para evitar residuos en memoria.

### 3) Inyección desde el plan del orquestador

Archivo: `tools/repo_orchestrator/services/plan_executor.py`

- En `_execute_single_task(...)` se crea `plan_scope_prompt` por task:
  - Incluye `Plan=<id>` y `Task=<id>`.
  - Refuerza “no salir del alcance” y “reportar blockers”.
- Ese prompt se envía en `DelegationRequest.constraints.system_prompt`.

## Tests

### Tests modificados

- `tests/services/test_sub_agent_manager.py`
  - Verifica que el prompt maestro se guarda al crear sub-agente.
  - Verifica que `execute_task(...)` llama `ModelService.generate(...)` con:
    - prompt que contiene `# EJECUCIÓN`
    - `system_prompt` presente.

- `tests/services/test_plan_executor.py`
  - Verifica que `_execute_single_task(...)` inyecta `constraints.system_prompt` con datos de Plan/Task.

### Ejecución

Comando:

```bash
python -m pytest tests/services/test_sub_agent_manager.py tests/services/test_plan_executor.py -q
```

Resultado:

- `11 passed`
- `2 warnings` (deprecations externas)

## Resultado

Queda implementado el flujo solicitado:

1. El orquestador genera/ejecuta plan.
2. Antes de cada sub-tarea, inyecta instrucciones de sistema por task.
3. El sub-agente ejecuta su parte con prompt maestro + alcance del plan.
