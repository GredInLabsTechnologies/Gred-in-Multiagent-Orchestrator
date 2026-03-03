GIMO Self-Construction Protocol v4
Plan estructurado por fases
Fase 0 — Precondiciones técnicas
Objetivo

Establecer las condiciones mínimas necesarias antes de iniciar la implementación.

Requisitos previos

Repositorio target funcional y compilable.

Tests básicos existentes o infraestructura para ejecutarlos.

Git correctamente configurado.

Ollama operativo en local.

Acceso de red permitido para uso opcional de modelo cloud.

Usuario Windows dedicado creado para el servicio.

Criterio de avance

Todos los requisitos verificados manualmente.

Fase 1 — Contrato API y Especificación Formal
Objetivo

Congelar el contrato externo antes de modificar código.

Entregables

Archivo:

docs/GPT_ACTIONS_INTEGRATION.md

Debe contener:

1. Endpoints expuestos a Actions

POST /ops/drafts

POST /ops/drafts/{id}/approve

GET /ops/runs/{id}

GET /ops/runs/{id}/preview

GET /ui/repos

GET /ui/repos/active

POST /ui/repos/select

2. JSON Schema exacto de Draft
{
  "objective": "string",
  "constraints": ["string"],
  "acceptance_criteria": ["string"],
  "repo_context": {
    "target_branch": "string",
    "path_scope": ["string"]
  },
  "execution": {
    "intent_class": "enum"
  }
}
3. Tabla de estados de ejecución

Debe definir todos los estados posibles:

DRAFT_REJECTED_FORBIDDEN_SCOPE

HUMAN_APPROVAL_REQUIRED

PRIMARY_MODEL_SUCCESS

FALLBACK_MODEL_USED

MERGE_LOCKED

MERGE_CONFLICT

VALIDATION_FAILED_TESTS

VALIDATION_FAILED_LINT

RISK_SCORE_TOO_HIGH

BASELINE_TAMPER_DETECTED

WORKER_CRASHED_RECOVERABLE

etc.

4. Política de intents

Reglas de auto_run permitidas y prohibidas.

5. Estrategia de modelos

Definición de cloud → local fallback y casos de ejecución forzada local.

Criterio de avance

Contrato aprobado y versionado.

Fase 2 — Runtime Baseline Inmutable
Objetivo

Separar completamente el runtime del repositorio target.

Alcance

Esta fase deja a GIMO operativo como servicio aislado del IDE y del repo target, con rutas, permisos y cuenta de ejecución controladas.

Implementación

Instalar GIMO en:

C:\Program Files\GIMO\
o

venv dedicado ejecutado como Windows Service.

Crear directorios:

C:\gimo_work\worktrees\

C:\gimo_work\logs\

C:\gimo_work\state\

Configurar servicio:

Nombre sugerido: GIMO-Orchestrator.

Inicio automático con recuperación en fallo (restart on failure).

Working directory fijo fuera del repo target.

Variables de entorno del servicio definidas explícitamente (sin secretos en texto plano).

Rutas de baseline en solo lectura para el usuario del servicio.

Seguridad

ACL:

Escritura solo en gimo_work y repo target.

Solo lectura en baseline.

Servicio ejecutado con usuario sin privilegios de administrador.

Hardening operativo mínimo:

Deshabilitar ejecución interactiva del servicio.

Registrar stdout/stderr estructurado en C:\gimo_work\logs.

Separar logs de aplicación, auditoría y errores críticos.

Hardening recomendado adicional:

Rotación y retención de logs con cuota por tipo (app/audit/error).

Secrets fuera de variables planas cuando sea posible (Credential Manager/DPAPI o equivalente).

Allowlist de binarios/herramientas invocables por el servicio.

Bloqueo de ejecución desde rutas temporales/no confiables.

Healthcheck local del servicio (liveness/readiness) con endpoint o comando dedicado.

Entregables

Runbook de instalación de servicio (Windows).

Checklist de ACL aplicadas por ruta.

Comando de verificación de estado del servicio (start/stop/restart/status).

Prueba de reinicio controlado con persistencia de state.

Runbook de recuperación ante desastre (restore de state/worktrees y relanzamiento seguro).

Checklist de hardening aplicado (logs, secrets, allowlist, healthcheck).

Evidencia de rotación de logs y límites de crecimiento.

Validaciones obligatorias

GIMO no puede escribir en baseline.

GIMO sí puede escribir en worktrees/logs/state.

El servicio arranca sin IDE abierto.

Tras reinicio de Windows, el servicio vuelve a estado healthy.

El servicio no expone secretos en logs ni variables de diagnóstico.

La rotación de logs evita crecimiento indefinido del disco.

Restore en entorno de prueba recupera estado operativo sin corrupción.

Healthcheck falla correctamente cuando el servicio pierde dependencias críticas.

Criterio de avance

GIMO ejecutándose como servicio independiente del IDE.

ACL y rutas verificadas con evidencia.

Persistencia de estado confirmada tras reinicio del servicio.

Runbook de recuperación y controles operativos verificados con evidencia.

Fase 3 — Policy Engine y Baseline Manifest
Objetivo

Implementar la capa de control irrompible.

Alcance

Esta fase define la fuente de verdad de seguridad del runtime y bloquea cualquier ejecución cuando exista deriva de policy o baseline.

Componentes
baseline_manifest.json (en runtime)

Campos:

baseline_version

policy_schema_version

policy_hash_expected

policy.json (en state)

Define:

allowed_paths

forbidden_paths

forbidden_globs

forbidden_filetypes

max_files_changed

max_loc_changed

require_human_review_if

Campos recomendados adicionales:

created_at

updated_at

policy_signature_alg

policy_hash_previous (opcional para trazabilidad)

execution_mode_defaults

Lógica obligatoria

En cada ejecución:

Calcular hash de policy.json.

Comparar con policy_hash_expected.

Si no coincide:
→ BASELINE_TAMPER_DETECTED
→ abortar ejecución.

Evaluar path_scope solicitado contra:

allowed_paths

forbidden_paths

forbidden_globs

forbidden_filetypes

Aplicar límites de cambio:

max_files_changed

max_loc_changed

Si excede límites o toca scope prohibido:
→ DRAFT_REJECTED_FORBIDDEN_SCOPE.

Generar decisión de política determinista con evidencia:

policy_decision_id

policy_hash_runtime

reglas disparadas

resultado final (allow/review/deny)

Entregables

baseline_manifest.json generado y firmado en runtime.

policy.json versionada en state con validación de schema.

Módulo de evaluación de policy con salida estructurada.

Registro de auditoría por decisión de policy.

Validaciones obligatorias

Intento de ejecutar con policy modificada en caliente → BASELINE_TAMPER_DETECTED.

Intento sobre forbidden_paths → DRAFT_REJECTED_FORBIDDEN_SCOPE.

Intento que excede max_files_changed/max_loc_changed → rechazo limpio y auditable.

Comparaciones de hash reproducibles entre reinicios del servicio.

Criterio de avance

Intentos de modificación de policy desde Actions son rechazados.

Toda ejecución produce evidencia verificable de policy_decision.

Modo de despliegue recomendado (para no bloquear desarrollo temprano)

Para evitar fricción antes de tener ciclo agentic estable, aplicar rollout en dos etapas:

1. observe-only (recomendado al inicio):
   - evaluar policy completa,
   - registrar `policy_decision_id`, hashes y reglas disparadas,
   - no bloquear automáticamente salvo tamper crítico de baseline.

2. enforce:
   - activar bloqueos de `forbidden_paths/globs/filetypes` y límites de blast radius,
   - mantener trazabilidad de decisión y razón de bloqueo.

Fase 4 — Intent Classification y Control de Auto-Run
Objetivo

Clasificación obligatoria de operaciones.

Alcance

Esta fase fuerza una clasificación explícita de intención para cada draft y convierte esa clasificación en reglas ejecutables de auto-run, revisión humana o bloqueo.

Implementación

Enum obligatorio:

DOC_UPDATE

TEST_ADD

SAFE_REFACTOR

FEATURE_ADD_LOW_RISK

ARCH_CHANGE

SECURITY_CHANGE

CORE_RUNTIME_CHANGE

Motor de clasificación:

Toda solicitud debe incluir intent_class explícito.

Si falta intent_class:
→ rechazo por schema antes de planificación.

Si intent_class no es consistente con path_scope o diff detectado:
→ reclasificación a categoría más restrictiva o bloqueo.

Reglas

Auto-run permitido únicamente si:

intent_class ∈ {DOC_UPDATE, TEST_ADD, SAFE_REFACTOR}

path_scope dentro de allowed_paths

risk_score ≤ umbral

En cualquier otro caso:
→ HUMAN_APPROVAL_REQUIRED

Reglas de endurecimiento:

SECURITY_CHANGE y CORE_RUNTIME_CHANGE nunca auto-run.

ARCH_CHANGE requiere aprobación humana aunque risk_score sea bajo.

Si hay conflicto entre intent declarado y riesgo real:
prevalece la decisión más restrictiva.

Matriz mínima de decisión

DOC_UPDATE / TEST_ADD / SAFE_REFACTOR + risk ≤ 30 + scope permitido:
auto-run elegible.

FEATURE_ADD_LOW_RISK + risk ≤ 30:
revisión humana por defecto (hasta madurez operativa).

Cualquier intent con risk 31–60:
HUMAN_APPROVAL_REQUIRED.

Cualquier intent con risk > 60:
RISK_SCORE_TOO_HIGH.

Entregables

Tabla de decisión intent_class × risk_score × scope.

Validador de consistencia intent vs cambios reales.

Registro de auditoría con:

intent_declared

intent_effective

risk_score

decision_reason

Validaciones obligatorias

Intent sin clase válida no entra al pipeline.

Intent declarado como SAFE_REFACTOR que toca paths sensibles:
reclasificación o bloqueo auditado.

Intent de auto_run indebido:
HUMAN_APPROVAL_REQUIRED consistente y reproducible.

Criterio de avance

Intentos de auto_run indebido son bloqueados.

Clasificación y decisión quedan trazables en auditoría con evidencia suficiente para revisión forense.

Fase 5 — Persistencia de Repo Override
Objetivo

Garantizar prioridad del operador humano.

Alcance

Esta fase asegura que la selección de repositorio hecha por un humano prevalece sobre Actions y sobre cualquier automatización hasta su expiración o revocación explícita.

Archivo

state/active_repo.json

Campos:

repo_id

set_by_user

set_at

expires_at

etag

Campos recomendados adicionales:

reason

source (ui/api)

version

Reglas

Si override activo:

POST /ui/repos/select desde Actions → 403 REPO_OVERRIDE_ACTIVE

Cambios humanos requieren coincidencia de ETag.

Persistencia tras reinicio obligatoria.

Reglas de concurrencia:

Si ETag no coincide:
→ 409 OVERRIDE_ETAG_MISMATCH.

Si override expiró:
→ limpiar estado de forma controlada y auditable.

Si override es revocado manualmente:
→ registrar evento con actor y timestamp.

Eventos de auditoría mínimos:

repo_override_set

repo_override_blocked_actions

repo_override_updated

repo_override_expired

repo_override_revoked

Entregables

Módulo de lectura/escritura atómica de active_repo.json.

Control de ETag con validación estricta.

Registro de auditoría por cambio de override.

Pruebas de reinicio y concurrencia.

Validaciones obligatorias

Actions no puede cambiar repo mientras override esté activo.

Cambio humano concurrente con ETag incorrecto falla con 409.

Reinicio del servicio mantiene override y ETag intactos.

Expiración automática no deja estado corrupto.

Criterio de avance

Reinicio del servicio no elimina override.

Bloqueo de Actions y control ETag verificados en pruebas repetibles.

Fase 6 — Model Strategy Resolver
Objetivo

Definir selección y fallback de modelo.

Alcance

Esta fase convierte la selección de modelo en una política determinista, auditable y resistente a fallos, sin permitir que el fallback relaje controles de seguridad.

Configuración

Primary:
qwen3-coder:480b-cloud

Fallback:
qwen3:8b (local)

Fallback activado solo en:

429

límites de sesión

límites semanales

timeout

error de red

5xx

No activar fallback si:

error 400

error de policy

error de schema

fallo de merge gate

Restricción

Fallback no altera:

intent_class

scope

policy

gates

Forzado local

Para:

SECURITY_CHANGE

CORE_RUNTIME_CHANGE

paths sensibles

Reglas operativas adicionales:

Si provider cloud está degradado de forma intermitente:

aplicar backoff exponencial antes de fallback definitivo.

registrar motivo exacto de fallback (429, timeout, 5xx, session_limit).

Si el error es de policy/schema/merge gate:

prohibido fallback, responder error de control limpio.

Fallback no puede cambiar:

path_scope

risk gates

policy decision

approval requirements

Entregables

Resolver de estrategia con tabla de decisión cloud/local.

Registro estructurado por intento de modelo:

model_attempted

failure_reason

final_model_used

fallback_used (true/false)

contador de fallback por ventana temporal.

Pruebas de resiliencia del resolver (caída cloud, timeouts, 429, errores 5xx).

Validaciones obligatorias

Caída simulada de cloud activa fallback local sin perder contexto del draft.

Error 400/policy/schema no activa fallback.

SECURITY_CHANGE y CORE_RUNTIME_CHANGE siempre ejecutan local-only.

Mismo input + mismo estado produce misma decisión de strategy resolver.

Criterio de avance

Simulación de caída de cloud ejecuta fallback correctamente.

Decisiones del resolver trazables y reproducibles en auditoría.

Fase 6.5 — Account OAuth Provider (Codex/OpenAI) + Auditoría
Objetivo

Habilitar autenticación por cuenta (device flow) con persistencia segura de sesión y trazabilidad completa del uso de IA.

Implementación

Feature flag obligatorio:

account_mode_enabled (default: false).

Si está desactivado, solo se permite auth_mode=api_key.

Device Flow (account mode):

Endpoints internos:

POST /ops/connectors/account/login/start

GET /ops/connectors/account/login/{flow_id}

POST /ops/connectors/account/refresh

POST /ops/connectors/account/logout

Estados del flujo:

pending

approved

denied

expired

error

Persistencia segura (no env volátil):

Guardar access_token y refresh_token en credential store (Windows Credential Manager / DPAPI).

En provider.json solo guardar referencia auth_ref: vault:<id>.

Prohibido persistir tokens en logs, previews o state plano.

Refresh automático + fallback:

Antes de cada llamada, validar expiración del token.

Si expira, refresh automático y un reintento único.

Si falla refresh, estado PROVIDER_AUTH_REFRESH_FAILED y fallback a api_key cuando exista.

Auditoría y observabilidad:

Registrar en logs/ai_usage.jsonl:

run_id

draft_id

provider_type

auth_mode

model

tokens_in

tokens_out

cost_usd

status

latency_ms

request_id

error_code

Eventos de auditoría mínimos:

provider_connected

provider_token_refreshed

provider_disconnected

provider_auth_failed

Limitaciones y gobernanza:

Account mode se clasifica como experimental.

En entornos strict/compliance, requerir api_key salvo aprobación explícita de policy.

Estados adicionales de ejecución

PROVIDER_AUTH_PENDING

PROVIDER_AUTH_APPROVED

PROVIDER_AUTH_EXPIRED

PROVIDER_AUTH_REFRESH_FAILED

PROVIDER_AUTH_REVOKED

Criterio de avance

Reinicio del servicio mantiene provider account conectado mediante auth_ref de vault.

Refresh automático validado en pruebas de expiración.

Ningún token aparece en provider.json, logs o preview.

Telemetría de uso visible por provider/model/run en observabilidad.

Fase 7 — Merge Gate Industrial
Objetivo

Implementar integración segura.

Alcance

Esta fase garantiza que ningún cambio llegue a la rama principal sin pasar validaciones deterministas, control de concurrencia, idempotencia y recuperación ante fallos parciales.

Concurrencia

Un solo merge activo por repo.

Estado MERGE_LOCKED para intentos simultáneos.

Reglas de lock:

Lock con TTL y heartbeat.

Si lock queda huérfano: transición a recuperación controlada (stuck lock recovery).

Reintentos concurrentes deben fallar de forma limpia y auditable con estado MERGE_LOCKED.

Pipeline

Validar worktree limpio.

Ejecutar tests.

Lint / typecheck.

Calcular risk_score.

Dry-run merge.

Gates previos obligatorios:

Policy decision válida y vigente.

Intent classification efectiva.

Validación de baseline hash.

Risk score

≤30: elegible auto

31–60: humano requerido

60: bloqueo

Regla adicional:

SECURITY_CHANGE y CORE_RUNTIME_CHANGE no se auto-mergean aunque score sea bajo.

Estados

MERGE_CONFLICT

VALIDATION_FAILED_TESTS

VALIDATION_FAILED_LINT

RISK_SCORE_TOO_HIGH

PIPELINE_TIMEOUT

WORKTREE_CORRUPTED

ROLLBACK_EXECUTED

Idempotencia

run_id determinista por draft + commit_base.

Si worker cae:
→ reanudar o marcar WORKER_CRASHED_RECOVERABLE.

Rollback determinista (cuando se toca main)

Capturar commit_before antes del merge real.

Si falla después de modificar main:

rollback inmediato a commit_before (estrategia definida: revert o reset controlado según política del repo).

Registrar evento ROLLBACK_EXECUTED con trazabilidad completa.

Entregables

Merge orchestrator serializado por repo.

Mecanismo de lock con TTL/heartbeat.

Runbook de recuperación para:

worker crash en cada etapa,

timeouts,

worktree corrupto,

lock atascado.

Pruebas de idempotencia por run_id determinista.

Validaciones obligatorias

Concurrencia N>1 mantiene un solo merge activo por repo.

Main nunca queda en estado intermedio tras fallo.

Rollback se ejecuta y queda auditado cuando corresponde.

Reanudación tras crash preserva consistencia de run y worktree.

Criterio de avance

Main branch nunca queda en estado intermedio.

Recuperación y rollback verificados con casos de fallo repetibles.

Fase 8 — Observabilidad y Auditoría
Objetivo

Garantizar trazabilidad end-to-end de cada decisión y ejecución para diagnóstico, cumplimiento y forensia.

Alcance

Esta fase define qué señales mínimas deben existir en logs, métricas, trazas y preview para poder reconstruir cualquier incidente sin ambigüedad.

Endpoint preview

GET /ops/runs/{id}/preview

Debe incluir:

diff resumen

risk_score

modelo utilizado

policy_hash_expected

policy_hash_runtime

baseline_version

commit_before

commit_after

Campos recomendados adicionales de preview:

run_id

draft_id

intent_declared

intent_effective

final_status

fallback_used

Logs estructurados

Registrar:

actor

intent_class

repo_id

baseline_version

model_attempted

final_model_used

Correlación mínima obligatoria:

trace_id

request_id

run_id

Métricas mínimas:

latency_ms por etapa

tasa de fallback

tasa de HUMAN_APPROVAL_REQUIRED

tasa de bloqueo por policy

errores por categoría

Entregables

Esquema de log estructurado versionado.

Panel de observabilidad mínimo (runs, errores, costos, fallback).

Alertas para Sev-0/Sev-1.

Validaciones obligatorias

Cada run produce trazas correlacionables de inicio a fin.

Incidente simulado puede reconstruirse solo con datos de observabilidad.

No se exponen secretos ni tokens en logs o preview.

Criterio de avance

Auditoría completa reproducible.

Alertas críticas verificadas en pruebas de fuego.

Fase 9 — Exposición Actions-Safe
Objetivo

Reducir superficie de ataque.

Alcance

Esta fase blinda el perímetro de API para que Actions solo vea y use endpoints estrictamente necesarios, con validación de schema y límites de uso.

openapi.json expone únicamente:

POST /ops/drafts

POST /ops/drafts/{id}/approve

GET /ops/runs/{id}

GET /ops/runs/{id}/preview

GET /ui/repos

GET /ui/repos/active

POST /ui/repos/select

Reglas de seguridad de exposición:

OpenAPI filtrado no debe contener rutas internas, admin ni debug.

Validación estricta de schema en request/response.

Rate limiting y payload size limit en endpoints Actions.

Mensajes de error sanitizados (sin paths internos ni stack traces).

Entregables

Generador/validador de spec filtrado.

Pruebas de contrato contra spec pública.

Checklist de hardening de endpoints expuestos.

Validaciones obligatorias

Fuzzing básico sobre payload inválido no rompe runtime ni filtra información sensible.

Rutas no expuestas en spec pública devuelven 404/403 consistente.

Cambios de contrato rompen CI si no se actualiza spec versionada.

Criterio de avance

Endpoints no autorizados no aparecen en spec filtrado.

Contrato público pasa validación automática en CI.

Fase 10 — Validación Integral
Objetivo

Probar el sistema como producto completo bajo condiciones normales y adversariales antes de declarar producción.

Alcance

Esta fase consolida pruebas funcionales, resiliencia, seguridad y recuperación para emitir decisión final Go/No-Go.

Casos obligatorios

Draft sobre forbidden path → rechazado.

Intent auto_run indebido → forzado a aprobación.

Cloud falla → fallback local.

Ambos modelos fallan → error limpio.

Merge conflict → main intacto.

Reinicio mantiene override.

Modificación de policy → BASELINE_TAMPER_DETECTED.

Casos adicionales recomendados

Lock atascado en merge gate → recuperación controlada.

Caída de worker durante merge y durante rollback.

Token account-mode expirado durante ejecución crítica.

ETag mismatch en override concurrente.

Payload malformado en endpoints Actions-Safe.

Salida esperada de validación

Matriz de resultados (pass/fail) por caso y severidad.

Evidencia adjunta (logs, trazas, snapshots, commits).

Lista de riesgos residuales con mitigación y owner.

Go/No-Go report firmado por responsables técnicos.

Criterios cuantitativos sugeridos

0 fallos Sev-0 abiertos.

0 fallos Sev-1 sin mitigación aceptada.

Tasa de éxito de runs en entorno controlado >= 95%.

Tiempo de recuperación de fallos críticos dentro de umbral operativo definido.

Criterio de cierre

Todos los casos ejecutados satisfactoriamente.

Go/No-Go explícito emitido con evidencia verificable.

Secuencia final de implementación

Fase 1

Fase 2

Fase 3

Fase 4

Fase 5

Fase 6

Fase 6.5

Fase 7

Fase 8

Fase 9

Fase 10

Orden de ejecución recomendado (estrategia pragmática de entrega)

Nota estratégica:
Aunque el protocolo está definido por fases 1→10, la ejecución recomendada es por vertical slices para validar valor real temprano y reducir riesgo de sobre-ingeniería.

Slice 0 — Vertical Slice Agentic mínimo (obligatorio antes de endurecer todo)

Objetivo:
Demostrar ciclo completo extremo a extremo en un caso real simple:

"petición" → contrato → implementación → tests/lint → merge/PR.

Componentes mínimos del Slice 0:

- `GraphState` mínimo versionado.
- RouterPM funcional.
- ContextIndexer básico (manifest/readme/CI/paths).
- Planner básico (sin DAG complejo inicial).
- 1 Specialist Agent (por ejemplo Backend).
- QA Gate mínimo (tests + lint).
- Merge simple (sin lock avanzado al inicio).

Fuera de alcance del Slice 0:

- paralelismo multiagente avanzado,
- critic adversarial completo,
- fix-loop iterativo complejo,
- account mode OAuth (Fase 6.5),
- fallbacks sofisticados,
- locking industrial completo.

Gate para pasar del Slice 0 al endurecimiento:

- Flujo E2E estable y repetible en repo real.
- Merge consistente sin dejar estado intermedio.
- Evidencia mínima trazable por run.

Slice 1 — Endurecimiento de Fase 3 (Policy Engine real)

Después del Slice 0 estable:

- activar baseline hash enforcement completo,
- activar bloqueos de scope/límites,
- mantener modo observe-only como fallback operativo si se detecta sobrebloqueo.

Slice 2 — Paralelismo y QA avanzado

- Fan-out/Fan-in real.
- Security Critic + Acceptance Matcher estrictos.
- FixLoop con límite de iteraciones.

Slice 3 — Capacidades de complejidad alta

- Account Mode (Fase 6.5) con vault/refresh/fallback.
- Locks industriales completos y escenarios de recuperación avanzados.

Regla de decisión para roadmap:

Priorizar siempre “sistema que ejecuta bien + evidencia” antes de introducir capas adicionales de complejidad.

Riesgos operativos a vigilar explícitamente

1. Complejidad excesiva sin E2E probado:
   - mitigación: no avanzar en hardening sin Slice 0 validado.

2. Policy demasiado estricta demasiado pronto:
   - mitigación: observe-only inicial + endurecimiento gradual.

3. Reclasificación intent/risk sin base determinista:
   - mitigar separando `risk_deterministic` (loc/files/sensitive paths) de `risk_semantic` (LLM critic), con precedencia del determinista.

4. Account Mode prematuro:
   - mitigar posponiendo Fase 6.5 hasta pipeline base estable.

Anexo A — Arquitectura objetivo: GIMO como Agente Autónomo (estilo Google Jules / Devin)

Objetivo del anexo

Definir la evolución de GIMO desde un ejecutor lineal hacia un orquestador multi-agente asíncrono, orientado a resultados verificables (PRs validadas) con control estricto de seguridad y evidencia.

A.0 Artefacto central — GraphState (fuente única de verdad)

El estado del grafo debe ser persistido y versionado durante todo el ciclo de vida:

```json
{
  "user_request_raw": "string // Ej: 'Pon un auth de Google'",
  "repo_snapshot": {
    "provider": "string",
    "repo": "string",
    "base_ref": "string",
    "worktree_id": "string // Entorno aislado"
  },
  "repo_context": {
    "stack": ["string"],
    "commands": ["string"],
    "paths_of_interest": ["string"],
    "env_notes": "string"
  },
  "contract": {
    "objective": "string",
    "constraints": ["string"],
    "acceptance_criteria": ["string"],
    "execution": { "intent_class": "feature|bugfix|refactor|chore" },
    "out_of_scope": ["string"]
  },
  "plan": {
    "milestones": ["string"],
    "tasks": ["TaskObject"]
  },
  "delegations": {
    "[agent_role]": {
      "prompt": "string",
      "inputs": "object",
      "expected_outputs": "object",
      "status": "pending|running|done|failed",
      "artifacts": ["string"]
    }
  },
  "evidence": {
    "commands_run": ["string"],
    "test_results": ["string"],
    "diffs": ["string"]
  },
  "qa": {
    "verdict": "PASS|FAIL",
    "failures": ["FailureObject"]
  },
  "final": {
    "summary": "string",
    "pr_link": "string"
  }
}
```

A.1 Topología del grafo (LangGraph-style)

Nodos y flujo condicional recomendado:

1. RepoBootstrapper:
   - Prepara entorno aislado (worktree/sandbox).

2. ContextIndexer:
   - Construye `repo_context` desde manifiestos, README, CI, estructura real del repo.

3. RouterPM (Product Manager técnico):
   - Convierte `user_request_raw` en `contract` JSON estricto.
   - Incluye checker para evitar alucinaciones.

4. PlannerOrchestrator:
   - Convierte `contract` en plan por hitos y DAG de tareas.

5. FanOutDispatcher:
   - Lanza delegaciones técnicas por rol (paralelo/secuencial según dependencias).

6. SpecialistAgents:
   - Frontend/Backend/DB/Security, etc.
   - Cada agente produce patch/diff en su worktree.

7. Integrator (Fan-In):
   - Integra patches en rama de integración.
   - Gestiona conflictos.

8. QA Gate:
   - Ejecuta lint/tests/checks.
   - Ejecuta crítico adversarial y compara evidencia vs acceptance criteria.

9. FixLoop Router:
   - Si falla QA, genera Fix Tickets y reinyecta al FanOutDispatcher.
   - Límite de iteraciones recomendado: N=3.

10. PR/Delivery:
   - Si pasa QA, empaqueta evidencia y abre PR documentada.

A.2 RouterPM como “prompt compilador” (dos pasadas)

Pasada 1 (Generación):
- Traduce texto libre a contrato preliminar usando `repo_context`.

Pasada 2 (Checker):
- Verifica que no se inventen rutas, comandos o stack.
- Fuerza restricciones conservadoras ante ambigüedad.

Plantilla de sistema recomendada:

```text
ROL: Staff Engineer + Product Manager Técnico
OBJETIVO: Producir SOLO JSON válido siguiendo el Schema exacto.
REGLAS ESTRICTAS:
1. NO inventar rutas, comandos ni tecnologías. Usa ÚNICAMENTE lo presente en `repo_context`.
2. `acceptance_criteria` DEBE ser verificable empíricamente.
3. Ante ambigüedades, añade `constraints` conservadoras y seguras.
4. Lista explícitamente exclusiones en `out_of_scope` para evitar scope creep.
INPUTS:
- user_request_raw
- repo_context (stack, commands, paths_of_interest)
```

A.3 Delegación y sub-prompts técnicos (Fan-Out)

El PlannerOrchestrator divide el contrato en `TaskContracts` por especialidad.

Ejemplo (Backend FastAPI):

```text
ROL: Backend Specialist (FastAPI).
GOAL: Implementar validación de identidad OAuth2 y mapeo de sesión (ticket #BE-123).
INPUTS:
- Repo path scope: `/services/api`
- Arquitectura actual: JWT propietario (revisar modulo X).
CONSTRAINTS:
- No romper endpoints existentes en `/auth/*`.
- Configurar credenciales vía variables de entorno.
ACCEPTANCE CHECKS:
- Endpoint callback implementado y con HTTP esperado.
- pytest pasa en `/services/api`.
EXPECTED ARTIFACTS:
- Diff (`git diff`).
- Archivos tocados.
- Lista de comandos ejecutados con éxito.
```

A.4 QA Gate reforzado (Acceptance Matcher + Security Critic)

1. Acceptance Matcher:
   - Evalúa PASS/FAIL por criterio usando evidencia empírica (`commands_run`, `test_results`, logs).

2. Security Critic:
   - Revisión adversarial del diff final (inyecciones, bypass auth, secretos expuestos, etc.).

3. Reinyección automática:
   - Si cualquiera falla, `FixLoop Router` genera ticket y reenvía al agente responsable.

A.5 Integración dentro del flujo de Self-Construction (roadmap operativo)

Para organizar esta arquitectura dentro del protocolo existente:

- Fases 1–3 (contrato + baseline + policy):
  base de seguridad y validación estructural para habilitar orquestación confiable.

- Fases 4–7 (intent + strategy + merge gate):
  gobiernan decisiones de ejecución, enrutado y entrega segura.

- Fases 8–10 (observabilidad + exposición segura + validación integral):
  habilitan trazabilidad forense y criterio Go/No-Go.

- Capa transversal nueva (este anexo):
  define la arquitectura de ejecución multi-agente asíncrona sobre esas garantías.

A.6 Próximos pasos de implementación

1. Consolidar `OpsCreateDraftRequest` para aceptar el estado mínimo requerido del grafo.
2. Implementar pipeline estilo LangGraph con RouterPM como entrada estricta.
3. Desarrollar `ContextIndexer` para reducir alucinaciones.
4. Definir infraestructura de worktrees/sandbox para paralelismo seguro.

A.7 Implementación MVP (estado base reportado)

Piezas iniciales definidas para fundación del sistema:

1. Modelos de estado en `ops_models.py`:
   - Contrato estricto, enums canónicos, artefactos de evidencia y contenedor `GraphState` versionado.

2. Capa pre-inyectora en `routers/ops/plan_router.py`:
   - Validación de entrada (modo contrato estructurado).
   - Runtime Policy Gate previo a la orquestación.
   - Rechazo temprano de drafts con riesgo/scope no permitido.

Nota operativa:
Este anexo funciona como guía de evolución arquitectónica y debe mantenerse alineado con la implementación real y la evidencia de pruebas en cada iteración.