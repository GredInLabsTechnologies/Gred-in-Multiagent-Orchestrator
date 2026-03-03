# Fase 8 — Revisión code-by-code (implementación vs plan)

Documento de verificación estricta de la Fase 8 de `docs/GIMO_Self_Construction_Protocol_v4.md`.

## Fuente de verdad del plan

- Plan base: `docs/GIMO_Self_Construction_Protocol_v4.md`
- Sección objetivo: **Fase 8 — Observabilidad y Auditoría**

## 1) Endpoint preview obligatorio

### Requisito del plan
`GET /ops/runs/{id}/preview` debe incluir:
- `diff_summary`
- `risk_score`
- `model_used`
- `policy_hash_expected`
- `policy_hash_runtime`
- `baseline_version`
- `commit_before`
- `commit_after`

### Implementación
- Archivo: `tools/gimo_server/services/ops_service.py`
- Método: `get_run_preview(...)`

Campos implementados en payload:
- `diff_summary`
- `risk_score`
- `model_used`
- `policy_hash_expected`
- `policy_hash_runtime`
- `baseline_version`
- `commit_before`
- `commit_after`

Adicionales recomendados del plan (también implementados):
- `run_id`, `draft_id`
- `intent_declared`, `intent_effective`
- `final_status`
- `fallback_used`

Extras de trazabilidad añadidos:
- `request_id`, `trace_id`
- `model_attempted`, `final_model_used`, `failure_reason`

## 2) Correlación obligatoria (`trace_id`, `request_id`, `run_id`)

### Requisito del plan
Toda traza debe correlacionarse con `trace_id`, `request_id`, `run_id`.

### Implementación
1. Archivo: `tools/gimo_server/middlewares.py`
   - Middleware: `correlation_id_middleware(...)`
   - Lee `X-Request-ID`/`X-Correlation-ID` y fija:
     - `request.state.request_id`
     - headers de respuesta `X-Request-ID`, `X-Correlation-ID`

2. Archivo: `tools/gimo_server/routers/ops/run_router.py`
   - Endpoint: `get_run_preview(...)`
   - Extrae:
     - `request_id` desde `request.state`/headers
     - `trace_id` desde `X-Trace-ID` o query `trace_id`
   - Pasa ambos a `OpsService.get_run_preview(...)`

3. Archivo: `tools/gimo_server/services/observability_service.py`
   - Método: `record_structured_event(...)`
   - Campos obligatorios del evento:
     - `trace_id`, `request_id`, `run_id`

## 3) Logs estructurados versionados

### Requisito del plan
Esquema versionado + campos mínimos:
- `actor`
- `intent_class`
- `repo_id`
- `baseline_version`
- `model_attempted`
- `final_model_used`

### Implementación
- Archivo: `tools/gimo_server/services/observability_service.py`

Elementos:
- `OBS_LOG_SCHEMA_VERSION = "1.0"`
- Buffer interno: `_structured_events`
- Método de escritura: `record_structured_event(...)`
- Método de lectura: `list_structured_events(...)`

Campos incluidos por evento:
- `schema_version`
- `event_type`, `status`
- `trace_id`, `request_id`, `run_id`
- `actor`, `intent_class`, `repo_id`, `baseline_version`
- `model_attempted`, `final_model_used`
- `stage`, `latency_ms`, `error_category`, `metadata`

## 4) Métricas mínimas de Fase 8

### Requisito del plan
- latency por etapa
- tasa fallback
- tasa HUMAN_APPROVAL_REQUIRED
- tasa bloqueo por policy
- errores por categoría

### Implementación
- Archivo: `tools/gimo_server/services/observability_service.py`
- Método: `get_metrics()`

Métricas implementadas:
- `latency_ms_by_stage`
- `fallback_rate`
- `human_approval_required_rate`
- `policy_block_rate`
- `errors_by_category`

Compatibilidad UI mantenida:
- `total_workflows`
- `active_workflows`
- `total_tokens`
- `estimated_cost`
- `error_rate`
- `avg_latency_ms`

## 5) Alertas críticas (Sev-0 / Sev-1)

### Requisito del plan
Alertas para incidentes críticos.

### Implementación
1. Archivo: `tools/gimo_server/services/observability_service.py`
   - Método: `get_alerts()`
   - Reglas:
     - `SEV-0`: `BASELINE_TAMPER_DETECTED` (categoría `baseline`)
     - `SEV-1`: `HIGH_ERROR_RATE`
     - `SEV-1`: `HIGH_FALLBACK_RATE`
     - `SEV-1`: `HIGH_POLICY_BLOCK_RATE`
     - `SEV-1`: `HIGH_HUMAN_APPROVAL_RATE`

2. Archivo: `tools/gimo_server/routers/ops/observability_router.py`
   - Endpoint añadido: `GET /ops/observability/alerts`
   - Devuelve: `{ items, count }`

## 6) Panel mínimo de observabilidad

### Requisito del plan
Panel mínimo con runs/errores/costos/fallback.

### Implementación
1. Archivo: `tools/orchestrator_ui/src/types.ts`
   - `ObservabilityMetrics` extendido con:
     - `fallback_rate`
     - `human_approval_required_rate`
     - `policy_block_rate`
     - `latency_ms_by_stage`
     - `errors_by_category`

2. Archivo: `tools/orchestrator_ui/src/components/observability/ObservabilityPanel.tsx`
   - Métrica añadida visible:
     - `Fallback Rate`
   - Métricas existentes:
     - workflows
     - coste estimado
     - error rate
     - latencia media

## 7) No exposición de secretos

### Requisito del plan
No exponer secretos/tokens en logs o preview.

### Evidencia implementada
- Archivo: `tests/unit/test_phase8_observability.py`
- Test: `test_phase8_preview_contract_and_correlation`
- Verifica que preview no incluya claves:
  - `api_key`, `token`, `refresh_token`, `auth_ref`

## 8) Pruebas de verificación Fase 8

### Archivo
`tests/unit/test_phase8_observability.py`

### Cobertura de requisitos
1. `test_phase8_preview_contract_and_correlation`
   - Contrato preview + correlación + no secretos
2. `test_phase8_request_id_header_is_echoed`
   - Correlación HTTP (`X-Request-ID`)
3. `test_phase8_metrics_include_required_rates_and_categories`
   - Métricas mínimas Fase 8
4. `test_phase8_alerts_endpoint_exposes_sev0_sev1`
   - Alertas críticas

### Resultado de ejecución
Comando:
`python -m pytest tests/unit/test_phase8_observability.py tests/unit/test_observability.py -q`

Resultado:
- `7 passed`

## Veredicto

Estado de cumplimiento Fase 8 (code-by-code): **COMPLETO** para los requisitos definidos en la sección Fase 8 del plan original.
