# Plan de Implementación: Dogma del Agente y Ejecución de Excelencia

---

## ⚠️ Inconsistencias Conocidas — Backlog Técnico

### [TRACK-002] ORCH_TOKEN — Modelo de seguridad insuficiente para uso multi-agente

**Problema:** El `ORCH_TOKEN` es una API key estática almacenada en `.env`. Se transmite en texto plano en `Authorization: Bearer` y el mismo token otorga acceso completo (lectura, escritura, aprobaciones de runs). No tiene expiración, no hay rotación automática, y no existen scopes diferenciados por operación.

**Impacto:**
- Si un proceso malicioso (o log) captura el token, tiene control total de GIMO indefinidamente.
- En escenarios multi-agente donde el token se inyecta en los contextos de los hijos, el blast radius de una fuga es total.
- No hay distinción entre `read-only` (Claude inspeccionando runs) y `execute` (lanzar runs) ni `approve` (aprobar action drafts).

**Fix propuesto:**
- Scopes por token: `read`, `execute`, `approve`, `admin`.
- Tokens de sesión con TTL (expiración en X horas, renovable vía refresh).
- Para agentes hijos: tokens derivados con scope restringido al run_id de su tarea.
- Rotación automática: generar nuevo token en cada arranque del servidor, notificar por logs al operador.

**Archivos afectados:** `security/auth.py`, `main.py` (lifespan), `config.py`

---

### [TRACK-001] Model metadata inconsistente para providers en modo `account`

**Problema:** El campo `model` en la config de GIMO para providers en modo `account` (e.g. `codex-account`) refleja el valor configurado en sesiones anteriores (`o4-mini`), pero el modelo real que ejecuta el CLI es el que tiene configurado el propio CLI (GPT-5 según `codex exec`). Además, `effective_state.effective_model` muestra `claude-opus-4-5` y `warnings` dice "Validated via local claude CLI session" — ambos incorrectos para el provider activo `codex-account`.

**Impacto:** Falta de trazabilidad — los logs y auditorías muestran `o4-mini` como modelo cuando en realidad se usa GPT-5. Viola el principio de tener registro de qué modelo hizo qué.

**Fix propuesto:**
- Al cambiar el provider activo vía `PUT /ops/provider`, revalidar y actualizar `effective_state` con el CLI activo.
- Para providers en `account` mode, añadir un campo `cli_reported_model` que se resuelva ejecutando `codex --version` o el equivalente del CLI activo.
- Asegurar que los logs de runs incluyan el modelo real obtenido del CLI response (ya existe `model` en la respuesta del `CliAccountAdapter`).

**Archivos afectados:** `provider_service_impl.py`, `cli_account.py`, `provider_service_adapter_registry.py`

---

Este documento detalla la hoja de ruta arquitectónica para integrar el **Dogma del Agente** (Regla de Oro #0) y el mandato de **Evaluación de Excelencia** dentro del núcleo del orquestador (GIMO).

## 🟢 FASE 1: Seguridad y Aprobación (Human-in-the-loop)

**Objetivo:** Evitar acciones destructivas no deseadas bloqueando la ejecución autónoma de modificaciones de disco/comandos hasta recibir permiso explícito del usuario.

### Tareas:
- [ ] **Definición de Interceptores en OpsService**
  - Identificar herramientas críticas (ej. `write_to_file`, `replace_file_content`, `run_command`, `delete_file`).
  - Modificar el flujo de llamada a herramientas en `ops_service.py` para pausar la ejecución si la herramienta está clasificada como "Crítica" o "Mutadora".
- [ ] **Mecanismo de "Draft de Ejecución" (Orchestrator)**
  - Cuando un agente requiera ejecutar una herramienta crítica, GIMO atrapará la solicitud y generará un payload de validación (un "Action Draft").
  - Enviar este payload vía SSE a la interfaz de usuario (OrchestratorChat).
- [ ] **UI de Aprobación de Acciones (Frontend)**
  - Crear un componente visual en el chat (ej. `AgentActionApproval.tsx`) que muestre al usuario qué herramienta se va a ejecutar y con qué parámetros (ej. Comando de Terminal o Diff de Código).
  - Incluir botones de **[Aprobar]** y **[Rechazar/Modificar]**.
- [ ] **Continuación de la Ejecución (Backend)**
  - Al recibir la aprobación del frontend, el backend reanuda la ejecución bloqueada de la herramienta.
  - Implementar la agrupación de pasos (Batches) para permitir aprobaciones en bloque y reducir fricción ("¿Aprobar estos 3 cambios juntos?").

---

## 🔵 FASE 2: La Trilogía de Operación (Segregación de Roles)

**Objetivo:** Estructurar los agentes backend por roles para que no exista la tentación ni la posibilidad técnica de mezclar exploración con ejecución.

### Tareas:
- [ ] **Refinar `ProviderConnectorService` y Prompts de Agente**
  - Definir la taxonomía de los 3 agentes especializados.
- [ ] **Configuración del `Explorer Agent` (El Arquitecto)**
  - **Tool constraint:** Solo herramientas de lectura y búsqueda web (`read_file`, `list_dir`, `web_search`).
  - **Prompt:** Enfocado en discusión, documentación y mapeo arquitectónico.
- [ ] **Configuración del `Auditor Agent` (El Forense)**
  - **Tool constraint:** Lectura e inspectores seguros (`grep_search`, y una versión segura de comandos de terminal de solo lectura).
  - **Prompt:** Encontrar la causa raíz, dejar rastro de lo que revisa. Prohibición total de sugerir arreglos usando "try/catch" ciegos.
- [ ] **Configuración del `Executor Agent` (El Constructor)**
  - **Tool constraint:** Solo este agente tiene permisos para mutar (`write_to_file`, etc.).
  - **Requisito de entrada:** El agente Executor orquestador solo entra en acción cuando el usuario aprueba un Plan generado por el Arquitecto o el Auditor.

---

## 🟣 FASE 3: Output Estructurado y Reporte Post-Vuelo

**Objetivo:** Obligar al LLM a devolver un formato inquebrantable cada vez que complete una acción ejecutora para garantizar la trazabilidad de seguridad y el rollback.

### Tareas:
- [ ] **Definir Esquemas Pydantic**
  - Crear el modelo `ExecutorReport` en `ops_models.py`:
    ```python
    class ExecutorReport(BaseModel):
        modified_files: List[str]
        safety_summary: str      # Por qué es seguro y funciona
        rollback_plan: List[str] # Pasos concretos para deshacerlo
    ```
- [ ] **Integración con Structured Outputs en ProviderService**
  - Actualizar el llamado a modelos ejecutores (OpenAI/Anthropic) para forzar la validación de estos esquemas. Si el agente no detalla su "Rollback Plan", la API lo rechaza.
- [ ] **Visualización del Reporte (Frontend)**
  - Cuando la tarea termina, mostrar este reporte estructurado como un desglose de misión en la UI.

---

## 🟠 FASE 4: Aplicación Estructural de la Excelencia

**Objetivo:** No confiar en que el LLM escribirá buen código. Medirlo e interceptarlo por la fuerza usando herramientas automatizadas como validadores.

### Tareas:
- [ ] **Capa 1: Bounding Boxes Typográficas**
  - Asegurar `strict: true` y barreras `no-explicit-any` en la base de código.
  - Incorporar reglas en el "Core Operating Philosophy" de los inyectores de prompt del orquestador.
- [ ] **Capa 2: El Juez Despiadado (Critic Agent Evaluator)**
  - Cuando el `Executor Agent` propone código, rutearlo internamente y de forma oculta a un mini-agente evaluador.
  - El Evaluador analizará verbosidad, sobre-ingeniería o falta de elegancia. Si no pasa la auditoría (JSON: `{"approved": false}`), el Ejecutor hace un reintento.
- [ ] **Capa 3: Justificación de Excelencia Forzada**
  - Incorporar métricas de justificación en los JSON de Output Estructurado al formular Drafts (ej. campos `why_is_this_elegant` y `what_was_removed`).
- [ ] **Capa 4: Linting Estático Automático (Opcional - Hardcore)**
  - En backend, correr herramientas como `radon` (Python) para bloquear commits subyacentes o propuestas si superan un umbral MÁXIMO de Complejidad Cognitiva (ej `> 5`).
