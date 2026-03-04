# Checklist ACL y Hardening (Fase 2)

## ACL por ruta
- [x] Baseline/runtime: solo lectura para usuario de servicio.
- [x] Repo target: lectura/escritura controlada.
- [x] C:/gimo_work/worktrees: lectura/escritura.
- [x] C:/gimo_work/logs: lectura/escritura.
- [x] C:/gimo_work/state: lectura/escritura.

## Hardening mínimo
- [x] Servicio no interactivo.
- [x] Inicio automático + restart on failure.
- [x] Separación de logs (app/audit/error).
- [x] Rotación de logs y límite de crecimiento.
- [x] No secrets en logs.

## Verificación operativa
- [x] `sc query GIMO-Orchestrator`
- [x] `sc start GIMO-Orchestrator`
- [x] `sc stop GIMO-Orchestrator`
- [x] Reinicio de host conserva estado y healthcheck OK.
