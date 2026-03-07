# GIMO — Revisión técnica real y plan de remediación integral (P0/P1/P2)

## 1) Diagnóstico real (basado en código actual)

Este plan valida los gaps reportados contra el estado del repositorio y propone una hoja de ruta ejecutable.

### Hallazgos críticos confirmados en código

1. **Realtime sin backpressure robusto y sin aislamiento por cliente**
   - `NotificationService` usa colas en memoria por subscriber y difusión fan-out local; aunque ahora hay cola acotada, sigue siendo in-process y sin QoS/prioridades por tipo de evento.
   - Riesgo residual: clientes tóxicos impactan latencia global de broadcast y no hay control de fairness multi-tenant.

2. **Doble autoridad de ejecución (RunWorker duplicado)**
   - FastAPI levanta worker en `main.py` (lifespan) y MCP bridge levanta otro worker separado en `mcp_bridge/server.py`.
   - Riesgo: doble polling, carreras sobre runs y comportamiento no determinista según entrypoint.

3. **Merge gate sobre repo principal**
   - Pipeline de validación y merge en `MergeGateService` opera en `repo_root_dir`.
   - Riesgo: contaminación de workspace principal, rollback frágil y side effects no aislados.

4. **Storage caliente con rewrite completo del JSON de run**
   - `append_log`, `update_run_status`, `set_run_stage`, etc. reescriben archivo completo del run.
   - Riesgo: I/O amplificado + lock global + escalado pobre.

5. **Concurrencia gobernada por slots estáticos, no por recursos reales**
   - `RunWorker` decide admisión por `max_concurrent_runs`; no considera CPU/RAM/VRAM efectiva.
   - Riesgo: saturación o infrautilización según perfil de carga.

6. **Diff git potencialmente erróneo**
   - `git diff --stat -- safe_base safe_head` trata refs como paths por el `--`.
   - Riesgo: diff incorrecto o silenciosamente vacío.

7. **Cliente HTTP sin pooling persistente**
   - `OpenAICompatAdapter` crea `httpx.AsyncClient` por request.
   - Riesgo: pérdida de keep-alive, latencia extra y overhead de sockets.

8. **Transport GICS con reconnect mínimo y semántica frágil**
   - retry simplificado (1 intento parcial), sin garantías de idempotencia/ack fuerte.
   - Riesgo: pérdida silenciosa ante cortes IPC.

---

## 2) Revisión SOTA (state-of-the-art) aplicable a GIMO

Patrones recomendados (industria 2024–2026) para orquestadores multiagente:

- **Single-writer authority + workers stateless**: un único proceso coordina scheduling/estado; los demás son clientes de control-plane.
- **Event-driven core + polling residual mínimo**: reemplazar loops periódicos por eventos (colas internas, pub/sub, notificaciones de transición).
- **Admission control por presupuesto de recursos**: tokens dinámicos CPU/RAM/VRAM, no solo “N concurrent runs”.
- **Ephemeral execution sandboxes** para CI/merge: worktree efímero por run, tests/lint/merge solo ahí.
- **Append-only log + materialized state**: journal inmutable para eventos y proyección de estado para lecturas rápidas.
- **Backpressure explícito y QoS**: prioridad de eventos, coalescing por clave, rate limiting y circuit breaker por subscriber.
- **Reliable IPC** con retries idempotentes + health/readiness + outbox persistente.
- **Observabilidad unificada**: traces/metrics/logs con correlación por `run_id` y `agent_id`.

---

## 3) Arquitectura objetivo (realista, incremental)

### A. Authority plane único
- Introducir `ExecutionAuthority` como único dueño de:
  - `RunWorker` (scheduler + admission),
  - transiciones de estado críticas,
  - dispatch de eventos de runtime.
- MCP/FastAPI pasan a modo client/control API; nunca instancian worker propio.

### B. Runtime bus interno
- Reemplazar polling crítico con `asyncio.Event`/canal interno para:
  - nuevos runs,
  - cambios de estado,
  - handovers.
- Polling solo como watchdog de seguridad (intervalos largos).

### C. Data plane dual
- **Run State Store (canónico):** SQLite WAL (tabla runs, locks, metadata).
- **Run Event Log (append-only):** JSONL o tabla events (inmutable).
- Proyección “run actual” derivada del evento más reciente (materialized view local).

### D. Merge Sandbox
- Worktree efímero por run (`.gimo/worktrees/<run_id>`), limpieza garantizada en `finally` + reconciliador al startup.
- Validación/merge/rollback aislados del root.

### E. Realtime QoS
- Clasificar eventos: `critical`, `state`, `telemetry`, `debug`.
- Backpressure por clase: nunca dropear `critical`; coalesce agresivo en `telemetry`.
- Circuit breaker por subscriber lento.

---

## 4) Plan de ejecución por fases

## P0 (1–2 semanas) — Estabilidad y no-regresión operativa

1. **Unificar autoridad de worker**
   - Quitar `RunWorker` de `mcp_bridge/server.py`.
   - Exponer endpoint/control RPC para que MCP consulte estado sin ejecutar scheduler.
   - Criterio de éxito: un solo loop de ejecución en producción.

2. **Merge gate en worktree sandbox**
   - Crear `GitSandboxService`:
     - `create_ephemeral_worktree(run_id, source_ref, target_ref)`
     - `cleanup_ephemeral_worktree(run_id)`
   - Ejecutar tests/lint/dry-run/merge en sandbox.
   - Criterio: repo raíz nunca cambia durante validación.

3. **Fix de diff git**
   - Cambiar a `git diff --stat <base>..<head>` o `git diff --stat <base> <head>` (sin `--` de paths).
   - Añadir tests de refs reales.

4. **Backpressure robusto realtime v2**
   - Añadir prioridad por evento + coalescing keyed (ej. `run_id+event_type`).
   - Añadir métricas por subscriber (`lag`, `drops`, `disconnect_reason`).

5. **Pool HTTP persistente en providers**
   - `AsyncClient` singleton por adapter/provider con cierre ordenado en shutdown.

## P1 (2–4 semanas) — Escalabilidad y resiliencia

6. **Storage caliente: append-only + estado canónico**
   - Migrar operaciones de run a SQLite WAL.
   - Mantener compatibilidad de lectura con JSON durante transición (dual-read).

7. **ResourceGovernor real**
   - Admission control por presupuesto: CPU, RAM, VRAM y clase de tarea.
   - Policy dinámica: `allow/defer/reject` con razones auditables.

8. **Reconciliador de worktrees/subagentes**
   - Startup GC: listar worktrees activos, comparar inventario, limpiar zombis.
   - Persistir inventario y última reconciliación.

9. **Hardening GICS transport**
   - protocolo request-id + ack + retry idempotente.
   - outbox persistente para comandos críticos.

10. **Pipeline de logs a GICS con retención**
   - raw local -> resumen -> index GICS -> compresión + TTL.

## P2 (4–8 semanas) — Optimización e innovación

11. **Routing VRAM-aware real**
   - thresholds de VRAM libre, util GPU, temperatura; fallback inteligente.

12. **Residency manager de modelos**
   - estados hot/warm/cold + eviction LFU/LRU híbrido con coste de recarga.

13. **Insights causales/temporales**
   - ventanas temporales, correlación run-hardware-model-tool.

14. **CI incremental por paths afectados**
   - pytest/ruff/mypy selectivos por diff + cachés.

15. **Startup lazy + degraded modes**
   - readiness granular por subsistema, no boot monolítico.

---

## 5) Mapa gap -> acción concreta

- Gaps 1,11,28 -> Realtime QoS + circuit breaker + métricas por subscriber.
- Gaps 2,10 -> Authority plane único + entrypoints armonizados.
- Gaps 3,9 -> Merge/worktree sandbox + reconciliador/GC.
- Gaps 4,8,22,25,27 -> separación estado/log, pipeline a GICS, retención TTL.
- Gaps 5,26 -> persistencia de runtime crítico (subagentes, locks, inventory).
- Gaps 6,14,23,24 -> ResourceGovernor + políticas CPU/RAM/VRAM + clasificación de tareas.
- Gap 7 -> event-driven core, reducir polling.
- Gap 12 -> corrección de `git diff` + tests.
- Gap 13 -> HTTP pooling.
- Gap 15 -> LocalModelResidencyManager.
- Gap 16 -> robustecer transporte GICS (retry/ack/idempotencia).
- Gap 17 -> insight avanzado causal.
- Gap 18 -> reconciliación completa de inventario.
- Gap 19 -> lazy init y degraded modes.
- Gaps 20,21 -> pipeline incremental y reducción de subprocess redundantes.

---

## 6) Métricas de éxito (SLO/SLI)

- **Realtime:** p95 fanout < 150ms; drops telemetry permitidos < 1%; drops critical = 0.
- **Worker:** 0 duplicación de ejecución por run_id; cola estable bajo carga sostenida.
- **Merge gate:** 0 mutaciones en repo root durante validación; cleanup 100% de worktrees.
- **Storage:** reducción >60% de write amplification en runs.
- **Provider IO:** reducción p95 latencia de llamadas >15% con pooling.
- **GICS:** tasa de pérdida de comandos críticos = 0 (con outbox+ack).

---

## 7) Riesgos y mitigaciones

- **Migración de storage**: riesgo de compatibilidad.
  - Mitigar con dual-read/dual-write temporal + feature flags.
- **Cambio de authority**: riesgo de regressions en entrypoints.
  - Mitigar con pruebas de contrato por modo (`api`, `mcp`, `hybrid`).
- **QoS realtime**: riesgo de “drop inesperado”.
  - Mitigar con catálogo de eventos críticos/no críticos y tests de invariantes.

---

## 8) Entregables recomendados para el siguiente agente

1. RFC corta: `authority-plane.md`.
2. PR 1 (P0): unificación worker + flag de compatibilidad.
3. PR 2 (P0): merge sandbox + reconciliador de worktrees.
4. PR 3 (P0): fix `git diff` + tests.
5. PR 4 (P0): realtime QoS v2 + métricas.
6. PR 5 (P1): storage append-only + proyección de estado.

