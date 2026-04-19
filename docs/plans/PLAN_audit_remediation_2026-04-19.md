# Plan — Remediación del audit Relaxed-Edison
**Fecha**: 2026-04-19
**Branch objetivo**: `main`
**Filosofía**: AGENTS.md (backend authority first + legacy hunting protocol + "disconnected ≠ dead")

---

## [GOAL]

Eliminar de raíz la causa única de los 7 findings del audit: **las superficies están infiriendo/recalculando lo que el backend ya sabe**. No son 7 bugs — es 1 doctrina violada ("one backend truth, multiple thin clients") manifestada en 7 puntos.

Objetivo terminal: **ninguna superficie puede re-inventar estado autoritativo**. Se logra con 4 palancas de reconexión + 1 palanca de protección.

---

## [INPUT DATA] — Evidencia verificada

| Fuente | Confirmado |
|---|---|
| `merge_gate_service.py:60-67` | `policy_decision = "allow"` en 2 ramas: fail-open real |
| `runtime_policy_service.py:134` | `evaluate_draft_policy()` existe y devuelve `PolicyDecision` con `policy_decision_id`, `decision`, `status_code` — el canónico para F1 |
| `legacy_ui_router.py:52-65` | `/ui/status` computa `status_str = "RUNNING" if is_healthy else "DEGRADED"` localmente |
| `operator_status_service.py:165` | `get_status_snapshot()` es el canónico para F2 |
| `tools/gimo_server/openapi.yaml` | Schema existe; puede generar TS (F3+F4+F5) |
| `notice_policy_service.py:8` | `evaluate_all()` es pura, no publica |
| `notification_service.py:108` | `publish()` existe, recibe `event_type + payload` — la arista faltante de F6 |
| `models/core.py:13-33` | `OpsRunStatus` tiene 20 valores; `types.ts:467` tiene 5 |
| `apps/web/src/lib/entitlement.ts` | Usa `adminDb` (server-side NextJS), no client-side; pero es exclusivo de `apps/web` |

---

## [PLAN]

### Palanca 1 — Fix fail-closed en merge gate (resuelve F1)

**Archivo**: `tools/gimo_server/services/merge_gate_service.py:47-87`

**Cambio**: Sustituir los dos defaults `policy_decision = "allow"` por fail-closed con ruta de recuperación explícita vía `RuntimePolicyService.evaluate_draft_policy()`.

```python
# Antes:
if not policy_decision:
    policy_decision = "allow"   # ← fail-open

# Después:
if not policy_decision:
    # Decisión ausente → re-evaluar contra política viva, no asumir allow.
    try:
        decision = RuntimePolicyService.evaluate_draft_policy(
            path_scope=context.get("path_scope") or [],
            estimated_files_changed=context.get("files_changed"),
            estimated_loc_changed=context.get("loc_changed"),
        )
        policy_decision = decision.decision
        policy_decision_id = decision.policy_decision_id
        OpsService.append_log(
            run_id, level="WARN",
            msg=f"policy_decision absent; re-evaluated: id={policy_decision_id} decision={policy_decision}"
        )
    except Exception as exc:
        OpsService.update_run_status(run_id, "WORKER_CRASHED_RECOVERABLE",
            msg=f"policy re-evaluation failed: {exc}")
        return False
```

La rama sintética `_LOW_RISK_INTENTS` se **conserva como fallback explícito** (no borrada) pero anotada:
```python
# DEPRECATED: synthetic fallback — only for LOW_RISK intents when upstream
# policy gate didn't persist decision. Prefer RuntimePolicyService re-evaluation above.
# Sunset criterion: when pipeline guarantees policy_decision_id in context for 100% of runs.
# Owner: merge_gate team.
```

**Evidencia requerida**:
- Test: `test_merge_gate_fails_closed_on_missing_decision` — run sin `policy_decision` termina en status de bloqueo, no en merge.
- Test: `test_merge_gate_reevaluates_on_missing_decision_id` — verifica que `RuntimePolicyService.evaluate_draft_policy` se llamó.

**Blast radius**: 1 archivo, ~20 líneas. Tests existentes de merge gate (test_merge_gate.py) deben seguir verdes.

---

### Palanca 2 — Contract codegen (resuelve F3 + F4 + F5)

**Problema real**: `types.ts` deriva del backend **a mano**. Cualquier cambio en `OpsRunStatus` se desincroniza silenciosamente. Las 3 findings (drift de tipos, polling sordo, optimistic UI con typos) son síntomas del mismo vacío: no hay pipe mecánico de contrato.

**Cambio**:

1. Añadir dep en `tools/orchestrator_ui/package.json`:
   ```json
   "devDependencies": {
     "openapi-typescript": "^7.4.0"
   }
   ```

2. Script en `package.json`:
   ```json
   "codegen": "openapi-typescript ../gimo_server/openapi.yaml -o src/types/backend-generated.ts",
   "codegen:check": "openapi-typescript ../gimo_server/openapi.yaml -o /tmp/.check.ts && diff /tmp/.check.ts src/types/backend-generated.ts"
   ```

3. `src/types.ts` (existing) **se conserva** para tipos UI-only (view models, ephemeral state). Pero las interfaces que mapean backend payloads se importan del generado:
   ```typescript
   // types.ts (after)
   import type { components } from "./types/backend-generated";
   export type OpsRun = components["schemas"]["OpsRun"];
   export type OpsRunStatus = components["schemas"]["OpsRunStatus"];
   export type OpsDraft = components["schemas"]["OpsDraft"];
   // UI-only types (ViewModels, Zustand slices) permanecen hand-written
   ```

4. CI gate en `.github/workflows/ci.yml`:
   ```yaml
   - name: Contract drift guard
     run: cd tools/orchestrator_ui && npm run codegen:check
   ```

5. Fix de F4 (una línea, después del codegen porque ahora TS exhaustivamente sabe los 20 statuses):
   ```typescript
   // useOpsService.ts — reemplaza la list hardcoded por derivado del tipo
   const ACTIVE_STATUSES: readonly OpsRunStatus[] =
     ['pending', 'running', 'awaiting_subagents', 'awaiting_review',
      'AWAITING_MERGE', 'HUMAN_APPROVAL_REQUIRED'] as const;
   const hasActive = runs.some(r => ACTIVE_STATUSES.includes(r.status));
   ```
   El array es exhaustive-checkable por TS. Si el backend añade un nuevo status activo, se actualiza aquí con un switch exhaustivo.

6. Fix de F5 en `useOpsService.ts` aprove/reject:
   ```typescript
   // Antes: setDrafts(prev => prev.map(d => d.id === id ? { ...d, status: 'approved' } : d));
   // Después: usar la respuesta del servidor
   const { approved, run } = await res.json() as OpsApproveResponse;
   setDrafts(prev => prev.map(d => d.id === id ? { ...d, status: approved.status } : d));
   setApproved(prev => [approved, ...prev]);
   ```

**Evidencia requerida**:
- `npm run codegen && git diff --exit-code` — reproducible.
- CI green con el gate.
- Test e2e: aprobar draft → UI muestra status del servidor (no cliente).

**Blast radius**: `types.ts` refactor, `useOpsService.ts` polling + approve/reject, 1 paquete npm nuevo, 1 paso CI. ~4 archivos.

---

### Palanca 3 — Legacy status delegation (resuelve F2)

**Archivo**: `tools/gimo_server/routers/legacy_ui_router.py:46-65`

**Cambio**: El handler de `/ui/status` se reduce a delegación. **No se borra el endpoint** (tiene callers externos documentados en CLIENT_SURFACES.md).

```python
@router.get("/ui/status", response_model=UiStatusResponse)
def get_ui_status(
    request: Request,
    auth: AuthContext = Depends(require_read_only_access),
    rl: None = Depends(check_rate_limit),
):
    # DEPRECATED: surface ingress. Canonical: /ops/operator/status.
    # Sunset criterion: when all clients migrate to /ops/operator/status.
    # Owner: surface-parity team.
    from tools.gimo_server.services.operator_status_service import OperatorStatusService
    snapshot = OperatorStatusService.get_status_snapshot(request)
    return UiStatusResponse(
        version=__version__,
        uptime_seconds=time.time() - request.app.state.start_time,
        allowlist_count=snapshot.get("allowlist_count", 0),
        last_audit_line=snapshot.get("last_audit_line"),
        service_status=snapshot.get("service_status", "UNKNOWN"),
    )
```

Si `OperatorStatusService.get_status_snapshot` no devuelve los campos necesarios en el shape de `UiStatusResponse`, se **extiende el servicio canónico** (no el router legacy) para cubrir la necesidad.

**Evidencia requerida**:
- Test: `test_ui_status_delegates_to_operator_status_service` — mock del service, verifica delegación.
- Test: respuesta de `/ui/status` tiene mismo shape que antes (compat con UI actual).

**Blast radius**: 1 archivo router + posible extensión pequeña a OperatorStatusService.

---

### Palanca 4 — Service reconnection (resuelve F6)

**Problema**: `NoticePolicyService.evaluate_all()` produce notices pero no notifica. `NotificationService.publish()` existe pero nadie la llama para notices nuevos.

**Cambio**: Localizar el único caller actual de `evaluate_all()` (probablemente `OperatorStatusService`) y encadenarlo con `NotificationService.publish()` para notices que acaben de aparecer (comparando contra el estado previo).

```python
# operator_status_service.py — dentro del método que evalúa notices
new_notices = NoticePolicyService.evaluate_all(context_state)
previous_ids = cls._last_notice_ids  # cache en clase
current_ids = {n["id"] for n in new_notices}
freshly_appeared = current_ids - previous_ids
if freshly_appeared:
    for notice in new_notices:
        if notice["id"] in freshly_appeared:
            asyncio.create_task(
                NotificationService.publish("notice_appeared", notice)
            )
cls._last_notice_ids = current_ids
```

**Evidencia requerida**:
- Test: `test_notice_appears_triggers_notification` — evaluar un context que dispara un notice nuevo, verificar `publish` llamado con el notice.
- Test: `test_existing_notice_no_duplicate_publish` — notice que ya existía no re-publica.

**Blast radius**: 1 método en OperatorStatusService (o donde se llame a evaluate_all), ~10 líneas.

---

### Palanca 5 — Entitlement extraction (resuelve F7)

**Problema**: `apps/web/src/lib/entitlement.ts` tiene lógica de licencia que otras superficies (CLI, MCP) no pueden reusar.

**Cambio (evolutivo, no destructivo)**:

1. Crear `tools/gimo_server/services/entitlement_service.py` portando la lógica de `applyEntitlementDecision`, `setLicenseStatus`, `deactivateActiveActivations`. Almacenamiento: reusar el patrón existente de GIMO (JSON bajo `.orch_data/ops/licenses/`) o mantener Firebase si el backend ya tiene access — esto se decide en Phase 5 tras leer el servicio completo.

2. Añadir endpoints REST en un nuevo `tools/gimo_server/routers/ops/entitlement_router.py`:
   - `POST /ops/entitlement/decide` → aplica `EntitlementDecision`
   - `GET /ops/entitlement/license/{id}` → estado
   - `POST /ops/entitlement/license/{id}/deactivate` → desactiva activaciones

3. Añadir tool MCP correspondiente: `gimo_get_entitlement`, `gimo_apply_entitlement_decision`.

4. `entitlement.ts` **se conserva** pero se vuelve un cliente HTTP thin que llama al backend:
   ```typescript
   export async function applyEntitlementDecision(
       licenseId: string, currentStatus: string | undefined, decision: EntitlementDecision
   ): Promise<void> {
       await fetch(`${BACKEND_URL}/ops/entitlement/decide`, {
           method: "POST",
           headers: { "Authorization": `Bearer ${serverToken()}` },
           body: JSON.stringify({ licenseId, currentStatus, decision })
       });
   }
   ```

**Evidencia requerida**:
- Test unitario del servicio backend.
- Test de integración: `entitlement.ts` → backend → Firestore.
- Test MCP: llamada a `gimo_apply_entitlement_decision` aplica la decisión.

**Blast radius**: 1 servicio nuevo + 1 router + 2 tools MCP + refactor de 1 archivo TS. ~5 archivos. Mayor de los 5 cambios.

---

### Palanca 6 — Anti-drift tests (protección permanente)

**Archivos nuevos**:
- `tests/unit/test_contract_drift.py` — valida que `openapi.yaml` es válido y que `OpsRunStatus` canónico cubre todos los statuses usados en merge_gate/run_worker.
- `tests/unit/test_merge_gate_fail_closed.py` — OWASP ASI02 compliance.
- `tests/unit/test_surface_authority.py` — grep-based test: detecta nuevos endpoints `/ui/*` que no deleguen a servicios canónicos (regla contra regresión).

**CI gate** adicional:
- `npm run codegen:check` en orchestrator_ui CI (ya mencionado).
- Python: `pytest tests/unit/test_contract_drift.py tests/unit/test_merge_gate_fail_closed.py` en pre-commit.

---

## [ORDEN DE EJECUCIÓN]

Ordenado por ratio de impacto/riesgo y por dependencia:

| # | Palanca | Finding(s) | Esfuerzo | Riesgo | Dependencia |
|---|---|---|---|---|---|
| 0 | Merge gate fail-closed | F1 | 30 min | Bajo | Ninguna. Va primero por ser el único vector de seguridad real |
| 1 | Contract codegen | F3, F4, F5 | 2-3h | Medio (cambia build pipeline) | Ninguna |
| 2 | /ui/status delegation | F2 | 30 min | Bajo | Ninguna |
| 3 | NoticePolicy → NotificationService | F6 | 45 min | Bajo | Ninguna |
| 4 | Entitlement extraction | F7 | 3-4h | Medio (toca web + backend + MCP) | Ninguna estrictamente, pero último por volumen |
| 5 | Anti-drift tests | — | 1-2h | Bajo | Debe correr al final, después de todas las palancas |

**Total estimado**: ~8-10h de trabajo focalizado. Commits separados por palanca para auditabilidad.

---

## [PLAN QUALITY SELF-CHECK] (AGENTS.md §Plan Quality Standard)

1. **Permanence**: ✓ Cada palanca enforece la doctrina permanente de AGENTS.md. El codegen + CI gate previene que la deuda de tipos reaparezca. Fail-closed es invariante OWASP ASI02.
2. **Completeness**: ✓ Cubre los 7 findings + anti-drift para los que no existían todavía.
3. **Foresight**: ✓ Contract codegen previene el próximo drift (cuando se añada un status nuevo). Fail-closed previene el próximo bypass (cuando se añada un nuevo stage upstream que pueda crashear).
4. **Potency**: ✓ Codegen + fail-closed + delegation son invariantes estructurales, no parches.
5. **Innovation**: — No hay innovación real; el estado del arte es el patrón que ya usa el MCP bridge (ver memoria: "schema drift guard at boot"). Esto lo replica en el frontend.
6. **Elegance**: ✓ Un concepto: "backend owns truth, clients codegenerate or delegate". Las 6 palancas son aplicaciones del mismo concepto.
7. **Lightness**: ✓ 0 abstracciones nuevas. 1 paquete npm nuevo (openapi-typescript, pin tight). ~12 archivos tocados en total.
8. **Multiplicity**: ✓ Codegen resuelve F3+F4+F5 con un cambio. Fail-closed pattern es el mismo que exige OWASP ASI02 → armoniza con invariantes existentes.
9. **Unification**: ✓ Esto es literalmente el objetivo — una sola fuente de verdad (backend), clientes thin, contract generado.

---

## [LEGACY HUNTING PROTOCOL] (AGENTS.md §12)

Durante ejecución, cada palanca escanea blast radius:

- **Palanca 1**: Buscar otros `if not X: X = "allow"` en gate stages → si existen, anotar y remediar en el mismo commit.
- **Palanca 2**: Buscar otras definiciones hand-written de types que sombreen el schema backend → reemplazar por generated.
- **Palanca 3**: Buscar otros handlers `/ui/*` que recomputen estado → candidatos futuros de delegation.
- **Palanca 4**: Buscar otros puntos donde `NoticePolicyService.evaluate_all` pueda llamarse sin notificar → documentar como follow-ups.

**Regla**: nada se borra sin reemplazo canónico identificado (principio "disconnected ≠ dead"). El endpoint `/ui/status`, `entitlement.ts`, la rama LOW_RISK de merge gate — todos se **reconectan** via delegación o thin-client, no se amputan.

---

## [RIESGOS]

1. **Palanca 2 (codegen)**: si `openapi.yaml` tiene holes semánticos (ej. schemas incompletos, campos marcados `additionalProperties: true`), el TS generado será pobre. Mitigación: validación previa del schema como primer paso.
2. **Palanca 1 (merge gate)**: cambiar fail-open a fail-closed puede bloquear runs en producción que antes pasaban por azar. Mitigación: correr con shadow-mode (log what WOULD have been blocked) durante 1 ciclo antes del switch real.
3. **Palanca 5 (entitlement)**: mover a backend implica acceso a Firestore desde Python. Si el backend no tiene credenciales Firebase configuradas, requiere setup de `google-cloud-firestore`. Fallback: empezar con JSON storage local y migrar a Firestore en follow-up.
4. **Tests**: ~6-10 tests nuevos. Ninguno debería ser flaky si siguen patrones del repo (no `importlib.reload`, no `TestClient` context-manager).

---

## [STATUS]

`NOT_STARTED` — plan esperando aprobación.

Próximo paso tras aprobación: ejecutar Palanca 0 (merge gate fail-closed) como primer commit, verificar tests verdes, seguir con Palanca 1 (codegen).
