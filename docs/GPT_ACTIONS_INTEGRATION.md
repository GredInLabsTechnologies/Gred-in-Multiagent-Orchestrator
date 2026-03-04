# GPT Actions Integration Contract

Este documento define el contrato estricto e inmutable mediante el cual GPT Actions puede interactuar con el runtime baseline de GIMO.

## 1. Exposición de API (Actions-Safe)
**URL del esquema:** `/ops/openapi.json`

El runtime baseline solo expone los siguientes endpoints para su consumo por GPT Actions:
- `POST /ops/drafts`: Crea un nuevo draft de ejecución de worktree.
- `POST /ops/drafts/{id}/approve`: Aprueba un draft previamente retenido para validación manual.
- `GET /ops/runs/{id}`: Obtiene el estado de ejecución y etapa del pipeline.
- `GET /ops/runs/{id}/preview`: Obtiene un resumen del diff, risk score e información de auditoría de un draft.
- `GET /ui/repos`: Lista de repositorios disponibles en el entorno.
- `GET /ui/repos/active`: Obtiene el repositorio objetivo seleccionado actualmente.
- `POST /ui/repos/select`: Modifica el repositorio objetivo (Sujeto a interrupciones por override humano).

Cualquier otro endpoint del sistema está estrictamente prohibido y no es accesible por Actions.

## 2. JSON Schema: `POST /ops/drafts`

El siguiente es el JSON Schema **exacto** requerido para enviar instrucciones al runtime base.
**No se aceptan prompts libres.**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "GIMO Self-Construct Draft Request",
  "type": "object",
  "required": [
    "objective",
    "constraints",
    "acceptance_criteria",
    "repo_context",
    "execution"
  ],
  "properties": {
    "objective": {
      "type": "string",
      "description": "El objetivo principal o tarea a realizar (ej: 'Refactorizar servicio auth')."
    },
    "constraints": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Reglas estrictas que el LLM debe seguir en la implementación."
    },
    "acceptance_criteria": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Criterios para considerar el trabajo terminado con éxito."
    },
    "repo_context": {
      "type": "object",
      "required": ["target_branch", "path_scope"],
      "properties": {
        "target_branch": {
          "type": "string",
          "description": "Rama objetivo del repositorio (ej: 'main')."
        },
        "path_scope": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Archivos o carpetas permitidos para modificación por este draft."
        }
      }
    },
    "execution": {
      "type": "object",
      "required": ["intent_class"],
      "properties": {
        "intent_class": {
          "type": "string",
          "enum": [
            "DOC_UPDATE",
            "TEST_ADD",
            "SAFE_REFACTOR",
            "FEATURE_ADD_LOW_RISK",
            "ARCH_CHANGE",
            "SECURITY_CHANGE",
            "CORE_RUNTIME_CHANGE"
          ]
        }
      }
    }
  }
}
```
*Nota: El parámetro `model_preference` no está expuesto a Actions. La selección del modelo recae enteramente sobre el 'Model Strategy Resolver' del runtime.*

## 3. Estados de Ejecución
Al solicitar el estado mediante `GET /ops/runs/{id}`, se devolverá uno de los siguientes:

### Estados Transitorios
- `PENDING`: Draft aceptado, esperando asignación a worker.
- `IN_PROGRESS`: Ejecución de modificaciones en worktree activa.
- `MERGE_LOCKED`: Ejecutando el pipeline serializado de merge y validación.
- `PROVIDER_AUTH_PENDING`: Flujo de autenticación de cuenta (device flow) en progreso, pendiente de aprobación del usuario.
- `PROVIDER_AUTH_APPROVED`: Autenticación de cuenta completada correctamente y sesión lista para uso.

### Estados Que Requieren Intervención
- `HUMAN_APPROVAL_REQUIRED`: El risk score superó el umbral de `30` o el `intent_class` no es elegible para auto-run.

### Estados de Falla
- `BASELINE_TAMPER_DETECTED`: Aborto de seguridad por firmas inválidas en `policy_hash_runtime`.
- `DRAFT_REJECTED_FORBIDDEN_SCOPE`: El `path_scope` o el diff tocan `forbidden_paths` / `forbidden_globs` previstos en el Policy.
- `MERGE_CONFLICT`: El pipeline falló en aplicar los cambios a la rama principal debido a conflictos o fallo en la condición de worktree limpio.
- `VALIDATION_FAILED_TESTS`: Los tests automáticos del CI pasaron a estado rojo.
- `VALIDATION_FAILED_LINT`: El linter local devolvió errores.
- `RISK_SCORE_TOO_HIGH`: Puntuación > 60. Hard block con hold forense.
- `PIPELINE_TIMEOUT`: Expiración de tiempo del merge gate.
- `WORKER_CRASHED_RECOVERABLE`: Fallo del runner que puede reanudarse tras reinicio system de GIMO.
- `PROVIDER_AUTH_EXPIRED`: Sesión account-mode expirada; requiere refresh o nueva autenticación.
- `PROVIDER_AUTH_REFRESH_FAILED`: Falló el refresh del token de cuenta; requiere reautenticación o fallback.
- `PROVIDER_AUTH_REVOKED`: Sesión de cuenta revocada o desconectada explícitamente.

### Severidad Operacional (mínima)
- `BASELINE_TAMPER_DETECTED`: **Sev-0** → abortar ejecución, bloquear corrida y alertar inmediatamente.
- `RISK_SCORE_TOO_HIGH`: **Sev-1** → bloqueo duro, requiere revisión humana.
- `PROVIDER_AUTH_REFRESH_FAILED`: **Sev-1** → fallback a `api_key` si existe; si no, abortar limpio.
- `MERGE_CONFLICT`: **Sev-2** → preservar worktree, escalar a revisión humana.
- `VALIDATION_FAILED_TESTS` / `VALIDATION_FAILED_LINT`: **Sev-2** → no mergear, registrar evidencia.
- `PIPELINE_TIMEOUT`: **Sev-2** → cancelar pipeline, conservar estado forense.
- `WORKER_CRASHED_RECOVERABLE`: **Sev-2** → reanudar o recuperar mediante runbook.

## 4. Estrategia de Modelos (Model Strategy)

La ejecución local o en nube es decidida dinámicamente:
- **Modelo Principal:** `qwen3-coder:480b-cloud`
- **Fallback Activo:** `qwen3:8b` (Local API)

**El modo Fallback se activa exclusivamente bajo estas condiciones:**
- Error HTTP 429 (Too Many Requests).
- Límite de sesión o límite semanal agotado en el provider cloud.
- Timeout de red o Error HTTP 5xx del servidor upstream.
- El modelo principal reporta indisponibilidad general (`Model unavailable`).
- **NO aplica** si la falla remota reporta HTTP 400, Scope Prohibido, Error de Schema, o Falla en Merge Gate.

**Obligatoriedad de ejecución LOCAL:**
Cualquier draft que posea el `intent_class` marcado como `SECURITY_CHANGE` o `CORE_RUNTIME_CHANGE` o detecte alteración en paths sensibles (en policy) obliga a que todo el procesamiento se ejecute de manera blindada mediante el fallback local `qwen3:8b`.

**Regla de seguridad adicional:**
Si un draft toca `sensitive paths` o supera umbral de riesgo de auto-run, no se permite enrutar ese procesamiento por cloud.

## 5. Risk Scoring & Auto-Run Rules

Para que un draft se ejecute de forma autónoma sin retención mediante `POST /ops/drafts/{id}/approve` (`auto_run=true` internamente):
1. **Intents Permitidos:** `DOC_UPDATE`, `TEST_ADD`, `SAFE_REFACTOR`
2. **Path Scope:** Todos los cambios ocurren estrictamente dentro de los `allowed_paths` del policy.
3. **Límites Físicos:** Se respeta `max_files_changed` y `max_loc_changed`.
4. **Risk Score:** La evaluación resultante del pipeline de diffs y AST arroja `≤ 30`.
5. **Límites explícitos de cambio:** deben respetarse `max_files_changed` y `max_loc_changed` definidos por policy/baseline.

- Score `31-60`: Requiere aprobación humana.
- Score `> 60`: Bloqueo directo (Falla dura `RISK_SCORE_TOO_HIGH`).

### 5.1 Fase 4 — Decision Matrix (canónica)

El runtime persiste y expone en `draft.context` los campos de decisión:
- `intent_declared`
- `intent_effective`
- `risk_score`
- `decision_reason`
- `execution_decision`

`execution_decision` debe ser uno de:
- `AUTO_RUN_ELIGIBLE`
- `HUMAN_APPROVAL_REQUIRED`
- `RISK_SCORE_TOO_HIGH`
- `DRAFT_REJECTED_FORBIDDEN_SCOPE`

Reglas operativas:
- `RISK_SCORE_TOO_HIGH` y `DRAFT_REJECTED_FORBIDDEN_SCOPE` se rechazan en creación de draft.
- Aunque se solicite `auto_run=true`, solo se autoriza auto-run cuando `execution_decision == AUTO_RUN_ELIGIBLE`.
- Si `execution_decision == RISK_SCORE_TOO_HIGH`, `POST /ops/drafts/{id}/approve` responde `409`.

*Drafts exitosos se eliminan tras N días. Los fallidos entran en status Forensic Hold por M días.*

## 6. Persistencia de Sesión y Repository Priority

Actions debe respetar la configuración del repositorio activo validando el `ETag` de concurrencia mediante `GET /ui/repos/active`.
- Si ocurre un override desde UI por un operador humano, `POST /ui/repos/select` arrojará un estado HTTP `403 REPO_OVERRIDE_ACTIVE`.
- Todo cambio por Actions requerirá revalidar el target antes de iniciar el proxy local de worktree en el state path persistente.

## 7. Contrato de Preview (campos obligatorios)
Toda respuesta de `GET /ops/runs/{id}/preview` debe incluir siempre:
- `diff_summary`
- `risk_score`
- `intent_declared`
- `intent_effective`
- `decision_reason`
- `execution_decision`
- `model_used`
- `policy_hash_expected`
- `policy_hash_runtime`
- `baseline_version`
- `commit_before`
- `commit_after`

Si alguno falta, la respuesta se considera inválida para auditoría.

## 8. Versionado del Contrato
- Este contrato se considera congelado para runtime baseline.
- Cambios de schema o estados deben introducirse con migración explícita y nota en changelog.
