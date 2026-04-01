# Especificación de Integración GIMO ↔ GICS 1.3.3 (v1.0)

Este documento define la arquitectura y los contratos técnicos exactos para la integración entre el orquestador GIMO y la memoria operacional de inferencia GICS 1.3.3.

## 0. Invariantes del Sistema
- GICS conserva siempre el canon íntegro.
- Ningún `DerivedContextArtifact` sustituye al canon.
- Ninguna ruta `execution_safe` podrá depender exclusivamente de un artefacto `abstractive`.
- `tool_pair_integrity = 100%` en toda compresión aplicada a mensajes con invocación de herramientas.
- `system_prompt_preserved = 100%` siempre.
- Toda rehidratación de memoria debe provenir de un único `canonical_snapshot_id`.
- GIMO debe garantizar la operación activa en **Modo Degradado** si GICS no está disponible temporalmente.

## 1. Principio Arquitectónico Fundacional: Canon vs Vista
**GICS guarda el canon; GIMO consume vistas.**

Toda destilación, resumen o compresión es un artefacto derivado. El estado original debe ser recuperable; los resúmenes actúan como vistas operativas.

## 2. Infraestructura Base y Dominios de Fallo

### A. Handshake de Compatibilidad RPC
El canal RPC JSON debe negociar `rpc_schema_version`, `capabilities` y `feature_flags` obligatoriamente durante el arranque de la conexión.

- Si no existe una intersección compatible entre versiones/capacidades mínimas, el enlace RPC debe fallar mediante **fast-fail**.
- En dicho caso, GIMO entrará en **modo degradado explícito**.
- Queda estrictamente prohibido el fallback implícito a contratos o rutinas no negociadas.

### B. Modo Degradado y Dominios de Fallo
GIMO debe seguir operando si GICS queda temporalmente indisponible u ocurre un fast-fail en el handshake.

**Restricciones Operativas Mínimas (Degraded Minimal State):**
- La indisponibilidad de GICS **no** debe bloquear el runtime de GIMO.
- GIMO operará sobre el último `session_state` conocido localmente y un `decision_log` truncado.
- **Router local estático:** el routing dispondrá de un fallback local determinista basado en hard-gates sin recomputación de ranking remoto (GICS).
- **Sin artefactos advisory:** no se accederá a vistas derivadas.
- Toda respuesta inyectada en el runtime llevará el flag `degraded=true` explícito.

## 3. Contratos de Inferencia y Rehidratación

### A. Control y Routing de Modelos
La selección se delega a `infer(domain='ops.provider_select')` en GICS, previa comprobación de hard-gates operacionales en GIMO.

**Frenos del Bandit Router:** Al interrogar a GICS, GIMO exigirá:
1. Presupuesto de exploración máximo.
2. Tie-breaker determinista local.
3. Cooldown temporal tras fallo confirmado del proveedor.
4. Latencia máxima permitida (`router_latency_p95_target_ms`).
5. **Política de Health Snapshot Stale:** Todo `provider_health_snapshot` debe tener un TTL asociado. Si el snapshot cruza este TTL y queda "stale", el router no podrá usarlo para tomar la decisión primaria; GIMO aplicará la penalización correspondiente, requiriendo validación contra gates locales estáticos o asumiendo el nodo en fallback.

### B. Bucle de Feedback Transaccional (reportOutcome)
**Semántica de la Outbox:** Los eventos `reportOutcome` que no alcancen GICS en tiempo real se retendrán en una outbox local (durable) bajo el siguiente contrato:
- **Garantía de entrega:** at-least-once.
- **Dedupe interno:** Control de idempotencia en destino mediante el atributo `event_id`.
- **Condición ACK:** Exclusivamente tras confirmación síncrona de persistencia en disco de GICS.
- **Ciclo de vida local:** Sujeto a un TTL por evento configurable, con un retry backoff base (ms).
- **Poison events:** En cuarentena automática tras superar `max_retries`.

**Esquema de Evento de Resultado:**
```typescript
type OutcomeEvent = {
  schema_version: string;
  event_id: string;
  correlation_id: string;
  timestamp_monotonic_ms: number;
  timestamp_wallclock: string;
  domain: "ops.provider_select" | "ops.plan_rank";
  choice: string;
  task_fingerprint: string;
  transport_outcome: "ok" | "timeout" | "network_error" | "rpc_error";
  provider_outcome: "ok" | "rate_limited" | "server_error" | "unavailable";
  task_outcome: "success" | "semantic_failure" | "format_failure" | "budget_exceeded";
  tool_outcome: "not_used" | "success" | "tool_failure";
  user_outcome: "none" | "aborted";
  latency_ms?: number;
  cost_usd?: number;
  tokens_in?: number;
  tokens_out?: number;
  retry_count: number;
  degraded: boolean;
}
```

### C. Rehidratación de Memoria Operacional Atómica
**Contrato `canonical_snapshot_id`:**
`canonical_snapshot_id` identifica un snapshot inmutable y reconstruible de la memoria operacional. Dos lecturas con un mismo ID garantizan devolver el mismo contenido lógico. Ninguna rehidratación local de GIMO podrá mezclar campos obtenidos de IDs distintos en una misma sesión.

**Contenido exigido por Snapshot:**
- `canonical_snapshot_id`
- `session_state`
- `agent_working_set`
- `decision_log`
- `active_artifacts`
- `provider_health_snapshot`
- `snapshot_created_at`
- `schema_version`

## 4. Política de Compresión: "Context Reduction Ladder"
GIMO recorrerá esta escala de operaciones para la reducción de contexto:
1. Prefix cache exacto del proveedor.
2. Rehidratación selectiva atómica desde GICS.
3. Recorte estructural no semántico.
4. Compresión extractiva.
5. Resumen abstractive (solo para recaps de la interfaz gráfica de usuario final).

**Non-Derivable Canon:** Prohibido resumir o comprimir de forma abstractiva:
- System prompt activos.
- Tool schemas / JSON schemas.
- Políticas de seguridad.
- Contratos de IPC / RPC.
- Rutas físicas, diffs funcionales, firmas ni código.
- Enlaces bidireccionales `tool_call` + `tool_result`.

## 5. Derived Context Reducer (Gestor de Vistas)
**Estado:** Operativo solo para `safety_class="advisory"`, y estrictamente restringido para entornos `execution_safe` a artefactos extractivos que proporcionen provenance verificable. Genera vistas parciales de reducción (artefactos) regidas por reglas de invalidación deterministas.

**Tipo de Contrato Fuerte (Vía Union Types)**
Para evitar la emisión de falsos positivos en TypeScript/Schema Validation, el tipo exige explícitamente la división de modos:

```typescript
type DerivedContextArtifact =
  | {
      schema_version: string;
      artifact_id: string;
      canonical_snapshot_id: string;
      source_checkpoint_ids: string[];
      source_hash: string;
      source_ranges: Array<{ doc_id: string; start: number; end: number }>;
      offset_unit: "bytes" | "chars" | "tokens" | "lines";
      mode: "extractive";
      safety_class: "execution_safe";
      created_from_mode: "ladder_step_3" | "ladder_step_4";
      task_objective: string;
      query_fingerprint?: string;
      distiller_version: string;
      model_id?: string;
      tool_schema_hash?: string;
      system_prompt_hash: string;
      compression_ratio: number;
      token_before: number;
      token_after: number;
      loss_metrics: {
        retained_spans_ratio?: number;
        dropped_message_count?: number;
        tool_pair_integrity: boolean;
        system_prompt_preserved: boolean;
      };
      created_at: string;
      expires_at?: string;
      invalidated_at?: string;
      invalidation_reason?: string;
    }
  | {
      schema_version: string;
      artifact_id: string;
      canonical_snapshot_id: string;
      source_checkpoint_ids: string[];
      source_hash: string;
      source_ranges: Array<{ doc_id: string; start: number; end: number }>;
      offset_unit: "bytes" | "chars" | "tokens" | "lines";
      mode: "extractive" | "abstractive";
      safety_class: "advisory";
      created_from_mode: "ladder_step_3" | "ladder_step_4" | "ladder_step_5";
      task_objective: string;
      query_fingerprint?: string;
      distiller_version: string;
      model_id?: string;
      tool_schema_hash?: string;
      system_prompt_hash: string;
      compression_ratio: number;
      token_before: number;
      token_after: number;
      loss_metrics: {
        retained_spans_ratio?: number;
        dropped_message_count?: number;
        tool_pair_integrity: boolean;
        system_prompt_preserved: boolean;
      };
      created_at: string;
      expires_at?: string;
      invalidated_at?: string;
      invalidation_reason?: string;
    };
```

**Invalidación por Deriva (Drift)**
El gestor disparará el flag `invalidated_at` si la vista cruza un cambio en:
- `source_hash`, `system_prompt_hash` o `tool_schema_hash`.
- `task_objective`.
- Constraints de los usuarios o configuraciones maestras de seguridad.

## 6. SLOs Operacionales Verificables
**Routing IPC (Local Nominal Benchmarks):**
- `router_latency_p95_target_ms = 20` (sujeto a validación de estrés del WAL y IPC local).

**Flush de Outbox Local:**
- `outbox_flush_p95_target_ms = 50`
- `outbox_flush_p99_target_ms = 150`
- `retry_backoff_base_ms = 200`

**Seguridad de Explotación Operativa (Obligaciones):**
- `% de resúmenes abstractivos inyectados en flujos execution_safe = 0%` (Fallo de Aserción Crítico Infranqueable).
- Recuperación de modo degradado determinista sin impacto global al servicio base.
